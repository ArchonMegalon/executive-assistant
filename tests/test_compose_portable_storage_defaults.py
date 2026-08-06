from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.fastestvpn.yml",
    "docker-compose.prod.yml",
    "docker-compose.whatsapp-web-session.yml",
)


def _rendered() -> str:
    return "\n".join((ROOT / name).read_text(encoding="utf-8") for name in COMPOSE_FILES)


def test_compose_uses_configurable_durable_storage_defaults() -> None:
    rendered = _rendered()

    assert "EA_AUDIOBOOK_DURABLE_STORAGE_ROOT" in rendered
    assert "EA_DURABLE_AUDIOBOOK_HOST_ROOT" in rendered
    assert "/data/audiobooks" in rendered
    assert "EA_ONEDRIVE_ATTACHMENTS_HOST_PATH:-./data/onedrive_attachments" in rendered
    assert "/data/onedrive_attachments" in rendered
    assert "EA_POCKET_AUDIO_ARCHIVE_HOST_ROOT:-./data/pocket-ai-audio" in rendered
    assert "EA_POCKET_AUDIO_ARCHIVE_ROOT" in rendered
    assert "/data/pocket-ai-audio" in rendered
    assert "EA_UI_SERVICE_SHARED_TEMP_ROOT" in rendered


def test_compose_does_not_default_to_old_host_storage_roots() -> None:
    rendered = _rendered()

    assert "/mnt/" + "pcloud" not in rendered
    assert "/mnt/" + "onedrive" not in rendered
    assert "/docker/" + "EA" not in rendered
    assert "/docker/" + "fleet" not in rendered
    assert "/docker/" + "property" not in rendered
    assert "/docker/" + "chummercomplete" not in rendered
