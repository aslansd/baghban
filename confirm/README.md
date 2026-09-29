# Confirming findings with the real Bonsai runtime

baghban's findings are grounded in Bonsai's *source*. This kit checks them
against Bonsai's *behaviour*: for each of 13 small workflows it asks baghban
for a prediction, runs the workflow with the released Bonsai packages on
.NET 8, and inspects exit codes and the files left on disk. A row says `yes`
when what Bonsai did matches what baghban said, `NO` when it does not.

A `NO` is not a failure of the kit. It means baghban's model of Bonsai (or
the kit itself) is wrong somewhere, which is exactly what the kit is for: the
first run on a Mac produced four, and each one led to a fix (see
[Results](#results)).

## 1. Install .NET 8

The kit needs the .NET 8 SDK (8.0.x). It works on Intel and Apple Silicon
Macs, and on Linux.

### Recommended: Microsoft's install script

No administrator password, no Homebrew, installs into `~/.dotnet`:

```
curl -sSL https://dot.net/v1/dotnet-install.sh -o ~/dotnet-install.sh
bash ~/dotnet-install.sh --channel 8.0
```

It ends with `Installation finished successfully.` Then put .NET on your
PATH for every new terminal:

```
echo 'export DOTNET_ROOT="$HOME/.dotnet"' >> ~/.zshrc
echo 'export PATH="$HOME/.dotnet:$PATH"' >> ~/.zshrc
```

Open a **new** terminal window (⌘N) and check:

```
dotnet --list-sdks
```

It should print a line starting with `8.0.`, e.g.
`8.0.425 [/Users/you/.dotnet/sdk]`.

### Why not `brew install dotnet`

On an Intel Mac, Homebrew no longer ships prebuilt packages (Intel macOS is a
Tier 3 platform for Homebrew since September 2026), so `brew install dotnet`
downloads the .NET *source* (about 300 MB) and compiles it, which takes
hours. It also installs the newest .NET (10), not 8. If you started it,
stop it:

```
pgrep -fl "brew.*dotnet"      # lists the process numbers
kill <number> <number>
```

Messages about `Permission denied … ghostscript` or `A brew install dotnet
process has already locked …` come from that Homebrew run and can be
ignored once it is stopped.

If you already have a newer .NET (9, 10, …) and not 8, the kit still runs:
the runner is marked `RollForward=Major`.

## 2. Set up baghban

From the baghban folder (quote the path if it contains spaces):

```
cd "/path/to/baghban"
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                          # 134 passed
```

**Order matters: .NET before the virtual environment.** A virtual
environment saves your PATH when it is activated and restores that copy when
it is activated again. If the window was opened before .NET was added to
`~/.zshrc`, activating (again) removes `~/.dotnet` from the PATH, and
`dotnet --list-sdks` says `command not found` even though .NET is installed.
Either open a new terminal window and activate afterwards, or add .NET to
the current window after activating:

```
export DOTNET_ROOT="$HOME/.dotnet"
export PATH="$HOME/.dotnet:$PATH"
```

## 3. Run the kit

```
dotnet --list-sdks                 # must print 8.0.x (or newer) in this window
python confirm/confirm.py
```

What happens:

1. baghban predicts each case (instant). A prediction that differs from what
   the case expects is printed as `PREDICTION MISMATCH`.
2. `dotnet build` compiles `runner/` into `runner/bin/confirm/`. The first
   time, it downloads `Bonsai.System` 2.9.x and `Bonsai.Core` from NuGet and
   prints .NET's welcome and telemetry notice (set
   `DOTNET_CLI_TELEMETRY_OPTOUT=1` to opt out). This takes a minute; later
   runs take a few seconds.
3. Each case runs in its own empty temporary folder, once or twice. Each run
   waits two seconds after the workflow completes, so Bonsai's background
   file writers can close their files (see [Results](#results)). The whole
   kit takes under a minute.
4. A table prints, and the details go to `confirm/results.json`.

Options:

```
python confirm/confirm.py --keep       # keep the run folders to open the files yourself
python confirm/confirm.py --dry-run    # predictions only, no .NET needed
```

## 4. Read the output

```
case                               baghban                observed   what happened
overwrite_across_runs              SILENT_OVERWRITE       yes        run 2 exit 0; 1 file(s) after 2 runs; rows per run [3] then [3]; content replaced: True
overwrite_with_timestamp_suffix    (quiet)                yes        run 2 exit 0; 2 file(s) after 2 runs
...
13/13 confirmed. Details: .../confirm/results.json
```

- **case**: the workflow (table below).
- **baghban**: what baghban reports for it; `(quiet)` means no finding.
  Quiet cases are the controls: they show nothing bad happens when baghban
  says nothing.
- **observed**: `yes` if Bonsai behaved as predicted, `NO` if not.
- **what happened**: exit codes, Bonsai's error message, files and rows.

`results.json` holds the same per case, with each run's exit code, full
error message and file list. Send it along when reporting a `NO`.

## The cases

| Case | baghban says | Confirmed when |
| --- | --- | --- |
| `overwrite_across_runs` | `SILENT_OVERWRITE` | after two runs there is one file, holding only run 2's rows |
| `overwrite_with_timestamp_suffix` | quiet | after two runs there are two files |
| `no_overwrite_second_run_stops` | quiet | run 2 fails with "already exists" and run 1's data is intact |
| `overwrite_per_element` | `SILENT_OVERWRITE` | three elements through a `SelectMany` leave one row |
| `writer_after_loop` | quiet | the same, with the writer after the loop, leaves three rows |
| `fails_on_repeat` | `FAILS_ON_REPEAT` | the run fails on the second element |
| `duplicate_output` | `DUPLICATE_OUTPUT` | the run fails, or fewer than all rows survive |
| `distinct_outputs` | quiet | two files, three rows each |
| `disabled_writer` | `DISABLED_WRITER` | the run succeeds and writes no file |
| `appends_across_runs` | `APPENDS_ACROSS_RUNS` | after two runs, one file with six rows |
| `dangling_subject` | `DANGLING_SUBJECT` | Bonsai refuses to build it |
| `unnamed_subscribe` | `UNNAMED_SUBJECT` (error) | Bonsai refuses to build the node after it |
| `unnamed_subscribe_alone` | `UNNAMED_SUBJECT` (info) | it builds, and the rest of the workflow runs |

Every workflow is three timer ticks, 100 ms apart, through `Take(3)` and
`Timestamp`, so every case ends on its own and every run writes different
values.

## Why a runner instead of Bonsai.Player

`Bonsai.Player` does the same thing (deserialize, build, run) but references
only `Bonsai.Core`, and finds other packages through a `Bonsai.config` in its
own install folder. The writers under test live in `Bonsai.System`, so
`runner/` is the Player's `Program.cs` with that package referenced
directly. Two changes: it awaits `LastOrDefaultAsync()`, so a workflow that
completes without values is not reported as a failure, and it waits two
seconds before exiting (next section).

## Results

### First run: macOS 26, Intel, .NET 8.0.425, Bonsai 2.9 packages (29 Sep 2026)

**8/12 confirmed.** The eight confirmations include every error baghban
reports for writers inside loops, duplicate outputs and dangling subjects,
with Bonsai's own messages (`IOException: The file 'trial.csv' already
exists.`, `ArgumentException: The specified variable 'Nope' was not found in
the current build context.`), and all quiet controls that completed.

The four `NO`s, and what they taught:

- **`overwrite_across_runs`, `writer_after_loop`, `appends_across_runs`: a
  bug in the kit.** The files existed but were empty. Bonsai's file writers
  write and close on a background thread (`EventLoopScheduler`, in
  `Bonsai.System/IO/WriterDisposable.cs`); when the workflow completes,
  closing is only scheduled. The runner exited at once and the process was
  killed before the writers flushed. (The editor never exits there, which is
  why rigs do not lose data this way.) Fixed: the runner now waits two
  seconds, and the overwrite judgement requires real rows in both runs,
  since two empty files are also "unchanged".
- **`unnamed_subscribe`: a wrong claim in baghban.** baghban 0.2.0 said an
  unnamed `SubscribeSubject` builds fine and silently produces nothing.
  Bonsai refused to build: `Unsupported number of arguments. This node
  requires at least 1 input connection(s).` The unnamed subscriber builds to
  an empty expression, and Bonsai does not pass empty expressions on
  (`ExpressionBuilderGraphExtensions.cs`), so the `CsvWriter` after it had
  no input. Fixed: `UNNAMED_SUBJECT` is an error when nodes are connected
  after it, info when nothing is. This also re-classified a survey finding:
  a Berkeley rig workflow has an unnamed subscriber feeding a
  `PropertyMapping`, so it cannot build (`survey/SURVEY.md`).

### Second run

Pending: re-run with the fixed runner and record the result here. Expected:
13/13.

## If a case says NO

1. Re-run with `--keep` and open the files in the printed folder.
2. Read the error in `results.json` and find the behaviour in the Bonsai
   source.
3. Decide whether baghban's check (or the claim in its message) or the kit
   is wrong, fix it, add the case to `tests/test_confirm_harness.py` and
   `tests/test_checks.py`, and record it here and in the CHANGELOG.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `dotnet not found` from `confirm.py`, or `zsh: command not found: dotnet` | .NET is not on this window's PATH: open a new window, or run the two `export` lines above after activating the virtual environment |
| `dotnet --list-sdks` works in one window but not another | the other window was opened, or its virtual environment activated, before `~/.zshrc` was changed |
| `brew install dotnet` compiles for hours | Intel Mac: use the install script instead and stop the Homebrew process |
| `You must install or update .NET to run this application` | only a newer .NET is installed and an old copy of the runner is used: delete `confirm/runner/bin` and `confirm/runner/obj` and re-run |
| `NU1101` / cannot find package `Bonsai.System` | no internet access to nuget.org during the first build |
| Every case `NO` with empty files | the runner exited before writers flushed: make sure `runner/Program.cs` has the `Task.Delay` after the workflow completes |
