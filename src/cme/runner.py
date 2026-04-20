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
from claude_agent_sdk.types import (
    SdkPluginConfig,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from .models import TestCase, TestResult

logger = logging.getLogger("cme.runner")


def _configure_debug_logging() -> None:
    """Attach a stderr handler at INFO level when CME_DEBUG is set.

    Without this, logger.info/logger.warning calls below go nowhere because
    nothing configures Python logging at runtime. Idempotent across calls.
    """
    if not os.environ.get("CME_DEBUG"):
        return
    if any(getattr(h, "_cme_debug", False) for h in logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    handler._cme_debug = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _truncate(s: str, limit: int = 240) -> str:
    s = s.replace("\n", " ")
    return s if len(s) <= limit else s[:limit] + "…"


def _debug_log_message(test_name: str, message: object) -> None:
    """Emit a one-line summary of each SDK message for debugging."""
    if isinstance(message, SystemMessage):
        data = message.data or {}
        if message.subtype == "init":
            plugins = [p.get("name") for p in data.get("plugins", [])]
            logger.info(
                "[%s] INIT model=%s plugins=%s skills=%s tools=%s",
                test_name,
                data.get("model"),
                plugins,
                data.get("skills", []),
                data.get("tools", []),
            )
        else:
            logger.info(
                "[%s] SYSTEM.%s %s",
                test_name,
                message.subtype,
                _truncate(str(data)),
            )
    elif isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, ThinkingBlock):
                logger.info("[%s] THINK %s", test_name, _truncate(block.thinking))
            elif isinstance(block, TextBlock):
                logger.info("[%s] TEXT %s", test_name, _truncate(block.text))
            elif isinstance(block, ToolUseBlock):
                logger.info(
                    "[%s] TOOL_USE %s input=%s",
                    test_name,
                    block.name,
                    _truncate(str(block.input)),
                )
    elif isinstance(message, UserMessage):
        for user_block in message.content:
            if isinstance(user_block, ToolResultBlock):
                logger.info(
                    "[%s] TOOL_RESULT error=%s %s",
                    test_name,
                    user_block.is_error,
                    _truncate(str(user_block.content)),
                )
    elif isinstance(message, ResultMessage):
        logger.info(
            "[%s] RESULT subtype=%s turns=%s error=%s stop=%s",
            test_name,
            message.subtype,
            message.num_turns,
            message.is_error,
            message.stop_reason,
        )


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


def _discover_plugin_entries(plugins: list) -> list[SdkPluginConfig]:
    """Convert PluginInfo list to SdkPluginConfig entries.

    Returns one SdkPluginConfig per plugin, with resolved
    absolute paths so the spawned CLI subprocess doesn't double-resolve
    them against its own cwd.
    """
    return [SdkPluginConfig(type="local", path=str(p.root_dir)) for p in plugins]


def _build_sdk_env() -> dict[str, str]:
    # Pass the caller's environment through unchanged so any auth configuration
    # (ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, CLAUDE_CODE_OAUTH_TOKEN, etc.)
    # reaches the CLI without cme introducing collisions.
    # Plugin isolation is handled by setting_sources=[] in ClaudeAgentOptions,
    # which skips the user settings source and the global plugin registry.
    return dict(os.environ)


async def _run_prompt(
    prompt: str,
    test: TestCase,
    plugin_entries: list[SdkPluginConfig],
    max_retries: int = 5,
    max_turns: int = 5,
    cwd: str | None = None,
) -> tuple[list[str], dict]:
    sdk_env = _build_sdk_env()
    extra_args: dict[str, str | None] = {}
    if os.environ.get("CME_DEBUG"):
        extra_args["debug"] = "api,hooks"
    effective_turns = test.max_turns if test.max_turns is not None else max_turns
    options = ClaudeAgentOptions(
        plugins=plugin_entries,
        allowed_tools=["Skill", "Read", "Glob", "Grep"],
        disallowed_tools=[
            "Bash",
            "Write",
            "Edit",
            "NotebookEdit",
            "WebFetch",
            "WebSearch",
            "TodoWrite",
            "Task",
            "AskUserQuestion",
            "ToolSearch",
            "EnterPlanMode",
            "ExitPlanMode",
            "EnterWorktree",
            "ExitWorktree",
            "CronCreate",
            "CronDelete",
            "CronList",
            "Monitor",
            "PushNotification",
            "RemoteTrigger",
            "ScheduleWakeup",
            "TaskOutput",
            "TaskStop",
        ],
        mcp_servers={},
        permission_mode="bypassPermissions",
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": (
                "If a skill matches the request, invoke it immediately via the "
                "Skill tool on your very first turn. Do not read files, run "
                "commands, or explore the workspace before invoking the skill. "
                "Never ask clarifying questions."
            ),
        },
        setting_sources=[],
        max_turns=effective_turns,
        model=test.model,
        cwd=cwd or os.getcwd(),
        env=sdk_env,
        stderr=lambda line: logger.warning("CLI[%s] %s", test.name, line),
        extra_args=extra_args,
    )

    debug = bool(os.environ.get("CME_DEBUG"))

    for attempt in range(max_retries + 1):
        try:
            skills_invoked: list[str] = []
            result_info: dict = {}
            pass_met = False

            async for message in query(prompt=prompt, options=options):
                if debug:
                    _debug_log_message(test.name, message)
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
    plugin_entries: list[SdkPluginConfig],
    timeout: int = 30,
    max_retries: int = 5,
    max_turns: int = 5,
    cwd: str | None = None,
) -> TestResult:
    try:
        skills_invoked, _ = await asyncio.wait_for(
            _run_prompt(
                test.prompt, test, plugin_entries, max_retries, max_turns, cwd=cwd
            ),
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
    plugin_entries: list[SdkPluginConfig],
    workers: int = 4,
    timeout: int = 30,
    max_retries: int = 5,
    threshold: float = 95.0,
    max_turns: int = 5,
    cwd: str | None = None,
) -> int:
    """Run all tests, print summary, return exit code."""
    _configure_debug_logging()
    print(f"Running {len(tests)} routing eval(s) with {workers} worker(s)...")
    semaphore = asyncio.Semaphore(workers)

    async def bounded(test: TestCase) -> TestResult:
        async with semaphore:
            return await run_test(
                test, plugin_entries, timeout, max_retries, max_turns, cwd=cwd
            )

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
