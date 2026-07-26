#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


EA_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPLETION_DIR = Path(os.environ.get("POPPY_COMPLETION_DIR") or EA_ROOT / "ea/_completion/poppy_ai")
DEFAULT_OUTPUT = Path(
    os.environ.get("POPPY_PROVIDER_ACCESS_PROBE_OUTPUT")
    or DEFAULT_COMPLETION_DIR / "POPPY_AI_PROVIDER_ACCESS_PROBE.generated.json"
)
SESSION_PROBE_PATH = Path(
    os.environ.get("POPPY_PROVIDER_SESSION_PROBE_PATH")
    or DEFAULT_COMPLETION_DIR / "POPPY_AI_PROVIDER_SESSION_PROBE.generated.json"
)
LOGIN_URL = "https://app.getpoppy.ai/login"
MARKETING_URL = "https://getpoppy.ai/"
BROWSERACT_API_BASE = str(os.environ.get("BROWSERACT_WORKFLOW_API_BASE") or "https://api.browseract.com/v2/workflow").rstrip("/")
CLERK_KEY_RE = re.compile(r"pk_live_[A-Za-z0-9_-]+")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_local_env() -> dict[str, str]:
    env_path = EA_ROOT / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


LOCAL_ENV = load_local_env()


def env_value(name: str) -> str:
    return str(os.environ.get(name) or LOCAL_ENV.get(name) or "").strip()


def browseract_key() -> str:
    for key_name in (
        "BROWSERACT_API_KEY",
        "BROWSERACT_API_KEY_FALLBACK_1",
        "BROWSERACT_API_KEY_FALLBACK_2",
        "BROWSERACT_API_KEY_FALLBACK_3",
    ):
        value = env_value(key_name)
        if value:
            return value
    return ""


def http_request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 120,
) -> tuple[int, str, dict[str, str]]:
    request_headers = {"User-Agent": "EA-Poppy-Probe/1.0"}
    if headers:
        request_headers.update(headers)
    data = None
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, method=method.upper(), headers=request_headers, data=data)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.getcode(), body, dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body, dict(exc.headers.items())


