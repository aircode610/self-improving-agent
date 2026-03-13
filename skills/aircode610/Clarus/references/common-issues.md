# Common Issues

This file grows from grader feedback — patterns the reviewer consistently misses.

---

## 1. `json.loads` on LLM Output Without `try/except` — BLOCKING
**Pattern:** `result = json.loads(response_content)` with no error handling.
**Why it matters:** LLM responses are non-deterministic. A single unexpected response format crashes the entire pipeline with an unhandled `json.JSONDecodeError`.
**Required fix:**
```python
try:
    result = json.loads(response_content)
except (json.JSONDecodeError, ValueError) as e:
    logger.warning(f"Malformed LLM response, skipping: {e}")
    continue  # or return default
```
**Evidence:** Missed in PR-15 (`get_llm_answer_with_parent`, `get_llm_answer_without_parent` both call `json.loads(content)` with no guard); missed in PR-8 (`extract_relations` in both `get_assertions_and_relations.py` variants).

---

## 2. Bare `except` Blocks Silently Discarding Records — WARNING
**Pattern:** `except: pass` or `except Exception: pass` in a data-processing loop.
**Why it matters:** Silent discard makes it impossible to detect how many records were dropped. A pipeline that processed 50 items but silently skipped 40 will appear to succeed.
**Required fix:** At minimum log the error and increment a counter:
```python
except (json.JSONDecodeError, ValueError) as e:
    logger.warning(f"Skipping malformed record: {e}")
    skipped_count += 1
```
**Evidence:** Missed in PR-8: `extract_relations` used a bare `except` block that swallowed JSON parse errors with no logging.

---

## 3. Unconditional Heavy/GPU Dependency Imports — BLOCKING
**Pattern:** `import unsloth`, `from transformers import ...`, `import torch` at the top level of a script without a `try/except ImportError` guard.
**Why it matters:** Users running an OpenAI/Grazie backend on a CPU-only machine cannot even import the module — they get `ImportError` before any code runs.
**Required fix:** Use the `_<DEP>_AVAILABLE` flag pattern (same as `voice/streamlit_voice.py`):
```python
try:
    import unsloth
    _UNSLOTH_AVAILABLE = True
except ImportError:
    _UNSLOTH_AVAILABLE = False
```
**Evidence:** Missed in PR-8: `get_assertions_and_relations.py` imported `unsloth` unconditionally at the top level.

---

## 4. Missing `os.makedirs` Before File Writes — BLOCKING
**Pattern:** Writing to `open("data/output.jsonl", "w")` without ensuring the parent directory exists.
**Why it matters:** If the `data/` directory doesn't exist (fresh clone, CI environment), Python raises `FileNotFoundError` immediately.
**Required fix:**
```python
import os
os.makedirs(os.path.dirname(output_path), exist_ok=True)
with open(output_path, "w") as f:
    ...
```
Or with `pathlib`:
```python
from pathlib import Path
Path(output_path).parent.mkdir(parents=True, exist_ok=True)
```
**Evidence:** Missed in PR-8: `prepare_data.py` and both `get_assertions_and_relations*.py` write to `data/` without creating it first.

---

## 5. Missing Environment Variable Validation Before API Client Construction — BLOCKING
**Pattern:** `client = openai.OpenAI()` or `client = anthropic.Anthropic()` with no prior check that the API key env var is set.
**Why it matters:** A missing key produces a cryptic SDK-internal exception rather than a helpful error message.
**Required fix:**
```python
api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable is not set. "
                     "Export it before running this script.")
client = openai.OpenAI(api_key=api_key)
```
**Evidence:** Missed in PR-8: `get_assertions_and_relations_openai.py` constructed `openai.OpenAI()` with no key validation, despite the reviewer reading the full file.

---

## 6. Case-Sensitivity Bug in String Comparisons — BLOCKING
**Pattern:** `keyword in paper.title.lower()` where `keyword` itself is not lowercased.
**Why it matters:** A search for `"Semantic Parsing"` silently returns zero results because the uppercase letters never match the lowercased title.
**Required fix:** Both sides must be normalized:
```python
if keyword_string.lower() in paper.title.lower():
```
**Where to look:** Any `in`, `==`, `.startswith()`, `.find()` comparison that applies `.lower()` to only one operand.
**Evidence:** Missed in PR-8: `prepare_data.py` lowercased `paper.title` but not `keyword_string`.

---

