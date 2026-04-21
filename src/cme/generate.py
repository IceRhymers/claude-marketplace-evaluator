"""Generate routing test cases from per-skill evals.json files."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .discover import PluginInfo, discover_plugins
from .models import EvalsFile, TestCase


def slugify_query(query: str, max_words: int = 5) -> str:
    words = query.lower().split()[:max_words]
    slugged = [re.sub(r"[^a-z0-9]", "", w) for w in words]
    return "-".join(w for w in slugged if w)


def derive_test_name(skill_name: str, query: str, seen: set[str]) -> str:
    slug = slugify_query(query)
    base = f"{skill_name}-{slug}"[:80]
    name = base
    counter = 2
    while name in seen:
        suffix = f"-{counter}"
        name = base[: 80 - len(suffix)] + suffix
        counter += 1
    seen.add(name)
    return name


def load_evals_file(path: Path) -> EvalsFile:
    """Load and validate an evals.json file. Raises ValueError on bad format."""
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {path}: {e}") from e
    if not isinstance(data, list):
        raise ValueError(f"{path}: top-level value must be a JSON array")
    try:
        return EvalsFile(entries=data)
    except Exception as e:
        raise ValueError(f"{path}: schema error: {e}") from e


def generate_test_cases(
    plugins_dir: Path, plugins: list[PluginInfo] | None = None
) -> tuple[list[TestCase], int]:
    """Walk plugins dir, build routing test cases in memory.

    Returns (test_cases, exit_code) where exit_code is 0 on success, 1 on error.
    """
    if not plugins_dir.is_dir():
        print(f"ERROR: plugins dir not found: {plugins_dir}", file=sys.stderr)
        return [], 1

    if plugins is None:
        plugins = discover_plugins(plugins_dir)
    entries: list[tuple[str, str, Path]] = []
    for plugin in plugins:
        for evals_path in sorted(plugin.skills_dir.glob("*/evals/evals.json")):
            skill_name = evals_path.parts[-3]
            entries.append((plugin.name, skill_name, evals_path))

    if not entries:
        print(f"WARN: no evals.json files found under {plugins_dir}", file=sys.stderr)

    per_plugin: dict[str, list[TestCase]] = {}
    had_error = False

    for plugin_name, skill_name, evals_path in entries:
        try:
            evals = load_evals_file(evals_path)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            had_error = True
            continue

        if not evals.positive_entries:
            print(
                f"WARN: no should_trigger:true entries in {evals_path}", file=sys.stderr
            )
            continue

        seen: set[str] = set()
        cases = [
            TestCase(
                name=derive_test_name(skill_name, e.query, seen),
                prompt=e.query,
                expected_skill=skill_name,
            )
            for e in evals.positive_entries
        ]
        per_plugin.setdefault(plugin_name, []).extend(cases)

    if had_error:
        return [], 1

    all_cases: list[TestCase] = []
    for plugin_name in sorted(per_plugin.keys()):
        all_cases.extend(per_plugin[plugin_name])

    total = len(all_cases)
    print(f"  {total} test cases from {len(per_plugin)} plugin(s)")
    return all_cases, 0
