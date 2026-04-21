# claude-marketplace-evaluator

`cme` is a CLI for Claude Code marketplace health. It validates that skills route correctly and detects functional overlap between skills — without running expensive LLM-based eval suites.

Marketplace health is not about optimizing skill descriptions. It is about catching structural problems early: missing evals, broken routing, and overlapping skills that confuse Claude's router. `cme` runs fast, fits in CI, and fails loud.

## Installation

Zero-install with `uvx` (recommended for CI):

```bash
uvx --from claude-marketplace-evaluator cme --help
```

Or install globally:

```bash
pip install claude-marketplace-evaluator
```

## Commands

### `cme routing`

Three-step pipeline that generates routing tests, checks coverage, and runs evals:

1. **Generate** — reads `evals/evals.json` from each skill directory, produces routing test YAML
2. **Coverage check** — verifies every skill has an evals file (fails if below threshold)
3. **Routing eval runner** — sends each prompt through the Claude Agent SDK, checks Claude routes to the expected skill

```bash
cme routing --plugins-dir plugins/
```

| Flag | Default | Description |
|---|---|---|
| `--plugins-dir` | `plugins/` | Path to the plugins directory |
| `--coverage-threshold` | `100` | Minimum eval coverage percentage. Fails if any skill lacks evals |
| `--threshold` | `95` | Minimum routing pass rate percentage. Set to `0` to skip the eval runner |
| `-j` / `--workers` | `4` | Parallel workers for the eval runner |
| `--timeout` | `30` | Per-test timeout in seconds |
| `--max-retries` | `1` | Max retries on rate limit errors (exponential backoff) |
| `--max-turns` | `5` | Max agent turns per routing eval. Individual test cases can override this with a `max_turns` field in `evals.json` |
| `--plugin` | | Glob filter on plugin name. Repeatable with OR semantics |

Exit codes: `0` = all checks pass, `1` = coverage or routing threshold not met.

### `cme overlap`

Detects functional overlap between skills across a marketplace. Two skills overlap when they perform the same action, produce the same output, or serve the same purpose — regardless of how they are triggered. Uses an LLM to analyze skill descriptions and `allowed-tools` and produces a JSON report with `severity: high | medium | low` findings.

Supports two modes:
- **Full-scan** (default): analyzes all skill pairs. Best for scheduled audits.
- **PR-aware** (`--new-skill`): checks only new skills against the existing catalog. Best for CI on pull requests.

```bash
# Full-scan (scheduled audit)
cme overlap --plugins-dir plugins/ --output overlap-report.json

# PR-aware (CI on new skill)
cme overlap --plugins-dir plugins/ --new-skill plugins/my-plugin/skills/new-skill --format github
```

| Flag | Default | Description |
|---|---|---|
| `--plugins-dir` | `plugins/` | Path to the plugins directory |
| `--output` | `overlap-report.json` | Output path for the JSON report |
| `--model` | `claude-sonnet-4-5` | Model for analysis (overrides `ANTHROPIC_MODEL` env var) |
| `--plugin` | | Glob filter on plugin name. Repeatable with OR semantics |
| `--new-skill` | | Path to a new skill directory. Repeatable. Enables PR-aware mode |
| `--format` | `json` | Output format: `json` writes file, `github` prints markdown to stdout |

Exit codes:
- **Full-scan mode**: `0` = no findings, `1` = any finding (HIGH, MEDIUM, or LOW)
- **PR-aware mode**: `0` = no HIGH findings, `1` = at least one HIGH finding

> **Note:** Due to LLM non-determinism in severity classification, we recommend running `cme overlap` (full-scan) on a scheduled cron rather than relying solely on PR-aware CI.

The output report structure:

```json
{
  "timestamp": "2026-04-17T00:00:00+00:00",
  "model_used": "claude-sonnet-4-5",
  "mode": "full-scan",
  "total_skills_analyzed": 6,
  "new_skills_checked": 0,
  "total_findings": 1,
  "findings": [
    {
      "skill_a": "plugins/my-plugin/skills/create-pr",
      "skill_b": "plugins/my-plugin/skills/submit-pr",
      "functional_summary": "Both skills create GitHub pull requests from the current branch.",
      "shared_tools": ["Bash", "Read"],
      "severity": "high",
      "recommendation": "Merge into a single create-pr skill.",
      "explanation": "These skills perform identical actions — pushing a branch and opening a PR via gh CLI. A user would get the same result from either."
    }
  ]
}
```

## Plugin Layout

