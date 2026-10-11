"""Write minimal, valid .NET assemblies with embedded resources, for tests.

The layout follows ECMA-335 Partition II (PE32 file, CLI header, metadata
root, #~ / #Strings / #GUID / #Blob streams, Module, AssemblyRef,
AssemblyRefProcessor, Assembly and ManifestResource tables). ``wide_heaps``
forces 4-byte heap indexes and ``assembly_refs`` adds rows that widen coded
and simple indexes, so the reader is tested on every width it can meet.
dnfile, an independent parser, confirms the output is well-formed
(test_dotnet.py), so the reader is not only tested against this writer.
"""

import io
import struct
import zipfile

MODULE, ASSEMBLY, ASSEMBLYREF, ASSEMBLYREFPROCESSOR, MANIFESTRESOURCE = 0x00, 0x20, 0x23, 0x24, 0x28


def _align(b: bytes, n: int = 4) -> bytes:
    return b + b"\0" * (-len(b) % n)


def make_assembly(name: str, resources: dict, *, wide_heaps: bool = False,
                  assembly_refs: int = 0, linked: tuple = (), pe32plus: bool = False) -> bytes:
    """resources: resource name -> bytes (embedded). linked: names of resources
    stored in another assembly (Implementation points at AssemblyRef 1)."""
    # ---- heaps
    strings = bytearray(b"\0")

    def s(text):
        off = len(strings)
        strings.extend(text.encode("utf-8") + b"\0")
        return off

    module_name = s(name + ".dll")
    asm_name = s(name)
    ref_name = s("mscorlib") if (assembly_refs or linked) else 0
    res_names = [(s(n), n) for n in resources]
    linked_names = [s(n) for n in linked]
    if wide_heaps:  # make the heap genuinely large, as real 4-byte heaps are
        strings.extend(b"x" * 70000 + b"\0")
    guid = b"\x11" * 16
    blob = b"\0\0\0\0"

    # ---- resource data (II.24.2.4: 4-byte length, then bytes, 8-byte aligned)
    res_data = bytearray()
    offsets = {}
    for n, data in resources.items():
        offsets[n] = len(res_data)
        res_data += struct.pack("<I", len(data)) + data
        res_data += b"\0" * (-len(res_data) % 8)

    # ---- tables
    n_refs = max(assembly_refs, 1 if linked else 0)
    rows = {MODULE: 1, ASSEMBLY: 1}
    if n_refs:
        rows[ASSEMBLYREF] = n_refs
        rows[ASSEMBLYREFPROCESSOR] = 1
    rows[MANIFESTRESOURCE] = len(resources) + len(linked)
    hs = 0x07 if wide_heaps else 0
    sw = gw = bw = 4 if wide_heaps else 2
    pack = {2: "H", 4: "I"}
    simple_ref = 4 if n_refs >= 0x10000 else 2
    impl = 4 if n_refs >= (1 << 14) else 2  # Implementation: 2 tag bits

    def idx(width, value):
        return struct.pack("<" + pack[width], value)

    t = bytearray()
    t += struct.pack("<H", 0) + idx(sw, module_name) + idx(gw, 1) + idx(gw, 0) + idx(gw, 0)
    t += (struct.pack("<IHHHHI", 0x8004, 1, 2, 3, 4, 0) + idx(bw, 0) + idx(sw, asm_name)
          + idx(sw, 0))
    for _ in range(n_refs):
        t += struct.pack("<HHHHI", 4, 0, 0, 0, 0) + idx(bw, 0) + idx(sw, ref_name) + idx(sw, 0) + idx(bw, 0)
    if n_refs:
        t += struct.pack("<I", 0) + idx(simple_ref, 1)
    for off, n in res_names:
        t += struct.pack("<II", offsets[n], 1) + idx(sw, off) + idx(impl, 0)
    for off in linked_names:
        t += struct.pack("<II", 0, 1) + idx(sw, off) + idx(impl, (1 << 2) | 1)  # AssemblyRef #1

    valid = sum(1 << n for n in rows)
    header = struct.pack("<IBBBBQQ", 0, 2, 0, hs, 1, valid, 0)
    header += b"".join(struct.pack("<I", rows[n]) for n in sorted(rows))
    tables = _align(bytes(header + t))

    streams = [("#~", tables), ("#Strings", _align(bytes(strings))), ("#GUID", guid),
               ("#Blob", blob)]
    version = _align(b"v4.0.30319\0")
    hdr_len = 16 + len(version) + 4 + sum(8 + len(_align(n.encode() + b"\0")) for n, _ in streams)
    root = struct.pack("<IHHII", 0x424A5342, 1, 1, 0, len(version)) + version
    root += struct.pack("<HH", 0, len(streams))
    body, pos = b"", hdr_len
    for n, data in streams:
        root += struct.pack("<II", pos, len(data)) + _align(n.encode() + b"\0")
        body += data
        pos += len(data)
    metadata = root + body

    # ---- section: CLI header, resources, metadata
    text_rva, text_raw = 0x2000, 0x200
    cli_size = 72
    res_rva = text_rva + cli_size
    md_rva = res_rva + len(res_data)
    cli = struct.pack("<IHHIIII", cli_size, 2, 5, md_rva, len(metadata), 1, 0)
    cli += struct.pack("<II", res_rva if res_data else 0, len(res_data))
    cli += b"\0" * (cli_size - len(cli))
    section = cli + bytes(res_data) + metadata
    raw_size = len(section) + (-len(section) % 0x200)

    # ---- PE headers
    dos = bytearray(0x80)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x80)
    opt_size, dirs = (240, 112) if pe32plus else (224, 96)
    coff = struct.pack("<HHIIIHH", 0x8664 if pe32plus else 0x14C, 1, 0, 0, 0, opt_size,
                       0x2022 if pe32plus else 0x2102)
    opt = bytearray(opt_size)
    struct.pack_into("<H", opt, 0, 0x20B if pe32plus else 0x10B)
    struct.pack_into("<I", opt, dirs - 4, 16)  # NumberOfRvaAndSizes
    struct.pack_into("<II", opt, dirs + 14 * 8, text_rva, cli_size)
    sec = struct.pack("<8sIIIIIIHHI", b".text", len(section), text_rva, raw_size, text_raw,
                      0, 0, 0, 0, 0x60000020)
    headers = bytes(dos) + b"PE\0\0" + coff + bytes(opt) + sec
    headers += b"\0" * (text_raw - len(headers))
    return headers + section + b"\0" * (raw_size - len(section))


def make_nupkg(package_id: str, version: str, dlls: dict) -> bytes:
    """dlls: 'lib/net472/Name.dll' -> bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{package_id}.nuspec",
                    f"<package><metadata><id>{package_id}</id><version>{version}</version>"
                    f"</metadata></package>")
        for path, data in dlls.items():
            zf.writestr(path, data)
    return buf.getvalue()
