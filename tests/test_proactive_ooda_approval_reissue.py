from __future__ import annotations

import hashlib
import json
from pathlib import Path
import runpy
from types import SimpleNamespace

from app.services import proactive_ooda_approval_capture
from app.services.proactive_ooda_approval_reissue import (
    current_proactive_ooda_approval_request,
    reissue_current_proactive_ooda_approval,
)
from app.services.proactive_ooda_runtime_artifacts import load_runtime_artifact_bundle


def _bundle(*, live_pending: int = 0, live_pending_age_seconds: int = 0) -> dict[str, object]:
    return {
        "current_packet_live_pending_count": live_pending,
        "current_packet_callback_latest_age_seconds": live_pending_age_seconds,
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


def test_default_proactive_ooda_root_skips_inaccessible_optional_candidate(monkeypatch) -> None:
    module_path = Path(proactive_ooda_approval_capture.__file__).resolve()
    inaccessible_marker = next(
        candidate / "scripts" / "run_proactive_ooda.py"
        for candidate in module_path.parents
        if candidate.name == "ea"
    )
    real_is_file = Path.is_file

    def _is_file(path: Path) -> bool:
        if path == inaccessible_marker:
            raise PermissionError(path)
        return real_is_file(path)

    monkeypatch.setattr(Path, "is_file", _is_file)

    resolved = proactive_ooda_approval_capture.default_proactive_ooda_root()

    assert resolved.name != "ea"
    assert (resolved / "scripts" / "run_proactive_ooda.py").is_file()


def test_reissue_cli_keeps_canonical_runtime_root_ahead_of_compatibility_layout(monkeypatch) -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "reissue_proactive_ooda_approval.py"
    monkeypatch.setattr("sys.path", list(__import__("sys").path))

    namespace = runpy.run_path(script_path.as_posix(), run_name="reissue_cli_test")

    assert namespace["sys"].path.index(namespace["ROOT"].as_posix()) < namespace["sys"].path.index(
        namespace["EA_ROOT"].as_posix()
    )


def test_current_proactive_ooda_approval_request_requires_staged_decision_packet() -> None:
    request = current_proactive_ooda_approval_request(_bundle())

    assert request["ready"] is True
    assert request["packet_ref"] == "stage_packet:packet-1"
    assert request["staged_artifact_ref"] == "safe_work_result:result-1"
    assert request["approval_prompt"] == "Approve whether EA should keep this staged packet."
    assert request["staged_action_url"] == "https://example.test/candidate"


def test_current_proactive_ooda_approval_request_blocks_quality_gate_review() -> None:
    bundle = _bundle()
    bundle["safe_work_result"]["audit_receipt"] = {
        "status": "review",
        "fail_closed": True,
        "issues": [{"code": "candidate_quality_failed"}],
    }
    bundle["safe_work_result"]["quality_gate"] = {"status": "review"}
    bundle["safe_work_result"]["execution_receipt"] = {"stop_condition": "quality_gate_failed"}

    request = current_proactive_ooda_approval_request(bundle)

    assert request == {"ready": False, "reason": "safe_work_quality_gate_review"}


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
    assert result["current_packet_callback_latest_age_seconds"] == 0
    assert result["reissue_after_seconds"] == 0
    assert result["reissue_eligible"] is False
    assert send_calls == []


def test_reissue_current_proactive_ooda_approval_skips_fresh_live_surface_below_threshold(tmp_path) -> None:
    send_calls: list[dict[str, object]] = []

    result = reissue_current_proactive_ooda_approval(
        principal_id="exec",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        reissue_after_seconds=3600,
        bundle_loader=lambda **_kwargs: _bundle(live_pending=1, live_pending_age_seconds=120),
        sender=lambda **kwargs: send_calls.append(dict(kwargs)),
    )

    assert result["status"] == "already_live_pending"
    assert result["current_packet_callback_latest_age_seconds"] == 120
    assert result["reissue_after_seconds"] == 3600
    assert result["reissue_eligible"] is False
    assert send_calls == []


def test_reissue_current_proactive_ooda_approval_dry_run_allows_stale_live_surface_threshold(tmp_path) -> None:
    result = reissue_current_proactive_ooda_approval(
        principal_id="exec",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        reissue_after_seconds=3600,
        dry_run=True,
        bundle_loader=lambda **_kwargs: _bundle(live_pending=1, live_pending_age_seconds=7200),
    )

    assert result["status"] == "dry_run"
    assert result["reason"] == "approval_surface_ready_to_reissue"
    assert result["current_packet_live_pending_count"] == 1
    assert result["current_packet_callback_latest_age_seconds"] == 7200
    assert result["reissue_after_seconds"] == 3600
    assert result["reissue_eligible"] is True


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


def test_reissue_current_proactive_ooda_approval_blocks_generic_shortlist_candidate(tmp_path) -> None:
    send_calls: list[dict[str, object]] = []
    bundle = _bundle()
    bundle["safe_work_result"]["approval_prompt"] = (
        "Approve whether EA should proceed with this staged shortlist candidate. "
        "Research, compare, or draft only; require explicit approval before purchase, booking, cancellation, sending, posting, or commitment."
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


def test_reissue_current_proactive_ooda_approval_sends_stale_live_surface_after_threshold(tmp_path) -> None:
    sent: list[dict[str, object]] = []

    def _sender(**kwargs):
        sent.append(dict(kwargs))
        return SimpleNamespace(
            channel="telegram",
            delivery_transport="telegram",
            message_ids=("tg-1",),
            approval_surface={"present": True, "status": "pending", "message_ids": ("tg-1",)},
        )

    result = reissue_current_proactive_ooda_approval(
        principal_id="exec",
        root=tmp_path,
        state_path="state/proactive_ooda_notified.json",
        reissue_after_seconds=3600,
        container=SimpleNamespace(tool_runtime="tool", channel_runtime="channel", memory_runtime="memory"),
        bundle_loader=lambda **_kwargs: _bundle(live_pending=1, live_pending_age_seconds=7200),
        sender=_sender,
    )

    assert result["status"] == "sent"
    assert result["current_packet_live_pending_count_before"] == 1
    assert result["current_packet_callback_latest_age_seconds"] == 7200
    assert result["reissue_after_seconds"] == 3600
    assert result["reissue_eligible"] is True
    assert sent


def test_reissue_current_proactive_ooda_approval_skips_archived_receipt_when_live_callback_still_exists(tmp_path) -> None:
    state_path = "state/proactive_ooda_notified.json"
    archive_receipt_path = tmp_path / "state" / "proactive_ooda_run_receipts" / "20260702T113932Z-sent.json"
    stage_dir = tmp_path / "state" / "proactive_ooda_stage_packets"
    safe_dir = tmp_path / "state" / "proactive_ooda_safe_work_results"
    callback_dir = tmp_path / "state" / "proactive_ooda_approval_callbacks"

    stage_packet = {
        "schema": "proactive_ooda.stage_packet.v1",
        "packet_ref": "stage_packet:packet-1",
        "stage": {"kind": "approval_packet"},
        "approval": {"required": True},
    }
    safe_work_result = {
        "schema": "proactive_ooda.safe_work_result.v1",
        "result_ref": "safe_work_result:result-1",
        "source_packet_ref_hash": _hash(stage_packet["packet_ref"]),
        "status": "staged_for_user_decision",
        "approval": {"required": True},
        "approval_prompt": "Approve whether EA should keep this staged packet.",
        "staged_action_url": "https://example.test/candidate",
    }
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_dir.mkdir(parents=True, exist_ok=True)
    callback_dir.mkdir(parents=True, exist_ok=True)
    (stage_dir / "packet-1.json").write_text(json.dumps(stage_packet) + "\n", encoding="utf-8")
    (safe_dir / "result-1.json").write_text(json.dumps(safe_work_result) + "\n", encoding="utf-8")
    archive_receipt_path.parent.mkdir(parents=True, exist_ok=True)
    archive_receipt_path.write_text(
        json.dumps(
            {
                "notification_status": "sent",
                "item_count": 1,
                "stage_packet_ref_hashes": [_hash(stage_packet["packet_ref"])],
                "safe_work_result_ref_hashes": [_hash(safe_work_result["result_ref"])],
                "stage_packet_output_dir": str(stage_dir),
                "safe_work_result_output_dir": str(safe_dir),
                "telegram_message_ids": ["tg-1"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (callback_dir / "pending.json").write_text(
        json.dumps(
            {
                "schema": "ea.proactive_ooda_telegram_approval_callback.v1",
                "callback_token": "cb-1",
                "status": "pending",
                "created_at": "2026-07-02T11:39:34Z",
                "expires_at": "2099-01-01T00:00:00Z",
                "packet_ref": stage_packet["packet_ref"],
                "staged_artifact_ref": safe_work_result["result_ref"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    send_calls: list[dict[str, object]] = []
    result = reissue_current_proactive_ooda_approval(
        principal_id="exec",
        root=tmp_path,
        state_path=state_path,
        receipt_path=archive_receipt_path,
        stage_packet_dir=stage_dir,
        safe_work_result_dir=safe_dir,
        bundle_loader=load_runtime_artifact_bundle,
        sender=lambda **kwargs: send_calls.append(dict(kwargs)),
    )

    assert result["status"] == "already_live_pending"
    assert result["current_packet_live_pending_count"] == 1
    assert send_calls == []
