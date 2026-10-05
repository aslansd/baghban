"""baghban (باغبان, bağban: gardener) — tend Bonsai workflows from Python.

Check, draw and compare Bonsai (bonsai-rx.org) workflow files on any
machine, macOS included, without Windows or .NET. Standard library only.

    import baghban
    doc = baghban.load("rig/foraging.bonsai")
    print(baghban.check(doc).summary())
"""

__version__ = "0.2.2"

from .model import Document, Node, Workflow, TypeRef, Include, WorkflowLoadError, load, loads
from .checks import Finding, Report, check, FINDINGS
from .diff import diff, WorkflowDiff
from .info import dependencies, parameters, fingerprint, manifest_fields
from .render import outline, mermaid, dot, html

__all__ = [
    "Document", "Node", "Workflow", "TypeRef", "Include", "WorkflowLoadError", "load", "loads",
    "Finding", "Report", "check", "FINDINGS", "diff", "WorkflowDiff", "dependencies",
    "parameters", "fingerprint", "manifest_fields", "outline", "mermaid", "dot", "html",
]
