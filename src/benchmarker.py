"""
Benchmark: compare old skill (snapshot) vs new skill (current) on the same PRs.

Directory layout produced:
  workspace/benchmarks/<timestamp>/
    eval-<pr_number>/
      new_skill/run-1/
        transcript.md
        outputs/
          review.json
        grading.json          ← saved by grader at outputs/../grading.json
      old_skill/run-1/
        transcript.md
        outputs/
          review.json
        grading.json
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
from src.grader import run_critic

PROJECT_ROOT = Path(__file__).parent.parent
SKILL_CREATOR_DIR = PROJECT_ROOT / "skill-creator"
HISTORY_DIR = PROJECT_ROOT / "history" / "reviews"
WORKSPACE_DIR = PROJECT_ROOT / "workspace"


def _skill_dir(owner: str, repo: str) -> Path:
    return PROJECT_ROOT / "skills" / owner / repo


def _snapshot_dir(owner: str, repo: str) -> Path:
    return WORKSPACE_DIR / "skill-snapshot" / owner / repo


def get_reviewed_prs(owner: str | None = None, repo: str | None = None) -> list[dict]:
    """Return [{pr_number, owner, repo}] from history, most recent first.
    Optionally filtered to a specific owner/repo.
    """
    prs = []
    if not HISTORY_DIR.exists():
        return prs
    for review_dir in sorted(HISTORY_DIR.iterdir(), reverse=True):
        # Try new layout first, then legacy
        for review_json_path in [
            review_dir / "outputs" / "review.json",
            review_dir / "review.json",
        ]:
            if not review_json_path.exists():
                continue
            try:
                data = json.loads(review_json_path.read_text())
                pr_ref = data.get("pr", "")
                if "#" not in pr_ref:
                    continue
                repo_part, pr_num = pr_ref.rsplit("#", 1)
                o, r = repo_part.split("/", 1)
                if owner and repo and (o != owner or r != repo):
                    break
                prs.append({"pr_number": int(pr_num), "owner": o, "repo": r})
            except (ValueError, KeyError):
                pass
            break
    return prs


def _load_grading(run_dir: Path) -> dict:
    """Load grading.json from run_dir or its parent (grader.md saves to outputs_dir/../grading.json)."""
    candidates = [
        run_dir / "grading.json",
        run_dir.parent / "grading.json",
    ]
    for p in candidates:
        if p.exists():
            expected = run_dir / "grading.json"
            if p != expected:
                expected.write_text(p.read_text())
                print(f"  [info] grading.json found at {p.relative_to(PROJECT_ROOT)}, "
                      f"copied to {expected.relative_to(PROJECT_ROOT)}")
            try:
                return json.loads(p.read_text())
            except json.JSONDecodeError as e:
                print(f"  [warn] invalid JSON in {p}: {e}")
                return {}
    print(f"  [warn] grading.json not found under {run_dir.relative_to(PROJECT_ROOT)}")
    return {}


# ── agent runners ──────────────────────────────────────────────────────────────

async def _review_with_skill(
    owner: str, repo: str, pr_number: int,
    skill_dir: Path, out_dir: Path,
    github_mcp_config: dict, label: str,
) -> str:
    """Run a review with a skill, saving outputs to out_dir/outputs/review.json
    and a transcript to out_dir/transcript.md."""
    outputs_dir = out_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    skill_rel = skill_dir.relative_to(PROJECT_ROOT)
    out_rel = outputs_dir.relative_to(PROJECT_ROOT)
    transcript_path = str(out_dir / "transcript.md")

    prompt = f"""Review PR #{pr_number} in {owner}/{repo}.

Load review skills (use these exact paths):
- Read {skill_rel}/SKILL.md
- Follow its instructions to read any reference files it points to

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
        max_turns=15,
        permission_mode="bypassPermissions",
        system_prompt="You are a code reviewer. Follow the skill file given. Save JSON locally only.",
    ), transcript_path=transcript_path)

    review_path = outputs_dir / "review.json"
    if not review_path.exists():
        review_path.write_text(json.dumps(
            {"pr": f"{owner}/{repo}#{pr_number}", "issues": [], "summary": "no output"}
        ))
        print(f"  [warn] reviewer did not write {review_path.relative_to(PROJECT_ROOT)}")
    return review_path.read_text()


