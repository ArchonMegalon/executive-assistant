from __future__ import annotations

from dataclasses import dataclass
import re
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.preference_profile_service import PreferenceProfileService


@dataclass(frozen=True)
class ProjectionTable:
    table_name: str
    record_count: int
    sample_keys: tuple[str, ...]


_ENV_TABLE_NAME = "environment_secret_backup"
_LTD_INVENTORY_TABLE_NAME = "ltd_inventory_snapshot"
_LTD_DISCOVERY_TABLE_NAME = "ltd_discovery_snapshot"
_ENV_KEY_VALUE_SEPARATOR = "="
_DISCOVERY_TRACKING_HEADING = "## Discovery Tracking"


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").is_dir() or (parent / ".codex-design").is_dir():
            return parent
    return current.parents[3]


def _strip_env_quotes(value: str) -> str:
    normalized = str(value or "").strip()
    if len(normalized) >= 2 and normalized[0] in ("'", '"', "`") and normalized.endswith(normalized[0]):
        return normalized[1:-1].strip()
    return normalized


def _normalize_projection_value(value: object) -> str:
    return str(value or "").strip()


def _normalize_projection_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _env_source_candidates() -> tuple[Path, ...]:
    explicit = str(
        os.environ.get("EA_TEABLE_ENV_BACKUP_PATH") or os.environ.get("EA_TEABLE_ENV_FILE_PATH") or ""
    ).strip()
    candidates: list[Path] = []
    if explicit:
        for raw in explicit.split(","):
            candidate = Path(raw.strip()).expanduser()
            if candidate.is_file():
                candidates.append(candidate)
    for path in (_repo_root() / ".env", Path(__file__).resolve().parents[2] / ".env", Path.cwd() / ".env"):
        if path.is_file() and path not in candidates:
            candidates.append(path)
    seen: set[str] = set()
    deduped: list[Path] = []
    for candidate in candidates:
        resolved = str(candidate.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(candidate)
    return tuple(deduped)


def _parse_env_file_lines(path: Path) -> tuple[tuple[str, str, int], ...]:
    rows: list[tuple[str, str, int]] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = str(raw_line or "").strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].lstrip()
        if _ENV_KEY_VALUE_SEPARATOR not in stripped:
            continue
        key, value = stripped.split(_ENV_KEY_VALUE_SEPARATOR, 1)
        key = key.strip()
        if not key:
            continue
        rows.append((key, _strip_env_quotes(value), line_no))
    return tuple(rows)


def _environment_backup_rows() -> list[dict[str, Any]]:
    seen_runtime: set[tuple[str, str, str]] = set()
    rows: list[dict[str, Any]] = []
    observed_at = datetime.now(timezone.utc).isoformat()

    for env_path in _env_source_candidates():
        for raw_key, raw_value, line_no in _parse_env_file_lines(env_path):
            key = str(raw_key).strip()
            value = _normalize_projection_value(raw_value)
            fingerprint = ("env_file", str(env_path), key)
            if fingerprint in seen_runtime:
                continue
            seen_runtime.add(fingerprint)
            projection_id = f"env-file::{_normalize_projection_key(env_path.name)}::{_normalize_projection_key(key)}:{line_no}"
            rows.append(
                {
                    "projection_id": projection_id,
                    "source": f"file:{env_path.name}",
                    "env_key": key,
                    "env_value": value,
                    "has_value": bool(value),
                    "value_length": len(value),
                    "value_file_line": line_no,
                    "value_origin": str(env_path),
                    "observed_at": observed_at,
                }
            )

    for key, value in sorted(os.environ.items(), key=lambda item: str(item[0]).strip().lower()):
        key_text = str(key).strip()
        value_text = _normalize_projection_value(value)
        fingerprint = ("runtime_env", "", key_text)
        if fingerprint in seen_runtime:
            continue
        seen_runtime.add(fingerprint)
        projection_id = f"env-runtime::{_normalize_projection_key(key_text)}"
        rows.append(
            {
                "projection_id": projection_id,
                "source": "runtime_env",
                "env_key": key_text,
                "env_value": value_text,
                "has_value": bool(value_text),
                "value_length": len(value_text),
                "value_file_line": 0,
                "value_origin": "os.environ",
                "observed_at": observed_at,
            }
        )
    return rows


