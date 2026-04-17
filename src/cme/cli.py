"""CLI entrypoint for cme (claude-marketplace-evaluator)."""

from __future__ import annotations

import click


@click.group()
@click.version_option()
def main() -> None:
    """Claude Code marketplace health CLI."""


@main.command()
def routing() -> None:
    """Run routing evals: coverage check + skill routing pass rate."""
    click.echo("not implemented")


@main.command()
def overlap() -> None:
    """Run semantic overlap detection across marketplace skills."""
    click.echo("not implemented")
