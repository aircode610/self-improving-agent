---
name: clarus-pr-reviewer
description: >
  Trigger when reviewing a PR against the aircode610/Clarus repository.
  Clarus is a LangGraph + Streamlit structured writing assistant that extracts
  atomic assertions from text/voice, organizes them into a relationship graph,
  reviews paragraphs for issues, and generates final prose. This skill performs
  a focused review of PRs touching workflows/, models/, ui/, voice/, app.py,
  streamlit_app.py — the five active code layers of the project — as well as
  any standalone scripts in src/, scripts/, or data-pipeline files added at the
  repo root or in subdirectories outside the main app layers.
---

# Clarus PR Review Skill

## What This Repo Is

Clarus is a Python application for structured technical writing. Users dictate or type
raw ideas; the system extracts **Assertions** (discrete atomic claims), builds a directed
**Relationship** graph between them, detects paragraph-level issues, and produces polished
prose in Academic or Technical style.

### Tech Stack
- **Python 3.x** — no type stubs, no mypy config, no linting config
- **LangGraph** (`>=0.2.0`) — all AI logic lives in `StateGraph` instances
- **LangChain + ChatOpenAI** — LLM calls via `langchain_openai.ChatOpenAI` (default `gpt-4o-mini`)
- **Pydantic v2** (`>=2.8.0`) — all models use `BaseModel`, `Field`, `model_dump()`
- **Streamlit** (`>=1.39.0`) — single-page app, `st.session_state` as the UI state bus
- **faster-whisper + vosk + pydub** — optional voice layer in `voice/streamlit_voice.py`
- **networkx + plotly** — graph visualization in `ui/structure_ui.py`
- **No test suite** — zero test files exist in the repo

### Key Modules
| Path | Purpose |
|------|---------|
| `models/assertions.py` | `Assertion`, `Relationship` — leaf Pydantic models |
| `models/states.py` | LangGraph state classes: `IdeaCaptureState`, `StructureState`, `ReviewState`, `ProseState`, `ChangeHistory` |
| `models/__init__.py` | Explicit `__all__` re-export of every public model |
| `workflows/idea_capture.py` | `IdeaCaptureWorkflow` + `create_idea_capture_workflow` |
| `workflows/structure.py` | `StructureWorkflow` + `create_structure_workflow` |
| `workflows/review.py` | `ReviewWorkflow` + `create_review_workflow` |
| `workflows/prose.py` | `ProseWorkflow` + `create_prose_workflow` |
| `workflows/conflict_resolving.py` | `GlobalGraph` — networkx SCC/contradiction detection |
| `workflows/__init__.py` | Explicit `__all__` re-export of all workflow symbols |
| `ui/common.py` | `display_assertions`, `create_assertion_groups`, export/clear/next buttons |
| `ui/idea_ui.py` | Chat + assertion panel for Idea Capture mode |
| `ui/structure_ui.py` | Graph visualization + ordering panel |
| `ui/review_ui.py` | Paragraph + issue review panel |
| `ui/prose_ui.py` | Prose generation controls |
| `voice/streamlit_voice.py` | `whisper_voice_to_text`, `load_whisper_model` |
| `app.py` | `ClarusApp` orchestrator class — coordinates all workflows |
| `streamlit_app.py` | Entry point — `main()`, `st.set_page_config`, session state init |
| `langgraph.json` | LangGraph Studio graph registry |

---

## PR Review Checklist

Work through these in order. Each item references specific files and patterns.

### 1. Workflow Class Structure
Does every new or modified workflow follow the established class contract?
- `__init__(self, model_name="gpt-4o-mini", config=None)` with `self.llm = ChatOpenAI(model=model_name, temperature=0.3)` and `self._graph = None`
- Lazy `graph` property calling `_build_graph()` on first access
- All graph nodes as private methods named `_<action>_node(self, state: <StateType>)`
- A `run()` method that constructs the initial `<Workflow>State` and calls `self.graph.invoke()`
- A module-level factory: `def create_<name>_workflow(config=None)` (required for `langgraph.json`)
→ See `workflows/prose.py` for the canonical pattern

