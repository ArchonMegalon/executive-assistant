#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
if str(EA_DIR) not in sys.path:
    sys.path.insert(0, str(EA_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.api.app import create_app  # noqa: E402


SHOW_SURFACE = ROOT / ".codex-design/product/SHOW_SURFACE_MANIFEST.generated.json"


def _client(*, operator: bool = False) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ["EA_ENABLE_PUBLIC_MEMORIALS"] = "0"
    os.environ["EA_ENABLE_PUBLIC_RESULTS"] = "0"
    os.environ["EA_ENABLE_PUBLIC_TOURS"] = "0"
    os.environ["PROPERTYQUARRY_DEFAULT_BRAND"] = "0"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    if operator:
        os.environ["EA_API_TOKEN"] = "test-token"
        os.environ["EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER"] = "1"
        os.environ["EA_OPERATOR_PRINCIPAL_IDS"] = "project-mode-runtime-check"
    else:
        os.environ["EA_API_TOKEN"] = ""
        os.environ.pop("EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER", None)
        os.environ.pop("EA_OPERATOR_PRINCIPAL_IDS", None)
    client = TestClient(create_app())
    client.headers.update({"X-EA-Principal-ID": "project-mode-runtime-check"})
    if operator:
        client.headers.update({"Authorization": "Bearer test-token"})
        client.headers.update({"X-EA-Operator-ID": "operator-project-mode-runtime"})
    return client


def _internal_hrefs(html: str) -> set[str]:
    return {match for match in re.findall(r'href="([^"]+)"', html) if match.startswith("/")}


def main() -> int:
    if any(arg in {"--help", "-h"} for arg in sys.argv[1:]):
        print("Usage: python scripts/verify_project_mode_runtime.py")
        print("Verifies that the EA core runtime obeys SHOW_SURFACE_MANIFEST route and link boundaries.")
        return 0
    manifest = json.loads(SHOW_SURFACE.read_text(encoding="utf-8"))
    forbidden_surfaces = tuple(str(value).replace("*", "") for value in manifest.get("forbidden_surfaces") or [])
    forbidden_provider_names = tuple(str(value) for value in manifest.get("forbidden_provider_names") or [])
    client = _client()
    operator_client = _client(operator=True)

    modes_public = client.get("/modes", follow_redirects=False)
    if modes_public.status_code not in {401, 403}:
        raise SystemExit(f"modes_public_not_operator_gated:{modes_public.status_code}")
    modes_operator = operator_client.get("/modes", follow_redirects=False)
    if modes_operator.status_code != 200 or "data-project-mode-switchboard" not in modes_operator.text:
        raise SystemExit("modes_operator_surface_unavailable")

    for path in ("/", "/product", "/get-started", "/sign-in", "/app/today", "/app/queue", "/app/commitments", "/app/settings"):
        response = client.get(path, follow_redirects=True)
        if response.status_code != 200:
            raise SystemExit(f"allowed_surface_unavailable:{path}:{response.status_code}")
        body = response.text
        for provider in forbidden_provider_names:
            if provider in body:
                raise SystemExit(f"forbidden_provider_visible:{path}:{provider}")
        for href in _internal_hrefs(body):
            if any(href.startswith(prefix) for prefix in forbidden_surfaces):
                raise SystemExit(f"forbidden_surface_linked:{path}:{href}")

    for path in ("/memorials/manfred", "/memorials/files/manfred/memorial.json", "/properties", "/property"):
        response = client.get(path, follow_redirects=False)
        if response.status_code not in {404, 405, 409}:
            raise SystemExit(f"forbidden_route_open_in_ea_core:{path}:{response.status_code}")

    print(json.dumps({"status": "pass", "message": "project mode runtime surfaces obey the EA core show manifest."}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
