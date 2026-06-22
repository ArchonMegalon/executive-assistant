from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_whatsapp_web_herta_live_e2e.py"


def _module():
    spec = importlib.util.spec_from_file_location("verify_whatsapp_web_herta_live_e2e", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _routes(ai_key: str = "empathetic_slow_typing_old_lady", per_char: int = 4000) -> dict[str, object]:
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
                "pre_reply_delay_max_seconds": 900,
                "pre_reply_delay_min_seconds": 60,
                "quiet_hours_end_hour": 6,
                "quiet_hours_start_hour": 21,
                "route_key": "436647916419",
                "typing_delay_ms_per_character": per_char,
            },
        ],
    }


def test_route_failures_require_herta_private_route_and_real_pacing() -> None:
    module = _module()

    failures = module.route_failures(
        _routes(ai_key="executive_assistant", per_char=0),
        expected_ai_key="empathetic_slow_typing_old_lady",
        required_route_keys=["436647916419"],
        expected_pre_reply_min_seconds=60,
        expected_pre_reply_max_seconds=900,
        expected_quiet_start_hour=21,
        expected_quiet_end_hour=6,
        expected_typing_delay_ms_per_character=4000,
    )

    assert failures == [
        {
            "mismatches": {
                "ai_key": {"actual": "executive_assistant", "expected": "empathetic_slow_typing_old_lady"},
                "typing_delay_ms_per_character": {"actual": 0, "expected": 4000},
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