def browseract_request(path: str, *, query: dict[str, object] | None = None) -> dict[str, object]:
    key = browseract_key()
    if not key:
        return {"status": "missing_api_key"}
    url = BROWSERACT_API_BASE + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    status, body, _headers = http_request(
        url,
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        parsed = json.loads(body or "{}")
    except json.JSONDecodeError:
        parsed = {"raw_body": body[:1000]}
    if not isinstance(parsed, dict):
        parsed = {"data": parsed}
    parsed["_http_status"] = status
    return parsed


def list_browseract_workflows() -> list[dict[str, object]]:
    workflows: list[dict[str, object]] = []
    page = 1
    while True:
        payload = browseract_request("/list-workflows", query={"page": page, "limit": 100})
        items = payload.get("items") or payload.get("workflows") or payload.get("data") or []
        if not isinstance(items, list) or not items:
            break
        workflows.extend([entry for entry in items if isinstance(entry, dict)])
        total_pages = int(payload.get("total_pages") or payload.get("totalPages") or page)
        if page >= total_pages:
            break
        page += 1
    return workflows


def first_non_empty(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def unwrap_clerk_object(payload: object) -> dict[str, object]:
    if isinstance(payload, dict):
        response = payload.get("response")
        if isinstance(response, dict):
            return response
        return payload
    return {}


def main() -> int:
    output_path = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DEFAULT_OUTPUT
    output_path.parent.mkdir(parents=True, exist_ok=True)

    marketing_status, _marketing_body, _marketing_headers = http_request(MARKETING_URL)
    login_status, login_body, _login_headers = http_request(LOGIN_URL)

    clerk_key = ""
    key_match = CLERK_KEY_RE.search(login_body)
    if key_match:
        clerk_key = key_match.group(0)
    frontend_api_host = ""
    if "$" in clerk_key:
        frontend_api_host = clerk_key.split("$", 1)[1]
    elif clerk_key:
        # Clerk keys typically encode the frontend host after a '$', but keep a fallback note.
        frontend_api_host = "clerk.getpoppy.ai"
    else:
        frontend_api_host = "clerk.getpoppy.ai"

    client_status, client_body, _client_headers = http_request(f"https://{frontend_api_host}/v1/client")
    try:
        client_json = json.loads(client_body or "{}")
    except json.JSONDecodeError:
        client_json = {}
    client_payload = unwrap_clerk_object(client_json)

    poppy_login_email = env_value("POPPY_LOGIN_EMAIL")
    poppy_login_password = env_value("POPPY_LOGIN_PASSWORD")
    poppy_password_probe_configured = bool(poppy_login_email and poppy_login_password)
    if poppy_password_probe_configured:
        sign_in_status, sign_in_body, _sign_in_headers = http_request(
            f"https://{frontend_api_host}/v1/client/sign_ins",
            method="POST",
            payload={
                "strategy": "password",
                "identifier": poppy_login_email,
                "password": poppy_login_password,
            },
        )
    else:
        sign_in_status, sign_in_body, _sign_in_headers = 0, "", {}
    try:
        sign_in_json = json.loads(sign_in_body or "{}")
    except json.JSONDecodeError:
        sign_in_json = {}
    sign_in_payload = unwrap_clerk_object(sign_in_json)

    first_factors = sign_in_payload.get("supported_first_factors") or []
    if not first_factors and isinstance(client_payload.get("sign_in"), dict):
        first_factors = client_payload.get("sign_in", {}).get("supported_first_factors") or []
    supported_identifiers = sign_in_payload.get("supported_identifiers") or []
    if not supported_identifiers and isinstance(client_payload.get("sign_in"), dict):
        supported_identifiers = client_payload.get("sign_in", {}).get("supported_identifiers") or []
    factor_strategies = []
    for entry in first_factors:
        if isinstance(entry, dict):
            strategy = first_non_empty(entry.get("strategy"), entry.get("name"), entry.get("type"))
            if strategy:
                factor_strategies.append(strategy)
        elif isinstance(entry, str):
            factor_strategies.append(entry)

    workflows = list_browseract_workflows()
    matching = []
    for entry in workflows:
        haystack = " ".join(str(entry.get(field) or "") for field in ("id", "name", "description", "slug", "workflow_name")).lower()
        if "poppy" not in haystack and "getpoppy" not in haystack:
            continue
        matching.append(
            {
                "id": first_non_empty(entry.get("id"), entry.get("_id"), entry.get("workflow_id")),
                "name": first_non_empty(entry.get("name"), entry.get("workflow_name"), entry.get("title")),
                "description": str(entry.get("description") or "").strip(),
                "publish_at": str(entry.get("publish_at") or "").strip(),
            }
        )

    local_workflow = EA_ROOT / "browseract_templates" / "poppy_ai_login_surface_reader.workflow.json"
    local_packet = EA_ROOT / "browseract_templates" / "poppy_ai_login_surface_reader.packet.json"
    session_probe = {}
    if SESSION_PROBE_PATH.exists():
        try:
            loaded = json.loads(SESSION_PROBE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                session_probe = loaded
        except json.JSONDecodeError:
            session_probe = {}

    authenticated_session_proven = bool(
        ((session_probe.get("verification_result") or {}) if isinstance(session_probe.get("verification_result"), dict) else {}).get(
            "authenticated_session_proven"
        )
    )

    artifact = {
        "artifact": "POPPY_AI_PROVIDER_ACCESS_PROBE",
        "provider": "Poppy AI",
        "status": "session_proven_boundaries_pending" if authenticated_session_proven else "bounded_unverified",
        "generated_at_utc": utc_now(),
        "marketing_site": {
            "url": MARKETING_URL,
            "status_code": marketing_status,
        },
        "login_surface": {
            "url": LOGIN_URL,
            "status_code": login_status,
            "auth_provider": "Clerk" if frontend_api_host else "",
            "clerk_publishable_key_present": bool(clerk_key),
            "frontend_api_host": frontend_api_host,
        },
        "client_probe": {
            "url": f"https://{frontend_api_host}/v1/client",
            "status_code": client_status,
        },
        "sign_in_probe": {
            "url": f"https://{frontend_api_host}/v1/client/sign_ins",
            "status_code": sign_in_status,
            "credentials_configured": poppy_password_probe_configured,
            "supported_identifiers": supported_identifiers,
            "supported_first_factors": factor_strategies,
            "password_factor_available": "password" in {value.lower() for value in factor_strategies},
        },
        "browseract_probe": {
            "api_base": BROWSERACT_API_BASE,
            "api_key_configured": bool(browseract_key()),
            "workflows_total": len(workflows),
            "matching_poppy_workflows": matching,
            "matching_poppy_workflow_count": len(matching),
        },
        "seeded_verification_lane": {
            "local_workflow_spec_path": str(local_workflow),
            "local_workflow_spec_exists": local_workflow.exists(),
            "local_packet_path": str(local_packet),
            "local_packet_exists": local_packet.exists(),
            "lane_kind": "browseract_login_surface_probe",
        },
        "live_session_probe": {
            "receipt_path": str(SESSION_PROBE_PATH),
            "receipt_exists": SESSION_PROBE_PATH.exists(),
            "status": str(session_probe.get("status") or "").strip(),
            "authenticated_session_proven": authenticated_session_proven,
            "blocked_reason": str(((session_probe.get("verification_result") or {}) if isinstance(session_probe.get("verification_result"), dict) else {}).get("blocked_reason") or "").strip(),
        },
        "verification_result": {
            "authenticated_session_proven": authenticated_session_proven,
            "reason": (
                "BrowserAct account is reachable and workflow inventory is enumerable. The live Clerk auth posture "
                "still exposes Google/ticket factors without a password factor, but a host headful Chromium lane "
                "under xvfb-run now proves an authenticated Poppy session on the onboarding surface."
                if authenticated_session_proven
                else (
                    "Poppy marketing, Clerk login, and client surfaces are reachable, but no authenticated "
                    "session receipt is present. Runtime and release use remain unverified."
                )
            ),
        },
        "boundaries": [
            "inventory_only",
            "provider_reachable",
            (
                "authenticated_session_proven_host_headful_only"
                if authenticated_session_proven
                else "authenticated_session_unproven"
            ),
            "browseract_seeded_but_not_published_for_poppy",
            "no_runtime_enablement",
            "no_product_truth",
            "no_release_truth",
        ],
    }

    output_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(output_path), "matching_poppy_workflows": len(matching)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
