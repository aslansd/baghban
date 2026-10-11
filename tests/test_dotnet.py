"""The pure-Python .NET reader (baghban.dotnet).

Assemblies come from tests/dllkit.py, which can force every index width the
reader must handle. Where dnfile (an independent parser) is installed, it
confirms the generated files and the reader agree; the exact width
boundaries are pinned by the ECMA-335 rule alone, because dnfile is off by
one there (it widens at more than 2^n rows, the standard at 2^n or more,
as does Microsoft's System.Reflection.Metadata).

Beyond these tests, the reader was compared with dnfile on 168 real
assemblies (a .NET runtime and pythonnet, from PyPI): identical names,
offsets, bytes and assembly names, including 4-byte heaps. confirm/packages
compares it with Microsoft's reader on real Bonsai packages.
"""

import pytest

from baghban.dotnet import Assembly, NotADotNetAssembly
from dllkit import make_assembly

RES = {"MyPkg.Mod.A.bonsai": b"<WorkflowBuilder>a</WorkflowBuilder>",
       "MyPkg.B.bonsai": b"<b/>" * 3, "MyPkg.notes.txt": b"not a workflow"}

VARIANTS = {
    "plain": {},
    "wide_heaps": {"wide_heaps": True},
    "pe32plus": {"pe32plus": True},
    "coded_below": {"assembly_refs": 16383},
    "coded_at_boundary": {"assembly_refs": 16384},
    "coded_above": {"assembly_refs": 16385},
    "simple_below": {"assembly_refs": 65535, "wide_heaps": True},
    "simple_at_boundary": {"assembly_refs": 65536, "wide_heaps": True},
    "simple_above": {"assembly_refs": 65537, "wide_heaps": True},
}


@pytest.mark.parametrize("variant", VARIANTS)
def test_reads_names_and_bytes_at_every_index_width(variant):
    a = Assembly(make_assembly("MyPkg", RES, **VARIANTS[variant]))
    assert a.name == "MyPkg" and a.version == "1.2.3.4"
    assert [r.name for r in a.resources()] == list(RES)
    for name, data in RES.items():
        assert a.resource(name) == data
    assert a.bonsai_resources() == {k: v for k, v in RES.items() if k.endswith(".bonsai")}


def test_linked_resource_is_not_embedded():
    a = Assembly(make_assembly("MyPkg", {"MyPkg.A.bonsai": b"<a/>"}, linked=("Other.bonsai",)))
    embedded = {r.name: r.embedded for r in a.resources()}
    assert embedded == {"MyPkg.A.bonsai": True, "Other.bonsai": False}
    assert list(a.bonsai_resources()) == ["MyPkg.A.bonsai"]
    with pytest.raises(KeyError):
        a.resource("Other.bonsai")


def test_unknown_resource_raises_keyerror():
    with pytest.raises(KeyError):
        Assembly(make_assembly("MyPkg", RES)).resource("MyPkg.Nope.bonsai")


def test_no_resources():
    a = Assembly(make_assembly("Empty", {}))
    assert a.resources() == [] and a.bonsai_resources() == {}


@pytest.mark.parametrize("data,why", [
    (b"", "MZ"),
    (b"not a dll at all" * 10, "MZ"),
    (b"MZ" + b"\0" * 100, "PE"),
])
def test_rejects_non_pe(data, why):
    with pytest.raises(NotADotNetAssembly, match=why):
        Assembly(data)


def test_rejects_native_dll():
    data = bytearray(make_assembly("MyPkg", RES))
    pe = int.from_bytes(data[0x3C:0x40], "little")
    dirs = pe + 4 + 20 + 96
    data[dirs + 14 * 8: dirs + 14 * 8 + 8] = b"\0" * 8  # no CLI header: native code
    with pytest.raises(NotADotNetAssembly, match="native"):
        Assembly(bytes(data))


def test_rejects_truncated_file():
    data = make_assembly("MyPkg", RES)
    with pytest.raises(NotADotNetAssembly):
        Assembly(data[: len(data) // 2])


AGREES_WITH_DNFILE = [v for v in VARIANTS if "boundary" not in v]


@pytest.mark.parametrize("variant", AGREES_WITH_DNFILE)
def test_dnfile_agrees(variant, tmp_path):
    dnfile = pytest.importorskip("dnfile")
    path = tmp_path / "x.dll"
    path.write_bytes(make_assembly("MyPkg", RES, **VARIANTS[variant]))
    pe = dnfile.dnPE(str(path))
    theirs = [(str(r.Name), r.Offset) for r in pe.net.mdtables.ManifestResource.rows]
    ours = [(r.name, r.offset) for r in Assembly(path.read_bytes()).resources()]
    assert ours == theirs
    assert str(pe.net.mdtables.Assembly.rows[0].Name) == "MyPkg"
