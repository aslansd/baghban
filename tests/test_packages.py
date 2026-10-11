"""Following includes into package DLLs (baghban.packages).

Packages are generated (tests/dllkit.py); "nuget.org" is a local HTTP server
serving the same flat-container layout, so no test touches the network.
"""

import http.server
import json
import threading
from pathlib import Path

import pytest

import baghban
from baghban.cli import main
from baghban.packages import PackageResolver, find_environment, newest, read_environment
from dllkit import make_assembly, make_nupkg
from xmlkit import (csv_writer, document, expr, include_expr, publish, subscribe, timer,
                    workflow, workflow_input, workflow_output)


# ------------------------------------------------------------------ helpers

def module_needing_subject(subject="Draw"):
    """A package module that subscribes to a subject its user must declare."""
    return document(workflow(expr(workflow_input()), expr(subscribe(subject)),
                             expr(workflow_output()), edges=[(1, 2)])).encode()


def module_offering_subject(subject="Frames"):
    return document(workflow(expr(timer()), expr(publish(subject)), edges=[(0, 1)])).encode()


def vision_dll(**extra):
    res = {"MyVision.Primitives.Quad.bonsai": module_needing_subject("Draw"),
           "MyVision.Sources.Frames.bonsai": module_offering_subject("Frames")}
    res.update(extra)
    return make_assembly("MyVision", res)


def bonsai_config(folder: Path, packages: dict, locations: dict = None):
    (folder / ".bonsai").mkdir(parents=True, exist_ok=True)
    pk = "".join(f'<Package id="{i}" version="{v}" />' for i, v in packages.items())
    loc = "".join(f'<AssemblyLocation assemblyName="{a}" processorArchitecture="MSIL" '
                  f'location="{l}" />' for a, l in (locations or {}).items())
    (folder / ".bonsai" / "Bonsai.config").write_text(
        '<?xml version="1.0" encoding="utf-8"?><PackageConfiguration>'
        f"<Packages>{pk}</Packages><AssemblyReferences /><AssemblyLocations>{loc}"
        "</AssemblyLocations></PackageConfiguration>")


def install(folder: Path, pid: str, version: str, dll: bytes, assembly: str = None,
            framework: str = "net472"):
    lib = folder / ".bonsai" / "Packages" / f"{pid}.{version}" / "lib" / framework
    lib.mkdir(parents=True, exist_ok=True)
    (lib / f"{assembly or pid}.dll").write_bytes(dll)


def rig(folder: Path, *nodes, edges=()):
    path = folder / "rig.bonsai"
    path.write_text(document(workflow(*nodes, edges=edges)))
    return path


class FakeNuGet:
    """A flat-container feed on localhost: /<id>/index.json and the .nupkg."""

    def __init__(self, packages: dict):
        self.packages = packages  # (id, version) -> nupkg bytes
        self.requests = []
        feed = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                feed.requests.append(self.path)
                parts = self.path.strip("/").split("/")
                body = None
                if len(parts) == 2 and parts[1] == "index.json":
                    versions = [v for (i, v) in feed.packages if i.lower() == parts[0]]
                    if versions:
                        body = json.dumps({"versions": versions}).encode()
                elif len(parts) == 3:
                    for (i, v), data in feed.packages.items():
                        if parts[0] == i.lower() and parts[1] == v.lower():
                            body = data
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def feed():
    nupkg = lambda v: make_nupkg("MyVision", v, {"lib/net472/MyVision.dll": vision_dll()})
    f = FakeNuGet({("MyVision", "1.0.0"): nupkg("1.0.0"), ("MyVision", "1.2.0"): nupkg("1.2.0"),
                   ("MyVision", "2.0.0-beta1"): nupkg("2.0.0-beta1")})
    yield f
    f.close()


# ------------------------------------------------------------------ environment

def test_reads_bonsai_config(tmp_path):
    bonsai_config(tmp_path, {"Bonsai.Core": "2.9.0", "MyCo.Vision": "1.0.0"},
                  {"MyVision": "Packages/MyCo.Vision.1.0.0/lib/net472/MyVision.dll"})
    env = read_environment(tmp_path / ".bonsai" / "Bonsai.config")
    assert env.packages == {"Bonsai.Core": "2.9.0", "MyCo.Vision": "1.0.0"}
    # the assembly is not named like its package: the AssemblyLocation says where it is
    assert env.package_of("MyVision") == ("MyCo.Vision", "1.0.0", "lib/net472/MyVision.dll")
    assert env.package_of("Bonsai.Core") == ("Bonsai.Core", "2.9.0", None)
    assert env.package_of("Unknown") is None


