#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MEMORIAL_SLUG = "manfred"
DEFAULT_BASE_URL = "https://app.teable.ai"
DEFAULT_TABLE_NAME = "memorial_source_signals"


def _dotenv_value(name: str) -> str:
    dotenv = ROOT / ".env"
    if not dotenv.is_file():
        return ""
    prefix = f"{name}="
    for raw_line in dotenv.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith(prefix):
            continue
        return line[len(prefix) :].strip().strip("'").strip('"')
    return ""


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid_json:{path}")
    return payload


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _configured_base_url() -> str:
    return str(os.environ.get("TEABLE_BASE_URL") or _dotenv_value("TEABLE_BASE_URL") or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL


def _default_memorial_slug() -> str:
    return (
        str(os.environ.get("EA_MEMORIAL_PUBLIC_SOURCE_SLUG") or os.environ.get("MEMORIAL_PUBLIC_SLUG") or "").strip()
        or DEFAULT_MEMORIAL_SLUG
    )


def _default_memorial_path() -> Path:
    configured = str(os.environ.get("EA_MEMORIAL_PUBLIC_SOURCE_JSON") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return ROOT / "memorial_data" / "public_memorials" / _default_memorial_slug() / "memorial.json"


def _default_private_profile_path() -> Path:
    configured = str(os.environ.get("EA_MEMORIAL_PUBLIC_SOURCE_PRIVATE_PROFILE_JSON") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return ROOT / "memorial_data" / "private_memorial_profiles" / _default_memorial_slug() / "llm_profile_notes.json"


def _teable_request(*, method: str, path: str, api_key: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if body is None else json.dumps(body, ensure_ascii=True).encode("utf-8")
    base_url = _configured_base_url()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": base_url.rstrip("/"),
            "Referer": f"{base_url.rstrip('/')}/",
            "User-Agent": "Mozilla/5.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")[:800]
        except Exception:
            detail = str(exc)[:800]
        raise SystemExit(f"teable_http_error:{exc.code}:{detail}")
    if not raw.strip():
        return {}
    loaded = json.loads(raw)
    return dict(loaded or {})


def _table_config() -> dict[str, dict[str, Any]]:
    raw = str(os.environ.get("TEABLE_TABLE_SYNC_CONFIG_JSON") or _dotenv_value("TEABLE_TABLE_SYNC_CONFIG_JSON")).strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(name or "").strip(): dict(value or {})
        for name, value in payload.items()
        if str(name or "").strip() and isinstance(value, dict)
    }


def _build_rows(*, memorial: dict[str, Any], private_profile: dict[str, Any]) -> list[dict[str, str]]:
    slug = str(memorial.get("slug") or _default_memorial_slug()).strip() or _default_memorial_slug()
    rows: list[dict[str, str]] = []
    now = _now_iso()
    seen: set[str] = set()

    for item in private_profile.get("public_source_notes") or []:
        if not isinstance(item, dict):
            continue
        label = " ".join(str(item.get("label") or "").split())
        note = " ".join(str(item.get("note") or "").split())
        source_url = " ".join(str(item.get("source_url") or "").split())
        confidence = " ".join(str(item.get("confidence") or "").split())
        if not note:
            continue
        projection_key = f"{slug}:public-source-note:{label or len(rows)}"
        if projection_key in seen:
            continue
        seen.add(projection_key)
        rows.append(
            {
                "projection_key": projection_key,
                "source_label": label or "public_source_note",
                "source_url": source_url,
                "signal_kind": "public_source_note",
                "confidence": confidence,
                "note": note,
                "memorial_slug": slug,
                "updated_at": now,
            }
        )

    for item in memorial.get("source_grounded_profile") or []:
        if not isinstance(item, dict):
            continue
        trait = " ".join(str(item.get("trait") or "").split())
        evidence = " ".join(str(item.get("evidence") or "").split())
        confidence = " ".join(str(item.get("confidence") or "").split())
        if not (trait or evidence):
            continue
        projection_key = f"{slug}:grounded-profile:{trait or len(rows)}"
        if projection_key in seen:
            continue
        seen.add(projection_key)
        rows.append(
            {
                "projection_key": projection_key,
                "source_label": trait or "grounded_profile",
                "source_url": "",
                "signal_kind": "grounded_profile",
                "confidence": confidence,
                "note": evidence,
                "memorial_slug": slug,
                "updated_at": now,
            }
        )

    return rows


def _existing_record_ids(*, api_key: str, table_id: str, key_field: str, field_key_type: str) -> dict[str, str]:
    payload = _teable_request(
        method="GET",
        path=f"/api/table/{table_id}/record?fieldKeyType={field_key_type}&cellFormat=json&take=1000&projection={key_field}",
        api_key=api_key,
    )
    found: dict[str, str] = {}
    for record in payload.get("records") or []:
        if not isinstance(record, dict):
            continue
        fields = dict(record.get("fields") or {})
        key_value = str(fields.get(key_field) or "").strip()
        record_id = str(record.get("id") or "").strip()
        if key_value and record_id:
            found[key_value] = record_id
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync curated memorial public-source signals into Teable.")
    parser.add_argument("--memorial-json", default=str(_default_memorial_path()))
    parser.add_argument("--private-profile-json", default=str(_default_private_profile_path()))
    parser.add_argument("--base-url", default=str(os.environ.get("TEABLE_BASE_URL") or _dotenv_value("TEABLE_BASE_URL") or DEFAULT_BASE_URL))
    parser.add_argument("--table-name", default=os.environ.get("EA_MEMORIAL_TEABLE_SOURCE_TABLE_NAME") or DEFAULT_TABLE_NAME)
    parser.add_argument("--table-id", default=os.environ.get("EA_MEMORIAL_TEABLE_SOURCE_TABLE_ID") or "")
    args = parser.parse_args()

    os.environ["TEABLE_BASE_URL"] = str(args.base_url or "").strip() or DEFAULT_BASE_URL

    api_key = str(os.environ.get("TEABLE_API_KEY") or _dotenv_value("TEABLE_API_KEY")).strip()
    if not api_key:
        raise SystemExit("teable_missing_api_key")
    config = _table_config()
    table_name = str(args.table_name or "").strip() or DEFAULT_TABLE_NAME
    configured = dict(config.get(table_name) or {})
    table_id = str(args.table_id or configured.get("table_id") or "").strip()
    if not table_id:
        raise SystemExit("teable_table_id_missing")
    key_field = str(configured.get("key_field") or "projection_key").strip() or "projection_key"
    field_key_type = str(configured.get("field_key_type") or "name").strip() or "name"

    memorial = _load_json(Path(args.memorial_json))
    private_profile = _load_json(Path(args.private_profile_json))
    rows = _build_rows(memorial=memorial, private_profile=private_profile)
    existing = _existing_record_ids(api_key=api_key, table_id=table_id, key_field=key_field, field_key_type=field_key_type)
    created = 0
    updated = 0
    pending_creates: list[dict[str, Any]] = []
    for row in rows:
        projection_key = str(row.get(key_field) or "").strip()
        if not projection_key:
            raise SystemExit(f"teable_projection_key_missing:{key_field}")
        record_id = str(existing.get(projection_key) or "").strip()
        if record_id:
            _teable_request(
                method="PATCH",
                path=f"/api/table/{table_id}/record/{record_id}",
                api_key=api_key,
                body={"fieldKeyType": field_key_type, "typecast": True, "record": {"fields": row}},
            )
            updated += 1
            continue
        pending_creates.append({"fields": row})
    if pending_creates:
        result = _teable_request(
            method="POST",
            path=f"/api/table/{table_id}/record",
            api_key=api_key,
            body={"fieldKeyType": field_key_type, "typecast": True, "records": pending_creates},
        )
        created += len(result.get("records") or pending_creates)
    print(
        json.dumps(
            {
                "status": "pass",
                "table_name": table_name,
                "table_id": table_id,
                "base_url": _configured_base_url(),
                "row_count": len(rows),
                "created_count": created,
                "updated_count": updated,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
