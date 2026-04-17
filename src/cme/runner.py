"""Routing eval runner using the Anthropic Agent SDK."""

from __future__ import annotations

import asyncio
import logging
import os
import random
from pathlib import Path

import yaml
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    query,
)
from claude_agent_sdk.types import ToolUseBlock

from .models import TestCase, TestResult

logger = logging.getLogger("cme.runner")


def skill_matches(expected: str, invoked: set[str]) -> bool:
    if expected in invoked:
        return True
    expected_name = expected.split(":")[-1] if ":" in expected else expected
    for inv in invoked:
        inv_name = inv.split(":")[-1] if ":" in inv else inv
        if expected_name == inv_name:
            return True
    return False


def _check_pass(skills_invoked: list[str], test: TestCase) -> bool:
    if not skills_invoked:
        return False
    invoked_set = set(skills_invoked)
    if test.expected_skills:
        return all(skill_matches(exp, invoked_set) for exp in test.expected_skills)
    elif test.expected_skill_one_of:
        return any(
            skill_matches(exp, invoked_set) for exp in test.expected_skill_one_of
        )
    elif test.expected_skill:
        return skill_matches(test.expected_skill, invoked_set)
    return False


def _build_sdk_env() -> dict[str, str]:
    env = dict(os.environ)
    overrides = {
        "ANTHROPIC_AUTH_TOKEN": os.environ.get("ANTHROPIC_AUTH_TOKEN", ""),
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.environ.get("ANTHROPIC_API_KEY", ""),
        "ANTHROPIC_BASE_URL": os.environ.get("ANTHROPIC_BASE_URL", ""),
        "ANTHROPIC_MODEL": os.environ.get("ANTHROPIC_MODEL", ""),
        "ANTHROPIC_CUSTOM_HEADERS": os.environ.get(
            "ANTHROPIC_CUSTOM_HEADERS", "x-databricks-use-coding-agent-mode: true"
        ),
        "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": os.environ.get(
            "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS", "1"
        ),
        "CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING": os.environ.get(
            "CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING", ""
        ),
    }
    env.update({k: v for k, v in overrides.items() if v != ""})
    return env


async def _run_prompt(
    prompt: str,
    test: TestCase,
    plugins_dir: Path,
    max_retries: int = 5,
) -> tuple[list[str], dict]:
    sdk_env = _build_sdk_env()
    options = ClaudeAgentOptions(
        plugins=[{"type": "local", "path": str(plugins_dir)}],
        allowed_tools=["Skill", "Read", "Glob", "Grep", "Bash"],
        permission_mode="bypassPermissions",
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": "Never ask clarifying questions. Invoke skills directly.",
        },
        setting_sources=["project"],
        max_turns=test.max_turns,
        model=test.model,
        cwd=str(plugins_dir),
        env=sdk_env,
    )

    for attempt in range(max_retries + 1):
        try:
            skills_invoked: list[str] = []
            result_info: dict = {}
            pass_met = False

            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock) and block.name == "Skill":
                            skill_name = block.input.get("skill", "")
                            if skill_name:
                                skills_invoked.append(skill_name)
                                if _check_pass(skills_invoked, test):
                                    pass_met = True
                                    break
                    if pass_met:
                        break
                elif isinstance(message, ResultMessage):
                    result_info = {
                        "session_id": message.session_id,
                        "num_turns": message.num_turns,
                        "is_error": message.is_error,
                        "early_exit": pass_met,
                    }

            return skills_invoked, result_info

        except Exception as exc:
            if "rate_limit" in str(exc).lower() and attempt < max_retries:
                delay = (2**attempt) + random.uniform(0, 1)
                logger.warning("Rate limit, retrying in %.1fs...", delay)
                await asyncio.sleep(delay)
            else:
                raise

    raise RuntimeError("Exhausted retries")


async def run_test(
    test: TestCase,
    plugins_dir: Path,
    timeout: int = 30,
    max_retries: int = 5,
) -> TestResult:
    try:
        skills_invoked, _ = await asyncio.wait_for(
            _run_prompt(test.prompt, test, plugins_dir, max_retries),
            timeout=timeout,
        )
    except TimeoutError:
        return TestResult(
            name=test.name,
            passed=False,
            expected="completion",
            actual="timeout",
            error=f"Timed out after {timeout}s",
        )
    except Exception as e:
        return TestResult(
            name=test.name,
            passed=False,
            expected="completion",
            actual="error",
            error=str(e),
        )

    invoked_set = set(skills_invoked)

    if test.expected_skills:
        passed = all(skill_matches(exp, invoked_set) for exp in test.expected_skills)
        expected = f"all of {test.expected_skills}"
    elif test.expected_skill_one_of:
        passed = any(
            skill_matches(exp, invoked_set) for exp in test.expected_skill_one_of
        )
        expected = f"one of {test.expected_skill_one_of}"
    elif test.expected_skill:
        passed = skill_matches(test.expected_skill, invoked_set)
        expected = test.expected_skill
    else:
        passed = len(skills_invoked) == 0
        expected = "null"

    actual = ", ".join(skills_invoked) if skills_invoked else "null"
    return TestResult(name=test.name, passed=passed, expected=expected, actual=actual)


async def run_all(
    tests: list[TestCase],
    plugins_dir: Path,
    workers: int = 4,
    timeout: int = 30,
    max_retries: int = 5,
    threshold: float = 95.0,
) -> int:
    """Run all tests, print summary, return exit code."""
    print(f"Running {len(tests)} routing eval(s) with {workers} worker(s)...")
    semaphore = asyncio.Semaphore(workers)

    async def bounded(test: TestCase) -> TestResult:
        async with semaphore:
            return await run_test(test, plugins_dir, timeout, max_retries)

    results = await asyncio.gather(*[bounded(t) for t in tests], return_exceptions=True)

    final: list[TestResult] = []
    for i, r in enumerate(results):
        if isinstance(r, BaseException):
            final.append(
                TestResult(
                    name=tests[i].name,
                    passed=False,
                    expected="completion",
                    actual="error",
                    error=str(r),
                )
            )
        else:
            final.append(r)
        status = "PASS" if final[-1].passed else "FAIL"
        print(f"  {final[-1].name}: {status}")

    passed = sum(1 for r in final if r.passed)
    total = len(final)
    pct = passed / total * 100 if total else 0.0

    print(f"\n{'=' * 50}")
    print(f"Results: {passed}/{total} passed ({pct:.1f}%)")

    if pct < threshold:
        failed = [r for r in final if not r.passed]
        print(f"\nFAILED ({pct:.1f}% < {threshold}% threshold)")
        for r in failed:
            print(f"  - {r.name}: expected '{r.expected}', got '{r.actual}'")
            if r.error:
                print(f"    Error: {r.error}")
        return 1

    print(f"\nPASSED ({pct:.1f}% >= {threshold}% threshold)")
    return 0


def load_test_cases(yaml_path: Path) -> list[TestCase]:
    with open(yaml_path) as f:
        suite = yaml.safe_load(f)
    tests = suite.get("tests") if suite else None
    if not tests:
        return []
    return [TestCase(**t) for t in tests]
