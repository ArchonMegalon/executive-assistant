from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from app.services.preference_profile_service import PreferenceProfileService


@dataclass(frozen=True)
class ProjectionTable:
    table_name: str
    record_count: int
    sample_keys: tuple[str, ...]


def _sample_keys(records: list[dict[str, Any]]) -> tuple[str, ...]:
    if not records:
        return ()
    return tuple(sorted(records[0].keys()))


def _static_projection_records() -> dict[str, list[dict[str, Any]]]:
    return {
        "product_signals": [
            {
                "signal_id": "signal_feedback_preview_001",
                "public_title": "Feedback lane keeps public signal separate from private support",
                "source": "chummer_public",
                "status": "triaged",
                "votes": 7,
                "follows": 2,
                "privacy_status": "public_safe",
                "updated_at": "2026-05-14T00:00:00Z",
            }
        ],
        "black_ledger_dispatches": [
            {
                "dispatch_id": "ledger_dispatch_emerald-sprawl-prelude_turn_0001",
                "world_id": "emerald-sprawl-prelude",
                "turn": 1,
                "title": "Turn 1 — The city is moving",
                "status": "published",
                "gate_status": "pass",
                "published_url": "/ledger/dispatches/ledger_dispatch_emerald-sprawl-prelude_turn_0001",
                "updated_at": "2026-05-14T00:00:00Z",
            }
        ],
        "tick_news_delivery": [
            {
                "batch_id": "tick_news_turn_0002",
                "world_id": "emerald-sprawl-prelude",
                "turn": 2,
                "policy": "operator_only",
                "recipient_count": 1,
                "status": "sent",
                "delivery_ref_redacted": "delivery_954bfaad4681e20d",
                "updated_at": "2026-05-14T00:00:00Z",
            }
        ],
        "package_pressure": [
            {
                "package_id": "desktop-preview",
                "package_type": "desktop",
                "status": "preview",
                "votes": 3,
                "follows": 1,
                "proof_url": "/packages/desktop-preview",
                "updated_at": "2026-05-14T00:00:00Z",
            }
        ],
        "ltd_adapter_readiness": [
            {
                "adapter_id": "productlift_signal_adapter",
                "tool": "productlift",
                "level": "dry_run",
                "status": "ready",
                "last_verified": "2026-05-14T00:00:00Z",
                "blocker": "",
                "owner_repo": "executive-assistant",
            }
        ],
        "preference_review_queue": [
            {
                "projection_id": "pref_node:self:willhaben:aversion:avoid_heating_types",
                "person_id": "self",
                "display_name": "Principal",
                "domain": "willhaben",
                "category": "aversion",
                "key": "avoid_heating_types",
                "confidence": 0.78,
                "source_mode": "explicit_correction",
                "status": "active",
                "target_ref": "preference_node:pref_node:self:willhaben:aversion:avoid_heating_types",
                "projection_version": "2026-05-25T00:00:00Z",
                "editable_fields_allowlist": ["value_json", "strength", "status"],
                "evidence_ref_count": 3,
                "last_updated_at": "2026-05-25T00:00:00Z",
                "expiry_at": "",
                "correlation_id": "principal:self:pref_node:self:willhaben:aversion:avoid_heating_types",
            }
        ],
    }


def build_teable_projection_records(
    *,
    preference_profile_service: PreferenceProfileService | None = None,
    principal_id: str = "",
    person_id: str = "self",
) -> dict[str, list[dict[str, Any]]]:
    records = _static_projection_records()
    if preference_profile_service is None or not str(principal_id or "").strip():
        return records
    dynamic = preference_profile_service.build_teable_projection_records(
        principal_id=str(principal_id or "").strip(),
        person_id=str(person_id or "").strip() or "self",
    )
    for table_name, rows in dynamic.items():
        records[table_name] = [dict(row) for row in rows]
    return records


def _dotenv_value(name: str) -> str:
    dotenv = Path("/docker/EA/.env")
    if not dotenv.is_file():
        return ""
    prefix = f"{name}="
    for raw_line in dotenv.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith(prefix):
            continue
        return line[len(prefix):].strip().strip("'").strip('"')
    return ""


def build_teable_projection_summary(
    *,
    preference_profile_service: PreferenceProfileService | None = None,
    principal_id: str = "",
    person_id: str = "self",
) -> dict[str, Any]:
    records = build_teable_projection_records(
        preference_profile_service=preference_profile_service,
        principal_id=principal_id,
        person_id=person_id,
    )
    return {
        "api_key_present": bool(str(os.environ.get("TEABLE_API_KEY") or "").strip() or _dotenv_value("TEABLE_API_KEY")),
        "tables": [
            {
                "table_name": name,
                "record_count": len(rows),
                "sample_keys": list(_sample_keys(rows)),
            }
            for name, rows in records.items()
        ],
    }