## 7. LLM Output Index Convention (1-based vs 0-based) — BLOCKING
**Pattern:** LLM returns assertion index `2`, code does `assertions[2]` expecting the third item — but LLMs count from 1, so `assertions[2]` is actually the third item only if the LLM was also 0-based.
**Why it matters:** If the LLM emits 1-based indices and code uses them directly as array indices, every relation mapping is silently off by one, producing wrong results with no error.
**Required fix:** Either:
- Prompt explicitly: "Return 0-based indices matching Python list positions"
- Or subtract 1: `assertions[llm_index - 1]`
**Where to look:** Any code that feeds LLM output integers into list subscripts.
**Evidence:** Missed in PR-8: `extract_relations` used LLM-returned assertion indices as direct Python array indices without adjustment.

---

## 8. Verbatim Code Duplication Across Parallel Script Variants — WARNING
**Pattern:** Two files (`get_assertions_and_relations.py`, `get_assertions_and_relations_openai.py`) contain identical function bodies for `extract_relations` or similar utilities.
**Why it matters:** Any bug fix or improvement must be applied twice. Reviewers who note "same bug exists in the other file" without filing a duplication issue are implicitly accepting the duplication.
**Required fix:** Factor shared logic into `src/utils/` and import from both variants.
**Evidence:** Missed in PR-8: reviewer acknowledged bugs appeared in both files but never filed a duplication issue or recommended factoring.

---

## 9. Generated Data Files Committed to Version Control — WARNING
**Pattern:** `data/selected_paper_abstracts.jsonl`, `data/generated_assertions.jsonl`, `data/generated_relations.jsonl` (or any script output) committed in the PR.
**Why it matters:** Generated files bloat the repo, may contain PII/proprietary content, and create a false impression that the data is authoritative rather than reproducible.
**Required fix:** Add to `.gitignore`:
```
data/*.jsonl
data/*.json
data/*.csv
```
And document reproduction steps in README.
**Evidence:** Missed in PR-8: reviewer flagged the `.jsonl` content only for Pydantic validation issues, never questioned whether the files should be committed at all.

---

## 10. Missing Test Coverage for New Complex Logic — WARNING
**Pattern:** PR adds non-trivial functions (index-mapping, LLM post-processing, JSON parsing, sorting comparators) with no new tests; or deletes existing test fixtures without replacement.
**How to detect:**
- Scan the PR diff for deleted `test_*.py` files or `@pytest.fixture` blocks
- For new functions with branching logic or LLM parsing, check whether any `test_*.py` file covers them
**Required fix:** File a warning issue requesting unit tests, especially for:
  - LLM output post-processing (e.g., `extract_relations`, `get_llm_answer_*`)
  - Index-mapping logic
  - Comparator functions used with `functools.cmp_to_key`
**Evidence:** Missed in both PR-8 (10 new script functions, zero tests) and PR-15 (`test_1` fixture deleted, `get_llm_answer_*` added with no mock tests).

---

## 11. Hardcoded Literals Audit — Enumerate ALL, Not Just the Obvious Ones
**Pattern:** Reviewer finds `parent_id="P1"` (obvious) but misses `confidence=0.8` (numeric) in the same function.
**Rule:** When a function accepts arguments that represent data-dependent values (IDs, types, scores, thresholds), scan its **entire body** for any literal that should instead come from those arguments. Numeric literals are as suspicious as string literals.
**Evidence:** PR-15: `get_llm_answer_with_parent` had four hardcoded values (`parent_id="P1"`, `relation_type="cause"`, `confidence=0.8`, `confidence=0.75`); review caught two, missed two, causing a grading failure.

---

## 12. API Call Loops Without Retry/Backoff — WARNING
**Pattern:** `for paper in papers: response = llm_client.call(...)` with no `try/except`, no retry, no partial-result save.
**Why it matters:** A single transient API error (rate limit, timeout, network blip) on item 47 of 50 aborts the entire run with no recoverable state.
**Required fix:**
```python
import time
for paper in papers:
    for attempt in range(3):
        try:
            response = client.call(...)
            break
        except Exception as e:
            if attempt == 2:
                logger.error(f"Failed after 3 attempts: {e}")
                raise
            time.sleep(2 ** attempt)
```
Or save partial results to disk after each item.
**Evidence:** Missed in PR-8: both `get_assertions_and_relations*.py` iterate over up to 50 papers with no retry or checkpointing.
