"""Grader agent: independently reads a PR via GitHub MCP and grades the review output."""

import json
from pathlib import Path

import anyio
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage


SKILL_CREATOR_DIR = Path(__file__).parent.parent / "skill-creator"
SKILLS_DIR = Path(__file__).parent.parent / "skills" / "pr-review"
HISTORY_DIR = Path(__file__).parent.parent / "history" / "reviews"


def _generate_expectations(owner: str, repo: str, pr_number: int) -> list[str]:
    """Auto-generate grading expectations for a PR review."""
    return [
        "The review identifies at least one concrete issue with file and line reference",
        "Every critical or warning issue includes a specific suggested fix, not just a description of the problem",
        "The review does not contain false positives (flagged issues that are actually correct code)",
        "The review checks code changes against repo-specific conventions from the skill",
        "The review verdict (APPROVE/REQUEST_CHANGES/COMMENT) is appropriate to the severity of issues found",
        "The review was posted to GitHub as a formal review with inline comments",
        f"All files changed in PR #{pr_number} were examined before forming conclusions",
    ]


async def run_grader(
    owner: str,
    repo: str,
    pr_number: int,
    review_id: str,
    review_output: str,
    github_mcp_config: dict,
) -> None:
    """Grade a review. Outputs grading.json in the official skill-creator schema."""

    project_root = str(Path(__file__).parent.parent)
    review_dir = HISTORY_DIR / review_id
    review_dir.mkdir(parents=True, exist_ok=True)

    # Load grader instructions from skill-creator
    grader_md_path = SKILL_CREATOR_DIR / "agents" / "grader.md"
    grader_instructions = (
        grader_md_path.read_text() if grader_md_path.exists() else ""
    )

    # Load current skill for context
    skill_md_path = SKILLS_DIR / "SKILL.md"
    current_skill = skill_md_path.read_text() if skill_md_path.exists() else ""

    # Auto-generate expectations
    expectations = _generate_expectations(owner, repo, pr_number)
    expectations_json = json.dumps(expectations, indent=2)

    prompt = f"""You are grading a PR review. You did NOT write the review — you are a separate agent evaluating its quality.

{grader_instructions}

---

Your task: grade a PR review for PR #{pr_number} in {owner}/{repo}.

Use GitHub MCP to independently read the PR yourself:
1. get_pull_request_files — read the full diff independently
2. get_pull_request — read title, description, context
3. get_file_contents — read source files to understand the code changes in context

Here is the review output to grade:
<review>
{review_output}
</review>

Here is the current review skill the reviewer was following:
<skill>
{current_skill}
</skill>

Grade against these expectations:
{expectations_json}

ALSO identify SKILL GAPS — specific things missing from the current skill that would have helped the reviewer catch issues they missed or avoid false positives. Be concrete: don't say "improve the skill", say "the skill should explicitly state that this repo uses X pattern in Y files".

Save your grading to: history/reviews/{review_id}/grading.json

Use this exact schema (from skill-creator/references/schemas.md):
{{
  "expectations": [
    {{
      "text": "...",
      "passed": true/false,
      "evidence": "specific quote or observation"
    }}
  ],
  "summary": {{
    "passed": N,
    "failed": N,
    "total": N,
    "pass_rate": 0.0-1.0
  }},
  "skill_gaps": [
    "Concrete description of what should be added to the skill..."
  ],
  "claims": [],
  "user_notes_summary": {{"uncertainties": [], "needs_review": [], "workarounds": []}}
}}

The working directory is {project_root}.
"""

    print(f"Grading review {review_id}...")
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            cwd=project_root,
            allowed_tools=["Read", "Write", "Glob", "Grep"],
            mcp_servers={"github": github_mcp_config},
            max_turns=20,
            permission_mode="bypassPermissions",
            system_prompt=(
                "You are an objective grader evaluating the quality of a code review. "
                "You have access to the same GitHub PR as the reviewer, and you independently "
                "verify what they caught and missed. Be rigorous: base all verdicts on evidence."
            ),
        ),
    ):
        if isinstance(message, ResultMessage):
            print("Grading complete.")
