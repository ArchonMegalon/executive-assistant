from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "check_whatsapp_web_teable_sync_readiness.py"


def _module():
    spec = importlib.util.spec_from_file_location("check_whatsapp_web_teable_sync_readiness", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_teable_sync_readiness_passes_for_fresh_cursor(tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "state.json"
    now = datetime(2026, 6, 21, 6, 30, tzinfo=timezone.utc)
    state_file.write_text(
        json.dumps(
            {
                "conversation_count": 1,
                "conversation_page_complete": False,
                "conversation_scan_completed": True,
                "conversation_scan_completed_at": (now - timedelta(minutes=3)).isoformat().replace("+00:00", "Z"),
                "conversation_scan_completed_count": 1,
                "conversation_scan_completed_total": 159,
                "conversation_skip": 4,
                "conversation_total": 159,
                "message_upsert_cycle_total": 12,
                "message_upsert": {"created": 0, "total": 5, "updated": 5},
                "next_conversation_skip": 5,
                "session_ref": "principal-wa-web",
                "updated_at": (now - timedelta(seconds=30)).isoformat().replace("+00:00", "Z"),
            }
        ),
        encoding="utf-8",
    )

    report = module.check_readiness(
        enabled=True,
        state_file=state_file,
        session_ref="principal-wa-web",
        stale_seconds=600,
        now=now,
    )

    assert report["ready"] is True
    assert report["reason"] == "ready"
    assert report["next_conversation_skip"] == 5
    assert report["message_upsert_total"] == 5
    assert report["message_upsert_cycle_total"] == 12
    assert report["conversation_scan_completed"] is True
    assert report["conversation_scan_completed_count"] == 1
    assert report["conversation_scan_completed_total"] == 159


def test_teable_sync_readiness_fails_for_stale_cursor(tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "state.json"
    now = datetime(2026, 6, 21, 6, 30, tzinfo=timezone.utc)
    state_file.write_text(
        json.dumps(
            {
                "conversation_count": 1,
                "conversation_total": 159,
                "next_conversation_skip": 5,
                "session_ref": "principal-wa-web",
                "updated_at": (now - timedelta(seconds=601)).isoformat().replace("+00:00", "Z"),
            }
        ),
        encoding="utf-8",
    )

    report = module.check_readiness(
        enabled=True,
        state_file=state_file,
        session_ref="principal-wa-web",
        stale_seconds=600,
        now=now,
    )

    assert report["ready"] is False
    assert report["reason"] == "state_stale"


def test_teable_sync_readiness_disabled_is_ready(tmp_path: Path) -> None:
    module = _module()

    report = module.check_readiness(
        enabled=False,
        state_file=tmp_path / "missing.json",
        session_ref="principal-wa-web",
        stale_seconds=600,
    )

    assert report["ready"] is True
    assert report["reason"] == "disabled"
