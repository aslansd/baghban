"""Where a ``.bonsai`` file sits decides what it is.

Bonsai has two conventions for workflows that are *modules*, meant to be
included by another workflow rather than run on their own:

* **Extensions modules.** The editor lists every ``.bonsai`` file under the
  ``Extensions`` folder next to a workflow as a toolbox element
  (``Project.EnumerateExtensionWorkflows`` in Bonsai.Editor/Project.cs).
  Workflows include them as ``Path="Extensions\\Module.bonsai"``, resolved
  from the project folder, the parent of ``Extensions``.
* **Package modules.** A Bonsai package project embeds its workflows with
  ``<EmbeddedResource Include="**\\*.bonsai" />`` in its ``.csproj``;
  workflows include them as ``Path="Assembly:Folder.Module.bonsai"``.

A module may rely on its includer: subscribing to subjects the includer
declares, or taking a subject's name from an externalized property. Those
are its interface, not errors. And a repository that contains package
projects tells baghban where their embedded workflows live, so includes
between them can be followed without ``--resource-root``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

_EMBEDS_BONSAI = re.compile(r"<EmbeddedResource\s+Include=\"[^\"]*\.bonsai\"", re.I)
_ASSEMBLY_NAME = re.compile(r"<AssemblyName>\s*([^<\s]+)\s*</AssemblyName>")
_SKIP_DIRS = {".git", "bin", "obj", "node_modules", ".bonsai", "Packages"}


def _embedding_project(csproj: Path) -> Optional[tuple]:
    """(assembly name, is_test) of a project that embeds .bonsai files, else None."""
    try:
        text = csproj.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not _EMBEDS_BONSAI.search(text):
        return None
    match = _ASSEMBLY_NAME.search(text)
    return (match.group(1) if match else csproj.stem), _is_test_project(csproj, text)


def _is_test_project(csproj: Path, text: str) -> bool:
    return (csproj.stem.endswith((".Tests", ".Test"))
            or "Microsoft.NET.Test.Sdk" in text
            or re.search(r"<IsTestProject>\s*true", text, re.I) is not None)


def repository_root(path: Path, max_up: int = 8) -> Path:
    """Nearest ancestor holding ``.git``; failing that, the highest one holding
    a ``.sln``; failing that, the file's own folder."""
    start = path.resolve().parent
    ancestors = [start, *list(start.parents)[: max_up - 1]]
    for folder in ancestors:
        if (folder / ".git").exists():
            return folder
    solution_dirs = [f for f in ancestors if any(f.glob("*.sln"))]
    return solution_dirs[-1] if solution_dirs else start


def discover_projects(path: Path) -> list:
    """(assembly name, project folder, is_test) for every project in the
    repository around ``path`` that embeds workflows."""
    root = repository_root(path)
    found = []
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in _SKIP_DIRS and not entry.name.startswith("."):
                    stack.append(entry)
            elif entry.suffix == ".csproj":
                info = _embedding_project(entry)
                if info:
                    found.append((info[0], folder, info[1]))
    return found


def discover_resource_roots(path: Path) -> dict:
    """Assembly name -> project folder, for following embedded includes."""
    roots: dict = {}
    for name, folder, _is_test in discover_projects(path):
        roots.setdefault(name, folder)
    return roots


def classify(path: Path, resource_roots: dict) -> tuple[str, Optional[Path]]:
    """Return (kind, project folder) with kind in workflow | extension | package."""
    resolved = path.resolve()
    for parent in resolved.parents:
        if parent.name == "Extensions":
            return "extension", parent.parent
    for folder in resource_roots.values():
        try:
            resolved.relative_to(Path(folder).resolve())
            return "package", Path(folder)
        except ValueError:
            continue
    return "workflow", None
