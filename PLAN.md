# Self-Improving PR Reviewer — Project Plan

## What This Is

A PR reviewer powered by the Claude Agent SDK that gets smarter over time. It uses Agent Skills as its knowledge layer and the official **skill-creator** skill from Anthropic to evaluate and improve its own review skills after every run.

Input: `owner/repo` + `pr-number`. All GitHub interaction happens through the **GitHub MCP server** — no local cloning, no diff parsing, no PyGithub.

**You don't need LangGraph.** The Claude Agent SDK handles each agent loop. The skills on disk are the memory. They persist and evolve across runs.

---

## Core Idea

```
First run (no skills exist yet):
    → Bootstrap agent uses GitHub MCP to read the repo
    → Bootstrap agent writes the initial review skills from what it finds
    → Skills are now on disk, ready to use

Every PR review (input: owner/repo + pr-number):
    → REVIEWER AGENT uses GitHub MCP to read PR diff + files → produces review
    → GRADER AGENT (auto-deployed) independently reads the PR via GitHub MCP
        → Grades: what was caught, what was missed, false positives
        → Writes grading.json in official skill-creator schema
    → IMPROVER uses official skill-creator scripts to run the 
      optimization loop and rewrite the skills
    → Next run uses improved skills
```

Two agents, zero human grading. The skills ARE the memory. They evolve.

---

## The Skill-Creator: What It Is and What We Use

The **skill-creator** is itself a Claude skill from the official `anthropics/skills` repo. It is NOT a Python library — it's a folder of markdown instructions and Python scripts that Claude reads and follows. When Claude loads the skill-creator's SKILL.md, it gains the knowledge of how to create, evaluate, and iteratively improve other skills.

### What's in the skill-creator

```
vendor/skill-creator/
├── SKILL.md                    # Main instructions Claude reads — the "brain" of the skill-creator
├── agents/                     # Subagent instruction files (markdown, not code)
│   ├── grader.md               # How to grade skill outputs against expectations
│   ├── comparator.md           # How to do blind A/B comparison of two skill versions  
│   └── analyzer.md             # How to analyze why one version beat another
├── scripts/                    # Python scripts Claude can execute
│   ├── run_eval.py             # Run a skill against test cases, grade results
│   ├── run_loop.py             # Full optimization loop (train/test split, iterate up to 5x)
│   ├── aggregate_benchmark.py  # Compute benchmark stats (pass_rate, time, tokens, mean ± stddev)
│   ├── generate_report.py      # Generate HTML report of eval results
│   ├── improve_description.py  # Optimize a skill's description for better triggering
│   ├── package_skill.py        # Package a skill for distribution
│   ├── quick_validate.py       # Quick validation of skill structure
│   └── utils.py                # Shared utilities
├── eval-viewer/                # HTML viewer for inspecting eval results
│   └── generate_review.py      # Generate the eval viewer HTML
└── references/
    └── schemas.md              # Exact JSON schemas for evals.json, grading.json, etc.
```

### How the skill-creator works (the loop we use)

The skill-creator's core loop, as described in its SKILL.md:

1. **Draft a skill** — write SKILL.md with frontmatter (name, description) and instructions
2. **Write test cases** — create eval prompts with expectations (assertions to check)
3. **Run test cases** — spawn subagents that execute the skill against each eval prompt
4. **Grade results** — spawn grader subagent (`agents/grader.md`) that reads outputs and grades each expectation as PASS/FAIL with cited evidence. Output is `grading.json` with exact fields: `text`, `passed`, `evidence`
5. **Show results** — generate the eval-viewer HTML for human inspection
6. **Improve the skill** — rewrite the skill based on what failed and why
7. **Re-run** — go back to step 3 with the improved skill
8. **Optimize description** — run `scripts/run_loop.py` which does 60/40 train/test split, evaluates the description (running each query 3x for reliability), proposes improvements via Claude, re-evaluates, iterates up to 5 times, picks best by test score to avoid overfitting

The skill-creator also supports **benchmarking** (A/B comparison of with-skill vs without-skill using `agents/comparator.md`) and **analysis** (understanding why one version won using `agents/analyzer.md`).

### What we use from it

| Component | How we use it |
|---|---|
| `agents/grader.md` | Our grader agent reads this as its instructions. It grades review output against expectations. |
| `agents/analyzer.md` | Used by improver to understand why skill gaps exist |
| `scripts/run_loop.py` | The improve command runs this to optimize skills with train/test split |
| `scripts/run_eval.py` | Used to run skills against test cases from past reviews |
| `scripts/aggregate_benchmark.py` | Track improvement over time |
| `eval-viewer/generate_review.py` | Generate HTML reports of eval results |
| `references/schemas.md` | We follow these schemas for our grading.json output |

