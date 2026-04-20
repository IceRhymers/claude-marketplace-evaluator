"""CLI tests for cme overlap command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from cme.cli import main
from cme.models import OverlapReport


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
        total_skills_analyzed=2,
        total_collisions=0,
        collisions=[],
    )

    output = tmp_path / "report.json"
    with patch("cme.overlap.detect_overlap", return_value=mock_report):
        runner = CliRunner()
        result = runner.invoke(
            main, ["overlap", "--plugins-dir", str(plugins), "--output", str(output)]
        )

    assert result.exit_code == 0
    assert "PASSED" in result.output


def test_overlap_with_collisions_exits_nonzero(tmp_path: Path) -> None:
    from cme.models import CollisionPair

    plugins = tmp_path / "plugins"
    _make_skill(plugins, "p", "skill-a")
    _make_skill(plugins, "p", "skill-b")

    collision = CollisionPair(
        skill_a="plugins/p/skills/skill-a",
        skill_b="plugins/p/skills/skill-b",
        overlapping_triggers=["do the thing"],
        description_excerpts=["Does skill-a things."],
        severity="high",
    )
    mock_report = OverlapReport(
        timestamp="2026-01-01T00:00:00+00:00",
        model_used="claude-sonnet-4-5",
        total_skills_analyzed=2,
        total_collisions=1,
        collisions=[collision],
    )

    output = tmp_path / "report.json"
    with patch("cme.overlap.detect_overlap", return_value=mock_report):
        runner = CliRunner()
        result = runner.invoke(
            main, ["overlap", "--plugins-dir", str(plugins), "--output", str(output)]
        )

    assert result.exit_code == 1
    assert "FAILED" in result.output
