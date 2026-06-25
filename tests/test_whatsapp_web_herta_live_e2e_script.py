from __future__ import annotations

import argparse
import io
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_whatsapp_web_herta_live_e2e.py"


def _module():
    spec = importlib.util.spec_from_file_location("verify_whatsapp_web_herta_live_e2e", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _routes(ai_key: str = "empathetic_slow_typing_old_lady", per_char: int = 8000) -> dict[str, object]:
    return {
        "route_count": 2,
        "routes": [
            {
                "ai_key": "executive_assistant",
                "pre_reply_delay_max_seconds": 0,
                "pre_reply_delay_min_seconds": 0,
                "quiet_hours_end_hour": 0,
                "quiet_hours_start_hour": 0,
                "route_key": "40424366432273",
                "typing_delay_ms_per_character": 0,
            },
            {
                "ai_key": ai_key,
                "pre_reply_delay_max_seconds": 1800,
                "pre_reply_delay_min_seconds": 180,
                "quiet_hours_end_hour": 6,
                "quiet_hours_start_hour": 21,
                "route_key": "436647916419",
                "typing_delay_ms_per_character": per_char,
            },
        ],
    }


def _args(**overrides: object) -> argparse.Namespace:
    values = {
        "conversation_fetch_timeout_ms": 15000,
        "conversation_message_limit": 40,
        "conversation_take": 5,
        "expected_ai_key": "empathetic_slow_typing_old_lady",
        "recipient": "436647916419",
        "send": False,
        "request_timeout_seconds": 30.0,
        "send_text": "passt live",
        "send_timeout_seconds": 960.0,
        "session_api_base_url": "https://wa-web.test",
        "session_ref": "default-wa-web",
        "since": "",
        "wait_seconds": 0,
        "poll_interval_seconds": 1.0,
        "required_route_keys": "436647916419",
        "expected_sender_digits": "436647916419",
        "body_contains": "passt live",
        "no_require_auto_reply": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_resolve_session_ref_prefers_live_sidecar_health_ref(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "_get_healthz_json",
        lambda **_kwargs: {"ok": True, "session_ref": "tibor-wa-web", "status": "ready"},
    )

    resolved = module.resolve_session_ref(
        base_url="https://wa-web.test",
        configured_session_ref="default-wa-web",
        timeout_seconds=3.0,
    )

    assert resolved["configured_session_ref"] == "default-wa-web"
    assert resolved["session_ref"] == "tibor-wa-web"
    assert resolved["session_ref_source"] == "sidecar_healthz"
    assert resolved["sidecar_health_status"] == "ready"


def test_resolve_session_ref_falls_back_to_configured_when_health_has_no_ref(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(module, "_get_healthz_json", lambda **_kwargs: {"ok": True, "status": "starting"})

    resolved = module.resolve_session_ref(
        base_url="https://wa-web.test",
        configured_session_ref="default-wa-web",
        timeout_seconds=3.0,
    )

    assert resolved["session_ref"] == "default-wa-web"
    assert resolved["session_ref_source"] == "configured"


def test_fetch_snapshot_uses_effective_session_ref(monkeypatch) -> None:
    module = _module()
    seen: list[tuple[str, str]] = []

    def fake_get_json(*, session_ref: str, suffix: str, **_kwargs):
        seen.append((session_ref, suffix))
        return {"ok": True}

    monkeypatch.setattr(module, "_get_json", fake_get_json)

    snapshot = module.fetch_snapshot(_args(session_ref="default-wa-web"), session_ref="tibor-wa-web")

    assert set(snapshot) == {"status", "routes", "inbox", "outbox", "conversations"}
    assert {session_ref for session_ref, _suffix in seen} == {"tibor-wa-web"}


def test_run_reports_session_not_ready_without_traceback(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "resolve_session_ref",
        lambda **_kwargs: {
            "configured_session_ref": "default-wa-web",
            "session_ref": "tibor-wa-web",
            "session_ref_source": "sidecar_healthz",
            "sidecar_health_ok": True,
            "sidecar_health_status": "qr_required",
        },
    )

    def raise_session_not_ready(*_args, **_kwargs):
        raise module.urllib.error.HTTPError(
            "https://wa-web.test/sessions/tibor-wa-web/conversations",
            409,
            "Conflict",
            {},
            io.BytesIO(b'{"ok":false,"reason":"session_not_ready","status":"qr_required"}'),
        )

    monkeypatch.setattr(module, "fetch_snapshot", raise_session_not_ready)

    report = module.run(
        _args(
            body_contains="passt live",
            expected_sender_digits="436647916419",
            no_require_auto_reply=False,
            poll_interval_seconds=1.0,
            required_route_keys="436647916419",
            since="2026-06-25T12:00:00Z",
            wait_seconds=0,
        )
    )

    serialized = json.dumps(report, sort_keys=True)
    assert report["ok"] is False
    assert report["reason"] == "session_not_ready"
    assert report["status"] == "qr_required"
    assert report["http_status"] == 409
    assert report["failure_count"] == 1
    assert report["session_ref"] == "tibor-wa-web"
    assert "Traceback" not in serialized


def test_send_prompt_uses_effective_session_ref(monkeypatch) -> None:
    module = _module()
    captured: dict[str, object] = {}

    def fake_post_json(*, session_ref: str, body: dict[str, object], **_kwargs):
        captured["session_ref"] = session_ref
        captured["body"] = body
        return {"ok": True}

    monkeypatch.setattr(module, "_post_json", fake_post_json)

    sent = module.send_prompt(_args(session_ref="default-wa-web"), session_ref="tibor-wa-web")

    assert sent == {"ok": True}
    assert captured["session_ref"] == "tibor-wa-web"
    assert captured["body"]["to"] == "436647916419"


def test_route_failures_require_herta_private_route_and_real_pacing() -> None:
    module = _module()

    failures = module.route_failures(
        _routes(ai_key="executive_assistant", per_char=0),
        expected_ai_key="empathetic_slow_typing_old_lady",
        required_route_keys=["436647916419"],
        expected_pre_reply_min_seconds=180,
        expected_pre_reply_max_seconds=1800,
        expected_quiet_start_hour=21,
        expected_quiet_end_hour=6,
        expected_typing_delay_ms_per_character=8000,
    )

    assert failures == [
        {
            "mismatches": {
                "ai_key": {"actual": "executive_assistant", "expected": "empathetic_slow_typing_old_lady"},
                "typing_delay_ms_per_character": {"actual": 0, "expected": 8000},
            },
            "reason": "required_route_mismatch",
            "route_key": "436647916419",
        }
    ]


def test_verify_snapshot_passes_when_inbound_and_auto_reply_match() -> None:
    module = _module()
    cutoff = module._parse_iso("2026-06-21T23:47:00Z")

    report = module.verify_snapshot(
        status_payload={"auto_reply_enabled": True, "ready": True, "status": "ready"},
        routes_payload=_routes(),
        inbox_payload={
            "messages": [
                {
                    "body_text": "passt live",
                    "direction": "inbound",
                    "from_me": False,
                    "heyy_ai_key": "empathetic_slow_typing_old_lady",
                    "heyy_ai_route_matched": True,
                    "received_at": "2026-06-21T23:48:00Z",
                    "sender_digits": "436647916419",
                }
            ]
        },
        outbox_payload={
            "messages": [
                {
                    "body_present": True,
                    "body_text": "Ja, passt. Ich tipp nur langsam.",
                    "heyy_ai_key": "empathetic_slow_typing_old_lady",
                    "origin": "auto_reply",
                    "sent_at": "2026-06-21T23:48:20Z",
                }
            ]
        },
        conversations_payload={"conversations": []},
        cutoff=cutoff,
        expected_ai_key="empathetic_slow_typing_old_lady",
        required_route_keys=["436647916419"],
        expected_sender_digits="436647916419",
        body_contains="passt live",
        require_auto_reply=True,
    )

    assert report["ok"] is True
    assert report["failure_count"] == 0
    assert report["inbound"]["body_text"] == "passt live"
    assert report["auto_reply"]["origin"] == "auto_reply"


def test_verify_snapshot_reports_missing_live_inbound_and_auto_reply() -> None:
    module = _module()
    cutoff = module._parse_iso("2026-06-21T23:47:00Z")

    report = module.verify_snapshot(
        status_payload={"auto_reply_enabled": True, "ready": True, "status": "ready"},
        routes_payload=_routes(),
        inbox_payload={"messages": []},
        outbox_payload={
            "messages": [
                {
                    "body_present": True,
                    "body_text": "Mei, schreib mir passt live.",
                    "heyy_ai_key": "empathetic_slow_typing_old_lady",
                    "origin": "send",
                    "sent_at": "2026-06-21T23:47:32Z",
                }
            ]
        },
        conversations_payload={"conversations": []},
        cutoff=cutoff,
        expected_ai_key="empathetic_slow_typing_old_lady",
        required_route_keys=["436647916419"],
        expected_sender_digits="436647916419",
        body_contains="passt live",
        require_auto_reply=True,
    )

    assert report["ok"] is False
    assert [failure["reason"] for failure in report["failures"]] == [
        "matching_inbound_not_seen",
        "matching_auto_reply_not_seen",
    ]


def test_conversation_history_can_supply_matching_inbound() -> None:
    module = _module()
    cutoff = module._parse_iso("2026-06-21T23:47:00Z")

    inbound = module.find_matching_inbound(
        module.messages_from_payloads(
            {"messages": []},
            {
                "conversations": [
                    {
                        "messages": [
                            {
                                "body_text": "passt live",
                                "direction": "inbound",
                                "from_me": False,
                                "heyy_ai_key": "empathetic_slow_typing_old_lady",
                                "heyy_ai_route_matched": True,
                                "message_timestamp": "2026-06-21T23:49:00Z",
                                "sender_digits": "436647916419",
                            }
                        ]
                    }
                ]
            },
        ),
        cutoff=cutoff,
        expected_sender_digits="436647916419",
        expected_ai_key="empathetic_slow_typing_old_lady",
        body_contains="passt live",
    )

    assert inbound["body_text"] == "passt live"