### What we DON'T use

| Component | Why not |
|---|---|
| `SKILL.md` (the skill-creator's own instructions) | We don't need Claude to interactively interview us about what skill to create — we already know (PR review) |
| `agents/comparator.md` | Nice to have for v2, not needed for the core loop |
| `scripts/package_skill.py` | We're not distributing the skill, it lives in the project |
| `scripts/improve_description.py` | Our skill is always loaded explicitly, triggering accuracy doesn't matter |

---

## GitHub MCP Server — What the Agents Can Do

All GitHub interaction goes through the official GitHub MCP server (`github/github-mcp-server`). No local git clone, no PyGithub, no diff parsing code. The agents call MCP tools directly.

### PR-related tools the agents will use

| Tool | What it does | Used by |
|---|---|---|
| `get_pull_request` | Get PR details: title, body, state, head/base branches, author | Reviewer, Grader |
| `get_pull_request_files` | Get list of changed files with patch/diff per file | Reviewer, Grader |
| `get_pull_request_reviews` | Get existing reviews on the PR | Reviewer (context) |
| `get_pull_request_review_comments` | Get inline review comments | Reviewer (context) |
| `get_pull_request_status` | Get CI/CD build and check status | Reviewer |
| `create_pending_pull_request_review` | Create a pending review to add comments to | Reviewer (posting) |
| `add_pull_request_review_comment_to_pending_review` | Add inline comment to pending review | Reviewer (posting) |
| `submit_pending_pull_request_review` | Submit the pending review (APPROVE/REQUEST_CHANGES/COMMENT) | Reviewer (posting) |

### Repo-related tools (used by bootstrapper)

| Tool | What it does | Used by |
|---|---|---|
| `get_file_contents` | Read any file or directory listing from the repo | Bootstrapper, Reviewer, Grader |
| `search_code` | Search for patterns across the codebase | Bootstrapper, Reviewer |
| `list_commits` | Recent commit history | Bootstrapper |
| `get_repository` | Repo metadata (language, description, topics) | Bootstrapper |

### MCP server config

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "<your-token>"
      }
    }
  }
}
```

The Claude Agent SDK supports MCP servers natively — pass them in `ClaudeAgentOptions.mcp_servers`.

---

## Requirements

### Must Have (v1)
1. **CLI input: `owner/repo` + `pr-number`** — no local files, everything via GitHub MCP
2. **Skill bootstrapper** — on `init`, an agent reads the repo via GitHub MCP and writes initial review skills. No hand-written templates.
3. **Reviewer agent** — reads PR diff + source files via GitHub MCP, loads skills, produces structured review
4. **Grader agent** — separate agent, auto-runs after every review. Independently reads the PR via GitHub MCP, grades the review using `agents/grader.md` instructions, outputs `grading.json` in official skill-creator schema
5. **Skill improvement** — uses official skill-creator `scripts/run_loop.py` to optimize skills based on grader feedback
6. **Post review to GitHub** — use GitHub MCP to create a review with inline comments

### Should Have (v2)
7. **Repo-specific sub-skills** — auto-generate separate skills for domain-specific patterns
8. **A/B benchmarking** — use `agents/comparator.md` to compare skill versions
9. **Eval suite from history** — auto-build test cases from past reviews
10. **Review history dashboard** — use eval-viewer to show improvement over time

### Won't Do (keep it simple)
- No local git clone or diff parsing — GitHub MCP handles everything
- No web UI beyond the eval-viewer HTML
- No LangGraph — sequential flow is fine
- No database — files on disk

---

## Project Structure

```
pr-reviewer/
├── CLAUDE.md                          # Project context for Claude Code
├── pyproject.toml                     # Dependencies: claude-agent-sdk
├── README.md
│
├── src/
│   ├── __init__.py
│   ├── cli.py                         # Entry: `python -m src.cli init owner/repo`
│   │                                  #        `python -m src.cli review owner/repo 42`
│   │                                  #        `python -m src.cli improve`
│   ├── bootstrapper.py                # Agent: scans repo via GitHub MCP → writes initial skills
│   ├── reviewer.py                    # AGENT 1: reviews PR via GitHub MCP using loaded skills
│   ├── grader.py                      # AGENT 2: grades review using official grader.md
│   └── improver.py                    # Thin wrapper: feeds grader output → skill-creator scripts
│
├── vendor/
│   └── skill-creator/                 # git subtree from anthropics/skills/skills/skill-creator
│       ├── SKILL.md                   # Skill-creator instructions (reference, not loaded by our agents)
│       ├── agents/
│       │   ├── grader.md              # USED — grader agent instructions
│       │   ├── comparator.md          # v2 — A/B comparison
│       │   └── analyzer.md            # USED — analysis of skill gaps
│       ├── scripts/
│       │   ├── run_eval.py            # USED — run skill against test cases
│       │   ├── run_loop.py            # USED — full optimization loop
│       │   ├── aggregate_benchmark.py # USED — benchmark stats
│       │   ├── generate_report.py     # USED — HTML report
│       │   ├── improve_description.py # skipped (triggering not relevant for us)
│       │   ├── package_skill.py       # skipped (not distributing)
│       │   ├── quick_validate.py      # USED — validate skill structure
│       │   └── utils.py
│       ├── eval-viewer/
│       │   └── generate_review.py     # USED — HTML eval viewer
│       └── references/
│           └── schemas.md             # USED — JSON schemas we must follow
│
├── skills/                            # EMPTY at start — bootstrapper creates these
│   └── pr-review/
│       ├── SKILL.md                   # Review instructions (AGENT-GENERATED, EVOLVES)
│       ├── repo-conventions.md        # Repo-specific patterns (from bootstrapper + grader)
│       └── common-issues.md           # Known pitfalls (grows from grader feedback)
│
├── history/
│   └── reviews/                       # One directory per review
│       └── 2026-03-12_pr-42/
│           ├── review.json            # Reviewer output
│           └── grading.json           # Official-format grading (text, passed, evidence)
│
└── workspace/                         # Temp workspace for skill-creator iteration runs
    ├── skill-snapshot/                # Pre-improvement skill backup
    └── iteration-N/                   # Eval outputs per iteration (created by run_loop.py)
