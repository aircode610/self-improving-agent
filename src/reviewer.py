"""Reviewer agent: reads a PR via GitHub MCP, reviews using skills, posts review to GitHub."""

import json
import os
from datetime import datetime
from pathlib import Path

import anyio
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage, AssistantMessage, TextBlock


SKILLS_DIR = Path(__file__).parent.parent / "skills" / "pr-review"
HISTORY_DIR = Path(__file__).parent.parent / "history" / "reviews"


async def run_reviewer(
    owner: str, repo: str, pr_number: int, github_mcp_config: dict
) -> tuple[str, str]:
    """Review a PR and return (review_id, review_output_text)."""

    # Check skills exist
    skill_md = SKILLS_DIR / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(
            f"No skills found at {SKILLS_DIR}. Run 'init' first:\n"
            f"  python -m src.cli init {owner}/{repo}"
        )

    project_root = str(Path(__file__).parent.parent)
    date_str = datetime.now().strftime("%Y-%m-%d")
    review_id = f"{date_str}_pr-{pr_number}"
    review_dir = HISTORY_DIR / review_id
    review_dir.mkdir(parents=True, exist_ok=True)

    prompt = f"""Review PR #{pr_number} in {owner}/{repo}.

First, read and internalize the review skills:
- Read skills/pr-review/SKILL.md — these are your primary review instructions
- Read skills/pr-review/repo-conventions.md — repo-specific conventions to enforce
- Read skills/pr-review/common-issues.md — known pitfalls to watch for

Then use GitHub MCP to read the PR:
1. get_pull_request — read PR title, description, author, base/head branches
2. get_pull_request_files — get the full diff/patch for every changed file
3. get_file_contents — read surrounding source files for context where needed
4. get_pull_request_status — check CI status

Perform a thorough review following the loaded skills. For each issue found, classify it as:
- critical: bugs, security vulnerabilities, data loss risks
- warning: code quality, performance, missing tests, violations of repo conventions
- nit: style, naming, minor improvements

After reviewing, format your findings as a JSON array written to history/reviews/{review_id}/review.json:
```json
{{
  "pr": "{owner}/{repo}#{pr_number}",
  "summary": "Brief overall assessment",
  "issues": [
    {{
      "file": "path/to/file.py",
      "line": 42,
      "severity": "critical|warning|nit",
      "comment": "Description of the issue and suggested fix"
    }}
  ],
  "verdict": "APPROVE|REQUEST_CHANGES|COMMENT"
}}
```

Then post the review to GitHub using MCP:
1. create_pending_pull_request_review for {owner}/{repo} PR #{pr_number}
2. For each critical/warning issue: add_pull_request_review_comment_to_pending_review
3. submit_pending_pull_request_review with event matching your verdict

The working directory is {project_root}.
"""

    print(f"Reviewing PR #{pr_number} in {owner}/{repo}...")
    review_output = ""

    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            cwd=project_root,
            allowed_tools=["Read", "Write", "Glob", "Grep"],
            mcp_servers={"github": github_mcp_config},
            max_turns=25,
            permission_mode="acceptEdits",
            system_prompt=(
                "You are an expert code reviewer. You follow repo-specific guidelines precisely. "
                "You are thorough but not pedantic — focus on meaningful issues. "
                "You always post your review back to GitHub after completing it."
            ),
        ),
    ):
        if isinstance(message, ResultMessage):
            review_output = message.result or ""
            print(f"Review complete. Review ID: {review_id}")

    # Load review.json if saved
    review_json_path = review_dir / "review.json"
    if review_json_path.exists():
        review_output = review_json_path.read_text()
    elif not review_output:
        review_output = json.dumps({"pr": f"{owner}/{repo}#{pr_number}", "issues": []})

    return review_id, review_output
