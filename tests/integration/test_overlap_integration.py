"""Integration tests for cme overlap against example_plugins/ fixtures.

The LLM call is controlled by CME_SKIP_LLM=1 env var (returns empty collisions)
for fast, API-key-free runs in standard CI. Unset it for live LLM testing.

Run with: make test-integration
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from cme.cli import main

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE_PLUGINS = REPO_ROOT / "example_plugins"

_HAS_ANTHROPIC_AUTH = bool(
    os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
)


def _mock_no_collisions() -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = "report_collisions"
    block.input = {"collisions": []}
    response = MagicMock()
    response.content = [block]
    client = MagicMock()
    client.messages.create.return_value = response
    return client


def _mock_with_collision() -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = "report_collisions"
    block.input = {
        "collisions": [
            {
                "skill_a": "collision-plugin/skills/create-pr",
                "skill_b": "collision-plugin/skills/submit-pr",
                "overlapping_triggers": ["Create a pull request", "Submit a PR"],
                "description_excerpts": [
                    "Create a new GitHub pull request",
                    "Submit a pull request on GitHub",
                ],
                "severity": "high",
            }
        ]
    }
    response = MagicMock()
    response.content = [block]
    client = MagicMock()
    client.messages.create.return_value = response
    return client


@pytest.mark.integration
class TestOverlapIntegration:
    def test_dev_tools_no_collisions(self, tmp_path: Path) -> None:
        """dev-tools has 3 distinct skills — no collisions expected."""
        output = tmp_path / "report.json"
        with patch(
            "cme.overlap.anthropic.Anthropic", return_value=_mock_no_collisions()
        ):
            runner = CliRunner()
            result = runner.invoke(
                main,
                [
                    "overlap",
                    "--plugins-dir",
                    str(EXAMPLE_PLUGINS / "dev-tools"),
                    "--output",
                    str(output),
                ],
            )
        logger.info("exit_code=%s\n%s", result.exit_code, result.output)
        assert result.exit_code == 0, result.output
        assert "PASSED" in result.output
        data = json.loads(output.read_text())
        logger.info("report=%s", json.dumps(data, indent=2))
        assert data["total_collisions"] == 0

    def test_collision_plugin_detected(self, tmp_path: Path) -> None:
        """collision-plugin has create-pr and submit-pr — should detect collision."""
        output = tmp_path / "report.json"
        with patch(
            "cme.overlap.anthropic.Anthropic", return_value=_mock_with_collision()
        ):
            runner = CliRunner()
            result = runner.invoke(
                main,
                [
                    "overlap",
                    "--plugins-dir",
                    str(EXAMPLE_PLUGINS / "collision-plugin"),
                    "--output",
                    str(output),
                ],
            )
        logger.info("exit_code=%s\n%s", result.exit_code, result.output)
        assert result.exit_code == 1
        assert "FAILED" in result.output
        data = json.loads(output.read_text())
        logger.info("report=%s", json.dumps(data, indent=2))
        assert data["total_collisions"] == 1
        collision = data["collisions"][0]
        assert (
            "create-pr" in collision["skill_a"] or "create-pr" in collision["skill_b"]
        )
        assert collision["severity"] == "high"

    def test_overlap_report_json_schema(self, tmp_path: Path) -> None:
        """Verify JSON report has all required top-level fields."""
        output = tmp_path / "report.json"
        with patch(
            "cme.overlap.anthropic.Anthropic", return_value=_mock_no_collisions()
        ):
            runner = CliRunner()
            result = runner.invoke(
                main,
                [
                    "overlap",
                    "--plugins-dir",
                    str(EXAMPLE_PLUGINS / "dev-tools"),
                    "--output",
                    str(output),
                ],
            )
        logger.info("exit_code=%s\n%s", result.exit_code, result.output)
        data = json.loads(output.read_text())
        logger.info("report=%s", json.dumps(data, indent=2))
        assert "timestamp" in data
        assert "model_used" in data
        assert "total_skills_analyzed" in data
        assert "total_collisions" in data
        assert "collisions" in data
        assert data["total_skills_analyzed"] == 3  # dev-tools has 3 skills

    def test_overlap_counts_all_skills(self, tmp_path: Path) -> None:
        """Skills without evals are still counted in total_skills_analyzed."""
        output = tmp_path / "report.json"
        with patch(
            "cme.overlap.anthropic.Anthropic", return_value=_mock_no_collisions()
        ):
            runner = CliRunner()
            result = runner.invoke(
                main,
                [
                    "overlap",
                    "--plugins-dir",
                    str(EXAMPLE_PLUGINS / "incomplete-plugin"),
                    "--output",
                    str(output),
                ],
            )
        logger.info("exit_code=%s\n%s", result.exit_code, result.output)
        data = json.loads(output.read_text())
        logger.info("report=%s", json.dumps(data, indent=2))
        # incomplete-plugin has 4 skills — all counted, not just those with evals
        assert data["total_skills_analyzed"] == 4


@pytest.mark.integration
@pytest.mark.skipif(
    not _HAS_ANTHROPIC_AUTH,
    reason="Live overlap detection requires ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN",
)
class TestLiveOverlap:
    """Real end-to-end overlap detection — hits the Anthropic API, no mocks.

    Slow and costs tokens. Skipped automatically without auth.
    """

    def _run_overlap(self, plugin: str, tmp_path: Path) -> tuple[int, str, dict]:
        output = tmp_path / "report.json"
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "overlap",
                "--plugins-dir",
                str(EXAMPLE_PLUGINS / plugin),
                "--output",
                str(output),
            ],
        )
        data = json.loads(output.read_text())
        logger.info(
            "[%s] exit_code=%s output=%s\nreport=%s",
            plugin,
            result.exit_code,
            result.output,
            json.dumps(data, indent=2),
        )
        return result.exit_code, result.output, data

    def test_dev_tools_no_collisions(self, tmp_path: Path) -> None:
        """dev-tools has 3 clearly distinct skills — model should find 0 collisions."""
        exit_code, _output, data = self._run_overlap("dev-tools", tmp_path)
        assert exit_code == 0
        assert data["total_skills_analyzed"] == 3
        assert data["total_collisions"] == 0

    def test_collision_plugin_detected(self, tmp_path: Path) -> None:
        """collision-plugin has create-pr + submit-pr — model should flag the overlap."""
        exit_code, output, data = self._run_overlap("collision-plugin", tmp_path)
        assert exit_code == 1, output
        assert data["total_skills_analyzed"] == 2
        assert data["total_collisions"] >= 1
        paths = {c["skill_a"] for c in data["collisions"]} | {
            c["skill_b"] for c in data["collisions"]
        }
        assert any("create-pr" in p for p in paths)
        assert any("submit-pr" in p for p in paths)
