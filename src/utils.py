"""Shared logging + agent runner with live progress output and transcript capture."""

import dataclasses
import json
import sys
import time
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    query,
)

# Patterns that identify Claude Code's internal skill-improvement hook errors.
# These fire on every Write/Edit tool call inside subagent processes and are
# harmless but noisy — filter them before they reach the terminal.
_HOOK_NOISE = (
    "Error in hook callback",
    "skill_improvement_apply",
    "/$bunfs/root/src/entrypoints/cli.js",
    "Stream closed\n",
)


def _stderr_filter(line: str) -> None:
    """Write stderr line to terminal, dropping known Claude Code internal hook errors."""
    if any(pattern in line for pattern in _HOOK_NOISE):
        return
    sys.stderr.write(line)
    sys.stderr.flush()


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    return f"{seconds/60:.1f}m"


async def run_agent(
    label: str,
    prompt: str,
    options: ClaudeAgentOptions,
    transcript_path: str | None = None,
) -> str:
    """
    Run a claude-agent-sdk query with live logging and optional transcript capture.

    Prints:
      [label] starting...
      [label]   → ToolName(brief_arg)
      [label] done in 42s (N tool calls)

    If transcript_path is provided, writes a markdown execution transcript there.

    Returns the ResultMessage.result string (or "" if none).
    """
    start = time.monotonic()
    print(f"  [{label}] starting...")
    result_text = ""
    tool_count = 0
    steps: list[str] = []

    async def _log_hook(input_data: dict, tool_use_id: str, context: Any) -> dict:
        nonlocal tool_count
        tool_count += 1
        name = input_data.get("tool_name", "?")
        inp = input_data.get("tool_input", {}) or {}
        arg = (
            inp.get("path")
            or inp.get("file_path")
            or inp.get("command")
            or inp.get("query")
            or (
                inp.get("owner")
                and f"{inp.get('owner')}/{inp.get('repo')} #{inp.get('pullNumber', '')}"
            )
            or ""
        )
        print(f"  [{label}]   → {name}({str(arg)[:60]})")

        # Capture step for transcript
        inp_repr = json.dumps(inp, default=str)
        if len(inp_repr) > 600:
            inp_repr = inp_repr[:600] + "..."
        steps.append(f"### Step {tool_count} — {name}\n**Input**: `{inp_repr}`\n")
        return {}

    # Inject our logging hook alongside any existing hooks
    existing_hooks: dict = getattr(options, "hooks", None) or {}
    merged_post = list(existing_hooks.get("PostToolUse", []))
    merged_post.append(HookMatcher(matcher=".*", hooks=[_log_hook]))
    merged_hooks = {**existing_hooks, "PostToolUse": merged_post}

    try:
        hook_options = dataclasses.replace(options, hooks=merged_hooks, stderr=_stderr_filter)
    except Exception:
        hook_options = options  # fallback: run without hook logging or filtering

    async for message in query(prompt=prompt, options=hook_options):
        if isinstance(message, ResultMessage):
            result_text = message.result or ""

    elapsed = time.monotonic() - start
    print(f"  [{label}] done in {_fmt_duration(elapsed)} ({tool_count} tool calls)")

    # Write transcript if requested
    if transcript_path:
        _write_transcript(label, prompt, steps, result_text, transcript_path)

    return result_text


def _write_transcript(
    label: str,
    prompt: str,
    steps: list[str],
    result: str,
    transcript_path: str,
) -> None:
    """Write a markdown execution transcript for use by the grader."""
    path = Path(transcript_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    prompt_excerpt = prompt[:3000] + ("..." if len(prompt) > 3000 else "")
    steps_text = "\n".join(steps) if steps else "_No tool calls recorded._\n"

    transcript = (
        f"# Execution Transcript: {label}\n\n"
        f"## Prompt\n```\n{prompt_excerpt}\n```\n\n"
        f"## Steps ({len(steps)} tool calls)\n\n"
        f"{steps_text}\n"
        f"## Result\n{result}\n"
    )
    path.write_text(transcript)
