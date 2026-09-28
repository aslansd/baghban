"""Run baghban over published Bonsai repositories and tabulate the findings.

    python survey/run_survey.py WORKDIR            # clone (shallow) and check
    python survey/run_survey.py WORKDIR --no-clone # re-check existing clones

Writes WORKDIR/results.json and prints a summary. Repositories are listed in
survey/repos.txt; the commit of each clone is recorded so a run can be
reproduced. The per-finding verdicts from reading the errors by hand are in
survey/SURVEY.md, not here: this script counts, people judge.
"""

import argparse
import collections
import json
import subprocess
import sys
import traceback
from pathlib import Path

import baghban
from baghban.checks import check
from baghban.cli import _collect, select_roots

HERE = Path(__file__).parent


def clone(repo: str, dest: Path) -> None:
    if not dest.exists():
        subprocess.run(["git", "clone", "-q", "--depth", "1", f"https://github.com/{repo}", str(dest)],
                       check=False, timeout=300)


def commit(dest: Path) -> str:
    out = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"], capture_output=True, text=True)
    return out.stdout.strip() or "?"


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("workdir")
    p.add_argument("--no-clone", action="store_true")
    args = p.parse_args(argv)
    work = Path(args.workdir)
    work.mkdir(parents=True, exist_ok=True)
    repos = [line.strip() for line in (HERE / "repos.txt").read_text().splitlines() if line.strip()]

    rows, crashes, unreadable, commits = [], [], [], {}
    for repo in repos:
        dest = work / repo.replace("/", "_")
        if not args.no_clone:
            clone(repo, dest)
        if not dest.exists():
            continue
        commits[repo] = commit(dest)
        docs = []
        for f in _collect([dest]):
            try:
                docs.append(baghban.load(f))
            except baghban.WorkflowLoadError as exc:
                unreadable.append({"repo": repo, "file": str(f), "error": str(exc)[:200]})
            except Exception:
                crashes.append({"repo": repo, "file": str(f), "stage": "load",
                                "trace": traceback.format_exc()[-600:]})
        for d in select_roots(docs):
            try:
                r = check(d)
            except Exception:
                crashes.append({"repo": repo, "file": str(d.path), "stage": "check",
                                "trace": traceback.format_exc()[-600:]})
                continue
            rows.append({"repo": repo, "root": str(d.path), "kind": r.kind, "nodes": r.n_nodes,
                         "skipped": len(r.skipped), "findings": [f.to_dict() for f in r.findings]})

    result = {"baghban": baghban.__version__, "commits": commits, "workflows": rows,
              "crashes": crashes, "unreadable": unreadable}
    (work / "results.json").write_text(json.dumps(result, indent=1))

    findings = [(w["repo"], f) for w in rows for f in w["findings"]]
    print(f"repositories: {len(commits)}   entry workflows checked: {len(rows)}   "
          f"nodes: {sum(w['nodes'] for w in rows)}")
    print(f"kinds: {dict(collections.Counter(w['kind'] for w in rows))}")
    print(f"crashes: {len(crashes)}   unreadable files: {len(unreadable)}   "
          f"workflows with 'not checked' notes: {sum(1 for w in rows if w['skipped'])}")
    print()
    tally = collections.Counter((f["severity"], f["code"]) for _, f in findings)
    order = {"error": 0, "warning": 1, "info": 2}
    for (sev, code), n in sorted(tally.items(), key=lambda kv: (order[kv[0][0]], -kv[1])):
        repos_hit = len({r for r, f in findings if f["code"] == code and f["severity"] == sev})
        print(f"  {n:4}  {sev:8} {code:<20} in {repos_hit} repo(s)")
    for c in crashes[:5]:
        print("CRASH", c["file"], c["stage"], c["trace"][-300:], file=sys.stderr)
    return 1 if crashes else 0


if __name__ == "__main__":
    sys.exit(main())
