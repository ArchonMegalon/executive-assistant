from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.domain.models import ObservationEvent
from scripts import materialize_telegram_video_delivery_live_receipt as live_module
from scripts.materialize_telegram_video_delivery_live_receipt import (
    EVENT_TYPE,
    build_receipt as build_live_receipt,
    _docker_postgres_diagnostics,
    _docker_postgres_observations,
    _load_runtime_env_files,
)


def _delivery_event(
    *,
    status: str = "sent",
    message_ids: list[str] | None = None,
    source_path_redacted: str = "/file/bot<redacted>/videos/file.mp4",
) -> ObservationEvent:
    return ObservationEvent(
        observation_id="obs-live-video-1",
        principal_id="principal-tibor",
        channel="telegram",
        event_type=EVENT_TYPE,
        payload={
            "receipt_type": "telegram_video_delivery",
            "chat_id": "123456789",
            "source_message_id": "source-message-42",
            "provider": "local_source_video_fx",
            "delivery_kind": "video",
            "telegram_method": "sendVideo",
            "status": status,
            "message_ids": message_ids if message_ids is not None else ["sent-video-77"],
            "source_video": {
                "has_source_video": True,
                "source_url_raw_stored": False,
                "source_url_sha256": "a" * 64,
                "source_host": "api.telegram.org",
                "source_path_redacted": source_path_redacted,
                "source_video_duration_seconds": 12,
                "source_video_reference_board_present": True,
                "source_video_reference_frame_count": 2,
            },
        },
        created_at="2026-06-18T10:00:00+00:00",
        source_id="telegram:123456789",
        external_id="source-message-42",
        dedupe_key="telegram-video-delivery:123456789:source-message-42:sent-video-77",
    )


def test_live_telegram_video_delivery_receipt_passes_with_redacted_sent_observation(tmp_path: Path) -> None:
    receipt = build_live_receipt(
        output_path=tmp_path / "telegram_video_delivery_live.generated.json",
        observations=[_delivery_event()],
        generated_at="2026-06-18T10:00:00Z",
    )

    assert receipt["contract_name"] == "ea.telegram_video_delivery_live_receipt"
    assert receipt["status"] == "pass"
    assert receipt["gold_claim_allowed"] is True
    assert receipt["next_action"] == ""
    assert receipt["delivery_observation_requirements"]["delivery_kind"] == "video"
    assert receipt["delivery_observation_requirements"]["telegram_method"] == "sendVideo"
    assert receipt["delivery_observation_requirements"]["message_ids_required"] is True
    selected = receipt["selected_observation"]
    assert selected["status"] == "sent"
    assert selected["delivery_kind"] == "video"
    assert selected["telegram_method"] == "sendVideo"
    assert selected["sent_message_ids"] == ["sent-video-77"]
    assert selected["chat_id_present"] is True
    assert selected["chat_id_sha256"]
    assert selected["source_message_id_sha256"]
    serialized = json.dumps(receipt)
    assert "123456789" not in serialized
    assert "source-message-42" not in serialized
    assert "bot123456" not in serialized


