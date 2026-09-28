"""What a workflow needs and what it exposes: assemblies, externalized
parameters, and a content fingerprint that ignores formatting."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from .model import Document, Node, Workflow, parse_namespace_uri

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
                             "location": node.location()})
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
    if deps["includes"]:
        lines += ["", "includes"]
        for inc in deps["includes"]:
            lines.append(f"  {inc['path']}  [{inc['status']}]")
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
            values = sorted({t.properties.get(name, "") for t in targets})
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


def manifest_fields(doc: Document) -> dict:
    """Flat, dotted fields describing the protocol, for provenance tools.

    With daftar::

        with daftar.track("session", params=baghban.manifest_fields(doc)) as run:
            ...

    records which exact workflow (includes and parameter values included)
    produced the data being analysed.
    """
    fields = {"bonsai.workflow": str(doc.path) if doc.path else None,
              "bonsai.version": doc.version,
              "bonsai.fingerprint": fingerprint(doc)}
    for p in parameters(doc):
        value = p["value"] if isinstance(p["value"], str) else "|".join(p["value"])
        fields[f"bonsai.param.{p['name']}"] = value
    for node in doc.walk():
        if node.is_include and node.include is not None:
            fields[f"bonsai.include.{node.include.path}"] = node.include.status
    return fields
