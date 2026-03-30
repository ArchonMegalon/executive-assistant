#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


EA_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EA_ROOT / "ea"))

from app.services.ltd_inventory_api import (
    build_inventory_execute_payload,
    extract_inventory_output_json,
)
from app.services.ltd_inventory_markdown import refresh_inventory_markdown


def update_discovery_tracking_table(markdown_text: str, inventory_output_json: dict[str, object]) -> str:
    return refresh_inventory_markdown(markdown_text, inventory_output_json)


def _request_json(
    *,
    host: str,
    api_token: str,
    principal_id: str,
    payload: dict[str, object],
) -> dict[str, object]:
    base = str(host or "").rstrip("/")
    if not base:
        raise ValueError("host_required")
    request = urllib.request.Request(
        url=f"{base}/v1/plans/execute",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"content-type": "application/json"},
    )
    if str(api_token or "").strip():
        request.add_header("authorization", f"Bearer {api_token.strip()}")
    if str(principal_id or "").strip():
        request.add_header("x-ea-principal-id", principal_id.strip())
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"inventory_refresh_http_error:{exc.code}:{body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"inventory_refresh_transport_error:{exc.reason}") from exc
    data = json.loads(body or "{}")
    if not isinstance(data, dict):
        raise ValueError("inventory_refresh_response_not_object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Execute the BrowserAct-backed LTD inventory refresh skill through the local EA API and rewrite LTDs.md.",
    )
    parser.add_argument("--host", default=os.environ.get("EA_HOST", "http://127.0.0.1:8000"))
    parser.add_argument("--api-token", default=os.environ.get("EA_API_TOKEN", ""))
    parser.add_argument("--principal-id", default=os.environ.get("EA_DEFAULT_PRINCIPAL_ID", "local-user"))
    parser.add_argument("--skill-key", default="ltd_inventory_refresh")
    parser.add_argument("--goal", default="refresh LTD inventory facts")
    parser.add_argument("--binding-id", required=True)
    parser.add_argument("--service-name", action="append", default=[])
    parser.add_argument("--requested-field", action="append", default=[])
    parser.add_argument("--instructions", default="")
    parser.add_argument("--run-url", default="")
    parser.add_argument("--inventory-output", default="")
    parser.add_argument("--markdown", default=str(EA_ROOT / "LTDs.md"))
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    payload = build_inventory_execute_payload(
        binding_id=args.binding_id,
        service_names=tuple(args.service_name),
        requested_fields=tuple(args.requested_field),
        skill_key=args.skill_key,
        goal=args.goal,
        instructions=args.instructions,
        run_url=args.run_url,
    )
    response_json = _request_json(
        host=args.host,
        api_token=args.api_token,
        principal_id=args.principal_id,
        payload=payload,
    )
    inventory_output_json = extract_inventory_output_json(response_json)
    if str(args.inventory_output or "").strip():
        Path(args.inventory_output).write_text(
            json.dumps(inventory_output_json, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    markdown_path = Path(args.markdown)
    existing = markdown_path.read_text(encoding="utf-8")
    updated = update_discovery_tracking_table(existing, inventory_output_json)
    if args.write:
        markdown_path.write_text(updated, encoding="utf-8")
    else:
        sys.stdout.write(updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
