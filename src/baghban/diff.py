"""Semantic diff of two workflows.

``git diff`` on a ``.bonsai`` file is hard to read: nodes are addressed by
their position, so inserting one node renumbers every edge after it, and the
editor rewrites the whole file on save. This diff matches nodes by *what they
are* instead:

* a node with a name (a subject, a named group) is matched by type and name;
* any other node by type and its occurrence count among unnamed nodes of the
  same type in the same workflow ("the second Threshold in group Tracking").

Inserting a node therefore does not disturb the keys of unrelated nodes. It
does shift the keys of later unnamed nodes of the *same* type in the same
workflow; naming them avoids that. Included files are expanded, so a change
inside an included module appears under the include that uses it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Document, Node, Workflow


def _keys(wf: Workflow) -> dict:
    counts: dict = {}
    keys = {}
    for node in wf.nodes:
        if node.name:
            base = f"{node.type.name}:{node.name}"
        elif node.is_include and node.include is not None:
            base = f"Include({node.include.path})"
        else:
            base = node.type.name
        n = counts.get(base, 0)
        counts[base] = n + 1
        keys[node.index] = base if n == 0 else f"{base}#{n}"
    return keys


def _index(doc: Document) -> tuple[dict, dict]:
    """path -> node, and workflow path -> set of edges expressed with keys."""
    nodes: dict = {}
    edges: dict = {}

    def visit(wf: Workflow, prefix: str) -> None:
        keys = _keys(wf)
        for node in wf.nodes:
            path = f"{prefix}/{keys[node.index]}" if prefix else keys[node.index]
            nodes[path] = node
            if node.workflow is not None:
                visit(node.workflow, path)
        edges[prefix or "/"] = {
            (keys[e.source], keys[e.target], e.label) for e in wf.edges
            if e.source in keys and e.target in keys}

    visit(doc.workflow, "")
    return nodes, edges


@dataclass
class Change:
    kind: str  # added | removed | changed | enabled | disabled | edge+ | edge- | meta
    path: str
    detail: str = ""
    before: object = None
    after: object = None
    label: str = ""

    def line(self) -> str:
        path = f"{self.path} ({self.label})" if self.label else self.path
        if self.kind == "added":
            return f"+ {path}"
        if self.kind == "removed":
            return f"- {path}"
        if self.kind in ("enabled", "disabled"):
            return f"~ {path}  {self.kind}"
        if self.kind == "changed":
            return f"~ {path}  {self.detail}: {_fmt(self.before)} -> {_fmt(self.after)}"
        if self.kind in ("edge+", "edge-"):
            sign = "+" if self.kind == "edge+" else "-"
            return f"{sign} edge  {self.path}: {self.detail}"
        return f"~ {self.detail}: {_fmt(self.before)} -> {_fmt(self.after)}"


def _fmt(value) -> str:
    if value is None:
        return "(unset)"
    text = str(value)
    return text if len(text) <= 60 else text[:57] + "..."


@dataclass
class WorkflowDiff:
    a: str
    b: str
    changes: list = field(default_factory=list)

    @property
    def identical(self) -> bool:
        return not self.changes

    def summary(self) -> str:
        head = [f"--- {self.a}", f"+++ {self.b}", ""]
        if self.identical:
            return "\n".join(head + ["Workflows are equivalent (formatting and node order "
                                     "of unrelated nodes aside)."])
        body = [c.line() for c in self.changes]
        counts = {}
        for c in self.changes:
            counts[c.kind] = counts.get(c.kind, 0) + 1
        tally = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
        return "\n".join(head + body + ["", f"{len(self.changes)} change(s): {tally}"])

    def to_dict(self) -> dict:
        return {"a": self.a, "b": self.b, "identical": self.identical,
                "changes": [{"kind": c.kind, "path": c.path, "label": c.label, "detail": c.detail,
                             "before": c.before, "after": c.after} for c in self.changes]}


def _hint(node: Node) -> str:
    """A readable tag for unnamed nodes whose key alone is ambiguous (writers)."""
    prop = node.filename_property
    if prop and node.properties.get(prop) and not node.name:
        return repr(node.properties[prop])
    return ""


def diff(a: Document, b: Document) -> WorkflowDiff:
    result = WorkflowDiff(str(a.path or "a"), str(b.path or "b"))
    if a.version != b.version:
        result.changes.append(Change("meta", "", "Bonsai version", a.version, b.version))

    nodes_a, edges_a = _index(a)
    nodes_b, edges_b = _index(b)

    for path in sorted(set(nodes_a) | set(nodes_b)):
        na, nb = nodes_a.get(path), nodes_b.get(path)
        if na is None:
            result.changes.append(Change("added", path, label=_hint(nb)))
            continue
        if nb is None:
            result.changes.append(Change("removed", path, label=_hint(na)))
            continue
        hint = _hint(nb)
        if na.type.qualified != nb.type.qualified:
            result.changes.append(Change("changed", path, "type", na.type.qualified,
                                         nb.type.qualified))
        if na.disabled != nb.disabled:
            result.changes.append(Change("disabled" if nb.disabled else "enabled", path,
                                         label=hint))
        for prop in sorted(set(na.properties) | set(nb.properties)):
            va, vb = na.properties.get(prop), nb.properties.get(prop)
            if va != vb:
                result.changes.append(Change("changed", path, prop, va, vb, label=hint))
        if na.include and nb.include and na.include.status != nb.include.status:
            result.changes.append(Change("changed", path, "include status",
                                         na.include.status, nb.include.status))

    for wf_path in sorted(set(edges_a) | set(edges_b)):
        ea, eb = edges_a.get(wf_path, set()), edges_b.get(wf_path, set())
        # edges of added/removed workflows are implied by the node change
        if wf_path != "/" and (wf_path not in nodes_a or wf_path not in nodes_b):
            continue
        for src, dst, label in sorted(eb - ea):
            result.changes.append(Change("edge+", wf_path, f"{src} -> {dst} ({label})"))
        for src, dst, label in sorted(ea - eb):
            result.changes.append(Change("edge-", wf_path, f"{src} -> {dst} ({label})"))
    return result
