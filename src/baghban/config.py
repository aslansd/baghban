"""Marking findings as intended.

A finding describes what Bonsai will do; whether that is a mistake can depend
on what the workflow is for. A demo that rewrites one scratch file on every
run *wants* ``Overwrite=True`` (neurogears/vestibular-vr#137). Such a finding
can be marked as intended:

* on the command line: ``baghban check --ignore SILENT_OVERWRITE`` (everywhere)
  or ``--ignore SILENT_OVERWRITE:src/Workflows/GNGTemplate.bonsai`` (one file);
* in a ``baghban.toml`` next to the workflows (or a ``[tool.baghban]`` table in
  ``pyproject.toml``), found by looking upward from the workflow, not past
  the repository's root::

      ignore = ["APPENDS_ACROSS_RUNS"]          # everywhere below this folder

      [per-file-ignores]
      "src/Workflows/GNGTemplate.bonsai" = ["SILENT_OVERWRITE"]
      "docs/*" = ["DANGLING_SUBJECT"]

Patterns are shell-style (``*`` also matches ``/``), relative to the folder of
the configuration file (or to the current folder for ``--ignore``). They are
matched against the checked workflow and against the file that holds the
node, so a module's finding can be marked in the module's own file.

Ignored findings are not hidden: reports count and list them, and they never
change what the other checks see. An unknown finding code is an error, so a
misspelt rule does not silently stop working.

Reading the file needs ``tomllib`` (Python 3.11 and later) or, on Python 3.10,
the ``tomli`` package.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CONFIG_FILE = "baghban.toml"
_PYPROJECT_TABLE = re.compile(r"^\s*\[\s*tool\s*\.\s*baghban\s*[\].]", re.MULTILINE)


class ConfigError(ValueError):
    """A configuration file or ``--ignore`` rule baghban cannot use."""


@dataclass(frozen=True)
class IgnoreRule:
    """Findings with ``code`` (in files matching ``pattern``) are intended."""

    code: str
    pattern: Optional[str] = None
    base: Optional[Path] = None  # patterns are relative to this folder
    source: str = "--ignore"  # where the rule came from, for reports

    def describe(self) -> str:
        where = f" in {self.pattern}" if self.pattern else ""
        return f"{self.code}{where} ({self.source})"

    def matches(self, finding, checked: Optional[str]) -> bool:
        if finding.code != self.code:
            return False
        if self.pattern is None:
            return True
        return any(self._matches_path(p) for p in (checked, finding.file) if p)

    def _matches_path(self, path: str) -> bool:
        pattern = self.pattern.replace("\\", "/")
        p = Path(path)
        names = [p.as_posix()]
        if self.base is not None:
            try:
                names.insert(0, p.resolve().relative_to(self.base.resolve()).as_posix())
            except (ValueError, OSError):
                pass
        return any(fnmatch.fnmatch(n, pattern) or fnmatch.fnmatch(n, "*/" + pattern)
                   for n in names)


def _known(code: str, source: str) -> str:
    from .checks import FINDINGS
    if code not in FINDINGS:
        raise ConfigError(f"{source}: unknown finding code '{code}' "
                          f"(known: {', '.join(sorted(FINDINGS))})")
    return code


def parse_ignore(text: str, base=None, source: str = "--ignore") -> IgnoreRule:
    """``CODE`` or ``CODE:PATTERN``, as ``--ignore`` takes it."""
    code, sep, pattern = text.strip().partition(":")
    if not code or (sep and not pattern):
        raise ConfigError(f"{source}: expected CODE or CODE:PATTERN, got '{text}'")
    return IgnoreRule(_known(code.strip(), source), pattern.strip() or None,
                      Path(base) if base is not None else Path.cwd(), source)


def _has_table(pyproject: Path) -> bool:
    try:
        return bool(_PYPROJECT_TABLE.search(pyproject.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError):
        return False


def find_config(start) -> Optional[Path]:
    """The ``baghban.toml`` (or ``pyproject.toml`` with ``[tool.baghban]``)
    nearest above ``start``, without leaving the repository it is in."""
    here = Path(start).resolve()
    folder = here if here.is_dir() else here.parent
    for d in (folder, *folder.parents):
        if (d / CONFIG_FILE).is_file():
            return d / CONFIG_FILE
        if (d / "pyproject.toml").is_file() and _has_table(d / "pyproject.toml"):
            return d / "pyproject.toml"
        if (d / ".git").exists():
            return None
    return None


def _toml(path: Path) -> dict:
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10
        try:
            import tomli as tomllib
        except ModuleNotFoundError:
            raise ConfigError(f"{path}: reading it needs Python 3.11 or later, or "
                              "`pip install tomli` on Python 3.10") from None
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def read_config(path) -> list:
    """The ignore rules in a ``baghban.toml`` or ``pyproject.toml``."""
    path = Path(path)
    data = _toml(path)
    if path.name == "pyproject.toml":
        data = data.get("tool", {}).get("baghban", {})
    source = path.name
    unknown = set(data) - {"ignore", "per-file-ignores"}
    if unknown:
        raise ConfigError(f"{path}: unknown setting(s) {', '.join(sorted(unknown))} "
                          "(baghban reads 'ignore' and 'per-file-ignores')")
    rules = []
    codes = data.get("ignore", [])
    if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
        raise ConfigError(f"{path}: 'ignore' must be a list of finding codes")
    for code in codes:
        rules.append(IgnoreRule(_known(code, f"{path}"), None, path.parent, source))
    per_file = data.get("per-file-ignores", {})
    if not isinstance(per_file, dict):
        raise ConfigError(f"{path}: 'per-file-ignores' must map patterns to lists of codes")
    for pattern, codes in per_file.items():
        if isinstance(codes, str):
            codes = [codes]
        if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
            raise ConfigError(f"{path}: per-file-ignores '{pattern}' must be a list of codes")
        for code in codes:
            rules.append(IgnoreRule(_known(code, f"{path}"), pattern, path.parent, source))
    return rules


def apply_ignores(report, rules) -> None:
    """Move the findings ``rules`` mark as intended to ``report.ignored``."""
    rules = [parse_ignore(r) if isinstance(r, str) else r for r in rules or ()]
    if not rules:
        return
    kept = []
    for f in report.findings:
        rule = next((r for r in rules if r.matches(f, report.path)), None)
        if rule is None:
            kept.append(f)
        else:
            report.ignored.append((f, rule))
    report.findings = kept
