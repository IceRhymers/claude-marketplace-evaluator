"""Coverage check — discovers skills and flags missing/malformed evals."""

from __future__ import annotations

import sys
from pathlib import Path

from .discover import discover_plugins
from .generate import load_evals_file
from .models import CoverageReport


def check_coverage(plugins_dir: Path, threshold: float) -> tuple[CoverageReport, int]:
    """Walk plugins dir, check eval coverage. Returns (report, exit_code)."""
    plugins = discover_plugins(plugins_dir)
    skill_dirs: list[Path] = []
    for plugin in plugins:
        skill_dirs.extend(
            sorted(d for d in plugin.skills_dir.glob("*/") if (d / "SKILL.md").exists())
        )

    missing: list[str] = []
    malformed: list[str] = []

    for skill_dir in skill_dirs:
        evals_path = skill_dir / "evals" / "evals.json"
        if not evals_path.exists():
            missing.append(str(skill_dir))
            continue
        try:
            load_evals_file(evals_path)
        except ValueError as e:
            malformed.append(f"{skill_dir}: {e}")

    skills_with_evals = len(skill_dirs) - len(missing) - len(malformed)
    report = CoverageReport(
        total_skills=len(skill_dirs),
        skills_with_evals=skills_with_evals,
        skills_missing_evals=missing,
        skills_with_malformed_evals=malformed,
    )

    _print_coverage_report(report)

    exit_code = 0
    if report.coverage_pct < threshold:
        print(
            f"\nFAILED: coverage {report.coverage_pct:.1f}% < {threshold}% threshold",
            file=sys.stderr,
        )
        exit_code = 1
    else:
        print(
            f"\nPASSED: coverage {report.coverage_pct:.1f}% >= {threshold}% threshold"
        )

    return report, exit_code


def _print_coverage_report(report: CoverageReport) -> None:
    print(f"\n{'=' * 50}")
    print(
        f"Coverage: {report.skills_with_evals}/{report.total_skills} skills have evals ({report.coverage_pct:.1f}%)"
    )

    if report.skills_missing_evals:
        print(f"\nMissing evals ({len(report.skills_missing_evals)}):")
        for s in report.skills_missing_evals:
            print(f"  - {s}")

    if report.skills_with_malformed_evals:
        print(f"\nMalformed evals ({len(report.skills_with_malformed_evals)}):")
        for s in report.skills_with_malformed_evals:
            print(f"  - {s}")