def test_environment_is_found_upwards_like_bonsai(tmp_path):
    bonsai_config(tmp_path, {"MyVision": "1.0.0"})
    deep = tmp_path / "src" / "tasks"
    deep.mkdir(parents=True)
    assert find_environment(deep / "task.bonsai").config == tmp_path / ".bonsai" / "Bonsai.config"


@pytest.mark.parametrize("folder", ["Bonsai", "bonsai"])
def test_portable_install_next_to_workflows_is_an_environment(tmp_path, folder):
    # as in iblrig (Bonsai/Bonsai.config) and vestibular-vr (bonsai/Bonsai.config)
    (tmp_path / folder).mkdir()
    (tmp_path / folder / "Bonsai.config").write_text(
        '<PackageConfiguration><Packages><Package id="MyVision" version="0.9.0" />'
        "</Packages></PackageConfiguration>")
    deep = tmp_path / "visual_stim" / "task"
    deep.mkdir(parents=True)
    env = find_environment(deep / "task.bonsai")
    assert env.config == tmp_path / folder / "Bonsai.config"
    assert env.package_of("MyVision") == ("MyVision", "0.9.0", None)


def test_dot_bonsai_wins_at_the_same_level_and_nearest_wins_overall(tmp_path):
    bonsai_config(tmp_path, {"MyVision": "1.0.0"})
    (tmp_path / "Bonsai").mkdir()
    (tmp_path / "Bonsai" / "Bonsai.config").write_text(
        '<PackageConfiguration><Packages><Package id="MyVision" version="0.9.0" />'
        "</Packages></PackageConfiguration>")
    assert find_environment(tmp_path / "w.bonsai").packages == {"MyVision": "1.0.0"}
    sub = tmp_path / "sub"
    bonsai_config(sub, {"MyVision": "2.0.0"})
    assert find_environment(sub / "w.bonsai").packages == {"MyVision": "2.0.0"}


def test_a_folder_named_bonsai_without_pins_is_not_an_environment(tmp_path):
    (tmp_path / "bonsai").mkdir()
    (tmp_path / "bonsai" / "Bonsai.config").write_text("<PackageConfiguration />")
    assert find_environment(tmp_path / "w.bonsai") is None


def test_newest_prefers_stable():
    assert newest(["1.0.0", "1.10.0", "1.9.3", "2.0.0-beta1"]) == "1.10.0"
    assert newest(["2.0.0-beta1", "2.0.0-alpha"]) == "2.0.0-beta1"
    assert newest([]) is None


# ------------------------------------------------------------------ local sources

def test_installed_environment_is_used_without_network(tmp_path):
    bonsai_config(tmp_path, {"MyVision": "1.0.0"})
    install(tmp_path, "MyVision", "1.0.0", vision_dll())
    path = rig(tmp_path, expr(timer()), expr(publish("Draw")),
               include_expr("MyVision:Primitives.Quad.bonsai"), edges=[(0, 1)])
    doc = baghban.load(path)
    inc = doc.workflow.nodes[2].include
    assert inc.status == "ok" and inc.package == "MyVision" and inc.package_version == "1.0.0"
    assert inc.pinned and inc.origin == "installed environment"
    report = baghban.check(doc)
    assert report.errors == []
    assert report.packages == [{"id": "MyVision", "version": "1.0.0", "pinned": True,
                                "origin": "installed environment"}]
    assert "package: MyVision 1.0.0 (pinned" in report.summary()


def test_finding_inside_a_package_names_package_and_version(tmp_path):
    bonsai_config(tmp_path, {"MyVision": "1.0.0"})
    install(tmp_path, "MyVision", "1.0.0", vision_dll())
    # the rig forgets to declare 'Draw', which the package module needs
    path = rig(tmp_path, include_expr("MyVision:Primitives.Quad.bonsai"))
    report = baghban.check(baghban.load(path))
    assert report.codes() == ["DANGLING_SUBJECT"]
    f = report.findings[0]
    assert f.file == "MyVision 1.0.0: MyVision.Primitives.Quad.bonsai"
    assert f.location.startswith("Include 'MyVision:Primitives.Quad.bonsai' #0 > ")


