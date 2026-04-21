"""Tests for cme overlap command — unit tests (no real API calls)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from cme.cli import main
from cme.models import OverlapFinding, OverlapReport
from cme.overlap import (
    _OVERLAP_TOOL,
    _build_full_scan_prompt,
    _build_pr_aware_prompt,
    _collect_skill_cards,
    detect_overlap,
    format_github_comment,
)


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
    frontmatter_extra: str = "",
) -> Path:
    _make_plugin_marker(base, plugin)
    skill_dir = base / plugin / "skills" / skill
    skill_dir.mkdir(parents=True, exist_ok=True)
    fm = f"---\nname: {skill}\ndescription: {description}\n{frontmatter_extra}---\n{description}"
    (skill_dir / "SKILL.md").write_text(fm)
    return skill_dir


def _mock_findings_response(findings: list[dict]) -> MagicMock:
    """Build a mock Anthropic client returning given findings."""
    mock_block = MagicMock()
    mock_block.type = "tool_use"
    mock_block.name = "report_findings"
    mock_block.input = {"findings": findings}
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    return mock_client


def _sample_finding(
    skill_a: str = "p/skills/a",
    skill_b: str = "p/skills/b",
    severity: str = "high",
) -> dict:
    return {
        "skill_a": skill_a,
        "skill_b": skill_b,
        "functional_summary": "Both skills do the same thing.",
        "shared_tools": ["Bash"],
        "severity": severity,
        "recommendation": "Merge into one skill.",
        "explanation": "They are duplicates. Same action, same output.",
    }


# --- _collect_skill_cards tests ---


def test_collect_skill_cards_empty(tmp_path: Path) -> None:
    _make_plugin_marker(tmp_path, "empty-plugin")
    skills = _collect_skill_cards(tmp_path)
    assert skills == []


def test_collect_skill_cards_reads_description(tmp_path: Path) -> None:
    desc = "X" * 2500
    _make_skill(tmp_path, "p", "my-skill", description=desc)
    skills = _collect_skill_cards(tmp_path)
    assert len(skills) == 1
    # Truncated at 2000 chars
    assert len(skills[0]["description"]) == 2000


def test_collect_skill_cards_parses_yaml_list(tmp_path: Path) -> None:
    _make_skill(
        tmp_path,
        "p",
        "s",
        frontmatter_extra="allowed-tools:\n  - Bash\n  - Read\n",
    )
    skills = _collect_skill_cards(tmp_path)
    assert skills[0]["allowed_tools"] == ["Bash", "Read"]


def test_collect_skill_cards_parses_json_array(tmp_path: Path) -> None:
    _make_skill(
        tmp_path,
        "p",
        "s",
        frontmatter_extra='allowed-tools: ["Bash", "Read"]\n',
    )
    skills = _collect_skill_cards(tmp_path)
    assert skills[0]["allowed_tools"] == ["Bash", "Read"]


def test_collect_skill_cards_parses_comma_sep(tmp_path: Path) -> None:
    _make_skill(
        tmp_path,
        "p",
        "s",
        frontmatter_extra="allowed-tools: Bash, Read\n",
    )
    skills = _collect_skill_cards(tmp_path)
    assert skills[0]["allowed_tools"] == ["Bash", "Read"]


def test_collect_skill_cards_no_allowed_tools(tmp_path: Path) -> None:
    _make_skill(tmp_path, "p", "s")
    skills = _collect_skill_cards(tmp_path)
    assert skills[0]["allowed_tools"] == []


def test_collect_skill_cards_ignores_evals(tmp_path: Path) -> None:
    """Has evals.json — NOT read by _collect_skill_cards."""
    _make_skill(tmp_path, "p", "s")
    evals_dir = tmp_path / "p" / "skills" / "s" / "evals"
    evals_dir.mkdir()
    (evals_dir / "evals.json").write_text(
        json.dumps([{"query": "test", "should_trigger": True}])
    )
    skills = _collect_skill_cards(tmp_path)
    assert "triggers" not in skills[0]
    assert "allowed_tools" in skills[0]


# --- Prompt tests ---


def test_build_full_scan_prompt_content() -> None:
    skills = [
        {
            "path": "plugins/p/skills/a",
            "name": "a",
            "description": "Does A things.",
            "allowed_tools": ["Bash"],
        },
        {
            "path": "plugins/p/skills/b",
            "name": "b",
            "description": "Does B things.",
            "allowed_tools": [],
        },
    ]
    prompt = _build_full_scan_prompt(skills)
    assert "functional overlap" in prompt.lower()
    assert "plugins/p/skills/a" in prompt
    assert "plugins/p/skills/b" in prompt
    assert "Does A things." in prompt


def test_build_full_scan_prompt_no_triggers() -> None:
    skills = [
        {
            "path": "p/skills/a",
            "name": "a",
            "description": "desc",
            "allowed_tools": [],
        },
    ]
    prompt = _build_full_scan_prompt(skills)
    assert "trigger" not in prompt.lower()
    assert "routing" not in prompt.lower()


def test_build_pr_aware_prompt_condensed_catalog() -> None:
    new_skill = {
        "path": "p/skills/new",
        "name": "new",
        "description": "A" * 500,
        "allowed_tools": ["Bash"],
    }
    catalog = [
        {
            "path": "p/skills/old",
            "name": "old",
            "description": "B" * 500,
            "allowed_tools": ["Read"],
        },
    ]
    prompt = _build_pr_aware_prompt(new_skill, catalog)
    # New skill has full text
    assert "A" * 500 in prompt
    # Catalog entry is condensed to 200 chars
    assert "B" * 200 in prompt
    assert "B" * 201 not in prompt


# --- Tool schema test ---


def test_overlap_tool_schema_fields() -> None:
    schema = _OVERLAP_TOOL["input_schema"]["properties"]["findings"]["items"]
    required = schema["required"]
    assert "skill_a" in required
    assert "skill_b" in required
    assert "functional_summary" in required
    assert "shared_tools" in required
    assert "severity" in required
    assert "recommendation" in required
    assert "explanation" in required


# --- detect_overlap tests ---


def test_detect_overlap_full_scan_no_skills(tmp_path: Path) -> None:
    _make_plugin_marker(tmp_path, "empty-plugin")
    output = tmp_path / "report.json"
    report = detect_overlap(tmp_path, output)
    assert report.total_skills_analyzed == 0
    assert report.total_findings == 0
    assert report.mode == "full-scan"
    assert output.exists()


def test_detect_overlap_full_scan_one_skill(tmp_path: Path) -> None:
    _make_skill(tmp_path, "p", "only-skill")
    output = tmp_path / "report.json"
    report = detect_overlap(tmp_path, output)
    assert report.total_skills_analyzed == 1
    assert report.total_findings == 0


def test_detect_overlap_full_scan_with_findings(tmp_path: Path) -> None:
    _make_skill(tmp_path, "p", "skill-a")
    _make_skill(tmp_path, "p", "skill-b")

    finding = _sample_finding(skill_a="p/skills/skill-a", skill_b="p/skills/skill-b")
    mock_client = _mock_findings_response([finding])

    output = tmp_path / "report.json"
    with patch("cme.overlap.anthropic.Anthropic", return_value=mock_client):
        report = detect_overlap(tmp_path, output)

    assert report.total_findings == 1
    assert report.findings[0].severity == "high"
    data = json.loads(output.read_text())
    assert data["total_findings"] == 1


def test_detect_overlap_pr_aware_mode(tmp_path: Path) -> None:
    skill_a_dir = _make_skill(tmp_path, "p", "skill-a")
    _make_skill(tmp_path, "p", "skill-b")

    finding = _sample_finding()
    mock_client = _mock_findings_response([finding])

    output = tmp_path / "report.json"
    with patch("cme.overlap.anthropic.Anthropic", return_value=mock_client):
        report = detect_overlap(tmp_path, output, new_skill_paths=[str(skill_a_dir)])

    assert report.mode == "pr-aware"
    assert report.new_skills_checked == 1


def test_detect_overlap_pr_aware_no_findings(tmp_path: Path) -> None:
    skill_a_dir = _make_skill(tmp_path, "p", "skill-a")
    _make_skill(tmp_path, "p", "skill-b")

    mock_client = _mock_findings_response([])

    output = tmp_path / "report.json"
    with patch("cme.overlap.anthropic.Anthropic", return_value=mock_client):
        report = detect_overlap(tmp_path, output, new_skill_paths=[str(skill_a_dir)])

    assert report.total_findings == 0


def test_detect_overlap_full_scan_batching(tmp_path: Path) -> None:
    """21 skills -> 2 LLM calls, dedup works."""
    for i in range(21):
        _make_skill(tmp_path, "p", f"skill-{i:02d}")

    finding = _sample_finding(skill_a="p/skills/skill-00", skill_b="p/skills/skill-01")
    mock_client = _mock_findings_response([finding])

    output = tmp_path / "report.json"
    with patch("cme.overlap.anthropic.Anthropic", return_value=mock_client):
        report = detect_overlap(tmp_path, output)

    # Should have been called twice (15 + 6)
    assert mock_client.messages.create.call_count == 2
    # Dedup: same pair returned by both calls -> counted once
    assert report.total_findings == 1


# --- format_github_comment tests ---


def test_format_github_comment_empty() -> None:
    report = OverlapReport(
        timestamp="2026-01-01T00:00:00",
        model_used="test",
        mode="full-scan",
        total_skills_analyzed=5,
        new_skills_checked=0,
        total_findings=0,
        findings=[],
    )
    md = format_github_comment(report)
    assert "No functional overlaps detected." in md


def test_format_github_comment_with_findings() -> None:
    findings = [
        OverlapFinding(**_sample_finding(severity="high")),
    ]
    report = OverlapReport(
        timestamp="2026-01-01T00:00:00",
        model_used="test",
        mode="full-scan",
        total_skills_analyzed=5,
        new_skills_checked=0,
        total_findings=1,
        findings=findings,
    )
    md = format_github_comment(report)
    assert "| Severity |" in md
    assert "| HIGH |" in md
    assert "Merge into one skill." in md


def test_format_github_comment_caps_at_5() -> None:
    findings = [
        OverlapFinding(**_sample_finding(skill_a=f"s/{i}", severity="low"))
        for i in range(7)
    ]
    report = OverlapReport(
        timestamp="2026-01-01T00:00:00",
        model_used="test",
        mode="full-scan",
        total_skills_analyzed=10,
        new_skills_checked=0,
        total_findings=7,
        findings=findings,
    )
    md = format_github_comment(report)
    assert "<details>" in md
    assert "2 more findings" in md


def test_format_github_comment_sorted_by_severity() -> None:
    findings = [
        OverlapFinding(**_sample_finding(skill_a="s/low", severity="low")),
        OverlapFinding(**_sample_finding(skill_a="s/high", severity="high")),
        OverlapFinding(**_sample_finding(skill_a="s/med", severity="medium")),
    ]
    report = OverlapReport(
        timestamp="2026-01-01T00:00:00",
        model_used="test",
        mode="full-scan",
        total_skills_analyzed=5,
        new_skills_checked=0,
        total_findings=3,
        findings=findings,
    )
    md = format_github_comment(report)
    lines = [
        line
        for line in md.split("\n")
        if line.startswith("| HIGH")
        or line.startswith("| MEDIUM")
        or line.startswith("| LOW")
    ]
    assert len(lines) == 3
    assert lines[0].startswith("| HIGH")
    assert lines[1].startswith("| MEDIUM")
    assert lines[2].startswith("| LOW")


# --- CLI exit code tests ---


def test_exit_code_full_scan_any_finding(tmp_path: Path) -> None:
    """Full-scan: LOW finding -> exit 1."""
    _make_skill(tmp_path, "p", "skill-a")
    _make_skill(tmp_path, "p", "skill-b")

    finding = _sample_finding(severity="low")
    mock_client = _mock_findings_response([finding])

    output = tmp_path / "report.json"
    runner = CliRunner()
    with patch("cme.overlap.anthropic.Anthropic", return_value=mock_client):
        result = runner.invoke(
            main,
            [
                "overlap",
                "--plugins-dir",
                str(tmp_path),
                "--output",
                str(output),
            ],
        )
    assert result.exit_code == 1


def test_exit_code_pr_aware_high_only(tmp_path: Path) -> None:
    """PR-aware: HIGH -> exit 1; only MEDIUM -> exit 0."""
    skill_a_dir = _make_skill(tmp_path, "p", "skill-a")
    _make_skill(tmp_path, "p", "skill-b")

    # MEDIUM only -> exit 0
    finding_med = _sample_finding(severity="medium")
    mock_client = _mock_findings_response([finding_med])

    output = tmp_path / "report.json"
    runner = CliRunner()
    with patch("cme.overlap.anthropic.Anthropic", return_value=mock_client):
        result = runner.invoke(
            main,
            [
                "overlap",
                "--plugins-dir",
                str(tmp_path),
                "--output",
                str(output),
                "--new-skill",
                str(skill_a_dir),
            ],
        )
    assert result.exit_code == 0

    # HIGH -> exit 1
    finding_high = _sample_finding(severity="high")
    mock_client2 = _mock_findings_response([finding_high])

    with patch("cme.overlap.anthropic.Anthropic", return_value=mock_client2):
        result2 = runner.invoke(
            main,
            [
                "overlap",
                "--plugins-dir",
                str(tmp_path),
                "--output",
                str(output),
                "--new-skill",
                str(skill_a_dir),
            ],
        )
    assert result2.exit_code == 1