`cme` expects this directory structure:

```
plugins/
  <plugin-name>/
    skills/
      <skill-name>/
        SKILL.md
        evals/
          evals.json
```

Each `evals.json` is a JSON array of routing test entries:

```json
[
  { "query": "Run the test suite for this project", "should_trigger": true },
  { "query": "Can you execute the unit tests?", "should_trigger": true },
  { "query": "Open a pull request for this branch", "should_trigger": false }
]
```

| Field | Type | Description |
|---|---|---|
| `query` | string | A user prompt to test routing against |
| `should_trigger` | boolean | `true` = this prompt should route to this skill, `false` = it should not |

Only `should_trigger: true` entries are used to generate routing test cases. Include `should_trigger: false` entries to document negative cases (used by overlap detection for trigger context).

## Authentication

`cme` does not manage credentials. It passes through environment variables to the Claude Agent SDK. Configure one of these auth modes:

### Claude subscription (OAuth)

For users with a Claude Pro/Team/Enterprise subscription:

```bash
claude setup-token              # generates the token
export CLAUDE_CODE_OAUTH_TOKEN="your-token"
cme routing --plugins-dir plugins/
```

### Direct API key

For direct Anthropic API access:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
cme routing --plugins-dir plugins/
```

### Databricks AI Gateway

For routing through Databricks AI Gateway, map your workspace secrets to the standard Anthropic SDK env vars:

```bash
export ANTHROPIC_AUTH_TOKEN="<DATABRICKS_SP_TOKEN>"           # service principal PAT
export ANTHROPIC_BASE_URL="<DATABRICKS_AI_GATEWAY_URL>"       # AI Gateway endpoint URL
export ANTHROPIC_MODEL="<DATABRICKS_AI_GATEWAY_MODEL>"        # endpoint model name
export ANTHROPIC_CUSTOM_HEADERS="x-databricks-use-coding-agent-mode: true"
export CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS="1"
export CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING=""
cme routing --plugins-dir plugins/
```

In GitHub Actions, these map directly from repository secrets:

```yaml
env:
  ANTHROPIC_AUTH_TOKEN: ${{ secrets.DATABRICKS_SP_TOKEN }}
  ANTHROPIC_BASE_URL: ${{ secrets.DATABRICKS_AI_GATEWAY_URL }}
  ANTHROPIC_MODEL: ${{ secrets.DATABRICKS_AI_GATEWAY_MODEL }}
  ANTHROPIC_CUSTOM_HEADERS: "x-databricks-use-coding-agent-mode: true"
  CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS: "1"
  CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING: ""
```

## CI/CD Integration

### GitHub Actions workflow

This is a production workflow from [claude-marketplace-builder](https://github.com/IceRhymers/claude-marketplace-builder) that runs both `cme routing` and `cme overlap` on every PR that touches plugin files:

```yaml
name: CME Checks

on:
  pull_request:
    paths:
      - "plugins/**"
      - "evals/**"
  workflow_dispatch:

jobs:
  coverage:
    runs-on: ubuntu-latest
    environment: cicd
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - name: Check eval coverage and routing
        env:
          ANTHROPIC_AUTH_TOKEN: ${{ secrets.DATABRICKS_SP_TOKEN }}
          ANTHROPIC_BASE_URL: ${{ secrets.DATABRICKS_AI_GATEWAY_URL }}
          ANTHROPIC_MODEL: ${{ secrets.DATABRICKS_AI_GATEWAY_MODEL }}
          ANTHROPIC_CUSTOM_HEADERS: "x-databricks-use-coding-agent-mode: true"
          CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS: "1"
        run: uvx --from claude-marketplace-evaluator cme routing --plugins-dir plugins/ --coverage-threshold 100 --threshold 95 --timeout 180

  overlap:
    runs-on: ubuntu-latest
    environment: cicd
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - name: Check skill overlap
        env:
          ANTHROPIC_AUTH_TOKEN: ${{ secrets.DATABRICKS_SP_TOKEN }}
          ANTHROPIC_BASE_URL: ${{ secrets.DATABRICKS_AI_GATEWAY_URL }}
          ANTHROPIC_MODEL: ${{ secrets.DATABRICKS_AI_GATEWAY_MODEL }}
          ANTHROPIC_CUSTOM_HEADERS: "x-databricks-use-coding-agent-mode: true"
          CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS: "1"
        run: |
          set +e
          uvx --from claude-marketplace-evaluator cme overlap --plugins-dir plugins/ --output overlap-report.json --format github
          EXIT_CODE=$?
          if [ -f overlap-report.json ]; then
            echo "## Overlap Report" >> "$GITHUB_STEP_SUMMARY"
            echo '```json' >> "$GITHUB_STEP_SUMMARY"
            cat overlap-report.json >> "$GITHUB_STEP_SUMMARY"
            echo '```' >> "$GITHUB_STEP_SUMMARY"
          fi
          exit $EXIT_CODE
