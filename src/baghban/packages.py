"""Follow includes into Bonsai packages: ``Path="BonVision:Primitives.DrawQuad.bonsai"``.

Such a workflow is an embedded resource of a package DLL. To read it,
baghban needs three things, found in this order:

1. **Which version.** Bonsai finds a workflow's environment by searching from
   the workflow's folder upwards for ``.bonsai/Bonsai.config``
   (``EnvironmentSelector.TryGetLocalBootstrapper`` in Bonsai.Configuration);
   baghban does the same. The file pins every package (``<Package id=...
   version=...>``) and records where each assembly lives
   (``<AssemblyLocation assemblyName=... location="Packages/Id.Version/lib/
   net472/Id.dll">``). ``--package ID=VERSION`` overrides it.
2. **The DLL.** Looked for, without any network access, in the installed
   environment (``.bonsai/Packages``), the NuGet global packages folder
   (``~/.nuget/packages`` or ``$NUGET_PACKAGES``), and baghban's own cache.
   Only with ``fetch=True`` (``--fetch``) is the ``.nupkg`` downloaded from
   nuget.org (or ``$BAGHBAN_NUGET_SOURCE``, a feed with the same flat-container
   layout), once, into the cache.
3. **The resource.** Read out of the DLL by :mod:`baghban.dotnet`, written to
   the cache as a plain ``.bonsai`` file, and loaded like any other include.

When no version is pinned, the newest version found (locally, or on nuget.org
with ``--fetch``) is used, and every report says so: findings inside it are
only as right as that guess.
"""

from __future__ import annotations

import io
import json
import os
import re
import ssl
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .dotnet import Assembly, NotADotNetAssembly

NUGET_FLAT = "https://api.nuget.org/v3-flatcontainer"
# Bonsai 2.x runs on .NET Framework; packages usually ship the same resources
# for every framework, so any will do, but prefer what Bonsai would load.
FRAMEWORK_PREFERENCE = ("net472", "net48", "net481", "net462", "net461", "net46", "net45",
                        "netstandard2.0", "netstandard2.1")


def default_cache() -> Path:
    env = os.environ.get("BAGHBAN_CACHE")
    if env:
        return Path(env)
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "baghban"


def nuget_global_folder() -> Path:
    env = os.environ.get("NUGET_PACKAGES")
    return Path(env) if env else Path(os.path.expanduser("~")) / ".nuget" / "packages"


# --------------------------------------------------------------------------- versions

def _version_key(v: str):
    """Order NuGet versions: numeric parts, stable after prerelease."""
    core, _, pre = v.partition("-")
    nums = []
    for part in core.split("+")[0].split("."):
        nums.append(int(part) if part.isdigit() else 0)
    while len(nums) < 4:
        nums.append(0)
    return (nums, pre == "", pre)


def newest(versions, stable_only: bool = True) -> Optional[str]:
    pool = [v for v in versions if "-" not in v] if stable_only else list(versions)
    if not pool and stable_only:
        pool = list(versions)
    return max(pool, key=_version_key) if pool else None


# --------------------------------------------------------------------------- environment

@dataclass
class Environment:
    """A Bonsai environment: ``.bonsai/Bonsai.config`` and what it pins."""

    config: Path
    packages: dict  # package id -> version
    locations: dict  # assembly name -> location relative to the .bonsai folder

    @property
    def folder(self) -> Path:
        return self.config.parent

    def package_of(self, assembly: str) -> Optional[tuple]:
        """(package id, version, path inside the package) for an assembly."""
        loc = self.locations.get(assembly)
        if loc:
            parts = loc.replace("\\", "/").split("/")
            if len(parts) >= 3 and parts[0].lower() == "packages":
                folder = parts[1]
                for pid, ver in self.packages.items():
                    if folder.lower() == f"{pid}.{ver}".lower():
                        return pid, ver, "/".join(parts[2:])
        for pid, ver in self.packages.items():
            if pid.lower() == assembly.lower():
                return pid, ver, None
        return None


def read_environment(config: Path) -> Optional[Environment]:
    try:
        root = ET.parse(config).getroot()
    except (ET.ParseError, OSError):
        return None
    packages, locations = {}, {}
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "Package" and el.get("id") and el.get("version"):
            packages[el.get("id")] = el.get("version")
        elif tag == "AssemblyLocation" and el.get("assemblyName") and el.get("location"):
            locations.setdefault(el.get("assemblyName"), el.get("location"))
    return Environment(config=config, packages=packages, locations=locations)


