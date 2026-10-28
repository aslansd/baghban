# Roadmap

Status as of 0.5.0. Evidence for the ordering is in `survey/SURVEY.md`.

1. **Confirm the findings by running them.** *Done on macOS.* Latest run
   (12 Oct 2026, baghban 0.4.1, Bonsai 2.9 packages, .NET 8, Intel Mac):
   15/15 cases confirmed. Earlier runs: 8/12 (a kit flaw and a wrong claim
   about unnamed subjects, both fixed), then 13/13 on 4 Oct 2026. Open: run the same kit
   on Windows, where rigs actually run (file locking differs, which matters
   most for `DUPLICATE_OUTPUT`), and add a case whenever a finding is added
   or its message changes.
2. **Measure on real rigs.** *Done for errors.* 32 repositories, 453 entry
   workflows: no false alarms among 27 errors after the module conventions
   were added. Reporting faults upstream also tests a second question: are
   findings faults *to their authors*? vestibular-vr's maintainers answered
   that their demo overwrites its file on purpose (#137). Hence 0.5.0:
   overwriting across runs is a warning, and findings can be marked as
   intended (`baghban.toml`). Open: re-run the survey with `--fetch` for
   0.5.0 (expected 40 → 39 errors); read the 57 `DISABLED_WRITER` warnings in full; add
   more rig repositories (the sample over-represents documentation);
   estimate recall by seeding known faults into real rigs and checking that
   baghban finds them.
3. **Follow includes into packages from other repositories.** *Done in
   0.3.0.* Embedded workflows are read out of package DLLs by a pure-Python
   ECMA-335 reader, at the version the environment pins. Confirmed against
   Microsoft's reader on 8 real packages (10 DLLs, 165 resources, 129
   workflows): identical (`confirm/README.md`). The survey with `--fetch` at
   the pinned versions (12 Oct 2026): 13 new errors, one new real fault, no
   false alarms among 40 (`survey/SURVEY.md`). Open: versions nuget.org does
   not have (CI builds on private feeds) stay unchecked unless
   `BAGHBAN_NUGET_SOURCE` points at that feed.
4. **daftar adapter.** *baghban's side done in 0.4.0; the adapter itself is
   built in daftar.* The dependency runs one way: `daftar.adapters.bonsai`
   (installed with `daftar[bonsai]`) imports baghban, and baghban does not
   depend on daftar (the `provenance` extra is gone). baghban provides what
   the adapter calls:
   - `baghban.provenance(workflow, properties, command_line=...)`: flat
     string fields, with a layout version (`bonsai.provenance`) the adapter
     can rely on; `manifest_fields` stays as an alias.
   - `parse_command_line`: a launcher's Bonsai.exe arguments, read as
     Bonsai's `CommandLineParser` reads them (`--property:N=V`, `-p N=V`, ...).
   - `set_properties`: the `--property` values applied as Bonsai's
     `SetWorkflowProperty` applies them. A dotted name walks through named
     groups and other nested workflows, but not into an include by name (an
     include is reached through an ExternalizedMapping wired into it). Names
     Bonsai would refuse are reported, not guessed.
   - `outputs`: the files a session writes, so the adapter can hash them
     afterwards. A `Suffix` (timestamp, count) is added at run time, so the
     adapter matches on the name's stem.

   Checked on iblrig's `Stim.ReceptiveFieldMappingStim.FileNameRFMapStim`,
   which reaches a MatrixWriter through two groups, an include and a group
   inside it, and on the survey: 1,114 dotted names built from the 572
   workflows' own properties all resolve. Building it fixed include values
   not reaching groups inside the included file. In the survey this removed
   one false `UNUSED_SUBJECT` and one "not checked" note; errors and
   warnings are unchanged. `confirm/confirm_properties.py` checks this on
   the real runtime. Its first run (12 Oct 2026, macOS) confirmed 9 of 10
   cases. The tenth was a wrong claim: baghban said that of two properties
   with one name the first wins, but Bonsai refuses to build such a
   workflow. Since 0.4.1, `set_properties` refuses the name and `check` reports
   `DUPLICATE_PROPERTY`. None of the 572 survey workflows has such a pair.
   Re-run with 0.4.1 (12 Oct 2026, macOS): `confirm_properties.py` 11/11
   and `confirm.py` 15/15. Open: values that need type conversion are not
   checked (they stay strings); the adapter, in daftar.
5. **Loops that run once.** iblrig's two remaining `SILENT_OVERWRITE`
   errors sit in a `SelectMany` that most likely receives one element per
   session, so they are likely harmless. baghban cannot know how many
   elements a loop receives. Where the XML shows it (a `Take(1)` before the
   loop, or a source that emits once), the in-loop error could become the
   across-run warning.
6. **`UNRECORDED_PARAMETER`**: an externalized property whose value is never
   written to any output, so the data does not say what settings produced it.
7. **Rate-dependent checks**, only where rates are stated in the XML (a
   `Timer` period, a configured frame rate): `Zip` over streams with
   different rates queues without bound; `CombineLatest` feeding a writer
   duplicates rows. Where rates are unknown, report not checked.
8. **A session-timing companion** (working name *nabz*, pulse): read the
   timestamps a session actually wrote and report dropped frames, jitter and
   clock drift; the empirical counterpart of the static checks.
