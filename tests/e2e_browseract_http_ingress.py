from __future__ import annotations

import json
from uuid import uuid4

import httpx

from app.db import get_db
from app.integrations.avomap.security import sign_webhook_body
from app.settings import settings


def test_browseract_http_ingress() -> None:
    ingest_token = settings.ea_ingest_token or settings.apixdrive_shared_secret
    if not ingest_token:
        print("[E2E][SKIP] browseract HTTP ingress test (missing ingest token)", flush=True)
        return

    tenant = f"chat_{100000 + int(uuid4().hex[:3], 16)}"
    use_signed_avomap = bool(settings.avomap_webhook_secret)
    workflow = settings.avomap_browseract_workflow if use_signed_avomap else "browseract.http_ingress_test"
    dedupe = f"http-wh-{uuid4().hex}"
    payload = {
        "status": "completed",
        "spec_id": f"spec-{uuid4().hex[:10]}",
        "cache_key": f"cache-{uuid4().hex[:10]}",
        "object_ref": f"https://example.invalid/{uuid4().hex}.mp4",
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {ingest_token}",
        "Content-Type": "application/json",
        "x-webhook-id": dedupe,
    }
    if str(workflow).startswith("avomap."):
        headers["x-webhook-signature"] = sign_webhook_body(str(settings.avomap_webhook_secret), body)

    with httpx.Client(timeout=10.0) as c:
        r = c.post(
            f"http://127.0.0.1:8090/webhooks/browseract/{tenant}/{workflow}",
            content=body,
            headers=headers,
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("status") == "ok", data

    row = get_db().fetchone(
        """
        SELECT tenant, source, event_type, dedupe_key
        FROM external_events
        WHERE tenant=%s
          AND source='browseract'
          AND event_type=%s
          AND dedupe_key=%s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (tenant, workflow, dedupe),
    )
    assert row and row.get("source") == "browseract", row
    print("[E2E][PASS] browseract HTTP ingress accepts and persists external event", flush=True)


if __name__ == "__main__":
    test_browseract_http_ingress()