async def _grade(
    owner: str, repo: str, pr_number: int,
    run_dir: Path,
    github_mcp_config: dict, label: str,
    expectations: list[str],
) -> None:
    """Grade a review using grader.md with transcript + outputs_dir + expectations."""
    outputs_dir = run_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = run_dir / "transcript.md"
    grading_dir = run_dir  # grader saves to outputs_dir/../grading.json = run_dir/grading.json

    grader_md = (SKILL_CREATOR_DIR / "agents" / "grader.md").read_text()
    transcript_rel = transcript_path.relative_to(PROJECT_ROOT) if transcript_path.exists() else f"{run_dir.relative_to(PROJECT_ROOT)}/transcript.md"
    outputs_rel = outputs_dir.relative_to(PROJECT_ROOT)
    grading_rel = grading_dir.relative_to(PROJECT_ROOT)

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
    await run_agent(label, prompt, ClaudeAgentOptions(
        cwd=str(PROJECT_ROOT),
        allowed_tools=["Read", "Write", "Glob", "Grep"],
        max_turns=12,
        permission_mode="bypassPermissions",
        system_prompt="You are a grader. Follow grader.md instructions. Save grading.json to the exact path specified.",
    ))


async def _compare(
    pr_number: int,
    new_run_dir: Path, old_run_dir: Path,
    out_path: Path, label: str,
) -> dict:
    comparator_md = (SKILL_CREATOR_DIR / "agents" / "comparator.md").read_text()
    new_rel = (new_run_dir / "outputs").relative_to(PROJECT_ROOT)
    old_rel = (old_run_dir / "outputs").relative_to(PROJECT_ROOT)

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


# ── per-PR benchmark ──────────────────────────────────────────────────────────

async def _benchmark_pr(
    pr_info: dict, bench_dir: Path,
    skill_dir: Path, snapshot_dir: Path,
    github_mcp_config: dict, idx: int, total: int,
) -> tuple[dict, float | str, float | str]:
    owner     = pr_info["owner"]
    repo      = pr_info["repo"]
    pr_number = pr_info["pr_number"]
    eval_dir  = bench_dir / f"eval-{pr_number}"

    new_run = eval_dir / "new_skill" / "run-1"
    old_run = eval_dir / "old_skill" / "run-1"

    pr_start = time.monotonic()
    print(f"\n[{idx}/{total}] PR #{pr_number} ({owner}/{repo})")

    # Reviews: run new + old IN PARALLEL
    t0 = time.monotonic()
    print(f"  Reviewing with new + old skill in parallel...")
    await asyncio.gather(
        _review_with_skill(owner, repo, pr_number, skill_dir,    new_run, github_mcp_config, "new-review"),
        _review_with_skill(owner, repo, pr_number, snapshot_dir, old_run, github_mcp_config, "old-review"),
    )
    print(f"  Reviews done in {_fmt_duration(time.monotonic() - t0)}")

    # Critic: run ONCE for this PR — both grades use the same expectations
    t0 = time.monotonic()
    print(f"  Running autonomous critic to generate grading expectations...")
    expectations_path = str(eval_dir / "expectations.json")
    expectations = await run_critic(
        owner, repo, pr_number, expectations_path, github_mcp_config
    )
    print(f"  Critic done in {_fmt_duration(time.monotonic() - t0)} ({len(expectations)} expectations)")

    # Grading: run new + old IN PARALLEL with shared expectations
    t0 = time.monotonic()
    print(f"  Grading both reviews in parallel...")
    await asyncio.gather(
        _grade(owner, repo, pr_number, new_run, github_mcp_config, "new-grade", expectations),
        _grade(owner, repo, pr_number, old_run, github_mcp_config, "old-grade", expectations),
    )
    print(f"  Grading done in {_fmt_duration(time.monotonic() - t0)}")

    new_grading = _load_grading(new_run)
    old_grading = _load_grading(old_run)
    new_pr = new_grading.get("summary", {}).get("pass_rate", "n/a")
    old_pr = old_grading.get("summary", {}).get("pass_rate", "n/a")
    print(f"  Pass rates → new: {new_pr}  old: {old_pr}")

    # Blind comparison
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

    return comparison, new_pr, old_pr


# ── main ──────────────────────────────────────────────────────────────────────

