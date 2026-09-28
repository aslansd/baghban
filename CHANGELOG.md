# Changelog

## 0.2.0 (unreleased)

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
  pass-through). New finding `UNNAMED_SUBJECT`: warning, or info for multicast.
- **Fixed:** `.bonsai` environment *folders* were collected as workflow files.
- **Fixed:** workflows that include each other were all skipped in folder mode.
- `SILENT_OVERWRITE` with an externalized file name is now info (launchers
  set these per session); the in-loop message no longer assumes the loop
  receives more than one element.
- `check --exclude GLOB`.
- `confirm/`: harness that runs the findings' cases with the real Bonsai
  runtime on .NET 8 (roadmap item 1). Not yet run on real Bonsai.
- `survey/`: reproducible survey script, repository list and write-up.
- 132 tests.

## 0.1.0 (unreleased)

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
