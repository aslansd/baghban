"""Recall: plant known faults in real rigs and see whether baghban finds them.

The survey measures precision: is what baghban reports true? This measures the
other half: of faults that are certainly there, how many does it report? It
takes real workflows from the survey's clones, plants one fault at a time, and
checks the planted workflow. A fault counts as found when baghban reports the
expected finding at the planted node and did not report it there before.

Every planted fault has a certain effect on Bonsai, whatever the rest of the
workflow does:

    dangling_subject     a SubscribeSubject renamed to a name declared nowhere
                         (Bonsai cannot build it)              -> DANGLING_SUBJECT
    unnamed_subject      a SubscribeSubject with nodes after it loses its name
                         (Bonsai cannot build it)              -> UNNAMED_SUBJECT
    duplicate_subject    a subject declaration copied into the same workflow,
                         with the same inputs (build error)    -> DUPLICATE_SUBJECT
    duplicate_property   an ExternalizedMapping copied into the same workflow,
                         feeding the same nodes (build error)  -> DUPLICATE_PROPERTY
    missing_include      an include pointed at a file that does not exist
                                                               -> MISSING_INCLUDE
    disabled_writer      a writer disabled (nothing written)   -> DISABLED_WRITER
    appends              a CsvWriter set to Append, no suffix  -> APPENDS_ACROSS_RUNS
    overwrites           a writer set to Overwrite, no suffix  -> SILENT_OVERWRITE
    duplicate_output     a second writer given the first's file name, no suffix
                                                               -> DUPLICATE_OUTPUT

Faults inside loops are not planted: whether a loop really repeats can depend
on more than the file shows, so the ground truth would not be certain.

Only nodes defined in the checked file itself are planted (not inside its
includes), in entry workflows (not modules, whose subjects come from an
includer). Each planted workflow is written next to the original, so its
includes resolve as before, and removed afterwards.

    python survey/seed_faults.py WORKDIR                 # the survey's clones
    python survey/seed_faults.py WORKDIR --per-repo 3 --seed 1 --out recall.json

Needs lxml (``pip install lxml``), which keeps every namespace prefix intact:
Bonsai reads ``xsi:type="rx:Timer"`` through prefixes that ElementTree would
rename.
"""

from __future__ import annotations

import argparse
import collections
import copy
import json
import random
import sys
from pathlib import Path

try:
    from lxml import etree
except ImportError:  # pragma: no cover
    sys.exit("seed_faults.py needs lxml: pip install lxml")

import baghban
from baghban.cli import _collect
from baghban.flow import data_inputs

XSI = "http://www.w3.org/2001/XMLSchema-instance"
XSI_TYPE = f"{{{XSI}}}type"
SEEDED_NAME = "BaghbanSeededNoSuchSubject"
EXPECTED = {
    "dangling_subject": "DANGLING_SUBJECT", "unnamed_subject": "UNNAMED_SUBJECT",
    "duplicate_subject": "DUPLICATE_SUBJECT", "duplicate_property": "DUPLICATE_PROPERTY",
    "missing_include": "MISSING_INCLUDE", "disabled_writer": "DISABLED_WRITER",
    "appends": "APPENDS_ACROSS_RUNS", "overwrites": "SILENT_OVERWRITE",
    "duplicate_output": "DUPLICATE_OUTPUT",
}


# ----------------------------------------------------------------------------- the XML side

def local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def child(el, name):
    return next((c for c in el if local(c.tag) == name), None)


def type_name(el) -> str:
    return (el.get(XSI_TYPE) or "").rpartition(":")[2]


def body_of(expr):
    """The element holding the operator's properties, as baghban's loader finds
    it: under a Disable's Builder, and under a Combinator/Source wrapper."""
    el = expr
    if type_name(el) == "Disable" and child(el, "Builder") is not None:
        el = child(el, "Builder")
    if type_name(el) in ("Combinator", "Source"):
        inner = child(el, "Combinator" if type_name(el) == "Combinator" else "Generator")
        if inner is not None and inner.get(XSI_TYPE):
            return inner
    return el