async def run_benchmarker(
    pr_numbers: list[int] | None,
    owner_repo: str | None,
    github_mcp_config: dict,
) -> None:
    # Determine owner/repo
    if owner_repo:
        owner, repo = owner_repo.split("/", 1)
    else:
        history = get_reviewed_prs()
        if not history:
            print("No reviewed PRs in history. Run 'review' first.")
            return
        first = history[0]
        owner, repo = first["owner"], first["repo"]
        print(f"No --repo specified — inferring {owner}/{repo} from history.")

    skill_dir = _skill_dir(owner, repo)
    snapshot_dir = _snapshot_dir(owner, repo)

    if not skill_dir.joinpath("SKILL.md").exists():
        print(f"No current skill found for {owner}/{repo}. Run 'init' first.")
        return

    if not snapshot_dir.joinpath("SKILL.md").exists():
        print(
            f"No skill snapshot found for {owner}/{repo}.\n"
            "Run 'improve' first — it snapshots the old skill before rewriting.\n"
            "If you haven't run improve yet, there's nothing to compare against."
        )
        return

    # Determine PRs to benchmark
    if pr_numbers:
        prs_to_run = [{"pr_number": n, "owner": owner, "repo": repo} for n in pr_numbers]
    else:
        history = get_reviewed_prs(owner, repo)
        if not history:
            print(f"No reviewed PRs in history for {owner}/{repo}. Run 'review' first.")
            return
        prs_to_run = history[:3]
        print(f"No --prs specified — using last {len(prs_to_run)} from history.")

    timestamp  = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    bench_dir  = WORKSPACE_DIR / "benchmarks" / timestamp
    bench_dir.mkdir(parents=True, exist_ok=True)

    total_start = time.monotonic()
    all_comparisons: list[dict] = []
    new_pass_rates: list[float] = []
    old_pass_rates: list[float] = []

    for i, pr_info in enumerate(prs_to_run, 1):
        comparison, new_pr, old_pr = await _benchmark_pr(
            pr_info, bench_dir, skill_dir, snapshot_dir, github_mcp_config, i, len(prs_to_run)
        )
        all_comparisons.append(comparison)
        if isinstance(new_pr, (int, float)):
            new_pass_rates.append(float(new_pr))
        if isinstance(old_pr, (int, float)):
            old_pass_rates.append(float(old_pr))

    # Try aggregate stats (optional — may fail)
    sys.path.insert(0, str(SKILL_CREATOR_DIR))
    benchmark: dict = {"run_summary": {}, "metadata": {}, "runs": [], "notes": []}
    generate_markdown = None
    try:
        from scripts.aggregate_benchmark import generate_benchmark, generate_markdown
        benchmark = generate_benchmark(bench_dir, skill_name=repo, skill_path=str(skill_dir))
    except Exception as e:
        print(f"  [info] aggregate_benchmark unavailable ({e}), using direct grading stats")

    new_wins = sum(1 for c in all_comparisons if c.get("winner") == "A")
    old_wins = sum(1 for c in all_comparisons if c.get("winner") == "B")
    ties     = len(all_comparisons) - new_wins - old_wins

    benchmark["notes"] = [
        "A = new_skill, B = old_skill",
        f"Blind comparison: new_skill {new_wins}W / old_skill {old_wins}W / {ties} ties",
    ]

    (bench_dir / "benchmark.json").write_text(json.dumps(benchmark, indent=2))
    try:
        if generate_markdown:
            (bench_dir / "benchmark.md").write_text(generate_markdown(benchmark))
    except Exception:
        pass

    # Compute means directly from per-PR grading
    new_pr_mean = sum(new_pass_rates) / len(new_pass_rates) if new_pass_rates else 0.0
    old_pr_mean = sum(old_pass_rates) / len(old_pass_rates) if old_pass_rates else 0.0

    # Override with aggregate stats if available
    run_summary = benchmark.get("run_summary", {})
    if run_summary:
        new_s = run_summary.get("new_skill", {})
        old_s = run_summary.get("old_skill", {})
        agg_new = new_s.get("pass_rate", {}).get("mean")
        agg_old = old_s.get("pass_rate", {}).get("mean")
        if agg_new is not None:
            new_pr_mean = agg_new
        if agg_old is not None:
            old_pr_mean = agg_old

    delta = run_summary.get("delta", {})

    combined = {
        "new_wins": new_wins, "old_wins": old_wins, "ties": ties,
        "winner": "new_skill" if new_wins > old_wins else ("old_skill" if old_wins > new_wins else "TIE"),
        "reasoning": f"Across {len(prs_to_run)} PRs: new_skill {new_wins}W / old_skill {old_wins}W / {ties} ties.",
        "per_pr": all_comparisons,
        "pass_rates": {"new": new_pass_rates, "old": old_pass_rates},
    }
    (bench_dir / "comparison.json").write_text(json.dumps(combined, indent=2))

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
