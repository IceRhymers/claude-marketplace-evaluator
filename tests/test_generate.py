"""Tests for routing test-case generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cme.generate import (
    derive_test_name,
    generate_test_cases,
    load_evals_file,
    slugify_query,
)


def test_slugify_query_basic() -> None:
    assert slugify_query("trace the lineage for table") == "trace-the-lineage-for-table"


def test_slugify_query_special_chars() -> None:
    assert slugify_query("what's the #1 table?") == "whats-the-1-table"


def test_slugify_query_max_words() -> None:
    result = slugify_query("one two three four five six seven", max_words=3)
    assert result == "one-two-three"


def test_derive_test_name_unique() -> None:
    seen: set[str] = set()
    n1 = derive_test_name("my-skill", "do the thing", seen)
    n2 = derive_test_name("my-skill", "do the thing", seen)
    assert n1 != n2
    assert n2.endswith("-2")


def test_load_evals_file_valid(tmp_path: Path) -> None:
    p = tmp_path / "evals.json"
    p.write_text(json.dumps([{"query": "do X", "should_trigger": True}]))
    evals = load_evals_file(p)
    assert len(evals.entries) == 1


def test_load_evals_file_bad_json(tmp_path: Path) -> None:
    p = tmp_path / "evals.json"
    p.write_text("{not valid json")
    with pytest.raises(ValueError, match="Invalid JSON"):
        load_evals_file(p)


def test_load_evals_file_not_array(tmp_path: Path) -> None:
    p = tmp_path / "evals.json"
    p.write_text('{"query": "x", "should_trigger": true}')
    with pytest.raises(ValueError, match="JSON array"):
        load_evals_file(p)


def test_generate_returns_test_cases(tmp_path: Path) -> None:
    # Create a fake plugin/skill/evals structure with plugin.json marker
    plugin_dir = tmp_path / "plugins" / "my-plugin"
    marker_dir = plugin_dir / ".claude-plugin"
    marker_dir.mkdir(parents=True)
    (marker_dir / "plugin.json").write_text(
        json.dumps({"name": "my-plugin", "skills": "./skills/"})
    )
    evals_dir = plugin_dir / "skills" / "my-skill" / "evals"
    evals_dir.mkdir(parents=True)
    (evals_dir / "evals.json").write_text(
        json.dumps(
            [
                {"query": "do the thing", "should_trigger": True},
                {"query": "don't do it", "should_trigger": False},
            ]
        )
    )
    # Also create a SKILL.md
    (evals_dir.parent / "SKILL.md").write_text("---\nname: my-skill\n---")

    cases, rc = generate_test_cases(tmp_path / "plugins")
    assert rc == 0
    assert len(cases) == 1
    assert cases[0].expected_skill == "my-skill"
    assert cases[0].prompt == "do the thing"
    assert "my-skill" in cases[0].name


def test_generate_missing_plugins_dir(tmp_path: Path) -> None:
    cases, rc = generate_test_cases(tmp_path / "nonexistent")
    assert rc == 1
    assert cases == []


def test_generate_bad_evals_json(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins" / "p"
    marker_dir = plugin_dir / ".claude-plugin"
    marker_dir.mkdir(parents=True)
    (marker_dir / "plugin.json").write_text(
        json.dumps({"name": "p", "skills": "./skills/"})
    )
    evals_dir = plugin_dir / "skills" / "s" / "evals"
    evals_dir.mkdir(parents=True)
    (evals_dir / "evals.json").write_text("not json")
    cases, rc = generate_test_cases(tmp_path / "plugins")
    assert rc == 1
    assert cases == []
