"""Data models for cme routing pipeline."""

from __future__ import annotations

from pydantic import BaseModel, field_validator


class EvalEntry(BaseModel):
    """Single entry in a skill's evals.json."""

    query: str
    should_trigger: bool


class EvalsFile(BaseModel):
    """Validated evals.json contents."""

    entries: list[EvalEntry]

    @field_validator("entries")
    @classmethod
    def must_have_entries(cls, v: list[EvalEntry]) -> list[EvalEntry]:
        if not v:
            raise ValueError("evals.json must not be empty")
        return v

    @property
    def positive_entries(self) -> list[EvalEntry]:
        return [e for e in self.entries if e.should_trigger]


class TestCase(BaseModel):
    """A routing test case (loaded from YAML)."""

    name: str
    prompt: str
    expected_skill: str | None = None
    expected_skills: list[str] | None = None
    expected_skill_one_of: list[str] | None = None
    max_turns: int | None = None
    model: str | None = None


class TestResult(BaseModel):
    """Result of a single routing eval."""

    name: str
    passed: bool
    expected: str
    actual: str | None = None
    error: str | None = None


class CoverageReport(BaseModel):
    """Coverage check results."""

    total_skills: int
    skills_with_evals: int
    skills_missing_evals: list[str]
    skills_with_malformed_evals: list[str]

    @property
    def coverage_pct(self) -> float:
        if self.total_skills == 0:
            return 100.0
        return self.skills_with_evals / self.total_skills * 100


class CollisionPair(BaseModel):
    """A detected semantic collision between two skills."""

    skill_a: str  # relative path, e.g. "plugins/p/skills/a"
    skill_b: str
    overlapping_triggers: list[str]
    description_excerpts: list[str]
    severity: str  # "high" | "medium" | "low"


class OverlapReport(BaseModel):
    """Full overlap detection report."""

    timestamp: str
    model_used: str
    total_skills_analyzed: int
    total_collisions: int
    collisions: list[CollisionPair]
