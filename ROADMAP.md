# Roadmap

In order.

1. **Confirm the writer findings by running them.** `Bonsai.Player` is a
   `net8.0` dotnet tool, so it runs on macOS. Build it from the Bonsai
   repository, copy `Bonsai.System` next to it, and run each firing fixture
   of `SILENT_OVERWRITE`, `FAILS_ON_REPEAT` and `DUPLICATE_OUTPUT` twice,
   checking the files on disk: the overwrite must actually happen, the second
   trial must actually raise. This turns "grounded in the source" into
   "observed". (Note: the Player does not change the working directory to
   the workflow's folder as the editor does, so run it from that folder.)
2. **Measure on real rigs.** Run `baghban check` over rig workflows labs
   publish on GitHub and count findings by kind, then read every error by
   hand: how many are real faults, how many false alarms. This decides
   whether the findings are useful, and it is the evidence for a post on the
   Bonsai discussions board.
3. **Follow includes into installed packages.** Resolve
   `Path="Package:Module.bonsai"` from a Bonsai environment's `Packages`
   folder (`.bonsai/Packages/<Name>.<Version>/`), so shared modules are
   checked too instead of being reported as not checked.
4. **daftar adapter.** Move `manifest_fields` into a `daftar.adapters.bonsai`
   adapter that also records the parameter values a launcher passed with
   `--property`, which the XML alone does not show.
5. **`UNRECORDED_PARAMETER`**: an externalized property whose value is never
   written to any output, so the data does not say what settings produced it.
6. **Rate-dependent checks**, only where rates are stated in the XML (a
   `Timer` period, a configured frame rate): `Zip` over streams with
   different rates queues without bound; `CombineLatest` feeding a writer
   duplicates rows. Where rates are unknown, report not checked.
7. **A session-timing companion** (working name *nabz*, pulse): read the
   timestamps a session actually wrote and report dropped frames, jitter and
   clock drift; the empirical counterpart of the static checks.
