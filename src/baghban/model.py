"""Object model for Bonsai workflow files (``.bonsai``).

A ``.bonsai`` file is XML written by .NET's XmlSerializer:

    <WorkflowBuilder Version="2.9.0" xmlns="https://bonsai-rx.org/2018/workflow"
                     xmlns:rx="clr-namespace:Bonsai.Reactive;assembly=Bonsai.Core" ...>
      <Workflow>
        <Nodes>  <Expression xsi:type="..."> ... </Expression> ... </Nodes>
        <Edges>  <Edge From="0" To="1" Label="Source1" /> ... </Edges>
      </Workflow>
    </WorkflowBuilder>

Everything here is read with the standard library only. Nothing is executed,
and no .NET installation is needed.

Two scoping rules from Bonsai's build process (Bonsai.Core/Expressions) are
modelled because the checks depend on them:

* ``GroupWorkflow`` and ``IncludeWorkflow`` build inside a ``GroupContext``,
  which forwards every declaration to its parent. They are *transparent*:
  a subject declared inside a group is visible next to the group.
* Every other nested workflow (``SelectMany``, ``Defer``, ``CreateObservable``,
  ...) builds inside a new ``BuildContext``: a real scope. Lookups fall back
  to the enclosing scope; declarations stay inside.

Include paths that are not embedded resources are opened with
``File.OpenRead``, i.e. relative to the working directory, which the Bonsai
editor sets to the folder of the top-level workflow. baghban resolves them
the same way: relative to the top-level file, even for nested includes.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

XSI = "http://www.w3.org/2001/XMLSchema-instance"
WORKFLOW_NS = "https://bonsai-rx.org/2018/workflow"
XSI_TYPE = f"{{{XSI}}}type"

EXPRESSIONS = "Bonsai.Expressions"  # namespace of types in the default xmlns
REACTIVE = "Bonsai.Reactive"

# Nested workflows whose contents are subscribed again for every input element
# (or window), so anything inside runs many times per session. Window is the
# Bonsai.Reactive operator whose nested workflow closes each window: it is
# subscribed once per window (Bonsai.Core/Reactive/Window.cs).
REPEATING = {"SelectMany", "CreateObservable", "WindowWorkflow", "Window"}

SUBJECT_DECLARATIONS = {
    "PublishSubject", "BehaviorSubject", "ReplaySubject",
    "ResourceSubject", "AsyncSubject", "Subject",
}
SUBJECT_USES = {"SubscribeSubject", "MulticastSubject"}

_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]|^\\\\")


class WorkflowLoadError(Exception):
    """The file is not a readable Bonsai workflow."""


# --------------------------------------------------------------------------- types

@dataclass(frozen=True)
class TypeRef:
    """A .NET type named by ``xsi:type``, resolved through the file's xmlns."""

    name: str
    namespace: Optional[str] = None
    assembly: Optional[str] = None

    @property
    def qualified(self) -> str:
        return f"{self.namespace}.{self.name}" if self.namespace else self.name

    def is_core(self, *names: str) -> bool:
        """True for Bonsai.Core expression/reactive types with one of ``names``."""
        return self.name in names and self.namespace in (EXPRESSIONS, REACTIVE, None)

    def __str__(self) -> str:
        return self.name


def parse_namespace_uri(uri: str) -> tuple[Optional[str], Optional[str]]:
    """``clr-namespace:Bonsai.Vision;assembly=Bonsai.Vision`` -> (namespace, assembly)."""
    if uri == WORKFLOW_NS:
        return EXPRESSIONS, "Bonsai.Core"
    if uri.startswith("clr-namespace:"):
        body = uri[len("clr-namespace:"):]
        namespace, _, rest = body.partition(";")
        assembly = None
        if rest.startswith("assembly="):
            assembly = rest[len("assembly="):]
        return namespace or None, assembly
    return uri, None


# --------------------------------------------------------------------------- graph

@dataclass
class Edge:
    source: int
    target: int
    label: str = "Source1"