def workflow_el(container_body):
    return child(container_body, "Workflow")


def expressions(wf_el):
    nodes = child(wf_el, "Nodes")
    return [] if nodes is None else [c for c in nodes if local(c.tag) == "Expression"]


def element_for(root, path):
    """The <Expression> at a baghban Node.id path in the file's own tree."""
    wf = child(root, "Workflow")
    expr = None
    for depth, i in enumerate(path):
        exprs = expressions(wf)
        expr = exprs[i]
        if depth < len(path) - 1:
            wf = workflow_el(body_of(expr))
            if wf is None:
                raise LookupError(path)
    return expr


def set_prop(body, name, value):
    """Set a property element of the operator, in the namespace its other
    properties use."""
    for c in body:
        if local(c.tag) == name:
            c.text = value
            return
    ns = next((c.tag.split("}")[0][1:] for c in body if isinstance(c.tag, str)
               and c.tag.startswith("{") and c.tag.split("}")[0][1:] != XSI), None)
    tag = f"{{{ns}}}{name}" if ns else name
    new = etree.SubElement(body, tag)
    new.text = value


def copy_into_same_workflow(expr, extra_edges):
    """Append a copy of ``expr`` to its own Nodes; edges given as (from, to,
    label) with None standing for the copy. Returns the copy's index."""
    nodes = expr.getparent()
    wf = nodes.getparent()
    dup = copy.deepcopy(expr)
    nodes.append(dup)
    index = len(expressions(wf)) - 1
    edges = child(wf, "Edges")
    if edges is None:
        edges = etree.SubElement(wf, (wf.tag.split("}")[0] + "}" if "}" in wf.tag else "")
                                 + "Edges")
    edge_tag = (wf.tag.split("}")[0] + "}" if "}" in wf.tag else "") + "Edge"
    for a, b, label in extra_edges:
        e = etree.SubElement(edges, edge_tag)
        e.set("From", str(index if a is None else a))
        e.set("To", str(index if b is None else b))
        e.set("Label", label)
    return index


def edge_labels(node):
    wf = node.parent
    return {(e.source, e.target): e.label for e in wf.edges}


# ----------------------------------------------------------------------------- sites

def own_nodes(doc):
    """Nodes defined in the checked file itself: no include on the path."""
    for n in doc.walk():
        if n.file is None or Path(n.file) != Path(doc.path) or n.in_package:
            continue
        if any(c.is_include for c in n.containers()):
            continue
        if n.is_effectively_disabled():
            continue
        yield n


def writable(n):
    prop = n.filename_property
    if not n.is_writer or prop is None or prop in n.mapped():
        return False
    fname = n.properties.get(prop, "") or ""
    return bool(fname) and not fname.startswith(">")


def sites(doc):
    """(kind, node, extra) for every plantable site."""
    out = []
    nodes = list(own_nodes(doc))
    writers = [n for n in nodes if writable(n)]
    for n in nodes:
        named = "Name" not in n.externalized()  # an externalized name is set from outside
        if n.type.is_core("SubscribeSubject") and n.name and named:
            out.append(("dangling_subject", n, None))
            if any(not s.type.is_core("ExternalizedMapping") for s in n.successors()):
                out.append(("unnamed_subject", n, None))
        if n.is_subject_declaration and n.name and named:
            out.append(("duplicate_subject", n, None))
        if n.type.is_core("ExternalizedMapping") and n.mappings and n.successors():
            out.append(("duplicate_property", n, None))
        if n.is_include and n.include is not None and n.include.status == "ok" \
                and ":" not in n.include.path:
            out.append(("missing_include", n, None))
    for n in writers:
        out.append(("disabled_writer", n, None))
        if n.type.name == "CsvWriter":
            out.append(("appends", n, None))
        if "Overwrite" in n.properties or n.type.name == "CsvWriter":
            out.append(("overwrites", n, None))
    if len(writers) >= 2:
        for a, b in zip(writers, writers[1:]):
            out.append(("duplicate_output", b, a))
    return out


