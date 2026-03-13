# matplotlib/matplotlib — Repository Conventions

Derived from `doc/devel/coding_guide.rst`, `doc/devel/api_changes.rst`,
`doc/devel/pr_guide.rst`, `pyproject.toml`, `.pre-commit-config.yaml`, and direct
source inspection.

---

## 1. Naming Patterns

### Files & Modules
- Source lives in `lib/matplotlib/<module>.py`; stub types in `lib/matplotlib/<module>.pyi`.
- Test files: `lib/matplotlib/tests/test_<module>.py` (mirrors the module name exactly).
  - Toolkits: `lib/mpl_toolkits/<toolkit>/tests/test_<module>.py`
- C/C++ interface wrappers: `FOO_wrap.cpp` or `FOO_wrapper.cpp` in `src/`.
- Gallery examples: `galleries/examples/<category>/<name>.py` (underscore-separated).
- What's-new RST notes: `doc/release/next_whats_new/<short_description>.rst`
- API-change RST notes: `doc/api/next_api_changes/<kind>/<short_description>.rst`
  - `<kind>` is one of: `deprecations`, `removals`, `behavior`, `development`.
  - **Common mistake:** the directories are `behavior` and `development`, NOT
    `behavior_changes` or `development_changes`. Always use the short form.

### Classes & Functions
- Public: `CamelCase` for classes, `snake_case` for functions/methods/variables.
- Private/internal: prefix with a single underscore (`_my_helper`, `_log`, `_validators`).
- Module-level sentinel values: `UPPER_CASE` (e.g., `_api.UNSET`).

### Variable Names (enforced by coding guide)
| Object type                        | Preferred variable name |
|------------------------------------|------------------------|
| `FigureBase` / `Figure`            | `fig`                  |
| `Axes`                             | `ax`                   |
| `Transform`                        | `trans`                |
| `Transform` (source → target)      | `trans_<source>_<target>` |
| Multiple instances of same class   | add number/letter suffix |

### rcParams keys
- Must be added to `_validators` dict in `lib/matplotlib/rcsetup.py`.
- Must be added (commented out) to `lib/matplotlib/mpl-data/matplotlibrc`.
- Must be added to the `RcKeyType` `Literal` in `lib/matplotlib/typing.py` **only when a
  new key is introduced**. If the PR only extends an existing validator (e.g., adds a
  new accepted string to an existing `validate_*` function without registering a new key
  in `_validators`), `typing.py` does not need to change. Do not flag it as missing in
  that case.

---

## 2. Import Ordering & Grouping

**Standard scipy/matplotlib conventions** (from `doc/devel/coding_guide.rst`):

```python
# Standard library
import logging

# NumPy / scientific stack (always aliased exactly as below)
import numpy as np
import numpy.ma as ma

# matplotlib — aliased exactly as below
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.cbook as cbook
import matplotlib.patches as mpatches
```

**Rules:**
- `isort` is only applied to `galleries/tutorials/`, `galleries/examples/`, and
  `galleries/plot_types/` (see `.pre-commit-config.yaml` — `isort` hook `files` filter).
  It is **not** applied to `lib/`.
- In `lib/`, imports are not mechanically sorted but follow the pattern: stdlib →
  third-party (numpy first) → intra-package.
- Never use `from matplotlib import rcParams`. Always use `mpl.rcParams` to avoid
  early-import issues.

---

## 3. Error Handling & Validation Patterns

Use `_api` helpers for all input validation in `lib/matplotlib/`. Never use bare
`raise ValueError(...)` for common patterns.

```python
from matplotlib import _api

# Type check
_api.check_isinstance((str, Path, None), filename=filename)

# Enumerated value check
_api.check_in_list(['linear', 'log', 'symlog', 'logit'], scale=scale)

# Array shape check (None = free dimension)
_api.check_shape((None, 2), points=points)

# Unknown key in a mapping
_api.getitem_checked(cmap_registry, cmap=name)
```

**Warning patterns:**

```python
# For user-facing runtime warnings (appears at user's call site, not matplotlib's):
from matplotlib import _api
_api.warn_external("Some message the user should act on.")

# For deprecation warnings:
_api.warn_deprecated("3.11", message="...", alternative="...")

# For logging (debug/info, NOT user-facing):
import logging
_log = logging.getLogger(__name__)   # module-level, right after imports
_log.debug("Processing %s", fname)  # NO f-strings in log calls
_log.info("Object not drawn: %s", reason)
```

