"""baghban command line.

    baghban check  WORKFLOW|DIR ...   problems found before the rig runs (exit 1 on errors)
    baghban show   WORKFLOW           the workflow as a tree
    baghban render WORKFLOW -f html   draw it (html | mermaid | dot)
    baghban diff   A B                what changed, by meaning rather than by line
    baghban deps   WORKFLOW           assemblies/packages and includes it needs
    baghban params WORKFLOW           externalized properties and their values
    baghban fingerprint WORKFLOW      content hash, stable across re-saves
    baghban provenance WORKFLOW       fields recording which protocol a session ran

Commands that read one workflow take -p/--property NAME=VALUE, as Bonsai.exe
does, to see the values a launcher passes instead of the saved ones. check and
render take --ignore CODE[:PATTERN] and read baghban.toml (see baghban.config)
to mark findings as intended.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .checks import check
from .diff import diff
from .info import (dependencies, fingerprint, format_dependencies, format_parameters,
                   parameters, provenance)
from .config import ConfigError, find_config, parse_ignore, read_config
from .launch import set_properties
from .model import WorkflowLoadError, load
from .render import dot, html, mermaid, outline


def _pins(values) -> dict:
    pins = {}
    for item in values or []:
        name, sep, version = item.partition("=")
        if not sep or not name or not version:
            raise SystemExit(f"--package expects ID=VERSION, got '{item}'")
        pins[name] = version
    return pins


def _load_options(args) -> dict:
    return {"resource_roots": _resource_roots(getattr(args, "resource_root", None)),
            "fetch": getattr(args, "fetch", False),
            "pins": _pins(getattr(args, "package", None)),
            "cache_dir": getattr(args, "cache", None)}


def _resource_roots(values) -> dict:
    roots = {}
    for item in values or []:
        name, sep, folder = item.partition("=")
        if not sep:
            raise SystemExit(f"--resource-root expects ASSEMBLY=DIR, got '{item}'")
        roots[name] = folder
    return roots


def _collect(paths, exclude=()) -> list:
    import fnmatch
    files = []
    for p in map(Path, paths):
        if p.is_dir():
            for f in sorted(p.rglob("*.bonsai")):
                if not f.is_file():
                    continue  # a ".bonsai" environment folder, not a workflow
                if any(part.startswith(".") for part in f.relative_to(p).parts[:-1]):
                    continue  # skip .bonsai environment folders and hidden dirs
                files.append(f)
        else:
            files.append(p)
    return [f for f in files
            if not any(fnmatch.fnmatch(f.as_posix(), pat) or fnmatch.fnmatch(f.as_posix(), f"*/{pat}")
                       for pat in exclude)]


def _properties(args) -> dict:
    props = {}
    for item in getattr(args, "property", None) or []:
        name, sep, value = item.partition("=")
        if not sep or not name:
            raise SystemExit(f"--property expects NAME=VALUE, got '{item}'")
        if name in props:
            raise SystemExit(f"--property {name} is given twice (Bonsai.exe refuses that too)")
        props[name] = value
    return props


def _load(path, args):
    """Load one workflow and apply any --property values; problems go to stderr
    and are remembered on ``args`` so the command can exit 1."""
    try:
        doc = load(path, **_load_options(args))
    except (WorkflowLoadError, OSError) as exc:
        raise SystemExit(f"baghban: {exc}")
    args.property_problems = 0
    for a in set_properties(doc, _properties(args)):
        if a.status != "ok":
            args.property_problems += 1
            print(f"baghban: --property {a.name}: {a.note} (Bonsai would refuse it)",
                  file=sys.stderr)
    return doc


def _ignore_rules(doc, args) -> list:
    """--ignore rules, plus those of the baghban.toml (or pyproject.toml) above
    the workflow unless --no-config."""
    try:
        rules = [parse_ignore(r) for r in getattr(args, "ignore", None) or []]
        if doc.path is not None and not getattr(args, "no_config", False):
            config = find_config(doc.path)
            if config is not None:
                cache = vars(args).setdefault("_config_cache", {})  # one read per run
                if config not in cache:
                    cache[config] = read_config(config)
                rules += cache[config]
    except ConfigError as exc:
        raise SystemExit(f"baghban: {exc}")
    return rules


def _with_problems(args, code: int) -> int:
    return max(code, 1 if getattr(args, "property_problems", 0) else 0)


def select_roots(docs) -> list:
    """Workflows to check as entry points: those no other file includes, plus
    enough of the rest that every file is reached (members of an include cycle
    include each other, so none of them would otherwise be checked)."""
    included = {p for d in docs for p in d.included_files}
    roots = [d for d in docs if d.path.resolve() not in included]
    covered = {d.path.resolve() for d in roots} | {p for d in roots for p in d.included_files}
    for d in docs:
        if d.path.resolve() not in covered:
            roots.append(d)
            covered |= {d.path.resolve(), *d.included_files}
    return roots


def cmd_check(args) -> int:
    files = _collect(args.paths, args.exclude or ())
    if not files:
        print("baghban: no .bonsai files found", file=sys.stderr)
        return 2
    if _properties(args) and len(files) != 1:
        raise SystemExit("baghban: --property applies to one workflow; check it on its own")
    docs, failures = [], []
    for f in files:
        try:
            docs.append(_load(f, args) if _properties(args) else load(f, **_load_options(args)))
        except (WorkflowLoadError, OSError) as exc:
            failures.append(str(exc))

    # A file that another checked file includes is checked through its includer,
    # where the subjects and parameters it relies on are defined.
    roots = select_roots(docs)
    via_includer = len(docs) - len(roots)

    reports = [check(d, ignore=_ignore_rules(d, args)) for d in roots]
    code = _with_problems(args, max([r.exit_code(args.strict) for r in reports]
                                    + [1 if failures else 0]))

    if args.json:
        print(json.dumps({"reports": [r.to_dict() for r in reports], "unreadable": failures},
                         indent=2))
        return code

    for i, r in enumerate(reports):
        if len(reports) > 1:
            print(("\n" if i else "") + f"== {r.path}")
        print(r.summary(show_info=not args.no_info))
    for msg in failures:
        print(f"unreadable: {msg}")
    if via_includer:
        print(f"\n{via_includer} file(s) checked through the workflows that include them.")
    return code


def cmd_show(args) -> int:
    print(outline(_load(args.workflow, args)))
    return _with_problems(args, 0)


def cmd_render(args) -> int:
    doc = _load(args.workflow, args)
    fmt = args.format
    report = check(doc, ignore=_ignore_rules(doc, args))
    if fmt == "html":
        text = html(doc, report)
    elif fmt == "dot":
        text = dot(doc, report.findings)
    else:
        text = mermaid(doc, report.findings)
    out = args.output
    if out is None and fmt == "html":
        # next to the workflow: two rigs' foraging.bonsai no longer overwrite each other
        out = Path(args.workflow).with_suffix(".html")
    if out:
        Path(out).write_text(text, encoding="utf-8")
        print(f"wrote {Path(out).resolve()}")
    else:
        print(text)
    return _with_problems(args, 0)


def cmd_diff(args) -> int:
    result = diff(_load(args.a, args), _load(args.b, args))
    print(json.dumps(result.to_dict(), indent=2, default=str) if args.json else result.summary())
    return 0 if result.identical else 1


def cmd_deps(args) -> int:
    deps = dependencies(_load(args.workflow, args))
    print(json.dumps(deps, indent=2) if args.json else format_dependencies(deps))
    return 0


def cmd_params(args) -> int:
    params = parameters(_load(args.workflow, args))
    print(json.dumps(params, indent=2) if args.json else format_parameters(params))
    return _with_problems(args, 0)


def cmd_fingerprint(args) -> int:
    if args.fields:  # kept from 0.1: the same as `baghban provenance`
        return cmd_provenance(args)
    if _properties(args):
        raise SystemExit("baghban: the fingerprint is of the workflow as saved; --property "
                         "only applies with --fields (or use `baghban provenance`)")
    print(f"{fingerprint(_load(args.workflow, args))}  {args.workflow}")
    return 0


def cmd_provenance(args) -> int:
    try:
        doc = load(args.workflow, **_load_options(args))
    except (WorkflowLoadError, OSError) as exc:
        raise SystemExit(f"baghban: {exc}")
    fields = provenance(doc, _properties(args))
    print(json.dumps(fields, indent=2))
    if "bonsai.problems" in fields:
        print(f"baghban: {fields['bonsai.problems']} (Bonsai would refuse it)", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="baghban",
        description="Check, draw and compare Bonsai workflows without Windows or .NET.")
    p.add_argument("--version", action="version", version=f"baghban {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def with_roots(sp):
        sp.add_argument("--resource-root", action="append", metavar="ASSEMBLY=DIR",
                        help="folder holding the source of an assembly, to follow "
                             "embedded-resource includes (repeatable)")
        sp.add_argument("--fetch", action="store_true",
                        help="download packages that are not installed or cached from "
                             "nuget.org, to read their embedded workflows (off by default: "
                             "baghban makes no network calls otherwise)")
        sp.add_argument("--package", action="append", metavar="ID=VERSION",
                        help="use this version of a package, overriding .bonsai/Bonsai.config "
                             "(repeatable)")
        sp.add_argument("--cache", metavar="DIR",
                        help="where downloaded packages and extracted workflows are kept "
                             "(default: $BAGHBAN_CACHE or ~/.cache/baghban)")
        return sp

    def with_ignores(sp):
        sp.add_argument("--ignore", action="append", metavar="CODE[:PATTERN]",
                        help="mark a finding as intended, everywhere or in files matching "
                             "PATTERN, e.g. SILENT_OVERWRITE:demos/* (repeatable); ignored "
                             "findings are listed but not counted")
        sp.add_argument("--no-config", action="store_true",
                        help="do not read ignore rules from baghban.toml or "
                             "pyproject.toml [tool.baghban]")
        return sp

    def with_properties(sp):
        sp.add_argument("-p", "--property", action="append", metavar="NAME=VALUE",
                        help="set an externalized property as Bonsai.exe --property does "
                             "(dotted names reach into nested workflows; repeatable)")
        return sp

    c = with_ignores(with_properties(with_roots(sub.add_parser(
        "check", help="find problems before the rig runs"))))
    c.add_argument("paths", nargs="+", help=".bonsai files or folders")
    c.add_argument("--json", action="store_true")
    c.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    c.add_argument("--no-info", action="store_true", help="hide info-level findings")
    c.add_argument("--exclude", action="append", metavar="GLOB",
                   help="skip matching files, e.g. 'docs/*' for documentation snippets "
                        "(repeatable)")
    c.set_defaults(func=cmd_check)

    s = with_properties(with_roots(sub.add_parser("show", help="print the workflow as a tree")))
    s.add_argument("workflow")
    s.set_defaults(func=cmd_show)

    r = with_ignores(with_properties(with_roots(sub.add_parser("render", help="draw the workflow"))))
    r.add_argument("workflow")
    r.add_argument("-f", "--format", choices=("html", "mermaid", "dot"), default="html")
    r.add_argument("-o", "--output", help="output file (html defaults to the workflow's name with .html, next to it)")
    r.set_defaults(func=cmd_render)

    d = with_roots(sub.add_parser("diff", help="semantic diff of two workflows"))
    d.add_argument("a")
    d.add_argument("b")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_diff)

    dp = with_roots(sub.add_parser("deps", help="assemblies and includes the workflow needs"))
    dp.add_argument("workflow")
    dp.add_argument("--json", action="store_true")
    dp.set_defaults(func=cmd_deps)

    pa = with_properties(with_roots(sub.add_parser("params", help="externalized properties and values")))
    pa.add_argument("workflow")
    pa.add_argument("--json", action="store_true")
    pa.set_defaults(func=cmd_params)

    f = with_properties(with_roots(sub.add_parser("fingerprint",
                                                  help="content hash stable across re-saves")))
    f.add_argument("workflow")
    f.add_argument("--fields", action="store_true",
                   help="print the provenance fields instead (same as `baghban provenance`)")
    f.set_defaults(func=cmd_fingerprint)

    pv = with_properties(with_roots(sub.add_parser(
        "provenance", help="fields recording which protocol a session ran (JSON)")))
    pv.add_argument("workflow")
    pv.set_defaults(func=cmd_provenance)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:  # e.g. `baghban diff a b | head`
        sys.stderr.close()
        return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