@dataclass
class Include:
    """An ``IncludeWorkflow`` reference and what became of it."""

    path: str
    embedded: bool
    status: str  # ok | missing | recursive | unresolved | invalid
    resolved: Optional[Path] = None
    workflow: Optional["Workflow"] = None
    overrides: dict = field(default_factory=dict)
    note: str = ""
    namespaces: dict = field(default_factory=dict)
    package: Optional[str] = None  # package id when read out of a package DLL
    package_version: Optional[str] = None
    pinned: bool = False  # version pinned by an environment or --package, not guessed
    origin: str = ""  # where the package DLL came from


@dataclass(eq=False)
class Node:
    index: int
    type: TypeRef
    properties: dict
    parent: "Workflow" = field(repr=False)
    disabled: bool = False
    wrapper: Optional[str] = None  # "Combinator" / "Source" when the operator is wrapped
    workflow: Optional["Workflow"] = None  # nested workflow, if any
    include: Optional[Include] = None
    mappings: list = field(default_factory=list)  # (Name, DisplayName) for mapping builders
    # property names set from outside: by an includer, or by a launcher's --property
    overridden: set = field(default_factory=set)

    # -- identity -------------------------------------------------------------
    @property
    def name(self) -> Optional[str]:
        value = self.properties.get("Name")
        return value if value else None

    @property
    def file(self) -> Optional[Path]:
        return self.parent.file

    @property
    def in_package(self) -> bool:
        return self.parent.package is not None

    @property
    def source(self) -> Optional[str]:
        """Where this node is defined, for reports: a file, or a package resource."""
        if self.parent.package is not None and self.parent.package[1] is not None:
            pid, version, resource = self.parent.package
            return f"{pid} {version}: {resource}"
        return str(self.file) if self.file else None

    @property
    def id(self) -> tuple:
        """Position in the (include-expanded) tree, e.g. (3, 0, 2)."""
        path = [self.index]
        wf = self.parent
        while wf.owner is not None:
            path.append(wf.owner.index)
            wf = wf.owner.parent
        return tuple(reversed(path))

    # -- classification -------------------------------------------------------
    @property
    def is_group(self) -> bool:
        return self.type.is_core("GroupWorkflow")

    @property
    def is_include(self) -> bool:
        return self.type.is_core("IncludeWorkflow")

    @property
    def is_subject_declaration(self) -> bool:
        return self.type.is_core(*SUBJECT_DECLARATIONS)

    @property
    def is_subject_use(self) -> bool:
        return self.type.is_core(*SUBJECT_USES)

    @property
    def filename_property(self) -> Optional[str]:
        """The path property of a file writer, or None if this is not a writer.

        Every file writer in the Bonsai standard library (CsvWriter, and the
        FileSink/StreamSink families: TextWriter, VideoWriter, AudioWriter,
        MatrixWriter, ImageWriter) exposes ``Suffix`` together with ``FileName``
        or ``Path``. Third-party writers that follow the same convention are
        recognised too.
        """
        if "Suffix" not in self.properties:
            return None
        for prop in ("FileName", "Path"):
            if prop in self.properties:
                return prop
        return None

    @property
    def is_writer(self) -> bool:
        return self.filename_property is not None

    # -- structure ------------------------------------------------------------
    def predecessors(self) -> list["Node"]:
        return [self.parent.nodes[e.source] for e in self.parent.edges
                if e.target == self.index and 0 <= e.source < len(self.parent.nodes)]

    def successors(self) -> list["Node"]:
        return [self.parent.nodes[e.target] for e in self.parent.edges
                if e.source == self.index and 0 <= e.target < len(self.parent.nodes)]

    def externalized(self) -> set:
        """Property names exposed by an ExternalizedMapping wired into this node."""
        names = set()
        for pred in self.predecessors():
            if pred.type.is_core("ExternalizedMapping") and not pred.disabled:
                names.update(n for n, _ in pred.mappings)
        return names

    def mapped(self) -> set:
        """Property names assigned from data at run time (Property/InputMapping)."""
        names = set()
        for pred in self.predecessors():
            if pred.type.is_core("PropertyMapping", "InputMapping") and not pred.disabled:
                names.update(n for n, _ in pred.mappings)
        return names

    def containers(self) -> list["Node"]:
        """Enclosing nodes, outermost first."""
        chain = []
        wf = self.parent
        while wf.owner is not None:
            chain.append(wf.owner)
            wf = wf.owner.parent
        return list(reversed(chain))

    def repeating_container(self) -> Optional["Node"]:
        """Innermost enclosing SelectMany/CreateObservable/WindowWorkflow, if any."""
        for container in reversed(self.containers()):
            if container.type.is_core(*REPEATING):
                return container
        return None

    def is_effectively_disabled(self) -> bool:
        return self.disabled or any(c.disabled for c in self.containers())

    # -- display --------------------------------------------------------------
    def label(self) -> str:
        if self.is_group:
            return f"Group '{self.name}'" if self.name else "Group"
        if self.is_include and self.include is not None:
            return f"Include '{self.include.path}'"
        if (self.is_subject_declaration or self.is_subject_use) and self.name:
            return f"{self.type.name} '{self.name}'"
        prop = self.filename_property
        if prop and self.properties.get(prop):
            return f"{self.type.name} '{self.properties[prop]}'"
        if self.name and not self.type.is_core("WorkflowInput", "WorkflowOutput"):
            return f"{self.type.name} '{self.name}'"
        return self.type.name

    def location(self) -> str:
        """Human-readable path, e.g. ``Include 'Rec.bonsai' #3 > VideoWriter 'a.avi' #1``.

        ``#n`` is the node's position in its own workflow, as in the editor's
        XML, so two copies of an included module are told apart."""
        return " > ".join(f"{n.label()} #{n.index}" for n in self.containers() + [self])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Node {self.id} {self.label()}{' (disabled)' if self.disabled else ''}>"


