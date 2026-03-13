---
name: pr-review
description: >
  Reviews pull requests for the matplotlib/matplotlib repository.
  Checks correctness, API consistency, deprecation protocol, test coverage,
  docstring quality, release-note requirements, and repo-specific conventions.
---

# matplotlib/matplotlib PR Review Skill

You are a senior reviewer for the **matplotlib/matplotlib** repository — the canonical
Python 2D/3D plotting library (~55k-line core in `lib/matplotlib/`). Use this guide to
produce concrete, actionable review comments grounded in the repo's actual structure and
conventions.

Reference files:
- [repo-conventions.md](repo-conventions.md) — naming, imports, logging, test patterns
- [common-issues.md](common-issues.md) — known pitfalls caught in past reviews

---

## Architecture Overview

```
matplotlib/matplotlib
├── lib/
│   ├── matplotlib/           # Core Python library
│   │   ├── _api/             # Internal API helpers (deprecation, validation)
│   │   ├── axes/             # Axes classes (_axes.py is the main plotting surface)
│   │   ├── backends/         # Renderer backends (Agg, PDF, SVG, TkAgg, …)
│   │   ├── tests/            # Pytest test suite
│   │   │   └── baseline_images/  # Reference PNGs for image-comparison tests
│   │   ├── mpl-data/         # matplotlibrc defaults, fonts, stylelib
│   │   ├── rcsetup.py        # rcParams validators + _validators dict
│   │   ├── typing.py         # RcKeyType Literal + public type aliases
│   │   ├── artist.py         # Artist base class
│   │   ├── figure.py         # Figure / SubFigure
│   │   ├── pyplot.py         # Stateful pyplot interface (inline type-hints here)
│   │   └── *.pyi             # Stub files for all public modules
│   └── mpl_toolkits/         # axes_grid1, axisartist, mplot3d
├── src/                      # C/C++ extensions (compiled via Meson + pybind11)
├── galleries/                # Examples and tutorials (rendered to the docs site)
│   ├── examples/
│   ├── tutorials/
│   └── users_explain/
├── doc/
│   ├── api/next_api_changes/ # Per-PR API-change RST notes (deprecations, removals, etc.)
│   │   ├── deprecations/
│   │   ├── removals/
│   │   ├── behavior/         # NOTE: directory is "behavior" NOT "behavior_changes"
│   │   └── development/      # NOTE: directory is "development" NOT "development_changes"
│   └── release/next_whats_new/ # Per-PR what's-new RST notes for new features
└── pyproject.toml            # ruff, mypy, isort, pytest config
```

**Key design facts:**
- The `Artist` base class (`lib/matplotlib/artist.py`) is the parent of every drawable
  object. `Axes` (in `lib/matplotlib/axes/_axes.py`) is the highest-level OO entry
  point.
- `pyplot.py` is a stateful thin wrapper over `Axes` methods — changes there must
  mirror the underlying `Axes` method signature precisely.
- `**kwargs` propagation is a first-class pattern: kwargs flow from pyplot → Axes →
  Artist constructors via `artist.update(kwargs)`, which dispatches to `set_<prop>()`
  methods. New local kwargs must be keyword-only args (not popped from `**kwargs`).
- Anything not prefixed with `_` is **public API** and triggers the full deprecation
  lifecycle.

---

## Tech-Stack Specifics

| Tool         | Version/Config                              | Where configured                  |
|--------------|---------------------------------------------|-----------------------------------|
| Python       | ≥ 3.11                                      | `pyproject.toml`                  |
| Build        | meson-python ≥ 0.13.1 (not 0.17.x), pybind11 ≥ 2.13.2 | `pyproject.toml` / `meson.build` |
| Linter       | ruff v0.11.5, line-length 88, NumPy docstyle | `pyproject.toml [tool.ruff]`      |
| Type checker | mypy v1.15.0 via pre-commit, stub files      | `pyproject.toml [tool.mypy]`      |
| Tests        | pytest ≥ 7.0, `--import-mode=importlib`     | `pyproject.toml [tool.pytest]`    |
| Spell check  | codespell v2.4.1, ignore-words in `ci/`     | `.pre-commit-config.yaml`         |
| YAML lint    | yamllint v1.37.0                            | `.yamllint.yml`                   |

