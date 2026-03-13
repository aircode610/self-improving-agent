"""
Benchmark: compare old skill (snapshot) vs new skill (current) on the same PRs.

Directory layout produced for aggregate_benchmark.py:
  workspace/benchmarks/<timestamp>/
    eval-<pr_number>/
      new_skill/run-1/  review.json  grading.json
      old_skill/run-1/  review.json  grading.json
      comparison.json
    benchmark.json
    benchmark.md
    comparison.json   ← combined summary
"""

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions

from src.utils import run_agent, _fmt_duration


PROJECT_ROOT = Path(__file__).parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills" / "pr-review"
SNAPSHOT_DIR = PROJECT_ROOT / "workspace" / "skill-snapshot"
HISTORY_DIR = PROJECT_ROOT / "history" / "reviews"
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
SKILL_CREATOR_DIR = PROJECT_ROOT / "skill-creator"


# ── helpers ────────────────────────────────────────────────────────────────────

def get_reviewed_prs() -> list[dict]:
    """Return [{pr_number, owner, repo}] from history, most recent first."""
    prs = []
    if not HISTORY_DIR.exists():
        return prs
    for review_dir in sorted(HISTORY_DIR.iterdir(), reverse=True):
        review_json = review_dir / "review.json"
        if not review_json.exists():
            continue
        try:
            data = json.loads(review_json.read_text())
            pr_ref = data.get("pr", "")
            if "#" not in pr_ref:
                continue
            repo_part, pr_num = pr_ref.rsplit("#", 1)
            owner, repo = repo_part.split("/", 1)
            prs.append({"pr_number": int(pr_num), "owner": owner, "repo": repo})
        except (ValueError, KeyError):
            continue
    return prs


