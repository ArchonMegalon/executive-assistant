from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            out[str(k)] = _to_jsonable(v)
        return out
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]
    return str(value)


def save_intelligence_snapshot(
    *,
    tenant: str,
    person_id: str,
    compose_mode: str,
    profile: Any,
    dossiers: Any,
    future_situations: Any,
    readiness: Any,
    critical: Any,
    preparation: Any,
    epics: Any = (),
    source: str = "briefing_compose",
) -> bool:
    """
    Persist a lightweight compose-cycle intelligence snapshot.
    Best-effort: returns False on DB/table/environment failures.
    """
    tenant_key = str(tenant or "").strip()
    person_key = str(person_id or "").strip()
    if not tenant_key or not person_key:
        return False

    payload = {
        "profile": _to_jsonable(profile),
        "dossiers": _to_jsonable(dossiers),
        "future_situations": _to_jsonable(future_situations),
        "readiness": _to_jsonable(readiness),
        "critical": _to_jsonable(critical),
        "preparation": _to_jsonable(preparation),
        "epics": _to_jsonable(epics),
    }
    try:
        from app.db import get_db

        db = get_db()
        db.execute(
            """
            INSERT INTO intelligence_snapshots
                (tenant, person_id, source, compose_mode, snapshot_json)
            VALUES
                (%s, %s, %s, %s, %s::jsonb)
            """,
            (
                tenant_key,
                person_key,
                str(source or "briefing_compose")[:64],
                str(compose_mode or "")[:64],
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        return True
    except Exception:
        return False
