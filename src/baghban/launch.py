"""What Bonsai does with a launcher's command line.

Rigs are rarely started from the editor. A launcher (a Python task runner, a
batch file) runs something like::

    Bonsai.exe rig.bonsai --no-editor --property Animal=M12 -p:Stim.Contrast=0.5

and the values passed with ``--property`` are what the session actually used.
This module reads such a command line the way ``Bonsai.exe`` does and applies
the values to a loaded workflow, so checks, ``parameters`` and provenance see
the session's effective values rather than the ones saved in the file.

Mirrored from the Bonsai source:

* ``CommandLineParser`` (Bonsai.Configuration): ``--property:N=V``,
  ``--property N=V``, ``-p:N=V`` and ``-p N=V``; a separate value is taken
  unless it starts with ``--``; the first argument that is not a command is
  the workflow, a second one is an error; a repeated name is an error.
* ``SetWorkflowProperty`` (Bonsai.Core): a dotted name walks down through
  *named nested workflows* (groups, SelectMany, ...); exactly one enabled one
  must match at each step. It does not walk into an IncludeWorkflow by name
  (an include is not a WorkflowExpressionBuilder); an include's properties
  are reached through an ExternalizedMapping wired into it, as the editor
  does. The last part names a property the workflow exposes through an
  ExternalizedMapping (DisplayName, or else Name). Bonsai.exe builds the
  workflow before assigning, and building refuses two properties of one name
  in one workflow, so such a name is reported as ``duplicate``.

Values stay strings. Bonsai converts them with the property's TypeConverter,
which needs the .NET types, so a value that does not convert (``Period=fast``)
is only caught when Bonsai runs.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Optional

from .model import Document, Workflow, externalized_properties, find_external, assign_external, \
    target_values

# Bonsai.exe's commands, in the order Program.cs registers them (the order
# decides which short aliases exist), and whether each takes a value.
_COMMANDS = [
    ("--debug", False), ("--start", False), ("--start-no-debug", False), ("--lib", True),
    ("--visualizer-layout", True), ("--debug-scripts", False), ("--no-boot", False),
    ("--no-editor", False), ("--no-env", False), ("--init", False), ("--info", False),
    ("--@pipe", True), ("--export-image", True), ("--export-package", False),
    ("--reload-editor", False), ("--gallery", False), ("--editor-scale", True),
    ("--package-manager", True), ("--property", True),
]


def _command_table() -> dict:
    """Every spelling Bonsai accepts, as CommandLineParser.RegisterCommand builds it:
    the long name, the long name without inner dashes, and initials (``-p``)."""
    table = {}
    for name, takes_value in _COMMANDS:
        table[name] = (name, takes_value)
        words = name[1:].split("-")
        words[0] = "--"
        if len(words) > 2:
            table.setdefault("".join(words), (name, takes_value))
        table.setdefault("".join(w[0] for w in words), (name, takes_value))
    return table


_TABLE = _command_table()


class PropertyAssignmentError(ValueError):
    """A ``--property`` Bonsai would refuse (raised by ``strict`` calls)."""


@dataclass
class Launch:
    """A Bonsai command line, read as Bonsai.exe reads it."""

    workflow: Optional[str]  # as written; Bonsai makes it absolute against its working folder
    properties: dict = field(default_factory=dict)  # name -> value, in order
    options: dict = field(default_factory=dict)  # other commands: True, or their value(s)


def parse_command_line(args) -> Launch:
    """Read Bonsai.exe's arguments (``sys.argv``-style, without the shell).

    A leading ``Bonsai.exe`` (or ``bonsai``) is skipped; strip any other
    wrapper (``mono``, ``wine``) first. Raises ``ValueError`` where Bonsai.exe
    would stop: a second workflow argument, a property without ``=``, or the
    same property twice.
    """
    args = [str(a) for a in args]
    if args and args[0].replace("\\", "/").rsplit("/", 1)[-1].lower() in ("bonsai.exe", "bonsai"):
        args = args[1:]
    launch = Launch(workflow=None)
    seen_workflow = False
    i = 0
    while i < len(args):
        token = args[i]
        parts = [p for p in token.split(":", 1) if p]  # Split(':', 2, RemoveEmptyEntries)
        command = _TABLE.get(parts[0]) if parts else None
        if command is not None:
            name, takes_value = command
            value = None
            if takes_value:
                if len(parts) > 1:
                    value = parts[1]
                elif i + 1 < len(args) and not args[i + 1].startswith("--"):
                    i += 1
                    value = args[i]
                else:
                    value = ""
            if name == "--property":
                prop, sep, val = value.partition("=")
                if not value:
                    raise ValueError("--property needs NAME=VALUE")
                if not sep:
                    raise ValueError(f"invalid property assignment '{value}' (expected NAME=VALUE)")
                if prop in launch.properties:
                    raise ValueError(f"property '{prop}' is set twice")
                launch.properties[prop] = val
            elif name == "--lib":
                launch.options.setdefault(name, []).append(value)
            else:
                launch.options[name] = True if value is None else value
        elif seen_workflow:
            raise ValueError(f"unrecognized command or argument '{token}'")
        else:
            seen_workflow = True
            launch.workflow = token
        i += 1
    return launch


@dataclass
class Assignment:
    """What became of one ``--property NAME=VALUE``."""

    name: str
    value: str
    status: str  # ok | unknown | ambiguous | duplicate | invalid
    note: str = ""
    targets: list = field(default_factory=list)  # locations of the nodes the value went to
    previous: object = None  # the value saved in the file (a list when the targets differ)

    def to_dict(self) -> dict:
        return asdict(self)


def _include_name(path: str) -> str:
    """IncludeWorkflowBuilder.GetDisplayName: the file name without extension,
    and for an embedded ``Assembly:Folder.Module`` path the last dotted part."""
    stem = os.path.splitext(path.replace("\\", "/").rsplit("/", 1)[-1])[0]
    if ":" in path:
        stem = stem.rsplit(".", 1)[-1]
    return stem


def _walk(doc: Document, name: str):
    """(workflow, property) for a dotted name, or (None, status, note)."""
    if not name.strip():
        return None, "invalid", "empty property name"
    chain = [p for p in name.split(".") if p]
    wf: Workflow = doc.workflow
    for depth, part in enumerate(chain[:-1]):
        here = ".".join(chain[:depth + 1])
        named = [n for n in wf.nodes if n.workflow is not None and not n.is_include
                 and n.name == part]
        enabled = [n for n in named if not n.disabled]
        if len(enabled) > 1:
            return None, "ambiguous", f"{len(enabled)} nested workflows are named '{here}'"
        if not enabled:
            if named:
                why = f"the nested workflow '{here}' is disabled"
            elif any(n.is_include and n.include is not None
                     and _include_name(n.include.path) == part for n in wf.nodes):
                why = (f"'{here}' is an include; Bonsai's --property does not reach inside "
                       "includes by name, only through an externalized property")
            else:
                why = f"no nested workflow named '{here}'"
            return None, "unknown", why
        wf = enabled[0].workflow
    return wf, chain[-1], ""


def _resolve(doc: Document, name: str):
    walked = _walk(doc, name)
    if walked[0] is None:
        return walked
    wf, prop, _ = walked
    if find_external(wf, prop) is None:
        exposed = sorted({n for n, _, _ in externalized_properties(wf)})
        scope = ".".join([p for p in name.split(".") if p][:-1]) or "the workflow"
        hint = f"; it exposes {', '.join(exposed)}" if exposed else "; it exposes none"
        return None, "unknown", f"{scope} has no externalized property '{prop}'{hint}"
    if sum(1 for n, _, _ in externalized_properties(wf) if n == prop) > 1:
        scope = ".".join([p for p in name.split(".") if p][:-1]) or "the workflow"
        return None, "duplicate", (f"{scope} exposes two properties named '{prop}', so Bonsai "
                                   "refuses to build it (DUPLICATE_PROPERTY)")
    return wf, prop, ""


def set_properties(doc: Document, properties: dict, strict: bool = False) -> list:
    """Apply a launcher's ``--property`` values to ``doc`` (changing it in place).

    ``properties`` maps names, dotted for nested workflows, to string values,
    as ``parse_command_line(...).properties`` gives them. Each value is set on
    every node it reaches, through groups and into includes, and those nodes
    record the property in ``Node.overridden``. Returns one ``Assignment`` per
    name; names Bonsai would refuse are reported (``unknown``, ``ambiguous``,
    ``duplicate``, ``invalid``) and left alone, or with ``strict`` raise
    ``PropertyAssignmentError`` before anything is changed.
    """
    resolved = [(name, str(value), _resolve(doc, name)) for name, value in properties.items()]
    if strict:
        for name, _value, (wf, status_or_prop, note) in resolved:
            if wf is None:
                raise PropertyAssignmentError(f"--property {name}: {note}")
    results = []
    for name, value, (wf, status_or_prop, note) in resolved:
        if wf is None:
            results.append(Assignment(name, value, status_or_prop, note))
            continue
        prop = status_or_prop
        mapping, mapped = find_external(wf, prop)
        before = sorted(set().union(*(target_values(t, mapped) for t in mapping.successors()))) or [""]
        targets = assign_external(wf, prop, value)
        results.append(Assignment(
            name, value, "ok",
            "" if targets else "the externalized property is not connected to anything",
            [f"{t.location()}.{mapped}" for t in targets],
            before[0] if len(before) == 1 else before))
    return results
