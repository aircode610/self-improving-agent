# Clarus Conventions

Conventions extracted directly from the codebase at `aircode610/Clarus` (main branch, 2026-03-13).

---

## 1. File & Module Naming

| Layer | Pattern | Examples |
|-------|---------|---------|
| Workflow files | `<workflow_name>.py` — snake_case, noun | `idea_capture.py`, `conflict_resolving.py`, `prose.py` |
| UI files | `<mode_name>_ui.py` | `idea_ui.py`, `structure_ui.py`, `review_ui.py`, `prose_ui.py` |
| Model files | noun, singular | `assertions.py`, `states.py` |
| Voice files | `streamlit_voice.py` (one file, no splitting) | |
| Test files | **none exist** — no test suite in this repo | |
| Constants/config | `UPPER_SNAKE_CASE` module-level variables | `VOSK_MODELS`, `MODELS_DIR` in `voice/streamlit_voice.py` |

No `test_*.py`, `*_test.py`, or `conftest.py` files exist anywhere in the repo.

---

## 2. Class Naming

- All classes are `PascalCase`.
- Workflow orchestrator classes: `<Mode>Workflow` — e.g., `IdeaCaptureWorkflow`, `StructureWorkflow`, `ReviewWorkflow`, `ProseWorkflow`.
- State classes: `<Mode>State` — e.g., `IdeaCaptureState`, `StructureState`, `ReviewState`, `ProseState`.
- Data model classes: descriptive nouns — `Assertion`, `Relationship`, `Paragraph`, `Issue`, `ChangeRecord`, `ChangeHistory`.
- Graph utility class: `GlobalGraph` (in `workflows/conflict_resolving.py`).

---

## 3. Function & Method Naming

### Workflow class methods
```python
# Private node methods — always _<verb>_<object>_node
def _extract_assertions_node(self, state: IdeaCaptureState) -> ...:
def _update_assertions_node(self, state: IdeaCaptureState) -> ...:
def _prepare_input_node(self, state: ProseState) -> ProseState:
def _generate_prose_node(self, state: ProseState) -> ProseState:
def _finalize_text_node(self, state: ProseState) -> ProseState:

# Public interface
def run(self, ...) -> Dict[str, Any]:

# Lazy graph property
@property
def graph(self): ...

# Private graph builder
def _build_graph(self) -> StateGraph: ...
```

### Module-level factory functions (required for `langgraph.json`)
```python
# Pattern: create_<workflow_name>_workflow(config=None)
def create_idea_capture_workflow(config: dict = None): ...
def create_structure_workflow(config: dict = None): ...
def create_review_workflow(config: dict = None): ...
def create_prose_workflow(config: dict = None): ...

# Second factory for LangGraph Studio graph object
def create_idea_capture_graph(): ...
def create_structure_graph(): ...
def create_review_graph(): ...
```

### UI functions
```python
# Top-level tab function — called by streamlit_app.py
def idea_capture_tab(): ...
def structure_tab(): ...
def review_tab(): ...
def prose_tab(): ...

# Shared helpers in ui/common.py — snake_case verb_noun
def display_assertions(assertions: List[Assertion]): ...
def create_assertion_groups(assertions, relationships): ...
def export_assertions_button(): ...
def clear_assertions_button(): ...
def next_mode_button(current_mode: str, next_mode: str, help_text: str): ...
```

### ClarusApp methods (app.py)
```python
def start_idea_capture(self, initial_input: str, session_id: str = None) -> Dict[str, Any]: ...
def continue_idea_capture(self, user_input: str) -> Dict[str, Any]: ...
def process_mixed_input(self, user_input: str, deleted_assertions: List[str] = None) -> Dict[str, Any]: ...
def start_structure_analysis(self, assertions=None, session_id=None) -> Dict[str, Any]: ...
def get_current_assertions(self) -> List[Assertion]: ...
def get_current_mode(self) -> str: ...
def reset_session(self): ...
def export_assertions(self) -> List[Dict[str, Any]]: ...
def import_assertions(self, assertions_data: List[Dict[str, Any]]): ...
def get_workflow_status(self) -> Dict[str, Any]: ...
```

---

## 4. Variable Naming

