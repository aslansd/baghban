"""Roadmap item 4: confirm baghban's reading of a launcher's --property values.

A launcher starts a rig with ``Bonsai.exe rig.bonsai -p:Stim.Contrast=0.5``,
and provenance records those values (``baghban.provenance``). That record is
only worth keeping if baghban sends each value where Bonsai does. For each
case this script asks baghban (``set_properties``, then ``outputs``) either
which files the session will write, or which name Bonsai will refuse; then
it runs the workflow with the real Bonsai runtime, applying the values as
Bonsai.exe does (runner/: build, ``SetWorkflowProperty`` for each, run), and
compares. Every value here is a CsvWriter's file name, so where it went is
visible on disk.

    python confirm/confirm_properties.py             # needs the .NET 8 SDK
    python confirm/confirm_properties.py --dry-run   # predictions only, no .NET

Writes confirm/properties-results.json. Each case runs in its own empty
folder (the working directory), with the include files it needs.
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

import baghban

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from confirm import HEAD, SOURCE, TAIL, build_runner  # noqa: E402

# Bonsai's exception for each way baghban says a name is refused
# (SetWorkflowProperty: KeyNotFoundException when nothing matches,
# InvalidOperationException when two nested workflows share the name)
REFUSALS = {"unknown": "KeyNotFoundException", "ambiguous": "InvalidOperationException",
            "invalid": "ArgumentException"}


# ----------------------------------------------------------------------------- building blocks

def csv(name: str) -> str:
    # Overwrite: a named SelectMany below runs its writer once per element
    return (f'<Expression xsi:type="io:CsvWriter"><io:FileName>{name}</io:FileName>'
            '<io:Append>false</io:Append><io:Overwrite>true</io:Overwrite>'
            '<io:Suffix>None</io:Suffix><io:IncludeHeader>false</io:IncludeHeader></Expression>')


def mapping(prop: str, display: str | None = None) -> str:
    d = f' DisplayName="{display}"' if display else ""
    return f'<Expression xsi:type="ExternalizedMapping"><Property Name="{prop}"{d} /></Expression>'


def edges(*es) -> str:
    return "".join(f'<Edge From="{a}" To="{b}" Label="{l}" />' for a, b, l in es)


def inner(nodes: str, es) -> str:
    return f"<Workflow><Nodes>{nodes}</Nodes><Edges>{edges(*es)}</Edges></Workflow>"


INPUT = '<Expression xsi:type="WorkflowInput"><Name>Source1</Name></Expression>'
OUTPUT = '<Expression xsi:type="WorkflowOutput" />'


def writer_body(default: str, display: str = "Log") -> str:
    """input -> CsvWriter -> output, its FileName exposed as ``display``."""
    return inner(INPUT + mapping("FileName", display) + csv(default) + OUTPUT,
                 [(0, 2, "Source1"), (1, 2, "Source2"), (2, 3, "Source1")])


def group(name: str, body: str, disabled: bool = False) -> str:
    if disabled:
        return (f'<Expression xsi:type="Disable"><Builder xsi:type="GroupWorkflow">'
                f'<Name>{name}</Name>{body}</Builder></Expression>')
    return f'<Expression xsi:type="GroupWorkflow"><Name>{name}</Name>{body}</Expression>'


def include(path: str, **values) -> str:
    body = "".join(f"<{k}>{v}</{k}>" for k, v in values.items())
    return f'<Expression xsi:type="IncludeWorkflow" Path="{path}">{body}</Expression>'


def top(nodes: str, *es) -> str:
    """The source chain (Timer -> Take -> Timestamp, nodes 0-2), then ``nodes``."""
    return HEAD + (f"<Nodes>{SOURCE}{nodes}</Nodes>"
                   f"<Edges>{edges((0, 1, 'Source1'), (1, 2, 'Source1'), *es)}</Edges>") + TAIL


def module(nodes: str, *es) -> str:
    return HEAD + f"<Nodes>{nodes}</Nodes><Edges>{edges(*es)}</Edges>" + TAIL


# iblrig's shape (passiveChoiceWorld: Stim.ReceptiveFieldMappingStim.FileNameRFMapStim):
# the included file exposes FileNameRF, which goes into a group holding the writer.
RF_MODULE = module(INPUT + mapping("FileNameRF") + group("Noise", writer_body("noise.csv", "FileNameRF"))
                   + OUTPUT, (0, 2, "Source1"), (1, 2, "Source2"), (2, 3, "Source1"))

RF_GROUP = group("RF", inner(INPUT + mapping("FileNameRF")
                             + include("RF.bonsai", FileNameRF="saved.csv") + OUTPUT,
                             [(0, 2, "Source1"), (1, 2, "Source2"), (2, 3, "Source1")]))


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
    properties: dict
    expect: tuple  # ("writes", [files]) or ("refuses", exception name)
    files: dict = field(default_factory=dict)  # extra files: name -> text
    note: str = ""
    prediction: tuple = ()

    def observe(self, run: Run) -> tuple:
        kind, what = self.prediction or self.expect
        written = sorted(k for k in run.files if k.endswith(".csv"))
        if kind == "writes":
            full = all(len(run.files[k].strip().splitlines()) >= 1 for k in written)
            ok = run.code == 0 and written == what and full
            happened = (f"wrote {', '.join(written) or 'nothing'}" if run.code == 0
                        else f"failed: {run.error}")
            return ok, happened
        ok = run.code == 1 and run.error.startswith(what)
        return ok, (f"refused: {run.error}" if run.code else f"ran, wrote {', '.join(written)}")


CASES = [
    Case("top_level", top(mapping("FileName", "Out") + csv("default.csv"),
                          (2, 4, "Source1"), (3, 4, "Source2")),
         {"Out": "a.csv"}, ("writes", ["a.csv"])),
    Case("through_a_group", top(group("Rec", writer_body("default.csv")), (2, 3, "Source1")),
         {"Rec.Log": "b.csv"}, ("writes", ["b.csv"])),
    Case("through_a_named_selectmany",
         top('<Expression xsi:type="rx:SelectMany"><Name>Trial</Name>'
             f'{writer_body("default.csv")}</Expression>', (2, 3, "Source1")),
         {"Trial.Log": "e.csv"}, ("writes", ["e.csv"]),
         note="any named nested workflow, not only groups"),
    Case("groups_then_include_then_group",
         top(group("Stim", inner(INPUT + RF_GROUP + OUTPUT, [(0, 1, "Source1"), (1, 2, "Source1")])),
             (2, 3, "Source1")),
         {"Stim.RF.FileNameRF": "c.csv"}, ("writes", ["c.csv"]), files={"RF.bonsai": RF_MODULE},
         note="iblrig's Stim.ReceptiveFieldMappingStim.FileNameRFMapStim, in miniature"),
    Case("include_value_reaches_group", top(include("RF.bonsai", FileNameRF="left.csv"),
                                            (2, 3, "Source1")),
         {}, ("writes", ["left.csv"]), files={"RF.bonsai": RF_MODULE},
         note="no --property: the value saved on the include; baghban 0.3.0 predicted noise.csv"),
    Case("first_of_two_same_names",
         top(mapping("FileName", "Out") + csv("w1.csv") + mapping("FileName", "Out") + csv("w2.csv"),
             (2, 4, "Source1"), (3, 4, "Source2"), (2, 6, "Source1"), (5, 6, "Source2")),
         {"Out": "z.csv"}, ("writes", ["w2.csv", "z.csv"]),
         note="PropertyDescriptorCollection.Find returns the first"),
    Case("unknown_name", top(mapping("FileName", "Out") + csv("default.csv"),
                             (2, 4, "Source1"), (3, 4, "Source2")),
         {"Nope": "x.csv"}, ("refuses", "KeyNotFoundException")),
    Case("ambiguous_group", top(group("Rec", writer_body("r1.csv")) + group("Rec", writer_body("r2.csv")),
                                (2, 3, "Source1"), (2, 4, "Source1")),
         {"Rec.Log": "x.csv"}, ("refuses", "InvalidOperationException")),
    Case("disabled_group", top(group("Off", writer_body("off.csv"), disabled=True), (2, 3, "Source1")),
         {"Off.Log": "x.csv"}, ("refuses", "KeyNotFoundException"),
         note="a disabled node is a DisableBuilder, not a workflow"),
    Case("include_by_name", top(include("RF.bonsai", FileNameRF="saved.csv"), (2, 3, "Source1")),
         {"RF.FileNameRF": "x.csv"}, ("refuses", "KeyNotFoundException"), files={"RF.bonsai": RF_MODULE},
         note="an include is not a WorkflowExpressionBuilder: reached only through a mapping"),
]


def predict(case: Case, folder: Path) -> tuple:
    """What baghban says: the files written, or the exception Bonsai raises."""
    for name, text in case.files.items():
        (folder / name).write_text(text, encoding="utf-8")
    (folder / "workflow.bonsai").write_text(case.xml, encoding="utf-8")
    doc = baghban.load(folder / "workflow.bonsai", packages=False)
    for a in baghban.set_properties(doc, case.properties):
        if a.status != "ok":
            return ("refuses", REFUSALS[a.status])
    return ("writes", sorted({o["path"] for o in baghban.outputs(doc)}))


def run_once(dll: Path, folder: Path, properties: dict) -> Run:
    args = [f"{k}={v}" for k, v in properties.items()]
    proc = subprocess.run(["dotnet", str(dll), "workflow.bonsai", *args], cwd=folder,
                          capture_output=True, text=True, timeout=60)
    files = {p.name: p.read_text(errors="replace") for p in folder.iterdir()
             if p.is_file() and p.suffix == ".csv"}
    return Run(proc.returncode, proc.stderr.strip(), files)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="only check baghban's predictions")
    p.add_argument("--keep", action="store_true", help="keep the run folders for inspection")
    args = p.parse_args(argv)

    root = Path(tempfile.mkdtemp(prefix="baghban-properties-"))
    bad = 0
    for case in CASES:
        folder = root / case.name
        folder.mkdir()
        case.prediction = predict(case, folder)
        if case.prediction != case.expect:
            bad += 1
            print(f"PREDICTION MISMATCH {case.name}: baghban says {case.prediction}, "
                  f"case expects {case.expect}")
    if args.dry_run:
        shutil.rmtree(root, ignore_errors=True)
        print(f"{len(CASES) - bad}/{len(CASES)} predictions as expected (dry run).")
        return 1 if bad else 0

    dll = build_runner()
    results, confirmed = [], 0
    print(f"\n{'case':<34} {'baghban':<34} {'observed':<9} what happened")
    for case in CASES:
        run = run_once(dll, root / case.name, case.properties)
        ok, what = case.observe(run)
        confirmed += ok
        kind, detail = case.prediction
        label = f"writes {', '.join(detail)}" if kind == "writes" else f"refused ({detail})"
        print(f"{case.name:<34} {label:<34} {'yes' if ok else 'NO':<9} {what}")
        results.append({"case": case.name, "properties": case.properties,
                        "baghban": list(case.prediction), "confirmed": ok, "observed": what,
                        "note": case.note, "exit": run.code, "error": run.error,
                        "files": sorted(run.files)})
    (HERE / "properties-results.json").write_text(json.dumps(results, indent=2))
    print(f"\n{confirmed}/{len(CASES)} confirmed. Details: {HERE / 'properties-results.json'}")
    if args.keep:
        print(f"run folders kept in {root}")
    else:
        shutil.rmtree(root, ignore_errors=True)
    return 0 if confirmed == len(CASES) and not bad else 1


if __name__ == "__main__":
    sys.exit(main())
