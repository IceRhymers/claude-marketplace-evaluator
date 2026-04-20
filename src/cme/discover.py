"""Plugin discovery via .claude-plugin/plugin.json markers."""

from __future__ import annotations

import fnmatch
import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PluginInfo:
    name: str
    root_dir: Path
    skills_dir: Path  # resolved absolute path


def discover_plugins(root: Path) -> list[PluginInfo]:
    """Find all plugins under root by locating .claude-plugin/plugin.json markers.

    Works for both:
    - marketplace root: root/plugin-a/.claude-plugin/plugin.json
    - single plugin:    root/.claude-plugin/plugin.json

    Raises SystemExit with clear error if no plugins found.
    """
    markers = sorted(root.resolve().glob("**/.claude-plugin/plugin.json"))
    if not markers:
        print(
            f"ERROR: no .claude-plugin/plugin.json found under {root}\n"
            "Each plugin must have a .claude-plugin/plugin.json marker file.",
            file=sys.stderr,
        )
        sys.exit(1)

    plugins: list[PluginInfo] = []
    for marker in markers:
        plugin_root = marker.parent.parent  # .claude-plugin/../ = plugin root
        try:
            data = json.loads(marker.read_text())
        except json.JSONDecodeError as e:
            print(f"WARN: invalid JSON in {marker}: {e}", file=sys.stderr)
            continue
        name = data.get("name") or plugin_root.name
        skills_rel = data.get("skills", "./skills/")
        skills_dir = (plugin_root / skills_rel).resolve()
        plugins.append(
            PluginInfo(name=name, root_dir=plugin_root, skills_dir=skills_dir)
        )
    return plugins


def filter_plugins(
    plugins: list[PluginInfo], patterns: tuple[str, ...]
) -> list[PluginInfo]:
    """Filter plugins by glob patterns against plugin name. OR semantics."""
    if not patterns:
        return plugins
    return [p for p in plugins if any(fnmatch.fnmatch(p.name, pat) for pat in patterns)]
