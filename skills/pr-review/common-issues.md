# Common Issues

This file grows over time as the grader identifies patterns the reviewer misses.

---

## Issue 1: Review not posted to GitHub (Critical — failed in PR #31218 and PR #31214)

**What happened:** The reviewer produced a correct `review.json` locally but never
called `mcp__github__create_pull_request_review`. Both PRs showed empty review lists
when graded (`mcp__github__get_pull_request_reviews` returned `[]`).

**Rule:** Writing `review.json` is NOT sufficient. You must post the review to GitHub
using `mcp__github__create_pull_request_review` with inline comments. Verify success by
calling `mcp__github__get_pull_request_reviews` afterward.

---

## Issue 2: Not all changed files examined (Critical — failed in PR #31214)

**What happened:** PR #31214 changed 30 files. The reviewer examined 5 of them
(colorbar.py, colorizer.py, colorizer.pyi, figure.py, test_colorbar.py) and missed:
- `lib/matplotlib/axes/_axes.py` (48 additions, 19 deletions)
- `lib/matplotlib/axes/_axes.pyi`
- `lib/matplotlib/pyplot.py` (37 additions, 15 deletions)
- `lib/matplotlib/tests/test_axes.py` (245 additions)
- `lib/matplotlib/image.py`
- `lib/matplotlib/collections.py` and `collections.pyi`
- `lib/matplotlib/backend_bases.py`

**Rule:** Before writing the review, retrieve the full file list and explicitly confirm
which files were examined. Large test files and pyplot.py are not optional.

---

## Issue 3: Return-type changes not flagged as breaking API (PR #31214)

**What happened:** The reviewer caught that `get_clim()` had a breaking API change
(return type changed) but missed that `Colorizer.clip`, `Colorizer.vmin`, and
`Colorizer.vmax` followed the identical pattern:
- `clip`: `bool` → `tuple[bool]`
- `vmin`: `float | None` → `tuple[float | None, ...]`
- `vmax`: `float | None` → `tuple[float | None, ...]`

The skill only mentioned "function signature changing" in the deprecation trigger list,
not return-type changes.

**Rule:** Any change to the return type of a public property or method is a breaking API
change requiring deprecation. Scan every modified `@property` and every public method
for return-type differences — don't stop after finding one instance.

---

## Issue 4: Missing what's-new RST for new public classes/functions (PR #31214)

**What happened:** The PR introduced `BivarColorbar` (a new public class),
`Figure.bivar_colorbar()`, and `pyplot.bivar_colorbar()`. The reviewer flagged the
missing deprecation RST for `get_clim()` but never checked whether
`doc/release/next_whats_new/` had a corresponding entry for these new public APIs.
No entry existed, and the reviewer did not flag it.

**Rule:** For every new public class or function identified during review, immediately
verify that a `.rst` file exists in `doc/release/next_whats_new/` AND that the docstring
contains `.. versionadded:: 3.N`. Flag the absence as a blocker.

---

## Issue 5: Deprecation RST missing even when deprecation code is present (PR #31214)

**What happened:** The reviewer correctly identified that `get_clim()` needed
`_api.warn_deprecated(...)` in the code, but did not also flag the absence of a
corresponding `.rst` file in `doc/api/next_api_changes/deprecations/`. A deprecation
without an RST is incomplete.

**Rule:** Every deprecation requires BOTH:
1. `_api.warn_deprecated(...)` or `@_api.deprecated(...)` in code.
2. A `.rst` file in `doc/api/next_api_changes/deprecations/`.

Always check for the RST even when the code is correct.

---

## Issue 6: pyplot.py type annotations not checked against stub files (PR #31214)

**What happened:** `pyplot.py` was not examined, so the inline type annotations for
`bivar_colorbar()` and `imshow()` were never verified against `figure.pyi` and
`axes/_axes.pyi`. Mismatches between pyplot.py inline annotations and the corresponding
`.pyi` stubs cause mypy CI failures.

**Rule:** When `pyplot.py` mirrors an Axes or Figure method, verify that the inline
annotations in `pyplot.py` match the corresponding `.pyi` stub. Read both files side
by side for changed methods.

---

## Issue 7: False positive — typing.py flagged for extended validators (PR #31218)

**What happened:** The skill said "New rcParam? Update typing.py with a new RcKeyType
Literal entry." A reviewer flagged `typing.py` as missing when the PR only extended an
existing validator (added new accepted values to a `validate_*` function) without adding
a new key to `_validators`. This is a false positive.

**Rule:** `typing.py` only needs updating when a **new key** is added to `_validators`
in `rcsetup.py`. If the PR only changes the validator function for an existing key, no
`RcKeyType` Literal update is needed. Before flagging `typing.py`, confirm that a new
key name was actually added to `_validators`.

---

## Issue 8: Wrong directory name cited for API-change RST (PR #31218)

**What happened:** The skill's architecture tree listed `behavior_changes/` and
`development_changes/` as subdirectory names under `doc/api/next_api_changes/`. The
actual directory names in the repository are `behavior/` and `development/` (without
the `_changes` suffix). Citing the wrong path in a review comment is misleading.

**Rule:** Always use `behavior/` and `development/` (not `behavior_changes/` or
`development_changes/`) when referring to subdirectories of `doc/api/next_api_changes/`.

---

## Issue 9: rc_context not checked for rcParams mutation in tests (PR #31218)

**What happened:** Tests that mutate `mpl.rcParams[...]` directly (without wrapping in
`mpl.rc_context(...)`) pollute the global state for subsequent tests. The skill mentioned
`pytest.warns` for deprecation tests but gave no guidance on rcParam mutation.

**Rule:** Any test that sets `mpl.rcParams[key] = value` directly must use
`mpl.rc_context({'key': value})` as a context manager or `@mpl.rc_context` decorator
instead. Flag bare `mpl.rcParams[...] = ...` mutations in test files.

---

## Issue 10: PostScript `newpath` requirement not checked (PR #31218)

**What happened:** New rendering methods added to `backend_ps.py` did not call
`newpath` before accumulating path segments. Unlike PDF/SVG backends, `gsave` in
PostScript does not clear the current path, so failing to call `newpath` first leads to
path contamination from prior drawing operations.

**Rule:** When reviewing changes to `lib/matplotlib/backends/backend_ps.py`:
1. Verify that any new path-rendering method calls `newpath` before `moveto`/`lineto`.
2. Verify that glyphs are filled individually (one `fill` per glyph), not accumulated
   into a single path, matching the PDF/SVG backend behavior.
