from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "check_whatsapp_web_route_persistence.py"


def _module():
    spec = importlib.util.spec_from_file_location("check_whatsapp_web_route_persistence", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_state(path: Path, *, now: datetime, routes: dict[str, object]) -> None:
    path.write_text(
        json.dumps(
            {
                "persisted_at": now.isoformat().replace("+00:00", "Z"),
                "route_count": len(routes),
                "routes": routes,
                "session_ref": "principal-wa-web",
            }
        ),
        encoding="utf-8",
    )


def test_route_persistence_ready_with_default_and_private_route(tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "routes.json"
    now = datetime(2026, 6, 21, 6, 30, tzinfo=timezone.utc)
    _write_state(state_file, now=now - timedelta(seconds=30), routes={"*": {"ai_key": "herta"}, "436812345678": {"ai_key": "executive_assistant"}})

    report = module.check_route_persistence(
        state_file=state_file,
        session_ref="principal-wa-web",
        min_route_count=2,
        min_private_route_count=1,
        require_default_route=True,
        stale_seconds=600,
        now=now,
    )

    assert report["ready"] is True
    assert report["route_count"] == 2
    assert report["private_route_count"] == 1
    assert report["default_route_present"] is True


def test_route_persistence_fails_without_default_route(tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "routes.json"
    now = datetime(2026, 6, 21, 6, 30, tzinfo=timezone.utc)
    _write_state(state_file, now=now, routes={"436812345678": {"ai_key": "executive_assistant"}})

    report = module.check_route_persistence(
        state_file=state_file,
        session_ref="principal-wa-web",
        min_route_count=1,
        min_private_route_count=1,
        require_default_route=True,
        stale_seconds=600,
        now=now,
    )

    assert report["ready"] is False
    assert report["reason"] == "default_route_missing"


def test_route_persistence_fails_when_private_route_missing(tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "routes.json"
    now = datetime(2026, 6, 21, 6, 30, tzinfo=timezone.utc)
    _write_state(state_file, now=now, routes={"*": {"ai_key": "herta"}})

    report = module.check_route_persistence(
        state_file=state_file,
        session_ref="principal-wa-web",
        min_route_count=1,
        min_private_route_count=1,
        require_default_route=True,
        stale_seconds=600,
        now=now,
    )

    assert report["ready"] is False
    assert report["reason"] == "private_route_count_too_low"


def test_route_persistence_fails_when_stale(tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "routes.json"
    now = datetime(2026, 6, 21, 6, 30, tzinfo=timezone.utc)
    _write_state(state_file, now=now - timedelta(seconds=601), routes={"*": {"ai_key": "herta"}, "436812345678": {"ai_key": "executive_assistant"}})

    report = module.check_route_persistence(
        state_file=state_file,
        session_ref="principal-wa-web",
        min_route_count=2,
        min_private_route_count=1,
        require_default_route=True,
        stale_seconds=600,
        now=now,
    )

    assert report["ready"] is False
    assert report["reason"] == "route_state_stale"


def test_route_persistence_requires_exact_herta_private_route(tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "routes.json"
    now = datetime(2026, 6, 21, 6, 30, tzinfo=timezone.utc)
    _write_state(
        state_file,
        now=now,
        routes={
            "*": {"ai_key": "empathetic_slow_typing_old_lady", "typing_delay_ms_per_character": 4000},
            "40424366432273": {
                "ai_key": "empathetic_slow_typing_old_lady",
                "pre_reply_delay_max_seconds": 30,
                "pre_reply_delay_min_seconds": 10,
                "quiet_hours_end_hour": 0,
                "quiet_hours_start_hour": 0,
                "typing_delay_ms_per_character": 0,
            },
        },
    )

    report = module.check_route_persistence(
        state_file=state_file,
        session_ref="principal-wa-web",
        min_route_count=2,
        min_private_route_count=1,
        require_default_route=True,
        required_routes=[
            {
                "route_key": "40424366432273",
                "ai_key": "empathetic_slow_typing_old_lady",
                "pre_reply_delay_max_seconds": 30,
                "pre_reply_delay_min_seconds": 10,
                "quiet_hours_end_hour": 0,
                "quiet_hours_start_hour": 0,
                "typing_delay_ms_per_character": 0,
            }
        ],
        stale_seconds=600,
        now=now,
    )

    assert report["ready"] is True
    assert report["required_route_count"] == 1


def test_route_persistence_reports_required_route_mismatch(tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "routes.json"
    now = datetime(2026, 6, 21, 6, 30, tzinfo=timezone.utc)
    _write_state(
        state_file,
        now=now,
        routes={
            "*": {"ai_key": "empathetic_slow_typing_old_lady"},
            "40424366432273": {
                "ai_key": "executive_assistant",
                "typing_delay_ms_per_character": 4000,
            },
        },
    )

    report = module.check_route_persistence(
        state_file=state_file,
        session_ref="principal-wa-web",
        min_route_count=2,
        min_private_route_count=1,
        require_default_route=True,
        required_routes=[
            {
                "route_key": "40424366432273",
                "ai_key": "empathetic_slow_typing_old_lady",
                "typing_delay_ms_per_character": 0,
            }
        ],
        stale_seconds=600,
        now=now,
    )

    assert report["ready"] is False
    assert report["reason"] == "required_route_mismatch"
    assert report["required_route_key"] == "40424366432273"
    assert report["mismatches"]["ai_key"]["actual"] == "executive_assistant"
    assert report["mismatches"]["typing_delay_ms_per_character"]["actual"] == 4000


def test_route_persistence_falls_back_to_container_state_file(tmp_path: Path) -> None:
    module = _module()
    now = datetime(2026, 6, 21, 6, 30, tzinfo=timezone.utc)
    missing_state_file = Path("/data/session/principal-wa-web.heyy-ai-routes.json")
    payload = {
        "persisted_at": (now - timedelta(seconds=30)).isoformat().replace("+00:00", "Z"),
        "route_count": 2,
        "routes": {
            "*": {"ai_key": "herta"},
            "436812345678": {"ai_key": "executive_assistant"},
        },
        "session_ref": "principal-wa-web",
    }

    def _fake_run(cmd, **kwargs):
        assert cmd[:4] == ["docker", "exec", "ea-whatsapp-web-session", "sh"]
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    report = module.resolve_route_persistence(
        state_file=missing_state_file,
        session_ref="principal-wa-web",
        min_route_count=2,
        min_private_route_count=1,
        require_default_route=True,
        stale_seconds=600,
        container_name="ea-whatsapp-web-session",
        run=_fake_run,
        now=now,
    )

    assert report["ready"] is True
    assert report["state_file_checked_in_container"] is True
    assert report["state_file_container"] == "ea-whatsapp-web-session"
    assert report["state_file"] == str(missing_state_file)
