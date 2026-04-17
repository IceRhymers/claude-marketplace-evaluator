# claude-marketplace-evaluator

CLI (`cme`) for Claude Code marketplace health — routing evals, coverage checks, and semantic collision detection across plugin skill catalogs.

## Commands

```bash
uv sync                  # install all dependencies
make check               # lint + format-check + typecheck (run before every push)
make lint                # ruff check src/ tests/
make fmt                 # ruff format src/ tests/ (auto-fix)
make fmt-check           # ruff format --check (what CI runs)
make typecheck           # mypy src/
make test                # pytest tests/
make routing             # cme routing (run routing evals)
make overlap             # cme overlap (run semantic overlap detection)
```

**Always run `make check` before pushing.** CI enforces both `ruff check` and `ruff format --check` as separate steps.

## Pre-commit

Ruff hooks run automatically on every commit:

```bash
uv sync
pre-commit install
```

Runs `ruff check --fix` and `ruff format` before each commit.

## Adding CLI subcommands

All subcommands live in `src/cme/cli.py`. To add one:

```python
@main.command()
@click.option("--plugins-dir", default="plugins/", show_default=True, help="Path to plugins directory.")
def my_command(plugins_dir: str) -> None:
    """One-line description shown in --help."""
    ...
```

Conventions:
- Options use `--kebab-case` names
- Always include `show_default=True` for options with defaults
- Exit non-zero via `raise SystemExit(1)` or `ctx.exit(1)` on failure
- Use `click.echo()` for output, `click.secho(..., fg="red", err=True)` for errors

## Linting rules

- `ruff` with `select = ["E", "F", "I", "UP", "B", "SIM"]`, `ignore = ["E501"]`
- `isort` with `known-first-party = ["cme"]`
- `mypy` on `src/` only — `disallow_untyped_defs = true`
- Tests are not mypy-checked

## Test conventions

- Unit tests in `tests/` — use `click.testing.CliRunner` for CLI tests
- Integration tests in `tests/integration/` marked with `@pytest.mark.integration`
- Mock at the module level: `@patch("cme.module.dependency")`
- Every command should have: help text test, success path, failure/error path

## Issue / PR conventions

- Branch naming: `issue/<N>-<slug>` (e.g. `issue/2-routing-command`)
- Issue structure: Problem, Scope, Acceptance Criteria, Technical Notes, Dependencies
- Always create a GitHub issue before opening a PR
- Never push directly to `main` — branch → PR always

## Codebase exploration

The `sourcebot` MCP tool is available for searching and reading this codebase. Use `mcp__sourcebot__grep`, `mcp__sourcebot__read_file`, and `mcp__sourcebot__glob` for exploration instead of spawning shell commands when possible.
