from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.services.ltd_inventory_markdown import (
    build_discovery_updates,
    update_discovery_tracking_table,
)


ROOT = Path(__file__).resolve().parents[1]


def test_update_discovery_tracking_table_rewrites_matching_services_only() -> None:
    markdown = """# LTDs

## Discovery Tracking

| Service | Account / Email | Discovery Status | Verification Source | Last Verified | Notes |
|---|---|---|---|---|---|
| `BrowserAct` |  | `runtime_ready` | `browseract.extract_account_inventory` |  | waiting |
| `Teable` |  | `missing` | `manual_inventory` |  | stale |
| `Vizologi` |  | `missing` | `manual_inventory` |  | keep me |

## Attention Items
"""
    inventory_output_json = {
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
            {
                "service_name": "UnknownService",
                "account_email": "",
                "discovery_status": "missing",
                "verification_source": "missing",
                "last_verified_at": "2026-03-07T12:02:00Z",
                "missing_fields": ["tier", "account_email"],
            },
        ]
    }

    updated = update_discovery_tracking_table(markdown, inventory_output_json)

    assert "| `BrowserAct` | ops@example.com | `complete` | `browseract_live` | 2026-03-07T12:00:00Z | Plan/Tier: Tier 3; Status: activated |" in updated
    assert "| `Teable` | ops@teable.example | `complete` | `connector_metadata` | 2026-03-07T12:01:00Z | Plan/Tier: License Tier 4; Status: activated |" in updated
    assert "| `Vizologi` |  | `missing` | `manual_inventory` |  | keep me |" in updated
    assert "UnknownService" not in updated


def test_build_discovery_updates_accepts_artifact_envelope_shape() -> None:
    updates = build_discovery_updates(
        {
            "structured_output_json": {
                "services_json": [
                    {
                        "service_name": "BrowserAct",
                        "account_email": "ops@example.com",
                        "discovery_status": "complete",
                        "verification_source": "connector_metadata",
                        "last_verified_at": "2026-03-07T12:00:00Z",
                        "plan_tier": "Tier 3",
                        "facts_json": {"status": "activated"},
                        "missing_fields": [],
                        "live_discovery_error": "",
                    }
                ]
            }
        }
    )

    assert updates["browseract"] == [
        "`BrowserAct`",
        "ops@example.com",
        "`complete`",
        "`connector_metadata`",
        "2026-03-07T12:00:00Z",
        "Plan/Tier: Tier 3; Status: activated",
    ]


def test_refresh_ltds_script_can_write_updated_markdown(tmp_path: Path) -> None:
    markdown_path = tmp_path / "LTDs.md"
    markdown_path.write_text(
        """# LTDs

## Discovery Tracking

| Service | Account / Email | Discovery Status | Verification Source | Last Verified | Notes |
|---|---|---|---|---|---|
| `BrowserAct` |  | `runtime_ready` | `browseract.extract_account_inventory` |  | waiting |

## Attention Items
""",
        encoding="utf-8",
    )
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
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
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/refresh_ltds_from_inventory.py"),
            "--input",
            str(inventory_path),
            "--markdown",
            str(markdown_path),
            "--write",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    updated = markdown_path.read_text(encoding="utf-8")
    assert "ops@example.com" in updated
    assert "Plan/Tier: Tier 3; Status: activated" in updated