def test_subjects_a_package_offers_are_not_unused(tmp_path):
    bonsai_config(tmp_path, {"MyVision": "1.0.0"})
    install(tmp_path, "MyVision", "1.0.0", vision_dll())
    path = rig(tmp_path, include_expr("MyVision:Sources.Frames.bonsai"))
    assert baghban.check(baghban.load(path)).findings == []


def test_subject_declared_in_package_satisfies_user(tmp_path):
    bonsai_config(tmp_path, {"MyVision": "1.0.0"})
    install(tmp_path, "MyVision", "1.0.0", vision_dll())
    # previously this include was unreadable, so the subscribe was "not checked"
    path = rig(tmp_path, include_expr("MyVision:Sources.Frames.bonsai"),
               expr(subscribe("Frames")), expr(csv_writer("f.csv", suffix="Timestamp")),
               edges=[(1, 2)])
    report = baghban.check(baghban.load(path))
    assert report.findings == [] and not any("Frames" in s for s in report.skipped)


def test_assembly_location_maps_assembly_to_differently_named_package(tmp_path):
    bonsai_config(tmp_path, {"MyCo.Vision": "1.0.0"},
                  {"MyVision": "Packages/MyCo.Vision.1.0.0/lib/net472/MyVision.dll"})
    install(tmp_path, "MyCo.Vision", "1.0.0", vision_dll(), assembly="MyVision")
    path = rig(tmp_path, include_expr("MyVision:Sources.Frames.bonsai"))
    inc = baghban.load(path).workflow.nodes[0].include
    assert (inc.status, inc.package, inc.package_version) == ("ok", "MyCo.Vision", "1.0.0")


def test_nuget_global_packages_folder(tmp_path, monkeypatch):
    nuget = tmp_path / "nuget"
    lib = nuget / "myvision" / "1.0.0" / "lib" / "net472"
    lib.mkdir(parents=True)
    (lib / "MyVision.dll").write_bytes(vision_dll())
    monkeypatch.setenv("NUGET_PACKAGES", str(nuget))
    bonsai_config(tmp_path, {"MyVision": "1.0.0"})
    path = rig(tmp_path, include_expr("MyVision:Sources.Frames.bonsai"))
    inc = baghban.load(path).workflow.nodes[0].include
    assert inc.status == "ok" and inc.origin == "NuGet global packages"


def test_prefers_net472_over_other_frameworks(tmp_path):
    bonsai_config(tmp_path, {"MyVision": "1.0.0"})
    old = make_assembly("MyVision", {"MyVision.Sources.Frames.bonsai": b"<WorkflowBuilder/>"})
    install(tmp_path, "MyVision", "1.0.0", old, framework="netstandard2.0")
    install(tmp_path, "MyVision", "1.0.0", vision_dll(), framework="net472")
    path = rig(tmp_path, include_expr("MyVision:Sources.Frames.bonsai"))
    nodes = list(baghban.load(path).walk())
    assert any(n.is_subject_declaration for n in nodes)  # the net472 content was read


def test_not_installed_and_no_fetch_is_not_checked_and_makes_no_request(tmp_path, feed):
    bonsai_config(tmp_path, {"MyVision": "1.0.0"})
    path = rig(tmp_path, include_expr("MyVision:Primitives.Quad.bonsai"), expr(subscribe("X")))
    report = baghban.check(baghban.load(path))
    assert report.findings == []
    note = " ".join(report.skipped)
    assert "--fetch" in note and "--resource-root" in note
    assert feed.requests == []


def test_resource_root_takes_precedence_over_packages(tmp_path):
    src = tmp_path / "MyVisionSource" / "Primitives"
    src.mkdir(parents=True)
    (src / "Quad.bonsai").write_text(document(workflow(expr(timer()))))
    bonsai_config(tmp_path, {"MyVision": "1.0.0"})
    install(tmp_path, "MyVision", "1.0.0", vision_dll())
    path = rig(tmp_path, include_expr("MyVision:Primitives.Quad.bonsai"))
    doc = baghban.load(path, resource_roots={"MyVision": tmp_path / "MyVisionSource"})
    inc = doc.workflow.nodes[0].include
    assert inc.status == "ok" and inc.package is None


