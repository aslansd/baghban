# Changelog

## Unreleased (documentation only)

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
