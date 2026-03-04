from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import urllib.request
from collections.abc import Callable


LAST_HEARTBEAT = time.monotonic()
WATCHDOG_BOOT_TS = time.monotonic()


def mark_heartbeat() -> None:
    global LAST_HEARTBEAT
    LAST_HEARTBEAT = time.monotonic()


def sentinel_enabled_for_role() -> bool:
    role = (os.getenv("EA_ROLE") or "monolith").strip().lower()
    override = os.getenv("EA_SENTINEL_ENABLED")
    if override is not None:
        return str(override).strip().lower() in ("1", "true", "yes", "on")
    # Default watchdog only where heartbeat_pinger is expected to run.
    return role in ("", "monolith", "poller")


def sentinel_heartbeat_timeout_sec() -> int:
    try:
        value = int(os.getenv("EA_SENTINEL_HEARTBEAT_TIMEOUT_SEC", "300"))
    except Exception:
        value = 300
    return max(60, value)


def sentinel_startup_grace_sec() -> int:
    try:
        value = int(os.getenv("EA_SENTINEL_STARTUP_GRACE_SEC", "180"))
    except Exception:
        value = 180
    return max(0, value)


def sentinel_exit_on_stall() -> bool:
    val = str(os.getenv("EA_SENTINEL_EXIT_ON_STALL", "true")).strip().lower()
    return val in ("1", "true", "yes", "on")


def sentinel_alert_throttled() -> bool:
    """
    Return True if we should suppress user-facing sentinel alerts for now.
    Persists state across container restarts in attachments volume.
    """
    min_interval_sec = max(60, int(os.getenv("EA_SENTINEL_ALERT_MIN_INTERVAL_SEC", "3600")))
    state_path = os.path.join(os.getenv("EA_ATTACHMENTS_DIR", "/attachments"), ".sentinel_last_alert.json")
    now = int(time.time())
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f) if f else {}
        last_ts = int((state or {}).get("ts") or 0)
    except Exception:
        last_ts = 0
    if last_ts > 0 and (now - last_ts) < min_interval_sec:
        return True
    try:
        os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)
        tmp = state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ts": now}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, state_path)
    except Exception:
        pass
    return False


def _watchdog_loop(get_admin_chat_id: Callable[[], str | int | None], telegram_bot_token: str | None) -> None:
    global LAST_HEARTBEAT
    while True:
        time.sleep(15)
        now = time.monotonic()
        if (now - WATCHDOG_BOOT_TS) < sentinel_startup_grace_sec():
            continue
        stalled_for = now - LAST_HEARTBEAT
        if stalled_for <= sentinel_heartbeat_timeout_sec():
            continue
        print(f"🚨 SENTINEL: Heartbeat stalled for {int(stalled_for)}s.", flush=True)
        try:
            admin = get_admin_chat_id()
            if telegram_bot_token and admin and not sentinel_alert_throttled():
                msg = (
                    "⚠️ <b>Temporary interruption</b>\n"
                    "I ran into an internal issue and I am restarting automatically now.\n"
                    "No action is needed from you. If a request was interrupted, please resend it in about a minute."
                )
                req = urllib.request.Request(
                    f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage",
                    data=json.dumps({"chat_id": admin, "text": msg, "parse_mode": "HTML"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass
        if sentinel_exit_on_stall():
            os._exit(1)
        # Diagnostics mode: keep the process alive and avoid tight-loop alerts.
        LAST_HEARTBEAT = now


def start_watchdog_thread(
    *,
    get_admin_chat_id: Callable[[], str | int | None],
    telegram_bot_token: str | None,
) -> None:
    if not sentinel_enabled_for_role():
        return
    threading.Thread(
        target=_watchdog_loop,
        kwargs={
            "get_admin_chat_id": get_admin_chat_id,
            "telegram_bot_token": telegram_bot_token,
        },
        daemon=True,
    ).start()


async def heartbeat_pinger() -> None:
    while True:
        mark_heartbeat()
        await asyncio.sleep(10)
