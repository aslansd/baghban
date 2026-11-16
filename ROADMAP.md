# Roadmap

Status as of 0.7.0. Evidence for the ordering is in `survey/SURVEY.md`.

1. **Confirm the findings by running them.** *Done on macOS.* Latest run
   (28 Oct 2026, baghban 0.6.0, Bonsai 2.9 packages, .NET 8, Intel Mac):
   17/17 cases confirmed. 0.7.0 before release (16 Nov 2026): 19/20. The
   NO corrected a wrong claim about disabled sources, and its replacement
   (`branch_off`) has not been run yet.
   Earlier runs: 8/12 (a kit flaw and a wrong claim
   about unnamed subjects, both fixed), then 13/13 on 4 Oct 2026. Open: run the same kit
   on Windows, where rigs actually run (file locking differs, which matters
   most for `DUPLICATE_OUTPUT`), and add a case whenever a finding is added
   or its message changes.
2. **Measure on real rigs.** *Done for errors, for `DISABLED_WRITER`, and
   for recall (0.7.0).* 32 repositories, 453 entry
   workflows: no false alarms among 27 errors after the module conventions
   were added. Reporting faults upstream also tests a second question: are
   findings faults *to their authors*? vestibular-vr's maintainers answered
   that their demo overwrites its file on purpose (#137). Hence 0.5.0:
   overwriting across runs is a warning, and findings can be marked as
   intended (`baghban.toml`).
   - **The 57 `DISABLED_WRITER` warnings, read in full:** all true. In 40
     the source is disabled too, so the branch is off: 36 are info since
     0.7.0.
   - **Recall**, by planting faults with a certain effect into real rigs
     (`survey/seed_faults.py`): 168 of 170 found with packages (156
     without). Both misses were reported "not checked": a renamed BonVision
     module and a CI build of Aeon.Acquisition that nuget.org lacks.

   Open:
   - run the survey with `--fetch` for 0.7.0 (expected 37 errors);
   - read the remaining warnings;
   - add more rig repositories (the sample over-represents documentation);
   - measure recall for loop faults, which needs the real runtime to say
     whether a loop repeats.
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
5. **Loops that run once.** *Done in 0.6.0.* `baghban.flow` follows
   elements through a workflow. A loop that is shown to receive at most one
   element per run, and that nothing re-subscribes, is judged as no loop.
   It uses only operators read in the Bonsai source; anything else keeps
   the loop a loop. iblrig's two "likely harmless" errors are now shown to
   be once per session, so 26 errors become 24. 124 of the survey's 849
   `SelectMany` loops are shown to run once per subscription; the
   `Repeat` after AIND's `RunTrial` rightly keeps that one a loop. The 2
   confirm cases passed (28 Oct 2026). Since 0.7.0 a writer before `Repeat`
   or `Retry` is treated as in a loop (none in the survey; 2 confirm cases,
   not run yet). Open: follow subjects (a loop fed by a `SubscribeSubject`
   is "not known" today), though no remaining survey error depends on it.
6. **`UNRECORDED_PARAMETER`**: an externalized property whose value is never
   written to any output, so the data does not say what settings produced it.
   *Re-planned (0.7.0).* Whether a value is recorded is mostly not in the
   XML: launchers save their settings elsewhere (iblrig and AIND write them
   to JSON), and `baghban.provenance` now records every top-level value for
   daftar (item 4). A check on the XML alone would fire on nearly all of the
   survey's 156 top-level externalized properties. Kept only in a narrow
   form: a parameter that no launcher sets and no provenance records, which
   needs the launcher's code, not the workflow.
7. **Rate-dependent checks**, only where rates are stated in the XML (a
   `Timer` period, a configured frame rate): `Zip` over streams with
   different rates queues without bound; `CombineLatest` feeding a writer
   duplicates rows. Where rates are unknown, report not checked.
   *Measured (0.7.0), and merged into item 8.* Of the survey's 2,463 `Zip`
   nodes, none joins timers with different stated periods: rates come from
   devices, not from the XML. So the static check would find nothing. Rates
   are in the data a session writes, which is what item 8 reads. The 6
   `CombineLatest` nodes feeding a writer (all in iblrig's Gabor `SaveData`)
   are to be read before deciding whether duplicated rows there are a
   fault: #137 showed that a behaviour baghban can see is not always a
   mistake.
8. **A session-timing companion** (working name *nabz*, pulse): read the
   timestamps a session actually wrote and report dropped frames, jitter and
   clock drift; the empirical counterpart of the static checks. This now
   includes item 7's question, answered from measured rates: does a `Zip`
   pair streams whose rates differ, so that its queue grows during the
   session?