def _ltd_markdown_path() -> Path | None:
    configured = (
        str(os.environ.get("EA_LTDS_MARKDOWN_PATH") or "").strip()
        or str(os.environ.get("EA_LTD_MARKDOWN_PATH") or "").strip()
    )
    if configured:
        configured_path = Path(configured).expanduser()
        if configured_path.is_file():
            return configured_path

    for candidate in (_repo_root() / "LTDs.md", Path(__file__).resolve().parents[3] / "LTDs.md"):
        if candidate.is_file():
            return candidate
    return None


def _parse_markdown_table_rows(lines: list[str], heading: str, minimum_columns: int) -> list[list[str]]:
    try:
        heading_index = next(index for index, value in enumerate(lines) if value.strip() == heading)
    except StopIteration:
        return []
    table_start = None
    for index in range(heading_index + 1, len(lines)):
        if lines[index].strip().startswith("|"):
            table_start = index
            break
    if table_start is None:
        return []
    table_end = table_start
    while table_end < len(lines) and lines[table_end].strip().startswith("|"):
        table_end += 1

    rows: list[list[str]] = []
    for line in lines[table_start:table_end]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        parts = [part.strip() for part in stripped.strip("|").split("|")]
        if len(parts) < minimum_columns:
            continue
        if stripped.startswith("|-") or stripped.startswith("| ---"):
            continue
        if parts and parts[0].lower() in {"service", "| service", "account / email", "`service`"}:
            continue
        rows.append(parts)
    return rows


def _ltd_inventory_rows() -> list[dict[str, Any]]:
    path = _ltd_markdown_path()
    if path is None or not path.is_file():
        return []
    try:
        from app.services.ltd_runtime_catalog import parse_ltd_inventory_markdown
    except Exception:
        return []

    try:
        inventory_rows = parse_ltd_inventory_markdown(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for index, row in enumerate(inventory_rows, start=1):
        rows.append(
            {
                "projection_id": f"ltd-inventory::{index}:{_normalize_projection_key(row.service_name)}",
                "kind": "inventory_row",
                "service_name": row.service_name,
                "plan_tier": row.plan_tier,
                "holding": row.holding,
                "status": row.status,
                "redeem_by": row.redeem_by,
                "workspace_integration_tier": row.workspace_integration_tier,
                "local_integration": row.local_integration,
                "notes": row.notes,
            }
        )
    return rows


def _ltd_discovery_rows() -> list[dict[str, Any]]:
    path = _ltd_markdown_path()
    if path is None or not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for index, row in enumerate(
        _parse_markdown_table_rows(lines, heading=_DISCOVERY_TRACKING_HEADING, minimum_columns=6),
        start=1,
    ):
        rows.append(
            {
                "projection_id": f"ltd-discovery::{index}:{_normalize_projection_key(row[0])}:{_normalize_projection_key(row[1])}",
                "kind": "discovery_row",
                "service_name": row[0].strip("`").strip(),
                "account_email": row[1],
                "discovery_status": row[2],
                "verification_source": row[3],
                "last_verified_at": row[4],
                "notes": row[5],
            }
        )
    return rows


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
        _ENV_TABLE_NAME: _environment_backup_rows(),
        _LTD_INVENTORY_TABLE_NAME: _ltd_inventory_rows(),
        _LTD_DISCOVERY_TABLE_NAME: _ltd_discovery_rows(),
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
    prefix = f"{name}="
    for env_path in _env_source_candidates():
        try:
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or not line.startswith(prefix):
                    continue
                return line[len(prefix):].strip().strip("'").strip('"')
        except Exception:
            continue
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
        "environment_rows": len(records.get(_ENV_TABLE_NAME, ())),
        "ltd_inventory_rows": len(records.get(_LTD_INVENTORY_TABLE_NAME, ())),
        "ltd_discovery_rows": len(records.get(_LTD_DISCOVERY_TABLE_NAME, ())),
        "tables": [
            {
                "table_name": name,
                "record_count": len(rows),
                "sample_keys": list(_sample_keys(rows)),
            }
            for name, rows in records.items()
        ],
    }