@dataclass(eq=False)
class Workflow:
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    owner: Optional[Node] = field(default=None, repr=False)
    file: Optional[Path] = None
    from_include: bool = False
    # (package or assembly, version, resource) for another assembly's embedded
    # workflow; version is None when it was read from source (--resource-root)
    package: Optional[tuple] = None

    @property
    def transparent(self) -> bool:
        """True if declarations here belong to the enclosing scope."""
        return self.owner is not None and (self.owner.is_group or self.owner.is_include)

    def scope(self) -> "Workflow":
        """The workflow that owns declarations made in this one."""
        wf = self
        while wf.transparent:
            wf = wf.owner.parent
        return wf

    def parent_scope(self) -> Optional["Workflow"]:
        s = self.scope()
        return None if s.owner is None else s.owner.parent.scope()

    def walk(self) -> Iterator[Node]:
        """Every node, depth first, descending into groups and resolved includes."""
        for node in self.nodes:
            yield node
            if node.workflow is not None:
                yield from node.workflow.walk()

    def workflows(self) -> Iterator["Workflow"]:
        yield self
        for node in self.nodes:
            if node.workflow is not None:
                yield from node.workflow.workflows()


@dataclass
class Document:
    """A loaded top-level ``.bonsai`` file with its includes resolved."""

    path: Optional[Path]
    version: Optional[str]
    namespaces: dict
    workflow: Workflow
    base_dir: Path
    included_files: list = field(default_factory=list)
    kind: str = "workflow"  # workflow | extension | package (see project.py)
    packages: object = field(default=None, repr=False)  # the PackageResolver used, if any

    @property
    def is_module(self) -> bool:
        return self.kind != "workflow"

    def walk(self) -> Iterator[Node]:
        return self.workflow.walk()

    def check(self, **kwargs):
        from .checks import check
        return check(self, **kwargs)

    def __repr__(self) -> str:  # pragma: no cover
        n = sum(1 for _ in self.walk())
        return f"<Document {self.path} Bonsai {self.version}: {n} nodes>"


# --------------------------------------------------------------------------- parsing

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if tag.startswith("{") else tag


def _child(el: ET.Element, name: str) -> Optional[ET.Element]:
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


