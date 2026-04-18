"""Semantic skill collision detection using the Anthropic SDK."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anthropic

from .discover import discover_plugins
from .models import CollisionPair, OverlapReport


def _collect_skills(plugins_dir: Path) -> list[dict[str, Any]]:
    """Walk plugins dir and collect skill descriptions + triggers."""
    plugins = discover_plugins(plugins_dir)
    all_skill_mds: list[Path] = []
    for plugin in plugins:
        all_skill_mds.extend(sorted(plugin.skills_dir.glob("*/SKILL.md")))

    skills: list[dict[str, Any]] = []
    for skill_md in all_skill_mds:
        skill_dir = skill_md.parent
        # relative path for display
        try:
            rel_path = str(skill_dir.relative_to(plugins_dir.parent))
        except ValueError:
            rel_path = str(skill_dir)

        description = skill_md.read_text()

        triggers: list[str] = []
        evals_path = skill_dir / "evals" / "evals.json"
        if evals_path.exists():
            try:
                data = json.loads(evals_path.read_text())
                triggers = [
                    e["query"]
                    for e in data
                    if isinstance(e, dict) and e.get("should_trigger")
                ]
            except (json.JSONDecodeError, KeyError):
                pass

        skills.append(
            {
                "path": rel_path,
                "description": description[:2000],  # truncate to avoid context overflow
                "triggers": triggers[:10],  # top 10 positive triggers
            }
        )

    return skills


def _build_client() -> anthropic.Anthropic:
    """Build Anthropic client (supports Databricks AI Gateway)."""
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
    "name": "report_collisions",
    "description": "Report semantic collisions found between skill pairs.",
    "input_schema": {
        "type": "object",
        "properties": {
            "collisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "skill_a",
                        "skill_b",
                        "overlapping_triggers",
                        "description_excerpts",
                        "severity",
                    ],
                    "properties": {
                        "skill_a": {"type": "string"},
                        "skill_b": {"type": "string"},
                        "overlapping_triggers": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "description_excerpts": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "severity": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                    },
                },
            }
        },
        "required": ["collisions"],
    },
}


def _build_prompt(skills: list[dict[str, Any]]) -> str:
    skills_text = ""
    for s in skills:
        skills_text += f"\n## Skill: {s['path']}\n"
        skills_text += f"### Description\n{s['description']}\n"
        if s["triggers"]:
            skills_text += "### Trigger queries (should_trigger=true)\n"
            for t in s["triggers"]:
                skills_text += f"- {t}\n"

    return f"""You are a Claude Code marketplace health auditor. Analyze these skills for semantic collisions.

A collision occurs when two different skills:
1. Have similar trigger queries that could cause ambiguous routing for the same user intent, OR
2. Have semantically overlapping descriptions/functionality suggesting duplicated purpose

Severity guide:
- HIGH: Skills are nearly identical in purpose; a user prompt would almost certainly trigger either skill
- MEDIUM: Skills overlap significantly in one area; some user queries would be ambiguous
- LOW: Skills share a thematic area but are clearly distinct enough in most cases

Only report genuine collisions. If skills are in clearly different domains, do not report them.

Call the report_collisions tool with your findings. If no collisions exist, call it with an empty list.

{skills_text}"""


def detect_overlap(
    plugins_dir: Path,
    output_path: Path,
    model: str | None = None,
) -> OverlapReport:
    """Run overlap detection and write JSON report. Returns the report."""
    skills = _collect_skills(plugins_dir)

    client = _build_client()

    model_used = model or os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-4-5"

    collisions: list[CollisionPair] = []

    if len(skills) >= 2:
        prompt = _build_prompt(skills)
        response = client.messages.create(  # type: ignore[call-overload]
            model=model_used,
            max_tokens=4096,
            tools=[_OVERLAP_TOOL],
            tool_choice={"type": "any"},
            messages=[{"role": "user", "content": prompt}],
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == "report_collisions":
                raw_collisions = block.input.get("collisions", [])  # type: ignore[union-attr]
                for c in raw_collisions:
                    collisions.append(CollisionPair(**c))
                break

    report = OverlapReport(
        timestamp=datetime.now(UTC).isoformat(),
        model_used=model_used,
        total_skills_analyzed=len(skills),
        total_collisions=len(collisions),
        collisions=collisions,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.model_dump_json(indent=2))
    return report