def test_module_from_source_root_also_offers_its_subjects(tmp_path):
    src = tmp_path / "MyVisionSource" / "Sources"
    src.mkdir(parents=True)
    (src / "Frames.bonsai").write_bytes(module_offering_subject("Frames"))
    path = rig(tmp_path, include_expr("MyVision:Sources.Frames.bonsai"))
    report = baghban.check(baghban.load(path, resource_roots={"MyVision": tmp_path / "MyVisionSource"}))
    assert report.findings == []  # not UNUSED_SUBJECT: it is what the module offers


def test_packages_false_disables_resolution(tmp_path):
    bonsai_config(tmp_path, {"MyVision": "1.0.0"})
    install(tmp_path, "MyVision", "1.0.0", vision_dll())
    path = rig(tmp_path, include_expr("MyVision:Sources.Frames.bonsai"))
    assert baghban.load(path, packages=False).workflow.nodes[0].include.status == "unresolved"


# ------------------------------------------------------------------ fetching

def test_fetch_pinned_version(tmp_path, feed):
    bonsai_config(tmp_path, {"MyVision": "1.0.0"})
    path = rig(tmp_path, expr(publish("Draw")), include_expr("MyVision:Primitives.Quad.bonsai"))
    resolver = PackageResolver.for_workflow(path, fetch=True, source=feed.url)
    doc = baghban.load(path, packages=resolver)
    inc = doc.workflow.nodes[1].include
    assert inc.status == "ok" and inc.package_version == "1.0.0" and inc.pinned
    assert inc.origin.startswith("nuget.org")
    assert feed.requests == ["/myvision/1.0.0/myvision.1.0.0.nupkg"]
    # the second time, the cache answers
    feed.requests.clear()
    again = PackageResolver.for_workflow(path, fetch=True, source=feed.url)
    assert baghban.load(path, packages=again).workflow.nodes[1].include.origin == "baghban cache"
    assert feed.requests == []


def test_fetch_unpinned_uses_newest_stable_and_says_so(tmp_path, feed):
    path = rig(tmp_path, include_expr("MyVision:Sources.Frames.bonsai"))
    resolver = PackageResolver.for_workflow(path, fetch=True, source=feed.url)
    report = baghban.check(baghban.load(path, packages=resolver))
    assert report.packages[0]["version"] == "1.2.0" and report.packages[0]["pinned"] is False
    assert "NOT pinned" in report.summary()


def test_pin_on_command_line_beats_environment(tmp_path, feed):
    bonsai_config(tmp_path, {"MyVision": "1.2.0"})
    path = rig(tmp_path, include_expr("MyVision:Sources.Frames.bonsai"))
    resolver = PackageResolver.for_workflow(path, fetch=True, pins={"MyVision": "1.0.0"},
                                            source=feed.url)
    inc = baghban.load(path, packages=resolver).workflow.nodes[0].include
    assert inc.package_version == "1.0.0" and inc.pinned


def test_missing_version_on_feed_is_not_checked(tmp_path, feed):
    bonsai_config(tmp_path, {"MyVision": "9.9.9"})
    path = rig(tmp_path, include_expr("MyVision:Sources.Frames.bonsai"))
    resolver = PackageResolver.for_workflow(path, fetch=True, source=feed.url)
    report = baghban.check(baghban.load(path, packages=resolver))
    assert report.findings == []
    assert any("no MyVision 9.9.9" in s for s in report.skipped)


def test_unreachable_feed_is_not_checked_not_a_crash(tmp_path):
    bonsai_config(tmp_path, {"MyVision": "1.0.0"})
    path = rig(tmp_path, include_expr("MyVision:Sources.Frames.bonsai"))
    resolver = PackageResolver.for_workflow(path, fetch=True, source="http://127.0.0.1:9",
                                            timeout=2)
    report = baghban.check(baghban.load(path, packages=resolver))
    assert report.findings == [] and any("could not download" in s for s in report.skipped)


# ------------------------------------------------------------------ missing resources

