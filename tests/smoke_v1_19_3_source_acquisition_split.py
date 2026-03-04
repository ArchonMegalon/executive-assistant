from __future__ import annotations

import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_source_acquisition_module_presence() -> None:
    src = (ROOT / "ea/app/intelligence/source_acquisition.py").read_text(encoding="utf-8")
    brief_src = (ROOT / "ea/app/briefings.py").read_text(encoding="utf-8")
    assert "class SourceAcquisitionResult" in src
    assert "def collect_briefing_sources(" in src
    assert "from app.intelligence.source_acquisition import collect_briefing_sources" in brief_src
    _pass("v1.19.3 source acquisition module presence")


def test_source_acquisition_behavior_contract() -> None:
    import importlib
    import types

    original_calendar_store = sys.modules.get("app.calendar_store")
    sys.modules["app.calendar_store"] = types.SimpleNamespace(list_events_range=lambda tenant, s, e: [])
    acq = importlib.import_module("app.intelligence.source_acquisition")

    async def _fake_safe_gog(container: str, cmd: list[str], account: str, timeout: float = 20.0) -> str:
        if cmd[:2] == ["auth", "list"]:
            return "tibor@example.com"
        if cmd[:3] == ["gmail", "messages", "search"]:
            return '[{"subject":"Invoice due","snippet":"Final notice","sender":"Billing"}]'
        if cmd[:2] == ["calendar", "events"]:
            return '[{"summary":"Board Meeting","start":{"dateTime":"2026-03-05T10:00:00+01:00"},"end":{"dateTime":"2026-03-05T11:00:00+01:00"}}]'
        return "[]"

    original_safe_gog = acq._safe_gog
    original_list_events = acq.list_events_range
    try:
        acq._safe_gog = _fake_safe_gog
        acq.list_events_range = lambda tenant, s, e: []
        res = asyncio.run(
            acq.collect_briefing_sources(
                openclaw_container="openclaw",
                primary_account="tibor@example.com",
                tenant_key="chat_1",
                status_cb=None,
            )
        )
        assert res.accounts
        assert any("invoice due" in str(m.get("subject", "")).lower() for m in res.mails)
        assert any("board meeting" in str(c.get("summary", "")).lower() for c in res.calendar_events)
    finally:
        acq._safe_gog = original_safe_gog
        acq.list_events_range = original_list_events
        if original_calendar_store is None:
            sys.modules.pop("app.calendar_store", None)
        else:
            sys.modules["app.calendar_store"] = original_calendar_store
    _pass("v1.19.3 source acquisition behavior contract")


if __name__ == "__main__":
    test_source_acquisition_module_presence()
    test_source_acquisition_behavior_contract()
