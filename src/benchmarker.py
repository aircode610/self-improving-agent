"""
Benchmark: compare old skill (snapshot) vs new skill (current) on the same PRs.

Directory layout it produces for aggregate_benchmark.py:
  workspace/benchmarks/<timestamp>/
    eval-<pr_number>/
      new_skill/run-1/grading.json
      old_skill/run-1/grading.json
    benchmark.json
    benchmark.md
    comparison.json   ← blind A/B comparison by comparator agent
"""

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import anyio
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage


PROJECT_ROOT = Path(__file__).parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills" / "pr-review"
SNAPSHOT_DIR = PROJECT_ROOT / "workspace" / "skill-snapshot"
HISTORY_DIR = PROJECT_ROOT / "history" / "reviews"
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
SKILL_CREATOR_DIR = PROJECT_ROOT / "skill-creator"


# ── helpers ───────────────────────────────────────────────────────────────────

def get_reviewed_prs() -> list[dict]:
    """Return list of {pr_number, owner, repo, review_id, review_json_path} from history."""
    prs = []
    if not HISTORY_DIR.exists():
        return prs
    for review_dir in sorted(HISTORY_DIR.iterdir(), reverse=True):
        review_json = review_dir / "review.json"
        if not review_json.exists():
            continue
        try:
            data = json.loads(review_json.read_text())
            pr_ref = data.get("pr", "")        # "owner/repo#42"
            if "#" not in pr_ref:
                continue
            repo_part, pr_num = pr_ref.rsplit("#", 1)
            owner, repo = repo_part.split("/", 1)
            prs.append({
                "pr_number": int(pr_num),
                "owner": owner,
                "repo": repo,
                "review_id": review_dir.name,
                "review_json_path": review_json,
            })
        except (ValueError, KeyError):
            continue
    return prs


async def _run_review_with_skill(
    owner: str,
    repo: str,
    pr_number: int,
    skill_dir: Path,
    output_path: Path,
    github_mcp_config: dict,
) -> str:
    """Run a review using skill files from skill_dir, save to output_path/review.json."""
    output_path.mkdir(parents=True, exist_ok=True)
    skill_dir_rel = skill_dir.relative_to(PROJECT_ROOT)

    prompt = f"""Review PR #{pr_number} in {owner}/{repo}.

Read review skills from these files (NOT from skills/pr-review/):
- Read {skill_dir_rel}/SKILL.md
- Read {skill_dir_rel}/repo-conventions.md (if it exists)
- Read {skill_dir_rel}/common-issues.md (if it exists)

Then use GitHub MCP to read the PR:
1. get_pull_request — title, description, author, branches
2. get_pull_request_files — full diff for every changed file
3. get_file_contents — surrounding source files for context where needed

Perform a thorough review. For each issue: file, line, severity (critical/warning/nit), comment with suggested fix.

Save findings to {output_path.relative_to(PROJECT_ROOT)}/review.json:
{{
  "pr": "{owner}/{repo}#{pr_number}",
  "summary": "Brief overall assessment",
  "issues": [
    {{"file": "...", "line": 42, "severity": "critical|warning|nit", "comment": "..."}}
  ],
  "verdict": "APPROVE|REQUEST_CHANGES|COMMENT"
}}

Do NOT post to GitHub. Save only to the local file.
Working directory: {PROJECT_ROOT}
"""

    review_text = ""
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            cwd=str(PROJECT_ROOT),
            allowed_tools=["Read", "Write", "Glob", "Grep"],
            mcp_servers={"github": github_mcp_config},
            max_turns=25,
            permission_mode="bypassPermissions",
            system_prompt=(
                "You are an expert code reviewer. Follow the skills you are given exactly. "
                "Save your review as JSON locally — do not post to GitHub."
            ),
        ),
    ):
        if isinstance(message, ResultMessage):
            review_text = message.result or ""

    review_json = output_path / "review.json"
    if not review_json.exists():
        review_json.write_text(
            json.dumps({"pr": f"{owner}/{repo}#{pr_number}", "issues": [], "summary": review_text[:500]})
        )
    return review_json.read_text()


async def _run_grader_for_benchmark(
    owner: str,
    repo: str,
    pr_number: int,
    review_text: str,
    skill_text: str,
    output_dir: Path,
    github_mcp_config: dict,
) -> dict:
    """Grade a review and save grading.json to output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)

    from src.grader import _generate_expectations
    expectations = _generate_expectations(owner, repo, pr_number)
    expectations_json = json.dumps(expectations, indent=2)

    grader_md = (SKILL_CREATOR_DIR / "agents" / "grader.md").read_text()

    prompt = f"""{grader_md}