def test_live_telegram_video_delivery_receipt_blocks_without_live_observation(tmp_path: Path) -> None:
    receipt = build_live_receipt(
        output_path=tmp_path / "telegram_video_delivery_live.generated.json",
        observations=[],
        generated_at="2026-06-18T10:00:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["gold_claim_allowed"] is False
    assert receipt["failed_codes"] == ["live_observation_missing"]
    assert receipt["next_action"] == "trigger_real_telegram_video_edit_request_and_wait_for_sendVideo_receipt"


def test_live_telegram_video_delivery_receipt_blocks_failed_or_unredacted_observation(tmp_path: Path) -> None:
    receipt = build_live_receipt(
        output_path=tmp_path / "telegram_video_delivery_live.generated.json",
        observations=[
            _delivery_event(status="failed", message_ids=[]),
            _delivery_event(source_path_redacted="/file/bot123456:secret-token/videos/file.mp4"),
        ],
        generated_at="2026-06-18T10:00:00Z",
    )

    assert receipt["status"] == "blocked"
    failed_codes = {code for candidate in receipt["failed_candidates"] for code in candidate["failed_codes"]}
    assert "delivery_not_sent" in failed_codes
    assert "message_ids_missing" in failed_codes
    assert "source_path_redaction_failed" in failed_codes
    assert "telegram_bot_token_not_redacted" in failed_codes


def test_live_telegram_video_delivery_receipt_rejects_text_kind_message_id(tmp_path: Path) -> None:
    event = _delivery_event()
    event.payload["delivery_kind"] = "text"
    event.payload["telegram_method"] = "sendMessage"

    receipt = build_live_receipt(
        output_path=tmp_path / "telegram_video_delivery_live.generated.json",
        observations=[event],
        generated_at="2026-06-18T10:00:00Z",
    )

    assert receipt["status"] == "blocked"
    failed_codes = {code for candidate in receipt["failed_candidates"] for code in candidate["failed_codes"]}
    assert "delivery_kind_not_video" in failed_codes
    assert "telegram_method_not_send_video" in failed_codes
    assert receipt["next_action"] == "inspect_failed_delivery_candidates_and_fix_sendVideo_receipt_fields"


def test_live_telegram_video_delivery_env_loader_sets_runtime_connectivity_without_secret_names(
    monkeypatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "EA_STORAGE_BACKEND=postgres",
                "DATABASE_URL=postgresql://user:secret@example.invalid/db",
                "TELEGRAM_BOT_TOKEN=123456:secret-token",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("EA_STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    report = _load_runtime_env_files((env_file,))

    assert report["files"] == ["[external_path]"]
    assert report["loaded_count"] == 3
    assert report["storage_backend_present"] is True
    assert report["database_url_present"] is True
    assert "DATABASE_URL" not in str(report)
    assert "secret-token" not in str(report)


def test_live_telegram_video_delivery_docker_postgres_fallback_parses_redacted_rows(
    monkeypatch, tmp_path: Path
) -> None:
    row = _delivery_event()
    raw = {
        "observation_id": row.observation_id,
        "principal_id": row.principal_id,
        "channel": row.channel,
        "event_type": row.event_type,
        "payload": row.payload,
        "created_at": row.created_at,
        "source_id": row.source_id,
        "external_id": row.external_id,
        "dedupe_key": row.dedupe_key,
        "auth_context_json": row.auth_context_json,
        "raw_payload_uri": row.raw_payload_uri,
    }
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout=json.dumps(raw) + "\n", stderr="")

    monkeypatch.setattr(live_module.subprocess, "run", fake_run)
    monkeypatch.setattr(live_module, "resolve_source_state_head", lambda root: "SOURCE_HEAD")

    observations, metadata, error = _docker_postgres_observations(limit=5, principal_id="principal-tibor")
    receipt = build_live_receipt(
        output_path=tmp_path / "telegram_video_delivery_live.generated.json",
        observations=observations,
        observation_source="docker_postgres:ea-db",
        runtime_env={"docker_postgres_fallback": metadata},
        generated_at="2026-06-18T10:00:00Z",
    )

    assert error == ""
    assert metadata["status"] == "pass"
    assert metadata["selected_container"] == "ea-db"
    assert calls and calls[0][:2] == ["docker", "exec"]
    assert receipt["status"] == "pass"
    assert receipt["runtime_env"]["docker_postgres_fallback"]["row_count"] == 1
    assert "principal-tibor" not in json.dumps(receipt)


def test_live_telegram_video_delivery_docker_postgres_diagnostics_are_aggregate_and_redacted(
    monkeypatch,
) -> None:
    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        sql_arg = next((str(item) for item in cmd if str(item).startswith("EA_LIVE_SQL=")), "")
        sql = sql_arg.removeprefix("EA_LIVE_SQL=")
        if "payload_json::text ilike '%video%'" in sql and "group by event_type" not in sql:
            return SimpleNamespace(returncode=0, stdout="82\n", stderr="")
        if f"event_type = '{EVENT_TYPE}'" in sql:
            return SimpleNamespace(returncode=0, stdout="0\n", stderr="")
        if "rendered and sent a short video reply" in sql:
            return SimpleNamespace(returncode=0, stdout="3\n", stderr="")
        if "group by event_type" in sql and "payload_json::text ilike '%video%'" in sql:
            return SimpleNamespace(
                returncode=0,
                stdout="telegram.message|20\ntelegram.reply_async_sent|11\n",
                stderr="",
            )
        if "group by event_type" in sql:
            return SimpleNamespace(
                returncode=0,
                stdout="telegram.message|22\ntelegram.reply_async_sent|17\n",
                stderr="",
            )
        if "to_regclass('public.delivery_outbox')" in sql:
            return SimpleNamespace(returncode=0, stdout="delivery_outbox\n", stderr="")
        if "channel || '|'" in sql:
            return SimpleNamespace(returncode=0, stdout="email|queued|81\nslack|sent|1\n", stderr="")
        if "from delivery_outbox" in sql and "channel = 'telegram'" in sql:
            return SimpleNamespace(returncode=0, stdout="0\n", stderr="")
        if "where channel = 'telegram'" in sql:
            return SimpleNamespace(returncode=0, stdout="104\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(live_module.subprocess, "run", fake_run)

    diagnostics = _docker_postgres_diagnostics("ea-db")

    assert diagnostics["status"] == "pass"
    assert diagnostics["telegram_observation_count"] == 104
    assert diagnostics["telegram_video_related_observation_count"] == 82
    assert diagnostics["telegram_video_delivery_receipt_count"] == 0
    assert diagnostics["telegram_video_sent_text_ack_count"] == 3
    assert diagnostics["telegram_delivery_outbox_video_count"] == 0
    assert diagnostics["interpretation"] == "telegram_video_sent_text_ack_without_delivery_receipt"
    assert diagnostics["privacy"]["raw_payloads_included"] is False
    serialized = json.dumps(diagnostics)
    assert "123456789" not in serialized
    assert "source-message-42" not in serialized
    assert "render the private video" not in serialized.lower()


def test_live_telegram_video_delivery_receipt_flags_text_ack_without_delivery_receipt(tmp_path: Path) -> None:
    receipt = build_live_receipt(
        output_path=tmp_path / "telegram_video_delivery_live.generated.json",
        observations=[],
        runtime_env={
            "docker_postgres_fallback": {
                "diagnostics": {
                    "telegram_video_sent_text_ack_count": 2,
                    "telegram_video_delivery_receipt_count": 0,
                }
            }
        },
        generated_at="2026-06-18T10:00:00Z",
    )

    assert receipt["status"] == "blocked"
    assert "live_observation_missing" in receipt["failed_codes"]
    assert "video_sent_text_ack_without_delivery_receipt" in receipt["failed_codes"]
    assert receipt["next_action"] == "fix_runtime_to_record_sendVideo_delivery_receipt_before_claiming_video_sent"
