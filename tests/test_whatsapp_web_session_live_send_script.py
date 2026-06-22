from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "send_whatsapp_web_session_live_test.py"


def _module():
    spec = importlib.util.spec_from_file_location("send_whatsapp_web_session_live_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "binding_json": "",
        "database_url": "",
        "binding_id": "wa-web-binding-1",
        "principal_id": "principal-wa-web-1",
        "recipient": "+15550101000",
        "text": "EA WhatsApp Web live delivery test",
        "heyy_ai_key": "",
        "heyy_ai_name": "",
        "probe_session": False,
        "dry_run": False,
    }
    values.update(overrides)
    return Namespace(**values)


def _binding(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "binding_id": "wa-web-binding-1",
        "principal_id": "principal-wa-web-1",
        "connector_name": "whatsapp_web_session",
        "external_account_ref": "+15550101000",
        "scope_json": {
            "scopes": ["whatsapp.send"],
            "service_routes": {"applies_to": ["connector.dispatch", "executive_assistant_channel_send"]},
        },
        "auth_metadata_json": {
            "session_ref": "session-secret",
            "session_store_ref": "vault://ea/whatsapp-web/session-secret",
            "session_send_url_template": "https://wa-web.test/sessions/{session_ref}/messages",
            "session_api_token": "session-token",
        },
        "status": "enabled",
        "created_at": "2026-06-21T00:00:00Z",
        "updated_at": "2026-06-21T00:00:00Z",
    }
    values.update(overrides)
    return values


def _write_binding(tmp_path: Path, **overrides: object) -> Path:
    path = tmp_path / "binding.json"
    path.write_text(json.dumps(_binding(**overrides)), encoding="utf-8")
    return path


def test_build_report_fails_closed_when_binding_is_not_ready(tmp_path: Path) -> None:
    module = _module()
    binding_file = _write_binding(tmp_path, status="staged")

    report = module.build_report(_args(binding_json=str(binding_file)))

    assert report["ready"] is False
    assert report["sent"] is False
    assert report["reason"] == "binding_disabled"
    assert report["binding_id"] == "wa-web-binding-1"


def test_build_report_dry_run_does_not_send_or_leak_session_values(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    binding_file = _write_binding(tmp_path)

    def _unexpected_send(**kwargs):
        raise AssertionError("send should not run during dry-run")

    monkeypatch.setattr(module.whatsapp_web_session_delivery, "send_whatsapp_web_session_text", _unexpected_send)

    report = module.build_report(_args(binding_json=str(binding_file), dry_run=True))

    serialized = json.dumps(report)
    assert report["ready"] is True
    assert report["sent"] is False
    assert report["reason"] == "dry_run"
    assert report["recipient_present"] is True
    assert "session-token" not in serialized
    assert "session-secret" not in serialized


def test_build_report_sends_with_ready_binding_and_returns_sanitized_receipt(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    binding_file = _write_binding(tmp_path)
    captured: dict[str, object] = {}

    def _fake_send(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            principal_id="principal-wa-web-1",
            binding_id="wa-web-binding-1",
            connector_name="whatsapp_web_session",
            recipient="4368120864006",
            session_ref="session-secret",
            message_ids=("wamid.live.1",),
            request_url="https://wa-web.test/sessions/session-secret/messages",
            binding_status="enabled",
            external_account_ref="+15550101000",
        )

    monkeypatch.setattr(module.whatsapp_web_session_delivery, "send_whatsapp_web_session_text", _fake_send)

    report = module.build_report(_args(binding_json=str(binding_file), text="private live test text"))

    serialized = json.dumps(report)
    assert report["ready"] is True
    assert report["sent"] is True
    assert report["reason"] == "sent"
    assert report["message_ids"] == ["wamid.live.1"]
    assert report["message_id_count"] == 1
    assert report["request_url_present"] is True
    assert report["request_host"] == "wa-web.test"
    assert report["external_account_ref_present"] is True
    assert captured["recipient"] == "+15550101000"
    assert captured["text"] == "private live test text"
    assert captured["heyy_ai_key"] == ""
    assert captured["heyy_ai_name"] == ""
    assert "session-token" not in serialized
    assert "session-secret" not in serialized
    assert "private live test text" not in serialized


def test_build_report_passes_heyy_ai_override_to_live_send(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    binding_file = _write_binding(tmp_path)
    captured: dict[str, object] = {}

    def _fake_send(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            principal_id="principal-wa-web-1",
            binding_id="wa-web-binding-1",
            connector_name="whatsapp_web_session",
            recipient="4368120864006",
            session_ref="session-secret",
            message_ids=("wamid.herta.1",),
            request_url="https://wa-web.test/sessions/session-secret/messages",
            binding_status="enabled",
            external_account_ref="+15550101000",
        )

    monkeypatch.setattr(module.whatsapp_web_session_delivery, "send_whatsapp_web_session_text", _fake_send)

    report = module.build_report(
        _args(
            binding_json=str(binding_file),
            heyy_ai_key="empathetic_slow_typing_old_lady",
            heyy_ai_name="Herta (Heyy Lady)",
        )
    )

    assert report["sent"] is True
    assert report["heyy_ai_key"] == "empathetic_slow_typing_old_lady"
    assert report["heyy_ai_name"] == "Herta (Heyy Lady)"
    assert captured["heyy_ai_key"] == "empathetic_slow_typing_old_lady"
    assert captured["heyy_ai_name"] == "Herta (Heyy Lady)"


def test_build_report_requires_recipient_after_readiness_passes(tmp_path: Path) -> None:
    module = _module()
    binding_file = _write_binding(tmp_path)

    report = module.build_report(_args(binding_json=str(binding_file), recipient=""))

    assert report["ready"] is True
    assert report["sent"] is False
    assert report["reason"] == "recipient_required"
