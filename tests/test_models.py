"""Tests for cme data models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cme.models import CoverageReport, EvalsFile, TestCase, TestResult


def test_evals_file_valid() -> None:
    ef = EvalsFile(entries=[{"query": "do X", "should_trigger": True}])
    assert len(ef.entries) == 1


def test_evals_file_empty_raises() -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        EvalsFile(entries=[])


def test_evals_file_positive_entries() -> None:
    ef = EvalsFile(
        entries=[
            {"query": "do X", "should_trigger": True},
            {"query": "don't do X", "should_trigger": False},
        ]
    )
    assert len(ef.positive_entries) == 1
    assert ef.positive_entries[0].query == "do X"


def test_coverage_report_pct() -> None:
    r = CoverageReport(
        total_skills=4,
        skills_with_evals=3,
        skills_missing_evals=["a"],
        skills_with_malformed_evals=[],
    )
    assert r.coverage_pct == 75.0


def test_coverage_report_pct_zero_skills() -> None:
    r = CoverageReport(
        total_skills=0,
        skills_with_evals=0,
        skills_missing_evals=[],
        skills_with_malformed_evals=[],
    )
    assert r.coverage_pct == 100.0


def test_test_case_defaults() -> None:
    tc = TestCase(name="x", prompt="do X", expected_skill="my-skill")
    assert tc.max_turns == 5
    assert tc.model is None


def test_test_result_fields() -> None:
    tr = TestResult(name="x", passed=True, expected="my-skill", actual="my-skill")
    assert tr.passed is True
