"""Draw a workflow without the Bonsai editor.

``outline`` prints a tree in the terminal. ``mermaid`` and ``dot`` emit text
that GitHub, VS Code or Graphviz render. ``html`` writes a single page that
opens in any browser (it loads the Mermaid script from a CDN), with the
check findings highlighted on the graph.
"""

from __future__ import annotations

import html as _html
from typing import Optional

from .model import Document, Node, Workflow

_SKIP_PROPS = ("Name",)


def _props_preview(node: Node, limit: int = 3, width: int = 60) -> str:
    skip = set(_SKIP_PROPS)
    if node.filename_property:
        skip.add(node.filename_property)  # already in the label
    items = [(k, v) for k, v in node.properties.items()
             if k not in skip and "@" not in k and v != "" and "." not in k]
    text = " ".join(f"{k}={v}" for k, v in items[:limit])
    if len(items) > limit:
        text += " ..."
    return text if len(text) <= width else text[: width - 3] + "..."


# --------------------------------------------------------------------------- outline

def outline(doc: Document, show_properties: bool = True) -> str:
    title = doc.path.name if doc.path else "<workflow>"
    lines = [f"{title}  (Bonsai {doc.version or '?'})"]

    def visit(wf: Workflow, prefix: str) -> None:
        for i, node in enumerate(wf.nodes):
            last = i == len(wf.nodes) - 1
            branch = "`- " if last else "|- "
            flags = " [disabled]" if node.disabled else ""
            if node.is_include and node.include and node.include.status != "ok":
                flags += f" [{node.include.status}]"
            props = ""
            if show_properties:
                if node.mappings:
                    kind = "exposes" if node.type.name == "ExternalizedMapping" else "sets"
                    props = f"  {kind} " + ", ".join(
                        f"{n} as {d}" if d else n for n, d in node.mappings)
                elif not (node.is_group or node.is_include or node.is_subject_declaration
                          or node.is_subject_use):
                    props = f"  {_props_preview(node)}"
            lines.append(f"{prefix}{branch}{node.index:>2} {node.label()}{flags}{props}".rstrip())
            if node.workflow is not None:
                visit(node.workflow, prefix + ("   " if last else "|  "))

    visit(doc.workflow, "")
    return "\n".join(lines)


# --------------------------------------------------------------------------- mermaid

def _mid(node: Node) -> str:
    return "n_" + "_".join(str(i) for i in node.id)


def _mlabel(text: str) -> str:
    return text.replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")


def mermaid(doc: Document, findings=None, direction: str = "LR") -> str:
    severity = _severity_by_node(findings)
    lines = [f"flowchart {direction}"]
    styles = []

    def entry(node: Node) -> str:
        return _mid(node)

    def visit(wf: Workflow, indent: str) -> None:
        for node in wf.nodes:
            nid = _mid(node)
            if node.workflow is not None:
                lines.append(f'{indent}subgraph {nid} ["{_mlabel(node.label())}"]')
                lines.append(f"{indent}  direction {direction}")
                visit(node.workflow, indent + "  ")
                lines.append(f"{indent}end")
            else:
                lines.append(f'{indent}{nid}["{_mlabel(node.label())}"]')
            if node.disabled:
                styles.append(f"style {nid} stroke-dasharray: 5 5,opacity:0.6")
            sev = severity.get(node.id)
            if sev == "error":
                styles.append(f"style {nid} stroke:#d62728,stroke-width:3px")
            elif sev == "warning":
                styles.append(f"style {nid} stroke:#ff9f1c,stroke-width:3px")
        for e in wf.edges:
            if 0 <= e.source < len(wf.nodes) and 0 <= e.target < len(wf.nodes):
                label = "" if e.label == "Source1" else f"|{e.label}|"
                lines.append(f"{indent}{entry(wf.nodes[e.source])} -->{label} {entry(wf.nodes[e.target])}")

    visit(doc.workflow, "  ")
    lines.extend("  " + s for s in styles)
    return "\n".join(lines)


# --------------------------------------------------------------------------- graphviz