### 2. State Class Compliance
Does any new `*State` class in `models/states.py` follow the established pattern?
- Extends `pydantic.BaseModel` (NOT `TypedDict`)
- Messages field typed exactly as `Annotated[List[BaseMessage], add_messages]`
- All list fields use `Field(default_factory=list)`, not `= []`
- Literal fields use `Literal["a", "b", "c"]` for constrained strings
→ Compare against `IdeaCaptureState`, `ProseState` in `models/states.py`

### 3. Model `__all__` Completeness
If `models/assertions.py` or `models/states.py` gains a new class, is it added to:
- `models/__init__.py` both as an import line AND in `__all__`
- `workflows/__init__.py` `__all__` if re-exported there
Missing from `__all__` silently breaks `from models import *` and LangGraph Studio introspection.

### 4. LLM Invocation Pattern
Does new LLM code use the correct invocation style?
- Use `self.llm.invoke([HumanMessage(content=prompt)])` — not `.predict()`, `.call()`, or `.chat()`
- Extract content as `getattr(response, "content", str(response))` — not `response.content` directly (avoids AttributeError on some LangChain response types)
- Do NOT mutate `self.llm.temperature` at node runtime (avoid the pattern in `prose.py:_generate_prose_node` where `self.llm.temperature = state.temperature` is set mid-call — this is not thread-safe)
- **Every `json.loads()` on LLM output must be wrapped in `try/except (json.JSONDecodeError, ValueError)`** — LLM responses are non-deterministic; an unguarded parse crashes the pipeline. Flag as **blocking** in both workflow nodes and standalone scripts. (Missed in PR-15: `get_llm_answer_with_parent/without_parent`; missed in PR-8: `extract_relations`)

### 5. Node Return Type Consistency
LangGraph node methods must return the **same type** they receive:
- Nodes in `workflows/prose.py` mutate and return the state object — is the PR consistent with this?
- Nodes in `workflows/idea_capture.py` return dicts keyed by state field names — is the PR consistent?
- Mixing return styles within a single workflow breaks LangGraph state merging.

### 6. Error Handling in UI vs Workflows
- **UI layer** (`ui/*.py`): all workflow calls MUST be wrapped in `try/except Exception as e` → `st.error(f"...: {str(e)}")` (see `ui/idea_ui.py:idea_capture_tab`)
- **Workflow nodes** (`workflows/*.py`): nodes should NOT silently swallow exceptions — let them bubble to the UI layer
- **Voice layer** (`voice/streamlit_voice.py`): optional deps MUST use the `try/except ImportError` + `_<DEP>_AVAILABLE` flag pattern; never assume voice deps are installed
- **Bare `except:` blocks** (`except:` or `except Exception: pass` with no logging): flag as a **warning** anywhere they appear. Silent discard of errors makes it impossible to detect how many records were dropped. Require at minimum a `logger.warning(...)` or counter increment. (Missed in PR-8: `extract_relations` bare `except` swallowed JSON parse errors with no log)

### 7. `st.session_state` Key Hygiene
All new Streamlit session state keys initialized in `streamlit_app.py:main()` under the `if "clarus_app" not in st.session_state:` block. Check:
- Is the new key initialized there before any UI file reads it?
- Does the Reset Session `st.button` block also clear the new key?
- UI files must access state as `st.session_state.key` (attribute style), not `st.session_state["key"]` — be consistent with the existing codebase

### 8. `load_dotenv()` Placement
`load_dotenv()` is called in both `app.py` (line ~13) and `streamlit_app.py` (line ~17). A PR should not add a third call in a workflow or model file — env vars are loaded by the entry points only.

### 9. `Assertion.id` as String UUID
`Assertion.id` is typed `str`, not `int` or `uuid.UUID`. Any code that generates new assertions must create IDs as string UUIDs (e.g., `str(uuid.uuid4())`). Relationship `assertion1_id` / `assertion2_id` must reference valid `Assertion.id` values — check for stale ID references after assertion list mutations.