```

### Posting overlap results as a PR comment

Extend the `overlap` job to post a formatted collision table as a PR comment using `actions/github-script`:

```yaml
  overlap:
    runs-on: ubuntu-latest
    environment: cicd
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - name: Check skill overlap
        id: overlap
        env:
          ANTHROPIC_AUTH_TOKEN: ${{ secrets.DATABRICKS_SP_TOKEN }}
          ANTHROPIC_BASE_URL: ${{ secrets.DATABRICKS_AI_GATEWAY_URL }}
          ANTHROPIC_MODEL: ${{ secrets.DATABRICKS_AI_GATEWAY_MODEL }}
          ANTHROPIC_CUSTOM_HEADERS: "x-databricks-use-coding-agent-mode: true"
          CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS: "1"
        run: |
          set +e
          uvx --from claude-marketplace-evaluator cme overlap --plugins-dir plugins/ --output overlap-report.json --format github > overlap-comment.md
          echo "exit_code=$?" >> "$GITHUB_OUTPUT"
          if [ -f overlap-report.json ]; then
            echo "## Overlap Report" >> "$GITHUB_STEP_SUMMARY"
            echo '```json' >> "$GITHUB_STEP_SUMMARY"
            cat overlap-report.json >> "$GITHUB_STEP_SUMMARY"
            echo '```' >> "$GITHUB_STEP_SUMMARY"
          fi

      - name: Comment on PR with overlap results
        if: always() && github.event_name == 'pull_request'
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const commentPath = 'overlap-comment.md';
            if (!fs.existsSync(commentPath)) return;

            const body = fs.readFileSync(commentPath, 'utf8').trim();
            if (!body) return;

            // Delete previous cme comments to avoid spam
            const { data: comments } = await github.rest.issues.listComments({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.issue.number,
            });
            for (const comment of comments) {
              if (comment.body.startsWith('## Skill Overlap Report')) {
                await github.rest.issues.deleteComment({
                  owner: context.repo.owner,
                  repo: context.repo.repo,
                  comment_id: comment.id,
                });
              }
            }

            await github.rest.issues.createComment({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.issue.number,
              body,
            });

      - name: Fail on collisions
        if: steps.overlap.outputs.exit_code != '0'
        run: exit 1
```

## Local Usage

Run against a local plugins directory:

```bash
# Coverage check only (skip routing evals)
cme routing --plugins-dir ./plugins --threshold 0

# Full routing pipeline
cme routing --plugins-dir ./plugins --timeout 60

# Overlap detection
cme overlap --plugins-dir ./plugins

# Increase parallelism for large marketplaces
cme routing --plugins-dir ./plugins -j 8 --timeout 120

# Run only plugins matching a pattern
cme routing --plugins-dir ./plugins --plugin "git-*"
cme routing --plugins-dir ./plugins --plugin "git-*" --plugin "slack-*"

# Increase max agent turns for complex multi-step skills
cme routing --plugins-dir ./plugins --max-turns 10

# Debug mode (verbose Agent SDK logging)
CME_DEBUG=1 cme routing --plugins-dir ./plugins
```

## Two-Tier Eval Strategy

`cme` is designed as the fast, structural first tier of a two-tier evaluation approach:

**Tier 1: `cme` (fast, free, structural)**
- Runs in seconds to minutes
- Coverage checks require zero LLM calls
- Routing evals use one short Agent SDK call per test case
- Catches missing evals, broken routing, and skill collisions
- Runs on every PR in CI

**Tier 2: Full LLM eval runners (deep, expensive)**
- Runs multi-turn conversations testing skill behavior end-to-end
- Validates output quality, not just routing correctness
- Costs significantly more in tokens and time
- Runs on release branches or nightly schedules

`cme` answers "did Claude pick the right skill?" — it does not answer "did the skill produce a good result?" Use tier 1 to gate PRs cheaply, then run tier 2 for deeper validation on release candidates.

## Development

```bash
uv sync
pre-commit install
make check   # lint + format + typecheck
make test    # pytest
```
