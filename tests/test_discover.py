"""Tests for plugin discovery via .claude-plugin/plugin.json markers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cme.discover import discover_plugins


def _make_marker(plugin_dir: Path, name: str, skills: str = "./skills/") -> None:
    marker_dir = plugin_dir / ".claude-plugin"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / "plugin.json").write_text(
        json.dumps({"name": name, "skills": skills})
    )


def test_discover_single_plugin_at_root(tmp_path: Path) -> None:
    """Single plugin layout: root/.claude-plugin/plugin.json."""
    _make_marker(tmp_path, "my-plugin")
    plugins = discover_plugins(tmp_path)
    assert len(plugins) == 1
    assert plugins[0].name == "my-plugin"
    assert plugins[0].root_dir == tmp_path.resolve()
    assert plugins[0].skills_dir == (tmp_path / "skills").resolve()


def test_discover_multiple_plugins_marketplace(tmp_path: Path) -> None:
    """Marketplace layout: root/plugin-a/.claude-plugin/plugin.json."""
    _make_marker(tmp_path / "plugin-a", "plugin-a")
    _make_marker(tmp_path / "plugin-b", "plugin-b")
    plugins = discover_plugins(tmp_path)
    assert len(plugins) == 2
    names = {p.name for p in plugins}
    assert names == {"plugin-a", "plugin-b"}


def test_discover_reads_skills_field(tmp_path: Path) -> None:
    """The skills field in plugin.json is used to resolve skills_dir."""
    _make_marker(tmp_path / "my-plugin", "my-plugin", skills="./custom-skills/")
    plugins = discover_plugins(tmp_path)
    assert len(plugins) == 1
    assert plugins[0].skills_dir == (tmp_path / "my-plugin" / "custom-skills").resolve()


def test_discover_defaults_skills_field(tmp_path: Path) -> None:
    """When skills is not in plugin.json, default to ./skills/."""
    marker_dir = tmp_path / ".claude-plugin"
    marker_dir.mkdir(parents=True)
    (marker_dir / "plugin.json").write_text(json.dumps({"name": "minimal"}))
    plugins = discover_plugins(tmp_path)
    assert len(plugins) == 1
    assert plugins[0].skills_dir == (tmp_path / "skills").resolve()


def test_discover_no_markers_exits(tmp_path: Path) -> None:
    """sys.exit(1) when no .claude-plugin/plugin.json found."""
    with pytest.raises(SystemExit) as exc_info:
        discover_plugins(tmp_path)
    assert exc_info.value.code == 1


def test_discover_name_falls_back_to_dir_name(tmp_path: Path) -> None:
    """When name is missing from plugin.json, use the directory name."""
    marker_dir = tmp_path / "my-dir" / ".claude-plugin"
    marker_dir.mkdir(parents=True)
    (marker_dir / "plugin.json").write_text(json.dumps({"skills": "./skills/"}))
    plugins = discover_plugins(tmp_path)
    assert len(plugins) == 1
    assert plugins[0].name == "my-dir"


def test_discover_skips_invalid_json(tmp_path: Path) -> None:
    """Invalid JSON in plugin.json is skipped with a warning."""
    marker_dir = tmp_path / "bad-plugin" / ".claude-plugin"
    marker_dir.mkdir(parents=True)
    (marker_dir / "plugin.json").write_text("not json{")
    # With only one marker and it's invalid, the result is empty (no SystemExit
    # because markers were found, just all skipped)
    plugins = discover_plugins(tmp_path)
    assert plugins == []
