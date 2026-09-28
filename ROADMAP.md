# Roadmap

Status as of 0.2.0. Evidence for the ordering is in `survey/SURVEY.md`.

1. **Confirm the findings by running them.** *Kit ready, not yet run.*
   `confirm/confirm.py` runs 12 cases (every writer finding with its quiet
   twin, plus a dangling and an unnamed subject) with the released Bonsai
   packages on .NET 8 and compares what happens with what baghban said. It
   uses a small runner instead of `Bonsai.Player`, which only references
   `Bonsai.Core`. Next: run it on macOS and record the results here.
2. **Measure on real rigs.** *Done for errors.* 32 repositories, 453 entry
   workflows: no false alarms among 27 errors after the module conventions
   were added. Open: read the 57 `DISABLED_WRITER` warnings in full; add
   more rig repositories (the sample over-represents documentation);
   estimate recall by seeding known faults into real rigs and checking that
   baghban finds them.
3. **Follow includes into packages from other repositories.** *Next, and
   now the biggest gain:* 116 entry workflows have includes baghban cannot
   read, 151 into BonVision and 122 into AllenNeuralDynamics.Core alone.
   Embedded workflows live inside the package DLL, so the route is: read
   package versions from the environment's `.bonsai/Bonsai.config`, fetch
   the `.nupkg` from nuget.org into a cache (a zip), and read the embedded
   `.bonsai` resources out of the DLL's .NET manifest-resource table, in
   pure Python. The same-repository case already works.
4. **daftar adapter.** Move `manifest_fields` into a `daftar.adapters.bonsai`
   adapter that also records the parameter values a launcher passes with
   `--property`. The survey showed launchers set *nested* properties
   (iblrig sets `Stim.ReceptiveFieldMappingStim.FileNameRFMapStim`), so the
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