class _Loader:
    def __init__(self, base_dir: Path, resource_roots: Optional[dict], packages=None):
        self.base_dir = base_dir
        self.resource_roots = {k: Path(v) for k, v in (resource_roots or {}).items()}
        self.packages = packages  # a PackageResolver, or None
        self.included_files: list[Path] = []

    # -- file level ---------------------------------------------------------
    def read(self, source) -> tuple[ET.Element, dict]:
        namespaces: dict[str, str] = {}
        try:
            events = ET.iterparse(source, events=("start-ns",))
            for _event, (prefix, uri) in events:
                namespaces.setdefault(prefix, uri)
            root = events.root
        except ET.ParseError as exc:
            raise WorkflowLoadError(f"{source}: not well-formed XML ({exc})") from exc
        if _local(root.tag) != "WorkflowBuilder":
            raise WorkflowLoadError(f"{source}: root element is <{_local(root.tag)}>, "
                                    "expected <WorkflowBuilder>")
        return root, namespaces

    def resolve_type(self, value: Optional[str], namespaces: dict) -> TypeRef:
        if not value:
            return TypeRef("Unknown")
        prefix, sep, name = value.rpartition(":")
        uri = namespaces.get(prefix if sep else "", WORKFLOW_NS if not sep else None)
        if uri is None:
            return TypeRef(name, prefix or None, None)
        namespace, assembly = parse_namespace_uri(uri)
        return TypeRef(name, namespace, assembly)

    # -- workflow level -------------------------------------------------------
    def parse_workflow(self, el: ET.Element, namespaces: dict, file: Optional[Path],
                       owner: Optional[Node], stack: tuple, from_include: bool,
                       package: Optional[tuple] = None) -> Workflow:
        wf = Workflow(owner=owner, file=file, from_include=from_include, package=package)
        nodes_el = _child(el, "Nodes")
        if nodes_el is not None:
            for i, expr in enumerate(c for c in nodes_el if _local(c.tag) == "Expression"):
                wf.nodes.append(self.parse_node(expr, i, wf, namespaces, stack))
        edges_el = _child(el, "Edges")
        if edges_el is not None:
            for e in edges_el:
                if _local(e.tag) != "Edge":
                    continue
                try:
                    wf.edges.append(Edge(int(e.get("From")), int(e.get("To")),
                                         e.get("Label", "Source1")))
                except (TypeError, ValueError):
                    continue
        self.apply_include_overrides(wf)
        return wf

    def parse_node(self, expr: ET.Element, index: int, parent: Workflow,
                   namespaces: dict, stack: tuple) -> Node:
        el = expr
        ref = self.resolve_type(el.get(XSI_TYPE), namespaces)
        disabled = False
        if ref.is_core("Disable"):
            builder = _child(el, "Builder")
            if builder is not None:
                disabled = True
                el = builder
                ref = self.resolve_type(el.get(XSI_TYPE), namespaces)

        wrapper = None
        body = el
        if ref.is_core("Combinator", "Source"):
            inner = _child(el, "Combinator" if ref.name == "Combinator" else "Generator")
            if inner is not None and inner.get(XSI_TYPE):
                wrapper = ref.name
                ref = self.resolve_type(inner.get(XSI_TYPE), namespaces)
                body = inner

        props: dict = {}
        for attr, value in body.attrib.items():
            if attr != XSI_TYPE:
                props["@" + _local(attr)] = value
        _flatten(body, "", props, namespaces, self, skip_workflow=True)

        node = Node(index=index, type=ref, properties=props, parent=parent,
                    disabled=disabled, wrapper=wrapper)

        if ref.is_core("ExternalizedMapping"):
            node.mappings = [(p.get("Name"), p.get("DisplayName"))
                             for p in body if _local(p.tag) == "Property" and p.get("Name")]
        elif ref.is_core("PropertyMapping", "InputMapping"):
            container = _child(body, "PropertyMappings")
            if container is not None:
                node.mappings = [(p.get("Name"), None)
                                 for p in container if _local(p.tag) == "Property" and p.get("Name")]

        nested = _child(body, "Workflow")
        if nested is not None:
            node.workflow = self.parse_workflow(nested, namespaces, parent.file, node, stack,
                                                parent.from_include, parent.package)
        elif node.is_include:
            node.include = self.resolve_include(body, node, stack)
            if node.include.workflow is not None:
                node.workflow = node.include.workflow
        return node

    # -- includes -------------------------------------------------------------
    def resolve_include(self, el: ET.Element, node: Node, stack: tuple) -> Include:
        raw = el.get("Path") or ""
        overrides = {}
        for c in el:
            if len(c) == 0 and _local(c.tag) != "Workflow":
                overrides[_local(c.tag)] = (c.text or "").strip()
        path = raw if os.path.splitext(raw)[1] else raw + ".bonsai"
        embedded = ":" in path and not _WINDOWS_ABSOLUTE.match(path) and not os.path.isabs(path)
        inc = Include(path=raw, embedded=embedded, status="unresolved", overrides=overrides)
        if not raw:
            inc.status, inc.note = "invalid", "IncludeWorkflow has an empty Path."
            return inc

        package = None
        if embedded:
            assembly, _, resource = path.partition(":")
            root = self.resource_roots.get(assembly)
            if root is None and self.packages is not None:
                res = self.packages.resolve(assembly, resource)
                inc.package, inc.package_version = res.package, res.version
                inc.pinned, inc.origin = res.pinned, res.origin
                if res.status != "ok":
                    inc.status, inc.note = res.status, res.note
                    return inc
                candidate = res.path
                package = (res.package, res.version, f"{assembly}.{resource}")
            elif root is None:
                inc.note = (f"embedded resource of assembly '{assembly}'; pass "
                            f"--resource-root {assembly}=DIR to check inside it")
                return inc
            else:
                candidate = _find_resource(root, resource)
                if candidate is None:
                    inc.status = "missing"
                    inc.note = f"resource '{resource}' not found under {root}"
                    return inc
                # another assembly's module, read from its source: no version
                package = (assembly, None, f"{assembly}.{resource}")
        elif _WINDOWS_ABSOLUTE.match(path) and os.name != "nt":
            inc.note = "absolute Windows path; cannot be checked on this machine"
            return inc
        else:
            candidate = Path(path.replace("\\", "/"))
            if not candidate.is_absolute():
                candidate = self.base_dir / candidate
            if not candidate.exists():
                inc.status = "missing"
                inc.resolved = candidate
                inc.note = f"looked for {candidate}"
                return inc

        candidate = candidate.resolve()
        inc.resolved = candidate
        if candidate in stack:
            inc.status = "recursive"
            chain = " -> ".join(p.name for p in stack + (candidate,))
            inc.note = f"include cycle: {chain}"
            return inc
        try:
            root_el, namespaces = self.read(str(candidate))
        except WorkflowLoadError as exc:
            inc.status, inc.note = "invalid", str(exc)
            return inc
        if candidate not in self.included_files:
            self.included_files.append(candidate)
        inc.namespaces = namespaces
        node.include = inc  # needed by apply_include_overrides during parsing
        body = _child(root_el, "Workflow")
        inc.workflow = self.parse_workflow(body if body is not None else ET.Element("Workflow"),
                                           namespaces, candidate, node, stack + (candidate,),
                                           from_include=True, package=package)
        inc.status = "ok"
        return inc

    @staticmethod
    def apply_include_overrides(wf: Workflow) -> None:
        """Values written on an IncludeWorkflow element set the included file's
        externalized properties. Apply them so checks see effective values."""
        owner = wf.owner
        if owner is None or not owner.is_include or owner.include is None:
            return
        for key, value in list(owner.include.overrides.items()):
            assign_external(wf, key, value)