def dot(doc: Document, findings=None) -> str:
    severity = _severity_by_node(findings)
    lines = ["digraph workflow {", "  compound=true;", "  rankdir=LR;",
             '  node [shape=box, style="rounded", fontname="Helvetica"];']

    def anchor(node: Node) -> str:
        return _mid(node) + ("_anchor" if node.workflow is not None else "")

    def visit(wf: Workflow, indent: str) -> None:
        for node in wf.nodes:
            nid = _mid(node)
            attrs = [f'label="{_dot_escape(node.label())}"']
            if node.disabled:
                attrs.append('style="rounded,dashed"')
            sev = severity.get(node.id)
            if sev == "error":
                attrs.append('color="#d62728", penwidth=2.5')
            elif sev == "warning":
                attrs.append('color="#ff9f1c", penwidth=2.5')
            if node.workflow is not None:
                lines.append(f"{indent}subgraph cluster_{nid} {{")
                lines.append(f'{indent}  label="{_dot_escape(node.label())}";')
                lines.append(f'{indent}  {nid}_anchor [shape=point, style=invis];')
                visit(node.workflow, indent + "  ")
                lines.append(f"{indent}}}")
            else:
                lines.append(f"{indent}{nid} [{', '.join(attrs)}];")
        for e in wf.edges:
            if 0 <= e.source < len(wf.nodes) and 0 <= e.target < len(wf.nodes):
                src, dst = wf.nodes[e.source], wf.nodes[e.target]
                extra = []
                if src.workflow is not None:
                    extra.append(f"ltail=cluster_{_mid(src)}")
                if dst.workflow is not None:
                    extra.append(f"lhead=cluster_{_mid(dst)}")
                if e.label != "Source1":
                    extra.append(f'label="{e.label}"')
                attr = f" [{', '.join(extra)}]" if extra else ""
                lines.append(f"{indent}{anchor(src)} -> {anchor(dst)}{attr};")

    visit(doc.workflow, "  ")
    lines.append("}")
    return "\n".join(lines)


def _dot_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


# --------------------------------------------------------------------------- html

MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"


def html(doc: Document, report=None) -> str:
    findings = report.findings if report is not None else None
    title = doc.path.name if doc.path else "workflow"
    rows = ""
    if report is not None:
        for f in report.findings:
            rows += (f"<tr class='{f.severity}'><td>{f.severity}</td><td>{f.code}</td>"
                     f"<td>{_html.escape(f.location)}</td><td>{_html.escape(f.message)}</td></tr>")
        if not report.findings:
            rows = "<tr><td colspan='4'>No findings.</td></tr>"
    table = ("<h2>Findings</h2><table><tr><th>severity</th><th>code</th><th>where</th>"
             f"<th>what</th></tr>{rows}</table>") if report is not None else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_html.escape(title)} - baghban</title>
<style>
 body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; margin: 2rem; color: #222; }}
 .graph {{ overflow-x: auto; border: 1px solid #ddd; padding: 1rem; border-radius: 6px; }}
 table {{ border-collapse: collapse; margin-top: .5rem; }}
 td, th {{ border: 1px solid #ddd; padding: .35rem .6rem; text-align: left; vertical-align: top; }}
 tr.error td:first-child {{ color: #d62728; font-weight: 600; }}
 tr.warning td:first-child {{ color: #c77700; font-weight: 600; }}
 pre.outline {{ background: #f6f6f6; padding: 1rem; overflow-x: auto; }}
</style></head><body>
<h1>{_html.escape(title)}</h1>
<p>Bonsai {_html.escape(doc.version or "?")} &middot; rendered by baghban</p>
<div class="graph"><pre class="mermaid">
{_html.escape(mermaid(doc, findings))}
</pre></div>
{table}
<h2>Outline</h2><pre class="outline">{_html.escape(outline(doc))}</pre>
<script src="{MERMAID_CDN}"></script>
<script>mermaid.initialize({{ startOnLoad: true, securityLevel: "strict" }});</script>
</body></html>
"""


def _severity_by_node(findings) -> dict:
    order = {"error": 0, "warning": 1, "info": 2}
    out: dict = {}
    for f in findings or []:
        current = out.get(f.node)
        if current is None or order[f.severity] < order[current]:
            out[f.node] = f.severity
    return out
