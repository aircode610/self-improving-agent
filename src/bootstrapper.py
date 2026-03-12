"""Bootstrap agent: scans a GitHub repo via MCP and writes initial PR review skills."""

import os
from pathlib import Path

import anyio
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage


SKILLS_DIR = Path(__file__).parent.parent / "skills" / "pr-review"


async def run_bootstrapper(owner: str, repo: str, github_mcp_config: dict) -> None:
    """Scan owner/repo via GitHub MCP and write initial review skills to skills/pr-review/."""

    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    project_root = str(Path(__file__).parent.parent)

    prompt = f"""Analyze the repository {owner}/{repo} to create PR review skills.

Use the GitHub MCP tools to thoroughly understand the codebase:

1. Use get_repository to read repo metadata (language, description, topics, default branch)
2. Use get_file_contents on the root directory to see the project structure
3. Use get_file_contents to read: README.md, package.json/pyproject.toml/go.mod/pom.xml/Cargo.toml (whichever exists), any CONTRIBUTING.md, PR templates (.github/PULL_REQUEST_TEMPLATE.md), .github/workflows/, key config files (eslint, prettier, mypy, etc.)
4. Use get_file_contents to read 3-5 representative source files to understand code patterns
5. Use search_code to find patterns: error handling conventions, auth/validation patterns, test file naming, logging patterns
6. Use list_commits to see recent commit messages and understand change patterns

Then create these files locally using the Write tool:

**File 1: skills/pr-review/SKILL.md**
Write YAML frontmatter with name and description, then detailed PR review instructions specific to THIS repo.
Include:
- Architecture overview (what the repo actually is)
- Tech stack specifics (exact framework versions, conventions you found)
- What to check: broken into categories (correctness, style, security, tests, etc.)
- Repo-specific patterns to look for (e.g., if it's FastAPI: check dependency injection; if React: check hooks rules)
- Common mistake patterns you noticed from the code
- Reference to repo-conventions.md and common-issues.md

**File 2: skills/pr-review/repo-conventions.md**
Specific coding conventions you found in the repo:
- Naming patterns (files, functions, variables, classes)
- Import ordering/grouping conventions
- Error handling patterns (how errors are thrown/handled/logged)
- Test patterns (test file locations, test naming, fixture patterns)
- Any project-specific rules from config files

**File 3: skills/pr-review/common-issues.md**
Start with a placeholder — this file grows from grader feedback:
```
# Common Issues

This file grows over time as the grader identifies patterns the reviewer misses.

## Known Pitfalls

(None yet — will be populated after the first reviews are graded)
```

Be specific to THIS repo. Reference actual file paths, class names, and patterns you found.
Do not write generic advice that applies to any codebase.
The working directory is {project_root} — write files relative to it.
"""

    print(f"Bootstrapping skills for {owner}/{repo}...")
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            cwd=project_root,
            allowed_tools=["Read", "Write", "Glob", "Grep"],
            mcp_servers={"github": github_mcp_config},
            max_turns=30,
            permission_mode="bypassPermissions",
            system_prompt=(
                "You are a codebase analyst. Your job is to deeply understand a GitHub repository "
                "and write precise, repo-specific PR review skills. Be concrete and specific — "
                "reference actual file paths, class names, and patterns from the code. "
                "Avoid generic advice."
            ),
        ),
    ):
        if isinstance(message, ResultMessage):
            print("Bootstrap complete!")
            print(message.result[:500] if message.result else "")
        else:
            # Print progress
            msg_type = getattr(message, "type", "unknown")
            if msg_type == "assistant":
                pass  # quiet
