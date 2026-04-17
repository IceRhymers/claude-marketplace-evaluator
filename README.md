# claude-marketplace-evaluator

`cme` is a CLI for Claude Code marketplace health. It validates that skills route correctly and detects semantic collisions between skills — without running expensive LLM-based eval suites.

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

Exit codes: `0` = all checks pass, `1` = coverage or routing threshold not met.

### `cme overlap`

Detects semantic collisions between skills across a marketplace. Two skills collide when their descriptions or trigger queries are similar enough to confuse Claude's routing. Uses an LLM to analyze all skill pairs and produces a JSON report with `severity: high | medium | low` collision pairs.

```bash
cme overlap --plugins-dir plugins/ --output overlap-report.json
```

| Flag | Default | Description |
|---|---|---|
| `--plugins-dir` | `plugins/` | Path to the plugins directory |
| `--output` | `overlap-report.json` | Output path for the JSON collision report |
| `--model` | `claude-sonnet-4-5` | Model for analysis (overrides `ANTHROPIC_MODEL` env var) |

Exit codes: `0` = no collisions, `1` = collisions detected.

The output report structure:

```json
{
  "timestamp": "2026-04-17T00:00:00+00:00",
  "model_used": "claude-sonnet-4-5",
  "total_skills_analyzed": 6,
  "total_collisions": 1,
  "collisions": [
    {
      "skill_a": "plugins/my-plugin/skills/create-pr",
      "skill_b": "plugins/my-plugin/skills/submit-pr",
      "overlapping_triggers": ["open a pull request"],
      "description_excerpts": ["Both skills handle PR creation workflows"],
      "severity": "high"
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

### LLM proxy (Databricks AI Gateway, etc.)

For routing through Databricks AI Gateway or other LLM proxies:

```bash
export ANTHROPIC_AUTH_TOKEN="dapi..."
export ANTHROPIC_BASE_URL="https://your-workspace.databricks.com/serving-endpoints/your-endpoint/invocations"
export ANTHROPIC_MODEL="databricks-claude-sonnet"
cme routing --plugins-dir plugins/
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
          uvx --from claude-marketplace-evaluator cme overlap --plugins-dir plugins/ --output overlap-report.json
          EXIT_CODE=$?
          if [ -f overlap-report.json ]; then
            echo "## Overlap Report" >> "$GITHUB_STEP_SUMMARY"
            echo '```json' >> "$GITHUB_STEP_SUMMARY"
            cat overlap-report.json >> "$GITHUB_STEP_SUMMARY"
            echo '```' >> "$GITHUB_STEP_SUMMARY"
            cat overlap-report.json
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
          uvx --from claude-marketplace-evaluator cme overlap --plugins-dir plugins/ --output overlap-report.json
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
            const path = 'overlap-report.json';
            if (!fs.existsSync(path)) return;

            const report = JSON.parse(fs.readFileSync(path, 'utf8'));
            const collisions = report.collisions || [];

            let body = '## Skill Overlap Report\n\n';
            body += `**Skills analyzed:** ${report.total_skills_analyzed}\n`;
            body += `**Collisions found:** ${report.total_collisions}\n\n`;

            if (collisions.length === 0) {
              body += '✅ No semantic collisions detected.\n';
            } else {
              body += '| Severity | Skill A | Skill B | Overlapping Triggers |\n';
              body += '|----------|---------|---------|---------------------|\n';
              for (const c of collisions) {
                const triggers = c.overlapping_triggers.join(', ');
                body += `| ${c.severity.toUpperCase()} | \`${c.skill_a}\` | \`${c.skill_b}\` | ${triggers} |\n`;
              }
              body += '\nResolve collisions before merging. Rename skills, narrow descriptions, or deduplicate functionality.\n';
            }

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
