"""Roadmap item 3: confirm baghban's package reader against Microsoft's.

baghban reads embedded workflows out of package DLLs with its own pure-Python
ECMA-335 reader (src/baghban/dotnet.py). This script checks it against
System.Reflection.Metadata, the reader .NET itself uses, on real Bonsai
packages from nuget.org:

1. download each package (newest version, or the one given) into baghban's
   cache, and take every DLL in it (``lib/<framework>/*.dll``);
2. list each DLL's assembly name and manifest resources (name, offset,
   embedded or not, SHA-256 of the bytes) with both readers, and compare;
3. for every embedded ``.bonsai`` resource, resolve it the way an include
   would (``Path="Assembly:Rest.bonsai"``) through baghban's resolver, and
   compare the extracted file with .NET's bytes.

    python confirm/confirm_packages.py                       # the default packages
    python confirm/confirm_packages.py BonVision=0.13.0 Bonsai.Harp
    python confirm/confirm_packages.py --dry-run             # baghban's side only, no .NET

Needs network access to nuget.org and, except with --dry-run, the .NET 8 SDK
(see confirm/README.md). Writes confirm/packages-results.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from baghban.dotnet import Assembly, NotADotNetAssembly
from baghban.packages import Environment, PackageResolver, default_cache, fetch_nupkg

HERE = Path(__file__).resolve().parent
LISTER = HERE / "resources"

# The packages whose embedded workflows the survey most often could not read
# (survey/SURVEY.md, "What limits coverage"), plus two more with workflows.
DEFAULT_PACKAGES = [
    "BonVision", "AllenNeuralDynamics.Core", "AllenNeuralDynamics.HarpUtils",
    "Aeon.Acquisition", "Bonsai.Harp", "Bonsai.ML.LinearDynamicalSystems",
    "Bonsai.ML.HiddenMarkovModels", "AllenNeuralDynamics.AindManipulator",
]


# ----------------------------------------------------------------------------- views

def python_view(dll: Path) -> dict:
    """What baghban's reader sees, in the same shape the .NET lister prints."""
    try:
        a = Assembly(dll.read_bytes())
    except NotADotNetAssembly as exc:
        return {"path": str(dll), "error": str(exc)}
    resources = []
    for r in a.resources():
        sha = hashlib.sha256(a.resource(r.name)).hexdigest() if r.embedded else None
        resources.append({"name": r.name, "offset": r.offset, "embedded": r.embedded,
                          "sha256": sha})
    try:
        name = a.name
    except NotADotNetAssembly:
        name = None
    return {"path": str(dll), "assembly": name, "resources": resources}


def compare(ours: dict, theirs: dict) -> list:
    """Differences between baghban's view and .NET's, as readable lines."""
    if "error" in theirs and "error" in ours:
        return []  # both refuse it (e.g. a native DLL)
    if "error" in theirs or "error" in ours:
        return [f"baghban: {ours.get('error', 'read it')}; .NET: {theirs.get('error', 'read it')}"]
    diffs = []
    if ours["assembly"] != theirs["assembly"]:
        diffs.append(f"assembly name: baghban {ours['assembly']!r}, .NET {theirs['assembly']!r}")
    a = {r["name"]: r for r in ours["resources"]}
    b = {r["name"]: r for r in theirs["resources"]}
    for name in sorted(set(a) | set(b)):
        if name not in a:
            diffs.append(f"resource {name}: only .NET sees it")
        elif name not in b:
            diffs.append(f"resource {name}: only baghban sees it")
        else:
            for key in ("offset", "embedded", "sha256"):
                if a[name][key] != b[name][key]:
                    diffs.append(f"resource {name}: {key} baghban {a[name][key]!r}, "
                                 f".NET {b[name][key]!r}")
    if [r["name"] for r in ours["resources"]] != [r["name"] for r in theirs["resources"]] \
            and set(a) == set(b):
        diffs.append("resources listed in a different order")
    return diffs


def resolve_through_baghban(pid: str, version: str, dll_rel: str, view: dict,
                            cache: Path) -> list:
    """Resolve every embedded .bonsai resource as an include would; differences."""
    assembly = view.get("assembly")
    if not assembly:
        return []
    env = Environment(config=cache / "confirm" / ".bonsai" / "Bonsai.config",
                      packages={pid: version},
                      locations={assembly: f"Packages/{pid}.{version}/{dll_rel}"})
    resolver = PackageResolver(environment=env, cache_dir=cache)
    diffs = []
    for r in view["resources"]:
        name = r["name"]
        if not (r["embedded"] and name.endswith(".bonsai") and name.startswith(assembly + ".")):
            continue
        res = resolver.resolve(assembly, name[len(assembly) + 1:])
        if res.status != "ok":
            diffs.append(f"include {assembly}:{name[len(assembly) + 1:]}: {res.status} ({res.note})")
        elif hashlib.sha256(res.path.read_bytes()).hexdigest() != r["sha256"]:
            diffs.append(f"include {assembly}:{name[len(assembly) + 1:]}: extracted bytes differ")
    return diffs