def plant(root, kind, node, extra):
    """Change the tree; returns the node locations the finding may be at."""
    expr = element_for(root, node.id)
    body = body_of(expr)
    if kind == "dangling_subject":
        set_prop(body, "Name", SEEDED_NAME)
        return [node.id]
    if kind == "unnamed_subject":
        for c in list(body):
            if local(c.tag) == "Name":
                body.remove(c)
        return [node.id]
    if kind == "duplicate_subject":
        labels = edge_labels(node)
        ins = [(p.index, None, labels.get((p.index, node.index), "Source1"))
               for p in node.predecessors()]
        i = copy_into_same_workflow(expr, ins)
        return [node.id, node.id[:-1] + (i,)]
    if kind == "duplicate_property":
        labels = edge_labels(node)
        outs = [(None, s.index, labels.get((node.index, s.index), "Source1"))
                for s in node.successors()]
        i = copy_into_same_workflow(expr, outs)
        return [node.id, node.id[:-1] + (i,)]
    if kind == "missing_include":
        body.set("Path", "Extensions/BaghbanSeededMissing.bonsai")
        return [node.id]
    if kind == "disabled_writer":
        # rewrite the element in place: <Expression xsi:type="Disable"><Builder ...>
        # (a new element would re-validate the file's clr-namespace URIs)
        builder = copy.deepcopy(expr)
        builder.tag = (expr.tag.split("}")[0] + "}" if "}" in expr.tag else "") + "Builder"
        disable = _qualified(expr, "Disable")
        for c in list(expr):
            expr.remove(c)
        for k in list(expr.attrib):
            del expr.attrib[k]
        expr.text = None
        expr.set(XSI_TYPE, disable)
        expr.append(builder)
        return [node.id]
    if kind == "appends":
        set_prop(body, "Append", "true")
        set_prop(body, "Suffix", "None")
        set_prop(body, "Overwrite", "false")
        return [node.id]
    if kind == "overwrites":
        set_prop(body, "Overwrite", "true")
        set_prop(body, "Suffix", "None")
        if node.type.name == "CsvWriter":
            set_prop(body, "Append", "false")
        return [node.id]
    if kind == "duplicate_output":
        other = extra
        prop = node.filename_property
        set_prop(body, prop, other.properties[other.filename_property])
        set_prop(body, "Suffix", "None")
        set_prop(body_of(element_for(root, other.id)), "Suffix", "None")
        return [node.id, other.id]
    raise ValueError(kind)


def _qualified(expr, name):
    """A core type name with the prefix the file uses for Bonsai's own
    namespace (usually none)."""
    for prefix, uri in (expr.nsmap or {}).items():
        if uri == "https://bonsai-rx.org/2018/workflow":
            return f"{prefix}:{name}" if prefix else name
    return name


# ----------------------------------------------------------------------------- running

PARSER = etree.XMLParser(recover=True, remove_blank_text=False)  # Bonsai's clr-namespace
# URIs contain spaces, which strict lxml refuses; each file must survive an
# unchanged round trip (same baghban fingerprint) before anything is planted


def round_trips(path, options) -> bool:
    copy_path = path.with_name(f"__baghban_roundtrip__{path.name}")
    try:
        etree.parse(str(path), PARSER).write(str(copy_path), xml_declaration=True,
                                              encoding="utf-8")
        return baghban.fingerprint(baghban.load(copy_path, **options)) == \
            baghban.fingerprint(baghban.load(path, **options))
    except Exception:
        return False
    finally:
        copy_path.unlink(missing_ok=True)