# --------------------------------------------------------------------------- properties
#
# A workflow's own properties are the entries of its enabled ExternalizedMapping
# nodes, named DisplayName or else Name (Bonsai.Core WorkflowTypeDescriptor).
# Setting one sets the mapped property on every node the mapping feeds. Names
# are unique in any workflow Bonsai builds: it refuses a workflow where two
# share one (checks.DUPLICATE_PROPERTY), so taking the first match below only
# matters for workflows that never run. A target that is itself a workflow (a group,
# SelectMany, ...) exposes its inner workflow's properties, so the value goes on
# down; an IncludeWorkflow stores the value on its own element and passes it on
# to the included file.

def externalized_properties(wf: Workflow) -> list:
    """``(name, mapping node, mapped property)`` for each property ``wf`` exposes,
    in Bonsai's order."""
    out = []
    for node in wf.nodes:
        if node.disabled or not node.type.is_core("ExternalizedMapping"):
            continue
        for prop, display in node.mappings:
            if prop:
                out.append((display or prop, node, prop))
    return out


def _inner_workflow(target: Node) -> Optional[Workflow]:
    if target.is_include:
        return target.include.workflow if target.include is not None else None
    return target.workflow


def _exposes(target: Node, prop: str) -> Optional[bool]:
    """Whether ``target`` has property ``prop``: True/False when baghban can tell
    (a group or a resolved include), None for an operator, whose .NET type
    baghban cannot see."""
    if target.workflow is None and not target.is_include:
        return None
    inner = _inner_workflow(target)
    if inner is None:
        return None
    return any(name == prop for name, _, _ in externalized_properties(inner))


