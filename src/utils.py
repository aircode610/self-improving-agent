"""Shared logging + agent runner with live progress output."""

import time
from collections.abc import AsyncIterator
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    query,
)

# Try to import message types for tool-call logging
try:
    from claude_agent_sdk import AssistantMessage
    _HAS_ASSISTANT = True
except ImportError:
    _HAS_ASSISTANT = False


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    return f"{seconds/60:.1f}m"


async def run_agent(
    label: str,
    prompt: str,
    options: ClaudeAgentOptions,
    log_tools: bool = True,
) -> str:
    """
    Run a claude-agent-sdk query with live logging.

    Prints:
      [label] starting...
      [label]   → ToolName: brief args
      [label] done in 42s

    Returns the ResultMessage.result string (or "" if none).
    """
    start = time.monotonic()
    print(f"  [{label}] starting...")
    result_text = ""
    tool_count = 0

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            result_text = message.result or ""
        elif _HAS_ASSISTANT and isinstance(message, AssistantMessage):
            if log_tools:
                for block in message.content:
                    btype = getattr(block, "type", None)
                    if btype == "tool_use":
                        tool_count += 1
                        name = getattr(block, "name", "?")
                        inp = getattr(block, "input", {}) or {}
                        # pick the most informative arg to show
                        arg = (
                            inp.get("path")
                            or inp.get("file_path")
                            or inp.get("command")
                            or inp.get("query")
                            or inp.get("owner", "") and f"{inp.get('owner')}/{inp.get('repo')} #{inp.get('pullNumber','')}"
                            or ""
                        )
                        short_arg = str(arg)[:60]
                        print(f"  [{label}]   → {name}({short_arg})")

    elapsed = time.monotonic() - start
    print(f"  [{label}] done in {_fmt_duration(elapsed)} ({tool_count} tool calls)")
    return result_text