### 10. `model_dump()` Not `.dict()`
All Pydantic serialization must use `.model_dump()` (Pydantic v2). Using `.dict()` will raise a deprecation warning and break in future Pydantic releases. The existing codebase is consistent: `app.py:export_assertions`, `ui/common.py:export_assertions_button`.

### 11. `@st.cache_resource` for Heavy Objects
Any new function that loads a ML model or large resource must use `@st.cache_resource(show_spinner=False)`. Do NOT use `@st.cache_data` for model objects. See `voice/streamlit_voice.py:load_whisper_model` and `get_vosk_model`.

### 12. `langgraph.json` Registration
New workflow graphs intended for LangGraph Studio must be registered in `langgraph.json` under `"graphs"` as `"<name>": "./workflows/<file>.py:<factory_function>"`. Confirm the factory function name matches the registered entry point exactly.

### 13. Relationship Type Exhaustiveness
`Relationship.relationship_type` is a `Literal["evidence", "background", "cause", "contrast", "condition", "contradiction"]`. Any code that creates or filters relationships must use one of these six exact strings — no new types can be added without updating `models/assertions.py` AND all workflow prompt engineering that enumerates them.

### 14. `ChangeHistory` Mutation Pattern
`ChangeHistory.add_change()` is the only valid way to add a record. Do not append directly to `change_history.changes`. Any workflow node that modifies assertions must record a `ChangeRecord` with `change_type` in `Literal["add", "remove", "modify"]`.

### 15. No New Top-Level Scripts
The entry point is `streamlit run streamlit_app.py`. `app.py` is an orchestration module, not a second entry point (despite its `if __name__ == "__main__":` block, README does not document running it). New executable scripts should not be added at the repo root without README documentation.

### 16. Test Coverage
The repo has **no test suite on main**, but PRs that add non-trivial logic should be flagged (as a warning). Specifically flag when:
- New functions contain index-mapping, LLM post-processing, or JSON parsing logic with no tests
- Existing test files or fixtures are **deleted** without replacement (always check the PR diff for removed `test_*.py` files or `@pytest.fixture` blocks)
- New LLM-based methods are added with no mock or unit tests

Evidence: Both PR-8 and PR-15 introduced complex logic; neither reviewer flagged missing test coverage.

### 17. New Standalone Scripts (outside `workflows/`, `ui/`, `models/`, `voice/`)
When a PR adds scripts in `src/`, `scripts/`, or elsewhere outside the main app layers, apply this additional checklist:

**a. Optional/heavy dependency imports** — `unsloth`, `torch`, `transformers`, GPU packages, etc. must use `try/except ImportError` + `_<DEP>_AVAILABLE` flag (same pattern as `voice/streamlit_voice.py`). Unconditional top-level imports of GPU-only packages raise `ImportError` on CPU-only machines. Flag as **blocking**. (Missed in PR-8: `unsloth` imported unconditionally in `get_assertions_and_relations.py`)

**b. File I/O safety** — Any `open(path, "w")` or `json.dump` writing to a path must be preceded by `os.makedirs(os.path.dirname(path), exist_ok=True)` or equivalent. Omitting this causes `FileNotFoundError` when the output directory doesn't exist. Flag as **blocking**. (Missed in PR-8: `prepare_data.py` and both `get_assertions_and_relations*.py`)

**c. API call loops — retry and checkpointing** — Loops calling an LLM or external API over a list of items (papers, rows, etc.) with no per-iteration error handling, retry logic, or partial-result checkpointing abort the entire run on a single transient error. Flag as a **warning**. (Missed in PR-8: both scripts iterate over up to 50 papers with no retry)

**d. LLM JSON response parsing** — See item 4: every `json.loads()` on LLM output must have `try/except`. This applies equally here. Flag as **blocking**.

