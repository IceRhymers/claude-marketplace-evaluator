"""CLI entrypoint for cme (claude-marketplace-evaluator)."""

from __future__ import annotations

import asyncio
import tempfile
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
def routing(
    plugins_dir: str,
    coverage_threshold: float,
    threshold: float,
    workers: int,
    timeout: int,
    max_retries: int,
) -> None:
    """Run routing evals: generate → coverage check → eval runner."""
    from .coverage import check_coverage
    from .generate import generate
    from .runner import load_test_cases, run_all

    plugins_path = Path(plugins_dir)

    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)

        # Step 1: Generate
        click.echo("\n[1/3] Generating routing test cases...")
        rc = generate(plugins_path, out_dir)
        if rc != 0:
            raise SystemExit(1)

        # Step 2: Coverage check
        click.echo("\n[2/3] Checking eval coverage...")
        _, cov_rc = check_coverage(plugins_path, coverage_threshold)
        if cov_rc != 0:
            raise SystemExit(1)

        # Step 3: Eval runner
        all_yaml = out_dir / "all.yaml"
        if not all_yaml.exists():
            click.secho(
                "No test cases generated — nothing to run.", fg="yellow", err=True
            )
            raise SystemExit(0)

        click.echo("\n[3/3] Running routing evals...")
        tests = load_test_cases(all_yaml)

        if not tests:
            click.secho(
                "No test cases generated — nothing to run.", fg="yellow", err=True
            )
            raise SystemExit(0)

        loop = asyncio.new_event_loop()

        def _exc_handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
            exc = context.get("exception")
            if isinstance(exc, RuntimeError) and "cancel scope" in str(exc):
                return
            loop.default_exception_handler(context)

        loop.set_exception_handler(_exc_handler)
        try:
            rc = loop.run_until_complete(
                run_all(tests, plugins_path, workers, timeout, max_retries, threshold)
            )
        finally:
            loop.close()

        raise SystemExit(rc)


@main.command()
def overlap() -> None:
    """Run semantic overlap detection across marketplace skills."""
    click.echo("not implemented")