# ----------------------------------------------------------------------------- running

def build_lister() -> Path:
    if shutil.which("dotnet") is None:
        sys.exit("dotnet not found: install the .NET 8 SDK (see confirm/README.md), "
                 "or use --dry-run")
    out = LISTER / "bin" / "confirm"
    subprocess.run(["dotnet", "build", str(LISTER), "-c", "Release", "-o", str(out)], check=True)
    dll = out / "ResourceLister.dll"
    if not dll.exists():
        sys.exit(f"build did not produce {dll}")
    return dll


def dotnet_views(lister: Path, dlls: list) -> dict:
    proc = subprocess.run(["dotnet", str(lister), *map(str, dlls)], capture_output=True,
                          text=True, timeout=300)
    if proc.returncode != 0:
        sys.exit(f"the .NET lister failed:\n{proc.stderr}")
    return {item["path"]: item for item in json.loads(proc.stdout)}


def parse_specs(specs: list) -> list:
    out = []
    for spec in specs:
        pid, _, version = spec.partition("=")
        out.append((pid, version or None))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("packages", nargs="*", metavar="ID[=VERSION]",
                   help="packages to check (default: the survey's most-included packages)")
    p.add_argument("--dry-run", action="store_true", help="baghban's side only, no .NET")
    p.add_argument("--cache", help="baghban cache folder (default: ~/.cache/baghban)")
    p.add_argument("--out", default=str(HERE / "packages-results.json"),
                   help="where to write the results (default: confirm/packages-results.json)")
    args = p.parse_args(argv)
    cache = Path(args.cache) if args.cache else default_cache()
    specs = parse_specs(args.packages) or [(pid, None) for pid in DEFAULT_PACKAGES]
    lister = None if args.dry_run else build_lister()

    work = Path(tempfile.mkdtemp(prefix="baghban-packages-"))
    results, all_same = [], True
    print(f"\n{'package':<40} {'version':<12} {'DLLs':>4} {'resources':>9} {'workflows':>9}  result")
    for pid, version in specs:
        try:
            version, nupkg = fetch_nupkg(pid, version, cache_dir=cache)
        except RuntimeError as exc:
            print(f"{pid:<40} {'-':<12} {'':>4} {'':>9} {'':>9}  not checked: {exc}")
            results.append({"package": pid, "skipped": str(exc)})
            continue
        dlls = []
        with zipfile.ZipFile(nupkg) as zf:
            for name in zf.namelist():
                parts = name.split("/")
                if len(parts) == 3 and parts[0] == "lib" and name.lower().endswith(".dll"):
                    target = work / pid / version / parts[1] / parts[2]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(name))
                    dlls.append((target, name))
        ours = {str(d): python_view(d) for d, _ in dlls}
        theirs = dotnet_views(lister, [d for d, _ in dlls]) if lister and dlls else {}
        diffs, n_res, n_wf = [], 0, 0
        for dll, rel in dlls:
            view = ours[str(dll)]
            n_res += len(view.get("resources", []))
            n_wf += sum(1 for r in view.get("resources", []) if r["name"].endswith(".bonsai"))
            if lister:
                diffs += [f"{rel}: {d}" for d in compare(view, theirs.get(str(dll), {"error": "missing"}))]
            if "error" not in view:
                diffs += [f"{rel}: {d}" for d in resolve_through_baghban(pid, version, rel, view, cache)]
        same = not diffs
        all_same &= same
        verdict = ("same as .NET" if lister else "read by baghban (dry run)") if same else \
            f"{len(diffs)} difference(s)"
        print(f"{pid:<40} {version:<12} {len(dlls):>4} {n_res:>9} {n_wf:>9}  {verdict}")
        for d in diffs[:10]:
            print(f"    {d}")
        results.append({"package": pid, "version": version, "dlls": [rel for _, rel in dlls],
                        "resources": n_res, "workflows": n_wf, "same": same,
                        "differences": diffs, "compared_with_dotnet": bool(lister)})
    shutil.rmtree(work, ignore_errors=True)
    out = Path(args.out)
    out.write_text(json.dumps(results, indent=2))
    checked = [r for r in results if "skipped" not in r]
    print(f"\n{sum(r['same'] for r in checked)}/{len(checked)} packages "
          f"{'identical to .NET' if lister else 'read (dry run)'}"
          f"{'; ' + str(len(results) - len(checked)) + ' not checked' if len(checked) < len(results) else ''}."
          f" Details: {out}")
    return 0 if all_same and checked else 1


if __name__ == "__main__":
    sys.exit(main())
