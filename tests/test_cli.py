"""Smoke tests for the cme CLI."""

from __future__ import annotations

from click.testing import CliRunner

from cme.cli import main


def test_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "marketplace health" in result.output


def test_routing_no_default_plugins() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["routing"])
    assert result.exit_code != 0


def test_overlap_no_default_plugins() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["overlap"])
    assert result.exit_code == 1
