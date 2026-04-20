"""Tests for plugin glob filtering."""

from __future__ import annotations

from pathlib import Path

from cme.discover import PluginInfo, filter_plugins


def _make_plugin(name: str) -> PluginInfo:
    return PluginInfo(
        name=name,
        root_dir=Path(f"/fake/{name}"),
        skills_dir=Path(f"/fake/{name}/skills"),
    )


def test_filter_single_pattern_match() -> None:
    plugins = [
        _make_plugin("git-commit"),
        _make_plugin("slack-notify"),
        _make_plugin("git-pr"),
    ]
    result = filter_plugins(plugins, ("git-*",))
    assert len(result) == 2
    assert {p.name for p in result} == {"git-commit", "git-pr"}


def test_filter_multi_pattern_or_match() -> None:
    plugins = [
        _make_plugin("git-commit"),
        _make_plugin("slack-notify"),
        _make_plugin("jira-create"),
    ]
    result = filter_plugins(plugins, ("git-*", "slack-*"))
    assert len(result) == 2
    assert {p.name for p in result} == {"git-commit", "slack-notify"}


def test_filter_no_match_returns_empty() -> None:
    plugins = [_make_plugin("git-commit"), _make_plugin("slack-notify")]
    result = filter_plugins(plugins, ("jira-*",))
    assert result == []


def test_filter_no_patterns_returns_all() -> None:
    plugins = [_make_plugin("git-commit"), _make_plugin("slack-notify")]
    result = filter_plugins(plugins, ())
    assert result == plugins
