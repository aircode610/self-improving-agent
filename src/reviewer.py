"""Reviewer agent: reads a PR via GitHub MCP, reviews using skills, saves results locally."""

import json
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions

from src.utils import run_agent

PROJECT_ROOT = Path(__file__).parent.parent
HISTORY_DIR = PROJECT_ROOT / "history" / "reviews"


def _skill_dir(owner: str, repo: str) -> Path:
    return PROJECT_ROOT / "skills" / owner / repo


async def run_reviewer(
    owner: str, repo: str, pr_number: int, github_mcp_config: dict
) -> tuple[str, str]:
    """Review a PR and return (review_id, review_output_text).

    Directory layout:
      history/reviews/{review_id}/
        transcript.md          ← execution log for grader
        outputs/
          review.json          ← the review output
    """

    skill_dir = _skill_dir(owner, repo)
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(
            f"No skills found at {skill_dir}. Run 'init' first:\n"
            f"  python -m src.cli init {owner}/{repo}"
        )

    date_str = datetime.now().strftime("%Y-%m-%d")
    review_id = f"{date_str}_pr-{pr_number}"
    review_dir = HISTORY_DIR / review_id
    outputs_dir = review_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    skill_rel = skill_dir.relative_to(PROJECT_ROOT)
    out_rel = outputs_dir.relative_to(PROJECT_ROOT)
    transcript_path = str(review_dir / "transcript.md")

    prompt = f"""Review PR #{pr_number} in {owner}/{repo}.

Step 1 — Load skills:
- Read {skill_rel}/SKILL.md
- Follow its instructions to read any reference files it points to

Step 2 — Read the PR via GitHub MCP:
1. get_pull_request — title, description, author, branches
2. get_pull_request_files — full diff for every changed file
3. get_file_contents — surrounding source files for context where needed (limit to files relevant to the diff)

Step 3 — Review following the loaded skill. For each issue, classify as:
- critical: bugs, security vulnerabilities, data loss risks
- warning: code quality, performance, missing tests, convention violations
- nit: style, naming, minor improvements

Step 4 — Save to {out_rel}/review.json:
{{
  "pr": "{owner}/{repo}#{pr_number}",
  "summary": "Brief overall assessment",
  "issues": [
    {{
      "file": "path/to/file.py",
      "line": 42,
      "severity": "critical|warning|nit",
      "comment": "Description and suggested fix"
    }}
  ],
  "verdict": "APPROVE|REQUEST_CHANGES|COMMENT"
}}

Do NOT post to GitHub. Save only to the local file above.
Working directory: {PROJECT_ROOT}
"""

    print(f"Reviewing PR #{pr_number} in {owner}/{repo}...")
    await run_agent(
        "reviewer",
        prompt,
        ClaudeAgentOptions(
            cwd=str(PROJECT_ROOT),
            allowed_tools=["Read", "Write", "Glob", "Grep"],
            mcp_servers={"github": github_mcp_config},
            max_turns=15,
            permission_mode="bypassPermissions",
            system_prompt=(
                "You are an expert code reviewer. Follow repo-specific guidelines precisely. "
                "Be thorough but focused — flag meaningful issues, not noise. "
                "Save the review as a JSON file locally. Do not post to GitHub."
            ),
        ),
        transcript_path=transcript_path,
    )

    review_json_path = outputs_dir / "review.json"
    if review_json_path.exists():
        review_output = review_json_path.read_text()
    else:
        review_output = json.dumps({"pr": f"{owner}/{repo}#{pr_number}", "issues": []})
        print(f"  [warn] reviewer did not write {out_rel}/review.json")

    print(f"Review complete. Review ID: {review_id}")
    return review_id, review_output
