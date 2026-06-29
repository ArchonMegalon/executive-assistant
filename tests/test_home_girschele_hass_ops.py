from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_home_girschele_compose_is_ea_owned_and_rotates_logs() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.home-girschele.yml").read_text(encoding="utf-8"))
    service = compose["services"]["home-girschele-hass"]

    assert service["profiles"] == ["home-assistant"]
    assert service["network_mode"] == "host"
    assert service["container_name"] == "home-girschele-hass"
    assert "/docker/EA/.state/home-girschele/homeassistant-config" in service["volumes"][0]
    assert service["logging"]["driver"] == "json-file"
    assert service["logging"]["options"]["max-size"] == "10m"
    assert service["logging"]["options"]["max-file"] == "3"


def test_home_girschele_ops_script_covers_operational_receipts() -> None:
    script = (ROOT / "scripts" / "home_girschele_hass_ops.sh").read_text(encoding="utf-8")

    for command in (
        "backup)",
        "restore-drill)",
        "drift)",
        "disk-log)",
        "scheduled-health)",
        "install-scheduled-health)",
    ):
        assert command in script

    for contract in (
        "home.girschele.home_assistant.health.v1",
        "home.girschele.home_assistant.backup.v1",
        "home.girschele.home_assistant.restore_drill.v1",
        "home.girschele.home_assistant.drift.v1",
        "home.girschele.home_assistant.disk_log.v1",
        "home.girschele.home_assistant.scheduled_health.v1",
        "home.girschele.home_assistant.schedule_install.v1",
    ):
        assert contract in script

    assert 'CF_ZONE_ID="${HOME_GIRSCHELE_CLOUDFLARE_ZONE_ID:-bd452cbf817e065da8063fc21673d536}"' in script
    assert 'ACCESS_EMAILS="${HOME_GIRSCHELE_ACCESS_EMAILS:-Tibor.girschele@gmail.com,Elisabeth.girschele@gmail.com,h.girschele@gmx.de,Archon.megalon@gmail.com}"' in script
    assert "load_home_girschele_private_defaults" in script
    assert "bd452cbf817e065da8063fc21673d536" in script
    assert "http://172.17.0.1:8123" in script
    assert 'max-size: "10m"' in script
    assert 'max-file: "3"' in script


def test_home_girschele_runbook_documents_recovery_and_safe_onboarding() -> None:
    runbook = (ROOT / "docs" / "HOME_GIRSCHELE_HOME_ASSISTANT_RUNBOOK.md").read_text(encoding="utf-8")

    for required in (
        "Backup And Restore Proof",
        "Drift And Pressure Monitoring",
        "Scheduled Health",
        "Safe Onboarding/Admin Path",
        "Cloudflare Access login flow",
        "homeassistant-backup.receipt.json",
        "homeassistant-restore-drill.receipt.json",
        "homeassistant-drift.receipt.json",
        "homeassistant-disk-log.receipt.json",
        "homeassistant-scheduled-health.receipt.json",
        "home-girschele-health.timer",
    ):
        assert required in runbook


def test_home_girschele_runtime_state_is_gitignored() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert ".state/home-girschele/" in gitignore
