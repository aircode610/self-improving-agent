"""Grader agent: autonomous critic generates expectations, grader.md evaluates the review."""

import json
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions

from src.utils import run_agent

PROJECT_ROOT = Path(__file__).parent.parent
SKILL_CREATOR_DIR = PROJECT_ROOT / "skill-creator"
HISTORY_DIR = PROJECT_ROOT / "history" / "reviews"


def _skill_dir(owner: str, repo: str) -> Path:
    return PROJECT_ROOT / "skills" / owner / repo


async def run_critic(
    owner: str,
    repo: str,
    pr_number: int,
    expectations_path: str,
    github_mcp_config: dict,
) -> list[str]:
    """Spawn an autonomous critic that reads the PR and generates grading expectations.

    The critic acts like a senior engineer independently reviewing the PR — it identifies
    what a thorough code review *should* have caught, without looking at the actual review
    output. This replaces hardcoded generic expectations with PR-specific ones.

    Returns the list of expectation strings (also saved to expectations_path).
    """
    path = Path(expectations_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    prompt = f"""You are a senior software engineer evaluating PR #{pr_number} in {owner}/{repo}.

Your job is NOT to review the code yourself — it is to define what a thorough, high-quality
code review of this PR should cover.

Step 1: Read the PR via GitHub MCP:
1. get_pull_request — understand what's being changed and why
2. get_pull_request_files — see all code changes in full

Step 2: Based on what you see, generate 6-10 specific expectations that a good review
of THIS PR must satisfy. These are grading criteria for the reviewer's output.

Rules for good expectations:
- Specific to this PR (not generic like "reviewer was thorough")
- Testable from a review document (can be verified with yes/no)
- Meaningful (would distinguish a careful review from a superficial one)
- Focus on what could go wrong: bugs, missing edge cases, convention violations,
  security issues, missing tests for changed logic, etc.

Examples of good expectations:
- "The review checks whether the new retry loop has a termination condition"
- "The review notes the missing null check when `user` could be None on line 42"
- "The review identifies that the new SQL query is missing input sanitization"
- "The review verifies test coverage was added for the changed authentication logic"
- "The review checks that the API response schema change is backward compatible"

Save the expectations as a JSON array of strings to: {expectations_path}
Working directory: {PROJECT_ROOT}
"""

    print(f"  [critic] Reading PR #{pr_number} to generate grading expectations...")
    result = await run_agent(
        "critic",
        prompt,
        ClaudeAgentOptions(
            cwd=str(PROJECT_ROOT),
            allowed_tools=["Write"],
            mcp_servers={"github": github_mcp_config},
            max_turns=8,
            permission_mode="bypassPermissions",
            system_prompt=(
                "You are a senior engineer defining what a good PR review should cover. "
                "Read the PR thoroughly and generate specific, testable expectations. "
                "Save them as a JSON array to the specified path."
            ),
        ),
    )

    if path.exists():
        try:
            expectations = json.loads(path.read_text())
            if isinstance(expectations, list) and expectations:
                return [str(e) for e in expectations]
        except (json.JSONDecodeError, ValueError):
            pass

    # Fallback: try parsing from result text
    try:
        start = result.find("[")
        end = result.rfind("]") + 1
        if start >= 0 and end > start:
            expectations = json.loads(result[start:end])
            if isinstance(expectations, list) and expectations:
                path.write_text(json.dumps(expectations, indent=2))
                return [str(e) for e in expectations]
    except (json.JSONDecodeError, ValueError):
        pass

    # Last resort: generic expectations
    print(f"  [warn] critic did not produce expectations; using generic fallback")
    fallback = [
        f"The review identifies at least one concrete issue with file and line reference",
        f"Every critical or warning issue includes a specific suggested fix",
        f"The review does not contain false positives (flagged issues that are correct code)",
        f"The review checks code changes against repo-specific conventions from the skill",
        f"The review verdict (APPROVE/REQUEST_CHANGES/COMMENT) is appropriate to issue severity",
        f"All files changed in PR #{pr_number} were examined before forming conclusions",
    ]
    path.write_text(json.dumps(fallback, indent=2))
    return fallback


async def run_grader(
    owner: str,
    repo: str,
    pr_number: int,
    review_id: str,
    github_mcp_config: dict,
    expectations: list[str] | None = None,
) -> None:
    """Grade a review using grader.md with transcript + outputs directory.

    If expectations is None, runs the autonomous critic first to generate them.

    Directory layout expected:
      history/reviews/{review_id}/
        transcript.md
        outputs/
          review.json
      → grading saved to history/reviews/{review_id}/grading.json
    """
    review_dir = HISTORY_DIR / review_id
    transcript_path = review_dir / "transcript.md"
    outputs_dir = review_dir / "outputs"
    expectations_path = review_dir / "expectations.json"

    # Run autonomous critic if expectations not provided
    if expectations is None:
        expectations = await run_critic(
            owner, repo, pr_number,
            str(expectations_path),
            github_mcp_config,
        )

    grader_md = (SKILL_CREATOR_DIR / "agents" / "grader.md").read_text()
    transcript_rel = transcript_path.relative_to(PROJECT_ROOT)
    outputs_rel = outputs_dir.relative_to(PROJECT_ROOT)
    grading_rel = review_dir.relative_to(PROJECT_ROOT)  # grader.md saves to outputs_dir/../grading.json

    prompt = f"""{grader_md}

---

Grade this PR review execution.

**transcript_path**: {transcript_rel}
**outputs_dir**: {outputs_rel}
**expectations**:
{json.dumps(expectations, indent=2)}

Additional context:
- PR: #{pr_number} in {owner}/{repo}
- The review.json is in {outputs_rel}/review.json
- Save grading to {grading_rel}/grading.json
  (this is {outputs_rel}/../grading.json per the instructions above)

Working directory: {PROJECT_ROOT}
"""

    print(f"Grading review {review_id}...")
    await run_agent(
        "grader",
        prompt,
        ClaudeAgentOptions(
            cwd=str(PROJECT_ROOT),
            allowed_tools=["Read", "Write", "Glob", "Grep"],
            max_turns=12,
            permission_mode="bypassPermissions",
            system_prompt="You are an objective grader. Follow grader.md instructions exactly.",
        ),
    )
    print("Grading complete.")