---

Grade this PR review for PR #{pr_number} in {owner}/{repo}.

Use GitHub MCP to independently read the PR:
1. get_pull_request_files — read the full diff
2. get_pull_request — title and description
3. get_file_contents — source files for context

Review to grade:
<review>
{review_text}
</review>

Skill used:
<skill>
{skill_text}
</skill>

Expectations:
{expectations_json}

Save grading to: {output_dir.relative_to(PROJECT_ROOT)}/grading.json
Use the exact schema (expectations array with text/passed/evidence, summary with pass_rate).
Working directory: {PROJECT_ROOT}
"""

    grading = {}
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            cwd=str(PROJECT_ROOT),
            allowed_tools=["Read", "Write", "Glob", "Grep"],
            mcp_servers={"github": github_mcp_config},
            max_turns=20,
            permission_mode="bypassPermissions",
            system_prompt="You are an objective grader. Base all verdicts on evidence from the PR diff.",
        ),
    ):
        if isinstance(message, ResultMessage):
            pass

    grading_path = output_dir / "grading.json"
    if grading_path.exists():
        try:
            grading = json.loads(grading_path.read_text())
        except json.JSONDecodeError:
            pass
    return grading


async def _run_comparator(
    pr_number: int,
    new_review_path: Path,
    old_review_path: Path,
    output_path: Path,
) -> dict:
    """Blind A/B comparison of new vs old review using comparator.md."""
    comparator_md = (SKILL_CREATOR_DIR / "agents" / "comparator.md").read_text()

    prompt = f"""{comparator_md}

---

Compare two PR reviews for PR #{pr_number}. You do NOT know which skill produced which.

Output A: {new_review_path.relative_to(PROJECT_ROOT)}/review.json
Output B: {old_review_path.relative_to(PROJECT_ROOT)}/review.json

Eval task: "Review this PR thoroughly, identify all real issues with file and line references,
avoid false positives, and produce a correct verdict."

