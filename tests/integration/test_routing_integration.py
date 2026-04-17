"""Integration tests for cme routing against example_plugins/ fixtures.

These tests invoke the CLI against real fixture files (no mocking).
The routing eval runner (step 3) is skipped by passing --threshold 0
to avoid requiring a live Claude API key in CI.

Run with: make test-integration
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from cme.cli import main

# Resolve example_plugins/ relative to repo root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE_PLUGINS = REPO_ROOT / "example_plugins"


@pytest.mark.integration
class TestRoutingCoverage:
    def test_healthy_plugin_full_coverage(self) -> None:
        """dev-tools has 3 skills all with evals — should pass at 100%."""
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "routing",
                "--plugins-dir",
                str(EXAMPLE_PLUGINS / "dev-tools"),
                "--coverage-threshold",
                "100",
                "--threshold",
                "0",  # skip routing eval pass rate
            ],
        )
        assert result.exit_code == 0, result.output

    def test_incomplete_plugin_fails_at_100_threshold(self) -> None:
        """incomplete-plugin has 2/4 skills without evals — fails at 100%."""
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "routing",
                "--plugins-dir",
                str(EXAMPLE_PLUGINS / "incomplete-plugin"),
                "--coverage-threshold",
                "100",
                "--threshold",
                "0",
            ],
        )
        assert result.exit_code == 1
        # Should name the missing skills
        assert "rollback-deploy" in result.output or "lint-code" in result.output

    def test_incomplete_plugin_passes_at_50_threshold(self) -> None:
        """incomplete-plugin has 50% coverage — passes at 50% threshold."""
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "routing",
                "--plugins-dir",
                str(EXAMPLE_PLUGINS / "incomplete-plugin"),
                "--coverage-threshold",
                "50",
                "--threshold",
                "0",
            ],
        )
        assert result.exit_code == 0, result.output

    def test_incomplete_plugin_fails_at_75_threshold(self) -> None:
        """50% coverage < 75% threshold — should fail."""
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "routing",
                "--plugins-dir",
                str(EXAMPLE_PLUGINS / "incomplete-plugin"),
                "--coverage-threshold",
                "75",
                "--threshold",
                "0",
            ],
        )
        assert result.exit_code == 1

    def test_collision_plugin_full_coverage(self) -> None:
        """collision-plugin has 2/2 skills with evals — 100% coverage."""
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "routing",
                "--plugins-dir",
                str(EXAMPLE_PLUGINS / "collision-plugin"),
                "--coverage-threshold",
                "100",
                "--threshold",
                "0",
            ],
        )
        assert result.exit_code == 0, result.output
