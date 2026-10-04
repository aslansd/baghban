# Testing

```
pip install -e ".[dev]"
pytest -q
```

Expected: `134 passed`, in well under a second. No network, no .NET, no
Bonsai installation.

## What the suite checks

**`test_ground_truth.py`: agreement with Bonsai itself.** The 30 workflows in
`tests/data/bonsai_upstream` come unchanged from Bonsai's repository. Bonsai's
own tests assert which of them fail to build and which build; baghban must
report a build-breaking finding on exactly the first group, and nothing on
workflows that build and fail only at run time (division by zero), or that
reference a type that does not exist (baghban has no type catalogue and must
not guess). It must also compute the nested include property value that
`Build_NestedIncludeWorkflows_EnsureInnerPropertyIsAssigned` asserts. This is
the part of the suite that does not depend on baghban's own reading of
Bonsai's behaviour.

**`test_checks.py`: every finding in both directions.** Each finding has a
workflow on which it must fire and a nearly identical one on which it must
stay quiet. The quiet cases are the ones that matter for trust:

| Finding | Must stay quiet when |
| --- | --- |
| `SILENT_OVERWRITE` | `Suffix` is `Timestamp` or `FileCount`; `Overwrite=False` outside a loop; the file name comes from data (`PropertyMapping`); the path is a named pipe; the writer is inside a group, which is not a loop |
| `FAILS_ON_REPEAT` | the writer is in a `Defer` (subscribed once), or has a suffix |
| `DUPLICATE_OUTPUT` | the file names differ; one copy is disabled; an included module gets its own `FileName` per include |
| `DANGLING_SUBJECT` | the subject is declared in an enclosing scope, or inside a group (groups share their parent's scope); the subscriber is disabled; an unreadable include in scope might declare it |
| `DUPLICATE_SUBJECT` | the second declaration is inside a nested workflow (closest redefinition) |
| `MISSING_INCLUDE` | the file exists, including with backslashes, without the `.bonsai` extension, or as a nested include resolved from the top-level folder; the include is disabled |
| `DISABLED_WRITER` | the writer is enabled |

Severities and exit codes are pinned too: an externalized file name turns
`SILENT_OVERWRITE` into a warning, info findings never fail `check`, and
`--strict` fails on warnings.

**`test_project.py`: module conventions**, added after the survey: Extensions
and package modules report their undeclared subjects as their interface,
test projects stay top-level, embedded includes into same-repository packages
resolve without flags, `.bonsai` folders are ignored, and include cycles are
still checked.

**`test_confirm_harness.py`** tests `confirm/confirm.py` without .NET:
baghban's prediction for every case, and the harness's judgement of
simulated outcomes in both directions, so a "NO" on a real machine means
Bonsai disagreed rather than a harness bug.

**`test_model.py`** covers the reader: namespace and type resolution,
`Combinator`/`Source`/`Disable` unwrapping, flattened property keys, scopes,
include expansion and overrides, byte-order marks, and malformed files.

**`test_diff_render_cli.py`** covers the diff (reformatting is not a change,
inserting an unrelated node does not renumber, rewired edges are reported),
the fingerprint (stable across re-saves and `Version` stamps, sensitive to
included content), rendering, and every CLI command and exit code, on the
example rigs.

## Adding a finding

1. Find the behaviour in the Bonsai source and cite the file in the check's
   docstring.
2. Write the firing fixture and at least one quiet neighbour in
   `test_checks.py`, using the builders in `tests/xmlkit.py`, which emit XML
   in the shape Bonsai's serializer writes.
3. If Bonsai's own tests say something about the case, add it to
   `test_ground_truth.py`.

## Beyond the unit tests

- `python confirm/confirm.py` runs 13 cases with the real Bonsai runtime
  (needs .NET 8). Last run: 13/13 confirmed (4 Oct 2026, macOS, Bonsai 2.9.1
  packages). `confirm/README.md` explains installing .NET on a Mac, running
  the kit, reading its output, and records every run's results.
- `python survey/run_survey.py DIR` re-runs the survey of published
  repositories; `survey/SURVEY.md` records the last run and its hand review,
  and `survey/survey-results.json` holds that run's full output.
