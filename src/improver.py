"""Improver: feeds grader feedback into an agent that rewrites the review skills."""

import json
import shutil
from datetime import datetime
from pathlib import Path

import anyio
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage


SKILL_CREATOR_DIR = Path(__file__).parent.parent / "skill-creator"
SKILLS_DIR = Path(__file__).parent.parent / "skills" / "pr-review"
HISTORY_DIR = Path(__file__).parent.parent / "history" / "reviews"
WORKSPACE_DIR = Path(__file__).parent.parent / "workspace"


def collect_recent_gradings(max_reviews: int = 10) -> list[dict]:
    """Collect grading.json from recent reviews."""
    gradings = []
    review_dirs = sorted(HISTORY_DIR.iterdir(), reverse=True) if HISTORY_DIR.exists() else []
    for review_dir in review_dirs[:max_reviews]:
        grading_path = review_dir / "grading.json"
        if grading_path.exists():
            try:
                data = json.loads(grading_path.read_text())
                data["_review_id"] = review_dir.name
                gradings.append(data)
            except json.JSONDecodeError:
                pass
    return gradings


def extract_skill_gaps(gradings: list[dict]) -> list[str]:
    """Collect all skill_gaps from gradings, deduplicated."""
    seen = set()
    gaps = []
    for g in gradings:
        for gap in g.get("skill_gaps", []):
            if gap not in seen:
                seen.add(gap)
                gaps.append(gap)
    return gaps


def build_failure_summary(gradings: list[dict]) -> str:
    """Build a human-readable summary of what failed across all gradings."""
    lines = []
    for g in gradings:
        review_id = g.get("_review_id", "unknown")
        summary = g.get("summary", {})
        pass_rate = summary.get("pass_rate", 0)
        lines.append(f"\n### Review: {review_id} (pass rate: {pass_rate:.0%})")
        for exp in g.get("expectations", []):
            if not exp.get("passed", True):
                lines.append(f"  FAILED: {exp['text']}")
                lines.append(f"    Evidence: {exp.get('evidence', 'N/A')}")
    return "\n".join(lines) if lines else "No grading history found."


async def run_improver() -> None:
    """Improve review skills based on all grading feedback collected so far."""

    project_root = str(Path(__file__).parent.parent)

    # Check skills exist
    if not (SKILLS_DIR / "SKILL.md").exists():
        print("No skills found. Run 'init' first.")
        return

    # Collect grading feedback
    gradings = collect_recent_gradings()
    if not gradings:
        print("No grading history found. Run 'review' on at least one PR first.")
        return

    skill_gaps = extract_skill_gaps(gradings)
    failure_summary = build_failure_summary(gradings)

    # Snapshot current skill before improving
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_dir = WORKSPACE_DIR / "skill-snapshot"
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)
    shutil.copytree(str(SKILLS_DIR), str(snapshot_dir))
    print(f"Snapshotted current skill to {snapshot_dir}")

    # Load analyzer instructions from skill-creator
    analyzer_md_path = SKILL_CREATOR_DIR / "agents" / "analyzer.md"
    analyzer_instructions = (
        analyzer_md_path.read_text() if analyzer_md_path.exists() else ""
    )

    gaps_json = json.dumps(skill_gaps, indent=2)
    gradings_json = json.dumps(
        [{"review_id": g["_review_id"], "summary": g.get("summary", {}),
          "skill_gaps": g.get("skill_gaps", [])} for g in gradings],
        indent=2
    )

    prompt = f"""You are improving PR review skills based on grading feedback from past reviews.

{analyzer_instructions}

---

You have collected feedback from {len(gradings)} recent PR reviews. Here is what failed:

{failure_summary}

Identified skill gaps (things missing from the current skill):
{gaps_json}

Grading summaries:
{gradings_json}

Your task:
1. Read the current skill files:
   - skills/pr-review/SKILL.md
   - skills/pr-review/repo-conventions.md
   - skills/pr-review/common-issues.md

2. Analyze the failures and skill gaps to understand what's missing or wrong

3. Rewrite the skill files to fix the identified gaps:
   - Update SKILL.md with clearer instructions for what was missed
   - Update repo-conventions.md with any new conventions that were missed
   - Update common-issues.md with the specific patterns that caused failures

4. For each change you make, be specific about WHY you're making it (cite the evidence from grading)

Key principles:
- Only add instructions that would have helped with actual observed failures
- Don't add generic advice — be specific to what this reviewer actually got wrong
- If the reviewer had false positives, add clarifications about what NOT to flag
- Make instructions actionable: "check X in files matching pattern Y" not "be more careful"

The working directory is {project_root}.
Write the updated skill files directly — they will be used on the next review.
"""

    print(f"Improving skills based on {len(gradings)} graded reviews...")
    print(f"Identified {len(skill_gaps)} skill gaps to address...")

    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            cwd=project_root,
            allowed_tools=["Read", "Write", "Edit", "Glob", "Grep"],
            max_turns=20,
            permission_mode="acceptEdits",
            system_prompt=(
                "You are a skill improvement expert. You analyze grading feedback and rewrite "
                "review skills to be more precise and effective. Your changes must be grounded "
                "in the actual observed failures — not speculation about what might help."
            ),
        ),
    ):
        if isinstance(message, ResultMessage):
            print("Skill improvement complete!")
            if message.result:
                print(message.result[:500])

    # Save improvement record
    record = {
        "improved_at": datetime.now().isoformat(),
        "reviews_analyzed": len(gradings),
        "skill_gaps_addressed": skill_gaps,
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
    print(f"Improvement record saved to {record_path}")
