from __future__ import annotations
import asyncio, base64, os, time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, List

from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import PlainTextResponse

from app.audit import log_event
from app.db import init_db, connect
from app.queue import ingest_update
from app.settings import settings
from app.scheduler import scheduler_loop
from app.poll_listener import poll_loop, heartbeat_pinger
from app.location_watcher import location_loop
from app.calendar_reminders import calendar_loop
from app.calendar_store import (
    ensure_schema as ensure_calendar_schema,
    list_events_range,
    render_ics,
    verify_ics_token,
    ics_token_for_tenant,
)

app = FastAPI(title="EA OS", version="0.9")


def _require_debug_auth(authorization: str | None) -> None:
    expected = settings.ea_operator_token
    if not expected or authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Unauthorized")

@app.on_event("startup")
async def _startup() -> None:
    await init_db()
    try:
        ensure_calendar_schema()
    except Exception as e:
        log_event(None, "calendar", "warn", "calendar schema init failed", {"error": str(e)})

    asyncio.create_task(scheduler_loop())
    asyncio.create_task(heartbeat_pinger())
    role = (os.environ.get("EA_ROLE") or "monolith").strip().lower()
    if role in ("", "monolith"):
        asyncio.create_task(poll_loop())
    asyncio.create_task(location_loop())
    asyncio.create_task(calendar_loop())

    log_event(None, "server", "startup", "EA server starting", {"tz": settings.tz, "version": "0.9"})

@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}

@app.get("/health/readiness")
async def readiness() -> Dict[str, Any]:
    return {"ok": True}

@app.get("/debug/audit")
async def debug_audit(limit: int = 50, authorization: str = Header(None)) -> Dict[str, Any]:
    _require_debug_auth(authorization)
    # Best-effort: audit table name differs across versions; try common candidates.
    q_candidates = [
        "SELECT ts, tenant, component, event_type, message, payload FROM audit_log ORDER BY ts DESC LIMIT %s",
        "SELECT ts, tenant, component, event_type, message, payload FROM audit_events ORDER BY ts DESC LIMIT %s",
        "SELECT ts, tenant, component, event_type, message, payload FROM audit ORDER BY ts DESC LIMIT %s",
    ]
    rows = []
    with connect() as conn:
        with conn.cursor() as cur:
            for q in q_candidates:
                try:
                    cur.execute(q, (int(limit),))
                    fetched = cur.fetchall() or []
                    rows = []
                    for r in fetched:
                        rows.append({
                            "ts": r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]),
                            "tenant": r[1],
                            "component": r[2],
                            "event_type": r[3],
                            "message": r[4],
                            "payload": r[5] if isinstance(r[5], dict) else (r[5] or {}),
                        })
                    break
                except Exception:
                    continue
    return {"rows": rows}

@app.post("/trigger/briefing/{tenant}")
async def trigger_briefing(tenant: str, authorization: str = Header(None)) -> Dict[str, Any]:
    _require_debug_auth(authorization)
    if not str(tenant).startswith("chat_"):
        raise HTTPException(status_code=400, detail="tenant must be chat_<telegram_chat_id>")
    try:
        chat_id = int(str(tenant).split("_", 1)[1])
    except Exception as e:
        raise HTTPException(status_code=400, detail="invalid chat tenant format") from e
    update_id = int(time.time() * 1000)
    payload = {
        "update_id": update_id,
        "message": {
            "message_id": update_id % 1000000,
            "date": int(time.time()),
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id, "is_bot": False, "first_name": "OperatorTrigger"},
            "text": "/brief",
        },
    }
    ingest_update(tenant=tenant, update_id=update_id, payload=payload)
    return {"ok": True, "tenant": tenant, "queued_update_id": update_id}

@app.get("/calendar/{tenant}.ics", response_class=PlainTextResponse)
async def calendar_ics(tenant: str, token: str) -> str:
    if not verify_ics_token(tenant, token):
        raise HTTPException(status_code=403, detail="bad token")
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=30)
    events = list_events_range(tenant, now - timedelta(days=7), horizon)
    return render_ics(tenant, events)

@app.get("/debug/calendar/token/{tenant}")
async def calendar_token(tenant: str, authorization: str = Header(None)) -> Dict[str, Any]:
    _require_debug_auth(authorization)
    return {"tenant": tenant, "token": ics_token_for_tenant(tenant)}

@app.get("/debug/calendar/{tenant}")
async def debug_calendar(tenant: str, days: int = 7, authorization: str = Header(None)) -> Dict[str, Any]:
    _require_debug_auth(authorization)
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=int(days))
    events = list_events_range(tenant, now - timedelta(days=1), end)
    return {"tenant": tenant, "events": events}
