"""Roadmap item 1: confirm baghban's findings by running the workflows.

For each case this script writes a small workflow, asks baghban what it
predicts, runs the workflow with the real Bonsai runtime (runner/, released
NuGet packages, .NET 8), then inspects exit codes and the files on disk. A
finding is *confirmed* when what happened matches what baghban said; each
quiet twin must show that nothing bad happened.

    python confirm/confirm.py             # needs the .NET 8 SDK (brew install dotnet)
    python confirm/confirm.py --dry-run   # predictions only, no .NET

Writes confirm/results.json. Each run happens in its own empty folder, which
is the working directory, so relative file names land there.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import baghban

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "runner"

HEAD = """<?xml version="1.0" encoding="utf-8"?>
<WorkflowBuilder Version="2.9.0"
                 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                 xmlns:rx="clr-namespace:Bonsai.Reactive;assembly=Bonsai.Core"
                 xmlns:io="clr-namespace:Bonsai.IO;assembly=Bonsai.System"
                 xmlns="https://bonsai-rx.org/2018/workflow">
  <Workflow>
"""
TAIL = "  </Workflow>\n</WorkflowBuilder>\n"

# three elements, 100 ms apart, then completion: every case ends by itself
SOURCE = """<Expression xsi:type="Combinator"><Combinator xsi:type="rx:Timer">
<rx:DueTime>PT0S</rx:DueTime><rx:Period>PT0.1S</rx:Period></Combinator></Expression>
<Expression xsi:type="Combinator"><Combinator xsi:type="rx:Take"><rx:Count>3</rx:Count>
</Combinator></Expression>
<Expression xsi:type="Combinator"><Combinator xsi:type="rx:Timestamp" /></Expression>
"""


def csv(name, overwrite=False, suffix="None", append=False):
    return (f'<Expression xsi:type="io:CsvWriter"><io:FileName>{name}</io:FileName>'
            f'<io:Append>{str(append).lower()}</io:Append>'
            f'<io:Overwrite>{str(overwrite).lower()}</io:Overwrite>'
            f'<io:Suffix>{suffix}</io:Suffix><io:IncludeHeader>false</io:IncludeHeader>'
            '</Expression>')


def disabled_csv(name):
    inner = csv(name).replace('<Expression xsi:type="io:CsvWriter">', "").replace("</Expression>", "")
    return f'<Expression xsi:type="Disable"><Builder xsi:type="io:CsvWriter">{inner}</Builder></Expression>'


def doc(nodes: str, edges) -> str:
    e = "".join(f'<Edge From="{a}" To="{b}" Label="Source1" />' for a, b in edges)
    return HEAD + f"<Nodes>{nodes}</Nodes><Edges>{e}</Edges>" + TAIL


CHAIN = [(0, 1), (1, 2)]  # Timer -> Take -> Timestamp


def linear(*writers) -> str:
    """source chain, then each writer attached to the Timestamp node (index 2)."""
    return doc(SOURCE + "".join(writers), CHAIN + [(2, 3 + i) for i in range(len(writers))])


def per_element(writer: str) -> str:
    inner = ('<Workflow><Nodes><Expression xsi:type="WorkflowInput"><Name>Source1</Name>'
             f'</Expression>{writer}<Expression xsi:type="WorkflowOutput" /></Nodes>'
             '<Edges><Edge From="0" To="1" Label="Source1" /><Edge From="1" To="2" '
             'Label="Source1" /></Edges></Workflow>')
    return doc(SOURCE + f'<Expression xsi:type="rx:SelectMany">{inner}</Expression>',
               CHAIN + [(2, 3)])


def after_loop(writer: str) -> str:
    inner = ('<Workflow><Nodes><Expression xsi:type="WorkflowInput"><Name>Source1</Name>'
             '</Expression><Expression xsi:type="WorkflowOutput" /></Nodes><Edges>'
             '<Edge From="0" To="1" Label="Source1" /></Edges></Workflow>')
    return doc(SOURCE + f'<Expression xsi:type="rx:SelectMany">{inner}</Expression>' + writer,
               CHAIN + [(2, 3), (3, 4)])


def subscriber(name: str | None) -> str:
    body = f"<Name>{name}</Name>" if name else ""
    return doc(f'<Expression xsi:type="SubscribeSubject">{body}</Expression>' + csv("out.csv"),
               [(0, 1)])


# ----------------------------------------------------------------------------- cases

@dataclass
class Run:
    code: int
    error: str
    files: dict  # name -> text


@dataclass
class Case:
    name: str
    xml: str
    predicts: list  # baghban finding codes expected (empty: quiet twin)
    runs: int
    observe: Callable[[list], tuple]  # [Run] -> (confirmed, what happened)
    note: str = ""
    prediction: list = field(default_factory=list)


def lines(text: str) -> int:
    return len([l for l in text.splitlines() if l.strip()])


def csvs(run: Run) -> dict:
    return {k: v for k, v in run.files.items() if k.endswith(".csv")}


def replaced_across_runs(rs):
    a, b = csvs(rs[0]), csvs(rs[1])
    ok = rs[1].code == 0 and len(b) == 1 and a != b and lines(next(iter(b.values()))) == 3
    return ok, f"run 2 exit {rs[1].code}; {len(b)} file(s) after 2 runs; content replaced: {a != b}"


def kept_both_runs(rs):
    b = csvs(rs[1])
    ok = rs[1].code == 0 and len(b) == 2
    return ok, f"run 2 exit {rs[1].code}; {len(b)} file(s) after 2 runs"


def second_run_stops(rs):
    ok = rs[1].code != 0 and "exists" in rs[1].error and csvs(rs[0]) == csvs(rs[1])
    return ok, f"run 2 exit {rs[1].code} ({rs[1].error[:70]}); data kept: {csvs(rs[0]) == csvs(rs[1])}"


def only_last_element(rs):
    f = csvs(rs[0])
    n = lines(next(iter(f.values()))) if f else -1
    return rs[0].code == 0 and n == 1, f"exit {rs[0].code}; lines in file: {n} of 3 elements"


def all_elements(rs):
    f = csvs(rs[0])
    n = lines(next(iter(f.values()))) if f else -1
    return rs[0].code == 0 and n == 3, f"exit {rs[0].code}; lines in file: {n} of 3 elements"


def fails_mid_session(rs):
    ok = rs[0].code != 0 and ("exists" in rs[0].error or "used by another" in rs[0].error)
    return ok, f"exit {rs[0].code} ({rs[0].error[:70]})"


def duplicate_conflict(rs):
    f = csvs(rs[0])
    total = sum(lines(t) for t in f.values())
    ok = rs[0].code != 0 or total < 6
    return ok, f"exit {rs[0].code} ({rs[0].error[:60]}); {len(f)} file(s), {total} of 6 rows"


def two_clean_files(rs):
    f = csvs(rs[0])
    ok = rs[0].code == 0 and len(f) == 2 and all(lines(t) == 3 for t in f.values())
    return ok, f"exit {rs[0].code}; {len(f)} file(s) with {[lines(t) for t in f.values()]} rows"


def nothing_written(rs):
    f = csvs(rs[0])
    return rs[0].code == 0 and not f, f"exit {rs[0].code}; files: {sorted(f) or 'none'}"


def accumulated(rs):
    f = csvs(rs[1])
    n = lines(next(iter(f.values()))) if f else -1
    return rs[1].code == 0 and n == 6, f"after 2 runs: {len(f)} file, {n} rows (3 per run)"


def build_fails(rs):
    ok = rs[0].code != 0
    return ok, f"exit {rs[0].code} ({rs[0].error[:70]})"


def runs_silently_empty(rs):
    f = csvs(rs[0])
    n = sum(lines(t) for t in f.values())
    return rs[0].code == 0 and n == 0, f"exit {rs[0].code}; rows written: {n}"


CASES = [
    Case("overwrite_across_runs", linear(csv("data.csv", overwrite=True)), ["SILENT_OVERWRITE"], 2,
         replaced_across_runs),
    Case("overwrite_with_timestamp_suffix", linear(csv("data.csv", overwrite=True, suffix="Timestamp")),
         [], 2, kept_both_runs),
    Case("no_overwrite_second_run_stops", linear(csv("data.csv")), [], 2, second_run_stops,
         note="loud failure, no data lost: why baghban stays quiet here"),
    Case("overwrite_per_element", per_element(csv("trial.csv", overwrite=True)), ["SILENT_OVERWRITE"],
         1, only_last_element),
    Case("writer_after_loop", after_loop(csv("trials.csv")), [], 1, all_elements),
    Case("fails_on_repeat", per_element(csv("trial.csv")), ["FAILS_ON_REPEAT"], 1, fails_mid_session),
    Case("duplicate_output", linear(csv("same.csv"), csv("same.csv")), ["DUPLICATE_OUTPUT"], 1,
         duplicate_conflict),
    Case("distinct_outputs", linear(csv("a.csv"), csv("b.csv")), [], 1, two_clean_files),
    Case("disabled_writer", linear(disabled_csv("data.csv")), ["DISABLED_WRITER"], 1, nothing_written),
    Case("appends_across_runs", linear(csv("data.csv", append=True)), ["APPENDS_ACROSS_RUNS"], 2,
         accumulated),
    Case("dangling_subject", subscriber("Nope"), ["DANGLING_SUBJECT"], 1, build_fails),
    Case("unnamed_subscribe", subscriber(None), ["UNNAMED_SUBJECT"], 1, runs_silently_empty,
         note="builds and runs, but produces nothing"),
]


# ----------------------------------------------------------------------------- running

def build_runner() -> Path:
    if shutil.which("dotnet") is None:
        sys.exit("dotnet not found: install the .NET 8 SDK (on a Mac: brew install dotnet)")
    out = HERE / "runner" / "bin" / "confirm"
    subprocess.run(["dotnet", "build", str(RUNNER), "-c", "Release", "-o", str(out)], check=True)
    dll = out / "BaghbanRunner.dll"
    if not dll.exists():
        sys.exit(f"build did not produce {dll}")
    return dll


def run_once(dll: Path, folder: Path) -> Run:
    proc = subprocess.run(["dotnet", str(dll), "workflow.bonsai"], cwd=folder,
                          capture_output=True, text=True, timeout=60)
    files = {p.name: p.read_text(errors="replace") for p in folder.iterdir()
             if p.is_file() and p.name != "workflow.bonsai"}
    return Run(proc.returncode, proc.stderr.strip(), files)


def predict(case: Case) -> list:
    report = baghban.check(baghban.loads(case.xml))
    return sorted({f.code for f in report.findings if f.code != "UNUSED_SUBJECT"})


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="only check baghban's predictions")
    p.add_argument("--keep", action="store_true", help="keep the run folders for inspection")
    args = p.parse_args(argv)

    bad_predictions = 0
    for case in CASES:
        case.prediction = predict(case)
        if case.prediction != sorted(case.predicts):
            bad_predictions += 1
            print(f"PREDICTION MISMATCH {case.name}: baghban says {case.prediction}, "
                  f"case expects {case.predicts}")
    if args.dry_run:
        print(f"{len(CASES) - bad_predictions}/{len(CASES)} predictions as expected (dry run).")
        return 1 if bad_predictions else 0

    dll = build_runner()
    results, confirmed = [], 0
    root = Path(tempfile.mkdtemp(prefix="baghban-confirm-"))
    print(f"\n{'case':<34} {'baghban':<22} {'observed':<10} what happened")
    for case in CASES:
        folder = root / case.name
        folder.mkdir()
        (folder / "workflow.bonsai").write_text(case.xml, encoding="utf-8")
        runs = [run_once(dll, folder) for _ in range(case.runs)]
        ok, what = case.observe(runs)
        confirmed += ok
        label = ", ".join(case.prediction) or "(quiet)"
        print(f"{case.name:<34} {label:<22} {'yes' if ok else 'NO':<10} {what}")
        results.append({"case": case.name, "baghban": case.prediction, "confirmed": ok,
                        "observed": what, "note": case.note,
                        "runs": [{"exit": r.code, "error": r.error, "files": sorted(r.files)}
                                 for r in runs]})
    (HERE / "results.json").write_text(json.dumps(results, indent=2))
    print(f"\n{confirmed}/{len(CASES)} confirmed. Details: {HERE / 'results.json'}")
    if args.keep:
        print(f"run folders kept in {root}")
    else:
        shutil.rmtree(root, ignore_errors=True)
    return 0 if confirmed == len(CASES) and not bad_predictions else 1


if __name__ == "__main__":
    sys.exit(main())