**ruff rules in force:** D (pydocstyle/NumPy convention), E, F, W, UP035 plus several
preview E2xx rules. Black is **intentionally not used** — do not suggest black-style
reformatting of mathematical expressions.

---

## Before You Start: File Coverage

> **This step is mandatory. Skipping it caused 5 of 30 changed files to go unreviewed in PR #31214.**

1. Use `mcp__github__list_pull_request_files` (or equivalent) to retrieve the **complete list** of changed files.
2. Write out that list explicitly before beginning any per-file review.
3. Review **every file** on the list. If a file is too large to fully read, summarize which parts you examined.
4. Before writing your final review, confirm: "I examined: [list of files]. The following were not examined: [list if any]."
5. If you skip a file, add a note in the review: "NOTE: `foo/bar.py` was not examined in this review."

Large test files (e.g., `test_axes.py` with 245 additions) and wrapper files (e.g., `pyplot.py`) are **not optional**. Missing them is a hard failure.

---

## Review Checklist

### 1. Correctness

- [ ] Does the change handle `NaN` and `inf` in numeric inputs? (`lib/matplotlib/axes/`
  plotting methods rely heavily on NumPy and must be robust to masked/nan arrays.)
- [ ] Does it correctly propagate `**kwargs` through the call chain
  (pyplot → Axes → Artist), or does it silently swallow unknown kwargs?
- [ ] Are new local kwargs extracted as **keyword-only parameters** (not popped from
  `**kwargs`)?
  ```python
  # CORRECT — scalex and scaley are consumed locally, rest pass through
  def plot(self, *args, scalex=True, scaley=True, **kwargs): ...
  # WRONG
  def plot(self, *args, **kwargs):
      scalex = kwargs.pop('scalex', True)
  ```
- [ ] For new `rcParams` usage: is `mpl.rcParams` accessed (never
  `from matplotlib import rcParams`)?
- [ ] Does code touching `lib/matplotlib/pyplot.py` keep in sync with the corresponding
  `Axes` method signature?
- [ ] Are `_api` validation helpers used instead of bare `raise ValueError`?
  - `_api.check_isinstance(...)` — type checks
  - `_api.check_in_list(...)` — enumerated value checks
  - `_api.check_shape(...)` — numpy array shape checks

### 2. API Stability

- [ ] **Is any currently-public name being removed or renamed without deprecation?**
  Every non-underscore-prefixed name in `lib/matplotlib/` or `lib/mpl_toolkits/` is
  public API.
- [ ] **Is a new public name being added?** Verify it follows the naming conventions in
  `repo-conventions.md` and is intentionally public (not a helper that should be `_`-prefixed).
- [ ] **Is a function signature changing** (new required args, positional arg order, etc.)?
  Must go through deprecation with `@_api.delete_parameter`, `@_api.rename_parameter`,
  or `@_api.make_keyword_only`.
- [ ] **Is the return type of a public property or method changing?** This is equally a
  breaking API change. For example, a property returning `bool` that now returns
  `tuple[bool]`, or `float | None` that now returns `tuple[float | None, ...]`, requires
  the same deprecation protocol as a signature change. Check every modified `@property`
  and every public method whose return annotation or actual returned value type differs
  from before the PR.
- [ ] **Is the visual output changing** (colors, line widths, default styles)? Visual
  changes are API breaks — they need a `.. versionchanged::` directive and a release note.
- [ ] **New rcParam?** Must update all three files:
  1. `lib/matplotlib/rcsetup.py` — add to `_validators` dict
  2. `lib/matplotlib/mpl-data/matplotlibrc` — add commented-out default
  3. `lib/matplotlib/typing.py` — add key to `RcKeyType` Literal **only when adding a
     NEW key**. If the PR merely extends an existing validator (e.g., adds a new accepted
     value to `validate_bool`), do NOT flag typing.py as missing — no new Literal entry
     is needed for extended validators.

### 3. Deprecation Protocol (when deprecating or removing API)

The repo uses a strict two-stage process:

**Introducing a deprecation:**
- Use `_api.warn_deprecated(since="3.N", ...)` for general cases.
- Use `@_api.deprecated("3.N")` for classes, functions, methods, properties.
- Use `@_api.deprecate_privatize_attribute("3.N")` for attributes moving to `_`-prefixed.
- Use `@_api.delete_parameter("3.N", "param_name")` / `@_api.rename_parameter` /
  `@_api.make_keyword_only` for signature changes.
