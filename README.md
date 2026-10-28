# baghban

**باغبان** — *bağban, gardener.* The same word in Persian and Azerbaijani.
Someone has to tend the bonsai.

**Know what will go wrong with a Bonsai rig before the session runs.**
baghban reads [Bonsai](https://bonsai-rx.org) workflow files and reports the
faults that lose data without an error: a writer that overwrites every trial,
two cameras recording into one file, a logger left disabled after debugging,
a subject name with a typo. It also draws, compares and fingerprints
workflows, so you can review a rig from a Mac or Linux laptop.

```
pip install baghban
```

Python 3.10+. Apache 2.0. **No dependencies. No Windows, no .NET, no Bonsai
installation.** baghban reads the `.bonsai` XML; it never runs a workflow.
It makes no network calls unless you ask it to download packages (`--fetch`).

---

## The failure that matters

Bonsai's costliest bugs do not crash anything. The workflow builds, the
cameras light up, the session runs for an hour, and the problem surfaces weeks
later in analysis:

- A `CsvWriter` inside a per-trial `SelectMany` with `Overwrite=True` and
  `Suffix=None` is opened again for every trial and replaces the file each
  time. After 200 trials, the file holds trial 200.
- A camera-recording module included twice, without giving each copy its own
  file name, sends both cameras to `camera.avi`.
- A writer disabled while debugging a sensor stays disabled. Nothing is
  recorded, and nothing says so.

Each of these is fully determined by the workflow file. None of them is
reported by Bonsai before the data is gone.

---

## The thirty-second version

```
$ baghban check examples/rig_v1/foraging.bonsai

[error] DUPLICATE_OUTPUT  Include 'modules/CameraRecorder.bonsai' #3 > VideoWriter 'camera.avi' #1
   in .../examples/rig_v1/modules/CameraRecorder.bonsai
    Another writer also writes 'camera.avi' (Include 'modules/CameraRecorder.bonsai' #1 >
    VideoWriter 'camera.avi' #1). Two writers cannot hold the same file: one of them fails,
    or they overwrite each other. This is common when a module containing a writer is
    included twice without giving each copy its own file name.
    fix: Give each writer its own file name; for included modules, externalize FileName and
    set it on each IncludeWorkflow.

[error] SILENT_OVERWRITE  SelectMany 'Trial' #6 > CsvWriter 'trial.csv' #2
    Overwrite=True with Suffix=None: each run replaces 'trial.csv' from the previous
    session. It sits inside SelectMany 'Trial', which opens it again for every element it
    receives: if that is more than one (e.g. one per trial), each element also replaces the
    previous one within the session.
    fix: Use Suffix=Timestamp or FileCount to keep one file per element, or move the writer
    after the SelectMany to collect all elements in one file.

[error] DANGLING_SUBJECT  SubscribeSubject 'TrialEnds' #8
    No subject named 'TrialEnds' is declared in this scope or any enclosing one, so Bonsai
    will fail to build the workflow.
    fix: Did you mean 'TrialEnd'?

[warning] DISABLED_WRITER  CsvWriter 'licks.csv' #11
    This CsvWriter is disabled, so nothing will be written to 'licks.csv'. Disabling a
    writer while debugging and forgetting to re-enable it loses whole sessions without an
    error.
    fix: Re-enable it, or delete it if the data is not needed.

[info] UNUSED_SUBJECT  PublishSubject 'TrialEnd' #7
    Subject 'TrialEnd' is declared but nothing subscribes to it.

3 errors, 1 warning, 1 info in 22 nodes.
```

That is `examples/rig_v1`, a foraging rig with two cameras, a lick sensor
and 10 s trials. `examples/rig_v2` is the same rig fixed, and checks clean.
`check` exits 1 when there are errors, so it can gate a commit or a CI run.

`#n` is a node's position in its own workflow, as in the XML, which is how
the two copies of the included module are told apart.

---

## Findings

| Finding | Severity | Question it answers |
| --- | --- | --- |
| `SILENT_OVERWRITE` | error / warning | Will a writer replace data without an error? Inside a per-trial loop, from an earlier trial in the same run: error. Across runs: warning. |
| `FAILS_ON_REPEAT` | error | Will a writer inside a per-trial loop raise "file already exists" on trial 2 and end the session? |
| `DUPLICATE_OUTPUT` | error | Do two writers write to the same file? |
| `DANGLING_SUBJECT` | error | Does a `SubscribeSubject` or `MulticastSubject` name a subject that is not declared where it can see it? |
| `DUPLICATE_SUBJECT` | error | Are two subjects with one name declared in the same scope? |
| `DUPLICATE_PROPERTY` | error | Do two externalized properties in one workflow share a name? |
| `MISSING_INCLUDE` | error | Does an `IncludeWorkflow` point at a file that does not exist? |
| `RECURSIVE_INCLUDE` | error | Do workflows include each other in a cycle? |
| `INVALID_INCLUDE` | error | Is an included file not a readable workflow? |
| `DISABLED_WRITER` | warning | Is a writer (or a group holding one) disabled, so nothing is recorded? |
| `UNNAMED_SUBJECT` | error | Does a `SubscribeSubject` without a name feed other nodes? It builds to nothing, so they get no input and Bonsai refuses to build them. (With nothing after it, or for an unnamed `MulticastSubject`: info.) |
| `APPENDS_ACROSS_RUNS` | info | Does every run append to the same file, and repeat the CSV header mid-file? |
| `UNUSED_SUBJECT` | info | Is a subject declared but never subscribed to? |

`SILENT_OVERWRITE` has three levels:
- **Error** inside a loop: all but the last trial are lost within one
  session, which is rarely anyone's intent.
- **Warning** across runs. `Overwrite=True` is a setting someone has to
  switch on, and replacing the last run's file is often the point, as in a
  demo (see [When a finding is intended](#when-a-finding-is-intended)).
- **Info** when the file name is externalized. Launchers commonly set a new
  name each session (the survey found this throughout IBL's rigs), and
  baghban cannot see the launcher.

### How it decides

baghban models the parts of Bonsai's build process the checks depend on, as
the Bonsai source implements them (Bonsai.Core, Bonsai.System):

- **Scopes.** `GroupWorkflow` and `IncludeWorkflow` build in a `GroupContext`
  that forwards every declaration to its parent, so a subject declared inside
  a group is visible beside it. Every other nested workflow (`SelectMany`,
  `Defer`, `CreateObservable`, ...) builds in a new `BuildContext`: lookups
  fall back outwards, declarations stay inside. Declaring a name twice in one
  build context is a build error.
- **Loops.** `SelectMany`, `CreateObservable` and `WindowWorkflow` subscribe
  their nested workflow once per input element, so a writer inside one is
  opened once per element, typically once per trial.
- **Writers.** `CsvWriter` and the `FileSink`/`StreamSink` families
  (`VideoWriter`, `TextWriter`, `AudioWriter`, `MatrixWriter`, `ImageWriter`)
  open their file on subscription, check `File.Exists(path) && !Overwrite`,
  then create it. Any operator with `Suffix` plus `FileName` or `Path` is
  treated as a writer, which also covers third-party writers that follow the
  convention.
- **Includes.** Paths are opened relative to the working directory, which
  the editor sets to the top-level workflow's folder. baghban resolves nested
  includes the same way: relative to the top-level file, not to the file
  containing the include. Values written on an `IncludeWorkflow` set the
  included file's externalized properties, and baghban applies them, through
  nested includes too, so checks see the effective file names.
- **Disabled nodes** are not built: a disabled subject declares nothing, and
  a disabled include is not opened.

### Staying quiet when it cannot know

A checker that cries wolf on good rigs gets switched off. When the XML is not
enough to be sure, baghban says what it did not check instead of guessing:

- an include it cannot open (a package that is not installed, cached or
  fetched, or an absolute Windows path on a Mac) suspends subject checks in
  that scope, because the include may declare the subject;
- a package version nothing pins is read at the newest version found, and
  every report says `NOT pinned: newest found, findings assume it`; a module
  missing from such a guessed version is "not checked", not an error;
- a file name assigned from data at run time (`PropertyMapping`,
  `InputMapping`) is not judged;
- types are not checked, because baghban has no catalogue of what each
  package contains.

These appear as `not checked:` lines under the report.

### When a finding is intended

baghban reports what Bonsai will do. Whether that is a mistake can depend on
what the workflow is for. vestibular-vr's `GNGTemplate.bonsai` is a demo that
rewrites one `responses.csv` on every run, on purpose: its maintainers want
neither a pile of files nor a new name for each test run
([neurogears/vestibular-vr#137](https://github.com/neurogears/vestibular-vr/issues/137)).
Mark such a finding as intended once, in a `baghban.toml` next to the
workflows:

```toml
ignore = ["APPENDS_ACROSS_RUNS"]                     # everywhere below this folder

[per-file-ignores]
"src/Workflows/GNGTemplate.bonsai" = ["SILENT_OVERWRITE"]
"docs/*" = ["DANGLING_SUBJECT"]
```

```
$ baghban check src/Workflows/GNGTemplate.bonsai --strict
No findings in 2 nodes.
1 finding(s) marked as intended, not counted:
  SILENT_OVERWRITE  CsvWriter 'responses.csv' #1  (ignored by baghban.toml)
```

- **Where the file lives.** `check` finds the nearest `baghban.toml` above
  the workflow, or a `pyproject.toml` with a `[tool.baghban]` table holding
  the same settings. It stops at the repository's root.
- **Patterns** are relative to that folder, and `*` also matches `/`. A
  pattern can name the checked workflow or the module that holds the node.
- **Command line.** `--ignore CODE[:PATTERN]` does the same without a file;
  `--no-config` skips the file.
- **Nothing is hidden.** Marked findings are listed, but not counted and not
  failing `check`.
- **Typos are caught.** An unknown finding code is an error, so a misspelt
  rule cannot silently stop working.
- **Python 3.10.** Reading the file needs `tomllib`, which is built into
  Python 3.11 and later. On 3.10, install `tomli`, or use `--ignore`.

### Modules

Not every `.bonsai` file is meant to run on its own. baghban recognises
Bonsai's two conventions for modules: files under an `Extensions` folder,
which the editor offers as reusable toolbox elements, and files embedded in
a package project (`<EmbeddedResource Include="**\*.bonsai" />`). A module
may subscribe to subjects its includer declares; baghban reports those as
the module's interface instead of as errors, and resolves an Extensions
module's includes from the project folder, as the editor does. Package
projects in the same repository are also used to follow embedded includes
(`Path="My.Package:Module.bonsai"`) without any flags.

### Packages

Most rigs include modules from packages built elsewhere:
`Path="BonVision:Primitives.DrawQuad.bonsai"`. Such a module is an embedded
resource of the package DLL, and baghban reads it out of the DLL with its
own pure-Python reader of the .NET metadata format (ECMA-335), so it is
checked like any other include: a subject the module needs and the rig does
not declare is an error; a module missing from the pinned package version
is an error.

**Which version.** The one the rig runs. Like Bonsai, baghban searches from
the workflow's folder upwards for `.bonsai/Bonsai.config`, which pins every
package and records each assembly's DLL; a portable Bonsai install committed
next to the workflows (`Bonsai/` or `bonsai/`) counts too.
`--package ID=VERSION` overrides it.

**Where the DLL comes from.** Without any network access: the installed
environment (`.bonsai/Packages`, so on a rig PC it just works), the NuGet
global packages folder (`~/.nuget/packages`), then baghban's cache
(`~/.cache/baghban`, or `$BAGHBAN_CACHE`). With `--fetch`, a package found in
none of them is downloaded from nuget.org, once, into the cache
(`$BAGHBAN_NUGET_SOURCE` points at a private feed or mirror instead).

```
$ baghban check --fetch rig/main.bonsai
...
package: BonVision 0.12.0 (pinned; from nuget.org, downloaded to the baghban cache)
package: AllenNeuralDynamics.Core 0.4.1 (pinned; from baghban cache)
```

(The format of the last lines of a report; these two versions are the ones
Aind.Behavior.VrForaging pins.)

A finding inside a package names the package and version
(`in BonVision 0.12.0: BonVision.Primitives.DrawQuad.bonsai`). Subjects a
package declares are what it offers its user and are never reported as
unused. `deps` lists the packages read, and `provenance` records
their versions (`bonsai.package.BonVision = 0.12.0`).

---

## Checked against something that does not depend on it

Bonsai's own test suite ships 30 small workflows and asserts which of them
fail to build (`WorkflowRunnerTests`, `IncludeWorkflowTests`). They are
included unchanged in `tests/data/bonsai_upstream` (MIT licence), and baghban
must agree with Bonsai on every one:

| Bonsai's expectation | baghban |
| --- | --- |
| `*BuildException` workflows fail to build (undeclared `MulticastSubject`, directly and through file and embedded includes) | `DANGLING_SUBJECT` |
| `IncludeWorkflowSelfOuter` fails to build (self-inclusion) | `RECURSIVE_INCLUDE` |
| `IncludeWorkflowMissing` fails to build (missing nested include) | `MISSING_INCLUDE` |
| `*RuntimeException` workflows build, then fail while running (division by zero) | no findings: not a static problem |
| `NestedSubscribeSubjectWithClosestRedefinition` builds | no findings |
| `MissingTypes` names a type that does not exist | no findings: baghban does not guess about types |
| Nested include property: the outer include's `OuterCount = 2` reaches the inner `Take.Count` | `Take.Count == "2"` |

On the file-writer findings, where Bonsai has no test fixtures, each finding
is tested in both directions on paired workflows: it must fire where the fault
exists and stay quiet on the nearest workflow without it (see `TESTING.md`).
And the findings have been run on the real Bonsai runtime: 15 of 15 cases
behaved as predicted (`confirm/`).

### On published rigs

`survey/` runs baghban over 32 public repositories (Bonsai's own, the Allen
Institute's foraging tasks, SWC's Aeon, IBL's rig, NeuroGears' vestibular VR
and others): 453 entry workflows, 61,915 nodes (4 Oct 2026). Every error was read by
hand, and every real fault against its repository's history. **None of the
29 was a false alarm**: 4 point at real faults (3 distinct problems: a
deleted module still used by documentation examples, a missing include in a
rig, and a workflow that cannot build), 23 are correct about files never
meant to work alone or that behave as their authors intend (documentation
snippets, tutorial steps and a demo), and 2 are correct but likely harmless.
The demo was first counted as a fault. Its maintainers explained that
replacing the file each run is intended
([#137](https://github.com/neurogears/vestibular-vr/issues/137)), which is
why overwriting across runs is a warning since 0.5.0.
Reading the first run's results is also where the module conventions above,
two bugs and one wrong claim came from; see `survey/SURVEY.md`.

Re-run on 12 Oct 2026, the same workflows had 27 errors: the two Allen
documentation examples are fixed upstream since they were reported
([PR #142](https://github.com/AllenNeuralDynamics/Bonsai.AllenNeuralDynamics/pull/142)).
Reading packages at the versions the rigs pin (`--fetch`) adds 8,651 nodes
and 13 errors, and still **no false alarm among the 40**: one new real fault
(an IBL workflow including BonVision modules that were renamed before the
0.9.0 the rig installs) and 10 more documentation snippets and templates. An
earlier preview that read packages from source at HEAD instead produced 4
false alarms, all from reading a package at the wrong version: the case for
reading the pinned one.

---

## Commands

```
baghban check  WORKFLOW|DIR ...      findings; exit 1 on errors (--strict: on warnings too)
baghban show   WORKFLOW              the workflow as a tree
baghban render WORKFLOW [-f html]    draw it: html (default), mermaid, dot
baghban diff   A B                   what changed, by meaning; exit 0 if equivalent
baghban deps   WORKFLOW              assemblies (= packages) and includes it needs
baghban params WORKFLOW              externalized properties and their values
baghban fingerprint WORKFLOW         content hash, stable across re-saves
baghban provenance WORKFLOW          fields recording which protocol a session ran (JSON)
```

`check` accepts folders. `--ignore CODE[:PATTERN]` marks a finding as
intended, and `baghban.toml` is read unless `--no-config` (see
[When a finding is intended](#when-a-finding-is-intended)). A file that
another checked file includes is checked
through its includer, where the subjects and file names it relies on are
defined, rather than on its own. `--exclude GLOB` skips files, e.g.
`--exclude 'docs/*'` for documentation snippets.

`check`, `show`, `render`, `params` and `provenance` take
`-p NAME=VALUE` (repeatable), as `Bonsai.exe --property` does, to see the
workflow with the values a launcher passes rather than the saved ones. A
dotted name reaches into nested workflows (`-p Stim.Contrast=0.5`). A name
Bonsai would refuse is reported, and the command exits 1:

```
$ baghban params examples/rig_v2/foraging.bonsai -p TrialIntervl=PT5S
baghban: --property TrialIntervl: the workflow has no externalized property 'TrialIntervl'; it exposes TrialInterval (Bonsai would refuse it)
TrialInterval  = PT12S
                 -> Timer #5.Period
```

Every command takes:

```
--fetch                 download packages not installed or cached, from nuget.org
--package ID=VERSION    use this version, overriding Bonsai.config (repeatable)
--cache DIR             where downloads and extracted modules are kept
--resource-root ASSEMBLY=DIR   read a package's modules from its source folder instead
```

### See a workflow without the editor

```
baghban render rig/foraging.bonsai && open rig/foraging.html
```

writes one HTML page next to the workflow (or wherever `-o` says, and prints
the full path) with the graph (nested workflows as boxes, disabled nodes
dashed, nodes with findings outlined in red or orange), the findings table and
a text outline. It loads the Mermaid script from a CDN, so it needs a network
connection to draw. `-f mermaid` output also renders directly in GitHub
markdown and pull requests.

### Diff by meaning

Nodes are addressed by position in the XML, so inserting one node renumbers
every edge after it, and `git diff` becomes noise. `baghban diff` matches
nodes by what they are: named nodes by type and name, others by type and
occurrence ("the second CsvWriter in the Trial SelectMany"):

```
$ baghban diff rig_v1/foraging.bonsai rig_v2/foraging.bonsai

~ CsvWriter#1 ('licks.csv')  enabled
+ CsvWriter#2 ('trials.csv')
~ Include(modules/CameraRecorder.bonsai)  FileName: (unset) -> left.avi
~ Include(modules/CameraRecorder.bonsai)/VideoWriter ('left.avi')  Suffix: None -> Timestamp
- SelectMany:Trial/CsvWriter ('trial.csv')
+ SubscribeSubject:TrialEnd
- SubscribeSubject:TrialEnds
~ Timer  Period: PT10S -> PT12S
...
```

Included files are expanded, so a change inside a module shows up under each
include that uses it. Inserting an unrelated node does not disturb other keys;
it does shift the keys of later unnamed nodes of the same type in the same
workflow, which naming them avoids.

---

## Python

```
import baghban

doc = baghban.load("rig/foraging.bonsai")
report = baghban.check(doc)
print(report.summary())
report.errors               # [Finding(code, severity, message, location, file, node, hint)]
baghban.check(doc, ignore=["SILENT_OVERWRITE:demos/*"]).ignored   # marked as intended
config = baghban.find_config(doc.path)           # nearest baghban.toml, or None
baghban.check(doc, ignore=baghban.read_config(config) if config else None)

for node in doc.walk():     # every node, includes expanded
    if node.is_writer:
        print(node.location(), node.properties)

baghban.diff(baghban.load("v1.bonsai"), baghban.load("v2.bonsai")).summary()
baghban.fingerprint(doc)
baghban.mermaid(doc)

doc = baghban.load("rig/main.bonsai", fetch=True, pins={"BonVision": "0.12.0"})
report = baghban.check(doc)
report.packages             # [{"id": "BonVision", "version": "0.12.0", "pinned": True, "origin": ...}]

launch = baghban.parse_command_line(["Bonsai.exe", "rig.bonsai", "--no-editor",
                                     "-p:Stim.Contrast=0.5"])
baghban.set_properties(doc, launch.properties)   # [Assignment(name, value, status, ...)]
baghban.outputs(doc)        # [{"writer": "CsvWriter", "path": "events.csv", "suffix": ...}]
```

---

## Provenance, with daftar

A session's data is only as interpretable as the record of the protocol that
produced it: a `.bonsai` file, plus its includes, plus the parameter values
it ran with, which a launcher often passes on the command line
(`Bonsai.exe rig.bonsai -p:Animal=M12`). `baghban.provenance` turns all of
that into flat fields:

```
fields = baghban.provenance("rig/foraging.bonsai", {"TrialInterval": "PT12S"})
fields = baghban.provenance(command_line=launcher_args, cwd=rig_folder)
```

```
$ baghban provenance examples/rig_v2/foraging.bonsai -p TrialInterval=PT15S
{
  "bonsai.provenance": "1",
  "bonsai.baghban": "0.5.0",
  "bonsai.workflow": "/path/to/examples/rig_v2/foraging.bonsai",
  "bonsai.version": "2.9.0",
  "bonsai.fingerprint": "fc07dd88c5331b2dfeb53671f5e05cd80b03f49e96060cb58a745b1682b600fd",
  "bonsai.property.TrialInterval": "PT15S",
  "bonsai.param.TrialInterval": "PT15S",
  "bonsai.include.modules/CameraRecorder.bonsai": "ok",
  "bonsai.output.0": "left.avi",
  "bonsai.output.1": "right.avi",
  "bonsai.output.2": "session.csv",
  "bonsai.output.3": "licks.csv",
  "bonsai.output.4": "trials.csv"
}
```

`bonsai.property.*` are the values the launcher passed; `bonsai.param.*`
are the workflow's top-level parameters with those values applied. Every
value is a string. `bonsai.provenance` numbers the layout, so tools reading
the fields can rely on it. The function's docstring lists every field.

The fingerprint is of the workflow as saved, so all sessions of one protocol
share it whatever values they ran with. It ignores whitespace, attribute
order, namespace prefixes and the `Version` stamp the editor writes on every
save. It changes with every operator, property value, edge, disabled flag
and included file's content. Two sessions of the same protocol therefore
compare as identical, even when someone re-saved the file in between.

[daftar](https://pypi.org/project/daftar/) records these fields through its
Bonsai adapter (`pip install "daftar[bonsai]"`). daftar depends on baghban,
not the other way round.

---

## Try it

```
python examples/demo.py
```

Shows, checks, fixes, diffs and fingerprints the example rig, and writes
`examples/rig_v1.html`.

## Status

Research prototype, honestly labelled.

- On 453 published workflows, no error was a false alarm about what Bonsai
  will do (`survey/SURVEY.md`). One described behaviour its authors intend (a
  demo that overwrites its file each run). That is why overwriting across
  runs is a warning since 0.5.0, and findings can be marked as intended.
  Warnings were sampled, not read in full, and nothing measures what baghban
  misses.
- **Confirmed on the real Bonsai runtime:** `confirm/` runs 15 cases (every
  finding baghban reports about writers and subjects, with a quiet control
  for each) on Bonsai 2.9.1 packages under .NET 8. On macOS all 15 behave
  as baghban predicts (12 Oct 2026, 0.4.1). The first run (8/12) exposed a flaw in the kit and a
  wrong claim about unnamed subjects, both fixed in 0.2.1
  (`confirm/README.md`). Not yet run on Windows, where rigs run.
- **Packages are read** (0.3.0), and the reader is **confirmed against
  Microsoft's**: on 8 real Bonsai packages from nuget.org (10 DLLs, 165
  resources, 129 embedded workflows) it agrees with System.Reflection.Metadata
  on every name, offset and byte (`confirm/README.md`).
- **Launcher values** (0.4.0): `--property` values are applied by Bonsai's
  rules, read from its source (`SetWorkflowProperty`, the same from 2.6.2
  to 2.9.1). `confirm/confirm_properties.py` checks them on the real
  runtime. Its first run (12 Oct 2026, macOS) confirmed 9 of 10 cases. The
  tenth showed that Bonsai refuses to build a workflow with two properties
  of the same name, where baghban had said the first one wins. Fixed in
  0.4.1 and reported (`DUPLICATE_PROPERTY`). The corrected kit: 11/11
  (12 Oct 2026).
- Timing problems (unbounded `Zip` queues, timestamps taken after heavy
  processing) need stream rates the XML rarely states, and are not checked.

## Development

```
pip install -e ".[dev]"
pytest -q                         # 250 tests, no network, no .NET
python confirm/confirm.py         # needs .NET 8: confirm findings with real Bonsai
                                  #   (install and troubleshooting: confirm/README.md)
python confirm/confirm_packages.py  # needs .NET 8 and nuget.org: the package reader
                                    #   against Microsoft's metadata reader
python confirm/confirm_properties.py  # needs .NET 8: launcher --property values
                                      #   against Bonsai's SetWorkflowProperty
python survey/run_survey.py DIR [--fetch]   # clone and check the published repositories
```

## Licence

Apache 2.0. `tests/data/bonsai_upstream` contains test workflows from Bonsai
(MIT); see `NOTICE`. baghban contains no Bonsai code.