# Where an environment can live, in the order checked at each folder level.
# ".bonsai" is Bonsai's own rule (EnvironmentSelector); "Bonsai" and "bonsai"
# are portable Bonsai installs committed next to the workflows, which the
# survey found in published rigs (iblrig, vestibular-vr): those are the
# versions those labs actually run.
ENVIRONMENT_FOLDERS = (".bonsai", "Bonsai", "bonsai")


def find_environment(start: Path) -> Optional[Environment]:
    """The nearest Bonsai environment at or above ``start``.

    Like Bonsai, search from the workflow's folder upwards; at each level
    ``.bonsai/Bonsai.config`` first, then a portable install in ``Bonsai/`` or
    ``bonsai/``. A portable folder counts only if its Bonsai.config pins packages.
    """
    current = Path(start).resolve()
    if current.is_file():
        current = current.parent
    for folder in (current, *current.parents):
        for name in ENVIRONMENT_FOLDERS:
            config = folder / name / "Bonsai.config"
            if config.is_file():
                # on a case-insensitive file system (macOS, Windows) "Bonsai/" also
                # matches a folder named "bonsai": report the name on disk
                config = folder / _name_on_disk(folder, name) / "Bonsai.config"
                env = read_environment(config)
                if env is not None and (name == ".bonsai" or env.packages):
                    return env
    return None


def _name_on_disk(folder: Path, name: str) -> str:
    try:
        entries = os.listdir(folder)
    except OSError:
        return name
    if name in entries:
        return name
    for entry in entries:
        if entry.lower() == name.lower():
            return entry
    return name


# --------------------------------------------------------------------------- resolution

@dataclass
class Resolution:
    status: str  # ok | missing | unresolved
    path: Optional[Path] = None
    package: Optional[str] = None
    version: Optional[str] = None
    pinned: bool = False  # version from an environment or --package, not guessed
    origin: str = ""  # where the DLL came from
    note: str = ""


@dataclass
class _Package:
    id: str
    version: str
    pinned: bool
    origin: str
    assembly: Optional[Assembly] = None
    error: str = ""
    resources: dict = field(default_factory=dict)