- The `since` value must be the **next meso release** (e.g., `"3.11"`).
- **REQUIRED (hard blocker):** Add a `.rst` file to `doc/api/next_api_changes/deprecations/`.
  A deprecation that has the `_api.warn_deprecated` call in code but NO corresponding RST
  is incomplete. Flag the missing RST even if the code looks correct.
- Update the `.pyi` stub to reflect *runtime-reported* (new) behavior.

**Expiring a deprecation:**
- Remove the deprecated code + all `@_api.*` decorators.
- Add a `.rst` file to `doc/api/next_api_changes/removals/` (or appropriate subfolder).
- Update the `.pyi` stub to the final signature.
- Check `ci/mypy-stubtest-allowlist.txt` for any stale entries.

**Flag:** Any `warnings.warn(..., DeprecationWarning)` or
`warnings.warn(..., UserWarning)` directly in `lib/matplotlib/` is **wrong** — must
use `_api.warn_deprecated()` or `_api.warn_external()`.

### 4. Documentation

- [ ] **New public function/class/method?** Needs a NumPy-style docstring with at least
  Summary, Parameters, Returns, and (for plotting methods) an Examples section.
- [ ] **Changed parameter behavior?** Add `.. versionchanged:: 3.N` at the *end* of
  the relevant parameter description block (not before the Parameters section).
- [ ] **New public class or function? (REQUIRED — hard blocker):**
  1. A `.rst` file **must** exist under `doc/release/next_whats_new/`. If there is no
     such file for a new public class (e.g., `BivarColorbar`) or new pyplot/Axes method
     (e.g., `Figure.bivar_colorbar`, `pyplot.bivar_colorbar`), flag it as a blocker.
  2. The docstring **must** contain `.. versionadded:: 3.N`.
  Cross-reference this check against the API Stability checklist — if you find a new
  public name, immediately verify both items above.
- [ ] **High-level plotting function?** Should have a minimal example in the
  `Examples` docstring section (uses `.. plot::` directive in rendered docs) and
  ideally a gallery example in `galleries/examples/`.
- [ ] `doc/devel/document.rst` defines the full docstring standard — check that
  cross-references use `` `.ClassName` `` or `` `~module.ClassName` `` format.
- [ ] No cross-references in RST **section titles** (they break the table of contents).

### 5. Tests

- [ ] New behavior or bugfix must have a corresponding test in
  `lib/matplotlib/tests/test_<module>.py`.
- [ ] **Image-comparison tests** (`@image_comparison`) require updated baseline PNGs in
  `lib/matplotlib/tests/baseline_images/<test_module>/`. If baselines are not
  regenerated, the CI will fail. Verify the PR author addressed this.
- [ ] **Figure-equality tests** use `@check_figures_equal()` with `fig_test, fig_ref`
  parameters — ensure both figures render identically.
- [ ] Tests for deprecated-API warnings use
  `pytest.warns(mpl.MatplotlibDeprecationWarning)`.
- [ ] Test names must follow `test_<what_is_being_tested>` (enforced by the
  `name-tests-test` pre-commit hook).
- [ ] There must be no `print()` statements in tests or library code.

### 6. Style & Formatting (ruff-enforced)

- [ ] Line length ≤ 88 characters.
- [ ] Imports follow the scipy conventions (see `repo-conventions.md`).
- [ ] No f-strings in logging calls:
  ```python
  # WRONG
  _log.debug(f"Processing {fname}")
  # CORRECT
  _log.debug("Processing %s", fname)
  ```
- [ ] Module-level logger is `_log = logging.getLogger(__name__)`, placed right after
  imports.
- [ ] User-visible debug info goes to `_log.info` / `_log.debug`, **not** `print()`.
- [ ] User-facing warnings go to `_api.warn_external(message)`, not
  `warnings.warn(message)` directly.

### 7. Build System / New Files

- [ ] New Python modules or data files must be listed in the `meson.build` in the
  **corresponding directory** (not just the top-level `meson.build`).
- [ ] New C/C++ files must follow the `FOO_wrap.cpp` / `FOO_wrapper.cpp` naming
  convention for Python/C interface code.
- [ ] Vendored code in `extern/` should stay close to upstream; style fixes to vendored
  code are explicitly discouraged.

