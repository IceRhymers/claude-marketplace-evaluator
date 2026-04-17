# claude-marketplace-evaluator

CLI for Claude Code marketplace health — routing evals, coverage checks, and semantic collision detection.

## Install

```bash
pip install claude-marketplace-evaluator
# or with uv:
uv add claude-marketplace-evaluator
```

## Usage

```bash
# Check routing eval coverage and pass rate
cme routing --plugins-dir plugins/ --coverage-threshold 100 --threshold 95

# Detect semantic skill overlap
cme overlap --plugins-dir plugins/ --output overlap-report.json
```

## Environment Variables

| Variable | Description | Required |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key | One of these |
| `ANTHROPIC_AUTH_TOKEN` | Databricks AI Gateway token | One of these |
| `ANTHROPIC_BASE_URL` | Custom base URL (Databricks AI Gateway) | If using Gateway |
| `ANTHROPIC_MODEL` | Model override | Optional |

## Development

```bash
uv sync
pre-commit install
make check   # lint + format + typecheck
make test    # pytest
```
