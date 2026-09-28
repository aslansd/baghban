"""Static checks: problems a Bonsai workflow has before it is ever run.

Each check reports a problem only when the XML is enough to be sure of it.
When it is not (an include that cannot be opened, a file name computed from
data at run time), the check stays quiet and says what it could not see in
``Report.skipped``, instead of guessing.

Behaviour that the checks rely on, verified in the Bonsai source:

* ``CsvWriter`` and ``FileSink`` (Bonsai.System/IO) open their file when they
  are *subscribed*, check ``File.Exists(path) && !Overwrite`` (and ``!Append``
  for CsvWriter), then create it. ``PathSuffix`` is ``None``, ``FileCount`` or
  ``Timestamp`` (ISO 8601 with 100 ns resolution).
* ``SelectMany``, ``CreateObservable`` and ``WindowWorkflow`` subscribe their
  nested workflow once per input element, so a writer inside one is opened
  once per element: typically once per trial.
* Declaring two subjects with the same name in one build context raises
  "A variable with the specified name already exists" (BuildContext.cs).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from .model import Document, Node, Workflow

SEVERITIES = ("error", "warning", "info")
PIPE_PREFIX = "\\\\.\\pipe\\"

# code -> (severity, one-line description); the README findings table mirrors this.
FINDINGS = {
    "SILENT_OVERWRITE": ("error", "a writer replaces data from an earlier run or trial without warning"),
    "FAILS_ON_REPEAT": ("error", "a writer inside a per-trial loop raises 'file already exists' on the second trial"),
    "DUPLICATE_OUTPUT": ("error", "two writers write to the same file"),
    "DANGLING_SUBJECT": ("error", "a SubscribeSubject/MulticastSubject names a subject that is not declared in scope"),
    "DUPLICATE_SUBJECT": ("error", "two subjects with the same name are declared in one scope"),
    "MISSING_INCLUDE": ("error", "an IncludeWorkflow points at a file that does not exist"),
    "RECURSIVE_INCLUDE": ("error", "workflows include each other in a cycle"),
    "INVALID_INCLUDE": ("error", "an included file is not a readable workflow"),
    "DISABLED_WRITER": ("warning", "a writer is disabled, so nothing is recorded to its file"),
    "UNNAMED_SUBJECT": ("warning", "a SubscribeSubject without a Name silently produces nothing"),
    "APPENDS_ACROSS_RUNS": ("info", "every run appends to the same file"),
    "UNUSED_SUBJECT": ("info", "a subject is declared but nothing subscribes to it"),
}


@dataclass
class Finding:
    code: str
    severity: str
    message: str
    location: str
    file: Optional[str] = None
    node: tuple = ()
    hint: str = ""

    def to_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "message": self.message,
                "location": self.location, "file": self.file, "node": list(self.node),
                "hint": self.hint}


@dataclass
class Report:
    path: Optional[str]
    findings: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    n_nodes: int = 0
    kind: str = "workflow"
    interface: list = field(default_factory=list)

    def by_severity(self, severity: str) -> list:
        return [f for f in self.findings if f.severity == severity]

    @property
    def errors(self) -> list:
        return self.by_severity("error")

    @property
    def warnings(self) -> list:
        return self.by_severity("warning")

    def codes(self) -> list:
        return [f.code for f in self.findings]

    def exit_code(self, strict: bool = False) -> int:
        if self.errors or (strict and self.warnings):
            return 1
        return 0

    def summary(self, show_info: bool = True) -> str:
        lines = []
        for f in self.findings:
            if f.severity == "info" and not show_info:
                continue
            lines.append(f"[{f.severity}] {f.code}  {f.location}")
            where = f"   in {f.file}" if f.file and f.file != self.path else ""
            if where:
                lines.append(where)
            for text in _wrap(f.message):
                lines.append(f"    {text}")
            if f.hint:
                for text in _wrap("fix: " + f.hint):
                    lines.append(f"    {text}")
            lines.append("")
        counts = [f"{len(self.by_severity(s))} {s}{'s' if len(self.by_severity(s)) != 1 else ''}"
                  for s in SEVERITIES]
        if self.kind != "workflow":
            lines.append(f"Checked as {_MODULE_KIND.get(self.kind, 'a module')}: a workflow "
                         "meant to be included, not run on its own.")
        if not self.findings:
            lines.append(f"No findings in {self.n_nodes} nodes.")
        else:
            lines.append(", ".join(counts) + f" in {self.n_nodes} nodes.")
        for note in self.skipped:
            lines.append(f"not checked: {note}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"path": self.path, "kind": self.kind, "nodes": self.n_nodes,
                "interface": list(self.interface),
                "findings": [f.to_dict() for f in self.findings],
                "skipped": list(self.skipped)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def _wrap(text: str, width: int = 88) -> list:
    import textwrap
    return textwrap.wrap(text, width) or [""]


def _bool(value: Optional[str]) -> bool:
    return (value or "").strip().lower() == "true"


def _finding(code: str, node: Node, message: str, hint: str = "",
             severity: Optional[str] = None) -> Finding:
    return Finding(code=code, severity=severity or FINDINGS[code][0], message=message,
                   location=node.location(), file=str(node.file) if node.file else None,
                   node=node.id, hint=hint)


# --------------------------------------------------------------------------- includes

def check_includes(doc: Document, report: Report) -> None:
    for node in doc.walk():
        if not node.is_include or node.include is None or node.is_effectively_disabled():
            continue
        inc = node.include
        if inc.status == "missing":
            report.findings.append(_finding(
                "MISSING_INCLUDE", node,
                f"IncludeWorkflow Path='{inc.path}' cannot be found ({inc.note}). "
                "Bonsai will fail to build the workflow.",
                hint="Include paths are resolved relative to the folder of the top-level "
                     "workflow (the editor's working directory), also for nested includes."))
        elif inc.status == "recursive":
            report.findings.append(_finding(
                "RECURSIVE_INCLUDE", node, f"{inc.note}. Bonsai cannot build a workflow "
                "that includes itself."))
        elif inc.status == "invalid":
            report.findings.append(_finding("INVALID_INCLUDE", node, inc.note))
        elif inc.status == "unresolved":
            report.skipped.append(f"{node.location()}: {inc.note}")


# --------------------------------------------------------------------------- subjects

def _enabled(node: Node) -> bool:
    return not node.is_effectively_disabled()


def check_subjects(doc: Document, report: Report) -> None:
    declared: dict[int, dict[str, list]] = {}
    scopes: dict[int, Workflow] = {}
    opaque: set = set()

    for wf in doc.workflow.workflows():
        scope = wf.scope()
        scopes[id(scope)] = scope
        declared.setdefault(id(scope), {})
        for node in wf.nodes:
            if not _enabled(node):
                continue
            if node.is_subject_declaration and node.name:
                declared[id(scope)].setdefault(node.name, []).append(node)
            if node.is_include and node.include is not None and node.include.status != "ok":
                opaque.add(id(scope))

    def chain(scope: Workflow):
        s: Optional[Workflow] = scope
        while s is not None:
            yield s
            s = s.parent_scope()

    # scopes that contain (at any depth) something baghban could not read
    opaque_within: set = set()
    for sid in opaque:
        for s in chain(scopes[sid]):
            opaque_within.add(id(s))

    for sid, names in declared.items():
        for name, nodes in names.items():
            if len(nodes) > 1:
                first = nodes[0]
                for dup in nodes[1:]:
                    report.findings.append(_finding(
                        "DUPLICATE_SUBJECT", dup,
                        f"Subject '{name}' is already declared in this scope by "
                        f"{first.location()}. Bonsai refuses to build the workflow. "
                        "Groups and included workflows share their parent's scope, so "
                        "declarations inside them count as declarations next to them.",
                        hint="Rename one of them, or move one inside a nested workflow such as "
                             "SelectMany if it is meant to be local."))

    used: set = set()
    skipped_names: set = set()
    interface: list = []
    for node in doc.walk():
        if not node.is_subject_use or not _enabled(node):
            continue
        scope = node.parent.scope()
        if "Name" in node.externalized() and not node.name:
            report.skipped.append(f"{node.location()}: subject name is externalized, set by "
                                  "whoever includes or launches this workflow")
            continue
        if not node.name:
            # Bonsai builds these without error: an unnamed SubscribeSubject becomes an
            # empty sequence, an unnamed MulticastSubject passes values through.
            if node.type.name == "SubscribeSubject":
                report.findings.append(_finding(
                    "UNNAMED_SUBJECT", node,
                    "This SubscribeSubject has no subject Name, so it produces no values: "
                    "everything downstream of it stays silent, without an error.",
                    hint="Pick the subject to subscribe to, or delete the node."))
            else:
                report.findings.append(_finding(
                    "UNNAMED_SUBJECT", node,
                    "This MulticastSubject has no subject Name, so it passes values through "
                    "without sending them to any subject.", severity="info"))
            continue
        target = None
        blind = False
        for s in chain(scope):
            if id(s) in opaque:
                blind = True
            hits = declared.get(id(s), {}).get(node.name)
            if hits:
                target = hits[0]
                break
        if target is not None:
            used.add(id(target))
        elif blind:
            key = (node.name, id(scope))
            if key not in skipped_names:
                skipped_names.add(key)
                report.skipped.append(f"subject '{node.name}' used at {node.location()} may be "
                                      "declared in an include that could not be read")
        else:
            hidden = [d for names in declared.values() for d in names.get(node.name, [])]
            if not hidden and (doc.is_module or "Name" in node.externalized()):
                # a module's undeclared subjects are what it expects from its includer
                if node.name not in interface:
                    interface.append(node.name)
                continue
            if hidden:
                why = (f" A subject with this name is declared at {hidden[0].location()}, but "
                       "that is inside a nested workflow, whose declarations are not visible "
                       "outside it (groups are the exception).")
                hint = "Move the declaration out of the nested workflow, or into a group."
            else:
                why = ""
                hint = _near_miss(node.name, declared)
            report.findings.append(_finding(
                "DANGLING_SUBJECT", node,
                f"No subject named '{node.name}' is declared in this scope or any enclosing "
                f"one, so Bonsai will fail to build the workflow.{why}", hint=hint))

    if interface:
        report.interface = interface
        report.skipped.append(
            f"{_MODULE_KIND.get(doc.kind, 'module')}: expects the including workflow to declare "
            f"subject(s) {', '.join(repr(n) for n in interface)}")

    for sid, names in declared.items():
        if sid in opaque_within or doc.is_module:  # a module's subjects are its outputs
            continue
        for name, nodes in names.items():
            if len(nodes) > 1:
                continue  # already reported as DUPLICATE_SUBJECT
            for decl in nodes:
                if id(decl) not in used and not decl.type.is_core("ResourceSubject"):
                    report.findings.append(_finding(
                        "UNUSED_SUBJECT", decl,
                        f"Subject '{name}' is declared but nothing subscribes to it."))


_MODULE_KIND = {"extension": "Extensions module", "package": "package module"}


def _near_miss(name: str, declared: dict) -> str:
    import difflib
    names = {n for scope in declared.values() for n in scope}
    close = difflib.get_close_matches(name, sorted(names), n=1, cutoff=0.75)
    return f"Did you mean '{close[0]}'?" if close else ""


# --------------------------------------------------------------------------- writers

def _loop_name(node: Node) -> str:
    return f"{node.type.name}" + (f" '{node.name}'" if node.name else "")


def check_writers(doc: Document, report: Report) -> None:
    outputs: dict[str, list] = {}
    for node in doc.walk():
        if not node.is_writer:
            continue
        prop = node.filename_property
        fname = node.properties.get(prop, "") or ""

        if node.is_effectively_disabled():
            why = "is disabled" if node.disabled else "sits inside a disabled node"
            report.findings.append(_finding(
                "DISABLED_WRITER", node,
                f"This {node.type.name} {why}, so nothing will be written to "
                f"'{fname or '(no file name)'}'. Disabling a writer while debugging and "
                "forgetting to re-enable it loses whole sessions without an error.",
                hint="Re-enable it, or delete it if the data is not needed."))
            continue

        if prop in node.mapped():
            report.skipped.append(f"{node.location()}: {prop} is assigned from data at "
                                  "run time")
            continue
        if not fname or fname.startswith(PIPE_PREFIX):
            continue

        suffix = (node.properties.get("Suffix") or "None").strip()
        overwrite = _bool(node.properties.get("Overwrite"))
        append = _bool(node.properties.get("Append"))
        externalized = prop in node.externalized()
        loop = node.repeating_container()

        if suffix == "None":
            outputs.setdefault(_normalise(fname), []).append(node)
            if append:
                header = (" With IncludeHeader=True the header row is written again in the "
                          "middle of the file each time." if _bool(node.properties.get("IncludeHeader")) else "")
                report.findings.append(_finding(
                    "APPENDS_ACROSS_RUNS", node,
                    f"Append=True with Suffix=None: every run appends to '{fname}', so rows "
                    f"from different sessions accumulate in one file.{header}",
                    hint="Fine if intended; otherwise use Suffix=Timestamp."))
            elif overwrite and loop is not None:
                report.findings.append(_finding(
                    "SILENT_OVERWRITE", node,
                    f"Overwrite=True with Suffix=None: each run replaces '{fname}' from the "
                    f"previous session. It sits inside {_loop_name(loop)}, which opens it again "
                    "for every element it receives: if that is more than one (e.g. one per "
                    "trial), each element also replaces the previous one within the session.",
                    hint="Use Suffix=Timestamp or FileCount to keep one file per element, or "
                         "move the writer after the SelectMany to collect all elements in one "
                         "file."))
            elif overwrite:
                # Launchers commonly set externalized file names per session (seen across
                # IBL's rigs), which baghban cannot see: report, but do not alarm.
                severity = "info" if externalized else "error"
                extra = (f" {prop} is externalized, so this is safe if the launcher sets a "
                         "new value on every run." if externalized else "")
                report.findings.append(_finding(
                    "SILENT_OVERWRITE", node,
                    f"Overwrite=True with Suffix=None: each run replaces '{fname}' from the "
                    f"previous session, without an error.{extra}",
                    hint="Use Suffix=Timestamp (one file per run), or Overwrite=False so a "
                         "second run stops instead of destroying data.",
                    severity=severity))
            elif loop is not None:
                report.findings.append(_finding(
                    "FAILS_ON_REPEAT", node,
                    f"Suffix=None and Overwrite=False inside {_loop_name(loop)}: the first "
                    f"element creates '{fname}', the second finds it already exists and "
                    "raises an IOException, which terminates the workflow mid-session.",
                    hint="Use Suffix=Timestamp or FileCount, or move the writer after the "
                         "SelectMany."))

    for key, nodes in outputs.items():
        if len(nodes) < 2:
            continue
        others = "; ".join(n.location() for n in nodes[:-1])
        for dup in nodes[1:]:
            report.findings.append(_finding(
                "DUPLICATE_OUTPUT", dup,
                f"Another writer also writes '{dup.properties[dup.filename_property]}' "
                f"({others}). Two writers cannot hold the same file: one of them fails, or "
                "they overwrite each other. This is common when a module containing a "
                "writer is included twice without giving each copy its own file name.",
                hint="Give each writer its own file name; for included modules, externalize "
                     "FileName and set it on each IncludeWorkflow."))


def _normalise(fname: str) -> str:
    # Bonsai rigs run on Windows, where paths are case-insensitive.
    return fname.replace("\\", "/").strip().casefold()


# --------------------------------------------------------------------------- entry point

CHECKS = (check_includes, check_subjects, check_writers)


def check(doc: Document) -> Report:
    """Run every check on a loaded document."""
    report = Report(path=str(doc.path) if doc.path else None,
                    n_nodes=sum(1 for _ in doc.walk()), kind=doc.kind)
    for fn in CHECKS:
        fn(doc, report)
    order = {s: i for i, s in enumerate(SEVERITIES)}
    report.findings.sort(key=lambda f: (order[f.severity], f.node))
    return report