### 8. Type Hints

- [ ] New or changed public API must have updated type hints.
- [ ] Type hints live in `lib/matplotlib/<module>.pyi` stub files (not inline),
  **except** `pyplot.py` which uses inline annotations.
- [ ] Run `tox -e stubtest` to validate.
- [ ] `@_api.rename_parameter` / `@_api.make_keyword_only` deprecation decorators
  report the *new* signature at runtime → update the `.pyi` on introduction.
- [ ] `@_api.delete_parameter` → add a default hint `param: type = ...` in the `.pyi`.
- [ ] **pyplot.py inline annotations must match stub files.** When `pyplot.py` adds or
  changes a method that mirrors an `Axes` or `Figure` method (e.g., `bivar_colorbar`,
  `imshow`), verify that the inline type annotations in `pyplot.py` are consistent with
  the corresponding `.pyi` stub (`figure.pyi`, `axes/_axes.pyi`). Mismatches will fail
  mypy CI and signal that one of the two was not updated.

### 9. PR Template Compliance

The PR must satisfy the checklist in `.github/PULL_REQUEST_TEMPLATE.md`:
- [ ] "closes #XXXX" or "fixes #XXXX" in the PR body.
- [ ] **AI Disclosure section** filled in (the template explicitly asks for this under
  the repo's generative-AI policy).
- [ ] PR targets the `main` branch (not a maintenance branch).
- [ ] Milestone is set: new features → next `v3.N.0`; bugfixes → next `v3.N.M`;
  docs-only → `v3.N-doc`.

### 10. Colormap / Style Changes

Adding or changing colormaps, color sequences, or styles has a very high bar:
- Visual changes to existing ones are always API breaks.
- New additions need: novelty evidence, colorblind-accessibility evaluation, open
  (BSD-compatible) license, and evidence of wide use.

---

## Common Mistake Patterns

See [common-issues.md](common-issues.md) for a growing list of issues identified
during past reviews.

Beyond that, watch for:

1. **Forgetting the `.pyi` stub update** when changing a public function signature —
   mypy CI will catch it, but it's worth flagging proactively.
2. **Accessing `rcParams` via `from matplotlib import rcParams`** — modules imported
   early (before rcParams is constructed) will get a stale reference.
3. **Using `warnings.warn` directly** instead of `_api.warn_external` or
   `_api.warn_deprecated` — the stacklevel logic for pointing to user code is
   non-trivial and already handled by `_api`.
4. **Missing `meson.build` entry** for a new `.py` file — the file won't be installed.
5. **Baseline images not regenerated** after visual changes — image-comparison CI fails.
6. **New rcParam added in only 1 of 3 required locations** — `rcsetup.py`,
   `matplotlibrc`, and `typing.py` must all be updated.
7. **API change undocumented** — missing entry in `doc/api/next_api_changes/` or
   `doc/release/next_whats_new/`.
8. **Print statements** used instead of `_log.debug(...)`.
9. **kwargs popped** from `**kwargs` instead of declared as keyword-only parameters.
10. **Colormap/style changes presented as non-breaking** when any visual change is
    technically an API break in matplotlib.

---

## Submitting the Review to GitHub

> **Both PR #31218 and PR #31214 failed because the review was written to a local
> `review.json` file but was NEVER posted to GitHub. This step is mandatory.**

After completing all checklist items and writing the review content:

1. **Post the review using `mcp__github__create_pull_request_review`** with:
   - `owner`: `matplotlib`
   - `repo`: `matplotlib`
   - `pull_number`: the PR number
   - `event`: `"COMMENT"` (or `"REQUEST_CHANGES"` if blockers are present)
   - `body`: the overall review summary
   - `comments`: array of inline comments, each with `path`, `line`, and `body`

2. **Verify the review was posted** by calling `mcp__github__get_pull_request_reviews`
   and confirming the response is non-empty.

3. Saving a local `review.json` is useful for your own record-keeping, but it does NOT
   substitute for posting to GitHub. The review is only complete when it appears on
   the PR page.

Example structure for inline comments:
```json
{
  "comments": [
    {
      "path": "lib/matplotlib/colorizer.py",
      "line": 42,
      "body": "The return type of `clip` changed from `bool` to `tuple[bool]` — this is a breaking API change requiring deprecation."
    }
  ]
}
```
