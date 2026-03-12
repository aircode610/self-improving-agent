# Self-Improving PR Reviewer

## Project Overview

A PR reviewer powered by the Claude Agent SDK that gets smarter over time.
Skills are stored in `skills/pr-review/` and evolve after every review cycle.

## Commands

```bash
# Bootstrap skills for a repo (run once per repo)
python -m src.cli init owner/repo

# Review a PR (auto-grades after review)
python -m src.cli review owner/repo 42

# Improve skills based on accumulated grading feedback
python -m src.cli improve
```

## Setup

```bash
pip install -e .
export GITHUB_PERSONAL_ACCESS_TOKEN=ghp_xxxxx
```

## Key Files

- `src/cli.py` — CLI entry point
- `src/bootstrapper.py` — Agent that scans repos and writes initial skills
- `src/reviewer.py` — Agent that reviews PRs using loaded skills
- `src/grader.py` — Agent that grades reviews using skill-creator/agents/grader.md
- `src/improver.py` — Rewrites skills based on grading feedback

## Directory Structure

- `skills/pr-review/` — Review skills (agent-generated, evolve over time)
- `history/reviews/` — Per-review history: review.json + grading.json
- `workspace/` — Temp files: skill snapshots, improvement records
- `skill-creator/` — Official Anthropic skill-creator (vendored, don't modify)

## Design Decisions

- All GitHub access via GitHub MCP server (`@modelcontextprotocol/server-github`)
- No local git clone, no PyGithub, no diff parsing
- Skills are the memory — they persist and evolve on disk
- Grader reads the PR independently to avoid echo-chamber grading
