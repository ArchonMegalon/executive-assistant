from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_base_compose_omits_host_docker_control_for_core_services() -> None:
    compose = _load_yaml(ROOT / "docker-compose.yml")
    services = compose.get("services") or {}
    for service_name in ("ea-api", "ea-worker", "ea-scheduler", "ea-responses-proxy"):
        service = services.get(service_name) or {}
        volumes = [str(item) for item in list(service.get("volumes") or [])]
        assert not any("/var/run/docker.sock" in item for item in volumes), service_name
        assert not any(item.startswith("/docker:") or ":/docker" in item for item in volumes), service_name


def test_host_tools_override_carries_explicit_host_docker_access() -> None:
    compose = _load_yaml(ROOT / "docker-compose.host-tools.yml")
    services = compose.get("services") or {}
    for service_name in ("ea-api", "ea-worker", "ea-scheduler", "ea-responses-proxy"):
        service = services.get(service_name) or {}
        volumes = [str(item) for item in list(service.get("volumes") or [])]
        build = service.get("build") or {}
        assert any("/var/run/docker.sock" in item for item in volumes), service_name
        assert any(item.startswith("/docker:") or ":/docker" in item for item in volumes), service_name
        assert build.get("dockerfile") == "ea/Dockerfile.operator", service_name
        assert service.get("image") == "ea-runtime-operator:latest", service_name


def test_release_manifest_materializer_emits_authority_fields(tmp_path: Path) -> None:
    module = _load_script("materialize_release_manifest")
    output_path = tmp_path / "release_manifest.generated.json"

    manifest = module.build_manifest(output_path=output_path, generated_at="2026-06-22T18:40:00Z")

    assert manifest["contract_name"] == "ea.release_manifest.v1"
    assert manifest["repository"] == "EA"
    assert manifest["generated_at"] == "2026-06-22T18:40:00Z"
    assert set(("branch", "commit_sha", "deployment_id", "public_origin", "artifact_set", "release_label")) <= set(manifest)
    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted == manifest
