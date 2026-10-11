import pytest

from baghban import packages


@pytest.fixture(autouse=True)
def isolated_package_caches(tmp_path_factory, monkeypatch):
    """Tests never read or write the developer's ~/.cache/baghban or ~/.nuget."""
    root = tmp_path_factory.mktemp("caches")
    monkeypatch.setenv("BAGHBAN_CACHE", str(root / "baghban"))
    monkeypatch.setenv("NUGET_PACKAGES", str(root / "nuget"))
    packages._ASSEMBLIES.clear()
    packages._REMOTE_VERSIONS.clear()
    yield
