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
