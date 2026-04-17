"""Tests for --max-turns flag and per-test max_turns override."""

from __future__ import annotations

from cme.models import TestCase


def test_test_case_max_turns_defaults_to_none() -> None:
    tc = TestCase(name="x", prompt="do X", expected_skill="my-skill")
    assert tc.max_turns is None


def test_test_case_max_turns_override() -> None:
    """When test.max_turns is set, it should be used over the CLI default."""
    tc = TestCase(name="x", prompt="do X", expected_skill="s", max_turns=3)
    cli_default = 5
    effective = tc.max_turns if tc.max_turns is not None else cli_default
    assert effective == 3


def test_test_case_max_turns_none_uses_cli_default() -> None:
    """When test.max_turns is None, the CLI max_turns is used."""
    tc = TestCase(name="x", prompt="do X", expected_skill="s")
    cli_default = 10
    effective = tc.max_turns if tc.max_turns is not None else cli_default
    assert effective == 10
