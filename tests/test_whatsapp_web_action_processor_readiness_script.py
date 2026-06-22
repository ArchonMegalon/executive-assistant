from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "check_whatsapp_web_action_processor_readiness.py"


def _module():
    spec = importlib.util.spec_from_file_location("check_whatsapp_web_action_processor_readiness", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(tmp_path: Path, **overrides: object) -> Namespace:
    compose_file = tmp_path / "docker-compose.whatsapp-web-session.yml"
    compose_file.write_text(
        """
services:
  ea-whatsapp-web-action-processor:
    volumes:
      - ea_whatsapp_web_actions:/data/whatsapp-actions
    command: python /app/scripts/process_whatsapp_web_session_actions.py
volumes:
  ea_whatsapp_web_actions:
    name: ea_whatsapp_web_actions
""",
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    state_file = tmp_path / "processed.json"
    state_file.write_text(
        json.dumps(
            {
                "actions": {},
                "session_ref": "session-1",
                "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        ),
        encoding="utf-8",
    )
    env_file.write_text(
        "\n".join(
            [
                "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET=secret-value",
                "EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED=1",
                f"EA_WHATSAPP_WEB_ACTION_STATE_FILE={state_file}",
                "EA_WHATSAPP_WEB_SESSION_API_BASE_URL=http://wa-web.test",
                "EA_WHATSAPP_WEB_DEFAULT_SESSION_REF=session-1",
            ]
        ),
        encoding="utf-8",
    )
    values: dict[str, object] = {
        "api_container": "ea-api",
        "auth_header_name": "Authorization",
        "auth_header_prefix": "Bearer ",
        "check_containers": False,
        "compose_file": str(compose_file),
        "env_file": str(env_file),
        "probe_sidecar": True,
        "processor_container": "ea-whatsapp-web-action-processor",
        "session_api_base_url": "http://wa-web.test",
        "session_api_token": "",
        "session_ref": "session-1",
        "state_file": str(state_file),
        "state_stale_seconds": 600,
        "timeout_seconds": 15.0,
    }
    values.update(overrides)
    return Namespace(**values)


def test_build_report_ready_when_secret_processor_and_sidecar_are_ready(tmp_path: Path) -> None:
    module = _module()

    report = module.build_report(
        _args(tmp_path),
        request_json=lambda **_: {"ready": True, "status": "ready", "store_message_text": True},
    )

    assert report["ready"] is True
    assert report["reason"] == "ready"
    assert report["callback_secret_present"] is True
    assert report["action_processor_enabled"] is True
    assert report["processor_service_declared"] is True
    assert report["state_file_present"] is True
    assert report["state_file_parent_writable"] is True
    assert report["state_fresh"] is True
    assert report["sidecar_store_message_text"] is True
    assert "secret-value" not in str(report)


def test_build_report_reports_disabled_processor_as_ready_idle(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "HOST_SECRET_FILE_CANDIDATES", ())
    env_file = tmp_path / "disabled.env"
    env_file.write_text("EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED=0\n", encoding="utf-8")

    report = module.build_report(
        _args(tmp_path, env_file=str(env_file)),
        request_json=lambda **_: {"ready": False, "status": "qr_required", "store_message_text": False},
    )

    assert report["ready"] is True
    assert report["reason"] == "disabled"
    assert report["action_processor_enabled"] is False
    assert report["reasons"] == []


def test_build_report_treats_missing_processor_enabled_env_as_enabled_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _module()
    monkeypatch.setattr(module, "HOST_SECRET_FILE_CANDIDATES", ())
    env_file = tmp_path / "missing-enable.env"
    missing_state_file = tmp_path / "missing-state.json"
    env_file.write_text(f"EA_WHATSAPP_WEB_ACTION_STATE_FILE={missing_state_file}\n", encoding="utf-8")

    report = module.build_report(
        _args(tmp_path, env_file=str(env_file), state_file=str(missing_state_file)),
        request_json=lambda **_: {"ready": False, "status": "qr_required", "store_message_text": False},
    )

    assert report["ready"] is False
    assert report["action_processor_enabled"] is True
    assert report["reason"] == "callback_secret_missing"
    assert "callback_secret_missing" in report["reasons"]
    assert "state_file_missing" in report["reasons"]
    assert "sidecar_not_ready" in report["reasons"]


def test_build_report_reports_missing_live_prerequisites(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "HOST_SECRET_FILE_CANDIDATES", ())
    env_file = tmp_path / "missing-secret.env"
    missing_state_file = tmp_path / "missing-state.json"
    env_file.write_text(
        "\n".join(
            [
                "EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED=1",
                f"EA_WHATSAPP_WEB_ACTION_STATE_FILE={missing_state_file}",
            ]
        ),
        encoding="utf-8",
    )

    report = module.build_report(
        _args(tmp_path, env_file=str(env_file), state_file=str(missing_state_file)),
        request_json=lambda **_: {"ready": False, "status": "qr_required", "store_message_text": False},
    )

    assert report["ready"] is False
    assert report["reason"] == "callback_secret_missing"
    assert "callback_secret_missing" in report["reasons"]
    assert "state_file_missing" in report["reasons"]
    assert "sidecar_not_ready" in report["reasons"]
    assert "sidecar_message_text_storage_disabled" in report["reasons"]


def test_build_report_reports_stale_or_unreadable_state(tmp_path: Path) -> None:
    module = _module()
    stale_state_file = tmp_path / "stale-state.json"
    stale_state_file.write_text(
        json.dumps({"actions": {}, "session_ref": "session-1", "updated_at": "2020-01-01T00:00:00Z"}),
        encoding="utf-8",
    )

    stale_report = module.build_report(
        _args(tmp_path, state_file=str(stale_state_file), state_stale_seconds=1),
        request_json=lambda **_: {"ready": True, "status": "ready", "store_message_text": True},
    )

    assert stale_report["ready"] is False
    assert "state_file_stale" in stale_report["reasons"]

    bad_state_file = tmp_path / "bad-state.json"
    bad_state_file.write_text("{bad json", encoding="utf-8")
    bad_report = module.build_report(
        _args(tmp_path, state_file=str(bad_state_file)),
        request_json=lambda **_: {"ready": True, "status": "ready", "store_message_text": True},
    )

    assert bad_report["ready"] is False
    assert "state_file_unreadable" in bad_report["reasons"]


def test_build_report_checks_runtime_containers_without_leaking_secret_values(tmp_path: Path) -> None:
    module = _module()

    def _fake_run(cmd, **kwargs):
        container = cmd[2]
        if container == "ea-api":
            return SimpleNamespace(returncode=0, stdout="EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET=api-secret\n")
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED=1\n"
                "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET=processor-secret\n"
            ),
        )

    report = module.build_report(
        _args(tmp_path, check_containers=True),
        request_json=lambda **_: {"ready": True, "status": "ready", "store_message_text": True},
        run=_fake_run,
    )

    assert report["ready"] is True
    assert report["api_callback_secret_present"] is True
    assert report["processor_callback_secret_present"] is True
    assert report["processor_container_enabled"] is True
    assert "api-secret" not in str(report)
    assert "processor-secret" not in str(report)


def test_build_report_derives_effective_session_ref_from_live_sidecar_when_default_ref_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _module()
    monkeypatch.setattr(module, "HOST_SECRET_FILE_CANDIDATES", ())
    env_file = tmp_path / "implicit-default.env"
    state_file = tmp_path / "processed-live.json"
    state_file.write_text(
        json.dumps(
            {
                "actions": {},
                "session_ref": "tibor-wa-web",
                "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        ),
        encoding="utf-8",
    )
    env_file.write_text(
        "\n".join(
            [
                "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET=secret-value",
                "EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED=1",
                f"EA_WHATSAPP_WEB_ACTION_STATE_FILE={state_file}",
                "EA_WHATSAPP_WEB_SESSION_API_BASE_URL=http://wa-web.test",
            ]
        ),
        encoding="utf-8",
    )

    def _request_json(**kwargs):
        url = str(kwargs.get("url") or "")
        if url.endswith("/healthz"):
            return {"ok": True, "status": "ready", "session_ref": "tibor-wa-web"}
        if url.endswith("/sessions/tibor-wa-web/status"):
            return {"ok": True, "ready": True, "status": "ready", "store_message_text": True}
        raise AssertionError(url)

    report = module.build_report(
        _args(
            tmp_path,
            env_file=str(env_file),
            state_file=str(state_file),
            session_ref=module.DEFAULT_SESSION_REF,
            session_api_base_url="http://wa-web.test",
        ),
        request_json=_request_json,
    )

    assert report["ready"] is True
    assert report["reason"] == "ready"
    assert report["configured_session_ref"] == "default-wa-web"
    assert report["effective_session_ref"] == "tibor-wa-web"
    assert report["effective_session_ref_source"] == "state_file"
    assert report["sidecar_health_session_ref"] == "tibor-wa-web"
    assert "state_session_ref_mismatch" not in report["reasons"]


def test_build_report_accepts_processor_state_file_inside_container(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "HOST_SECRET_FILE_CANDIDATES", ())
    env_file = tmp_path / "container-state.env"
    env_file.write_text(
        "\n".join(
            [
                "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET=secret-value",
                "EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED=1",
                "EA_WHATSAPP_WEB_ACTION_STATE_FILE=/data/whatsapp-actions/processed.json",
                "EA_WHATSAPP_WEB_SESSION_API_BASE_URL=http://wa-web.test",
                "EA_WHATSAPP_WEB_DEFAULT_SESSION_REF=session-1",
            ]
        ),
        encoding="utf-8",
    )

    container_state = {
        "state_file": "/data/whatsapp-actions/processed.json",
        "state_file_checked_in_container": True,
        "state_file_container": "ea-whatsapp-web-action-processor",
        "state_file_json_readable": True,
        "state_file_object": True,
        "state_file_parent_writable": True,
        "state_file_present": True,
        "state_stale_seconds": 600,
        "state_session_ref": "session-1",
        "state_updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "state_updated_at_valid": True,
        "state_age_seconds": 0,
        "state_fresh": True,
    }

    def _fake_run(cmd, **kwargs):
        if cmd[:3] == ["docker", "exec", "ea-whatsapp-web-action-processor"] and cmd[3:5] == ["python", "-c"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps(container_state))
        if cmd[:3] == ["docker", "exec", "ea-api"]:
            if cmd[3:] == ["env"]:
                return SimpleNamespace(returncode=0, stdout="EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET=api-secret\n")
            return SimpleNamespace(returncode=0, stdout="")
        if cmd[:3] == ["docker", "exec", "ea-whatsapp-web-action-processor"]:
            if cmd[3:] == ["env"]:
                return SimpleNamespace(
                    returncode=0,
                    stdout=(
                        "EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED=1\n"
                        "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET=processor-secret\n"
                    ),
                )
            return SimpleNamespace(returncode=0, stdout="")
        return SimpleNamespace(returncode=1, stdout="")

    report = module.build_report(
        _args(
            tmp_path,
            check_containers=True,
            env_file=str(env_file),
            state_file="/data/whatsapp-actions/processed.json",
        ),
        request_json=lambda **_: {"ready": True, "status": "ready", "store_message_text": True},
        run=_fake_run,
    )

    assert report["ready"] is True
    assert report["reason"] == "ready"
    assert report["state_file_checked_in_container"] is True
    assert report["state_file_container"] == "ea-whatsapp-web-action-processor"
    assert report["state_file_present"] is True
    assert report["state_fresh"] is True
    assert "secret-value" not in str(report)
    assert "api-secret" not in str(report)
    assert "processor-secret" not in str(report)


def test_build_report_accepts_host_and_container_secret_files(tmp_path: Path) -> None:
    module = _module()
    env_file = tmp_path / "file-secret.env"
    secret_file = tmp_path / "whatsapp_audiobook_callback_secret"
    secret_file.write_text("file-secret\n", encoding="utf-8")
    env_file.write_text(
        "\n".join(
            [
                f"EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET_FILE={secret_file}",
                "EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED=1",
            ]
        ),
        encoding="utf-8",
    )

    def _fake_run(cmd, **kwargs):
        if cmd[:3] == ["docker", "exec", "ea-api"]:
            if cmd[3:] == ["env"]:
                return SimpleNamespace(returncode=0, stdout="")
            return SimpleNamespace(returncode=0, stdout="")
        if cmd[:3] == ["docker", "exec", "ea-whatsapp-web-action-processor"]:
            if cmd[3:] == ["env"]:
                return SimpleNamespace(returncode=0, stdout="EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED=1\n")
            return SimpleNamespace(returncode=0, stdout="")
        return SimpleNamespace(returncode=1, stdout="")

    report = module.build_report(
        _args(tmp_path, check_containers=True, env_file=str(env_file)),
        request_json=lambda **_: {"ready": True, "status": "ready", "store_message_text": True},
        run=_fake_run,
    )

    assert report["ready"] is True
    assert report["callback_secret_present"] is True
    assert report["api_callback_secret_present"] is True
    assert report["processor_callback_secret_present"] is True
    assert "file-secret" not in str(report)
