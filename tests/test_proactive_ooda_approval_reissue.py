from __future__ import annotations

import hashlib
from types import SimpleNamespace

from app.services.proactive_ooda_approval_reissue import (
    current_proactive_ooda_approval_request,
    reissue_current_proactive_ooda_approval,
)


def _bundle(*, live_pending: int = 0) -> dict[str, object]:
    return {
        "current_packet_live_pending_count": live_pending,
        "stage_packet": {
            "packet_ref": "stage_packet:packet-1",
            "approval": {"required": True},
            "stage": {
                "kind": "research_packet",
                "payload": {},
            },
        },
        "safe_work_result": {
            "result_ref": "safe_work_result:result-1",
            "status": "staged_for_user_decision",
            "approval": {"required": True},
            "approval_prompt": "Approve whether EA should keep this staged packet.",
            "staged_action_url": "https://example.test/candidate",
        },
    }


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_current_proactive_ooda_approval_request_requires_staged_decision_packet() -> None:
    request = current_proactive_ooda_approval_request(_bundle())

    assert request["ready"] is True
    assert request["packet_ref"] == "stage_packet:packet-1"
    assert request["staged_artifact_ref"] == "safe_work_result:result-1"
    assert request["approval_prompt"] == "Approve whether EA should keep this staged packet."
    assert request["staged_action_url"] == "https://example.test/candidate"


def test_reissue_current_proactive_ooda_approval_dry_run_returns_redacted_surface_summary(tmp_path) -> None:
    result = reissue_current_proactive_ooda_approval(
        principal_id="exec",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        dry_run=True,
        bundle_loader=lambda **_kwargs: _bundle(),
    )

    assert result["status"] == "dry_run"
    assert result["packet_ref_sha256"]
    assert result["staged_artifact_ref_sha256"]
    assert result["approval_prompt_sha256"]
    assert result["staged_action_url_sha256"]
    assert "stage_packet:packet-1" not in str(result)
    assert "safe_work_result:result-1" not in str(result)


def test_reissue_current_proactive_ooda_approval_skips_when_current_surface_is_live(tmp_path) -> None:
    send_calls: list[dict[str, object]] = []

    result = reissue_current_proactive_ooda_approval(
        principal_id="exec",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        bundle_loader=lambda **_kwargs: _bundle(live_pending=1),
        sender=lambda **kwargs: send_calls.append(dict(kwargs)),
    )

    assert result["status"] == "already_live_pending"
    assert send_calls == []


def test_reissue_current_proactive_ooda_approval_skips_when_current_packet_already_decided(tmp_path) -> None:
    send_calls: list[dict[str, object]] = []
    bundle = _bundle()
    bundle["approval_outcome"] = {
        "approval_outcome_recorded": True,
        "status": "accepted_redacted",
        "packet_ref_sha256": _hash("stage_packet:packet-1"),
        "staged_artifact_sha256": _hash("safe_work_result:result-1"),
    }

    result = reissue_current_proactive_ooda_approval(
        principal_id="exec",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        bundle_loader=lambda **_kwargs: bundle,
        sender=lambda **kwargs: send_calls.append(dict(kwargs)),
    )

    assert result["status"] == "already_decided"
    assert result["reason"] == "current_packet_approval_outcome_already_recorded"
    assert result["approval_outcome_status"] == "accepted_redacted"
    assert send_calls == []


def test_reissue_current_proactive_ooda_approval_blocks_internal_proof_packet(tmp_path) -> None:
    send_calls: list[dict[str, object]] = []
    bundle = _bundle()
    bundle["safe_work_result"]["approval_prompt"] = (
        "Approve whether EA should preserve this proof packet as the canonical live check."
    )

    result = reissue_current_proactive_ooda_approval(
        principal_id="exec",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        bundle_loader=lambda **_kwargs: bundle,
        sender=lambda **kwargs: send_calls.append(dict(kwargs)),
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "approval_request_not_user_action_required"
    assert send_calls == []


def test_reissue_current_proactive_ooda_approval_sends_telegram_action_surface(tmp_path) -> None:
    sent: list[dict[str, object]] = []

    def _sender(**kwargs):
        sent.append(dict(kwargs))
        return SimpleNamespace(
            channel="telegram",
            delivery_transport="telegram",
            message_ids=("tg-1",),
            approval_surface={
                "present": True,
                "channel": "telegram",
                "status": "pending",
                "callback_token_sha256": "a" * 64,
                "expires_at": "2026-07-05T10:00:00Z",
                "packet_ref_sha256": "b" * 64,
                "staged_artifact_sha256": "c" * 64,
                "approval_prompt_sha256": "d" * 64,
                "staged_action_url_sha256": "e" * 64,
                "inline_button_count": 3,
                "url_button_count": 1,
                "message_count": 1,
                "message_ids": ("tg-1",),
            },
        )

    result = reissue_current_proactive_ooda_approval(
        principal_id="exec",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        container=SimpleNamespace(tool_runtime="tool", channel_runtime="channel", memory_runtime="memory"),
        bundle_loader=lambda **_kwargs: _bundle(),
        sender=_sender,
    )

    assert result["status"] == "sent"
    assert result["message_ids"] == ["tg-1"]
    assert result["approval_surface"]["status"] == "pending"
    assert result["approval_surface"]["inline_button_count"] == 3
    assert sent[0]["approval_request"]["packet_ref"] == "stage_packet:packet-1"
    assert sent[0]["approval_request"]["staged_artifact_ref"] == "safe_work_result:result-1"
    assert sent[0]["text"] == "Approve whether EA should keep this staged packet."