- Local variables: `snake_case`
- Session state keys: `snake_case` strings matching the local variable name (e.g., `st.session_state.assertions`, `st.session_state.clarus_app`, `st.session_state.deleted_assertions`)
- Boolean availability flags in voice module: `_<PACKAGE>_AVAILABLE` (e.g., `_AUDIORECORDER_AVAILABLE`, `_VOSK_AVAILABLE`, `_PYDUB_AVAILABLE`, `_FASTER_WHISPER_AVAILABLE`, `_VOICE_AVAILABLE`)
- Confidence scores: always named `confidence` (float, range 0–1)
- IDs: always named `id` on the model class, `<model>_id` in referencing classes (e.g., `assertion1_id`, `paragraph_id`, `issue_id`)

---

## 5. Import Ordering and Grouping

The project follows this import order (observed across `app.py`, `workflows/prose.py`, `ui/idea_ui.py`, `voice/streamlit_voice.py`):

```python
# 1. stdlib — warnings, os, io, typing, datetime, uuid, etc.
import warnings
import os
from typing import List, Dict, Any, Optional, Literal, Annotated

# 2. Third-party (in rough dependency order)
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
import streamlit as st
import networkx as nx
import plotly.graph_objects as go

# 3. Internal — absolute from package root (NOT relative for cross-package)
from models import Assertion, Relationship, Paragraph, Issue, ProseState
from workflows.idea_capture import IdeaCaptureWorkflow
from app import create_clarus_app

# 4. Intra-package — relative imports only within the same package
from .common import display_assertions, export_assertions_button
import voice.streamlit_voice as streamlit_voice
```

Key rules:
- `models.*` imports use **absolute** style from the repo root: `from models import Assertion`
- `ui/*.py` files use **relative** imports for siblings: `from .common import display_assertions`
- `workflows/*.py` files use **absolute** imports for models: `from models import ...`
- `app.py` uses absolute imports for both `models` and `workflows.idea_capture`

---

## 6. Module Docstrings

Every Python file opens with a triple-quoted module docstring:

```python
"""
<Title Line>

<One paragraph describing what the module does and its role in the system.>
"""
```

Examples:
- `app.py`: `"""Main Clarus Application\n\nThis module provides the main application class...`
- `models/assertions.py`: `"""Data models for assertions and relationships.\n\nThis module defines the core data structures...`
- `workflows/prose.py`: `"""Prose Workflow - Transform structured paragraphs into fluent text\n\nThis module implements the final step...`
- `ui/common.py`: `"""Common UI components and utilities for the Clarus application.\n\nThis module contains shared UI components...`

---

## 7. Pydantic Model Conventions

All domain models and state classes extend `pydantic.BaseModel` (Pydantic v2).

```python
class Assertion(BaseModel):
    """Represents a discrete, atomic assertion extracted from user input."""
    id: str = Field(description="Unique identifier for the assertion")
    content: str = Field(description="The actual assertion text")
    confidence: float = Field(description="Confidence score (0-1) for this assertion")
    source: str = Field(description="Source text that led to this assertion")
```

Rules:
- Every field has a `Field(description=...)` annotation — no bare `= None` without description
- List fields use `Field(default_factory=list)` — never `= []`
- Constrained string enums use `Literal["a", "b"]` — never `enum.Enum`
- Serialization: `.model_dump()` only — `.dict()` is Pydantic v1 and forbidden
- Validation: `Assertion(**data)` for construction from dicts (see `app.py:import_assertions`)

---

## 8. LangGraph State Conventions

State classes live in `models/states.py`. Messages field canonical form:

```python
from typing import Annotated, List
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field

class IdeaCaptureState(BaseModel):
    messages: Annotated[List[BaseMessage], add_messages] = Field(default_factory=list)
    assertions: List[Assertion] = Field(default_factory=list)
    current_input: str = Field(default="")
    chat_summary: str = Field(default="")
```

States that carry conversation context always include `messages` + `current_input` + `chat_summary`.
States that don't need conversation history (e.g., `ProseState`) still carry `messages` for LangGraph compatibility.

---

## 9. Error Handling Patterns

### UI layer — always catch and display
```python
# ui/idea_ui.py — canonical pattern
try:
    result = st.session_state.clarus_app.process_mixed_input(
        prompt,
        st.session_state.get("deleted_assertions", [])
    )
    # ... process result
except Exception as e:
    error_msg = f"Sorry, I encountered an error: {str(e)}"
    st.error(error_msg)
    st.session_state.messages.append({"role": "assistant", "content": error_msg})
```

