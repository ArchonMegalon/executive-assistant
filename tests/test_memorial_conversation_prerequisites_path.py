from __future__ import annotations

from pathlib import Path

import pytest

from app.api.routes import public_memorials


def test_conversation_prerequisites_path_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "EA_MEMORIAL_CONVERSATION_PREREQUISITES_PATH",
        raising=False,
    )

    assert public_memorials._memorial_voice_release_receipt_path() is None
    assert public_memorials._memorial_voice_release_decision("manfred") == {
        "allowed": False,
        "status": "blocked",
        "reason": "conversation_prerequisites_path_unconfigured",
        "receipt_status": "",
    }


def test_conversation_prerequisites_path_must_be_absolute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "EA_MEMORIAL_CONVERSATION_PREREQUISITES_PATH",
        "conversation-release/prerequisites.json",
    )

    assert public_memorials._memorial_voice_release_receipt_path() is None
    assert (
        public_memorials._memorial_voice_release_decision("manfred")["reason"]
        == "conversation_prerequisites_path_unconfigured"
    )


def test_absolute_conversation_prerequisites_path_is_passed_to_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = Path(
        "/data/memorial_data/conversation-release/"
        "manfred_realtime_conversation_release.generated.json"
    )
    captured: dict[str, object] = {}

    def evaluate(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "allowed": False,
            "status": "blocked",
            "reason": "fixture",
            "receipt_status": "",
        }

    monkeypatch.setenv(
        "EA_MEMORIAL_CONVERSATION_PREREQUISITES_PATH",
        str(configured),
    )
    monkeypatch.setattr(
        public_memorials,
        "evaluate_memorial_voice_release",
        evaluate,
    )

    assert public_memorials._memorial_voice_release_receipt_path() == configured
    assert public_memorials._memorial_voice_release_decision("manfred")[
        "reason"
    ] == "fixture"
    assert captured == {"slug": "manfred", "receipt_path": configured}