```

---

## How Each Piece Works

### `cli.py`

Three commands, all taking `owner/repo`:

```
python -m src.cli init owner/repo              # Bootstrap: scan repo, write initial skills
python -m src.cli review owner/repo 42         # Review PR #42 → auto-grade
python -m src.cli improve                      # Run skill-creator optimization loop
```

### `bootstrapper.py`

Runs on `init`. Scans the repo entirely through GitHub MCP:

```python
options = ClaudeAgentOptions(
    system_prompt="You are a codebase analyst. Your job is to write PR review skills.",
    allowed_tools=["Read", "Write"],
    mcp_servers=[github_mcp_config],
    max_turns=20,
)

prompt = f"""Analyze the repository {owner}/{repo} to create PR review skills.
Use the GitHub MCP tools to:

1. get_repository — read repo metadata (language, description)
2. get_file_contents — read directory structure, README, config files, 
   key source files, contributing guides, PR templates
3. search_code — find patterns: error handling, auth, validation, test patterns
4. list_commits — recent commit messages to understand change patterns

Then create these files locally:
- skills/pr-review/SKILL.md — main review instructions tailored to THIS repo
  Must have YAML frontmatter with name and description.
- skills/pr-review/repo-conventions.md — specific conventions you found
- skills/pr-review/common-issues.md — start empty, will be filled by grader

Be specific to this repo. Reference actual file paths, patterns, class names,
and conventions you found. Don't write generic advice.
"""
```

### `reviewer.py`

The review agent. Reads the PR via GitHub MCP, loads skills from disk:

```python
options = ClaudeAgentOptions(
    system_prompt="You are a code reviewer. Read and follow skills/pr-review/SKILL.md.",
    allowed_tools=["Read", "Grep", "Glob"],
    mcp_servers=[github_mcp_config],
    max_turns=15,
)

prompt = f"""Review PR #{pr_number} in {owner}/{repo}.

Use GitHub MCP to:
1. get_pull_request — read PR title, description, base/head branches
2. get_pull_request_files — get the full diff of every changed file
3. get_file_contents — read surrounding context files when needed
4. get_pull_request_status — check CI status

First, read skills/pr-review/SKILL.md and follow its instructions.

For each issue found, output JSON:
{{"file": "...", "line": N, "severity": "critical|warning|nit", "comment": "..."}}

After reviewing, use GitHub MCP to post your review:
1. create_pending_pull_request_review
2. add_pull_request_review_comment_to_pending_review (for each inline comment)
3. submit_pending_pull_request_review with appropriate event (COMMENT or REQUEST_CHANGES)
"""
```

### `grader.py`

Separate agent that uses the **official skill-creator `agents/grader.md`** as its instructions. Auto-runs after every review.

```python
grader_options = ClaudeAgentOptions(
    allowed_tools=["Read", "Write", "Grep", "Glob"],
    mcp_servers=[github_mcp_config],
    max_turns=15,
)

