"""CLI entrypoint for cme (claude-marketplace-evaluator)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from . import __version__


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """Claude Code marketplace health CLI."""


@main.command()
@click.option(
    "--plugins-dir",
    default="plugins/",
    show_default=True,
    help="Path to plugins directory.",
)
@click.option(
    "--coverage-threshold",
    default=100.0,
    show_default=True,
    help="Minimum eval coverage % (default: 100).",
)
@click.option(
    "--threshold",
    default=95.0,
    show_default=True,
    help="Minimum routing pass rate % (default: 95).",
)
@click.option(
    "-j",
    "--workers",
    default=4,
    show_default=True,
    help="Parallel workers for eval runner.",
)
@click.option(
    "--timeout", default=30, show_default=True, help="Per-test timeout in seconds."
)
@click.option(
    "--max-retries",
    default=1,
    show_default=True,
    help="Max retries on rate limit errors.",
)
@click.option(
    "--max-turns",
    default=5,
    show_default=True,
    help="Max agent turns per routing eval.",
)
@click.option(
    "--plugin",
    "plugin_patterns",
    multiple=True,
    metavar="PATTERN",
    help="Glob filter on plugin name. Repeatable: --plugin 'git-*' --plugin 'slack-*'. OR semantics.",
)
def routing(
    plugins_dir: str,
    coverage_threshold: float,
    threshold: float,
    workers: int,
    timeout: int,
    max_retries: int,
    max_turns: int,
    plugin_patterns: tuple[str, ...],
) -> None:
    """Run routing evals: generate → coverage check → eval runner."""
    from .coverage import check_coverage
    from .discover import discover_plugins, filter_plugins
    from .generate import generate_test_cases
    from .runner import _discover_plugin_entries, run_all

    plugins_path = Path(plugins_dir)

    all_plugins = discover_plugins(plugins_path)

    if plugin_patterns:
        plugins = filter_plugins(all_plugins, plugin_patterns)
        if not plugins:
            patterns_str = ", ".join(plugin_patterns)
            click.secho(
                f"ERROR: no plugins matched pattern(s): {patterns_str}",
                fg="red",
                err=True,
            )
            raise SystemExit(1)
        names = ", ".join(p.name for p in plugins)
        click.echo(f"Filtering to {len(plugins)}/{len(all_plugins)} plugins: {names}")
    else:
        plugins = all_plugins

    plugin_entries = _discover_plugin_entries(plugins)

    # Step 1: Generate
    click.echo("\n[1/3] Generating routing test cases...")
    tests, rc = generate_test_cases(plugins_path, plugins=plugins)
    if rc != 0:
        raise SystemExit(1)

    # Step 2: Coverage check
    click.echo("\n[2/3] Checking eval coverage...")
    _, cov_rc = check_coverage(plugins_path, coverage_threshold, plugins=plugins)
    if cov_rc != 0:
        raise SystemExit(1)

    # Step 3: Eval runner
    if threshold <= 0:
        click.echo("\n[3/3] Skipping routing evals (--threshold 0).")
        raise SystemExit(0)

    if not tests:
        click.secho("No test cases generated — nothing to run.", fg="yellow", err=True)
        raise SystemExit(0)

    click.echo("\n[3/3] Running routing evals...")

    loop = asyncio.new_event_loop()

    def _exc_handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
        exc = context.get("exception")
        if isinstance(exc, RuntimeError) and "cancel scope" in str(exc):
            return
        loop.default_exception_handler(context)

    loop.set_exception_handler(_exc_handler)
    try:
        rc = loop.run_until_complete(
            run_all(
                tests,
                plugin_entries,
                workers,
                timeout,
                max_retries,
                threshold,
                max_turns,
                cwd=str(plugins_path.resolve()),
            )
        )
    finally:
        loop.close()

    raise SystemExit(rc)


@main.command()
@click.option(
    "--plugins-dir",
    default="plugins/",
    show_default=True,
    help="Path to plugins directory.",
)
@click.option(
    "--output",
    default="overlap-report.json",
    show_default=True,
    help="Output JSON report path.",
)
@click.option(
    "--model",
    default=None,
    help="Model to use for analysis (overrides ANTHROPIC_MODEL env var).",
)
@click.option(
    "--plugin",
    "plugin_patterns",
    multiple=True,
    metavar="PATTERN",
    help="Glob filter on plugin name. Repeatable: --plugin 'git-*' --plugin 'slack-*'. OR semantics.",
)
@click.option(
    "--new-skill",
    "new_skill_paths",
    multiple=True,
    metavar="PATH",
    help="Path to a new skill directory. Repeatable. Enables PR-aware mode.",
)
@click.option(
    "--format",
    "output_format",
    default="json",
    type=click.Choice(["json", "github"]),
    show_default=True,
    help="Output format: json writes file, github prints markdown to stdout.",
)
def overlap(
    plugins_dir: str,
    output: str,
    model: str | None,
    plugin_patterns: tuple[str, ...],
    new_skill_paths: tuple[str, ...],
    output_format: str,
) -> None:
    """Detect functional skill overlap across marketplace plugins."""
    from .discover import discover_plugins, filter_plugins
    from .overlap import detect_overlap, format_github_comment

    plugins_path = Path(plugins_dir)
    output_path = Path(output)

    if not plugins_path.is_dir():
        click.secho(f"ERROR: plugins dir not found: {plugins_path}", fg="red", err=True)
        raise SystemExit(1)

    # Validate --new-skill paths
    for nsp in new_skill_paths:
        skill_dir = Path(nsp)
        if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").exists():
            click.secho(
                f"ERROR: --new-skill path must be a directory containing SKILL.md: {nsp}",
                fg="red",
                err=True,
            )
            raise SystemExit(1)

    all_plugins = discover_plugins(plugins_path)

    if plugin_patterns:
        plugins = filter_plugins(all_plugins, plugin_patterns)
        if not plugins:
            patterns_str = ", ".join(plugin_patterns)
            click.secho(
                f"ERROR: no plugins matched pattern(s): {patterns_str}",
                fg="red",
                err=True,
            )
            raise SystemExit(1)
        names = ", ".join(p.name for p in plugins)
        click.echo(f"Filtering to {len(plugins)}/{len(all_plugins)} plugins: {names}")
    else:
        plugins = all_plugins

    click.echo(f"Analyzing skills in {plugins_path}...", err=True)
    report = detect_overlap(
        plugins_path,
        output_path,
        model=model,
        plugins=plugins,
        new_skill_paths=list(new_skill_paths) if new_skill_paths else None,
    )

    click.echo(f"\nReport written to: {output_path}", err=True)
    click.echo(f"Skills analyzed: {report.total_skills_analyzed}", err=True)
    click.echo(f"Findings: {report.total_findings}", err=True)

    if output_format == "github":
        click.echo(format_github_comment(report))

    if report.findings:
        by_severity: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
        for f in report.findings:
            by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        for sev, count in by_severity.items():
            if count:
                click.echo(f"  {sev}: {count}", err=True)

        # Exit code logic differs by mode
        if new_skill_paths:
            # PR-aware mode: exit 1 only if any HIGH severity
            if any(f.severity == "high" for f in report.findings):
                click.secho(
                    "\nFAILED: high-severity overlap detected.",
                    fg="red",
                    err=True,
                )
                raise SystemExit(1)
            click.echo("\nPASSED: no high-severity overlaps (warnings only).", err=True)
        else:
            # Full-scan mode: exit 1 if ANY findings
            click.secho(
                "\nFAILED: functional overlaps detected — review catalog health.",
                fg="red",
                err=True,
            )
            raise SystemExit(1)
    else:
        click.echo("\nPASSED: no functional overlaps detected.", err=True)