Save comparison to: {output_path.relative_to(PROJECT_ROOT)}
Working directory: {PROJECT_ROOT}
"""

    comparison = {}
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            cwd=str(PROJECT_ROOT),
            allowed_tools=["Read", "Write", "Glob", "Grep"],
            max_turns=15,
            permission_mode="bypassPermissions",
            system_prompt="You are a blind comparator. Judge purely on output quality, not on which approach was used.",
        ),
    ):
        if isinstance(message, ResultMessage):
            pass

    if output_path.exists():
        try:
            comparison = json.loads(output_path.read_text())
        except json.JSONDecodeError:
            pass
    return comparison


def _print_report(benchmark: dict, comparison: dict, bench_dir: Path) -> None:
    """Print a human-readable benchmark report to stdout."""
    run_summary = benchmark.get("run_summary", {})
    new = run_summary.get("new_skill", {})
    old = run_summary.get("old_skill", {})
    delta = run_summary.get("delta", {})

    new_pr = new.get("pass_rate", {}).get("mean", 0)
    old_pr = old.get("pass_rate", {}).get("mean", 0)
    delta_pr = delta.get("pass_rate", "—")

    winner = comparison.get("winner", "?")
    # A = new_skill, B = old_skill (deterministic assignment in run_benchmark)
    winner_label = "new skill" if winner == "A" else ("old skill" if winner == "B" else "TIE")

    print("\n" + "=" * 60)
    print("  BENCHMARK RESULTS")
    print("=" * 60)
    print(f"  New skill pass rate : {new_pr*100:.0f}%")
    print(f"  Old skill pass rate : {old_pr*100:.0f}%")
    print(f"  Delta               : {delta_pr}")
    print(f"  Blind comparison    : {winner_label} wins")
    if comparison.get("reasoning"):
        print(f"\n  Reasoning: {comparison['reasoning'][:300]}")
    print(f"\n  Full results: {bench_dir}")
    print("=" * 60 + "\n")


# ── main entry point ───────────────────────────────────────────────────────────

async def run_benchmarker(
    pr_numbers: list[int] | None,
    owner_repo: str | None,
    github_mcp_config: dict,
) -> None:
    """Run benchmark comparing new skill vs old skill snapshot."""

    if not SKILLS_DIR.joinpath("SKILL.md").exists():
        print("No current skill found. Run 'init' first.")
        return

    if not SNAPSHOT_DIR.joinpath("SKILL.md").exists():
        print(
            "No skill snapshot found. Run 'improve' first — it snapshots the old skill before rewriting.\n"
            "If you haven't improved yet, there's nothing to compare against."
        )
        return

    # Determine which PRs to benchmark on
    if pr_numbers and owner_repo:
        owner, repo = owner_repo.split("/", 1)
        prs_to_run = [{"pr_number": n, "owner": owner, "repo": repo} for n in pr_numbers]
    else:
        history = get_reviewed_prs()
        if not history:
            print("No reviewed PRs in history. Run 'review' on at least one PR first.")
            return
        prs_to_run = history[:3]   # default: last 3 reviewed PRs
        print(f"No PRs specified — using last {len(prs_to_run)} from history.")

    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    bench_dir = WORKSPACE_DIR / "benchmarks" / timestamp
    bench_dir.mkdir(parents=True, exist_ok=True)

    new_skill_text = (SKILLS_DIR / "SKILL.md").read_text()
    old_skill_text = (SNAPSHOT_DIR / "SKILL.md").read_text()

    all_comparisons: list[dict] = []

    for i, pr_info in enumerate(prs_to_run):
        owner = pr_info["owner"]
        repo = pr_info["repo"]
        pr_number = pr_info["pr_number"]
        eval_dir = bench_dir / f"eval-{pr_number}"

        print(f"\n[{i+1}/{len(prs_to_run)}] Benchmarking PR #{pr_number} ({owner}/{repo})")

        new_run_dir = eval_dir / "new_skill" / "run-1"
        old_run_dir = eval_dir / "old_skill" / "run-1"

        # Run reviews with each skill
        print(f"  Running review with NEW skill...")
        new_review = await _run_review_with_skill(
            owner, repo, pr_number, SKILLS_DIR, new_run_dir, github_mcp_config
        )

        print(f"  Running review with OLD skill...")
        old_review = await _run_review_with_skill(
            owner, repo, pr_number, SNAPSHOT_DIR, old_run_dir, github_mcp_config
        )

        # Grade both
        print(f"  Grading new skill review...")
        await _run_grader_for_benchmark(
            owner, repo, pr_number, new_review, new_skill_text, new_run_dir, github_mcp_config
        )

        print(f"  Grading old skill review...")
        await _run_grader_for_benchmark(
            owner, repo, pr_number, old_review, old_skill_text, old_run_dir, github_mcp_config
        )

        # Blind comparison
        print(f"  Running blind A/B comparison...")
        comparison = await _run_comparator(
            pr_number,
            new_run_dir,
            old_run_dir,
            eval_dir / "comparison.json",
        )
        all_comparisons.append(comparison)

    # Aggregate stats using skill-creator's aggregate_benchmark.py logic
    sys.path.insert(0, str(SKILL_CREATOR_DIR))
    try:
        from scripts.aggregate_benchmark import generate_benchmark, generate_markdown
        benchmark = generate_benchmark(bench_dir, skill_name="pr-review", skill_path=str(SKILLS_DIR))
    except ImportError:
        benchmark = {"run_summary": {}, "metadata": {}, "runs": [], "notes": []}

    # Summarize comparisons
    new_wins = sum(1 for c in all_comparisons if c.get("winner") == "A")
    old_wins = sum(1 for c in all_comparisons if c.get("winner") == "B")
    ties = sum(1 for c in all_comparisons if c.get("winner") == "TIE")
    benchmark["notes"] = [
        f"Blind comparison: new_skill {new_wins}W / old_skill {old_wins}W / {ties} ties",
        f"A = new_skill, B = old_skill in all comparison files",
    ]

    # Save benchmark.json + benchmark.md
    benchmark_json = bench_dir / "benchmark.json"
    benchmark_json.write_text(json.dumps(benchmark, indent=2))

    try:
        md = generate_markdown(benchmark)
        (bench_dir / "benchmark.md").write_text(md)
    except Exception:
        pass

    # Save combined comparison summary
    combined_comparison = {
        "new_wins": new_wins,
        "old_wins": old_wins,
        "ties": ties,
        "winner": "new_skill" if new_wins > old_wins else ("old_skill" if old_wins > new_wins else "TIE"),
        "reasoning": f"Across {len(prs_to_run)} PRs: new_skill won {new_wins}, old_skill won {old_wins}, {ties} ties.",
        "per_pr": all_comparisons,
    }
    (bench_dir / "comparison.json").write_text(json.dumps(combined_comparison, indent=2))

    _print_report(benchmark, combined_comparison, bench_dir)
