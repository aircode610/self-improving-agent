"""Improver: uses analyzer.md + grading transcripts to rewrite review skills."""

import json
import shutil
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions

from src.utils import run_agent

PROJECT_ROOT = Path(__file__).parent.parent
SKILL_CREATOR_DIR = PROJECT_ROOT / "skill-creator"
HISTORY_DIR = PROJECT_ROOT / "history" / "reviews"
WORKSPACE_DIR = PROJECT_ROOT / "workspace"


def _skill_dir(owner: str, repo: str) -> Path:
    return PROJECT_ROOT / "skills" / owner / repo


def _snapshot_dir(owner: str, repo: str) -> Path:
    return WORKSPACE_DIR / "skill-snapshot" / owner / repo


def collect_recent_reviews(owner: str, repo: str, max_reviews: int = 10) -> list[dict]:
    """Collect recent review+grading pairs for the given repo.

    Returns list of dicts with keys: review_id, review_dir, transcript_path,
    outputs_dir, grading_path, grading (dict), has_transcript.
    """
    reviews = []
    review_dirs = sorted(HISTORY_DIR.iterdir(), reverse=True) if HISTORY_DIR.exists() else []

    for review_dir in review_dirs:
        if len(reviews) >= max_reviews:
            break

        # Check if this review is for our repo
        review_json = review_dir / "outputs" / "review.json"
        if not review_json.exists():
            # Try legacy path
            review_json = review_dir / "review.json"
        if not review_json.exists():
            continue

        try:
            review_data = json.loads(review_json.read_text())
            pr_ref = review_data.get("pr", "")
            if not pr_ref.startswith(f"{owner}/{repo}#"):
                continue
        except (json.JSONDecodeError, OSError):
            continue

        grading_path = review_dir / "grading.json"
        if not grading_path.exists():
            continue

        try:
            grading = json.loads(grading_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        transcript_path = review_dir / "transcript.md"
        outputs_dir = review_dir / "outputs"

        reviews.append({
            "review_id": review_dir.name,
            "review_dir": review_dir,
            "transcript_path": transcript_path if transcript_path.exists() else None,
            "outputs_dir": outputs_dir if outputs_dir.exists() else review_dir,
            "grading_path": grading_path,
            "grading": grading,
        })

    return reviews


def build_grading_summary(reviews: list[dict]) -> str:
    """Build a human-readable summary of failures across all reviews."""
    lines = []
    for r in reviews:
        review_id = r["review_id"]
        g = r["grading"]
        summary = g.get("summary", {})
        pass_rate = summary.get("pass_rate", 0)
        lines.append(f"\n### Review: {review_id} (pass rate: {pass_rate:.0%})")
        for exp in g.get("expectations", []):
            if not exp.get("passed", True):
                lines.append(f"  FAILED: {exp.get('text', '?')}")
                evidence = exp.get("evidence", "N/A")
                lines.append(f"    Evidence: {evidence}")
        for gap in g.get("skill_gaps", []):
            lines.append(f"  SKILL GAP: {gap}")
    return "\n".join(lines) if lines else "No grading history found."


async def run_improver(owner: str, repo: str) -> None:
    """Improve review skills based on grading feedback from recent reviews."""

    skill_dir = _skill_dir(owner, repo)
    if not (skill_dir / "SKILL.md").exists():
        print(f"No skills found for {owner}/{repo}. Run 'init' first.")
        return

    reviews = collect_recent_reviews(owner, repo)
    if not reviews:
        print(f"No graded reviews found for {owner}/{repo}. Run 'review' first.")
        return

    grading_summary = build_grading_summary(reviews)

    # Snapshot current skill before improving
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_dir = _snapshot_dir(owner, repo)
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)
    shutil.copytree(str(skill_dir), str(snapshot_dir))
    print(f"Snapshotted current skill to {snapshot_dir.relative_to(PROJECT_ROOT)}")

    # Load analyzer.md for improvement methodology
    analyzer_md = (SKILL_CREATOR_DIR / "agents" / "analyzer.md").read_text()

    skill_rel = skill_dir.relative_to(PROJECT_ROOT)

    # Build transcript references
    transcript_refs = []
    for r in reviews:
        if r["transcript_path"]:
            t_rel = r["transcript_path"].relative_to(PROJECT_ROOT)
            g_rel = r["grading_path"].relative_to(PROJECT_ROOT)
            transcript_refs.append(f"- Transcript: {t_rel}  |  Grading: {g_rel}")
    transcripts_block = "\n".join(transcript_refs) if transcript_refs else "(no transcripts available)"

    prompt = f"""You are improving PR review skills based on grading feedback.

You have access to the skill-creator's analyzer methodology below. Your task is to
analyze grading failures and rewrite the skill to fix the identified gaps.

{analyzer_md}

---

## Context: PR Review Skill Improvement

**Skill to improve**: {skill_rel}/SKILL.md
**Reviews analyzed**: {len(reviews)}

**Grading failures and skill gaps**:
{grading_summary}

**Execution transcripts and grading files**:
{transcripts_block}

## Your Task

1. Read the current skill files:
   - {skill_rel}/SKILL.md
   - {skill_rel}/references/conventions.md  (if exists)
   - {skill_rel}/references/common-issues.md  (if exists)

2. Read the transcripts to understand HOW the reviewer executed each review
   (what tools it called, what it examined, where it diverged from optimal behavior)

3. Read the grading files to understand WHAT failed and why

4. Rewrite the skill files to fix the identified gaps:
   - Update SKILL.md with clearer instructions for what was missed
   - Update references/conventions.md with conventions that were missed
   - Update references/common-issues.md with patterns that caused failures

5. For each change, cite the evidence from grading (why you're making it)

Key principles:
- Only add instructions grounded in actual observed failures
- Be specific: "check X in files matching Y" not "be more careful"
- If there were false positives, add clarifications about what NOT to flag
- Keep SKILL.md under 500 lines; move detail to references/ files

Working directory: {PROJECT_ROOT}
Write the updated skill files directly.
"""

    print(f"Improving skills for {owner}/{repo} based on {len(reviews)} graded reviews...")

    await run_agent(
        "improver",
        prompt,
        ClaudeAgentOptions(
            cwd=str(PROJECT_ROOT),
            allowed_tools=["Read", "Write", "Edit", "Glob", "Grep"],
            max_turns=20,
            permission_mode="bypassPermissions",
            system_prompt=(
                "You are a skill improvement expert. Analyze grading feedback and transcripts, "
                "then rewrite review skills to be more precise. Ground all changes in observed failures."
            ),
        ),
    )

    # Save improvement record
    record = {
        "improved_at": datetime.now().isoformat(),
        "owner": owner,
        "repo": repo,
        "reviews_analyzed": len(reviews),
        "reviews": [r["review_id"] for r in reviews],
    }
    record_path = WORKSPACE_DIR / "improvement-history.json"
    history = []
    if record_path.exists():
        try:
            history = json.loads(record_path.read_text())
        except json.JSONDecodeError:
            pass
    history.append(record)
    record_path.write_text(json.dumps(history, indent=2))
    print(f"Skill improvement complete! Record saved to {record_path.relative_to(PROJECT_ROOT)}")
