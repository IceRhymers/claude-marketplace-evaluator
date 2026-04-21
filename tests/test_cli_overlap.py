"""CLI tests for cme overlap command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from cme.cli import main
from cme.models import OverlapFinding, OverlapReport


def _make_skill(base: Path, plugin: str, skill: str) -> None:
    skill_dir = base / plugin / "skills" / skill
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {skill}\n---\nDoes {skill} things."
    )
    # Ensure .claude-plugin/plugin.json marker exists for discover_plugins
    marker_dir = base / plugin / ".claude-plugin"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker_file = marker_dir / "plugin.json"
    if not marker_file.exists():
        marker_file.write_text(f'{{"name": "{plugin}", "skills": "./skills/"}}')


def test_overlap_missing_plugins_dir() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["overlap", "--plugins-dir", "/nonexistent"])
    assert result.exit_code == 1


def test_overlap_no_collisions(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    _make_skill(plugins, "p", "skill-a")
    _make_skill(plugins, "p", "skill-b")

    mock_report = OverlapReport(
        timestamp="2026-01-01T00:00:00+00:00",
        model_used="claude-sonnet-4-5",
        mode="full-scan",
        total_skills_analyzed=2,
        new_skills_checked=0,
        total_findings=0,
        findings=[],
    )

    output = tmp_path / "report.json"
    with patch("cme.overlap.detect_overlap", return_value=mock_report):
        runner = CliRunner()
        result = runner.invoke(
            main, ["overlap", "--plugins-dir", str(plugins), "--output", str(output)]
        )

    assert result.exit_code == 0
    assert "PASSED" in result.output


def test_overlap_with_findings_exits_nonzero(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    _make_skill(plugins, "p", "skill-a")
    _make_skill(plugins, "p", "skill-b")

    finding = OverlapFinding(
        skill_a="plugins/p/skills/skill-a",
        skill_b="plugins/p/skills/skill-b",
        functional_summary="Both skills do the same thing.",
        shared_tools=["Bash"],
        severity="high",
        recommendation="Merge into one skill.",
        explanation="They are duplicates.",
    )
    mock_report = OverlapReport(
        timestamp="2026-01-01T00:00:00+00:00",
        model_used="claude-sonnet-4-5",
        mode="full-scan",
        total_skills_analyzed=2,
        new_skills_checked=0,
        total_findings=1,
        findings=[finding],
    )

    output = tmp_path / "report.json"
    with patch("cme.overlap.detect_overlap", return_value=mock_report):
        runner = CliRunner()
        result = runner.invoke(
            main, ["overlap", "--plugins-dir", str(plugins), "--output", str(output)]
        )

    assert result.exit_code == 1
    assert "FAILED" in result.output
