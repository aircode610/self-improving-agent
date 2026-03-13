"""Bootstrap agent: scans a GitHub repo via MCP and writes initial PR review skills."""

from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from src.utils import run_agent

PROJECT_ROOT = Path(__file__).parent.parent


async def run_bootstrapper(owner: str, repo: str, github_mcp_config: dict) -> None:
    """Scan owner/repo via GitHub MCP and write initial review skills."""

    skill_dir = PROJECT_ROOT / "skills" / owner / repo
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "references").mkdir(exist_ok=True)

    skill_rel = skill_dir.relative_to(PROJECT_ROOT)

    prompt = f"""Analyze the GitHub repository {owner}/{repo} and create PR review skills.

Use the GitHub MCP tools to understand the codebase:
1. get_repository — repo metadata (language, description, topics, default branch)
2. get_file_contents on "/" — project structure overview
3. get_file_contents to read: README.md, package.json/pyproject.toml/go.mod/Cargo.toml (whichever exists), CONTRIBUTING.md, .github/PULL_REQUEST_TEMPLATE.md, .github/workflows/ (first 2-3 files)
4. get_file_contents on 3-5 representative source files — understand code patterns
5. search_code for error handling, auth patterns, test naming, logging conventions

Now write THREE files using the Write tool:

━━━ FILE 1: {skill_rel}/SKILL.md ━━━
This is the orchestrator (keep under 400 lines). Include:
- YAML frontmatter: name, description (when to trigger + what it does)
- Architecture overview: what the repo actually is, tech stack, key modules
- PR review checklist (≤15 focused items, specific to THIS repo)
- How to use reference files:
  "For naming/import/error conventions → read {skill_rel}/references/conventions.md"
  "For known pitfalls from past reviews → read {skill_rel}/references/common-issues.md"
- Review output format instructions (JSON schema)

━━━ FILE 2: {skill_rel}/references/conventions.md ━━━
Detailed conventions found in the code:
- Naming patterns (files, functions, variables, classes) with real examples
- Import ordering and grouping rules
- Error handling pattern (how exceptions are thrown, caught, logged)
- Test file locations and naming conventions
- Any project-specific rules from config files (eslint, mypy, etc.)
- Reference actual file paths and class names you found

━━━ FILE 3: {skill_rel}/references/common-issues.md ━━━
Start with:
```
# Common Issues

This file grows from grader feedback — patterns the reviewer consistently misses.

## Known Pitfalls

(None yet — will be populated after the first reviews are graded)
```

Be concrete and specific to THIS repo. No generic advice.
Working directory: {PROJECT_ROOT}
"""

    print(f"Bootstrapping skills for {owner}/{repo}...")
    await run_agent(
        "bootstrap",
        prompt,
        ClaudeAgentOptions(
            cwd=str(PROJECT_ROOT),
            allowed_tools=["Read", "Write", "Glob", "Grep"],
            mcp_servers={"github": github_mcp_config},
            max_turns=20,
            permission_mode="bypassPermissions",
            system_prompt=(
                "You are a codebase analyst. Deeply understand a GitHub repository "
                "and write precise, repo-specific PR review skills. Be concrete — "
                "reference actual file paths, class names, and patterns. No generic advice."
            ),
        ),
    )
    print(f"Bootstrap complete! Skills written to {skill_rel}/")
