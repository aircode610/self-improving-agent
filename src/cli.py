"""CLI entry point for the self-improving PR reviewer."""

import argparse
import asyncio
import os
import sys
from pathlib import Path


def _load_dotenv() -> None:
    """Load .env from the project root (no external dependency needed)."""
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def get_github_mcp_config() -> dict:
    token = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "")
    return {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": token},
    }


def _parse_owner_repo(owner_repo: str) -> tuple[str, str]:
    if "/" not in owner_repo:
        print(f"Error: repo must be in 'owner/repo' format, got: {owner_repo}")
        sys.exit(1)
    owner, repo = owner_repo.split("/", 1)
    return owner, repo


def cmd_init(args):
    """Bootstrap: scan repo via GitHub MCP, write initial skills."""
    from src.bootstrapper import run_bootstrapper

    owner, repo = _parse_owner_repo(args.repo)
    asyncio.run(run_bootstrapper(owner, repo, get_github_mcp_config()))


def cmd_review(args):
    """Review a PR and auto-grade it."""
    from src.reviewer import run_reviewer
    from src.grader import run_grader

    owner, repo = _parse_owner_repo(args.repo)
    pr_number = args.pr_number
    mcp_config = get_github_mcp_config()

    review_id, _ = asyncio.run(
        run_reviewer(owner, repo, pr_number, mcp_config)
    )

    print(f"\nAuto-grading review {review_id}...")
    asyncio.run(run_grader(owner, repo, pr_number, review_id, mcp_config))
    print(f"Grading complete. See history/reviews/{review_id}/grading.json")


def cmd_improve(args):
    """Run skill improvement loop based on grader feedback."""
    from src.improver import run_improver

    owner, repo = _parse_owner_repo(args.repo)
    asyncio.run(run_improver(owner, repo))


def cmd_benchmark(args):
    """Compare new skill vs old skill snapshot on past PRs."""
    from src.benchmarker import run_benchmarker

    pr_numbers = None
    owner_repo = None
    if args.prs:
        if not args.repo:
            print("Error: --repo required when specifying --prs")
            sys.exit(1)
        owner_repo = args.repo
        pr_numbers = args.prs
    elif args.repo:
        owner_repo = args.repo

    asyncio.run(run_benchmarker(pr_numbers, owner_repo, get_github_mcp_config()))


def main():
    parser = argparse.ArgumentParser(
        description="Self-improving PR reviewer powered by Claude Agent SDK"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init command
    init_parser = subparsers.add_parser("init", help="Bootstrap skills for a repo")
    init_parser.add_argument("repo", help="GitHub repo in owner/repo format")

    # review command
    review_parser = subparsers.add_parser("review", help="Review a PR")
    review_parser.add_argument("repo", help="GitHub repo in owner/repo format")
    review_parser.add_argument("pr_number", type=int, help="PR number to review")

    # improve command
    improve_parser = subparsers.add_parser("improve", help="Improve skills based on grader feedback")
    improve_parser.add_argument("repo", help="GitHub repo in owner/repo format")

    # benchmark command
    bench_parser = subparsers.add_parser(
        "benchmark", help="Compare new vs old skill on past PRs"
    )
    bench_parser.add_argument(
        "--prs", type=int, nargs="+", metavar="PR",
        help="PR numbers to benchmark on (default: last 3 from history)"
    )
    bench_parser.add_argument(
        "--repo", metavar="OWNER/REPO",
        help="Repo to benchmark (required when specifying --prs; otherwise inferred from history)"
    )

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "review":
        cmd_review(args)
    elif args.command == "improve":
        cmd_improve(args)
    elif args.command == "benchmark":
        cmd_benchmark(args)


if __name__ == "__main__":
    main()
