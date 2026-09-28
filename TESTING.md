# Testing

```
pip install -e ".[dev]"
pytest -q
```

Expected: `113 passed`, in well under a second. No network, no .NET, no
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

## Not tested yet

Nothing here runs a workflow. `ROADMAP.md` describes confirming the writer
findings with `Bonsai.Player` on macOS.
