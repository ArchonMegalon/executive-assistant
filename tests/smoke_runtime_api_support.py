from __future__ import annotations

import os

from fastapi.testclient import TestClient


def build_client(
    *,
    storage_backend: str = "memory",
    auth_token: str = "",
    database_url: str = "",
    approval_threshold_chars: int | None = None,
    principal_id: str = "exec-1",
) -> TestClient:
    os.environ["EA_STORAGE_BACKEND"] = storage_backend
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = auth_token
    if approval_threshold_chars is None:
        os.environ.pop("EA_APPROVAL_THRESHOLD_CHARS", None)
    else:
        os.environ["EA_APPROVAL_THRESHOLD_CHARS"] = str(approval_threshold_chars)
    if database_url:
        os.environ["DATABASE_URL"] = database_url
    else:
        os.environ.pop("DATABASE_URL", None)
    from app.api.app import create_app

    client = TestClient(create_app())
    if principal_id:
        client.headers.update({"X-EA-Principal-ID": principal_id})
    return client


def build_headers(token: str = "", principal_id: str = "") -> dict[str, str]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if principal_id:
        headers["X-EA-Principal-ID"] = principal_id
    return headers
