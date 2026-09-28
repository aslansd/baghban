# Changelog

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
