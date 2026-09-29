# Survey: baghban on published Bonsai workflows

Roadmap item 2. The question: on workflows people actually publish, how often
do the findings fire, and how often are they right?

**Run:** September 2026, baghban 0.2.0; numbers updated with 0.2.1, after
the first `confirm/` run corrected `UNNAMED_SUBJECT`. `python survey/run_survey.py WORKDIR`.
32 repositories listed in `repos.txt`; 17 contain workflows. 630 `.bonsai`
files; 453 entry workflows checked (the rest through the workflows that
include them); 61,915 nodes. Every error was then read by hand, together with
the repository's own code where needed.

| Repository | Commit | Entry workflows |
| --- | --- | --- |
| bonsai-rx/docs | `3d06647c30` | 187 |
| bonsai-rx/harp | `f582c4ff9a` | 4 |
| bonsai-rx/machinelearning | `955962b1e6` | 20 |
| bonsai-rx/sleap | `6bff454ba8` | 5 |
| bonsai-rx/zeromq | `118ab7fe59` | 8 |
| bonsai-rx/daqmx | `ac70eb81f7` | 9 |
| bonsai-rx/spikeglx | `1fb9e97f52` | 5 |
| bonsai-rx/mixer | `c32aa91122` | 5 |
| harp-tech/device.stepperdriver | `f3788fc883` | 3 |
| AllenNeuralDynamics/Bonsai.AllenNeuralDynamics | `717c551cc3` | 44 |
| AllenNeuralDynamics/Aind.Behavior.VrForaging | `d41b073bbc` | 3 |
| AllenNeuralDynamics/Aind.Behavior.Telekinesis | `3c233a66b8` | 3 |
| AllenNeuralDynamics/Aind.Behavior.DynamicForaging | `0ff230123f` | 10 |
| jtdbod/restaurant-row-berkeley | `358d356436` | 30 |
| int-brain-lab/iblrig | `a0a031e2f9` | 22 |
| SainsburyWellcomeCentre/aeon_acquisition | `208267664d` | 57 |
| neurogears/vestibular-vr | `18bf7151e4` | 38 |

## What the first run taught baghban

The first run (baghban 0.1.0) reported **202 `DANGLING_SUBJECT` errors**. Rigs
that run every day are not that broken, so they were read by hand. Almost all
were in *modules*: workflows meant to be included, whose subjects the
including workflow declares. Bonsai has two conventions for them, both
confirmed in its source and now modelled (`src/baghban/project.py`):

- files under an `Extensions` folder, which the editor lists as reusable
  toolbox elements (`Project.EnumerateExtensionWorkflows`);
- files embedded in a package project (`<EmbeddedResource Include="**\*.bonsai" />`,
  in 19 project files across these repositories).

A module's undeclared subjects are now reported as its *interface*, not as
errors. Test projects, which embed fixtures that are run as top-level
workflows, are excluded from that rule. Package projects in the same
repository are also used to follow embedded includes automatically.

Reading the errors also exposed two bugs and one wrong claim in baghban
0.1.0, all fixed, each with a regression test:

- `.bonsai` *folders* (Bonsai environments) were collected as workflow files;
- two workflows including each other were both skipped as "checked through
  their includer", so neither was checked;
- **a wrong claim:** baghban said an unnamed `SubscribeSubject` makes Bonsai
  fail to build. Reading `SubscribeSubject.cs` suggested it does not (it
  returns an empty expression), so 0.2.0 made it a warning. Running it on
  real Bonsai (`confirm/`) showed the full story: the empty expression is not
  passed on, so a node connected after it gets no input and Bonsai refuses to
  build it. `UNNAMED_SUBJECT` is now an error when nodes follow it, info when
  none do. Reading the source alone got this half right; running it settled
  it.

Result: 202 → 13 `DANGLING_SUBJECT` errors.

## Findings after the fixes

| Findings | Severity | Code | Repositories |
| ---: | --- | --- | ---: |
| 13 | error | `DANGLING_SUBJECT` | 3 |
| 11 | error | `MISSING_INCLUDE` | 3 |
| 3 | error | `SILENT_OVERWRITE` | 2 |
| 2 | error | `UNNAMED_SUBJECT` (nodes connected after it) | 2 |
| 57 | warning | `DISABLED_WRITER` | 3 |
| 154 | info | `UNUSED_SUBJECT` | 8 |
| 44 | info | `SILENT_OVERWRITE` (externalized file name) | 1 |
| 5 | info | `APPENDS_ACROSS_RUNS` | 1 |
| 3 | info | `UNNAMED_SUBJECT` (nothing after it, or multicast) | 1 |

