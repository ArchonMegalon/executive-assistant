from __future__ import annotations

import asyncio
import json
import time
from uuid import uuid4

import httpx

from app.db import get_db
from app.integrations.avomap.security import sign_webhook_body
from app.integrations.avomap.service import AvoMapService
from app.settings import settings
from app.workers.event_worker import poll_external_events


def _ctx(city: str) -> dict:
    return {
        "home_base": {"lat": 48.2082, "lon": 16.3738, "city": "Vienna"},
        "route_stops": [
            {"label": f"{city} Airport", "city": city, "country": "CH", "lat": 47.4582, "lon": 8.5555},
            {"label": f"{city} Hotel", "city": city, "country": "CH", "lat": 47.3769, "lon": 8.5417},
            {"label": f"{city} HQ", "city": city, "country": "CH", "lat": 47.3780, "lon": 8.5400},
        ],
        "travel_email_hints": [f"Flight booking to {city}", f"Hotel confirmation in {city}"],
    }


def _browser_job_data(db, *, tenant: str) -> dict:
    row = db.fetchone(
        """
        SELECT script_payload_json
        FROM browser_jobs
        WHERE tenant=%s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (tenant,),
    ) or {}
    payload = row.get("script_payload_json") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    data = (payload or {}).get("data") or {}
    return dict(data) if isinstance(data, dict) else {}


async def _run_worker_until_ready(*, tenant: str, person_id: str, date_key: str, dedupe: str, timeout_sec: float = 25.0):
    db = get_db()
    svc = AvoMapService(db, enabled=True)
    worker_task = asyncio.create_task(poll_external_events())
    try:
        deadline = time.monotonic() + float(timeout_sec)
        while time.monotonic() < deadline:
            ev = db.fetchone(
                """
                SELECT status
                FROM external_events
                WHERE tenant=%s
                  AND source='browseract'
                  AND dedupe_key=%s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (tenant, dedupe),
            ) or {}
            ready = svc.get_ready_asset(tenant=tenant, person_id=person_id, date_key=date_key)
            if ready and str(ev.get("status") or "") == "processed":
                return ready, ev
            await asyncio.sleep(0.4)
        raise AssertionError("timed out waiting for HTTP->worker->ready-asset chain")
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass


def test_browseract_http_to_ready_asset_chain() -> None:
    ingest_token = settings.ea_ingest_token or settings.apixdrive_shared_secret
    if not ingest_token:
        print("[E2E][SKIP] HTTP->worker chain (missing ingest token)", flush=True)
        return
    if not settings.avomap_webhook_secret:
        print("[E2E][SKIP] HTTP->worker chain (missing avomap webhook secret)", flush=True)
        return

    db = get_db()
    svc = AvoMapService(db, enabled=True)
    tenant = f"e2e_http_chain_{uuid4().hex[:8]}"
    person = "p1"
    day = "2026-03-11"
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
    ) or {}
    spec_id = str(spec_row.get("spec_id") or "")
    cache_key = str(spec_row.get("cache_key") or "")
    assert spec_id and cache_key, spec_row

    payload = _browser_job_data(db, tenant=tenant)
    payload.update(
        {
            "status": "completed",
            "spec_id": spec_id,
            "cache_key": cache_key,
            "object_ref": f"https://cdn.example.com/avomap/{uuid4().hex}.mp4",
            "render_id": f"http-chain-{uuid4().hex[:10]}",
            "duration_sec": 23,
        }
    )
    workflow = str(settings.avomap_browseract_workflow)
    dedupe = f"http-chain-{uuid4().hex}"
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {ingest_token}",
        "Content-Type": "application/json",
        "x-webhook-id": dedupe,
        "x-webhook-signature": sign_webhook_body(str(settings.avomap_webhook_secret), body),
    }

    with httpx.Client(timeout=10.0) as c:
        r = c.post(
            f"http://127.0.0.1:8090/webhooks/browseract/{tenant}/{workflow}",
            content=body,
            headers=headers,
        )
    assert r.status_code == 200, r.text
    ingress_row = db.fetchone(
        """
        SELECT status
        FROM external_events
        WHERE tenant=%s
          AND source='browseract'
          AND event_type=%s
          AND dedupe_key=%s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (tenant, workflow, dedupe),
    ) or {}
    assert str(ingress_row.get("status") or "") in {"new", "queued", "processing", "processed"}, ingress_row

    ready, ev = asyncio.run(
        _run_worker_until_ready(
            tenant=tenant,
            person_id=person,
            date_key=day,
            dedupe=dedupe,
            timeout_sec=30.0,
        )
    )
    assert ready and str(ready.get("object_ref") or "").startswith("https://"), ready
    assert str(ev.get("status") or "") == "processed", ev
    print("[E2E][PASS] browseract HTTP -> durable event -> worker -> ready asset", flush=True)


if __name__ == "__main__":
    test_browseract_http_to_ready_asset_chain()

