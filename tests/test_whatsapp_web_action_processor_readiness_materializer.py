from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "materialize_whatsapp_web_action_processor_readiness.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("materialize_whatsapp_web_action_processor_readiness", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(tmp_path: Path, *, env_lines: list[str]) -> Namespace:
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
    env_file.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
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
    return Namespace(
        output=tmp_path / "whatsapp_web_action_processor_readiness.generated.json",
        env_file=str(env_file),
        compose_file=str(compose_file),
        session_api_base_url="http://wa-web.test",
        session_ref="session-1",
        session_api_token="",
        auth_header_name="Authorization",
        auth_header_prefix="Bearer ",
        timeout_seconds=15.0,
        state_file=str(state_file),
        state_stale_seconds=600,
        probe_sidecar=True,
        check_containers=False,
        api_container="ea-api",
        processor_container="ea-whatsapp-web-action-processor",
    )


def test_materialize_whatsapp_web_action_processor_readiness_writes_ready_receipt(tmp_path: Path) -> None:
    module = _load_script()
    args = _args(
        tmp_path,
        env_lines=[
            "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET=secret-value",
            "EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED=1",
            f"EA_WHATSAPP_WEB_ACTION_STATE_FILE={tmp_path / 'processed.json'}",
            "EA_WHATSAPP_WEB_SESSION_API_BASE_URL=http://wa-web.test",
            "EA_WHATSAPP_WEB_DEFAULT_SESSION_REF=session-1",
        ],
    )

    receipt = module.build_whatsapp_web_action_processor_readiness(
        output_path=args.output,
        generated_at="2026-06-22T16:40:00Z",
        args=args,
        request_json=lambda **_: {"ready": True, "status": "ready", "store_message_text": True},
    )

    assert receipt["contract_name"] == "ea.whatsapp_web_action_processor_readiness.v1"
    assert receipt["status"] == "ready"
    assert receipt["head_semantics"] == "source_state"
    assert receipt["source_git_head"]
    assert receipt["ready"] is True
    assert receipt["runtime_ready_claim_allowed"] is True
    assert receipt["live_delivery_claim_allowed"] is False
    assert receipt["next_action"] == "send_epub_over_whatsapp_to_start_or_refresh_live_audiobook_flow"
    assert (
        "Ready runtime means WhatsApp can process both button callbacks and degraded text controls for audiobook voice "
        "selection when the upstream transport preserves those messages."
        in receipt["rules"]
    )
    persisted = json.loads(args.output.read_text(encoding="utf-8"))
    assert persisted["status"] == "ready"
    assert "secret-value" not in json.dumps(receipt, sort_keys=True)


def test_materialize_whatsapp_web_action_processor_readiness_maps_blocked_runtime_to_fix_action(
    tmp_path: Path,
) -> None:
    module = _load_script()
    checker = module._load_check_module()
    checker.HOST_SECRET_FILE_CANDIDATES = ()
    module._load_check_module = lambda: checker
    args = _args(
        tmp_path,
        env_lines=[
            "EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED=1",
            f"EA_WHATSAPP_WEB_ACTION_STATE_FILE={tmp_path / 'processed.json'}",
            "EA_WHATSAPP_WEB_SESSION_API_BASE_URL=http://wa-web.test",
            "EA_WHATSAPP_WEB_DEFAULT_SESSION_REF=session-1",
        ],
    )

    receipt = module.build_whatsapp_web_action_processor_readiness(
        output_path=args.output,
        generated_at="2026-06-22T16:41:00Z",
        args=args,
        request_json=lambda **_: {"ready": True, "status": "ready", "store_message_text": True},
    )

    assert receipt["status"] == "blocked"
    assert receipt["head_semantics"] == "source_state"
    assert receipt["source_git_head"]
    assert receipt["ready"] is False
    assert receipt["reason"] == "callback_secret_missing"
    assert receipt["next_action"] == "seed_whatsapp_callback_secret_and_rerun_readiness"


def test_materialize_whatsapp_web_action_processor_readiness_prioritizes_unavailable_processor_container(
    tmp_path: Path,
) -> None:
    module = _load_script()
    args = _args(
        tmp_path,
        env_lines=[
            "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET=secret-value",
            "EA_WHATSAPP_WEB_ACTION_PROCESSOR_ENABLED=1",
            "EA_WHATSAPP_WEB_ACTION_STATE_FILE=/data/whatsapp-actions/processed.json",
            "EA_WHATSAPP_WEB_SESSION_API_BASE_URL=http://wa-web.test",
            "EA_WHATSAPP_WEB_DEFAULT_SESSION_REF=session-1",
        ],
    )
    args.state_file = "/data/whatsapp-actions/processed.json"
    args.check_containers = True

    def _fake_run(cmd, **kwargs):
        if cmd[:3] == ["docker", "exec", "ea-api"]:
            if cmd[3:] == ["env"]:
                return type("Completed", (), {"returncode": 0, "stdout": "EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET=api-secret\n"})()
            return type("Completed", (), {"returncode": 0, "stdout": ""})()
        if cmd[:3] == ["docker", "exec", "ea-whatsapp-web-action-processor"]:
            return type("Completed", (), {"returncode": 1, "stdout": "", "stderr": "container secret failure"})()
        raise AssertionError(cmd)

    receipt = module.build_whatsapp_web_action_processor_readiness(
        output_path=args.output,
        generated_at="2026-06-22T16:42:00Z",
        args=args,
        request_json=lambda **_: {"ready": True, "status": "ready", "store_message_text": True},
        run=_fake_run,
    )

    assert receipt["status"] == "blocked"
    assert receipt["reason"] == "state_file_container_probe_unavailable"
    assert receipt["next_action"] == "start_or_repair_whatsapp_action_processor_container"
    assert "state_file_missing" not in receipt["reasons"]
    assert "state_file_parent_not_writable" not in receipt["reasons"]
    assert "container secret failure" not in json.dumps(receipt, sort_keys=True)


def test_resolve_whatsapp_web_action_processor_readiness_output_path_falls_back_to_runtime_cache(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_script()
    runtime_output = tmp_path / "provider-ledger" / "provider-health-cache" / "whatsapp_web_action_processor_readiness.generated.json"
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", str(tmp_path / "provider-ledger"))
    monkeypatch.setattr(module, "_path_parent_writable", lambda path: path == runtime_output)

    resolved = module.resolve_whatsapp_web_action_processor_readiness_output_path(module.DEFAULT_OUTPUT)

    assert resolved == runtime_output


def test_default_args_skip_container_checks_when_docker_is_unavailable(monkeypatch, tmp_path: Path) -> None:
    module = _load_script()
    checker = module._load_check_module()
    monkeypatch.setattr(module.shutil, "which", lambda name: None if name == "docker" else "/usr/bin/tool")

    args = module._default_args(checker, output=tmp_path / "receipt.json")

    assert args.check_containers is False


def test_default_args_skip_container_checks_when_docker_daemon_is_unavailable(monkeypatch, tmp_path: Path) -> None:
    module = _load_script()
    checker = module._load_check_module()
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)
    monkeypatch.setattr(module.subprocess, "run", lambda **_kwargs: None)

    args = module._default_args(checker, output=tmp_path / "receipt.json")

    assert args.check_containers is False


def test_default_args_enable_container_checks_when_docker_is_available(monkeypatch, tmp_path: Path) -> None:
    module = _load_script()
    checker = module._load_check_module()
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: type("Completed", (), {"returncode": 0})())

    args = module._default_args(checker, output=tmp_path / "receipt.json")

    assert args.check_containers is True
