# Survey: baghban on published Bonsai workflows

Roadmap item 2. The question: on workflows people actually publish, how often
do the findings fire, and how often are they right?

**Runs:** September 2026 with baghban 0.2.0; re-run on 4 Oct 2026 with
baghban 0.2.1, after the first `confirm/` run corrected `UNNAMED_SUBJECT`.
The numbers below are from the 0.2.1 run, on the same 32 repository commits;
its full output is `survey-results.json` in this folder. `python survey/run_survey.py WORKDIR`.
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
  it, and the second `confirm/` run confirmed both behaviours (an error with
  a node after it, a normal run without).

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
| --- | --- | --- |
| 2 | Bonsai.AllenNeuralDynamics docs: [AindManipulatorFromDefault](https://github.com/AllenNeuralDynamics/Bonsai.AllenNeuralDynamics/blob/717c551cc3ed7e1aafb556b2da2cd9920d31c2b1/docs/workflows/AindManipulatorFromDefault.bonsai#L50) and [AindManipulatorFromJson](https://github.com/AllenNeuralDynamics/Bonsai.AllenNeuralDynamics/blob/717c551cc3ed7e1aafb556b2da2cd9920d31c2b1/docs/workflows/AindManipulatorFromJson.bonsai#L28) include `AllenNeuralDynamics.AindManipulator:AindManipulator.bonsai`, which was deleted from the package on 2026-01-29 (commit `b0b68b8`, "Update AindManipulator to latest aind-behavior-services model specification"); both examples are embedded in `docs/articles/aind-manipulator.md` | **true fault** (in documentation) |
| 1 | iblrig: [screen_sweep_harp_photodiode.bonsai](https://github.com/int-brain-lab/iblrig/blob/a0a031e2f9969c192767a255781920028034b7b0/devices/harp_photodiode/screen_sweep_harp_photodiode.bonsai#L34) includes `Extensions\range.bonsai`. `devices/harp_photodiode/` has never had an `Extensions` folder in the repository's history; the only `range.bonsai` lived in `devices/screen_calibration/wrkflws/Extensions/` and was removed with that folder's screen-sweep workflows in the 2024-08-12 dead-code cleanup (`2434fee3`). Nothing in the Python code refers to this workflow | **true fault**, possibly in dead code |
| 1 | neurogears/vestibular-vr [GNGTemplate.bonsai](https://github.com/neurogears/vestibular-vr/blob/18bf7151e417310acc5d8881eb157df98f486943/src/Workflows/GNGTemplate.bonsai#L30-L36): `CsvWriter 'responses.csv'`, `Overwrite=True`, `Suffix=None`. Unchanged since March 2023, referenced nowhere | **true fault**, low impact: each run replaces the last run's responses, which matters only if the template is still used or copied |
| 1 | restaurant-row-berkeley [5s-wait_80pct-rewarded_EXPERIMENTAL.bonsai](https://github.com/jtdbod/restaurant-row-berkeley/blob/358d356436f835192ae05b9727ab139773384b5e/5s-wait_80pct-rewarded_EXPERIMENTAL.bonsai): inside `Timestamp & Save Events`, an unnamed `SubscribeSubject` feeds the `PropertyMapping` that sets the event `CsvWriter`'s `FileName`; `PropertyMapping` needs exactly one input | **true fault**: the workflow cannot build. The mechanism was confirmed on real Bonsai (`confirm/`, case `unnamed_subscribe`); this exact workflow was not run. Repository inactive since February 2021 |
| 8 | bonsai-rx/docs: five BonVision tutorial workflows include `Extensions\RandomOrientationGrating.bonsai`, which is not in the repository | **true, by design**: the tutorial (`tutorials/vision-psychophysics.md`, line 81) has the reader create this extension with *Save as Workflow*; the workflows are snapshots of the tutorial's steps. Recorded as a fault in the first version of this write-up, and corrected before reporting it, after reading the tutorial |
| 13 | `docs/workflows` in bonsai-rx/docs (5), Bonsai.AllenNeuralDynamics (5) and bonsai-rx/machinelearning (3): diagram snippets that subscribe to subjects declared nowhere | **true, by design**: snippets for rendering documentation figures, never built alone. `--exclude 'docs/*'` skips them |
| 1 | bonsai-rx/docs `language-subject-subscribe.bonsai`: unnamed `SubscribeSubject` feeding a `VideoWriter` | **true, by design**: a documentation snippet |
| 2 | iblrig `ReceptiveFieldMappingStim.bonsai` (two task copies): `MatrixWriter 'NoiseLocations.bin'`, `Overwrite=True`, `Suffix=None` | **true, likely harmless**: the file is replaced every session, but IBL's launcher collects the stimulus data through a different, externalized file name and nothing in the repository reads `NoiseLocations.bin` |

**No false alarms among the 29 errors.** 5 point at real faults (4
distinct problems), 22 are correct about files that are not meant to work
on their own (documentation snippets and tutorial steps), and 2 are correct
but likely harmless.

Each real fault was checked against the repository's history before being
reported; that check is what reclassified the BonVision tutorial workflows.
The lesson for baghban: a missing `Extensions` module can be something the
reader is meant to create. Tutorials could be recognised by a check that the
module is named in nearby documentation; until then this stays a human
judgement.

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
  The confirmation kit (`confirm/`, 13/13 on real Bonsai) addresses whether
  what baghban reports actually happens, not what it misses.
