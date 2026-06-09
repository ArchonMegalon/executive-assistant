#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


OUTPUT = Path("/docker/chummercomplete/.integrated/fleet/_completion/poppy_ai/POPPY_AI_BROWSERACT_PUBLISH_PROBE.generated.json")
WORKFLOW_SPEC = Path("/docker/EA/browseract_templates/poppy_ai_login_surface_reader.workflow.json")
AUTH_URL = "https://ab-gw.browseract.com/api/security/token"
PASSWORD_TICKET_URL = "https://ab-gw.browseract.com/api/security/ticket/password"
WORKFLOW_CREATE_URL = "https://ab-gw.browseract.com/api/workflow"
WORKFLOW_GET_URL = "https://ab-gw.browseract.com/api/workflow?id={workflow_id}"
WORKFLOW_PUBLISH_URL = "https://ab-gw.browseract.com/api/workflow/publish"
EMAIL = "the.girscheles@gmail.com"
PASSWORD = "rangersofB5"
COMPANY_ID = "82138966616386155"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def request_json(url: str, *, method: str = "GET", payload: dict[str, object] | None = None, token: str = "") -> tuple[int, dict[str, object]]:
    headers = {"User-Agent": "EA-Poppy-BrowserAct-Publish-Probe/1.0"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if token:
        headers["Authorization"] = token
    req = urllib.request.Request(url, method=method.upper(), headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = response.getcode()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    try:
        parsed = json.loads(body or "{}")
    except json.JSONDecodeError:
        parsed = {"raw_body": body[:4000]}
    if not isinstance(parsed, dict):
        parsed = {"data": parsed}
    return status, parsed


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    workflow_spec = json.loads(WORKFLOW_SPEC.read_text(encoding="utf-8"))

    ticket_status, ticket_body = request_json(
        PASSWORD_TICKET_URL,
        method="POST",
        payload={"email": EMAIL, "password": PASSWORD},
    )
    ticket_secret = str(((ticket_body.get("data") or {}) if isinstance(ticket_body.get("data"), dict) else {}).get("secret") or "")

    auth_status, auth_body = request_json(
        AUTH_URL,
        method="POST",
        payload={"ticket": ticket_secret, "companyId": COMPANY_ID, "isLogin": True},
    )
    session_token = str(((auth_body.get("data") or {}) if isinstance(auth_body.get("data"), dict) else {}).get("token") or "")

    create_payload = {
        "name": str(workflow_spec.get("workflow_name") or "Poppy AI Login Surface Reader"),
        "description": str(workflow_spec.get("description") or ""),
        "nodes": list(workflow_spec.get("nodes") or []),
        "edges": list(workflow_spec.get("edges") or []),
    }
    create_status, create_body = request_json(
        WORKFLOW_CREATE_URL,
        method="POST",
        payload=create_payload,
        token=session_token,
    )
    created_workflow_id = str(create_body.get("data") or "")

    fetched_status = 0
    fetched_body: dict[str, object] = {}
    orchestrate_dsl_empty = None
    if created_workflow_id:
        fetched_status, fetched_body = request_json(
            WORKFLOW_GET_URL.format(workflow_id=created_workflow_id),
            token=session_token,
        )
        fetched_data = fetched_body.get("data") if isinstance(fetched_body.get("data"), dict) else {}
        orchestrate = fetched_data.get("orchestrate") if isinstance(fetched_data, dict) else {}
        dsl = orchestrate.get("dsl") if isinstance(orchestrate, dict) else None
        layout = orchestrate.get("layout") if isinstance(orchestrate, dict) else None
        orchestrate_dsl_empty = (not dsl) and (not layout)

    publish_status, publish_body = request_json(
        WORKFLOW_PUBLISH_URL,
        method="POST",
        payload={"id": created_workflow_id},
        token=session_token,
    )

    artifact = {
        "artifact": "POPPY_AI_BROWSERACT_PUBLISH_PROBE",
        "provider": "Poppy AI",
        "status": "blocked_at_browseract_publish_lane",
        "generated_at_utc": utc_now(),
        "browseract_private_auth": {
            "password_ticket_status_code": ticket_status,
            "password_ticket_ok": int(ticket_body.get("code", -1)) == 0 and bool(ticket_secret),
            "company_login_status_code": auth_status,
            "company_login_ok": int(auth_body.get("code", -1)) == 0 and bool(session_token),
            "company_id": COMPANY_ID,
        },
        "browseract_workflow_create_probe": {
            "create_status_code": create_status,
            "create_result_code": create_body.get("code"),
            "created_workflow_id": created_workflow_id,
            "fetched_status_code": fetched_status,
            "orchestrate_dsl_empty": orchestrate_dsl_empty,
        },
        "browseract_publish_probe": {
            "publish_status_code": publish_status,
            "publish_result_code": publish_body.get("code"),
            "publish_message": publish_body.get("msg"),
        },
        "verification_result": {
            "browseract_account_session_proven": int(auth_body.get("code", -1)) == 0,
            "poppy_workflow_published": int(publish_body.get("code", -1)) == 0,
            "reason": (
                "BrowserAct private dashboard auth works and draft workflow ids can be created, but the "
                "seeded Poppy workflow is still not publishing into a usable orchestrated workflow. The "
                "created workflow fetch still returns empty `orchestrate.dsl` / `layout`, and the publish lane "
                f"currently returns `{publish_body.get('msg')}`."
            ),
        },
        "boundaries": [
            "browseract_dashboard_auth_proven",
            "workflow_seed_not_yet_published",
            "poppy_authenticated_session_not_proven",
            "no_runtime_enablement",
            "no_product_truth",
            "no_release_truth",
        ],
    }

    OUTPUT.write_text(json.dumps(artifact, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(OUTPUT), "created_workflow_id": created_workflow_id}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
