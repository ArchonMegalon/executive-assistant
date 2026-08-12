from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.services import voice_runtime


ROOT = Path(__file__).resolve().parents[1]


def _slots() -> tuple[tuple[str, str], ...]:
    return (
        ("UNMIXR_API_KEY", "primary-key"),
        ("UNMIXR_API_KEY_FALLBACK_1", "preferred-a"),
        ("UNMIXR_API_KEY_FALLBACK_2", "reserve-key"),
        ("UNMIXR_API_KEY_FALLBACK_3", "preferred-b"),
        ("UNMIXR_API_KEY_FALLBACK_4", "standard-key"),
    )


def _configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    state_path = tmp_path / "unmixr-slot-selector.json"
    monkeypatch.setenv("EA_UNMIXR_SLOT_SELECTOR_ENABLED", "1")
    monkeypatch.setenv("EA_UNMIXR_SLOT_SELECTOR_STATE_FILE", str(state_path))
    monkeypatch.setenv(
        "EA_UNMIXR_PREFERRED_SLOTS",
        "UNMIXR_API_KEY_FALLBACK_1,UNMIXR_API_KEY_FALLBACK_3",
    )
    monkeypatch.setenv(
        "EA_UNMIXR_RESERVE_SLOTS",
        "UNMIXR_API_KEY_FALLBACK_2",
    )
    return state_path


def test_preferred_slots_rotate_before_standard_and_reserve(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = _configure(monkeypatch, tmp_path)
    state_path.write_text(
        json.dumps({"last_slot_name": "UNMIXR_API_KEY_FALLBACK_1"}),
        encoding="utf-8",
    )

    selected = voice_runtime._selected_unmixr_slots(_slots())

    assert [name for name, _key in selected] == [
        "UNMIXR_API_KEY_FALLBACK_3",
        "UNMIXR_API_KEY_FALLBACK_1",
        "UNMIXR_API_KEY",
        "UNMIXR_API_KEY_FALLBACK_4",
        "UNMIXR_API_KEY_FALLBACK_2",
    ]


def test_cooling_preferred_slots_fall_back_to_standard_before_reserve(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(voice_runtime.time, "time", lambda: 1_000.0)
    state_path.write_text(
        json.dumps(
            {
                "slots": {
                    "UNMIXR_API_KEY_FALLBACK_1": {"cooldown_until_epoch": 1_100},
                    "UNMIXR_API_KEY_FALLBACK_3": {"cooldown_until_epoch": 1_100},
                }
            }
        ),
        encoding="utf-8",
    )

    selected = voice_runtime._selected_unmixr_slots(_slots())

    assert [name for name, _key in selected] == [
        "UNMIXR_API_KEY",
        "UNMIXR_API_KEY_FALLBACK_4",
        "UNMIXR_API_KEY_FALLBACK_2",
    ]


def test_slot_policy_rejects_overlap_unknown_slots_and_pii(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "EA_UNMIXR_PREFERRED_SLOTS",
        "UNMIXR_API_KEY_FALLBACK_1",
    )
    monkeypatch.setenv(
        "EA_UNMIXR_RESERVE_SLOTS",
        "UNMIXR_API_KEY_FALLBACK_1",
    )
    with pytest.raises(HTTPException, match="unmixr_slot_policy_overlap"):
        voice_runtime._unmixr_slot_policy(_slots())

    monkeypatch.setenv("EA_UNMIXR_RESERVE_SLOTS", "UNMIXR_API_KEY_FALLBACK_99")
    with pytest.raises(HTTPException, match="unmixr_slot_policy_unknown_slot"):
        voice_runtime._unmixr_slot_policy(_slots())

    monkeypatch.setenv("EA_UNMIXR_RESERVE_SLOTS", "person@example.test")
    with pytest.raises(HTTPException, match="unmixr_account_slot_invalid"):
        voice_runtime._unmixr_slot_policy(_slots())


def test_slot_policy_summary_is_content_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UNMIXR_API_KEY", "primary-key")
    monkeypatch.setenv("UNMIXR_API_KEY_FALLBACK_1", "preferred-secret")
    monkeypatch.setenv("UNMIXR_API_KEY_FALLBACK_2", "reserve-secret")
    monkeypatch.setenv(
        "EA_UNMIXR_PREFERRED_SLOTS",
        "UNMIXR_API_KEY_FALLBACK_1",
    )
    monkeypatch.setenv(
        "EA_UNMIXR_RESERVE_SLOTS",
        "UNMIXR_API_KEY_FALLBACK_2",
    )

    summary = voice_runtime.unmixr_slot_policy_summary()
    serialized = json.dumps(summary, sort_keys=True)

    assert summary["status"] == "configured"
    assert summary["preferred_slot_count"] == 1
    assert summary["standard_slot_count"] == 1
    assert summary["reserve_slot_count"] == 1
    assert len(str(summary["policy_sha256"])) == 64
    assert summary["raw_credentials_exposed"] is False
    assert summary["account_emails_exposed"] is False
    assert "preferred-secret" not in serialized
    assert "reserve-secret" not in serialized


def test_runtime_services_receive_slot_policy_from_private_compose_environment() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    whatsapp = (ROOT / "docker-compose.whatsapp-web-session.yml").read_text(
        encoding="utf-8"
    )

    for marker in (
        "EA_UNMIXR_SLOT_SELECTOR_ENABLED=${EA_UNMIXR_SLOT_SELECTOR_ENABLED:-1}",
        "EA_UNMIXR_PREFERRED_SLOTS=${EA_UNMIXR_PREFERRED_SLOTS:-}",
        "EA_UNMIXR_RESERVE_SLOTS=${EA_UNMIXR_RESERVE_SLOTS:-}",
    ):
        assert compose.count(marker) == 3
        assert whatsapp.count(marker) == 1
