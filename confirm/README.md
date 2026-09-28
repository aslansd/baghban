# Confirming findings with the real Bonsai runtime

Roadmap item 1. baghban's findings are grounded in Bonsai's source; this
kit checks them against Bonsai's *behaviour*. For each of 12 cases it asks
baghban for a prediction, runs the workflow with the released Bonsai
packages, and inspects exit codes and the files left on disk.

## On a Mac

```
brew install dotnet                  # .NET 8 SDK or later; Apple Silicon is fine
pip install -e ".[dev]"              # from the baghban folder
python confirm/confirm.py
```

The first run builds `runner/` (downloads `Bonsai.System` 2.9.x from NuGet)
and takes a minute; each case then runs in its own temporary folder. Expected
ending:

```
12/12 confirmed. Details: confirm/results.json
```

`--keep` leaves the run folders in place so you can open the files;
`--dry-run` checks only baghban's predictions and needs no .NET.

## Why a runner instead of Bonsai.Player

`Bonsai.Player` does the same thing (deserialize, build, run) but references
only `Bonsai.Core`, and finds other packages through a `Bonsai.config` in its
own install folder. The writers under test live in `Bonsai.System`, so
`runner/` is the Player's `Program.cs` with that package referenced
directly. One change: it awaits `LastOrDefaultAsync()`, so a workflow that
completes without values is not reported as a failure.

## The cases

| Case | baghban says | Confirmed when |
| --- | --- | --- |
| `overwrite_across_runs` | `SILENT_OVERWRITE` | after two runs there is one file, holding only run 2 |
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
| `unnamed_subscribe` | `UNNAMED_SUBJECT` | Bonsai builds and runs it, and nothing is written |

The last case checks a correction from the survey: an unnamed
`SubscribeSubject` is not a build error.

## If a case says NO

Keep the folders (`--keep`) and look at what Bonsai actually did. A NO means
baghban's model of Bonsai is wrong somewhere, which is exactly what this is
for: fix the check (or the claim in its message), add the case to
`tests/test_confirm_harness.py`, and record it in the CHANGELOG.

The harness's own judgement of outcomes is unit-tested with simulated runs
(`tests/test_confirm_harness.py`); it has not yet been run against real
Bonsai, because the machine it was written on could not install .NET.
