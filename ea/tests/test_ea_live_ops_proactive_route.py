from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EA_LIVE_OPS_PATH = ROOT / "scripts" / "ea_live_ops.py"


def _load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_probe_proactive_route_upgrades_blocked_route_when_live_receipt_proves_telegram_delivery(monkeypatch) -> None:
    module = _load_script(EA_LIVE_OPS_PATH, "ea_live_ops_proactive_route_test")

    calls = {"count": 0}

    def _docker_json(*, compose_file, service, command, timeout_seconds):  # type: ignore[no-untyped-def]
        calls["count"] += 1
        if calls["count"] == 1:
            return (
                0,
                {
                    "ok": True,
                    "errors": [],
                    "delivery_route": {
                        "mode": "lightweight",
                        "ready": False,
                        "selected_channel": "",
                        "selected_transport": "",
                        "selected_by": "",
                        "selected_reason": "",
                        "binding_id_present": False,
                        "recipient_ref_hash_present": False,
                        "available_channels": [],
                        "errors": ["telegram_notification_not_configured"],
                        "route_error": "telegram_notification_not_configured",
                        "recovery_hint": "Link Telegram delivery.",
                        "next_action": "configure_telegram_proactive_delivery",
                        "preference_count": 0,
                        "policy_count": 0,
                        "follow_up_hint_count": 0,
                    },
                    "delivery_guard": {
                        "delivery_state": "",
                        "deferred_reason": "",
                    },
                },
                "",
                "",
            )
        return (
            0,
            {
                "ok": True,
                "delivery_mode": "telegram_sent",
                "notification_status": "sent",
                "delivery_channel": "telegram",
                "delivery_message_count": 1,
                "telegram_message_count": 1,
                "delivery_route_error": "",
                "delivery_recovery_hint": "",
                "delivery_next_action": "",
            },
            "",
            "",
        )

    monkeypatch.setattr(module, "_docker_compose_exec_json", _docker_json)
    monkeypatch.setattr(
        module,
        "probe_proactive_artifacts",
        lambda **kwargs: {
            "probe_ok": True,
            "current_packet_live_pending_count": 1,
            "run_receipt_path": "/tmp/proactive-run-receipt.json",
        },
    )

    report = module.probe_proactive_route(
        principal_id="cf-email:tibor.girschele@gmail.com",
        compose_file="/tmp/docker-compose.yml",
        runtime_service="ea-proactive-ooda",
        timeout_seconds=5.0,
        output_format="json",
    )

    assert report["probe_ok"] is True
    assert report["delivery_route_ready"] is True
    assert report["selected_channel"] == "telegram"
    assert report["blocking_reason"] == ""
    assert dict(report["route_report"])["delivery_route"]["ready"] is True
    assert dict(report["route_report"])["delivery_route"]["route_error"] == ""
    assert "live_receipt_route_override_applied" in list(dict(report["route_report"]).get("warnings") or [])
