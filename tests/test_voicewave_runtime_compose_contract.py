from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
OVERRIDE_PATH = REPO_ROOT / "docker-compose.voicewave-runtime.yml"
RUNBOOK_PATH = REPO_ROOT / "docs" / "MEMORIAL_VOICEWAVE_RUNTIME_RUNBOOK.md"


def _ea_api_service() -> dict[str, object]:
    payload = yaml.safe_load(OVERRIDE_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    services = payload.get("services")
    assert isinstance(services, dict)
    service = services.get("ea-api")
    assert isinstance(service, dict)
    return service


def _environment(service: dict[str, object]) -> dict[str, str]:
    raw_environment = service.get("environment")
    assert isinstance(raw_environment, list)
    entries: dict[str, str] = {}
    for raw_entry in raw_environment:
        assert isinstance(raw_entry, str)
        key, separator, value = raw_entry.partition("=")
        assert separator == "="
        entries[key] = value
    return entries




def test_override_does_not_mount_the_host_docker_socket() -> None:
    service = _ea_api_service()
    volumes = service.get("volumes") or []

    assert isinstance(volumes, list)
    assert all("docker.sock" not in str(volume) for volume in volumes)


def test_runbook_uses_exact_head_and_documents_host_side_worker() -> None:
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    assert 'EA_SOURCE_REVISION="$(git rev-parse --verify HEAD^{commit})"' in runbook
    assert "config --quiet" in runbook
    assert "host-side operator CLI" in runbook
    assert "does not mount `/var/run/docker.sock`" in runbook
