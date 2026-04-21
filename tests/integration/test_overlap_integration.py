"""Integration tests for cme overlap against example_plugins/ fixtures.

The LLM call is controlled by CME_SKIP_LLM=1 env var (returns empty findings)
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


def _mock_no_findings() -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = "report_findings"
    block.input = {"findings": []}
    response = MagicMock()
    response.content = [block]
    client = MagicMock()
    client.messages.create.return_value = response
    return client


def _mock_with_finding() -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = "report_findings"
    block.input = {
        "findings": [
            {
                "skill_a": "collision-plugin/skills/create-pr",
                "skill_b": "collision-plugin/skills/submit-pr",
                "functional_summary": "Both skills create GitHub pull requests from the current branch.",
                "shared_tools": ["Bash", "Read"],
                "severity": "high",
                "recommendation": "Merge into a single create-pr skill.",
                "explanation": "These skills perform identical actions — pushing a branch and opening a PR via gh CLI. A user would get the same result from either skill.",
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
    def test_dev_tools_no_findings(self, tmp_path: Path) -> None:
        """dev-tools has 3 distinct skills — no findings expected."""
        output = tmp_path / "report.json"
        with patch("cme.overlap.anthropic.Anthropic", return_value=_mock_no_findings()):
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
        assert data["total_findings"] == 0

    def test_collision_plugin_detected(self, tmp_path: Path) -> None:
        """collision-plugin has create-pr and submit-pr — should detect overlap."""
        output = tmp_path / "report.json"
        with patch(
            "cme.overlap.anthropic.Anthropic", return_value=_mock_with_finding()
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
        assert data["total_findings"] == 1
        finding = data["findings"][0]
        assert "create-pr" in finding["skill_a"] or "create-pr" in finding["skill_b"]
        assert finding["severity"] == "high"

    def test_overlap_report_json_schema(self, tmp_path: Path) -> None:
        """Verify JSON report has all required top-level fields."""
        output = tmp_path / "report.json"
        with patch("cme.overlap.anthropic.Anthropic", return_value=_mock_no_findings()):
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
        assert "mode" in data
        assert "total_skills_analyzed" in data
        assert "total_findings" in data
        assert "findings" in data
        assert "new_skills_checked" in data
        assert data["total_skills_analyzed"] == 3  # dev-tools has 3 skills

    def test_overlap_counts_all_skills(self, tmp_path: Path) -> None:
        """Skills without evals are still counted in total_skills_analyzed."""
        output = tmp_path / "report.json"
        with patch("cme.overlap.anthropic.Anthropic", return_value=_mock_no_findings()):
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

    def test_format_github_output(self, tmp_path: Path) -> None:
        """--format github prints markdown to stdout."""
        output = tmp_path / "report.json"
        with patch(
            "cme.overlap.anthropic.Anthropic", return_value=_mock_with_finding()
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
                    "--format",
                    "github",
                ],
            )
        assert "## Skill Overlap Report" in result.output
        assert "| Severity |" in result.output

    def test_new_skill_flag(self, tmp_path: Path) -> None:
        """--new-skill enables PR-aware mode."""
        output = tmp_path / "report.json"
        skill_dir = EXAMPLE_PLUGINS / "collision-plugin" / "skills" / "create-pr"
        with patch("cme.overlap.anthropic.Anthropic", return_value=_mock_no_findings()):
            runner = CliRunner()
            runner.invoke(
                main,
                [
                    "overlap",
                    "--plugins-dir",
                    str(EXAMPLE_PLUGINS / "collision-plugin"),
                    "--output",
                    str(output),
                    "--new-skill",
                    str(skill_dir),
                ],
            )
        data = json.loads(output.read_text())
        assert data["mode"] == "pr-aware"
        assert data["new_skills_checked"] == 1


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

    def test_dev_tools_no_findings(self, tmp_path: Path) -> None:
        """dev-tools has 3 clearly distinct skills — model should find 0 findings."""
        exit_code, _output, data = self._run_overlap("dev-tools", tmp_path)
        assert exit_code == 0
        assert data["total_skills_analyzed"] == 3
        assert data["total_findings"] == 0

    def test_collision_plugin_detected(self, tmp_path: Path) -> None:
        """collision-plugin has create-pr + submit-pr — model should flag the overlap."""
        exit_code, output, data = self._run_overlap("collision-plugin", tmp_path)
        assert exit_code == 1, output
        assert data["total_skills_analyzed"] == 2
        assert data["total_findings"] >= 1
        paths = {f["skill_a"] for f in data["findings"]} | {
            f["skill_b"] for f in data["findings"]
        }
        assert any("create-pr" in p for p in paths)
        assert any("submit-pr" in p for p in paths)
