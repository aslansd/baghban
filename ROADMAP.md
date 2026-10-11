# Roadmap

Status as of 0.3.0. Evidence for the ordering is in `survey/SURVEY.md`.

1. **Confirm the findings by running them.** *Done on macOS.* Second run
   (4 Oct 2026, baghban 0.2.1, Bonsai 2.9.1 packages, .NET 8, Intel Mac):
   13/13 cases confirmed, after the first run (8/12) exposed a kit flaw and
   a wrong claim about unnamed subjects, both fixed. Open: run the same kit
   on Windows, where rigs actually run (file locking differs, which matters
   most for `DUPLICATE_OUTPUT`), and add a case whenever a finding is added
   or its message changes.
2. **Measure on real rigs.** *Done for errors.* 32 repositories, 453 entry
   workflows: no false alarms among 27 errors after the module conventions
   were added. Open: read the 57 `DISABLED_WRITER` warnings in full; add
   more rig repositories (the sample over-represents documentation);
   estimate recall by seeding known faults into real rigs and checking that
   baghban finds them.
3. **Follow includes into packages from other repositories.** *Done in
   0.3.0.* Embedded workflows are read out of package DLLs by a pure-Python
   ECMA-335 reader, at the version the environment pins. Open: run
   `confirm/confirm_packages.py` (the reader against Microsoft's, on real
   packages) and the survey with `--fetch` at the pinned versions; both need
   nuget.org, which the machine 0.3.0 was built on could not reach.
4. **daftar adapter.** *Next.* Move `manifest_fields` into a
   `daftar.adapters.bonsai` adapter that also records the parameter values a
   launcher passes with `--property`. 0.3.0 already records each package's
   version (`bonsai.package.<id>`). The survey showed launchers set *nested*
   properties (iblrig sets `Stim.ReceptiveFieldMappingStim.FileNameRFMapStim`), so the
   adapter needs to resolve dotted paths through groups and includes.
5. **`UNRECORDED_PARAMETER`**: an externalized property whose value is never
   written to any output, so the data does not say what settings produced it.
6. **Rate-dependent checks**, only where rates are stated in the XML (a
   `Timer` period, a configured frame rate): `Zip` over streams with
   different rates queues without bound; `CombineLatest` feeding a writer
   duplicates rows. Where rates are unknown, report not checked.
7. **A session-timing companion** (working name *nabz*, pulse): read the
   timestamps a session actually wrote and report dropped frames, jitter and
   clock drift; the empirical counterpart of the static checks.