def findings_at(report, code):
    return {f.node for f in report.findings if f.code == code}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("workdir", help="the survey's clones (run_survey.py WORKDIR)")
    p.add_argument("--per-repo", type=int, default=3, help="sites per fault kind per repository")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", default="recall.json")
    p.add_argument("--fetch", action="store_true",
                   help="read packages at their pinned versions, downloading from nuget.org "
                        "(as run_survey.py --fetch); without it, includes from packages are "
                        "unread and checks that depend on them say 'not checked'")
    p.add_argument("--cache", help="baghban package cache (default: ~/.cache/baghban)")
    args = p.parse_args(argv)
    options = {"fetch": args.fetch}
    if args.cache:
        options["cache_dir"] = args.cache
    work = Path(args.workdir).resolve()
    rng = random.Random(args.seed)

    by_kind_repo = collections.defaultdict(list)
    no_round_trip = []
    for f in _collect([work]):
        try:
            doc = baghban.load(f, **options)
        except Exception:
            continue
        if doc.kind != "workflow":
            continue
        if not round_trips(f, options):
            no_round_trip.append(str(f.relative_to(work)))
            continue
        repo = f.resolve().relative_to(work).parts[0]
        report = baghban.check(doc)
        for kind, node, extra in sites(doc):
            if any(f2.code == EXPECTED[kind] and f2.node in (node.id, extra.id if extra else None)
                   for f2 in report.findings):
                continue  # already reported: planting it again would prove nothing
            by_kind_repo[(kind, repo)].append((f, node.id, extra.id if extra else None))

    chosen = []
    for (kind, repo), items in sorted(by_kind_repo.items()):
        rng.shuffle(items)
        chosen += [(kind, repo, *it) for it in items[: args.per_repo]]

    results = []
    for kind, repo, path, node_id, extra_id in chosen:
        code = EXPECTED[kind]
        before = baghban.check(baghban.load(path, **options))
        doc = baghban.load(path, **options)
        node = next(n for n in doc.walk() if n.id == node_id)
        extra = next((n for n in doc.walk() if n.id == extra_id), None)
        tree = etree.parse(str(path), PARSER)
        targets = plant(tree.getroot(), kind, node, extra)
        planted = path.with_name(f"__baghban_seeded__{path.name}")
        try:
            tree.write(str(planted), xml_declaration=True, encoding="utf-8")
            try:
                after_doc = baghban.load(planted, **options)
                after = baghban.check(after_doc)
                error = None
            except Exception as exc:  # a crash is a miss, and a bug
                after, error = None, f"{type(exc).__name__}: {exc}"
        finally:
            planted.unlink(missing_ok=True)
        if after is None:
            found, where = False, error
        else:
            had = findings_at(before, code)
            new = findings_at(after, code) - had
            found = any(t in new for t in targets)
            where = None
            if not found:
                # why not: a "not checked" note about the planted node, if any
                here = [n.location() for n in after_doc.walk() if n.id in targets]
                notes = [s for s in after.skipped if any(h in s for h in here)
                         or SEEDED_NAME in s]
                where = notes[:1] or [f"{f.code} {f.location}" for f in after.findings
                                      if f.code == code][:2] or ["no finding, no note"]
        skipped = len(after.skipped) if after is not None else None
        results.append({"kind": kind, "code": code, "repo": repo,
                        "file": str(path.relative_to(work)), "node": list(node_id),
                        "location": node.location(), "found": found,
                        "not_checked_notes": skipped, "other": where})

    totals = collections.defaultdict(lambda: [0, 0])
    for r in results:
        totals[r["kind"]][0] += r["found"]
        totals[r["kind"]][1] += 1
    print(f"\n{'fault':<20} {'expected':<22} {'found':>9}")
    for kind in EXPECTED:
        if kind in totals:
            f, n = totals[kind]
            print(f"{kind:<20} {EXPECTED[kind]:<22} {f:>4}/{n:<4}")
    f = sum(r["found"] for r in results)
    print(f"\nall: {f}/{len(results)} planted faults found. Files skipped because they do "
          f"not round-trip unchanged: {len(no_round_trip)}")
    for r in results:
        if not r["found"]:
            print(f"  MISSED {r['kind']}: {r['file']} :: {r['location']}  {r['other']}")
    Path(args.out).write_text(json.dumps({"baghban": baghban.__version__, "seed": args.seed,
                                          "per_repo": args.per_repo, "results": results,
                                          "not_round_tripped": no_round_trip},
                                         indent=2))
    print(f"Details: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
