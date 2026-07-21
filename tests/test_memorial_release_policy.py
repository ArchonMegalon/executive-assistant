from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.routes import public_memorials
from app.services.memorial_release_policy import evaluate_memorial_voice_release


def _release_payload(*, generated_at: str) -> dict[str, object]:
    return {
        "contract_name": "ea.manfred_realtime_conversation_readiness.v1",
        "generated_by": "ea/scripts/materialize_manfred_realtime_conversation_readiness.py",
        "memorial_slug": "manfred",
        "status": "ready_for_realtime_conversation_review",
        "generated_at": generated_at,
        "evidence_source": "receipt_aggregation",
        "ready_for_realtime_conversation_review": True,
        "blocked_checks": [],
        "runtime_enablement_allowed": True,
        "voice_authority_verified": True,
        "realtime_conversation_claim_allowed": True,
        "premium_spoken_claim_allowed": True,
        "operator_acceptance_receipt_sha256": "1" * 64,
        "voice_authority_receipt_sha256": "2" * 64,
        "deployed_source_sha256": "3" * 64,
    }


def _write_private_receipt(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)


def test_memorial_voice_release_accepts_only_private_fresh_explicitly_bound_receipt(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 13, 4, 30, tzinfo=timezone.utc).timestamp()
    path = tmp_path / "release.json"
    _write_private_receipt(
        path,
        _release_payload(generated_at="2026-07-13T04:00:00Z"),
    )

    decision = evaluate_memorial_voice_release(
        slug="manfred",
        receipt_path=path,
        now=now,
    )

    assert decision == {
        "allowed": True,
        "status": "released",
        "reason": "",
        "receipt_status": "ready_for_realtime_conversation_review",
    }


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"runtime_enablement_allowed": False}, "release_human_acceptance_missing"),
        ({"voice_authority_verified": False}, "release_human_acceptance_missing"),
        ({"blocked_checks": ["manual_room_checks_confirmed"]}, "release_prerequisites_blocked"),
        ({"memorial_slug": "other"}, "release_receipt_slug_unbound"),
        ({"operator_acceptance_receipt_sha256": ""}, "release_digest_binding_missing"),
    ],
)
def test_memorial_voice_release_fails_closed_on_missing_authority_or_review_binding(
    tmp_path: Path,
    mutation: dict[str, object],
    reason: str,
) -> None:
    now = datetime(2026, 7, 13, 4, 30, tzinfo=timezone.utc).timestamp()
    payload = _release_payload(generated_at="2026-07-13T04:00:00Z")
    payload.update(mutation)
    path = tmp_path / "release.json"
    _write_private_receipt(path, payload)

    decision = evaluate_memorial_voice_release(
        slug="manfred",
        receipt_path=path,
        now=now,
    )

    assert decision["allowed"] is False
    assert decision["reason"] == reason


def test_memorial_voice_release_rejects_world_readable_or_symlinked_evidence(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 13, 4, 30, tzinfo=timezone.utc).timestamp()
    path = tmp_path / "release.json"
    _write_private_receipt(path, _release_payload(generated_at="2026-07-13T04:00:00Z"))
    path.chmod(0o644)

    world_readable = evaluate_memorial_voice_release(
        slug="manfred", receipt_path=path, now=now
    )
    assert world_readable["reason"] == "release_receipt_permissions_unsafe"

    path.chmod(0o600)
    link = tmp_path / "release-link.json"
    link.symlink_to(path)
    symlinked = evaluate_memorial_voice_release(
        slug="manfred", receipt_path=link, now=now
    )
    assert symlinked["reason"] == "release_receipt_symlink"


def test_memorial_voice_release_rejects_stale_evidence(tmp_path: Path) -> None:
    path = tmp_path / "release.json"
    _write_private_receipt(path, _release_payload(generated_at="2026-07-10T04:00:00Z"))

    decision = evaluate_memorial_voice_release(
        slug="manfred",
        receipt_path=path,
        now=datetime(2026, 7, 13, 4, 30, tzinfo=timezone.utc).timestamp(),
    )

    assert decision["reason"] == "release_receipt_stale"


def test_memorial_chat_contract_is_transparent_and_never_claims_to_be_manfred() -> None:
    payload = public_memorials._load_memorial("manfred")
    messages = public_memorials._build_memorial_chat_messages(
        payload,
        {},
        "Wer bist du wirklich?",
        slug="manfred",
        memory_runtime=None,
        personal_memory_context={},
    )
    instruction = str(messages[0]["content"])

    assert "Du sprichst hier als Manfred selbst" not in instruction
    assert "Sag niemals, dass du ein LLM" not in instruction
    assert "Du bist nicht Manfred" in instruction
    answer = public_memorials._enforce_memorial_narrator_boundary(
        "Ich bin Manfred. Ich bin wirklich hier.",
        question="Wer bist du wirklich?",
    )
    assert "nicht Manfred" in answer
    assert "Ich bin Manfred" not in answer


def test_memorial_voice_config_reports_clone_truthfully() -> None:
    payload = public_memorials._load_voice_config("manfred")
    public_payload = public_memorials._public_voice_config_payload("manfred", payload)

    assert payload["synthetic_voice_clone_of_memorial_person"] is True
    assert public_payload["synthetic_voice_clone_of_memorial_person"] is True


def test_production_voice_gate_rejects_before_provider_work(monkeypatch) -> None:
    payload = public_memorials._payload_with_slug(
        "manfred",
        public_memorials._load_memorial("manfred"),
    )
    monkeypatch.setattr(public_memorials, "_memorial_voice_release_enforced", lambda: True)
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda _slug: {
            "allowed": False,
            "status": "blocked",
            "reason": "release_prerequisites_blocked",
            "receipt_status": "blocked_realtime_prerequisites",
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        public_memorials._require_voice_consent(payload, "synthesize")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "memorial_voice_release_not_verified"


def test_blocked_release_prevents_page_prewarm(monkeypatch) -> None:
    scheduled: list[str] = []
    monkeypatch.setattr(public_memorials, "_memorial_page_prewarm_enabled", lambda: True)
    monkeypatch.setattr(public_memorials, "_memorial_voice_release_enforced", lambda: True)
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda _slug: {"allowed": False},
    )
    monkeypatch.setattr(
        public_memorials,
        "_schedule_memorial_live_warmup",
        lambda slug: scheduled.append(slug),
    )

    public_memorials._prime_memorial_live_warmup_on_page_render("manfred")

    assert scheduled == []
