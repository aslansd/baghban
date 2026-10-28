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
statement is correct, but the file is not meant to work alone, or its authors
want that behaviour), **true, likely harmless**, or **false alarm**.

| Findings | Where | Verdict |
| --- | --- | --- |
| 2 | Bonsai.AllenNeuralDynamics docs: [AindManipulatorFromDefault](https://github.com/AllenNeuralDynamics/Bonsai.AllenNeuralDynamics/blob/717c551cc3ed7e1aafb556b2da2cd9920d31c2b1/docs/workflows/AindManipulatorFromDefault.bonsai#L50) and [AindManipulatorFromJson](https://github.com/AllenNeuralDynamics/Bonsai.AllenNeuralDynamics/blob/717c551cc3ed7e1aafb556b2da2cd9920d31c2b1/docs/workflows/AindManipulatorFromJson.bonsai#L28) include `AllenNeuralDynamics.AindManipulator:AindManipulator.bonsai`, which was deleted from the package on 2026-01-29 (commit `b0b68b8`, "Update AindManipulator to latest aind-behavior-services model specification"); both examples are embedded in `docs/articles/aind-manipulator.md` | **true fault** (in documentation) |
| 1 | iblrig: [screen_sweep_harp_photodiode.bonsai](https://github.com/int-brain-lab/iblrig/blob/a0a031e2f9969c192767a255781920028034b7b0/devices/harp_photodiode/screen_sweep_harp_photodiode.bonsai#L34) includes `Extensions\range.bonsai`. `devices/harp_photodiode/` has never had an `Extensions` folder in the repository's history; the only `range.bonsai` lived in `devices/screen_calibration/wrkflws/Extensions/` and was removed with that folder's screen-sweep workflows in the 2024-08-12 dead-code cleanup (`2434fee3`). Nothing in the Python code refers to this workflow | **true fault**, possibly in dead code |
| 1 | neurogears/vestibular-vr [GNGTemplate.bonsai](https://github.com/neurogears/vestibular-vr/blob/18bf7151e417310acc5d8881eb157df98f486943/src/Workflows/GNGTemplate.bonsai#L30-L36): `CsvWriter 'responses.csv'`, `Overwrite=True`, `Suffix=None`. Unchanged since March 2023, referenced nowhere | **true, by design**: each run does replace the last run's responses (confirmed on real Bonsai), and that is what its maintainers want. It is a demo of the task structure, run to experiment with, where one file rewritten each time is the point ([neurogears/vestibular-vr#137](https://github.com/neurogears/vestibular-vr/issues/137)). Recorded as a true fault until 28 Oct 2026; since baghban 0.5.0 this finding is a warning |
| 1 | restaurant-row-berkeley [5s-wait_80pct-rewarded_EXPERIMENTAL.bonsai](https://github.com/jtdbod/restaurant-row-berkeley/blob/358d356436f835192ae05b9727ab139773384b5e/5s-wait_80pct-rewarded_EXPERIMENTAL.bonsai): inside `Timestamp & Save Events`, an unnamed `SubscribeSubject` feeds the `PropertyMapping` that sets the event `CsvWriter`'s `FileName`; `PropertyMapping` needs exactly one input | **true fault**: the workflow cannot build. The mechanism was confirmed on real Bonsai (`confirm/`, case `unnamed_subscribe`); this exact workflow was not run. Repository inactive since February 2021 |
| 8 | bonsai-rx/docs: five BonVision tutorial workflows include `Extensions\RandomOrientationGrating.bonsai`, which is not in the repository | **true, by design**: the tutorial (`tutorials/vision-psychophysics.md`, line 81) has the reader create this extension with *Save as Workflow*; the workflows are snapshots of the tutorial's steps. Recorded as a fault in the first version of this write-up, and corrected before reporting it, after reading the tutorial |
| 13 | `docs/workflows` in bonsai-rx/docs (5), Bonsai.AllenNeuralDynamics (5) and bonsai-rx/machinelearning (3): diagram snippets that subscribe to subjects declared nowhere | **true, by design**: snippets for rendering documentation figures, never built alone. `--exclude 'docs/*'` skips them |
| 1 | bonsai-rx/docs `language-subject-subscribe.bonsai`: unnamed `SubscribeSubject` feeding a `VideoWriter` | **true, by design**: a documentation snippet |
| 2 | iblrig `ReceptiveFieldMappingStim.bonsai` (two task copies): `MatrixWriter 'NoiseLocations.bin'`, `Overwrite=True`, `Suffix=None` | **true, likely harmless**: the file is replaced every session, but IBL's launcher collects the stimulus data through a different, externalized file name and nothing in the repository reads `NoiseLocations.bin` |

**No false alarms among the 29 errors.** 4 point at real faults (3
distinct problems), 23 are correct about files that are not meant to work
on their own or that behave as their authors intend (documentation
snippets, tutorial steps and a demo), and 2 are correct but likely
harmless. The demo was first counted as a fault; its maintainers' answer
corrected that (see [Intent](#intent-what-050-changes-28-oct-2026)).

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

In the 0.2.1 run, 116 entry workflows carried `not checked:` notes, almost
all from includes into packages that live in other repositories:

| Unresolved embedded includes | Package |
| ---: | --- |
| 151 | BonVision |
| 122 | AllenNeuralDynamics.Core |
| 59 | AllenNeuralDynamics.HarpUtils |
| 18 | Aeon.Acquisition |
| 17 | Bonsai.Harp |

Roadmap item 3 (baghban 0.3.0) reads these: see the next section.

## Packages: what reading them adds (0.3.0 preview, 11 Oct 2026)

baghban 0.3.0 reads embedded workflows out of package DLLs, at the version
the rig's environment pins. The real run downloads the packages from
nuget.org (`python survey/run_survey.py WORKDIR --fetch`). nuget.org was not
reachable from the machine this preview was made on, so it read each package
from its **source repository at HEAD** instead (`--package-sources`: the
survey's own clones, which hold AllenNeuralDynamics.Core, HarpUtils,
Aeon.Acquisition and Bonsai.Harp, plus BonVision at `785fa61d35`). That is
an approximation, and the review below shows where it fails. Full output:
`survey-results-0.3.0-preview.json`.

Both runs are on the repositories as of 11 Oct 2026. Six had moved since
4 Oct; one of those changes came out of this survey:
AllenNeuralDynamics/Bonsai.AllenNeuralDynamics merged
[PR #142](https://github.com/AllenNeuralDynamics/Bonsai.AllenNeuralDynamics/pull/142),
which fixed the two documentation examples reported in
[issue #141](https://github.com/AllenNeuralDynamics/Bonsai.AllenNeuralDynamics/issues/141),
so their two `MISSING_INCLUDE` errors are gone.

| | Without packages | With packages (preview) |
| --- | ---: | ---: |
| Nodes checked | 62,696 | 72,047 |
| Entry workflows with `not checked` notes | 115 | 86 |
| `DANGLING_SUBJECT` | 13 | 21 |
| `MISSING_INCLUDE` | 9 | 16 |
| `SILENT_OVERWRITE` (error) | 3 | 3 |
| `UNNAMED_SUBJECT` (error) | 2 | 2 |
| `UNUSED_SUBJECT` (info) | 153 | 177 |

Almost all remaining notes are now intrinsic: file names computed at run
time (69) and module interfaces, not unreadable packages. Only the two
`Bonsai.ML` packages stay unread (7 workflows): their current source no
longer has those assembly names, which a `--fetch` run at the pinned
version would read.

Of the 193 cross-repository package includes in entry workflows, 166 (86%)
have their version pinned by an environment; the 27 others (BonVision in
documentation snippets, the two `Bonsai.ML` packages) would be read at the
newest version, and every report says so.

### The 15 new errors, read by hand

Each was checked against the history of the package at the version the
rig pins, not only against the preview's source at HEAD.

| Findings | Where | Verdict |
| ---: | --- | --- |
| 3 | iblrig [`Gabor2D_clean.bonsai`](https://github.com/int-brain-lab/iblrig/blob/a0a031e2f9969c192767a255781920028034b7b0/visual_stim/GaborIBLTask/Gabor2D_clean.bonsai) includes `BonVision:Environment.OrthographicViewport`, `ViewingWindow` and `NormalizedViewport`. iblrig pins BonVision 0.9.0 (in `Bonsai/Bonsai.config`), released 2021-03-25; those modules were renamed in March 2020 (`2aec89b`, to `OrthographicView`, `ViewWindow`, `NormalizedView`) | **true fault**: with the version the rig installs, the workflow cannot build. Probably an unused variant: nothing in iblrig's code refers to it, and its sibling `Gabor2D.bonsai` uses the current names |
| 8 | bonsai-rx/docs BonVision tutorial workflows subscribe to `Draw` (7) or `AngleDistribution` (1), declared nowhere in the file | **true, by design**: the tutorial (`vision-psychophysics.md`, line 33) has the reader declare `Draw` in an earlier step. Hidden before because BonVision was unreadable |
| 4 | neurogears/vestibular-vr `Main.bonsai` and `TrialLogicTest.bonsai` include `Aeon.Acquisition:LogVideo.bonsai`, not in Aeon.Acquisition's source at HEAD | **false alarm of the preview method**: vestibular-vr pins Aeon.Acquisition 0.5.0-build240227 (in `bonsai/Bonsai.config`); in February 2024 `LogVideo.bonsai` was still in Aeon.Acquisition, and moved to Aeon.Video in July 2024 (`a46d067`). Read at the pinned version, as `--fetch` does, it resolves |

So: no false alarm from baghban's model of Bonsai, one new real fault
(3 findings), 8 more documentation fragments, and 4 false alarms that come
from reading a package at the wrong version, which is the case for reading
the pinned version in the first place.

The review also changed baghban: both pinned environments above are
*portable* Bonsai installs committed next to the workflows (`Bonsai/` and
`bonsai/`), which Bonsai's own lookup (`.bonsai/` only) does not see. 0.3.0
accepts them after `.bonsai/`, so `--fetch` reads the versions those labs run.

The 24 new `UNUSED_SUBJECT` infos are subjects in the rigs' own workflows
(e.g. `RawLoadCellData` in Aind.Behavior.Telekinesis): before, an unreadable
include in the same scope might have subscribed to them, so baghban stayed
quiet; now it can see that nothing does. None is in a package module:
subjects a package declares are what it offers, and are never reported.

### The real run: packages at their pinned versions (12 Oct 2026)

`python survey/run_survey.py ~/baghban-survey --fetch` on a Mac that reaches
nuget.org, on exactly the same repository commits as the runs above. Full
output: `survey-results-0.3.0.json`. Each package was read from its DLL at
the version the rig's environment pins: BonVision 0.9.0 for iblrig, 0.11.0
for vestibular-vr and 0.12.0 for the Allen tasks, AllenNeuralDynamics.Core
0.4.1, Bonsai.Harp 3.5.0 and 3.6.1, and so on. 42 of the 54 uses of a package
in an entry workflow had a pinned version; the 12 others (BonVision in the
documentation, the two `Bonsai.ML` packages in their own documentation) were
read at the newest version, and their reports say so.

| | Without packages | Preview (source at HEAD) | Real run (pinned DLLs) |
| --- | ---: | ---: | ---: |
| Nodes checked | 62,696 | 72,047 | 71,347 |
| Entry workflows with `not checked` notes | 115 | 86 | 84 |
| `DANGLING_SUBJECT` | 13 | 21 | 23 |
| `MISSING_INCLUDE` | 9 | 16 | 12 |
| `SILENT_OVERWRITE` (error) | 3 | 3 | 3 |
| `UNNAMED_SUBJECT` (error) | 2 | 2 | 2 |
| `UNUSED_SUBJECT` (info) | 153 | 177 | 179 |

One package could not be read: vestibular-vr pins Aeon.Acquisition
`0.5.0-build240227`, a CI build that nuget.org does not have (18 includes in
3 workflows). baghban reports those includes as not checked instead of
reading another version, so the four preview false alarms about `LogVideo`
do not appear.

**The 13 new errors, read by hand:**

| Findings | Where | Verdict |
| ---: | --- | --- |
| 3 | iblrig `Gabor2D_clean.bonsai`: `BonVision 0.9.0 ... has no embedded workflow 'BonVision.Environment.OrthographicViewport.bonsai'`, and the same for `ViewingWindow` and `NormalizedViewport` | **true fault**, now read from the DLL the rig installs; the preview had found it from BonVision's history |
| 8 | bonsai-rx/docs BonVision tutorial workflows (`Draw`, `AngleDistribution`) | **true, by design**, as in the preview |
| 2 | bonsai-rx/machinelearning `docs/workflows/HMMImplementation.bonsai` (`Data`) and `KFModelImplementation.bonsai` (`BehaviorData`) | **true, by design**: the getting-started pages tell the reader to "connect your data source to a `Subject` named `Data`" (or `BehaviorData`); these are templates the reader completes. Hidden until the `Bonsai.ML` packages could be read |

**No false alarms among the 40 errors.** 5 point at real faults (3 distinct
problems), 33 are correct about files never meant to work alone or that
behave as their authors intend (documentation snippets, tutorial steps,
templates and a demo), and 2 are correct but likely harmless. No finding
disappeared. (Counted as 6 real faults until the vestibular-vr demo was
reclassified on 28 Oct 2026.)

Reading packages also confirmed the reader itself: on the 8 packages the
survey most needed, it agrees with Microsoft's System.Reflection.Metadata on
every name, offset and byte (`confirm/README.md`).

## Launcher values: what 0.4.0 changes (12 Oct 2026)

0.4.0 applies `--property` values as Bonsai does, and in doing so fixed
how values written on an IncludeWorkflow element travel: they now reach
groups inside the included file, as they do in Bonsai. Re-running the
survey without packages (`--no-clone`, the same clones), with 0.3.0 and
with 0.4.0:

| | 0.3.0 | 0.4.0 |
| --- | ---: | ---: |
| Errors | 27 | 27 (identical) |
| `DISABLED_WRITER` (warning) | 57 | 57 (identical) |
| `UNUSED_SUBJECT` (info) | 153 | 152 |
| Entry workflows with `not checked` notes | 115 | 114 |

With packages read at their pinned versions (`--fetch`, baghban 0.4.1, run
on macOS on 12 Oct 2026), the comparison is the same. Errors and warnings
match 0.3.0's real run (23 `DANGLING_SUBJECT`, 12 `MISSING_INCLUDE`, 3
`SILENT_OVERWRITE`, 2 `UNNAMED_SUBJECT`; 57 `DISABLED_WRITER`).
`UNUSED_SUBJECT` goes from 179 to 178, and `not checked` notes from 84 to 83.
The new `DUPLICATE_PROPERTY` check finds nothing.

Both differences are one workflow, AIND Dynamic Foraging's
`src/test_saturation_visualizer.bonsai`. It includes
`Extensions/CameraPreviewVisualizer.bonsai` with
`<FrameSubject>Frame</FrameSubject>`, and the included file maps
`FrameSubject` into the group `CameraPreview`, onto a `SubscribeSubject`.
0.3.0 stopped at the group: it reported the subject `Frame` as unused (a
**false alarm**, at info level) and the module as expecting a subject
`Camera` from its includer. 0.4.0 follows the value, sees `Frame`
subscribed, and checks the module fully.

The same clones were also used to test the new API. Provenance was built for
all 572 readable workflows. Every property each workflow exposes, through
uniquely named nested workflows, was turned into a dotted `--property`
name (1,114 names with a single saved value) and set to that value: all
resolve. The fingerprint changes in one workflow, where a value that came
from a module's default is now written on the include element, as Bonsai
also does. This is why provenance fingerprints the file as saved.

## Intent: what 0.5.0 changes (28 Oct 2026)

The vestibular-vr maintainers answered the report about `GNGTemplate.bonsai`
([#137](https://github.com/neurogears/vestibular-vr/issues/137)).
`Overwrite=True` there is intended: the workflow is a small demo for setting
up the task structure. While testing they want neither many output files
nor a new file name each time. They added that `Overwrite=True` with
`Suffix=None` "is not necessarily a mistake, it very much depends on the
intended use of the workflow".

They are right, and baghban was half right. What it said would happen did
happen (each run replaces the file, confirmed on real Bonsai). But reporting
it as an **error** called it a mistake. `Overwrite=True` is a setting someone
has to switch on (the default is `False`), so it often signals intent.
baghban 0.5.0 therefore:

- reports overwriting across runs (writer not in a loop) as a **warning**,
  whose message says it is fine for a demo or scratch output;
- keeps overwriting inside a per-element loop (`SelectMany`,
  `CreateObservable`, `WindowWorkflow`) an **error**: there, all but the last
  element are lost within one session, which is rarely anyone's intent
  (confirmed on real Bonsai, case `overwrite_per_element`);
- lets a project mark a finding as intended, once: `--ignore CODE[:PATTERN]`,
  or a `baghban.toml` (or `[tool.baghban]` in `pyproject.toml`) next to the
  workflows. Marked findings are listed, not hidden, and not counted.

Re-running the survey without packages, on the same 32 commits (28 Oct
2026). The 0.5.0 column is the released package, installed from PyPI; its
full output is `survey-results-0.5.0.json`, with paths relative to the
survey folder (`WORKDIR/`):

| | 0.4.1 | 0.5.0 |
| --- | ---: | ---: |
| Errors | 27 | 26 |
| `SILENT_OVERWRITE` (error) | 3 | 2 |
| `SILENT_OVERWRITE` (warning) | 0 | 1 |
| Everything else | | identical |

The one change is `GNGTemplate.bonsai`. The two `SILENT_OVERWRITE` errors
left are iblrig's `ReceptiveFieldMappingStim.bonsai` (two task copies), whose
writer sits inside a `SelectMany`. They were read as **likely harmless**,
because the loop most likely receives one element per session. baghban
cannot know how many elements a loop receives, so they stay errors, with a
message that says "if". The survey with packages (`--fetch`) was not re-run
for 0.5.0. Its three `SILENT_OVERWRITE` errors are these same three
findings, so it should go from 40 errors to 39. That run needs nuget.org,
so it is done on a machine that can reach it, with
`python survey/run_survey.py WORKDIR --no-clone --fetch` over existing
clones.

## Caveats

- Public repositories over-represent documentation and packages: 187 of the
  453 entry workflows come from bonsai-rx/docs alone, and 110 are package or
  Extensions modules.
- Precision is estimated on errors only. Warnings were sampled, not read in
  full.
- "No false alarm" means baghban was right about what Bonsai will do.
  Whether that behaviour is a mistake is for the workflow's authors to say:
  vestibular-vr's demo is correct about the behaviour and intended by its
  authors, and is now counted as by design.
- The package preview read packages from source at HEAD; the real run read
  them at the pinned versions, and the tables above keep both. A version
  nuget.org does not have (a CI build) is not checked.
- Recall is not measured: nothing here says which faults baghban misses.
  The confirmation kit (`confirm/`, 13/13 on real Bonsai) addresses whether
  what baghban reports actually happens, not what it misses.