def test_missing_resource_in_pinned_package_is_an_error(tmp_path):
    bonsai_config(tmp_path, {"MyVision": "1.0.0"})
    install(tmp_path, "MyVision", "1.0.0", vision_dll())
    path = rig(tmp_path, include_expr("MyVision:Primitives.Renamed.bonsai"))
    report = baghban.check(baghban.load(path))
    assert report.codes() == ["MISSING_INCLUDE"]
    assert "MyVision 1.0.0" in report.findings[0].message


def test_missing_resource_in_unpinned_package_is_not_checked(tmp_path, feed):
    path = rig(tmp_path, include_expr("MyVision:Primitives.Renamed.bonsai"))
    resolver = PackageResolver.for_workflow(path, fetch=True, source=feed.url)
    report = baghban.check(baghban.load(path, packages=resolver))
    assert report.findings == []
    assert any("version mismatch" in s for s in report.skipped)


def test_nested_includes_inside_a_package_resolve(tmp_path):
    outer = document(workflow(include_expr("MyVision:Sources.Frames.bonsai"))).encode()
    dll = vision_dll(**{"MyVision.Outer.bonsai": outer})
    bonsai_config(tmp_path, {"MyVision": "1.0.0"})
    install(tmp_path, "MyVision", "1.0.0", dll)
    path = rig(tmp_path, include_expr("MyVision:Outer.bonsai"))
    nodes = list(baghban.load(path).walk())
    inner = [n for n in nodes if n.is_include][1].include
    assert inner.status == "ok" and inner.package == "MyVision"


def test_unsafe_resource_name_is_refused(tmp_path):
    from baghban.packages import _safe_name
    assert _safe_name("MyVision.Primitives.Quad.bonsai")
    for bad in ("../x.bonsai", "a/b.bonsai", "a\\b.bonsai", ".hidden.bonsai", "A:b.bonsai", ""):
        assert not _safe_name(bad)


# ------------------------------------------------------------------ reports and CLI

def test_provenance_and_deps_name_the_package(tmp_path):
    bonsai_config(tmp_path, {"MyVision": "1.0.0"})
    install(tmp_path, "MyVision", "1.0.0", vision_dll())
    path = rig(tmp_path, include_expr("MyVision:Sources.Frames.bonsai"))
    doc = baghban.load(path)
    assert baghban.manifest_fields(doc)["bonsai.package.MyVision"] == "1.0.0"
    from baghban.info import format_dependencies
    text = format_dependencies(baghban.dependencies(doc))
    assert "MyVision 1.0.0  (pinned; from installed environment)" in text


def test_fingerprint_changes_with_package_content(tmp_path):
    bonsai_config(tmp_path, {"MyVision": "1.0.0"})
    install(tmp_path, "MyVision", "1.0.0", vision_dll())
    path = rig(tmp_path, include_expr("MyVision:Sources.Frames.bonsai"))
    before = baghban.fingerprint(baghban.load(path))
    changed = make_assembly("MyVision", {"MyVision.Sources.Frames.bonsai": module_offering_subject("Other")})
    install(tmp_path, "MyVision", "1.0.0", changed)
    assert baghban.fingerprint(baghban.load(path)) != before


def test_cli_fetch_package_and_cache(tmp_path, feed, monkeypatch, capsys):
    monkeypatch.setenv("BAGHBAN_NUGET_SOURCE", feed.url)
    path = rig(tmp_path, include_expr("MyVision:Primitives.Quad.bonsai"))
    cache = tmp_path / "mycache"
    assert main(["check", str(path)]) == 0                    # offline: not checked
    assert "--fetch" in capsys.readouterr().out
    assert main(["check", str(path), "--fetch", "--package", "MyVision=1.0.0",
                 "--cache", str(cache)]) == 1                 # the module needs 'Draw'
    out = capsys.readouterr().out
    assert "DANGLING_SUBJECT" in out and "MyVision 1.0.0 (pinned" in out
    assert (cache / "nuget" / "myvision" / "1.0.0" / "myvision.1.0.0.nupkg").is_file()
    assert main(["deps", str(path), "--package", "MyVision=1.0.0", "--cache", str(cache)]) == 0
    assert "MyVision 1.0.0" in capsys.readouterr().out


def test_cli_rejects_bad_package_option(tmp_path):
    path = rig(tmp_path, expr(timer()))
    with pytest.raises(SystemExit):
        main(["check", str(path), "--package", "MyVision"])