### Voice module — optional dependency guard at import time
```python
# voice/streamlit_voice.py — canonical pattern
try:
    from audiorecorder import audiorecorder
    _AUDIORECORDER_AVAILABLE = True
except ImportError:
    _AUDIORECORDER_AVAILABLE = False
    audiorecorder = None

# Aggregate flag
_VOICE_AVAILABLE = all([_AUDIORECORDER_AVAILABLE, _VOSK_AVAILABLE, _PYDUB_AVAILABLE, _FASTER_WHISPER_AVAILABLE])

# Usage guard inside function
def whisper_voice_to_text(...):
    if not _VOICE_AVAILABLE:
        st.info("🎤 Voice input is not available. Please install voice dependencies...")
        return
```

### Workflow nodes — do NOT catch exceptions
Workflow nodes (`_*_node` methods) let exceptions propagate. The UI catches them. Example from `workflows/prose.py`:
```python
def _generate_prose_node(self, state: ProseState) -> ProseState:
    # No try/except — exceptions bubble to the UI layer
    response = self.llm.invoke([message])
    generated_text = getattr(response, "content", str(response))
    state.generated_text = generated_text
    return state
```

### app.py — selective exception for mode validation
`ClarusApp.continue_idea_capture` raises `ValueError` for invalid mode, but does not catch LLM errors:
```python
if self.current_mode != "idea_capture":
    raise ValueError("Not currently in idea capture mode")
```

---

## 10. LLM Invocation Pattern

```python
# Standard pattern (workflows/prose.py, workflows/idea_capture.py, etc.)
from langchain_core.messages import HumanMessage
message = HumanMessage(content=prompt)
response = self.llm.invoke([message])
text = getattr(response, "content", str(response))
```

- `self.llm` is `ChatOpenAI(model=self.model_name, temperature=0.3)` initialized in `__init__`
- Default model: `"gpt-4o-mini"` (set in `ClarusApp.__init__` and each `*Workflow.__init__`)
- Default temperature: `0.3`
- Structured output (used in idea_capture/structure/review for JSON extraction): likely `self.llm.with_structured_output(SomePydanticModel)`

---

## 11. Streamlit Session State Conventions

All keys initialized in `streamlit_app.py` under the single guard:
```python
if "clarus_app" not in st.session_state:
    st.session_state.clarus_app = create_clarus_app()
    st.session_state.messages = []
    st.session_state.assertions = []
    st.session_state.deleted_assertions = []
    st.session_state.current_mode = "Idea Capture"
    # ... all other keys
```

The Reset Session button clears **all** initialized keys back to their defaults.

Access pattern: always attribute-style `st.session_state.key` (not dict-style `st.session_state["key"]`).

Defensive reads use `.get()`: `st.session_state.get("deleted_assertions", [])`.

---

## 12. `__all__` Completeness in `__init__.py` Files

Both `models/__init__.py` and `workflows/__init__.py` maintain explicit `__all__` lists that must include every public symbol:

```python
# models/__init__.py
from .assertions import Assertion, Relationship
from .states import IdeaCaptureState, StructureState, ChangeRecord, ChangeHistory, ReviewState, ProseState, Paragraph, Issue

__all__ = [
    "Assertion", "Relationship",
    "IdeaCaptureState", "StructureState", "ChangeRecord", "ChangeHistory",
    "ReviewState", "ProseState", "Paragraph", "Issue"
]
```

Any new model class must be added to **both** the import line and `__all__`.

---

## 13. `load_dotenv()` Placement

Called exactly twice — once in `app.py` (module level, after stdlib imports) and once in `streamlit_app.py` (module level, after stdlib imports). Must not be added to workflow or model files.

```python
# app.py lines 11-13 (canonical)
import os
from dotenv import load_dotenv
load_dotenv()
```

---

## 14. Relationship Type Vocabulary

The six valid `Relationship.relationship_type` literals (from `models/assertions.py`):
```python
Literal["evidence", "background", "cause", "contrast", "condition", "contradiction"]
```

Any prompt engineering that instructs the LLM to produce relationship types must enumerate exactly these six strings.

---

## 15. `Assertion.id` Generation

IDs are `str`. New assertions must use `str(uuid.uuid4())` or equivalent. The `id` field carries no default factory — callers must supply it. References in `Relationship.assertion1_id` / `assertion2_id` must point to existing `Assertion.id` values.
