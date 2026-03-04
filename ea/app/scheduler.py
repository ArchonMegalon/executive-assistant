import asyncio
import contextlib
import httpx
import os
import traceback
from datetime import datetime, timedelta, timezone, time as dtime
from typing import Awaitable
from zoneinfo import ZoneInfo

from app.poll_listener import tg, handle_callback, handle_photo, handle_command
from app.settings import settings

_LAST_AVOMAP_PREWARM_DAY: str = ""


def _collect_prewarm_tenants() -> list[str]:
    keys: set[str] = set()
    try:
        from app.tenants import load_tenants
        all_tenants = load_tenants(settings.tenants_yaml)
        for t in all_tenants.values():
            keys.add(str(t.name))
            for cid in list(getattr(t, "allow_chat_ids", []) or []):
                keys.add(f"chat_{int(cid)}")
    except Exception:
        pass
    return sorted(k for k in keys if str(k).strip())


def _run_avomap_prewarm_sync() -> int:
    if not settings.avomap_enabled:
        return 0
    from app.db import get_db
    from app.calendar_store import list_events_range
    from app.integrations.avomap.service import AvoMapService, build_day_context

    db = get_db()
    svc = AvoMapService(db, enabled=True)
    local_tz = ZoneInfo(settings.tz)
    now_local = datetime.now(local_tz)
    target_day_local = (now_local + timedelta(days=1)).date()
    target_day = target_day_local.isoformat()
    window_start_local = datetime.combine(target_day_local, dtime.min, tzinfo=local_tz)
    window_end_local = window_start_local + timedelta(days=1)
    # Calendar rows are stored/queried in UTC; convert the local "tomorrow" window.
    window_start = window_start_local.astimezone(timezone.utc)
    window_end = window_end_local.astimezone(timezone.utc)

    warmed = 0
    for tenant_key in _collect_prewarm_tenants():
        try:
            rows = list_events_range(tenant_key, window_start, window_end) or []
            calendar_events = [
                {
                    "title": str(r.get("title") or ""),
                    "summary": str(r.get("title") or ""),
                    "location": str(r.get("location") or ""),
                }
                for r in rows
                if isinstance(r, dict)
            ]
            day_ctx = build_day_context(calendar_events=calendar_events, travel_emails=[])
            decision = svc.plan_for_briefing(
                tenant=tenant_key,
                person_id=tenant_key,
                day_context=day_ctx,
                date_key=target_day,
            )
            if str((decision or {}).get("status") or "") in {"dispatched", "existing_spec", "cache_hit"}:
                warmed += 1
        except Exception:
            continue
    return warmed


async def _maybe_avomap_prewarm() -> None:
    global _LAST_AVOMAP_PREWARM_DAY
    if not settings.avomap_enabled:
        return
    prewarm_hour = int(os.environ.get("EA_AVOMAP_PREWARM_HOUR", "20"))
    now_local = datetime.now(ZoneInfo(settings.tz))
    today_key = now_local.date().isoformat()
    if now_local.hour != prewarm_hour:
        return
    if _LAST_AVOMAP_PREWARM_DAY == today_key:
        return
    await asyncio.to_thread(_run_avomap_prewarm_sync)
    _LAST_AVOMAP_PREWARM_DAY = today_key

async def scheduler_loop():
    """Background loop for scheduled tasks."""
    while True:
        try:
            await _maybe_avomap_prewarm()
        except Exception:
            pass
        await asyncio.sleep(60)


async def _run_with_typing(chat_id: int | None, crash_label: str, handler: Awaitable[None]) -> None:
    keep_typing = True

    async def _typer() -> None:
        if not chat_id:
            return
        token = os.environ.get("EA_TELEGRAM_BOT_TOKEN")
        if not token:
            return
        async with httpx.AsyncClient() as hc:
            while keep_typing:
                try:
                    await hc.post(
                        f"https://api.telegram.org/bot{token}/sendChatAction",
                        json={"chat_id": chat_id, "action": "typing"},
                    )
                except Exception:
                    pass
                await asyncio.sleep(4)

    typing_task = asyncio.create_task(_typer())
    try:
        await handler
    except Exception as e:
        print(f"\n🔥 CRASH IN {crash_label}: {e}\n", flush=True)
        traceback.print_exc()
    finally:
        keep_typing = False
        typing_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await typing_task


async def send_briefing_and_poll():
    """Main Telegram poller loop with crash recovery and typing UX."""
    offset = 0
    while True:
        try:
            updates = await tg.get_updates(offset)
            for u in updates:
                offset = u["update_id"] + 1

                if "callback_query" in u:
                    callback = u["callback_query"]
                    callback_chat = callback.get("message", {}).get("chat", {}).get("id")
                    asyncio.create_task(
                        _run_with_typing(callback_chat, "CALLBACK", handle_callback(callback))
                    )
                elif "message" in u:
                    msg = u["message"]
                    chat_id = msg["chat"]["id"]
                    if msg.get("photo"):
                        asyncio.create_task(handle_photo(chat_id, msg))
                    elif msg.get("text") and msg["text"].startswith("/"):
                        asyncio.create_task(
                            _run_with_typing(chat_id, "COMMAND", handle_command(chat_id, msg["text"]))
                        )

        except Exception as e:
            print(f"Poller Warning: {e}", flush=True)
            await asyncio.sleep(5)
