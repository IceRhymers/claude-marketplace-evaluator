"""CLI integration tests for cme routing command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from cme.cli import main


def _make_plugin_marker(base: Path, plugin: str) -> None:
    marker_dir = base / plugin / ".claude-plugin"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker = marker_dir / "plugin.json"
    if not marker.exists():
        marker.write_text(json.dumps({"name": plugin, "skills": "./skills/"}))


def _make_plugin(base: Path, plugin: str, skill: str) -> None:
    _make_plugin_marker(base, plugin)
    skill_dir = base / plugin / "skills" / skill
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {skill}\n---")
    evals_dir = skill_dir / "evals"
    evals_dir.mkdir()
    (evals_dir / "evals.json").write_text(
        json.dumps(
            [
                {"query": "do the thing with " + skill, "should_trigger": True},
            ]
        )
    )


def test_routing_no_plugins_dir() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["routing", "--plugins-dir", "/nonexistent"])
    assert result.exit_code != 0


def test_routing_empty_plugins_dir(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    # No plugin markers = sys.exit(1)
    runner = CliRunner()
    result = runner.invoke(main, ["routing", "--plugins-dir", str(plugins)])
    assert result.exit_code == 1


def test_routing_missing_evals_fails_coverage(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    _make_plugin_marker(plugins, "p")
    skill_dir = plugins / "p" / "skills" / "s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: s\n---")
    # No evals.json

    runner = CliRunner()
    result = runner.invoke(main, ["routing", "--plugins-dir", str(plugins)])
    assert result.exit_code == 1
