from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "sync_whatsapp_web_session_to_teable.py"


def _module():
    spec = importlib.util.spec_from_file_location("sync_whatsapp_web_session_to_teable", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_update_conversation_page_state_accumulates_cycle_total(tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "state.json"
    args = argparse.Namespace(
        disable_conversation_page_state=False,
        conversation_page_state_file=str(state_file),
        session_ref="principal-wa-web",
        sync_all_conversations=True,
    )

    first = module._update_conversation_page_state(
        args=args,
        payload={
            "conversation_count": 5,
            "conversation_page_complete": False,
            "conversation_pages": 1,
            "conversation_skip": 0,
            "conversation_total": 100,
            "next_conversation_skip": 5,
        },
        message_upsert={"created": 0, "updated": 5, "total": 5},
    )
    second = module._update_conversation_page_state(
        args=args,
        payload={
            "conversation_count": 5,
            "conversation_page_complete": False,
            "conversation_pages": 1,
            "conversation_skip": 5,
            "conversation_total": 100,
            "next_conversation_skip": 10,
        },
        message_upsert={"created": 0, "updated": 7, "total": 7},
    )

    assert first["message_upsert_cycle_total"] == 5
    assert second["message_upsert_cycle_total"] == 12

    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["message_upsert_cycle_total"] == 12


def test_update_conversation_page_state_resets_cycle_total_on_new_cycle(tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "state.json"
    args = argparse.Namespace(
        disable_conversation_page_state=False,
        conversation_page_state_file=str(state_file),
        session_ref="principal-wa-web",
        sync_all_conversations=True,
    )

    state_file.write_text(
        json.dumps(
            {
                "session_ref": "principal-wa-web",
                "conversation_page_complete": True,
                "completed_refresh": False,
                "next_conversation_skip": 0,
                "message_upsert_cycle_total": 19,
            }
        ),
        encoding="utf-8",
    )

    page_state = module._update_conversation_page_state(
        args=args,
        payload={
            "conversation_count": 5,
            "conversation_page_complete": False,
            "conversation_pages": 1,
            "conversation_skip": 0,
            "conversation_total": 100,
            "next_conversation_skip": 5,
        },
        message_upsert={"created": 0, "updated": 3, "total": 3},
    )

    assert page_state["message_upsert_cycle_total"] == 3


def test_session_api_unavailable_from_exit_treats_conversations_failed_as_waiting() -> None:
    module = _module()

    unavailable = module._session_api_unavailable_from_exit(
        SystemExit('http_error:502:{"ok":false,"reason":"conversations_failed"}')
    )

    assert unavailable is not None
    assert unavailable.operation == "session_api_request"
    assert "conversations_failed" in unavailable.detail


def test_main_tolerates_conversation_system_exit_via_waiting_receipt(monkeypatch, tmp_path: Path, capsys) -> None:
    module = _module()
    state_file = tmp_path / "conversation-page-state.json"

    args = argparse.Namespace(
        api_key="teable-key",
        base_url="https://teable.example",
        base_id="base-1",
        route_table_id="route-table",
        route_table_name="Routes",
        persona_table_id="persona-table",
        persona_table_name="Personas",
        message_table_id="message-table",
        message_table_name="Messages",
        audiobook_table_id="audiobook-table",
        audiobook_table_name="Audiobooks",
        session_ref="principal-wa-web",
        create_missing_tables=False,
        skip_personas=True,
        skip_routes=True,
        skip_messages=False,
        skip_audiobook_jobs=True,
        refresh_default_route=False,
        map_inbound_number_digits="",
        map_heyy_ai_key="",
        map_heyy_ai_name="",
        route_seeds_json="",
        route_seeds_file="",
        route_import_sources_json="",
        route_import_sources_file="",
        preserve_sidecar_live_routes=False,
        session_api_base_url="https://wa.example",
        session_api_token="",
        auth_header_name="Authorization",
        auth_header_prefix="Bearer ",
        timeout_seconds=10.0,
        sync_all_conversations=True,
        conversation_skip=None,
        conversation_take=25,
        conversation_max_pages=5,
        conversation_page_state_file=str(state_file),
        disable_conversation_page_state=False,
        tolerate_session_api_unavailable=True,
    )

    monkeypatch.setattr(module, "parse_args", lambda: args)
    monkeypatch.setattr(module, "_ensure_table", lambda **kwargs: (str(kwargs["table_id"]), False))
    monkeypatch.setattr(module, "_ensure_fields", lambda **kwargs: 0)
    monkeypatch.setattr(module, "_cleanup_projectionless_rows", lambda **kwargs: {"deleted": 0, "failed": 0, "total": 0})
    monkeypatch.setattr(
        module,
        "_message_batches_from_sidecar",
        lambda _args: (_ for _ in ()).throw(SystemExit('http_error:502:{"ok":false,"reason":"conversations_failed"}')),
    )

    exit_code = module.main()

    assert exit_code == 0
    receipt = json.loads(capsys.readouterr().out.strip())
    assert receipt["status"] == "waiting"
    assert receipt["reason"] == "session_api_unavailable"
    assert "conversations_failed" in receipt["detail"]
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["status"] == "waiting"
    assert saved["reason"] == "session_api_unavailable"
    assert saved["session_ref"] == "principal-wa-web"
    assert saved["updated_at"] == receipt["updated_at"]