# Load the official grader instructions
grader_md = Path("vendor/skill-creator/agents/grader.md").read_text()

prompt = f"""
{grader_md}

You are grading a PR review. You did NOT write the review — you are 
a separate agent evaluating its quality.

Use GitHub MCP to independently read PR #{pr_number} in {owner}/{repo}:
1. get_pull_request_files — read the full diff yourself
2. get_file_contents — read the actual source files for context

Here is the review output to grade:
<review>{review_output}</review>

Here is the current review skill:
<skill>{current_skill_md}</skill>

Grade against these auto-generated expectations:
{expectations_json}

ALSO identify SKILL GAPS — things missing from the current skill
that would have caught the issues the reviewer missed.
Add "skill_gaps": ["...", "..."] to your output.

Save grading.json to: history/reviews/{review_id}/grading.json
Use the exact schema from references/schemas.md: 
expectations array with fields: text, passed, evidence
"""
```

The grader reads the PR independently via GitHub MCP — it doesn't trust the reviewer's interpretation. It grades each expectation as PASS/FAIL with evidence, following the exact schema the skill-creator's eval-viewer expects.

### `improver.py`

Thin wrapper that feeds grader output into the official skill-creator scripts:

```python
# 1. Collect grading.json from recent reviews
gradings = collect_recent_gradings("history/reviews/")

# 2. Extract skill_gaps across all gradings
all_gaps = extract_skill_gaps(gradings)

# 3. Build eval test cases from review history
#    Each past review becomes a test case with expectations
build_eval_set(gradings, output="workspace/test-cases.json")

# 4. Snapshot current skill
shutil.copytree("skills/pr-review", "workspace/skill-snapshot")

# 5. Run the official skill-creator optimization loop
subprocess.run([
    "python", "-m", "scripts.run_loop",
    "--eval-set", "workspace/test-cases.json",
    "--skill-path", "skills/pr-review",
    "--model", model_id,
    "--max-iterations", "5",
    "--verbose"
], cwd="vendor/skill-creator")

# 6. Generate eval viewer report
subprocess.run([
    "python", "-m", "eval-viewer.generate_review",
    "--static", "workspace/eval-report.html"
], cwd="vendor/skill-creator")
```

The `run_loop.py` handles everything: 60/40 train/test split → evaluate current skill (3x per query) → Claude proposes improvements → re-evaluate → iterate up to 5x → pick best by test score.

### `skills/pr-review/SKILL.md` — agent-generated, not a template

No fixed starting template. The bootstrapper writes this by reading the repo via GitHub MCP. Example for a FastAPI project:

```yaml
---
name: pr-review
description: Review PRs for the user-service FastAPI project. Checks API route 
  correctness, Pydantic model validation, SQLAlchemy query safety, and test coverage.
---

# PR Review Instructions for user-service

## Architecture
FastAPI app with SQLAlchemy ORM. Routes in src/routes/,
models in src/models/, schemas (Pydantic) in src/schemas/.

## What to check
- Route handlers must use dependency injection for DB sessions (get_db)
- All Pydantic schemas must have Config.from_attributes = True
- SQLAlchemy queries must use .scalars() not .all() (project convention)
- Every new route needs a test in tests/routes/
- Error responses use src/exceptions.py HTTPException subclasses

## Repo-specific conventions
See repo-conventions.md

## Known issues
See common-issues.md
```

Every repo gets different skills. That's the point.

---

## The Improvement Loop (How It Gets Smarter)

```
Init:   Bootstrapper reads owner/repo via GitHub MCP → finds it's a 
        FastAPI project with SQLAlchemy, Pydantic, custom exceptions → 
        writes initial skills tailored to these patterns. No human input.

Run 1:  Reviewer reads PR #42 via GitHub MCP → reviews using bootstrapped 
        skills → grader agent auto-runs → independently reads PR #42 via 
        GitHub MCP → finds reviewer missed that this repo uses `select()` 
        not `query()` → writes skill_gap + grading.json

        improver feeds grading into run_loop.py → skill updated:
        "This repo uses SQLAlchemy 2.0 style: select() not query()."

