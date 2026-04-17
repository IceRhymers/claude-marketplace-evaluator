"""Tests for coverage check."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cme.coverage import check_coverage


def _make_skill(
    base: Path,
    plugin: str,
    skill: str,
    *,
    with_evals: bool = True,
    malformed: bool = False,
) -> None:
    skill_dir = base / plugin / "skills" / skill
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {skill}\n---")
    if with_evals:
        evals_dir = skill_dir / "evals"
        evals_dir.mkdir()
        if malformed:
            (evals_dir / "evals.json").write_text("not json")
        else:
            (evals_dir / "evals.json").write_text(
                json.dumps([{"query": "do X", "should_trigger": True}])
            )


def test_full_coverage(tmp_path: Path) -> None:
    _make_skill(tmp_path, "p", "skill-a")
    _make_skill(tmp_path, "p", "skill-b")
    report, rc = check_coverage(tmp_path, 100.0)
    assert rc == 0
    assert report.coverage_pct == 100.0
    assert report.skills_missing_evals == []


def test_missing_evals_fails_threshold(tmp_path: Path) -> None:
    _make_skill(tmp_path, "p", "skill-a")
    _make_skill(tmp_path, "p", "skill-b", with_evals=False)
    report, rc = check_coverage(tmp_path, 100.0)
    assert rc == 1
    assert len(report.skills_missing_evals) == 1


def test_malformed_evals_flagged(tmp_path: Path) -> None:
    _make_skill(tmp_path, "p", "skill-a", malformed=True)
    report, rc = check_coverage(tmp_path, 0.0)  # 0% threshold — don't fail on coverage
    assert len(report.skills_with_malformed_evals) == 1


def test_zero_skills_is_100pct(tmp_path: Path) -> None:
    report, rc = check_coverage(tmp_path, 100.0)
    assert report.coverage_pct == 100.0
    assert rc == 0


def test_partial_coverage_below_threshold(tmp_path: Path) -> None:
    _make_skill(tmp_path, "p", "a")
    _make_skill(tmp_path, "p", "b", with_evals=False)
    _make_skill(tmp_path, "p", "c", with_evals=False)
    report, rc = check_coverage(tmp_path, 90.0)
    assert rc == 1
    assert report.coverage_pct == pytest.approx(33.33, rel=0.01)