def find_external(wf: Workflow, key: str) -> Optional[tuple]:
    """The ``(mapping node, mapped property)`` Bonsai would use for ``key``."""
    for name, mapping, prop in externalized_properties(wf):
        if name == key and all(_exposes(t, prop) is not False for t in mapping.successors()):
            return mapping, prop
    return None


def assign_external(wf: Workflow, key: str, value: str) -> list:
    """Set workflow property ``key`` of ``wf`` to ``value`` as Bonsai would, so
    every node it reaches holds the effective value. Returns the nodes the
    mapping feeds (empty when ``wf`` has no such property)."""
    found = find_external(wf, key)
    if found is None:
        return []
    mapping, prop = found
    targets = mapping.successors()
    for target in targets:
        if target.is_include:
            target.properties[prop] = value
            target.overridden.add(prop)
            if target.include is not None:
                target.include.overrides[prop] = value
                if target.include.workflow is not None:
                    assign_external(target.include.workflow, prop, value)
        elif target.workflow is not None:
            assign_external(target.workflow, prop, value)
        else:
            target.properties[prop] = value
            target.overridden.add(prop)
    return targets


def target_values(target: Node, prop: str) -> set:
    """Effective value(s) of ``prop`` on ``target``, looking inside groups and
    includes, whose values live on the nodes they map to."""
    if target.is_include and prop in target.properties:
        return {target.properties[prop]}
    inner = _inner_workflow(target) if (target.is_include or target.workflow is not None) else None
    if inner is None:
        return {target.properties.get(prop, "")}
    found = find_external(inner, prop)
    if found is None:
        return {""}
    mapping, inner_prop = found
    values = set()
    for t in mapping.successors():
        values |= target_values(t, inner_prop)
    return values or {""}


def _flatten(el: ET.Element, prefix: str, out: dict, namespaces: dict,
             loader: _Loader, skip_workflow: bool = False) -> None:
    """Flatten child elements into sorted, dotted keys (as daftar does)."""
    children = list(el)
    counts: dict[str, int] = {}
    for c in children:
        counts[_local(c.tag)] = counts.get(_local(c.tag), 0) + 1
    seen: dict[str, int] = {}
    for c in children:
        tag = _local(c.tag)
        if skip_workflow and not prefix and tag == "Workflow":
            continue
        key = prefix + tag
        if counts[tag] > 1:
            key += f"[{seen.get(tag, 0)}]"
            seen[tag] = seen.get(tag, 0) + 1
        if c.get(XSI_TYPE):
            out[key + "@type"] = loader.resolve_type(c.get(XSI_TYPE), namespaces).name
        for attr, value in c.attrib.items():
            if attr != XSI_TYPE:
                out[key + "@" + _local(attr)] = value
        if len(c):
            _flatten(c, key + ".", out, namespaces, loader)
        else:
            text = (c.text or "").strip()
            if text or not c.attrib:
                out[key] = text


def _find_resource(root: Path, resource: str) -> Optional[Path]:
    """Map a manifest resource name (dots for folders) back to a file under root."""
    stem, ext = os.path.splitext(resource)
    parts = stem.split(".")
    for i in range(len(parts)):
        candidate = root.joinpath(*parts[:i], ".".join(parts[i:]) + ext)
        if candidate.exists():
            return candidate
    return None