Run 5:  Reviewer catches SQLAlchemy style now → grader finds false 
        positive (reviewer flagged valid @cache decorator) → skill_gap:
        "clarify that @cache on routes is intentional"
        
        run_loop.py optimizes → adds to repo-conventions.md:
        "@cache on route handlers is intentional for idempotent GETs."

Run 20: Skills are a repo-specific expert. Both the reviewer and 
        grader have shaped them through the feedback loop.
```

---

## Dependencies

```toml
[project]
name = "pr-reviewer"
requires-python = ">=3.10"
dependencies = [
    "claude-agent-sdk",
]
```

No PyGithub — GitHub MCP server handles all GitHub API calls.

### Vendoring the skill-creator

```bash
# Clone and copy just the skill-creator
git clone https://github.com/anthropics/skills.git /tmp/skills
cp -r /tmp/skills/skills/skill-creator vendor/skill-creator
```

The scripts run as `python -m scripts.run_loop` from within the skill-creator directory.

### GitHub MCP server setup

```bash
# Install globally (agents will spawn it via config)
npm install -g @modelcontextprotocol/server-github

# Set your token
export GITHUB_PERSONAL_ACCESS_TOKEN=ghp_xxxxx
```

---

## Getting Started (First Session with Claude Code)

Tell Claude Code:

```
Read this plan at PR_REVIEWER_PLAN.md, then:

1. Set up the project structure
2. Vendor the official skill-creator from anthropics/skills into vendor/
3. Set up GitHub MCP server config
4. Implement cli.py — three commands: init, review, improve
5. Implement bootstrapper.py — scans repo via GitHub MCP, writes initial skills
6. Implement reviewer.py — reviews PR via GitHub MCP using skills, 
   posts review back to GitHub
7. Implement grader.py — uses vendor/skill-creator/agents/grader.md,
   reads PR independently via GitHub MCP, outputs grading.json 
   in official schema
8. Implement improver.py — thin wrapper: converts grader output 
   to eval test cases, calls vendor/skill-creator/scripts/run_loop.py
9. Test end-to-end: init on a real repo, review a real PR

All GitHub interaction goes through the GitHub MCP server.
No local cloning. No PyGithub. No diff parsing.
Use the claude-agent-sdk Python package.
Don't reimplement anything the skill-creator already provides.
```

---

## What We Build vs What We Reuse

### From the official skill-creator (vendor/)

| Component | How we use it |
|---|---|
| `agents/grader.md` | Grader agent reads this as its instructions |
| `agents/analyzer.md` | Used by improver to understand skill gaps |
| `scripts/run_loop.py` | The `improve` command runs this for optimization |
| `scripts/run_eval.py` | Run skills against test cases from past reviews |
| `scripts/aggregate_benchmark.py` | Track improvement metrics over time |
| `eval-viewer/generate_review.py` | HTML reports of eval results |
| `references/schemas.md` | JSON schemas our grading.json must follow |

### From the GitHub MCP server

| Capability | Replaces |
|---|---|
| `get_pull_request` + `get_pull_request_files` | diff.py (deleted) |
| `get_file_contents` + `search_code` | local git clone |
| `create_pending_pull_request_review` + comments | GitHub API posting code |
| `get_repository` + `list_commits` | repo analysis scripts |

### What we build ourselves

| Component | Why it's custom |
|---|---|
| `bootstrapper.py` | Repo-scanning + initial skill generation is our unique feature |
| `reviewer.py` | The PR review agent — loads skills, calls GitHub MCP, posts review |
| `grader.py` | Thin wrapper: feeds review + PR into official grader.md |
| `improver.py` | Thin wrapper: converts grader output → eval test cases → run_loop.py |
| `cli.py` | CLI tying it all together |

### Key Design Decisions

| Decision | Choice | Why |
|---|---|---|
| GitHub access | GitHub MCP server | No local clone, no PyGithub, agents call tools directly |
| Input format | `owner/repo` + `pr-number` | Simple, works with any repo you have access to |
| Eval/improve | Official skill-creator scripts | Don't reimplement — train/test split, iteration, benchmarking all built in |
| Grading | Official `agents/grader.md` | Proven grading logic, outputs in eval-viewer compatible format |
| Starting skills | Agent-generated via bootstrapper | Reads repo via MCP, writes skills itself. No templates. |
| Framework | Claude Agent SDK only | Sequential: review → grade → improve. No graph needed. |