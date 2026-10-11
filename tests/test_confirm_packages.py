"""confirm/confirm_packages.py runs on a machine with .NET and nuget.org; here
its comparison and resolution logic are tested with generated packages, a
local feed and a simulated .NET lister, so a difference reported on a real
machine means .NET disagreed with baghban, not a bug in the kit."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "confirm"))
import confirm_packages as cp  # noqa: E402
from dllkit import make_assembly, make_nupkg  # noqa: E402
from test_packages import FakeNuGet  # noqa: E402

RES = {"MyVision.Primitives.Quad.bonsai": b"<WorkflowBuilder Version='2.9.0'/>",
       "MyVision.Strings.resources": b"\x01\x02"}


def dll(tmp_path, **kw):
    path = tmp_path / "MyVision.dll"
    path.write_bytes(make_assembly("MyVision", RES, **kw))
    return path


def test_identical_views_have_no_differences(tmp_path):
    view = cp.python_view(dll(tmp_path))
    assert view["assembly"] == "MyVision" and len(view["resources"]) == 2
    assert cp.compare(view, json.loads(json.dumps(view))) == []


def test_compare_finds_each_kind_of_difference(tmp_path):
    ours = cp.python_view(dll(tmp_path))
    theirs = json.loads(json.dumps(ours))
    theirs["assembly"] = "Other"
    theirs["resources"][0]["sha256"] = "0" * 64
    theirs["resources"].append({"name": "Extra.bonsai", "offset": 0, "embedded": True,
                                "sha256": None})
    diffs = cp.compare(ours, theirs)
    assert any("assembly name" in d for d in diffs)
    assert any("sha256" in d for d in diffs)
    assert any("only .NET sees it" in d for d in diffs)


def test_both_refusing_a_native_dll_is_agreement():
    assert cp.compare({"error": "native"}, {"error": "no .NET metadata"}) == []
    assert cp.compare({"error": "native"}, {"assembly": "X", "resources": []}) != []


def test_resolution_through_baghban_matches_resource_bytes(tmp_path):
    cache = tmp_path / "cache"
    nupkg = cache / "nuget" / "myvision" / "1.0.0" / "myvision.1.0.0.nupkg"
    nupkg.parent.mkdir(parents=True)
    data = make_assembly("MyVision", RES)
    nupkg.write_bytes(make_nupkg("MyVision", "1.0.0", {"lib/net472/MyVision.dll": data}))
    path = tmp_path / "x.dll"
    path.write_bytes(data)
    view = cp.python_view(path)
    assert cp.resolve_through_baghban("MyVision", "1.0.0", "lib/net472/MyVision.dll", view,
                                      cache) == []
    view["resources"][0]["sha256"] = "f" * 64  # .NET would have seen other bytes
    assert cp.resolve_through_baghban("MyVision", "1.0.0", "lib/net472/MyVision.dll", view,
                                      cache) != []


@pytest.fixture
def feed():
    nupkg = make_nupkg("MyVision", "1.0.0", {"lib/net472/MyVision.dll": make_assembly("MyVision", RES),
                                             "lib/netstandard2.0/MyVision.dll": make_assembly("MyVision", RES)})
    f = FakeNuGet({("MyVision", "1.0.0"): nupkg})
    yield f
    f.close()


def test_dry_run_end_to_end(tmp_path, feed, monkeypatch, capsys):
    monkeypatch.setenv("BAGHBAN_NUGET_SOURCE", feed.url)
    out = tmp_path / "results.json"
    code = cp.main(["MyVision", "Missing.Package", "--dry-run", "--cache", str(tmp_path / "c"),
                    "--out", str(out)])
    assert code == 0
    results = {r["package"]: r for r in json.loads(out.read_text())}
    assert results["MyVision"]["same"] and results["MyVision"]["workflows"] == 2
    assert "skipped" in results["Missing.Package"]
    assert "1 not checked" in capsys.readouterr().out


def test_simulated_dotnet_agreeing_and_disagreeing(tmp_path, feed, monkeypatch, capsys):
    monkeypatch.setenv("BAGHBAN_NUGET_SOURCE", feed.url)
    monkeypatch.setattr(cp, "build_lister", lambda: Path("lister.dll"))
    monkeypatch.setattr(cp, "dotnet_views", lambda lister, dlls: {str(d): cp.python_view(d) for d in dlls})
    args = ["MyVision", "--cache", str(tmp_path / "c"), "--out", str(tmp_path / "r.json")]
    assert cp.main(args) == 0
    assert "identical to .NET" in capsys.readouterr().out

    def disagreeing(lister, dlls):
        views = {str(d): cp.python_view(d) for d in dlls}
        for v in views.values():
            v["resources"][0]["offset"] += 8
        return views
    monkeypatch.setattr(cp, "dotnet_views", disagreeing)
    assert cp.main(args) == 1
    assert "difference(s)" in capsys.readouterr().out