class PackageResolver:
    """Finds embedded workflows in package DLLs. One per run; it caches."""

    def __init__(self, environment: Optional[Environment] = None, pins: Optional[dict] = None,
                 fetch: bool = False, cache_dir=None, nuget_folder=None,
                 source: Optional[str] = None, timeout: float = 30.0):
        self.environment = environment
        self.pins = dict(pins or {})
        self.fetch = fetch
        self.cache = Path(cache_dir) if cache_dir else default_cache()
        self.nuget_folder = Path(nuget_folder) if nuget_folder else nuget_global_folder()
        # a private feed or mirror with the same flat-container layout also works
        self.source = (source or os.environ.get("BAGHBAN_NUGET_SOURCE") or NUGET_FLAT).rstrip("/")
        self.timeout = timeout
        self._packages: dict = {}
        self.used: dict = {}  # (id, version) -> Resolution summary for reports
        self.problems: list = []

    @classmethod
    def for_workflow(cls, path, **kwargs) -> "PackageResolver":
        kwargs.setdefault("environment", find_environment(Path(path)))
        return cls(**kwargs)

    # -- public ---------------------------------------------------------------------
    def resolve(self, assembly: str, resource: str) -> Resolution:
        """``assembly`` and ``resource`` as in ``Path="assembly:resource"``."""
        pkg = self._package(assembly)
        if pkg is None or pkg.assembly is None:
            note = pkg.error if pkg is not None else ""
            return Resolution("unresolved", note=note)
        name = f"{assembly}.{resource}"  # IncludeWorkflowBuilder.GetWorkflowStream
        base = Resolution("ok", package=pkg.id, version=pkg.version, pinned=pkg.pinned,
                          origin=pkg.origin)
        try:
            data = pkg.assembly.resource(name)
        except KeyError:
            base.status = "missing" if pkg.pinned else "unresolved"
            base.note = (f"{pkg.id} {pkg.version} ({pkg.origin}) has no embedded workflow "
                         f"'{name}'")
            if not pkg.pinned:
                base.note += "; no environment pins this version, so this may be a version mismatch"
            return base
        if not _safe_name(name):
            base.status, base.note = "unresolved", f"unsafe resource name '{name}'"
            return base
        out = self.cache / "resources" / pkg.id.lower() / pkg.version / name
        if not out.is_file() or out.read_bytes() != data:
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(out.suffix + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, out)
        base.path = out
        self.used[(pkg.id, pkg.version)] = base
        return base

    def summary(self) -> list:
        """One line per package used, for reports."""
        lines = []
        for (pid, ver), res in sorted(self.used.items()):
            how = "pinned" if res.pinned else "NOT pinned: newest found, findings assume it"
            lines.append(f"{pid} {ver} ({how}; from {res.origin})")
        return lines

    # -- package lookup ---------------------------------------------------------------
    def _package(self, assembly: str) -> Optional[_Package]:
        if assembly in self._packages:
            return self._packages[assembly]
        pkg = self._locate(assembly)
        self._packages[assembly] = pkg
        return pkg

    def _locate(self, assembly: str) -> _Package:
        pid, version, inner, pinned, where = assembly, None, None, False, ""
        if self.environment is not None:
            found = self.environment.package_of(assembly)
            if found:
                pid, version, inner = found
                pinned, where = True, f"pinned in {self.environment.config}"
        for key, ver in self.pins.items():
            if key.lower() in (assembly.lower(), pid.lower()):
                pid, version, pinned, where = key, ver, True, "pinned with --package"

        if version is None:
            version = self._newest_available(pid)
            if version is None:
                if self.fetch:
                    hint = (f"nuget.org has no package '{pid}' either; if it is built from "
                            f"source, pass --resource-root {assembly}=DIR")
                else:
                    hint = (f"pass --fetch to download it from nuget.org, or --resource-root "
                            f"{assembly}=DIR to read it from source")
                return _Package(pid, "", False, "", error=(
                    f"embedded workflow of package '{pid}', which is not installed or cached; "
                    f"{hint}"))

        pkg = _Package(pid, version, pinned, "")
        for origin, loader in (("installed environment", lambda: self._from_environment(pid, version, inner, assembly)),
                               ("NuGet global packages", lambda: self._from_folder(self.nuget_folder / pid.lower() / version.lower(), assembly, inner)),
                               ("baghban cache", lambda: self._from_cache(pid, version, assembly, inner))):
            data = loader()
            if data is not None:
                pkg.origin = origin
                return self._read(pkg, data)
        if not self.fetch:
            pkg.error = (f"embedded workflow of package {pid} {version} ({where or 'newest'}), "
                         f"which is not installed or cached; pass --fetch to download it from "
                         f"nuget.org, or --resource-root {assembly}=DIR to read it from source")
            return pkg
        err = self._download(pid, version)
        if err:
            pkg.error = f"could not download {pid} {version}: {err}"
            self.problems.append(pkg.error)
            return pkg
        data = self._from_cache(pid, version, assembly, inner)
        if data is None:
            pkg.error = f"{pid} {version} contains no {assembly}.dll"
            return pkg
        pkg.origin = "nuget.org, downloaded to the baghban cache"
        return self._read(pkg, data)

    def _read(self, pkg: _Package, data: bytes) -> _Package:
        import hashlib
        key = hashlib.sha256(data).hexdigest()
        if key not in _ASSEMBLIES:
            try:
                _ASSEMBLIES[key] = Assembly(data)
            except NotADotNetAssembly as exc:
                pkg.error = f"{pkg.id} {pkg.version}: cannot read the assembly ({exc})"
                return pkg
        pkg.assembly = _ASSEMBLIES[key]
        return pkg

    def _newest_available(self, pid: str) -> Optional[str]:
        versions = set()
        for folder in (self.nuget_folder / pid.lower(), self.cache / "nuget" / pid.lower()):
            if folder.is_dir():
                versions |= {p.name for p in folder.iterdir() if p.is_dir()}
        if not versions and self.fetch:
            versions = set(self._remote_versions(pid))
        return newest(versions)

    # -- sources ---------------------------------------------------------------------
    def _from_environment(self, pid, version, inner, assembly) -> Optional[bytes]:
        if self.environment is None:
            return None
        folder = self.environment.folder / "Packages" / f"{pid}.{version}"
        return self._from_folder(folder, assembly, inner)

    @staticmethod
    def _from_folder(folder: Path, assembly: str, inner: Optional[str]) -> Optional[bytes]:
        if not folder.is_dir():
            return None
        if inner and (folder / inner).is_file():
            return (folder / inner).read_bytes()
        for candidate in _framework_order(p.relative_to(folder).as_posix()
                                          for p in folder.glob(f"lib/*/{assembly}.dll")):
            return (folder / candidate).read_bytes()
        return None

    def _nupkg(self, pid: str, version: str) -> Path:
        v = version.lower()
        return self.cache / "nuget" / pid.lower() / v / f"{pid.lower()}.{v}.nupkg"

    def _from_cache(self, pid, version, assembly, inner) -> Optional[bytes]:
        nupkg = self._nupkg(pid, version)
        if not nupkg.is_file():
            return None
        try:
            with zipfile.ZipFile(nupkg) as zf:
                names = zf.namelist()
                if inner and inner in names:
                    return zf.read(inner)
                wanted = [n for n in names
                          if re.fullmatch(rf"lib/[^/]+/{re.escape(assembly)}\.dll", n, re.I)]
                for candidate in _framework_order(wanted):
                    return zf.read(candidate)
        except zipfile.BadZipFile:
            return None
        return None

    def _get(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": _user_agent()})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read()

    def _remote_versions(self, pid: str) -> list:
        key = (self.source, pid.lower())
        if key in _REMOTE_VERSIONS:
            return _REMOTE_VERSIONS[key]
        try:
            data = json.loads(self._get(f"{self.source}/{pid.lower()}/index.json"))
            versions = list(data.get("versions", []))
        except urllib.error.HTTPError as exc:
            versions = []
            if exc.code != 404:
                self.problems.append(f"could not list versions of {pid}: {_describe(exc)}")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.problems.append(f"could not list versions of {pid}: {_describe(exc)}")
            return []  # not cached: a network hiccup should not stick for the whole run
        _REMOTE_VERSIONS[key] = versions
        return versions

    def _download(self, pid: str, version: str) -> str:
        v = version.lower()
        url = f"{self.source}/{pid.lower()}/{v}/{pid.lower()}.{v}.nupkg"
        try:
            data = self._get(url)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return f"nuget.org has no {pid} {version}"
            return _describe(exc)
        except (urllib.error.URLError, OSError) as exc:
            return _describe(exc)
        try:
            zipfile.ZipFile(io.BytesIO(data)).testzip()
        except zipfile.BadZipFile:
            return "the download is not a valid .nupkg"
        out = self._nupkg(pid, version)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, out)
        return ""


