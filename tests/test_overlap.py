"""Tests for cme overlap command — unit tests (no real API calls)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from cme.models import CollisionPair
from cme.overlap import _build_prompt, _collect_skills, detect_overlap


def _make_plugin_marker(base: Path, plugin: str) -> None:
    """Create .claude-plugin/plugin.json marker for a plugin."""
    marker_dir = base / plugin / ".claude-plugin"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker = marker_dir / "plugin.json"
    if not marker.exists():
        marker.write_text(json.dumps({"name": plugin, "skills": "./skills/"}))


def _make_skill(
    base: Path,
    plugin: str,
    skill: str,
    description: str = "A skill that does things.",
    triggers: list[str] | None = None,
) -> None:
    _make_plugin_marker(base, plugin)
    skill_dir = base / plugin / "skills" / skill
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {skill}\ndescription: {description}\n---\n{description}"
    )
    if triggers is not None:
        evals_dir = skill_dir / "evals"
        evals_dir.mkdir()
        entries = [{"query": t, "should_trigger": True} for t in triggers]
        (evals_dir / "evals.json").write_text(json.dumps(entries))


def test_collect_skills_empty(tmp_path: Path) -> None:
    # Plugin with marker but no skills
    _make_plugin_marker(tmp_path, "empty-plugin")
    skills = _collect_skills(tmp_path)
    assert skills == []


def test_collect_skills_finds_skill(tmp_path: Path) -> None:
    _make_skill(tmp_path, "p", "my-skill", triggers=["do the thing"])
    skills = _collect_skills(tmp_path)
    assert len(skills) == 1
    assert "my-skill" in skills[0]["path"]
    assert "do the thing" in skills[0]["triggers"]


def test_collect_skills_no_evals(tmp_path: Path) -> None:
    _make_skill(tmp_path, "p", "my-skill")
    skills = _collect_skills(tmp_path)
    assert skills[0]["triggers"] == []


def test_collect_skills_multiple(tmp_path: Path) -> None:
    _make_skill(tmp_path, "p", "skill-a", triggers=["query a"])
    _make_skill(tmp_path, "p", "skill-b", triggers=["query b"])
    skills = _collect_skills(tmp_path)
    assert len(skills) == 2


def test_build_prompt_includes_skill_data(tmp_path: Path) -> None:
    skills = [
        {
            "path": "plugins/p/skills/a",
            "description": "Does A things.",
            "triggers": ["do A"],
        },
        {
            "path": "plugins/p/skills/b",
            "description": "Does B things.",
            "triggers": ["do B"],
        },
    ]
    prompt = _build_prompt(skills)
    assert "plugins/p/skills/a" in prompt
    assert "Does A things." in prompt
    assert "do A" in prompt


def test_detect_overlap_no_skills(tmp_path: Path) -> None:
    """With no skills, skip LLM call and return empty report."""
    _make_plugin_marker(tmp_path, "empty-plugin")
    output = tmp_path / "report.json"
    report = detect_overlap(tmp_path, output)
    assert report.total_skills_analyzed == 0
    assert report.total_collisions == 0
    assert output.exists()


def test_detect_overlap_one_skill(tmp_path: Path) -> None:
    """With only one skill, skip LLM call (no pairs possible)."""
    _make_skill(tmp_path, "p", "only-skill")
    output = tmp_path / "report.json"
    report = detect_overlap(tmp_path, output)
    assert report.total_skills_analyzed == 1
    assert report.total_collisions == 0


def test_detect_overlap_with_collisions(tmp_path: Path) -> None:
    """With 2+ skills, LLM call is made — mock it to return a collision."""
    _make_skill(tmp_path, "p", "skill-a", triggers=["run lineage"])
    _make_skill(tmp_path, "p", "skill-b", triggers=["run lineage check"])

    mock_block = MagicMock()
    mock_block.type = "tool_use"
    mock_block.name = "report_collisions"
    mock_block.input = {
        "collisions": [
            {
                "skill_a": "plugins/p/skills/skill-a",
                "skill_b": "plugins/p/skills/skill-b",
                "overlapping_triggers": ["run lineage"],
                "description_excerpts": ["A skill that does things."],
                "severity": "high",
            }
        ]
    }

    mock_response = MagicMock()
    mock_response.content = [mock_block]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    output = tmp_path / "report.json"
    with patch("cme.overlap.anthropic.Anthropic", return_value=mock_client):
        report = detect_overlap(tmp_path, output)

    assert report.total_collisions == 1
    assert report.collisions[0].severity == "high"
    assert output.exists()
    data = json.loads(output.read_text())
    assert data["total_collisions"] == 1


def test_detect_overlap_no_collisions(tmp_path: Path) -> None:
    """LLM returns empty collisions list."""
    _make_skill(tmp_path, "p", "skill-a")
    _make_skill(tmp_path, "p", "skill-b")

    mock_block = MagicMock()
    mock_block.type = "tool_use"
    mock_block.name = "report_collisions"
    mock_block.input = {"collisions": []}

    mock_response = MagicMock()
    mock_response.content = [mock_block]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    output = tmp_path / "report.json"
    with patch("cme.overlap.anthropic.Anthropic", return_value=mock_client):
        report = detect_overlap(tmp_path, output)

    assert report.total_collisions == 0


def test_detect_overlap_report_json_structure(tmp_path: Path) -> None:
    """Verify JSON output has required top-level fields."""
    _make_plugin_marker(tmp_path, "empty-plugin")
    output = tmp_path / "report.json"
    detect_overlap(tmp_path, output)
    data = json.loads(output.read_text())
    assert "timestamp" in data
    assert "model_used" in data
    assert "total_skills_analyzed" in data
    assert "total_collisions" in data
    assert "collisions" in data


def test_overlap_model_pct(tmp_path: Path) -> None:
    pair = CollisionPair(
        skill_a="a",
        skill_b="b",
        overlapping_triggers=["q"],
        description_excerpts=["x"],
        severity="medium",
    )
    assert pair.severity == "medium"
