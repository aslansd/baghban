"""Read embedded resources out of a .NET assembly, in pure Python.

Bonsai packages ship their workflows as *embedded resources* of the package
DLL (``<EmbeddedResource Include="**\\*.bonsai" />``), and a workflow includes
one as ``Path="BonVision:Primitives.DrawQuad.bonsai"``. Bonsai finds it with
``Assembly.GetManifestResourceStream("BonVision.Primitives.DrawQuad.bonsai")``
(Bonsai.Core/Expressions/IncludeWorkflowBuilder.cs): the assembly name, a
dot, and the rest of the path.

This module does the same lookup without .NET. It follows ECMA-335 (6th
edition), Partition II:

* the PE file: DOS header, COFF header, optional header, section table, and
  data directory 14, which locates the CLI header (II.25);
* the CLI header (II.25.3.3): where the metadata and the resources are;
* the metadata root and its streams (II.24.2); the ``#~`` table stream
  (II.24.2.6) and the ``#Strings`` heap;
* every table before ``ManifestResource`` (0x28), whose row sizes depend on
  heap and coded-index widths (II.22, II.24.2.6);
* each ``ManifestResource`` row (II.22.24) whose ``Implementation`` is null
  is in this file: at ``Resources RVA + Offset``, a 4-byte length, then the
  bytes.

Nothing here executes the assembly or loads its dependencies.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


class NotADotNetAssembly(ValueError):
    """The bytes are not a PE file with .NET metadata, or are malformed."""


# --------------------------------------------------------------------------- tables

# Table numbers, ECMA-335 II.22.
MODULE, TYPEREF, TYPEDEF, FIELDPTR, FIELD, METHODPTR, METHODDEF, PARAMPTR, PARAM = range(9)
INTERFACEIMPL, MEMBERREF, CONSTANT, CUSTOMATTRIBUTE, FIELDMARSHAL, DECLSECURITY = range(9, 15)
CLASSLAYOUT, FIELDLAYOUT, STANDALONESIG, EVENTMAP, EVENTPTR, EVENT = range(15, 21)
PROPERTYMAP, PROPERTYPTR, PROPERTY, METHODSEMANTICS, METHODIMPL, MODULEREF = range(21, 27)
TYPESPEC, IMPLMAP, FIELDRVA, ENCLOG, ENCMAP, ASSEMBLY = range(27, 33)
ASSEMBLYPROCESSOR, ASSEMBLYOS, ASSEMBLYREF, ASSEMBLYREFPROCESSOR, ASSEMBLYREFOS = range(33, 38)
FILE, EXPORTEDTYPE, MANIFESTRESOURCE, NESTEDCLASS, GENERICPARAM, METHODSPEC = range(38, 44)
GENERICPARAMCONSTRAINT = 44
_NONE = -1  # an unused slot in a coded index

# Coded indexes, II.24.2.6: the tables each one can point into, in tag order.
CODED = {
    "TypeDefOrRef": (TYPEDEF, TYPEREF, TYPESPEC),
    "HasConstant": (FIELD, PARAM, PROPERTY),
    "HasCustomAttribute": (METHODDEF, FIELD, TYPEREF, TYPEDEF, PARAM, INTERFACEIMPL,
                           MEMBERREF, MODULE, DECLSECURITY, PROPERTY, EVENT, STANDALONESIG,
                           MODULEREF, TYPESPEC, ASSEMBLY, ASSEMBLYREF, FILE, EXPORTEDTYPE,
                           MANIFESTRESOURCE, GENERICPARAM, GENERICPARAMCONSTRAINT, METHODSPEC),
    "HasFieldMarshal": (FIELD, PARAM),
    "HasDeclSecurity": (TYPEDEF, METHODDEF, ASSEMBLY),
    "MemberRefParent": (TYPEDEF, TYPEREF, MODULEREF, METHODDEF, TYPESPEC),
    "HasSemantics": (EVENT, PROPERTY),
    "MethodDefOrRef": (METHODDEF, MEMBERREF),
    "MemberForwarded": (FIELD, METHODDEF),
    "Implementation": (FILE, ASSEMBLYREF, EXPORTEDTYPE),
    "CustomAttributeType": (_NONE, _NONE, METHODDEF, MEMBERREF, _NONE),
    "ResolutionScope": (MODULE, MODULEREF, ASSEMBLYREF, TYPEREF),
}

# Column kinds: an int is a fixed width in bytes; "str"/"guid"/"blob" are heap
# indexes; ("t", n) is a simple index into table n; a name in CODED is a coded
# index. Tables up to and including ManifestResource, II.22.2-II.22.39.
SCHEMA = {
    MODULE: (2, "str", "guid", "guid", "guid"),
    TYPEREF: ("ResolutionScope", "str", "str"),
    TYPEDEF: (4, "str", "str", "TypeDefOrRef", ("t", FIELD), ("t", METHODDEF)),
    FIELDPTR: (("t", FIELD),),
    FIELD: (2, "str", "blob"),
    METHODPTR: (("t", METHODDEF),),
    METHODDEF: (4, 2, 2, "str", "blob", ("t", PARAM)),
    PARAMPTR: (("t", PARAM),),
    PARAM: (2, 2, "str"),
    INTERFACEIMPL: (("t", TYPEDEF), "TypeDefOrRef"),
    MEMBERREF: ("MemberRefParent", "str", "blob"),
    CONSTANT: (2, "HasConstant", "blob"),
    CUSTOMATTRIBUTE: ("HasCustomAttribute", "CustomAttributeType", "blob"),
    FIELDMARSHAL: ("HasFieldMarshal", "blob"),
    DECLSECURITY: (2, "HasDeclSecurity", "blob"),
    CLASSLAYOUT: (2, 4, ("t", TYPEDEF)),
    FIELDLAYOUT: (4, ("t", FIELD)),
    STANDALONESIG: ("blob",),
    EVENTMAP: (("t", TYPEDEF), ("t", EVENT)),
    EVENTPTR: (("t", EVENT),),
    EVENT: (2, "str", "TypeDefOrRef"),
    PROPERTYMAP: (("t", TYPEDEF), ("t", PROPERTY)),
    PROPERTYPTR: (("t", PROPERTY),),
    PROPERTY: (2, "str", "blob"),
    METHODSEMANTICS: (2, ("t", METHODDEF), "HasSemantics"),
    METHODIMPL: (("t", TYPEDEF), "MethodDefOrRef", "MethodDefOrRef"),
    MODULEREF: ("str",),
    TYPESPEC: ("blob",),
    IMPLMAP: (2, "MemberForwarded", "str", ("t", MODULEREF)),
    FIELDRVA: (4, ("t", FIELD)),
    ENCLOG: (4, 4),
    ENCMAP: (4,),
    ASSEMBLY: (4, 2, 2, 2, 2, 4, "blob", "str", "str"),
    ASSEMBLYPROCESSOR: (4,),
    ASSEMBLYOS: (4, 4, 4),
    ASSEMBLYREF: (2, 2, 2, 2, 4, "blob", "str", "str", "blob"),
    ASSEMBLYREFPROCESSOR: (4, ("t", ASSEMBLYREF)),
    ASSEMBLYREFOS: (4, 4, 4, ("t", ASSEMBLYREF)),
    FILE: (4, "str", "blob"),
    EXPORTEDTYPE: (4, 4, "str", "str", "Implementation"),
    MANIFESTRESOURCE: (4, 4, "str", "Implementation"),
}


# --------------------------------------------------------------------------- reader

@dataclass(frozen=True)
class Resource:
    name: str
    offset: int
    public: bool
    embedded: bool  # False when the resource lives in another file or assembly


class Assembly:
    """A .NET assembly read from bytes: its name and its manifest resources."""

    def __init__(self, data: bytes):
        self.data = data
        try:
            self._read_pe()
            self._read_metadata()
            self._read_tables()
        except (struct.error, IndexError) as exc:
            raise NotADotNetAssembly(f"truncated or malformed: {exc}") from exc

    # -- PE ---------------------------------------------------------------------
    def _u16(self, off):
        return struct.unpack_from("<H", self.data, off)[0]

    def _u32(self, off):
        return struct.unpack_from("<I", self.data, off)[0]

    def _read_pe(self):
        d = self.data
        if len(d) < 0x40 or d[:2] != b"MZ":
            raise NotADotNetAssembly("no MZ header")
        pe = self._u32(0x3C)
        if d[pe:pe + 4] != b"PE\0\0":
            raise NotADotNetAssembly("no PE signature")
        coff = pe + 4
        n_sections = self._u16(coff + 2)
        opt_size = self._u16(coff + 16)
        opt = coff + 20
        magic = self._u16(opt)
        if magic == 0x10B:
            dirs = opt + 96
        elif magic == 0x20B:
            dirs = opt + 112
        else:
            raise NotADotNetAssembly(f"unknown optional header magic {magic:#x}")
        n_dirs = self._u32(dirs - 4)
        if n_dirs <= 14:
            raise NotADotNetAssembly("no CLI header directory: not a .NET assembly")
        cli_rva, cli_size = struct.unpack_from("<II", d, dirs + 14 * 8)
        if cli_rva == 0:
            raise NotADotNetAssembly("no CLI header: a native DLL, not a .NET assembly")
        self.sections = []
        sec = opt + opt_size
        for i in range(n_sections):
            vsize, vaddr, raw_size, raw_ptr = struct.unpack_from("<IIII", d, sec + i * 40 + 8)
            self.sections.append((vaddr, max(vsize, raw_size), raw_ptr))
        cli = self._offset(cli_rva)
        self.metadata_rva, self.metadata_size = struct.unpack_from("<II", d, cli + 8)
        self.resources_rva, self.resources_size = struct.unpack_from("<II", d, cli + 24)

    def _offset(self, rva: int) -> int:
        for vaddr, size, raw in self.sections:
            if vaddr <= rva < vaddr + size:
                return rva - vaddr + raw
        raise NotADotNetAssembly(f"RVA {rva:#x} is in no section")

    # -- metadata root and streams (II.24.2.1, II.24.2.2) -------------------------
    def _read_metadata(self):
        root = self._offset(self.metadata_rva)
        if self._u32(root) != 0x424A5342:
            raise NotADotNetAssembly("bad metadata signature")
        ver_len = self._u32(root + 12)
        pos = root + 16 + ver_len
        n_streams = self._u16(pos + 2)
        pos += 4
        self.streams = {}
        for _ in range(n_streams):
            off, size = struct.unpack_from("<II", self.data, pos)
            end = self.data.index(b"\0", pos + 8)
            name = self.data[pos + 8:end].decode("ascii")
            pos = (end + 1 + 3) & ~3  # name is padded to a 4-byte boundary
            self.streams[name] = (root + off, size)
        if "#~" in self.streams:
            self._tables = self.streams["#~"]
        elif "#-" in self.streams:  # uncompressed (edit-and-continue) layout, same rows
            self._tables = self.streams["#-"]
        else:
            raise NotADotNetAssembly("no metadata table stream")

    def string(self, index: int) -> str:
        start, size = self.streams["#Strings"]
        pos = start + index
        end = self.data.index(b"\0", pos)
        return self.data[pos:end].decode("utf-8")

    # -- tables (II.24.2.6) --------------------------------------------------------
    def _read_tables(self):
        d = self.data
        pos, _size = self._tables
        heap_sizes = d[pos + 6]
        valid = struct.unpack_from("<Q", d, pos + 8)[0]
        pos += 24
        self.rows = [0] * 64
        for n in range(64):
            if valid >> n & 1:
                self.rows[n] = self._u32(pos)
                pos += 4
        if heap_sizes & 0x40:  # extra 4 bytes in edit-and-continue metadata
            pos += 4
        widths = {"str": 4 if heap_sizes & 1 else 2,
                  "guid": 4 if heap_sizes & 2 else 2,
                  "blob": 4 if heap_sizes & 4 else 2}

        def col_width(kind):
            if isinstance(kind, int):
                return kind
            if isinstance(kind, tuple):  # simple index
                return 2 if self.rows[kind[1]] < 0x10000 else 4
            if kind in widths:
                return widths[kind]
            tables = CODED[kind]
            tag_bits = (len(tables) - 1).bit_length()
            largest = max((self.rows[t] for t in tables if t != _NONE), default=0)
            return 2 if largest < (1 << (16 - tag_bits)) else 4

        self._layout = {}
        self._table_start = {}
        for n in range(MANIFESTRESOURCE + 1):
            cols = [col_width(k) for k in SCHEMA[n]]
            self._layout[n] = cols
            self._table_start[n] = pos
            pos += sum(cols) * self.rows[n]

    def _row(self, table: int, i: int) -> list:
        cols = self._layout[table]
        pos = self._table_start[table] + i * sum(cols)
        out = []
        for w in cols:
            out.append(self._u16(pos) if w == 2 else self._u32(pos))
            pos += w
        return out

    # -- what callers want ---------------------------------------------------------
    @property
    def name(self) -> str:
        """The assembly's simple name, from the Assembly table (II.22.2)."""
        if not self.rows[ASSEMBLY]:
            raise NotADotNetAssembly("no Assembly row: a .NET module, not an assembly")
        return self.string(self._row(ASSEMBLY, 0)[7])

    @property
    def version(self) -> str:
        r = self._row(ASSEMBLY, 0)
        return f"{r[1]}.{r[2]}.{r[3]}.{r[4]}"

    def resources(self) -> list:
        out = []
        for i in range(self.rows[MANIFESTRESOURCE]):
            offset, flags, name, implementation = self._row(MANIFESTRESOURCE, i)
            out.append(Resource(self.string(name), offset, (flags & 7) == 1, implementation == 0))
        return out

    def resource(self, name: str) -> bytes:
        """The bytes of an embedded resource; KeyError if there is none by that name."""
        for res in self.resources():
            if res.name == name:
                if not res.embedded:
                    raise KeyError(f"{name} is a linked resource, stored outside this file")
                start = self._offset(self.resources_rva) + res.offset
                length = self._u32(start)
                return self.data[start + 4:start + 4 + length]
        raise KeyError(name)

    def bonsai_resources(self) -> dict:
        """Every embedded resource whose name ends in .bonsai, name -> bytes."""
        return {r.name: self.resource(r.name) for r in self.resources()
                if r.embedded and r.name.endswith(".bonsai")}


def read_assembly(path) -> Assembly:
    with open(path, "rb") as fh:
        return Assembly(fh.read())