No crashes. One file was unreadable: `3sec_Restaurant(Dim)_…_old.bonsai` in
restaurant-row-berkeley is not well-formed XML, so Bonsai cannot open it
either.

## Every error, read by hand

Verdicts: **true fault** (the workflow is wrong), **true, by design** (the
statement is correct but the file is not meant to work alone), **true,
likely harmless**, or **false alarm**.

| Findings | Where | Verdict |
| ---: | --- | --- |
| 8 | bonsai-rx/docs: five BonVision examples include `Extensions\RandomOrientationGrating.bonsai` (some twice), which is not in the repository | **true fault** (in documentation) |
| 1 | iblrig: `devices/harp_photodiode/screen_sweep_harp_photodiode.bonsai` includes `Extensions\range.bonsai`, which is not in the repository | **true fault** |
| 2 | Bonsai.AllenNeuralDynamics docs: two examples include `AllenNeuralDynamics.AindManipulator:AindManipulator.bonsai`; the package only contains `AindManipulatorGui.bonsai`, apparently a rename the examples did not follow | **true fault** (in documentation) |
| 1 | neurogears/vestibular-vr `GNGTemplate.bonsai`: `CsvWriter 'responses.csv'`, `Overwrite=True`, `Suffix=None` | **true fault**: each run replaces the last run's responses, and a template is copied into new tasks |
| 13 | `docs/workflows` in bonsai-rx/docs (5), Bonsai.AllenNeuralDynamics (5) and bonsai-rx/machinelearning (3): diagram snippets that subscribe to subjects declared nowhere | **true, by design**: snippets for rendering documentation figures, never built alone. `--exclude 'docs/*'` skips them |
| 1 | restaurant-row-berkeley `5s-wait_80pct-rewarded_EXPERIMENTAL.bonsai`: an unnamed `SubscribeSubject` inside `Timestamp & Save Events` feeds a `PropertyMapping`, which needs exactly one input | **true fault**: the workflow cannot build (confirmed behaviour, `confirm/`) |
| 1 | bonsai-rx/docs `language-subject-subscribe.bonsai`: unnamed `SubscribeSubject` feeding a `VideoWriter` | **true, by design**: a documentation snippet |
| 2 | iblrig `ReceptiveFieldMappingStim.bonsai` (two task copies): `MatrixWriter 'NoiseLocations.bin'`, `Overwrite=True`, `Suffix=None` | **true, likely harmless**: the file is replaced every session, but IBL's launcher collects the stimulus data through a different, externalized file name and nothing in the repository reads `NoiseLocations.bin` |

**No false alarms among the 29 errors.** 13 point at real faults (5
distinct problems, repeated across files), 14 are true of documentation
snippets by design, and 2 are true but likely harmless.

## Warnings and infos, sampled

- `DISABLED_WRITER` (57): 52 are in restaurant-row-berkeley, whose many task
  variants hard-code animal and day file names and disable the photometry
  and video writers in variants that do not record them. Correct, and
  deliberate there; a warning ("confirm this is intended") fits.
- `SILENT_OVERWRITE` with an externalized file name (44, all iblrig): the
  launcher sets a per-session path (the XML holds a `2000-01-01\001`
  placeholder). This used to be a warning; it is now info, because
  launchers setting these names is the norm and baghban cannot see them.
- In-loop overwrite: iblrig includes the module above inside a `SelectMany`
  that most likely receives one element per session. The message now says
  what baghban cannot know: *if* the loop receives more than one element,
  each replaces the previous one.

## What limits coverage

116 entry workflows carry `not checked:` notes, almost all from includes
into packages that live in other repositories:

| Unresolved embedded includes | Package |
| ---: | --- |
| 151 | BonVision |
| 122 | AllenNeuralDynamics.Core |
| 59 | AllenNeuralDynamics.HarpUtils |
| 18 | Aeon.Acquisition |
| 17 | Bonsai.Harp |

Resolving these (roadmap item 3) is the largest remaining gain in coverage.

## Caveats

- Public repositories over-represent documentation and packages: 187 of the
  453 entry workflows come from bonsai-rx/docs alone, and 110 are package or
  Extensions modules.
- Precision is estimated on errors only. Warnings were sampled, not read in
  full.
- Recall is not measured: nothing here says which faults baghban misses.
  The confirmation harness (`confirm/`) addresses correctness of what it
  reports, not what it misses.