# Parsed assemblies and remote version lists, shared by every resolver in this
# process, so checking a folder of workflows reads each package DLL once.
_ASSEMBLIES: dict = {}
_REMOTE_VERSIONS: dict = {}


def _framework_order(paths) -> list:
    """Package-relative DLL paths, most preferred framework first."""
    def rank(p):
        parts = p.split("/")
        tfm = parts[1].lower() if len(parts) > 2 else ""
        return (FRAMEWORK_PREFERENCE.index(tfm) if tfm in FRAMEWORK_PREFERENCE
                else len(FRAMEWORK_PREFERENCE), p)
    return sorted(paths, key=rank)


def _safe_name(name: str) -> bool:
    """A resource name is used as a file name in the cache: no paths, no tricks."""
    return (bool(name) and not name.startswith(".") and ".." not in name
            and not any(c in name for c in "/\\\x00:"))


def _describe(exc: BaseException) -> str:
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(reason):
        return ("SSL certificate verification failed. With the python.org installer on macOS, "
                "run 'Install Certificates.command' from your Python folder once, or set "
                "SSL_CERT_FILE=$(python -m certifi)")
    return str(reason)


def _user_agent() -> str:
    from . import __version__
    return f"baghban/{__version__} (+https://github.com/aslansd/baghban)"


def fetch_nupkg(package_id: str, version: Optional[str] = None, cache_dir=None,
                source: Optional[str] = None, timeout: float = 60.0) -> tuple:
    """Download a package into baghban's cache unless it is already there.

    Returns ``(version, path to the .nupkg)``; the newest stable version when
    ``version`` is None. Raises ``RuntimeError`` with a readable reason.
    """
    r = PackageResolver(fetch=True, cache_dir=cache_dir, source=source, timeout=timeout)
    if version is None:
        version = newest(r._remote_versions(package_id))
        if version is None:
            reason = "; ".join(r.problems) or f"{r.source} has no package '{package_id}'"
            raise RuntimeError(reason)
    path = r._nupkg(package_id, version)
    if not path.is_file():
        err = r._download(package_id, version)
        if err:
            raise RuntimeError(err)
    return version, path
