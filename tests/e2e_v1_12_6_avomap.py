from __future__ import annotations

from uuid import uuid4

from app.db import get_db
from app.integrations.avomap.finalize import finalize_avomap_render_event
from app.integrations.avomap.service import AvoMapService
from app.settings import settings


def p(msg: str) -> None:
    print(msg, flush=True)


def _ctx(city: str) -> dict:
    return {
        "home_base": {"lat": 48.2082, "lon": 16.3738, "city": "Vienna"},
        "route_stops": [
            {"label": f"{city} Airport", "city": city, "country": "CH", "lat": 47.4582, "lon": 8.5555},
            {"label": f"{city} Hotel", "city": city, "country": "CH", "lat": 47.3769, "lon": 8.5417},
            {"label": f"{city} HQ", "city": city, "country": "CH", "lat": 47.3780, "lon": 8.5400},
        ],
        "travel_email_hints": [
            f"Flight booking to {city}",
            f"Hotel confirmation in {city}",
        ],
    }


def test_v126_avomap() -> None:
    db = get_db()
    svc = AvoMapService(db, enabled=True)

    tenant = f"e2e_v126_{uuid4().hex[:8]}"
    person = "p1"
    day = "2026-03-04"
    decision = svc.plan_for_briefing(tenant=tenant, person_id=person, day_context=_ctx("Zurich"), date_key=day)
    assert decision["status"] in {"dispatched", "existing_spec", "cache_hit"}, decision

    spec_row = db.fetchone(
        """
        SELECT spec_id, cache_key
        FROM travel_video_specs
        WHERE tenant=%s AND person_id=%s AND date_key=%s
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (tenant, person, day),
    )
    assert spec_row and spec_row.get("spec_id"), spec_row
    spec_id = str(spec_row["spec_id"])
    cache_key = str(spec_row.get("cache_key") or "")

    payload_ok = {
        "status": "completed",
        "spec_id": spec_id,
        "cache_key": cache_key,
        "object_ref": f"https://cdn.example.com/avomap/{uuid4().hex}.mp4",
        "render_id": f"render-{uuid4().hex[:10]}",
        "duration_sec": 21,
    }
    fin = finalize_avomap_render_event(
        event_id=str(uuid4()),
        tenant=tenant,
        workflow=settings.avomap_browseract_workflow,
        payload=payload_ok,
        db=db,
    )
    assert fin["status"] == "completed", fin

    fin_dup = finalize_avomap_render_event(
        event_id=str(uuid4()),
        tenant=tenant,
        workflow=settings.avomap_browseract_workflow,
        payload=payload_ok,
        db=db,
    )
    assert fin_dup["status"] == "completed", fin_dup

    ready = svc.get_ready_asset(tenant=tenant, person_id=person, date_key=day)
    assert ready and str(ready.get("object_ref", "")).startswith("https://"), ready

    tenant_fail = f"e2e_v126_fail_{uuid4().hex[:8]}"
    day_fail = "2026-03-05"
    decision_fail = svc.plan_for_briefing(tenant=tenant_fail, person_id=person, day_context=_ctx("Geneva"), date_key=day_fail)
    assert decision_fail["status"] in {"dispatched", "existing_spec"}, decision_fail
    spec_fail = db.fetchone(
        """
        SELECT spec_id
        FROM travel_video_specs
        WHERE tenant=%s AND person_id=%s AND date_key=%s
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (tenant_fail, person, day_fail),
    )
    assert spec_fail and spec_fail.get("spec_id"), spec_fail
    fin_fail = finalize_avomap_render_event(
        event_id=str(uuid4()),
        tenant=tenant_fail,
        workflow=settings.avomap_browseract_workflow,
        payload={"status": "failed", "spec_id": str(spec_fail["spec_id"]), "error": "simulated timeout"},
        db=db,
    )
    assert fin_fail["status"] == "failed", fin_fail

    failed_row = db.fetchone("SELECT status FROM travel_video_specs WHERE spec_id=%s", (str(spec_fail["spec_id"]),))
    assert (failed_row or {}).get("status") == "failed", failed_row
    p("[E2E][PASS] v1.12.6 avomap candidate/spec/job/finalize/idempotence")


if __name__ == "__main__":
    test_v126_avomap()
