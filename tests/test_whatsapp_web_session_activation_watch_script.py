from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "watch_whatsapp_web_session_activation.py"


def _module():
    spec = importlib.util.spec_from_file_location("watch_whatsapp_web_session_activation", SCRIPT_PATH)
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
        "interval_seconds": 1,
        "max_seconds": 30,
        "once": False,
        "phone_number": "+15550101000",
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
    }
    values.update(overrides)
    return Namespace(**values)


def test_parse_args_uses_repo_wide_principal_before_literal_default(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    (tmp_path / ".env").write_text("EA_DEFAULT_PRINCIPAL_ID=repo-wide-principal\n", encoding="utf-8")
    for name in (
        "EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID",
        "EA_WHATSAPP_DEFAULT_PRINCIPAL_ID",
        "EA_DEFAULT_PRINCIPAL_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(module.activation.readiness_script, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["watch_whatsapp_web_session_activation.py", "--once"])

    args = module.parse_args()

    assert args.principal_id == "repo-wide-principal"


def test_parse_args_prefers_shell_principal_over_repo_env(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    (tmp_path / ".env").write_text("EA_DEFAULT_PRINCIPAL_ID=repo-wide-principal\n", encoding="utf-8")
    for name in (
        "EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID",
        "EA_WHATSAPP_DEFAULT_PRINCIPAL_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", "shell-wide-principal")
    monkeypatch.setattr(module.activation.readiness_script, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["watch_whatsapp_web_session_activation.py", "--once"])

    args = module.parse_args()

    assert args.principal_id == "shell-wide-principal"


def test_build_report_stops_after_activation_success(monkeypatch) -> None:
    module = _module()
    reports = [
        {
            "activated": False,
            "binding_id": "principal-whatsapp-web-session",
            "principal_id": "principal-default",
            "qr": "secret-qr-payload",
            "reason": "sidecar_not_ready",
            "session_api_token": "secret-token",
            "session_ref": "principal-wa-web",
            "sidecar_qr_required": True,
        },
        {
            "activated": True,
            "binding_id": "principal-whatsapp-web-session",
            "principal_id": "principal-default",
            "reason": "activated",
            "session_ref": "principal-wa-web",
            "sidecar_ready": True,
        },
    ]
    sleeps: list[float] = []
    events: list[dict[str, object]] = []
    now = {"value": 0.0}

    def _fake_activation(args):
        return reports.pop(0)

    def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now["value"] += seconds

    monkeypatch.setattr(module.activation, "build_report", _fake_activation)

    report = module.build_report(
        _args(),
        emit=events.append,
        sleep=_fake_sleep,
        clock=lambda: now["value"],
    )

    serialized = json.dumps({"events": events, "report": report})
    assert report["activated"] is True
    assert report["attempts"] == 2
    assert sleeps == [1]
    assert events[0]["qr"] == "[redacted]"
    assert events[0]["session_api_token"] == "[redacted]"
    assert "secret-qr-payload" not in serialized
    assert "secret-token" not in serialized


def test_build_report_retries_until_requested_live_send_succeeds(monkeypatch) -> None:
    module = _module()
    reports = [
        {
            "activated": True,
            "binding_id": "principal-whatsapp-web-session",
            "live_send": {"sent": False, "reason": "recipient_required"},
            "principal_id": "principal-default",
            "reason": "activated",
            "session_ref": "principal-wa-web",
        },
        {
            "activated": True,
            "binding_id": "principal-whatsapp-web-session",
            "live_send": {"sent": True, "reason": "sent", "message_id_count": 1},
            "principal_id": "principal-default",
            "reason": "activated",
            "session_ref": "principal-wa-web",
        },
    ]
    sleeps: list[float] = []
    events: list[dict[str, object]] = []
    now = {"value": 0.0}

    monkeypatch.setattr(module.activation, "build_report", lambda args: reports.pop(0))

    def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now["value"] += seconds

    report = module.build_report(
        _args(send_test=True),
        emit=events.append,
        sleep=_fake_sleep,
        clock=lambda: now["value"],
    )

    assert report["activated"] is True
    assert report["attempts"] == 2
    assert sleeps == [1]
    assert events[0]["activated"] is False
    assert events[0]["binding_activated"] is True
    assert events[0]["reason"] == "live_send_pending"
    assert events[0]["live_send_reason"] == "recipient_required"
    assert events[1]["live_send"]["sent"] is True


def test_build_report_once_returns_not_ready_without_raw_qr(monkeypatch) -> None:
    module = _module()
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        module.activation,
        "build_report",
        lambda args: {
            "activated": False,
            "binding_id": "principal-whatsapp-web-session",
            "principal_id": "principal-default",
            "qr": "secret-qr-payload",
            "reason": "sidecar_not_ready",
            "session_ref": "principal-wa-web",
            "sidecar_qr_required": True,
        },
    )

    report = module.build_report(_args(once=True), emit=events.append, sleep=lambda seconds: None)

    serialized = json.dumps({"events": events, "report": report})
    assert report["activated"] is False
    assert report["attempts"] == 1
    assert report["reason"] == "sidecar_not_ready"
    assert report["last_activation"]["sidecar_qr_required"] is True
    assert "secret-qr-payload" not in serialized


def test_build_report_converts_activation_exception_to_retryable_event(monkeypatch) -> None:
    module = _module()

    def _raise_activation(args):
        raise RuntimeError("database password leaked in exception")

    monkeypatch.setattr(module.activation, "build_report", _raise_activation)

    report = module.build_report(_args(once=True, database_url="postgresql://user:secret@example/ea"))

    serialized = json.dumps(report)
    assert report["activated"] is False
    assert report["reason"] == "activation_exception"
    assert report["last_activation"]["error_type"] == "RuntimeError"
    assert "secret" not in serialized
    assert "database password leaked" not in serialized


def test_main_prints_attempt_and_completion_json(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(module, "parse_args", lambda: _args(once=True))
    monkeypatch.setattr(
        module.activation,
        "build_report",
        lambda args: {
            "activated": False,
            "binding_id": "principal-whatsapp-web-session",
            "principal_id": "principal-default",
            "reason": "sidecar_not_ready",
            "session_ref": "principal-wa-web",
        },
    )

    exit_code = module.main()
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert exit_code == 2
    assert lines[0]["event"] == "whatsapp_web_session_activation_attempt"
    assert lines[1]["event"] == "whatsapp_web_session_activation_watch_complete"
    assert lines[1]["reason"] == "sidecar_not_ready"