**e. Environment variable validation** — Scripts constructing API clients (`openai.OpenAI()`, etc.) must check the required env var before calling the constructor:
  ```python
  api_key = os.environ.get("OPENAI_API_KEY")
  if not api_key:
      raise ValueError("OPENAI_API_KEY is not set")
  client = openai.OpenAI(api_key=api_key)
  ```
  A missing key produces a cryptic SDK exception otherwise. Flag as **blocking**. (Missed in PR-8: `get_assertions_and_relations_openai.py` constructs `openai.OpenAI()` with no key check)

**f. String comparison case sensitivity** — Comparisons like `keyword in paper.title.lower()` silently return zero results if `keyword` is not also lowercased. Scan all `in`, `==`, `.startswith()`, `.find()` calls that apply `.lower()` to only one side. Flag as **blocking**. (Missed in PR-8: `prepare_data.py` lowercased `paper.title` but not `keyword_string`)

**g. LLM output index convention (0-based vs 1-based)** — LLMs naturally produce 1-based indices when referencing items in a list. If code uses LLM-returned integers to index a Python list (e.g., `assertions[llm_index]`), verify whether the prompt enforces 0-based output or whether the code subtracts 1. An uncorrected mismatch silently produces wrong mappings. Flag as **blocking** when no adjustment exists. (Missed in PR-8: `extract_relations` uses LLM-returned indices as direct array indices)

**h. Code duplication across parallel variants** — When a PR adds two near-identical files (e.g., `get_assertions_and_relations.py` and `get_assertions_and_relations_openai.py`), check whether shared logic is duplicated verbatim. Duplicated functions mean bugs fixed in one copy won't be fixed in the other. Flag as a **warning** and recommend factoring shared code into `src/utils/`. (Missed in PR-8: `extract_relations` duplicated verbatim)

**i. Generated/derived data files committed to git** — Files in `data/` that are outputs of the PR's scripts (`.jsonl`, `.json`, `.csv`) should not be committed. Flag as a **warning**: suggest `.gitignore` entries and reproduction instructions. (Missed in PR-8: `data/selected_paper_abstracts.jsonl`, `data/generated_assertions.jsonl`, `data/generated_relations.jsonl`)

### 18. Hardcoded Literals Audit in New Functions
When reviewing new functions that accept arguments representing IDs, types, or numeric scores, scan for **all** hardcoded literals in the function body — not just the most obvious ones. Common missed cases alongside obvious ones:
- Numeric scores: `confidence=0.8`, `threshold=0.5` that should come from an argument
- String IDs alongside type strings: if `parent_id="P1"` is caught, also check `confidence=0.8` in the same function

A function that hard-codes any argument-derived value is broken regardless of which specific literal was caught. Enumerate **all** hardcoded literals in the finding.

Evidence: PR-15 review caught `parent_id="P1"` and `relation_type="cause"` in `get_llm_answer_with_parent` but missed `confidence=0.8` and `confidence=0.75` in the same function — caused a grading failure.

---

## Reference Files

- **Naming, imports, and error conventions** → read `skills/aircode610/Clarus/references/conventions.md`
- **Known pitfalls from past reviews** → read `skills/aircode610/Clarus/references/common-issues.md`

---

## Review Output Format

Return your review as a JSON object with this schema:

```json
{
  "summary": "<1-2 sentence overview of the PR>",
  "verdict": "approve" | "request_changes" | "comment",
  "checklist": [
    {
      "item": "<checklist item number and name, e.g. '4. LLM Invocation Pattern'>",
      "status": "pass" | "fail" | "n/a",
      "finding": "<concrete finding referencing file:line — empty string if pass>"
    }
  ],
  "blocking_issues": [
    {
      "file": "<path/to/file.py>",
      "line_hint": "<line number or range if known>",
      "description": "<precise description of the problem>",
      "fix": "<concrete fix instruction>"
    }
  ],
  "suggestions": [
    {
      "file": "<path/to/file.py>",
      "description": "<non-blocking improvement>",
      "rationale": "<why, referencing repo conventions>"
    }
  ]
}
```

`verdict` must be `"request_changes"` if any `blocking_issues` exist.
