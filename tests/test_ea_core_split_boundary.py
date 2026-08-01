from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOTS = ("ea/app/", "ea/scripts/", "deploy/")
RUNTIME_FILES = {".env.example", "Dockerfile", "Makefile", "pyproject.toml"}
RETIRED_ROUTE_PREFIX = "/" + "memorials"


def _tracked_runtime_paths() -> tuple[str, ...]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    paths = (item.decode("utf-8") for item in raw.split(b"\0") if item)
    return tuple(
        path
        for path in paths
        if path.startswith(RUNTIME_ROOTS)
        or Path(path).name.startswith("docker-compose")
        or path in RUNTIME_FILES
    )


def test_ea_core_runtime_tree_does_not_own_product_code() -> None:
    product_token = RETIRED_ROUTE_PREFIX.removeprefix("/").encode("utf-8")[:-1]
    offenders: list[str] = []
    for relative_path in _tracked_runtime_paths():
        path = ROOT / relative_path
        if not path.is_file() or path.is_symlink():
            continue
        if product_token in path.read_bytes().lower():
            offenders.append(relative_path)
    assert offenders == []


def test_ea_core_app_does_not_mount_retired_product_routes(monkeypatch) -> None:
    monkeypatch.setenv("EA_RUNTIME_MODE", "test")
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_ENABLE_LEGACY_RUNTIME_SURFACES", "0")
    from app.api.app import create_app

    route_paths = {str(route.path) for route in create_app().routes}
    assert not any(path == RETIRED_ROUTE_PREFIX or path.startswith(f"{RETIRED_ROUTE_PREFIX}/") for path in route_paths)
