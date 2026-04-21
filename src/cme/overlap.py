"""Functional skill overlap detection using the Anthropic SDK."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anthropic

from .discover import PluginInfo, discover_plugins
from .models import OverlapFinding, OverlapReport


def _parse_allowed_tools(text: str) -> list[str]:
    """Parse allowed-tools from SKILL.md frontmatter. Handles YAML list, CSV, JSON."""
    # Extract frontmatter
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return []
    frontmatter = match.group(1)

    # Find allowed-tools line(s)
    tools_match = re.search(r"^allowed-tools:[^\S\n]*(.*)$", frontmatter, re.MULTILINE)
    if not tools_match:
        return []

    inline_value = tools_match.group(1).strip()

    # Format 3: JSON array inline  e.g. ["Bash", "Read"]
    if inline_value.startswith("["):
        try:
            parsed = json.loads(inline_value)
            if isinstance(parsed, list):
                return [str(t).strip() for t in parsed]
        except json.JSONDecodeError:
            pass

    # Format 2: Comma-separated  e.g. Bash, Read
    if inline_value and not inline_value.startswith("["):
        return [t.strip() for t in inline_value.split(",") if t.strip()]

    # Format 1: YAML list  e.g.  - Bash\n  - Read
    # inline_value is empty, items follow on subsequent lines
    tools: list[str] = []
    lines = frontmatter.split("\n")
    in_tools = False
    for line in lines:
        if re.match(r"^allowed-tools:\s*$", line):
            in_tools = True
            continue
        if in_tools:
            item_match = re.match(r"^\s+-\s+(.+)$", line)
            if item_match:
                tools.append(item_match.group(1).strip())
            else:
                break
    return tools


def _collect_skill_cards(
    plugins_dir: Path, plugins: list[PluginInfo] | None = None
) -> list[dict[str, Any]]:
    """Walk plugins dir and collect skill descriptions + allowed-tools."""
    if plugins is None:
        plugins = discover_plugins(plugins_dir)
    all_skill_mds: list[Path] = []
    for plugin in plugins:
        all_skill_mds.extend(sorted(plugin.skills_dir.glob("*/SKILL.md")))

    skills: list[dict[str, Any]] = []
    for skill_md in all_skill_mds:
        skill_dir = skill_md.parent
        try:
            rel_path = str(skill_dir.relative_to(plugins_dir.parent))
        except ValueError:
            rel_path = str(skill_dir)

        text = skill_md.read_text()
        description = text[:2000]

        allowed_tools = _parse_allowed_tools(text)

        # Derive name from directory
        name = skill_dir.name

        skills.append(
            {
                "path": rel_path,
                "name": name,
                "description": description,
                "allowed_tools": allowed_tools,
            }
        )

    return skills


def _build_client() -> anthropic.Anthropic:
    """Build Anthropic client (supports Databricks AI Gateway).

    Requires ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN. CLAUDE_CODE_OAUTH_TOKEN
    is not accepted here — /v1/messages rejects OAuth tokens.
    """
    api_key: str | None = None
    base_url: str | None = None
    if token := os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        api_key = token
    elif key := os.environ.get("ANTHROPIC_API_KEY"):
        api_key = key
    if url := os.environ.get("ANTHROPIC_BASE_URL"):
        base_url = url
    kwargs: dict[str, str] = {}
    if api_key is not None:
        kwargs["api_key"] = api_key
    if base_url is not None:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)  # type: ignore[arg-type]


_OVERLAP_TOOL: dict[str, Any] = {
    "name": "report_findings",
    "description": "Report functional overlap findings between skill pairs.",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "skill_a",
                        "skill_b",
                        "functional_summary",
                        "shared_tools",
                        "severity",
                        "recommendation",
                        "explanation",
                    ],
                    "properties": {
                        "skill_a": {"type": "string"},
                        "skill_b": {"type": "string"},
                        "functional_summary": {"type": "string"},
                        "shared_tools": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "severity": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                        "recommendation": {"type": "string"},
                        "explanation": {"type": "string"},
                    },
                },
            }
        },
        "required": ["findings"],
    },
}

_SEVERITY_RUBRIC = """\
Severity rubric:
- HIGH: Skills are functional duplicates — same action, same output, same scope. A user would get identical results from either.
- MEDIUM: One skill's functionality is a subset of the other, or they overlap significantly in one area.
- LOW: Skills share a domain or tool set but serve clearly different purposes."""


def _build_full_scan_prompt(skills: list[dict[str, Any]]) -> str:
    """Build prompt for full-scan functional overlap detection."""
    skills_text = ""
    for s in skills:
        skills_text += f"\n## Skill: {s['path']}\n"
        skills_text += f"**Name:** {s['name']}\n"
        skills_text += f"**Allowed tools:** {', '.join(s['allowed_tools']) or 'none'}\n"
        skills_text += f"### Description\n{s['description']}\n"

    return f"""You are a Claude Code marketplace health auditor. Analyze these skills for functional overlap.

A functional overlap occurs when two different skills do the same job — they perform the same action, produce the same output, or serve the same purpose for the user.

{_SEVERITY_RUBRIC}

Only report genuine functional overlaps. If skills are in clearly different domains or serve different purposes, do not report them.

Call the report_findings tool with your findings. If no functional overlaps exist, call it with an empty findings list.

{skills_text}"""


def _build_pr_aware_prompt(
    new_skill: dict[str, Any], catalog: list[dict[str, Any]]
) -> str:
    """Build prompt for PR-aware overlap detection of a new skill against catalog."""
    catalog_text = ""
    for s in catalog:
        condensed_desc = s["description"][:200]
        catalog_text += f"\n- **{s['name']}** ({s['path']}): {condensed_desc}"
        if s["allowed_tools"]:
            catalog_text += f" [tools: {', '.join(s['allowed_tools'])}]"

    return f"""You are a Claude Code marketplace health auditor. Check if a new skill functionally overlaps with any existing skill in the catalog.

