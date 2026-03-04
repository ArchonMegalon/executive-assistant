from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from app.db import get_db
from app.settings import settings


def create_briefing_delivery_session(chat_id: int, *, status: str = "pending") -> int | None:
    window_sec = max(60, int(getattr(settings, "avomap_late_attach_window_sec", 900) or 900))
    deadline = datetime.now(timezone.utc) + timedelta(seconds=window_sec)
    row = get_db().fetchone(
        """
        INSERT INTO delivery_sessions (correlation_id, chat_id, mode, status, enhancement_deadline_ts)
        VALUES (%s, %s, 'briefing', %s, %s)
        RETURNING session_id
        """,
        (f"brief-{chat_id}-{int(time.time() * 1000)}", str(chat_id), str(status), deadline),
    )
    if not row:
        return None
    return int(row["session_id"])


def activate_briefing_delivery_session(session_id: int) -> None:
    window_sec = max(60, int(getattr(settings, "avomap_late_attach_window_sec", 900) or 900))
    get_db().execute(
        """
        UPDATE delivery_sessions
        SET status='active',
            enhancement_deadline_ts=NOW() + (%s * INTERVAL '1 second')
        WHERE session_id=%s
        """,
        (window_sec, int(session_id)),
    )