**Never:**
- `print(...)` in library code (use `_log.debug` / `_log.info`)
- `warnings.warn(msg, DeprecationWarning)` directly (use `_api.warn_deprecated`)
- `warnings.warn(msg, UserWarning)` directly in matplotlib internals (use
  `_api.warn_external`)
- f-strings as the first argument to any logging call (security + performance)

---

## 4. Logging Convention

```python
# At module top-level, after imports:
_log = logging.getLogger(__name__)
# → produces logger named "matplotlib.<module_name>"

# Usage:
_log.debug("Normal intermediate step: %s", detail)
_log.info("Unexpected but non-fatal situation: %s", situation)
# logging.warning / logging.error are for truly exceptional conditions
```

Logging level guide:
- `debug` — expected code-path details (layout, rendering steps)
- `info` — non-fatal unexpected situations (NaN positions, skipped draws)
- `warning` / `error` — only for errors that end library use but don't kill the process

---

## 5. Deprecation Patterns

### Introducing (warn users, keep old behavior)

```python
from matplotlib import _api

# General case
def old_function(...):
    _api.warn_deprecated("3.11", name="old_function", alternative="new_function")

# Whole function/class/method
@_api.deprecated("3.11", alternative="NewClass")
class OldClass: ...

# Parameter removal
@_api.delete_parameter("3.11", "old_param")
def my_func(x, old_param=None): ...

# Parameter rename
@_api.rename_parameter("3.11", "old_name", "new_name")
def my_func(x, new_name): ...

# Make positional arg keyword-only
@_api.make_keyword_only("3.11", "param")
def my_func(x, param): ...

# Attribute → private
@_api.deprecate_privatize_attribute("3.11", alternative="._private")
class Foo:
    public_attr = ...
```

`since` must always be the **next meso release** (e.g., `"3.11"`).

### Expiry (remove old behavior, 2 meso releases after introduction)
- Remove the decorator and old code path.
- Remove corresponding entries from `ci/mypy-stubtest-allowlist.txt`.

### Documentation
- Introduction → `doc/api/next_api_changes/deprecations/<name>.rst`
- Expiry → `doc/api/next_api_changes/removals/<name>.rst` (copy/adapt intro notice)
- New feature → `doc/release/next_whats_new/<feature>.rst`

---

## 6. Keyword Argument Processing

The canonical pattern for pass-through vs local consumption:

```python
# Pass-through (kwargs forwarded to child artist):
def scatter(self, x, y, **kwargs):
    return PathCollection(..., **kwargs)

# Local consumption + pass-through (keyword-only for local args):
def plot(self, *args, scalex=True, scaley=True, **kwargs):
    # scalex/scaley are consumed here; rest go to Line2D
    ...

# WRONG — popping from **kwargs hides the API:
def plot(self, *args, **kwargs):
    scalex = kwargs.pop('scalex', True)   # don't do this
```

---

## 7. Test Patterns

### File structure
- `lib/matplotlib/tests/test_<module>.py`
- `lib/mpl_toolkits/<toolkit>/tests/test_<module>.py`

### Function naming
```python
def test_<descriptive_behavior>():   # NOT test1, testFoo
```

### Required imports in test files
```python
import pytest
import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.<module> as m<abbrev>
from matplotlib.testing.decorators import check_figures_equal, image_comparison
```

### Image-comparison tests
```python
@image_comparison(['baseline_name'], remove_text=True, style='default')
def test_my_plot():
    fig, ax = plt.subplots()
    ax.plot(...)
    # Don't call plt.show() or savefig() — the decorator handles it
```
- Baseline images live in `lib/matplotlib/tests/baseline_images/<test_module>/`.
- If the rendering changes, the baseline PNG **must** be regenerated and committed.
- `remove_text=True` strips tick labels/titles to reduce sensitivity to font changes.

### Figure-equality tests (preferred for new tests when possible)
```python
@check_figures_equal()
def test_equivalent_apis(fig_test, fig_ref):
    ax_test = fig_test.subplots()
    ax_ref = fig_ref.subplots()
    ax_test.scatter(...)       # new API path
    ax_ref.scatter(...)        # reference path
```

