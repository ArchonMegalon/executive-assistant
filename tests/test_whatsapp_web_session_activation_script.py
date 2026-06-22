from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "activate_whatsapp_web_session.py"


def _module():
    spec = importlib.util.spec_from_file_location("activate_whatsapp_web_session", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "auth_header_name": "Authorization",
        "auth_header_prefix": "Bearer ",
        "binding_id": "principal-whatsapp-web-session",
        "browser_profile_ref": "docker-volume://ea_whatsapp_web_session",
        "database_url": "postgresql://example.invalid/ea",
        "display_name": "Principal User",
        "dry_run": False,
        "email": "principal@example.test",
        "phone_number": "+15550101000",
        "poll_interval_seconds": 0,
        "principal_id": "principal-default",
        "probe_session": False,
        "recipient": "+15550101000",
        "send_test": False,
        "session_api_base_url": "http://ea-whatsapp-web-session:8098",
        "session_api_token": "",
        "session_label": "Principal WhatsApp Web Session",
        "session_ref": "principal-wa-web",
        "session_send_url_template": "",
        "session_status_url_template": "",
        "session_store_ref": "",
        "tenant_id": "tenant-principal",
        "tenant_name": "Principal",
        "tenant_slug": "principal",
        "text": "EA WhatsApp Web live delivery test",
        "timeout_seconds": 5,
        "wait_seconds": 0,
    }
    values.update(overrides)
    return Namespace(**values)


def test_build_report_refuses_to_activate_when_sidecar_needs_qr(monkeypatch) -> None:
    module = _module()
    seeded = False

    def _unexpected_seed(*args, **kwargs):
        nonlocal seeded
        seeded = True
        raise AssertionError("should not seed while QR is required")

    monkeypatch.setattr(
        module,
        "_sidecar_status",
        lambda args: {
            "ok": True,
            "ready": False,
            "authenticated": False,
            "qr_required": True,
            "session_ref": "principal-wa-web",
            "status": "qr_required",
        },
    )
    monkeypatch.setattr(module.bootstrap, "seed_postgres", _unexpected_seed)

    report = module.build_report(_args())

    assert report["activated"] is False
    assert report["reason"] == "sidecar_not_ready"
    assert report["sidecar_qr_required"] is True
    assert seeded is False


def test_build_report_ready_dry_run_returns_sanitized_seed_without_db_write(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "_sidecar_status",
        lambda args: {
            "ok": True,
            "ready": True,
            "authenticated": True,
            "qr_required": False,
            "session_ref": "principal-wa-web",
            "status": "ready",
        },
    )

    report = module.build_report(_args(dry_run=True, session_api_token="session-token"))

    serialized = json.dumps(report)
    assert report["activated"] is False
    assert report["reason"] == "dry_run"
    assert report["would_seed"] is True
    assert report["seed"]["connector_status"] == "enabled"
    assert report["seed"]["session_api_token_present"] is True
    assert "session-token" not in serialized


def test_build_report_ready_sidecar_seeds_enabled_binding(monkeypatch) -> None:
    module = _module()
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        module,
        "_sidecar_status",
        lambda args: {
            "ok": True,
            "ready": True,
            "authenticated": True,
            "qr_required": False,
            "session_ref": "principal-wa-web",
            "status": "ready",
        },
    )

    def _fake_seed_postgres(database_url, seed):
        captured["database_url"] = database_url
        captured["seed"] = seed

    monkeypatch.setattr(module.bootstrap, "seed_postgres", _fake_seed_postgres)
    monkeypatch.setattr(
        module,
        "_readiness_report",
        lambda args: {
            "ready": True,
            "reason": "ready",
            "binding_id": "principal-whatsapp-web-session",
            "principal_id": "principal-default",
        },
    )

    report = module.build_report(_args())

    assert report["activated"] is True
    assert report["reason"] == "activated"
    assert captured["database_url"] == "postgresql://example.invalid/ea"
    assert captured["seed"].connector_status == "enabled"
    assert captured["seed"].session_ref == "principal-wa-web"
    assert captured["seed"].session_api_base_url == "http://ea-whatsapp-web-session:8098"


def test_build_report_can_chain_live_send_after_activation(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "_sidecar_status",
        lambda args: {
            "ok": True,
            "ready": True,
            "authenticated": True,
            "qr_required": False,
            "session_ref": "principal-wa-web",
            "status": "ready",
        },
    )
    monkeypatch.setattr(module.bootstrap, "seed_postgres", lambda database_url, seed: None)
    monkeypatch.setattr(module, "_readiness_report", lambda args: {"ready": True, "reason": "ready"})
    monkeypatch.setattr(
        module,
        "_live_send_report",
        lambda args: {
            "ready": True,
            "sent": True,
            "reason": "sent",
            "message_id_count": 1,
        },
    )

    report = module.build_report(_args(send_test=True))

    assert report["activated"] is True
    assert report["live_send"]["sent"] is True
    assert report["live_send"]["message_id_count"] == 1


def test_main_returns_nonzero_when_activation_is_not_ready(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(module, "parse_args", lambda: _args())
    monkeypatch.setattr(
        module,
        "_sidecar_status",
        lambda args: {
            "ok": True,
            "ready": False,
            "authenticated": False,
            "qr_required": True,
            "session_ref": "principal-wa-web",
            "status": "qr_required",
        },
    )

    exit_code = module.main()
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert output["activated"] is False
    assert output["reason"] == "sidecar_not_ready"
