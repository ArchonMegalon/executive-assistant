from __future__ import annotations

from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SAFE_CINEMATIC_DEFAULTS = {
    "EA_AUDIOBOOK_CINEMATIC_SINGLE_PASS": "0",
    "EA_AUDIOBOOK_CINEMATIC_MAX_CHARS_PER_REQUEST": "1800",
}
CANARY_HMAC_KEY = "EA_AUDIOBOOK_CANARY_RECEIPT_HMAC_KEY"


def _env_example() -> dict[str, str]:
    entries: dict[str, str] = {}
    for raw_line in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        entries[key] = value
    return entries


def _compose_environment(path: Path, service_name: str) -> dict[str, str]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    services = payload.get("services")
    assert isinstance(services, dict)
    service = services.get(service_name)
    assert isinstance(service, dict)
    raw_environment = service.get("environment")
    assert isinstance(raw_environment, list)

    entries: dict[str, str] = {}
    for raw_entry in raw_environment:
        assert isinstance(raw_entry, str)
        key, separator, value = raw_entry.partition("=")
        assert separator == "="
        entries[key] = value
    return entries


def test_env_example_declares_safe_audiobook_runtime_defaults() -> None:
    environment = _env_example()

    assert {key: environment[key] for key in SAFE_CINEMATIC_DEFAULTS} == SAFE_CINEMATIC_DEFAULTS
    assert CANARY_HMAC_KEY in environment
    assert environment[CANARY_HMAC_KEY] == ""


@pytest.mark.parametrize("service_name", ("ea-api", "ea-worker", "ea-scheduler"))
def test_main_compose_audiobook_services_share_safe_runtime_contract(service_name: str) -> None:
    environment = _compose_environment(REPO_ROOT / "docker-compose.yml", service_name)

    for key, default in SAFE_CINEMATIC_DEFAULTS.items():
        assert environment[key] == f"${{{key}:-{default}}}"
    assert environment[CANARY_HMAC_KEY] == f"${{{CANARY_HMAC_KEY}:-}}"


def test_whatsapp_action_processor_shares_safe_audiobook_runtime_contract() -> None:
    environment = _compose_environment(
        REPO_ROOT / "docker-compose.whatsapp-web-session.yml",
        "ea-whatsapp-web-action-processor",
    )

    for key, default in SAFE_CINEMATIC_DEFAULTS.items():
        assert environment[key] == f"${{{key}:-{default}}}"
    assert environment[CANARY_HMAC_KEY] == f"${{{CANARY_HMAC_KEY}:-}}"