A functional overlap occurs when two skills do the same job — they perform the same action, produce the same output, or serve the same purpose for the user.

{_SEVERITY_RUBRIC}

## New Skill: {new_skill["path"]}
**Name:** {new_skill["name"]}
**Allowed tools:** {", ".join(new_skill["allowed_tools"]) or "none"}
### Description
{new_skill["description"]}

## Existing Skill Catalog
{catalog_text}

Call the report_findings tool with any functional overlaps between the new skill and existing catalog skills. If no overlaps exist, call it with an empty findings list."""


def _call_llm(
    client: anthropic.Anthropic, model: str, prompt: str
) -> list[OverlapFinding]:
    """Make a single LLM call and extract findings."""
    response = client.messages.create(  # type: ignore[call-overload]
        model=model,
        max_tokens=4096,
        tools=[_OVERLAP_TOOL],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": prompt}],
    )

    findings: list[OverlapFinding] = []
    for block in response.content:
        if block.type == "tool_use" and block.name == "report_findings":
            raw_findings = block.input.get("findings", [])  # type: ignore[union-attr]
            for f in raw_findings:
                findings.append(OverlapFinding(**f))
            break
    return findings


def detect_overlap(
    plugins_dir: Path,
    output_path: Path,
    model: str | None = None,
    plugins: list[PluginInfo] | None = None,
    new_skill_paths: list[str] | None = None,
) -> OverlapReport:
    """Run overlap detection and write JSON report. Returns the report."""
    skills = _collect_skill_cards(plugins_dir, plugins=plugins)

    client = _build_client()
    model_used = model or os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-4-5"

    all_findings: list[OverlapFinding] = []

    if new_skill_paths is not None:
        # PR-aware mode
        mode = "pr-aware"
        new_skills_checked = len(new_skill_paths)

        for nsp in new_skill_paths:
            nsp_resolved = Path(nsp).resolve()
            # Find matching skill card
            new_skill = None
            for s in skills:
                skill_dir_resolved = (plugins_dir.parent / s["path"]).resolve()
                if skill_dir_resolved == nsp_resolved:
                    new_skill = s
                    break
            if new_skill is None:
                continue

            catalog = [s for s in skills if s["path"] != new_skill["path"]]
            if not catalog:
                continue

            prompt = _build_pr_aware_prompt(new_skill, catalog)
            all_findings.extend(_call_llm(client, model_used, prompt))
    else:
        # Full-scan mode
        mode = "full-scan"
        new_skills_checked = 0

        if len(skills) >= 2:
            batch_size = 15
            if len(skills) <= batch_size:
                prompt = _build_full_scan_prompt(skills)
                all_findings = _call_llm(client, model_used, prompt)
            else:
                # Batch into chunks
                seen_pairs: set[tuple[str, str]] = set()
                for i in range(0, len(skills), batch_size):
                    batch = skills[i : i + batch_size]
                    if len(batch) < 2:
                        continue
                    prompt = _build_full_scan_prompt(batch)
                    batch_findings = _call_llm(client, model_used, prompt)
                    # Deduplicate by sorted pair
                    for f in batch_findings:
                        pair: tuple[str, str] = (
                            min(f.skill_a, f.skill_b),
                            max(f.skill_a, f.skill_b),
                        )
                        if pair not in seen_pairs:
                            seen_pairs.add(pair)
                            all_findings.append(f)

    report = OverlapReport(
        timestamp=datetime.now(UTC).isoformat(),
        model_used=model_used,
        mode=mode,
        total_skills_analyzed=len(skills),
        new_skills_checked=new_skills_checked,
        total_findings=len(all_findings),
        findings=all_findings,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.model_dump_json(indent=2))
    return report


def format_github_comment(report: OverlapReport) -> str:
    """Format an OverlapReport as a GitHub-flavored markdown comment."""
    lines: list[str] = []
    lines.append("## Skill Overlap Report")
    lines.append(
        f"Skills analyzed: {report.total_skills_analyzed} | "
        f"New skills: {report.new_skills_checked} | "
        f"Findings: {report.total_findings}"
    )
    lines.append("")

    if not report.findings:
        lines.append("No functional overlaps detected.")
        return "\n".join(lines)

    # Sort by severity: HIGH first, then MEDIUM, then LOW
    severity_order = {"high": 0, "medium": 1, "low": 2}
    sorted_findings = sorted(
        report.findings, key=lambda f: severity_order.get(f.severity, 3)
    )

    lines.append("| Severity | Skill | Conflicts With | Recommendation |")
    lines.append("|----------|-------|----------------|----------------|")

    display_count = min(5, len(sorted_findings))
    for f in sorted_findings[:display_count]:
        lines.append(
            f"| {f.severity.upper()} | `{f.skill_a}` | `{f.skill_b}` | {f.recommendation} |"
        )

    if len(sorted_findings) > 5:
        remaining = len(sorted_findings) - 5
        lines.append("")
        lines.append(f"<details><summary>{remaining} more findings</summary>")
        lines.append("")
        lines.append("| Severity | Skill | Conflicts With | Recommendation |")
        lines.append("|----------|-------|----------------|----------------|")
        for f in sorted_findings[5:]:
            lines.append(
                f"| {f.severity.upper()} | `{f.skill_a}` | `{f.skill_b}` | {f.recommendation} |"
            )
        lines.append("")
        lines.append("</details>")

    return "\n".join(lines)
