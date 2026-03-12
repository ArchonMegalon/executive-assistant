from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.services.ltd_inventory_api import (
    build_inventory_execute_payload,
    extract_inventory_output_json,
)


ROOT = Path(__file__).resolve().parents[1]


def test_build_inventory_execute_payload_defaults_requested_fields() -> None:
    payload = build_inventory_execute_payload(
        binding_id="binding-1",
        service_names=("BrowserAct", "Teable"),
        requested_fields=(),
    )

    assert payload["skill_key"] == "ltd_inventory_refresh"
    assert payload["goal"] == "refresh LTD inventory facts"
    assert payload["input_json"] == {
        "binding_id": "binding-1",
        "service_names": ["BrowserAct", "Teable"],
        "requested_fields": ["tier", "account_email", "status"],
    }


def test_extract_inventory_output_json_accepts_plan_execute_envelope() -> None:
    payload = extract_inventory_output_json(
        {
            "artifact_id": "artifact-1",
            "structured_output_json": {
                "service_names": ["BrowserAct"],
                "services_json": [
                    {
                        "service_name": "BrowserAct",
                        "account_email": "ops@example.com",
                    }
                ],
            },
        }
    )

    assert payload["service_names"] == ["BrowserAct"]
    assert payload["services_json"][0]["account_email"] == "ops@example.com"


def test_extract_inventory_output_json_rejects_async_acceptance_shape() -> None:
    try:
        extract_inventory_output_json(
            {
                "session_id": "session-1",
                "status": "awaiting_approval",
                "next_action": "poll_or_subscribe",
            }
        )
    except ValueError as exc:
        assert str(exc) == "inventory_refresh_not_immediate:awaiting_approval"
    else:
        raise AssertionError("expected ValueError for accepted response")


def test_refresh_ltds_via_api_script_executes_skill_and_updates_markdown(tmp_path: Path) -> None:
    request_log: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_POST(self) -> None:  # noqa: N802
            content_length = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(content_length).decode("utf-8")
            request_log.append(
                {
                    "path": self.path,
                    "headers": {str(key).lower(): value for key, value in self.headers.items()},
                    "body": json.loads(body or "{}"),
                }
            )
            response = {
                "skill_key": "ltd_inventory_refresh",
                "task_key": "ltd_inventory_refresh",
                "artifact_id": "artifact-1",
                "kind": "ltd_inventory_profile",
                "content": "inventory summary",
                "structured_output_json": {
                    "service_names": ["BrowserAct", "Teable"],
                    "services_json": [
                        {
                            "service_name": "BrowserAct",
                            "account_email": "ops@example.com",
                            "discovery_status": "complete",
                            "verification_source": "browseract_live",
                            "last_verified_at": "2026-03-07T12:00:00Z",
                            "plan_tier": "Tier 3",
                            "facts_json": {"status": "activated"},
                            "missing_fields": [],
                        },
                        {
                            "service_name": "Teable",
                            "account_email": "ops@teable.example",
                            "discovery_status": "complete",
                            "verification_source": "connector_metadata",
                            "last_verified_at": "2026-03-07T12:01:00Z",
                            "plan_tier": "License Tier 4",
                            "facts_json": {"status": "activated"},
                            "missing_fields": [],
                        },
                    ],
                    "missing_services": [],
                },
                "execution_session_id": "session-1",
                "principal_id": "exec-1",
            }
            encoded = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        markdown_path = tmp_path / "LTDs.md"
        markdown_path.write_text(
            """# LTDs

## Discovery Tracking

| Service | Account / Email | Discovery Status | Verification Source | Last Verified | Notes |
|---|---|---|---|---|---|
| `BrowserAct` |  | `runtime_ready` | `browseract.extract_account_inventory` |  | waiting |
| `Teable` |  | `missing` | `manual_inventory` |  | stale |

## Attention Items
""",
            encoding="utf-8",
        )
        inventory_output_path = tmp_path / "inventory.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/refresh_ltds_via_api.py"),
                "--host",
                f"http://127.0.0.1:{server.server_port}",
                "--api-token",
                "test-token",
                "--principal-id",
                "exec-1",
                "--binding-id",
                "binding-1",
                "--service-name",
                "BrowserAct",
                "--service-name",
                "Teable",
                "--markdown",
                str(markdown_path),
                "--inventory-output",
                str(inventory_output_path),
                "--write",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert completed.returncode == 0, completed.stderr
    updated = markdown_path.read_text(encoding="utf-8")
    assert "ops@example.com" in updated
    assert "ops@teable.example" in updated
    assert "Plan/Tier: Tier 3; Status: activated" in updated
    assert "Plan/Tier: License Tier 4; Status: activated" in updated
    saved_inventory = json.loads(inventory_output_path.read_text(encoding="utf-8"))
    assert saved_inventory["services_json"][0]["service_name"] == "BrowserAct"
    assert request_log[0]["path"] == "/v1/plans/execute"
    assert request_log[0]["headers"]["authorization"] == "Bearer test-token"
    assert request_log[0]["headers"]["x-ea-principal-id"] == "exec-1"
    assert request_log[0]["body"]["skill_key"] == "ltd_inventory_refresh"
    assert request_log[0]["body"]["input_json"]["binding_id"] == "binding-1"
    assert request_log[0]["body"]["input_json"]["requested_fields"] == ["tier", "account_email", "status"]


def test_extract_inventory_output_json_accepts_nested_output_json() -> None:
    payload = extract_inventory_output_json(
        {
            "status": "completed",
            "next_action": "download_artifact",
            "output_json": {
                "services_json": [
                    {
                        "service_name": "MarkupGo",
                        "account_email": "ops@example.com",
                    }
                ]
            },
        }
    )

    assert payload["services_json"][0]["service_name"] == "MarkupGo"
