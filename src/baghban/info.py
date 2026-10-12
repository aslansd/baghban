"""What a workflow needs and what it exposes: assemblies, externalized
parameters, and a content fingerprint that ignores formatting."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Optional

from .model import Document, Node, Workflow, parse_namespace_uri, target_values

DOTNET_ASSEMBLIES = {"mscorlib", "System", "System.Core", "netstandard", "System.Private.CoreLib",
                     "System.Runtime", "System.Xml", "System.Drawing"}


def dependencies(doc: Document) -> dict:
    """Assemblies (and so NuGet packages) the workflow and its includes use.

    Taken from the ``clr-namespace`` declarations of every file: XmlSerializer
    only declares the prefixes a file actually uses, so this also catches
    types that appear only inside properties (e.g. ``TypeArguments``).
    """
    maps = [doc.namespaces]
    includes = []
    for node in doc.walk():
        if node.is_include and node.include is not None:
            inc = node.include
            includes.append({"path": inc.path, "status": inc.status,
                             "resolved": str(inc.resolved) if inc.resolved else None,
                             "location": node.location(), "package": inc.package,
                             "package_version": inc.package_version, "pinned": inc.pinned,
                             "origin": inc.origin, "note": inc.note})
            if inc.namespaces:
                maps.append(inc.namespaces)

    assemblies: dict = {}
    for mapping in maps:
        for uri in mapping.values():
            if not uri.startswith("clr-namespace:"):
                continue
            namespace, assembly = parse_namespace_uri(uri)
            if assembly:
                entry = assemblies.setdefault(assembly, {"namespaces": set(), "nodes": 0,
                                                         "dotnet": assembly in DOTNET_ASSEMBLIES})
                entry["namespaces"].add(namespace)

    usage = Counter(n.type.assembly for n in doc.walk() if n.type.assembly)
    for assembly, count in usage.items():
        entry = assemblies.setdefault(assembly, {"namespaces": set(), "nodes": 0,
                                                 "dotnet": assembly in DOTNET_ASSEMBLIES})
        entry["nodes"] = count
    for n in doc.walk():
        if n.type.assembly and n.type.namespace:
            assemblies[n.type.assembly]["namespaces"].add(n.type.namespace)

    return {"version": doc.version,
            "assemblies": {k: {"namespaces": sorted(v["namespaces"]), "nodes": v["nodes"],
                               "dotnet": v["dotnet"]} for k, v in sorted(assemblies.items())},
            "includes": includes}


def format_dependencies(deps: dict) -> str:
    lines = [f"Bonsai {deps['version'] or '?'}", "", "assemblies"]
    width = max((len(a) for a in deps["assemblies"]), default=10)
    for name, info in deps["assemblies"].items():
        tag = "  (.NET)" if info["dotnet"] else ""
        lines.append(f"  {name:<{width}}  {info['nodes']:>3} node(s)  "
                     f"{', '.join(info['namespaces'])}{tag}")
    lines.append("")
    lines.append("Bonsai packages are named after their assembly (Bonsai.Vision -> package "
                 "Bonsai.Vision);")
    lines.append("third-party packages usually follow the same convention.")
    pkgs = {}
    for inc in deps["includes"]:
        if inc.get("package") and inc["status"] == "ok":
            pkgs.setdefault((inc["package"], inc["package_version"]), inc)
    if pkgs:
        lines += ["", "packages read for their embedded workflows"]
        for (pid, ver), inc in sorted(pkgs.items()):
            how = "pinned" if inc["pinned"] else "not pinned, newest found"
            lines.append(f"  {pid} {ver}  ({how}; from {inc['origin']})")
    if deps["includes"]:
        lines += ["", "includes"]
        for inc in deps["includes"]:
            lines.append(f"  {inc['path']}  [{inc['status']}]")
            if inc["status"] != "ok" and inc.get("note"):
                lines.append(f"      {inc['note']}")
    return "\n".join(lines)


def parameters(doc: Document) -> list:
    """Externalized properties of the top-level workflow.

    These are what ``Bonsai.exe --property Name=Value`` can set on the command
    line, i.e. the knobs an experimenter changes between sessions.
    """
    out = []
    for node in doc.workflow.nodes:
        if not node.type.is_core("ExternalizedMapping") or node.disabled:
            continue
        for name, display in node.mappings:
            targets = node.successors()
            # a group's or include's value lives on the nodes it maps to
            values = sorted(set().union(*(target_values(t, name) for t in targets))) or [""]
            out.append({"name": display or name, "property": name,
                        "value": values[0] if len(values) == 1 else values,
                        "targets": [t.location() for t in targets]})
    return out


def format_parameters(params: list) -> str:
    if not params:
        return "No externalized properties at the top level."
    width = max(len(p["name"]) for p in params)
    lines = []
    for p in params:
        value = p["value"] if isinstance(p["value"], str) else " | ".join(p["value"])
        lines.append(f"{p['name']:<{width}}  = {value or '(empty)'}")
        for t in p["targets"]:
            lines.append(f"{'':<{width}}    -> {t}.{p['property']}")
    return "\n".join(lines)


def _canonical_workflow(wf: Workflow) -> dict:
    return {"nodes": [_canonical_node(n) for n in wf.nodes],
            "edges": sorted([e.source, e.target, e.label] for e in wf.edges)}


def _canonical_node(n: Node) -> dict:
    out = {"type": n.type.qualified, "assembly": n.type.assembly, "disabled": n.disabled,
           "properties": sorted(n.properties.items())}
    if n.include is not None:
        out["include"] = {"path": n.include.path, "status": n.include.status}
    if n.workflow is not None:
        out["workflow"] = _canonical_workflow(n.workflow)
    return out


def fingerprint(doc: Document) -> str:
    """SHA-256 of the workflow's content with includes expanded.

    Insensitive to whitespace, attribute order, namespace prefixes and the
    ``Version`` stamp the editor writes on save; sensitive to every operator,
    property value, edge, disabled flag and included file's content.
    """
    blob = json.dumps(_canonical_workflow(doc.workflow), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def outputs(doc: Document) -> list:
    """The files the workflow writes: every enabled file writer, with its path.

    ``path`` is the effective value (after includes and any ``set_properties``),
    as written: Bonsai opens a relative path against its working folder (the
    workflow's folder in the editor, the launcher's folder with ``--no-editor``).
    ``suffix`` is the writer's ``Suffix``: ``None`` means exactly ``path``;
    ``Timestamp`` or ``FileCount`` mean Bonsai adds to the name, so look for
    ``path``'s stem followed by anything. ``set_at_run_time`` means a
    PropertyMapping assigns the path from data, so the value here is only the
    starting one.
    """
    out = []
    for node in doc.walk():
        prop = node.filename_property
        if prop is None or node.is_effectively_disabled():
            continue
        out.append({"writer": node.type.name, "property": prop,
                    "path": node.properties.get(prop, ""),
                    "suffix": node.properties.get("Suffix", ""),
                    "location": node.location(), "source": node.source,
                    "overridden": prop in node.overridden,
                    "set_at_run_time": prop in node.mapped()})
    return out


PROVENANCE_SCHEMA = "1"


def provenance(workflow=None, properties: Optional[dict] = None, *, command_line=None,
               cwd=None, **load_options) -> dict:
    """Flat, dotted fields recording which protocol a session ran.

    The entry point for provenance tools (daftar's Bonsai adapter uses it).
    ``workflow`` is a ``Document`` or a path; ``properties`` are the launcher's
    ``--property`` values (``{"Animal": "M12", "Stim.Contrast": "0.5"}``);
    ``command_line`` is the launcher's Bonsai.exe arguments instead, from
    which the workflow and properties are read (``properties`` adds to them).
    A relative workflow path is taken against ``cwd``. Other keyword arguments
    go to ``baghban.load``. A ``Document`` passed in is not changed.

    Every value is a string (``None`` when unknown). Fields:

    ``bonsai.provenance``      version of this field layout (bumped on any change)
    ``bonsai.baghban``         baghban version that wrote them
    ``bonsai.workflow``        absolute path of the workflow
    ``bonsai.version``         Bonsai version stamped in the file
    ``bonsai.fingerprint``     ``fingerprint`` of the file as saved (launcher
                               values not included, so sessions of one
                               protocol share it)
    ``bonsai.environment``     the ``Bonsai.config`` package versions came from
    ``bonsai.property.<name>`` each value the launcher passed
    ``bonsai.param.<name>``    each top-level externalized property, effective value
    ``bonsai.include.<path>``  each include's status (ok, missing, ...)
    ``bonsai.package.<id>``    version of each package whose workflows were read
    ``bonsai.output.<n>``      path of each enabled file writer (see ``outputs``)
    ``bonsai.problems``        launcher values Bonsai would refuse, ``; ``-joined
                               (only present when there are some)
    """
    from . import __version__
    from .launch import parse_command_line, set_properties
    from .model import load

    props = {}
    if command_line is not None:
        launch = parse_command_line(command_line)
        props.update(launch.properties)
        if workflow is None:
            workflow = launch.workflow
    props.update(properties or {})
    if workflow is None:
        raise ValueError("no workflow: pass one, or a command line that names it")
    if isinstance(workflow, Document):
        doc = _copy(workflow) if props else workflow
    else:
        path = Path(workflow)
        if not path.is_absolute() and cwd is not None:
            path = Path(cwd) / path
        doc = load(path, **load_options)

    fields = {"bonsai.provenance": PROVENANCE_SCHEMA, "bonsai.baghban": __version__,
              "bonsai.workflow": str(doc.path.resolve()) if doc.path else None,
              "bonsai.version": doc.version,
              "bonsai.fingerprint": fingerprint(doc)}
    env = getattr(doc.packages, "environment", None)
    if env is not None:
        fields["bonsai.environment"] = str(env.config)
    assignments = set_properties(doc, props) if props else []
    for a in assignments:
        fields[f"bonsai.property.{a.name}"] = a.value
    for p in parameters(doc):
        value = p["value"] if isinstance(p["value"], str) else "|".join(p["value"])
        fields[f"bonsai.param.{p['name']}"] = value
    for node in doc.walk():
        if node.is_include and node.include is not None:
            inc = node.include
            fields[f"bonsai.include.{inc.path}"] = inc.status
            if inc.package and inc.status == "ok":
                fields[f"bonsai.package.{inc.package}"] = inc.package_version
    for i, o in enumerate(outputs(doc)):
        fields[f"bonsai.output.{i}"] = o["path"]
    problems = [f"--property {a.name}: {a.note}" for a in assignments if a.status != "ok"]
    if problems:
        fields["bonsai.problems"] = "; ".join(problems)
    return fields


def _copy(doc: Document) -> Document:
    """A deep copy to apply launcher values to; the package resolver is shared."""
    import copy
    return copy.deepcopy(doc, {id(doc.packages): doc.packages})


def manifest_fields(doc: Document) -> dict:
    """Provenance fields of a loaded workflow; the same as ``provenance(doc)``.

    Kept from 0.1 for existing callers; new code should call ``provenance``,
    which also takes the launcher's ``--property`` values.
    """
    return provenance(doc)
