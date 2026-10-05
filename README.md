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
$ baghban check rig/foraging.bonsai

[error] DUPLICATE_OUTPUT  Include 'modules/CameraRecorder.bonsai' #3 > VideoWriter 'camera.avi' #1
    Another writer also writes 'camera.avi' (Include 'modules/CameraRecorder.bonsai' #1 >
    VideoWriter 'camera.avi' #1). Two writers cannot hold the same file: one of them fails,
    or they overwrite each other. This is common when a module containing a writer is
    included twice without giving each copy its own file name.
    fix: Give each writer its own file name; for included modules, externalize FileName and
    set it on each IncludeWorkflow.

[error] SILENT_OVERWRITE  SelectMany 'Trial' #6 > CsvWriter 'trial.csv' #2
    Overwrite=True with Suffix=None inside SelectMany 'Trial': the writer is opened again
    for every element (e.g. every trial), and each time it replaces 'trial.csv'. Only the
    last element's data survives the session.
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
| `SILENT_OVERWRITE` | error | Will a writer replace data from an earlier run, or from an earlier trial in the same run, without an error? |
| `FAILS_ON_REPEAT` | error | Will a writer inside a per-trial loop raise "file already exists" on trial 2 and end the session? |
| `DUPLICATE_OUTPUT` | error | Do two writers write to the same file? |
| `DANGLING_SUBJECT` | error | Does a `SubscribeSubject` or `MulticastSubject` name a subject that is not declared where it can see it? |
| `DUPLICATE_SUBJECT` | error | Are two subjects with one name declared in the same scope? |
| `MISSING_INCLUDE` | error | Does an `IncludeWorkflow` point at a file that does not exist? |
| `RECURSIVE_INCLUDE` | error | Do workflows include each other in a cycle? |
| `INVALID_INCLUDE` | error | Is an included file not a readable workflow? |
| `DISABLED_WRITER` | warning | Is a writer (or a group holding one) disabled, so nothing is recorded? |
| `UNNAMED_SUBJECT` | error | Does a `SubscribeSubject` without a name feed other nodes? It builds to nothing, so they get no input and Bonsai refuses to build them. (With nothing after it, or for an unnamed `MulticastSubject`: info.) |
| `APPENDS_ACROSS_RUNS` | info | Does every run append to the same file, and repeat the CSV header mid-file? |
| `UNUSED_SUBJECT` | info | Is a subject declared but never subscribed to? |

`SILENT_OVERWRITE` drops to info when the file name is externalized:
launchers commonly set a new name each session (the survey found this
throughout IBL's rigs), and baghban cannot see the launcher.

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

- an include it cannot open (an embedded resource of a NuGet package, or an
  absolute Windows path on a Mac) suspends subject checks in that scope,
  because the include may declare the subject;
- a file name assigned from data at run time (`PropertyMapping`,
  `InputMapping`) is not judged;
- types are not checked, because baghban has no catalogue of what each
  package contains.

These appear as `not checked:` lines under the report.

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
And every finding has been run on the real Bonsai runtime: 13 of 13 cases
behaved as predicted (`confirm/`).

### On published rigs

`survey/` runs baghban over 32 public repositories (Bonsai's own, the Allen
Institute's foraging tasks, SWC's Aeon, IBL's rig, NeuroGears' vestibular VR
and others): 453 entry workflows, 61,915 nodes. Every error was read by
hand, and every real fault against its repository's history. **None of the
29 was a false alarm**: 5 point at real faults (4 distinct problems: a
deleted module still used by documentation examples, a missing include in a
rig, a template that overwrites its data, and a workflow that cannot
build), 22 are correct about files never meant to work alone (documentation
snippets and tutorial steps), and 2 are correct but likely harmless.
Reading the first run's results is also where the module conventions above,
two bugs and one wrong claim came from; see `survey/SURVEY.md`.

---

## Commands

```
baghban check  WORKFLOW|DIR ...      findings; exit 1 on errors (--strict: on warnings too)
baghban show   WORKFLOW              the workflow as a tree
baghban render WORKFLOW [-f html]    draw it: html (default), mermaid, dot
baghban diff   A B                   what changed, by meaning; exit 0 if equivalent
baghban deps   WORKFLOW              assemblies (= packages) and includes it needs
baghban params WORKFLOW              externalized properties and their values
baghban fingerprint WORKFLOW         content hash, stable across re-saves (--fields for daftar)
```

`check` accepts folders. A file that another checked file includes is checked
through its includer, where the subjects and file names it relies on are
defined, rather than on its own. `--exclude GLOB` skips files, e.g.
`--exclude 'docs/*'` for documentation snippets. Every command takes `--resource-root
ASSEMBLY=DIR` to follow embedded-resource includes (`Path="MyPackage:Module.bonsai"`)
into a package's source folder.

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

for node in doc.walk():     # every node, includes expanded
    if node.is_writer:
        print(node.location(), node.properties)

baghban.diff(baghban.load("v1.bonsai"), baghban.load("v2.bonsai")).summary()
baghban.fingerprint(doc)
baghban.mermaid(doc)
```

---

## Provenance, with daftar

A session's data is only as interpretable as the record of the protocol that
produced it, and that protocol is a `.bonsai` file plus its includes plus the
parameter values it ran with. `baghban.manifest_fields` turns that into flat
fields for [daftar](https://pypi.org/project/daftar/):

```
with daftar.track("session-0412", params=baghban.manifest_fields(doc)) as run:
    ...
```

```
$ baghban fingerprint rig_v2/foraging.bonsai --fields
{
  "bonsai.workflow": "examples/rig_v2/foraging.bonsai",
  "bonsai.version": "2.9.0",
  "bonsai.fingerprint": "fc07dd88c5331b2dfeb53671f5e05cd80b03f49e96060cb58a745b1682b600fd",
  "bonsai.param.TrialInterval": "PT12S",
  "bonsai.include.modules/CameraRecorder.bonsai": "ok"
}
```

The fingerprint ignores whitespace, attribute order, namespace prefixes and
the `Version` stamp the editor writes on every save, and changes with every
operator, property value, edge, disabled flag and included file's content.
Two sessions that ran the same protocol then diff as identical in daftar,
even when someone re-saved the file in between.

---

## Try it

```
python examples/demo.py
```

Shows, checks, fixes, diffs and fingerprints the example rig, and writes
`examples/rig_v1.html`.

## Status

Research prototype, honestly labelled.

- On 453 published workflows, no error was a false alarm (`survey/SURVEY.md`).
  Warnings were sampled, not read in full, and nothing measures what baghban
  misses.
- **Confirmed on the real Bonsai runtime:** `confirm/` runs 13 cases (every
  finding baghban reports about writers and subjects, with a quiet control
  for each) on Bonsai 2.9.1 packages under .NET 8. On macOS all 13 behaved
  as baghban predicts. The first run (8/12) exposed a flaw in the kit and a
  wrong claim about unnamed subjects, both fixed in 0.2.1
  (`confirm/README.md`). Not yet run on Windows, where rigs run.
- Includes into packages from other repositories (BonVision,
  AllenNeuralDynamics.Core, Bonsai.Harp, ...) are reported as not checked,
  unless you point `--resource-root` at the package source. This is the
  largest gap in coverage (`ROADMAP.md`, item 3).
- Timing problems (unbounded `Zip` queues, timestamps taken after heavy
  processing) need stream rates the XML rarely states, and are not checked.

## Development

```
pip install -e ".[dev]"
pytest -q                         # 134 tests, no network, no .NET
python confirm/confirm.py         # needs .NET 8: confirm findings with real Bonsai
                                  #   (install and troubleshooting: confirm/README.md)
python survey/run_survey.py DIR   # clone and check the published repositories
```

## Licence

Apache 2.0. `tests/data/bonsai_upstream` contains test workflows from Bonsai
(MIT); see `NOTICE`. baghban contains no Bonsai code.