# --------------------------------------------------------------------------- API

def load(path, resource_roots: Optional[dict] = None, base_dir=None,
         discover: bool = True, packages=None, fetch: bool = False,
         pins: Optional[dict] = None, cache_dir=None) -> Document:
    """Load a ``.bonsai`` file and resolve its includes.

    ``resource_roots`` maps an assembly name to the folder holding its source,
    so embedded-resource includes (``Path="MyPackage:Module.bonsai"``) can be
    followed, e.g. ``{"Bonsai.Core.Tests": "bonsai/Bonsai.Core.Tests"}``.
    With ``discover`` (the default), package projects in the surrounding git
    repository that embed workflows are found and added automatically.

    Files under an ``Extensions`` folder or inside such a package project are
    loaded as modules (``Document.kind``); an Extensions module resolves its
    includes from the project folder, as the editor does.

    Includes into packages from elsewhere (``Path="BonVision:..."``) are read out
    of the package DLL (see :mod:`baghban.packages`): versions come from the
    workflow's ``.bonsai/Bonsai.config`` or ``pins`` (``{"BonVision": "0.13.0"}``);
    DLLs from the installed environment, ``~/.nuget/packages`` or baghban's
    cache, and from nuget.org only with ``fetch=True``. Pass a ``PackageResolver``
    as ``packages`` to share one across files, or ``packages=False`` to skip.
    """
    from .project import classify, discover_projects, repository_root
    path = Path(path)
    projects = discover_projects(path) if discover else []
    # every embedding project can resolve includes; only non-test projects make
    # their files modules (test projects embed fixtures that run top-level)
    roots = {}
    for name, folder, _is_test in projects:
        roots.setdefault(name, folder)
    project_folders = {name: folder for name, folder, is_test in projects if not is_test}
    roots.update({k: Path(v) for k, v in (resource_roots or {}).items()})
    kind, project = classify(path, project_folders)
    if kind == "extension":
        try:  # only trust an Extensions folder inside the repository
            project.resolve().relative_to(repository_root(path))
        except ValueError:
            kind, project = "workflow", None
    if base_dir is not None:
        base = Path(base_dir)
    elif kind == "extension":
        base = project
    else:
        base = path.resolve().parent
    resolver = _resolver(packages, path, fetch, pins, cache_dir)
    loader = _Loader(base, roots, resolver)
    root, namespaces = loader.read(str(path))
    body = _child(root, "Workflow")
    if body is None:
        raise WorkflowLoadError(f"{path}: <WorkflowBuilder> has no <Workflow>")
    wf = loader.parse_workflow(body, namespaces, path, None, (path.resolve(),), False)
    return Document(path=path, version=root.get("Version"), namespaces=namespaces,
                    workflow=wf, base_dir=base, included_files=loader.included_files,
                    kind=kind, packages=resolver)


def _resolver(packages, where, fetch, pins, cache_dir):
    if packages is False:
        return None
    if packages is not None:
        return packages
    from .packages import PackageResolver
    return PackageResolver.for_workflow(where, fetch=fetch, pins=pins, cache_dir=cache_dir)


def loads(text: str, resource_roots: Optional[dict] = None, base_dir=".",
          kind: str = "workflow", packages=None, fetch: bool = False,
          pins: Optional[dict] = None, cache_dir=None) -> Document:
    """Load a workflow from a string (includes resolve against ``base_dir``)."""
    import io
    base = Path(base_dir)
    resolver = _resolver(packages, base, fetch, pins, cache_dir)
    loader = _Loader(base, resource_roots, resolver)
    root, namespaces = loader.read(io.BytesIO(text.encode("utf-8")))
    body = _child(root, "Workflow")
    if body is None:
        raise WorkflowLoadError("<WorkflowBuilder> has no <Workflow>")
    wf = loader.parse_workflow(body, namespaces, None, None, (), False)
    return Document(path=None, version=root.get("Version"), namespaces=namespaces,
                    workflow=wf, base_dir=base, included_files=loader.included_files,
                    kind=kind, packages=resolver)