def _find_grading_json(run_dir: Path) -> Path | None:
    """
    Search multiple locations for grading.json.

    The grader.md instructions tell the agent to save at
    '{outputs_dir}/../grading.json', which conflicts with the path we give it.
    Check both locations.
    """
    candidates = [
        run_dir / "grading.json",          # where we ask it to save
        run_dir.parent / "grading.json",   # where grader.md tells it to save
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _load_grading(run_dir: Path) -> dict:
    path = _find_grading_json(run_dir)
    if path is None:
        print(f"  [warn] grading.json not found under {run_dir.relative_to(PROJECT_ROOT)}")
        print(f"  [warn] checked: {run_dir}/grading.json and {run_dir.parent}/grading.json")
        return {}
    # Normalise: copy to expected location if found in parent
    expected = run_dir / "grading.json"
    if path != expected:
        expected.write_text(path.read_text())
        print(f"  [info] grading.json found at {path.relative_to(PROJECT_ROOT)}, copied to {expected.relative_to(PROJECT_ROOT)}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        print(f"  [warn] invalid JSON in {path}: {e}")
        return {}


# ── agent runners ──────────────────────────────────────────────────────────────

async def _review_with_skill(
    owner: str, repo: str, pr_number: int,
    skill_dir: Path, out_dir: Path,
    github_mcp_config: dict, label: str,
) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    skill_rel = skill_dir.relative_to(PROJECT_ROOT)
    out_rel   = out_dir.relative_to(PROJECT_ROOT)

    prompt = f"""Review PR #{pr_number} in {owner}/{repo}.

Load review skills from (use these exact paths, NOT skills/pr-review/):
- Read {skill_rel}/SKILL.md
- Read {skill_rel}/repo-conventions.md  (skip if missing)
- Read {skill_rel}/common-issues.md     (skip if missing)

Use GitHub MCP:
1. get_pull_request — title, description, branches
2. get_pull_request_files — full diff for every changed file
3. get_file_contents — source context where needed (limit to files relevant to the diff)

Review following the loaded skill. Classify each issue as critical / warning / nit.

Save to {out_rel}/review.json:
{{
  "pr": "{owner}/{repo}#{pr_number}",
  "summary": "...",
  "issues": [{{"file":"...","line":0,"severity":"critical|warning|nit","comment":"..."}}],
  "verdict": "APPROVE|REQUEST_CHANGES|COMMENT"
}}

Do NOT post to GitHub. Working directory: {PROJECT_ROOT}
"""
    await run_agent(label, prompt, ClaudeAgentOptions(
        cwd=str(PROJECT_ROOT),
        allowed_tools=["Read", "Write", "Glob", "Grep"],
        mcp_servers={"github": github_mcp_config},
        max_turns=20,
        permission_mode="bypassPermissions",
        system_prompt="You are a code reviewer. Follow the skill file given. Save JSON locally only.",
    ))

    review_path = out_dir / "review.json"
    if not review_path.exists():
        review_path.write_text(json.dumps(
            {"pr": f"{owner}/{repo}#{pr_number}", "issues": [], "summary": "no output"}
        ))
        print(f"  [warn] reviewer did not write {review_path.relative_to(PROJECT_ROOT)}")
    return review_path.read_text()


async def _grade(
    owner: str, repo: str, pr_number: int,
    review_text: str, skill_text: str,
    out_dir: Path, github_mcp_config: dict, label: str,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_rel = out_dir.relative_to(PROJECT_ROOT)

    from src.grader import _generate_expectations
    expectations = _generate_expectations(owner, repo, pr_number)

    grader_md = (SKILL_CREATOR_DIR / "agents" / "grader.md").read_text()

    prompt = f"""{grader_md}

---

Grade a PR review for PR #{pr_number} in {owner}/{repo}.

Use GitHub MCP to independently read the PR:
1. get_pull_request_files — full diff
2. get_pull_request — title and description

Review to grade:
<review>
{review_text[:4000]}
</review>

Skill the reviewer used:
<skill>
{skill_text[:2000]}
</skill>

Expectations to grade:
{json.dumps(expectations, indent=2)}

IMPORTANT: Save grading to this exact path: {out_rel}/grading.json
(Ignore any other path mentioned in the instructions above — use this path only.)

Schema: expectations array with text/passed/evidence fields, plus summary with pass_rate.
Working directory: {PROJECT_ROOT}
"""
    await run_agent(label, prompt, ClaudeAgentOptions(
        cwd=str(PROJECT_ROOT),
        allowed_tools=["Read", "Write", "Glob", "Grep"],
        mcp_servers={"github": github_mcp_config},
        max_turns=15,
        permission_mode="bypassPermissions",
        system_prompt="You are a grader. Save grading.json to the exact path specified.",
    ))


async def _compare(
    pr_number: int,
    new_run_dir: Path, old_run_dir: Path,
    out_path: Path, label: str,
) -> dict:
    comparator_md = (SKILL_CREATOR_DIR / "agents" / "comparator.md").read_text()
    new_rel = new_run_dir.relative_to(PROJECT_ROOT)
    old_rel = old_run_dir.relative_to(PROJECT_ROOT)

    prompt = f"""{comparator_md}

---

Compare two PR reviews for PR #{pr_number}.

Output A: read {new_rel}/review.json
Output B: read {old_rel}/review.json

Task: "Review the PR thoroughly, find all real issues with file+line refs, avoid false positives."

Save comparison to {out_path.relative_to(PROJECT_ROOT)}
Working directory: {PROJECT_ROOT}
"""
    await run_agent(label, prompt, ClaudeAgentOptions(
        cwd=str(PROJECT_ROOT),
        allowed_tools=["Read", "Write"],
        max_turns=10,
        permission_mode="bypassPermissions",
        system_prompt="You are a blind comparator. Judge on output quality only.",
    ))

    if out_path.exists():
        try:
            return json.loads(out_path.read_text())
        except json.JSONDecodeError:
            pass
    return {"winner": "TIE", "reasoning": "comparison agent did not produce output"}


# ── per-PR benchmark (new + old run in parallel) ───────────────────────────────

async def _benchmark_pr(
    pr_info: dict, bench_dir: Path, github_mcp_config: dict, idx: int, total: int
) -> dict:
    owner      = pr_info["owner"]
    repo       = pr_info["repo"]
    pr_number  = pr_info["pr_number"]
    eval_dir   = bench_dir / f"eval-{pr_number}"

    new_run = eval_dir / "new_skill" / "run-1"
    old_run = eval_dir / "old_skill" / "run-1"

    pr_start = time.monotonic()
    print(f"\n[{idx}/{total}] PR #{pr_number} ({owner}/{repo})")

    new_skill_text = (SKILLS_DIR / "SKILL.md").read_text()
    old_skill_text = (SNAPSHOT_DIR / "SKILL.md").read_text()

    # ── reviews: run new + old IN PARALLEL ──────────────────────────────────
    t0 = time.monotonic()
    print(f"  Reviewing with new + old skill in parallel...")
    new_review, old_review = await asyncio.gather(
        _review_with_skill(owner, repo, pr_number, SKILLS_DIR,    new_run, github_mcp_config, "new-review"),
        _review_with_skill(owner, repo, pr_number, SNAPSHOT_DIR,  old_run, github_mcp_config, "old-review"),
    )
    print(f"  Reviews done in {_fmt_duration(time.monotonic() - t0)}")

    # ── grading: also in parallel ────────────────────────────────────────────
    t0 = time.monotonic()
    print(f"  Grading both reviews in parallel...")
    await asyncio.gather(
        _grade(owner, repo, pr_number, new_review, new_skill_text, new_run, github_mcp_config, "new-grade"),
        _grade(owner, repo, pr_number, old_review, old_skill_text, old_run, github_mcp_config, "old-grade"),
    )
    print(f"  Grading done in {_fmt_duration(time.monotonic() - t0)}")

    # Load grading results (handles misplaced files)
    new_grading = _load_grading(new_run)
    old_grading = _load_grading(old_run)
    new_pr = new_grading.get("summary", {}).get("pass_rate", "n/a")
    old_pr = old_grading.get("summary", {}).get("pass_rate", "n/a")
    print(f"  Pass rates → new: {new_pr}  old: {old_pr}")

    # ── blind comparison ─────────────────────────────────────────────────────
    t0 = time.monotonic()
    print(f"  Running blind A/B comparison...")
    comparison = await _compare(
        pr_number, new_run, old_run,
        eval_dir / "comparison.json",
        "compare",
    )
    winner = comparison.get("winner", "?")
    winner_label = {"A": "new skill", "B": "old skill"}.get(winner, "TIE")
    print(f"  Comparison done in {_fmt_duration(time.monotonic() - t0)} → {winner_label} wins")
    print(f"  PR #{pr_number} total: {_fmt_duration(time.monotonic() - pr_start)}")

    return comparison


# ── main ───────────────────────────────────────────────────────────────────────

async def run_benchmarker(
    pr_numbers: list[int] | None,
    owner_repo: str | None,
    github_mcp_config: dict,
) -> None:
    if not SKILLS_DIR.joinpath("SKILL.md").exists():
        print("No current skill found. Run 'init' first.")
        return

    if not SNAPSHOT_DIR.joinpath("SKILL.md").exists():
        print(
            "No skill snapshot found.\n"
            "Run 'improve' first — it snapshots the old skill before rewriting.\n"
            "If you haven't run improve yet, there's nothing to compare against."
        )
        return

    # Determine PRs
    if pr_numbers and owner_repo:
        owner, repo = owner_repo.split("/", 1)
        prs_to_run = [{"pr_number": n, "owner": owner, "repo": repo} for n in pr_numbers]
    else:
        history = get_reviewed_prs()
        if not history:
            print("No reviewed PRs in history. Run 'review' first.")
            return
        prs_to_run = history[:3]
        print(f"No PRs specified — using last {len(prs_to_run)} from history.")

    timestamp  = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    bench_dir  = WORKSPACE_DIR / "benchmarks" / timestamp
    bench_dir.mkdir(parents=True, exist_ok=True)

    total_start = time.monotonic()
    all_comparisons: list[dict] = []

    for i, pr_info in enumerate(prs_to_run, 1):
        comparison = await _benchmark_pr(pr_info, bench_dir, github_mcp_config, i, len(prs_to_run))
        all_comparisons.append(comparison)

    # ── aggregate stats ──────────────────────────────────────────────────────
    sys.path.insert(0, str(SKILL_CREATOR_DIR))
    benchmark: dict = {"run_summary": {}, "metadata": {}, "runs": [], "notes": []}
    try:
        from scripts.aggregate_benchmark import generate_benchmark, generate_markdown
        benchmark = generate_benchmark(bench_dir, skill_name="pr-review", skill_path=str(SKILLS_DIR))
    except Exception as e:
        print(f"  [warn] aggregate_benchmark failed: {e}")

    new_wins = sum(1 for c in all_comparisons if c.get("winner") == "A")
    old_wins = sum(1 for c in all_comparisons if c.get("winner") == "B")
    ties     = len(all_comparisons) - new_wins - old_wins

    benchmark["notes"] = [
        f"A = new_skill, B = old_skill",
        f"Blind comparison: new_skill {new_wins}W / old_skill {old_wins}W / {ties} ties",
    ]

    (bench_dir / "benchmark.json").write_text(json.dumps(benchmark, indent=2))
    try:
        (bench_dir / "benchmark.md").write_text(generate_markdown(benchmark))
    except Exception:
        pass

    combined = {
        "new_wins": new_wins, "old_wins": old_wins, "ties": ties,
        "winner": "new_skill" if new_wins > old_wins else ("old_skill" if old_wins > new_wins else "TIE"),
        "reasoning": f"Across {len(prs_to_run)} PRs: new_skill {new_wins}W / old_skill {old_wins}W / {ties} ties.",
        "per_pr": all_comparisons,
    }
    (bench_dir / "comparison.json").write_text(json.dumps(combined, indent=2))

    # ── final report ─────────────────────────────────────────────────────────
    run_summary = benchmark.get("run_summary", {})
    new_s = run_summary.get("new_skill", {})
    old_s = run_summary.get("old_skill", {})
    delta = run_summary.get("delta", {})

    new_pr_mean = new_s.get("pass_rate", {}).get("mean", 0)
    old_pr_mean = old_s.get("pass_rate", {}).get("mean", 0)

    total_elapsed = _fmt_duration(time.monotonic() - total_start)
    print(f"\n{'='*60}")
    print(f"  BENCHMARK RESULTS  (total: {total_elapsed})")
    print(f"{'='*60}")
    print(f"  New skill pass rate : {new_pr_mean*100:.0f}%")
    print(f"  Old skill pass rate : {old_pr_mean*100:.0f}%")
    print(f"  Delta               : {delta.get('pass_rate', '—')}")
    print(f"  Blind comparison    : {combined['winner'].replace('_',' ')} wins")
    print(f"                        ({new_wins}W new / {old_wins}W old / {ties} ties)")
    print(f"\n  Full results: {bench_dir}")
    print(f"{'='*60}\n")
