# Changelog

## 0.5.0 (unreleased)

Intent. The vestibular-vr maintainers explained that their `GNGTemplate.bonsai`
overwrites `responses.csv` on every run on purpose: it is a demo, and one
rewritten file is what they want while testing
([neurogears/vestibular-vr#137](https://github.com/neurogears/vestibular-vr/issues/137)).
baghban was right about the behaviour and wrong to call it an error.

- **`SILENT_OVERWRITE` across runs is now a warning, not an error.** The
  writer is not in a loop and has `Overwrite=True`, `Suffix=None`.
  `Overwrite=True` is a setting someone has to switch on (the default is
  `False`), so it often means intent. The message says so ("Fine for a demo
  or scratch output; not for session data"), and `check` exits 0 for it
  unless `--strict`.
- **Overwriting inside a per-element loop stays an error.** In a
  `SelectMany`, `CreateObservable` or `WindowWorkflow`, all but the last
  element are lost within one session. With an externalized file name it
  stays info, as before.
- **Findings can be marked as intended:**
  - `baghban check --ignore CODE[:PATTERN]`, repeatable;
  - a `baghban.toml` (`ignore = [...]`, `[per-file-ignores]`), or a
    `[tool.baghban]` table in `pyproject.toml`, found above the workflow and
    not past the repository's root; `--no-config` skips it;
  - in Python, `check(doc, ignore=[...])`, with `read_config`, `find_config`,
    `parse_ignore`, `IgnoreRule` and `ConfigError` in the API.
  
  Marked findings move to `Report.ignored`: they are listed in the summary
  and in `--json` (with `ignored_by`), and are not counted. An unknown code
  is an error, so a typo cannot silently disable a rule. `render` honours
  the same rules. Reading the file uses `tomllib` (Python 3.11 and later),
  or `tomli` on 3.10; `--ignore` works everywhere.
- **Survey:** `GNGTemplate.bonsai` moves from "true fault" to "true, by
  design". Real-fault findings go from 5 to 4 (3 distinct problems) in the
  hand-read run, and from 6 to 5 with packages. Re-run without packages:
  27 errors become 26, and the 3 `SILENT_OVERWRITE` errors become 2 errors
  (iblrig, inside a `SelectMany`) and 1 warning. Nothing else changed.
- The README's sample `check` output is regenerated from the real output (its
  `SILENT_OVERWRITE` wording had drifted). TESTING said an externalized file
  name makes `SILENT_OVERWRITE` a warning; it has been info since 0.2.1.
- 250 tests (Python 3.11 and 3.13).

## 0.4.1 (2026-10-12)

A fix found by the first run of `confirm/confirm_properties.py` on real
Bonsai (12 Oct 2026, macOS: 9/10 confirmed).

- **Two externalized properties with one name in one workflow.** 0.4.0 said
  a `--property` value goes to the first of them. In fact Bonsai.exe builds
  the workflow before assigning any value, and the build refuses a repeated
  name ("A workflow property with the name 'Out' already exists.",
  `RegisterPropertyName`, the same since at least 2.6.2). Such a workflow
  never runs, launcher or not.
  - `set_properties` now reports the name as `duplicate` and changes
    nothing; `provenance` lists it under `bonsai.problems`.
  - **New finding `DUPLICATE_PROPERTY`** (error): two enabled externalized
    properties with the same name (DisplayName, or else Name) in one
    workflow. The same name in different groups is fine (each group is its
    own workflow), as are disabled ones. None of the 572 survey workflows
    has one, so the survey's numbers are unchanged.
- `confirm/confirm_properties.py`: the case now predicts the refusal
  (`two_properties_same_name`), plus a quiet twin, `same_name_in_two_groups`
  (11 cases). `confirm/confirm.py` gains `duplicate_property` and
  `same_property_in_two_groups` (15 cases).
- Re-run on real Bonsai with 0.4.1 (12 Oct 2026, macOS): `confirm.py`
  15/15, `confirm_properties.py` 11/11, `confirm_packages.py` 8/8. The
  survey with `--fetch` gives the same errors and warnings as 0.3.0's real
  run, with one false `UNUSED_SUBJECT` and one "not checked" note fewer
  (the include fix in 0.4.0).
- 231 tests.

## 0.4.0 (2026-10-12)

Roadmap item 4, baghban's side: what daftar's Bonsai adapter needs. The
adapter itself lives in daftar (`daftar.adapters.bonsai`,
`pip install "daftar[bonsai]"`). daftar depends on baghban, not the other
way round.

- **`baghban.provenance(workflow, properties, command_line=..., cwd=...)`**:
  the stable entry point for provenance tools. Flat string fields, with a
  layout version (`bonsai.provenance = "1"`), the baghban version, the
  `Bonsai.config` package versions came from (`bonsai.environment`), each
  launcher value (`bonsai.property.<name>`), top-level parameters with those
  values applied, includes, packages, output paths (`bonsai.output.<n>`) and
  any values Bonsai would refuse (`bonsai.problems`). The fingerprint is of
  the file as saved, and a `Document` passed in is not changed.
  `bonsai.workflow` is now an absolute path.
- **`manifest_fields(doc)`** is kept as an alias of `provenance(doc)`, and so
  gains the new fields.
- **`baghban.parse_command_line(args)`**: Bonsai.exe's arguments read as its
  `CommandLineParser` reads them: `--property:N=V`, `--property N=V`, `-p:N=V`,
  `-p N=V`, the other commands and their short aliases, and the errors
  Bonsai.exe stops on.
- **`baghban.set_properties(doc, values, strict=False)`**: launcher values
  applied as Bonsai's `SetWorkflowProperty` applies them. A dotted name walks
  through uniquely named, enabled nested workflows (groups, SelectMany, ...),
  but not into an include by name. The last part is an externalized
  property, and the first one with that name wins (wrong: see 0.4.1). The
  value reaches every node it maps to, through groups and into includes.
  Each name gets an `Assignment` (`ok`, `unknown`, `ambiguous`, `invalid`, with a note and
  the saved value). `strict` raises `PropertyAssignmentError` before
  changing anything.
- **`baghban.outputs(doc)`**: every enabled file writer with its effective
  path, `Suffix`, location, whether a launcher or includer set it, and
  whether the path is assigned from data at run time.
- **Fix: include values now reach groups inside the included file.** A value
  on an IncludeWorkflow element (`<FrameSubject>Frame</FrameSubject>`) set
  only nodes the included file's mapping fed directly, not nodes inside a
  group it fed. In the survey this removed one false `UNUSED_SUBJECT` (AIND
  `test_saturation_visualizer.bonsai`) and one "not checked" note. Errors
  and warnings are unchanged.
- `parameters` reports the value of a property mapped onto a group or an
  include, which lives inside it (it was empty).
- CLI: `-p/--property NAME=VALUE` on `check`, `show`, `render`, `params`
  and `provenance` (and on `fingerprint --fields`). New `baghban provenance`
  command; `fingerprint --fields` is the same.
- Removed the `provenance = ["daftar"]` extra.
- `confirm/confirm_properties.py`: 10 cases checking launcher values on the
  real runtime. The runner now takes `NAME=VALUE` arguments and applies them
  as Bonsai.exe does.
- Checked on the survey: provenance built for all 572 workflows, and 1,114
  dotted names made from the workflows' own properties all resolve. 228
  tests.

## 0.3.0 (2026-10-11)

Roadmap item 3: includes into packages from other repositories are read.

- **Packages.** `Path="BonVision:Primitives.DrawQuad.bonsai"` is read out of
  the package DLL and checked like any other include. New modules
  `baghban.dotnet` (a pure-Python ECMA-335 reader of .NET manifest
  resources, no dependencies) and `baghban.packages` (versions, sources,
  cache).
- **Versions** come from the workflow's environment: the nearest
  `.bonsai/Bonsai.config` above it, as Bonsai searches, or a portable install
  committed next to the workflows (`Bonsai/`, `bonsai/`), which the survey
  found in iblrig and vestibular-vr. `--package ID=VERSION` overrides. An
  unpinned package is read at the newest version found, and reports say so.
- **Sources**, without network access: the installed environment
  (`.bonsai/Packages`), `~/.nuget/packages` (`$NUGET_PACKAGES`), baghban's
  cache (`~/.cache/baghban`, `$BAGHBAN_CACHE`). With `--fetch`, missing
  packages are downloaded from nuget.org (`$BAGHBAN_NUGET_SOURCE` for another
  feed). Nothing touches the network otherwise.
- A finding inside a package names it (`in BonVision 0.12.0: ...`); a module
  missing from a pinned package is `MISSING_INCLUDE`, from a guessed version
  "not checked". Subjects declared by another assembly's module (read from a
  DLL or from source) are never `UNUSED_SUBJECT`.
- `check` reports the packages read (`Report.packages`); `deps` lists them;
  `fingerprint --fields` adds `bonsai.package.<id>`.
- CLI: `--fetch`, `--package`, `--cache` on every command.
- On case-insensitive file systems (macOS, Windows), a portable environment
  folder is reported by its name on disk (`bonsai/`, not `Bonsai/`); found
  by the first test run on a Mac.
- `confirm/confirm_packages.py` and `confirm/resources/`: compare the reader
  with Microsoft's System.Reflection.Metadata on real Bonsai packages.
- `survey/run_survey.py --fetch` and `--package-sources`; SURVEY.md: a
  preview with packages read from source, every new error read by hand
  (one new real fault, four false alarms from reading the wrong version).
- Reader checked against dnfile on 168 real assemblies (identical), and
  against Microsoft's System.Reflection.Metadata on 8 real Bonsai packages
  (identical, `confirm/README.md`); dnfile added to the `dev` extra.
- Survey with `--fetch` at the pinned versions: 13 new errors (one new real
  fault, 10 documentation snippets and templates), no false alarms among 40. 196 tests.

## 0.2.2 (2026-10-05)

- SURVEY.md, README: before reporting the survey's faults upstream, each was
  checked against its repository's history. The 8 BonVision findings in
  bonsai-rx/docs are reclassified from "true fault" to "true, by design":
  the tutorial has readers create the missing extension. The Allen module
  was deleted (2026-01-29), not renamed. Now 5 real-fault findings (4
  problems), 22 by design, 2 likely harmless; still no false alarms. Links
  to every affected file at the surveyed commit.

- `confirm/README.md`: second run on real Bonsai recorded: 13/13 cases
  confirmed (4 Oct 2026, macOS, Bonsai.Core/System 2.9.1, .NET 8.0.425),
  with every case's outcome and Bonsai's messages, the exact package
  versions of both runs, and what the result does and does not establish.
- README, ROADMAP, TESTING: roadmap item 1 marked done on macOS; Windows run
  added as the open part.
- `survey/survey-results.json` regenerated with baghban 0.2.1 (it was the
  0.2.0 output, while SURVEY.md already quoted 0.2.1 numbers); same 32
  repository commits, same counts as SURVEY.md.

## 0.2.1 (2026-09-29)

Fixes from the first `confirm/` run on real Bonsai (macOS, Intel, .NET 8.0.425,
Bonsai 2.9 packages), which confirmed 8 of 12 cases.

- **Fixed a wrong claim:** an unnamed `SubscribeSubject` with nodes after it
  makes Bonsai refuse to build those nodes (it builds to an empty expression,
  which Bonsai does not pass on). `UNNAMED_SUBJECT` is now an error in that
  case and info otherwise; the survey gains one true fault (a Berkeley rig
  workflow that cannot build).
- **Fixed the kit:** the runner exited before Bonsai's background file
  writers flushed, leaving empty files; it now waits two seconds. The
  overwrite judgement requires real rows in both runs. New case
  `unnamed_subscribe_alone`; 13 cases.
- Runner runs on newer .NET too (`RollForward=Major`).
- `render` writes the HTML next to the workflow by default and prints the
  full path (two rigs' `foraging.bonsai` no longer overwrite each other's page).
- `confirm/README.md`: installing .NET on a Mac (and why not Homebrew on
  Intel), the virtual-environment PATH pitfall, running and reading the kit,
  results of every run, troubleshooting.
- 134 tests.

## 0.2.0 (2026-09-28)

From running baghban over 32 published repositories (`survey/`) and reading
every error by hand.

- **Modules.** Files under an `Extensions` folder and files embedded in a
  package project are loaded as modules (`Document.kind`). Their undeclared
  subjects are reported as their interface (`Report.interface`), not as
  `DANGLING_SUBJECT`; a subject whose name is externalized is taken to be
  set by the includer. Extensions modules resolve includes from the project
  folder. Test projects are excluded: their embedded workflows are fixtures
  that run top-level. 202 dangling-subject errors on the survey became 13,
  all in documentation snippets.
- **Embedded includes into package projects of the same repository** are
  followed automatically. The repository root is the nearest `.git`, else
  the highest folder with a `.sln`.
- **Fixed:** an unnamed `SubscribeSubject` was reported as a build error; Bonsai
  builds it as an empty sequence (and an unnamed `MulticastSubject` as a
  pass-through). New finding `UNNAMED_SUBJECT` (corrected again in 0.2.1,
  after running it on real Bonsai).
- **Fixed:** `.bonsai` environment *folders* were collected as workflow files.
- **Fixed:** workflows that include each other were all skipped in folder mode.
- `SILENT_OVERWRITE` with an externalized file name is now info (launchers
  set these per session); the in-loop message no longer assumes the loop
  receives more than one element.
- `check --exclude GLOB`.
- `confirm/`: harness that runs the findings' cases with the real Bonsai
  runtime on .NET 8 (roadmap item 1). Not yet run on real Bonsai.
- `survey/`: reproducible survey script, repository list and write-up.

## 0.1.0 (2026-09-28)

First version.

- Reader for `.bonsai` files: types resolved through xmlns, `Combinator`,
  `Source` and `Disable` unwrapped, nested workflows, Bonsai's scoping rules
  (groups and includes transparent, other nested workflows real scopes),
  includes resolved from the top-level folder or, with `--resource-root`,
  from embedded resources; include property overrides applied, through
  nested includes too.
- Findings: `SILENT_OVERWRITE`, `FAILS_ON_REPEAT`, `DUPLICATE_OUTPUT`,
  `DANGLING_SUBJECT`, `DUPLICATE_SUBJECT`, `MISSING_INCLUDE`,
  `RECURSIVE_INCLUDE`, `INVALID_INCLUDE`, `DISABLED_WRITER`,
  `APPENDS_ACROSS_RUNS`, `UNUSED_SUBJECT`; what could not be checked is
  reported, not guessed.
- Commands: `check`, `show`, `render` (HTML, Mermaid, DOT), `diff`, `deps`,
  `params`, `fingerprint` (with `--fields` for daftar).
- Tests: 113, including agreement with Bonsai's own test workflows.
