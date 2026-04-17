"""Tests for routing eval runner logic (unit — no Agent SDK calls)."""

from __future__ import annotations

from cme.models import TestCase
from cme.runner import _check_pass, skill_matches


def test_skill_matches_exact() -> None:
    assert skill_matches("my-skill", {"my-skill"})


def test_skill_matches_prefixed() -> None:
    assert skill_matches("my-skill", {"plugin:my-skill"})


def test_skill_matches_expected_prefixed() -> None:
    assert skill_matches("plugin:my-skill", {"my-skill"})


def test_skill_no_match() -> None:
    assert not skill_matches("other-skill", {"my-skill"})


def test_check_pass_single_skill() -> None:
    tc = TestCase(name="x", prompt="p", expected_skill="my-skill")
    assert _check_pass(["my-skill"], tc)


def test_check_pass_single_skill_not_yet() -> None:
    tc = TestCase(name="x", prompt="p", expected_skill="my-skill")
    assert not _check_pass([], tc)


def test_check_pass_skills_and_logic() -> None:
    tc = TestCase(name="x", prompt="p", expected_skills=["a", "b"])
    assert not _check_pass(["a"], tc)
    assert _check_pass(["a", "b"], tc)


def test_check_pass_skills_or_logic() -> None:
    tc = TestCase(name="x", prompt="p", expected_skill_one_of=["a", "b"])
    assert _check_pass(["a"], tc)
    assert _check_pass(["b"], tc)


def test_check_pass_no_expected_always_false() -> None:
    tc = TestCase(name="x", prompt="p")
    assert not _check_pass(["anything"], tc)