### Deprecation warning tests
```python
with pytest.warns(mpl.MatplotlibDeprecationWarning, match="expected message"):
    result = deprecated_function()
```

### rcParams mutation in tests
Any test that modifies `rcParams` **must** isolate the change using `mpl.rc_context`:
```python
# CORRECT — mutations are rolled back after the with-block
with mpl.rc_context({'lines.linewidth': 3}):
    ax.plot(x, y)

# CORRECT — decorator form for entire test functions
@mpl.rc_context({'axes.facecolor': 'black'})
def test_dark_background():
    ...

# WRONG — leaks rcParam change to subsequent tests
mpl.rcParams['lines.linewidth'] = 3
```
Flag any test that mutates `mpl.rcParams[...]` directly without wrapping it in
`mpl.rc_context(...)` or the `@mpl.rc_context` decorator.

### Parametrize
```python
@pytest.mark.parametrize('value,expected', [
    ('linear', True),
    ('log', True),
    ('invalid', False),
])
def test_scale_valid(value, expected):
    ...
```

---

## 8. Docstring Convention (NumPy style)

All public API uses NumPy-style docstrings. **Not Google, not reStructuredText-only.**

```python
def my_function(x, y, *, color='blue'):
    """
    One-line summary (imperative mood, no trailing period in summary).

    Extended description paragraph. May span multiple lines.

    Parameters
    ----------
    x : array-like
        Description of x.
    y : float
        Description of y.
    color : color, default: 'blue'
        Description of color. Use :rc:`axes.facecolor` for the default.

        .. versionadded:: 3.11

    Returns
    -------
    Artist
        The created artist.

    Examples
    --------
    .. plot::

        fig, ax = plt.subplots()
        ax.my_function([1, 2, 3], [4, 5, 6])
    """
```

**Key rules:**
- Summary line: imperative, one sentence, no trailing period (`Plot x versus y.`).
- `.. versionadded:: 3.N` goes at the **end** of a parameter description (not before
  `Parameters`).
- For whole functions/classes: `.. versionadded:: 3.N` goes **before** `Parameters`.
- No cross-references in RST **section titles**.
- Use `` `.ClassName` `` for same-module cross-refs; `` `~module.ClassName` `` for
  others; `` `~.ClassName` `` as shorthand.
- `rcParams` cross-refs use `` :rc:`axes.facecolor` ``.
- Discouraged (not deprecated) API: add ``.. admonition:: Discouraged`` in the docstring.

---

## 9. C/C++ Extension Conventions

- Interface code: `FOO_wrap.cpp` or `FOO_wrapper.cpp` (separate from core C++ logic).
- Code style: PEP7 for C extensions; C++ does not have a direct PEP but same spirit.
- Header docstrings: NumPy format.
- Vendored code in `extern/`: keep close to upstream; **no style fixes**.
- New files in `src/` must be listed in `meson.build`.

---

## 10. meson.build Requirements

Any new file must be added to the `meson.build` in its **directory**:
- New Python `.py` file → `lib/matplotlib/meson.build` (or subdirectory build file).
- New data file → corresponding `install_data(...)` call.
- New C/C++ source → add to the `extension_module(...)` sources list.

Omitting this will cause the file to not be installed in wheel/sdist builds.

---

## 11. PostScript Backend Conventions (`backends/backend_ps.py`)

When reviewing new rendering methods in `backend_ps.py`, check:

1. **`newpath` before path accumulation.** The PS `gsave` operator saves the graphics
   state but does NOT clear the current path. Any new method that accumulates path
   segments must call `newpath` first, otherwise segments from a prior drawing operation
   contaminate the new path. PDF and SVG backends implicitly start fresh paths; PS does
   not.
   ```postscript
   % CORRECT
   newpath
   moveto lineto ... fill

   % WRONG — gsave does not clear the current path
   gsave moveto lineto ... fill grestore
   ```

2. **Fill glyphs individually, not as accumulated paths.** New glyph-rendering methods
   should fill each glyph immediately after constructing its path, matching the behavior
   of the PDF and SVG backends. Accumulating all glyphs into one path before filling
   produces incorrect rendering when glyphs overlap or have transparency.
