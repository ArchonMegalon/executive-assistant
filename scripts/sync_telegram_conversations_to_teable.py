#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEABLE_BASE_URL = "https://app.teable.ai"
DEFAULT_TABLE_NAME = "ea_telegram_conversation_messages"
DEFAULT_STATE_FILE = "/data/telegram-teable-sync/state.json"
TRANSIENT_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}
KEY_LOOKUP_BATCH_SIZE = 20
CREATE_RECORD_BATCH_SIZE = 20
VOLATILE_NOOP_FIELDS = {"synced_at"}
TEABLE_LIST_PAGE_SIZE = 1000
CONVERSATION_EVENT_TYPES = (
    "telegram.message",
    "telegram.reply_sent",
    "telegram.reply_async_sent",
)


MESSAGE_FIELDS: list[dict[str, object]] = [
    {"name": "projection_id", "type": "singleLineText"},
    {"name": "observation_id", "type": "singleLineText"},
    {"name": "principal_id", "type": "singleLineText"},
    {"name": "channel", "type": "singleLineText"},
    {"name": "event_type", "type": "singleLineText"},
    {"name": "chat_ref", "type": "singleLineText"},
    {"name": "source_id", "type": "singleLineText"},
    {"name": "external_id", "type": "singleLineText"},
    {"name": "dedupe_key", "type": "singleLineText"},
    {"name": "direction", "type": "singleLineText"},
    {"name": "message_kind", "type": "singleLineText"},
    {"name": "body_text", "type": "longText"},
    {"name": "body_present", "type": "checkbox"},
    {"name": "message_timestamp", "type": "singleLineText"},
    {"name": "event_created_at", "type": "singleLineText"},
    {"name": "synced_at", "type": "singleLineText"},
]


def _load_env_file(path: Path = ROOT / ".env") -> None:
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _parse_env_value(raw_value)


def _parse_env_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        if value[0] == '"':
            try:
                loaded = json.loads(value)
                if isinstance(loaded, str):
                    return loaded
            except Exception:
                return value[1:-1]
        return value[1:-1]
    return value


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _int_value(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _nonnegative_int(value: object, default: int = 0) -> int:
    return max(0, _int_value(value, default))


def _bool_value(value: object, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _load_sync_state(path_value: object) -> dict[str, Any]:
    raw_path = str(path_value or "").strip()
    if not raw_path:
        return {}
    path = Path(raw_path)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(loaded) if isinstance(loaded, dict) else {}


def _save_sync_state(path_value: object, state: dict[str, Any]) -> None:
    raw_path = str(path_value or "").strip()
    if not raw_path:
        return
    path = Path(raw_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")


def _request_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: dict[str, object] | None = None,
    timeout: float = 30,
    attempts: int = 3,
) -> Any:
    import time
    import urllib.error

    data = None if body is None else json.dumps(body, ensure_ascii=True).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **dict(headers or {})},
    )
    bounded_attempts = max(1, min(int(attempts or 1), 5))
    for attempt in range(1, bounded_attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")[:800]
            if exc.code in TRANSIENT_HTTP_STATUS_CODES and attempt < bounded_attempts:
                time.sleep(min(8.0, 1.5 * attempt))
                continue
            raise SystemExit(f"http_error:{exc.code}:{detail}") from exc
        except Exception as exc:
            if attempt < bounded_attempts:
                time.sleep(min(8.0, 1.5 * attempt))
                continue
            raise SystemExit(f"http_request_failed:{type(exc).__name__}:{exc}") from exc
    if not raw.strip():
        return {}
    return json.loads(raw)


def _teable_request(*, method: str, base_url: str, api_key: str, path: str, body: dict[str, object] | None = None) -> Any:
    return _request_json(
        method=method,
        url=f"{base_url.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {api_key}"},
        body=body,
        timeout=45,
    )


def _table_id_from_base(*, base_url: str, api_key: str, base_id: str, table_name: str) -> str:
    if not base_id:
        return ""
    tables_payload = _teable_request(
        method="GET",
        base_url=base_url,
        api_key=api_key,
        path=f"/api/base/{urllib.parse.quote(base_id)}/table",
    )
    tables = tables_payload if isinstance(tables_payload, list) else tables_payload.get("tables") or []
    for raw_table in tables:
        if isinstance(raw_table, dict) and str(raw_table.get("name") or "").strip() == table_name:
            return str(raw_table.get("id") or "").strip()
    return ""


def _discover_table_id(*, base_url: str, api_key: str, table_name: str, base_id: str = "") -> str:
    direct = _table_id_from_base(base_url=base_url, api_key=api_key, base_id=base_id, table_name=table_name)
    if direct:
        return direct
    spaces_payload = _teable_request(method="GET", base_url=base_url, api_key=api_key, path="/api/space")
    spaces = spaces_payload if isinstance(spaces_payload, list) else spaces_payload.get("spaces") or []
    for raw_space in spaces:
        if not isinstance(raw_space, dict):
            continue
        space_id = str(raw_space.get("id") or "").strip()
        if not space_id:
            continue
        bases_payload = _teable_request(method="GET", base_url=base_url, api_key=api_key, path=f"/api/space/{urllib.parse.quote(space_id)}/base")
        bases = bases_payload if isinstance(bases_payload, list) else bases_payload.get("bases") or []
        for raw_base in bases:
            if not isinstance(raw_base, dict):
                continue
            discovered_base_id = str(raw_base.get("id") or "").strip()
            if not discovered_base_id:
                continue
            found = _table_id_from_base(base_url=base_url, api_key=api_key, base_id=discovered_base_id, table_name=table_name)
            if found:
                return found
    return ""


def _create_table(*, base_url: str, api_key: str, base_id: str, table_name: str, fields: list[dict[str, object]]) -> str:
    created = _teable_request(
        method="POST",
        base_url=base_url,
        api_key=api_key,
        path=f"/api/base/{urllib.parse.quote(base_id)}/table/",
        body={"name": table_name, "fields": fields, "fieldKeyType": "name"},
    )
    table_id = str(created.get("id") or "").strip()
    if not table_id:
        raise SystemExit(f"teable_create_table_missing_id:{table_name}")
    return table_id


def _table_fields(*, base_url: str, api_key: str, table_id: str) -> list[dict[str, Any]]:
    payload = _teable_request(
        method="GET",
        base_url=base_url,
        api_key=api_key,
        path=f"/api/table/{urllib.parse.quote(table_id)}/field",
    )
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [dict(item) for item in payload.get("fields") or [] if isinstance(item, dict)]
    return []


def _ensure_fields(*, base_url: str, api_key: str, table_id: str, fields: list[dict[str, object]]) -> int:
    existing = {str(field.get("name") or "").strip() for field in _table_fields(base_url=base_url, api_key=api_key, table_id=table_id)}
    created = 0
    for field in fields:
        name = str(field.get("name") or "").strip()
        if not name or name in existing:
            continue
        _teable_request(
            method="POST",
            base_url=base_url,
            api_key=api_key,
            path=f"/api/table/{urllib.parse.quote(table_id)}/field",
            body={"field": field},
        )
        created += 1
        existing.add(name)
    return created


def _ensure_table(
    *,
    base_url: str,
    api_key: str,
    base_id: str,
    table_id: str,
    table_name: str,
    fields: list[dict[str, object]],
    create_missing: bool,
) -> tuple[str, bool]:
    normalized_table_id = str(table_id or "").strip()
    if normalized_table_id:
        return normalized_table_id, False
    discovered = _discover_table_id(base_url=base_url, api_key=api_key, table_name=table_name, base_id=base_id)
    if discovered:
        return discovered, False
    if not create_missing:
        raise SystemExit(f"teable_table_missing:{table_name}")
    if not base_id:
        raise SystemExit(f"teable_base_id_missing:{table_name}")
    return _create_table(base_url=base_url, api_key=api_key, base_id=base_id, table_name=table_name, fields=fields), True


def _list_records(*, base_url: str, api_key: str, table_id: str, fields: list[str] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    skip = 0
    while True:
        query = ["fieldKeyType=name", "cellFormat=json", f"take={TEABLE_LIST_PAGE_SIZE}", f"skip={skip}"]
        if fields:
            for field in fields:
                query.append(f"fields={urllib.parse.quote(str(field), safe='')}")
        payload = _teable_request(
            method="GET",
            base_url=base_url,
            api_key=api_key,
            path=f"/api/table/{urllib.parse.quote(table_id)}/record?{'&'.join(query)}",
        )
        records = (payload.get("records") or payload.get("data") or []) if isinstance(payload, dict) else (payload if isinstance(payload, list) else [])
        batch = [dict(item) for item in records if isinstance(item, dict)]
        rows.extend(batch)
        if len(batch) < TEABLE_LIST_PAGE_SIZE:
            return rows
        skip += TEABLE_LIST_PAGE_SIZE


def _normalized_row(row: dict[str, object]) -> dict[str, object]:
    return {str(key): value for key, value in row.items() if str(key) not in VOLATILE_NOOP_FIELDS}


def _key_value(value: object) -> str:
    return str(value or "").strip()


def _chunked(values: list[object], size: int) -> list[list[object]]:
    return [values[index : index + size] for index in range(0, len(values), max(1, size))]


def _existing_records_by_key(*, base_url: str, api_key: str, table_id: str, key_field: str, keys: list[str]) -> dict[str, dict[str, Any]]:
    if not keys:
        return {}
    records = _list_records(base_url=base_url, api_key=api_key, table_id=table_id, fields=[key_field])
    by_key: dict[str, dict[str, Any]] = {}
    wanted = set(keys)
    for record in records:
        fields = dict(record.get("fields") or {})
        key = _key_value(fields.get(key_field))
        if key and key in wanted:
            by_key[key] = record
    return by_key


def _upsert_rows(
    *,
    base_url: str,
    api_key: str,
    table_id: str,
    key_field: str,
    rows: list[dict[str, object]],
) -> dict[str, int]:
    if not rows:
        return {"created": 0, "updated": 0, "total": 0}
    keys = [_key_value(row.get(key_field)) for row in rows if _key_value(row.get(key_field))]
    existing = _existing_records_by_key(base_url=base_url, api_key=api_key, table_id=table_id, key_field=key_field, keys=keys)
    to_create: list[dict[str, object]] = []
    to_update: list[dict[str, object]] = []
    created = 0
    updated = 0
    for row in rows:
        key = _key_value(row.get(key_field))
        if not key:
            continue
        record = existing.get(key)
        if not record:
            to_create.append({"fields": row})
            continue
        record_id = _key_value(record.get("id"))
        current_fields = dict(record.get("fields") or {})
        if _normalized_row(current_fields) == _normalized_row(row):
            continue
        if record_id:
            to_update.append({"id": record_id, "fields": row})
    for batch in _chunked(to_create, CREATE_RECORD_BATCH_SIZE):
        _teable_request(
            method="POST",
            base_url=base_url,
            api_key=api_key,
            path=f"/api/table/{urllib.parse.quote(table_id)}/record",
            body={"records": batch, "fieldKeyType": "name"},
        )
        created += len(batch)
    for batch in _chunked(to_update, CREATE_RECORD_BATCH_SIZE):
        _teable_request(
            method="PATCH",
            base_url=base_url,
            api_key=api_key,
            path=f"/api/table/{urllib.parse.quote(table_id)}/record",
            body={"records": batch, "fieldKeyType": "name"},
        )
        updated += len(batch)
    return {"created": created, "updated": updated, "total": created + updated}


def _source_chat_ref(source_id: object, fallback_chat_id: object = "") -> str:
    normalized_source = str(source_id or "").strip()
    if normalized_source.startswith("telegram:"):
        value = normalized_source.split(":", 1)[1].strip()
        if value:
            return value
    return str(fallback_chat_id or "").strip()


def _projection_id(observation_id: object) -> str:
    normalized = str(observation_id or "").strip()
    if not normalized:
        return ""
    return hashlib.sha256(f"telegram:{normalized}".encode("utf-8")).hexdigest()


def _message_row_from_observation(observation: dict[str, Any]) -> dict[str, object] | None:
    event_type = str(observation.get("event_type") or "").strip().lower()
    if event_type not in CONVERSATION_EVENT_TYPES:
        return None
    payload = dict(observation.get("payload") or {})
    source_id = str(observation.get("source_id") or "").strip()
    external_id = str(observation.get("external_id") or "").strip()
    created_at = str(observation.get("created_at") or "").strip()
    if event_type == "telegram.message":
        body_text = str(payload.get("text") or "").strip()
        chat_ref = _source_chat_ref(source_id)
        message_kind = str(payload.get("kind") or "text").strip() or "text"
        message_timestamp = str(payload.get("date") or created_at).strip()
        direction = "inbound"
    else:
        body_text = str(payload.get("reply_text") or "").strip()
        chat_ref = _source_chat_ref(source_id, payload.get("chat_id"))
        message_kind = "text"
        message_timestamp = created_at
        direction = "outbound"
    projection_id = _projection_id(observation.get("observation_id"))
    if not projection_id:
        return None
    return {
        "projection_id": projection_id,
        "observation_id": str(observation.get("observation_id") or "").strip(),
        "principal_id": str(observation.get("principal_id") or "").strip(),
        "channel": "telegram",
        "event_type": event_type,
        "chat_ref": chat_ref,
        "source_id": source_id,
        "external_id": external_id,
        "dedupe_key": str(observation.get("dedupe_key") or "").strip(),
        "direction": direction,
        "message_kind": message_kind,
        "body_text": body_text,
        "body_present": bool(body_text),
        "message_timestamp": message_timestamp,
        "event_created_at": created_at,
        "synced_at": _now_iso(),
    }


def _message_rows_from_observations(observations: list[dict[str, Any]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for observation in observations:
        row = _message_row_from_observation(observation)
        if row is not None:
            rows.append(row)
    return rows


def _connect(database_url: str):  # type: ignore[no-untyped-def]
    try:
        import psycopg
    except Exception as exc:  # pragma: no cover
        raise SystemExit("psycopg_missing") from exc
    return psycopg.connect(database_url, autocommit=True)


def _fetch_telegram_conversation_observations(
    *,
    database_url: str,
    batch_size: int,
    cursor_created_at: str = "",
    cursor_observation_id: str = "",
) -> list[dict[str, Any]]:
    limit = max(1, min(5000, int(batch_size or 500)))
    params: list[object] = [list(CONVERSATION_EVENT_TYPES)]
    where = ["channel = 'telegram'", "event_type = ANY(%s)"]
    if cursor_created_at:
        where.append("(created_at > %s OR (created_at = %s AND observation_id > %s))")
        params.extend([cursor_created_at, cursor_created_at, cursor_observation_id])
    sql = f"""
        SELECT
            observation_id,
            principal_id,
            channel,
            event_type,
            payload_json,
            created_at::text,
            source_id,
            external_id,
            dedupe_key
        FROM observation_events
        WHERE {' AND '.join(where)}
        ORDER BY created_at ASC, observation_id ASC
        LIMIT %s
    """
    params.append(limit)
    with _connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
    return [
        {
            "observation_id": str(observation_id or "").strip(),
            "principal_id": str(principal_id or "").strip(),
            "channel": str(channel or "").strip(),
            "event_type": str(event_type or "").strip(),
            "payload": dict(payload_json or {}),
            "created_at": str(created_at or "").strip(),
            "source_id": str(source_id or "").strip(),
            "external_id": str(external_id or "").strip(),
            "dedupe_key": str(dedupe_key or "").strip(),
        }
        for (
            observation_id,
            principal_id,
            channel,
            event_type,
            payload_json,
            created_at,
            source_id,
            external_id,
            dedupe_key,
        ) in rows
    ]


def parse_args() -> argparse.Namespace:
    _load_env_file()
    parser = argparse.ArgumentParser(description="Sync Telegram conversation observations to Teable.")
    parser.add_argument("--base-url", default=_env("TEABLE_BASE_URL", DEFAULT_TEABLE_BASE_URL))
    parser.add_argument("--api-key", default=_env("TEABLE_API_KEY"))
    parser.add_argument("--base-id", default=_env("EA_TELEGRAM_TEABLE_BASE_ID") or _env("EA_ENV_TEABLE_BASE_ID"))
    parser.add_argument("--table-id", default=_env("EA_TELEGRAM_MESSAGES_TEABLE_TABLE_ID"))
    parser.add_argument("--table-name", default=_env("EA_TELEGRAM_MESSAGES_TEABLE_TABLE_NAME", DEFAULT_TABLE_NAME))
    parser.add_argument("--state-file", default=_env("EA_TELEGRAM_TEABLE_SYNC_STATE_FILE", DEFAULT_STATE_FILE))
    parser.add_argument("--database-url", default=_env("DATABASE_URL"))
    parser.add_argument("--batch-size", type=int, default=int(_env("EA_TELEGRAM_TEABLE_SYNC_BATCH_SIZE", "500") or "500"))
    parser.add_argument("--create-missing-tables", action="store_true", default=True)
    parser.add_argument("--no-create-missing-tables", action="store_false", dest="create_missing_tables")
    parser.add_argument(
        "--disable-state",
        action=argparse.BooleanOptionalAction,
        default=_bool_value(_env("EA_TELEGRAM_TEABLE_SYNC_DISABLE_STATE", "0"), False),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = str(args.api_key or "").strip()
    if not api_key:
        raise SystemExit("teable_api_key_missing")
    database_url = str(args.database_url or "").strip()
    if not database_url:
        raise SystemExit("database_url_missing")
    base_url = str(args.base_url or DEFAULT_TEABLE_BASE_URL).strip().rstrip("/")
    base_id = str(args.base_id or "").strip()
    state = {} if bool(args.disable_state) else _load_sync_state(args.state_file)
    cursor_created_at = str(state.get("last_created_at") or "").strip()
    cursor_observation_id = str(state.get("last_observation_id") or "").strip()

    table_id, created_table = _ensure_table(
        base_url=base_url,
        api_key=api_key,
        base_id=base_id,
        table_id=str(args.table_id or "").strip(),
        table_name=str(args.table_name or DEFAULT_TABLE_NAME).strip(),
        fields=MESSAGE_FIELDS,
        create_missing=bool(args.create_missing_tables),
    )
    fields_created = _ensure_fields(base_url=base_url, api_key=api_key, table_id=table_id, fields=MESSAGE_FIELDS)
    observations = _fetch_telegram_conversation_observations(
        database_url=database_url,
        batch_size=int(args.batch_size),
        cursor_created_at=cursor_created_at,
        cursor_observation_id=cursor_observation_id,
    )
    rows = _message_rows_from_observations(observations)
    upsert = _upsert_rows(base_url=base_url, api_key=api_key, table_id=table_id, key_field="projection_id", rows=rows)

    next_state = dict(state)
    if observations:
        last = observations[-1]
        next_state.update(
            {
                "last_created_at": str(last.get("created_at") or "").strip(),
                "last_observation_id": str(last.get("observation_id") or "").strip(),
            }
        )
    next_state.update(
        {
            "batch_size": max(1, min(5000, int(args.batch_size or 500))),
            "last_batch_observation_count": len(observations),
            "last_batch_row_count": len(rows),
            "table_id": table_id,
            "table_name": str(args.table_name or DEFAULT_TABLE_NAME).strip(),
            "updated_at": _now_iso(),
        }
    )
    if not bool(args.disable_state):
        _save_sync_state(args.state_file, next_state)

    print(
        json.dumps(
            {
                "status": "pass",
                "table_id": table_id,
                "table_name": str(args.table_name or DEFAULT_TABLE_NAME).strip(),
                "created_table": created_table,
                "fields_created": fields_created,
                "observation_count": len(observations),
                "row_count": len(rows),
                "upsert": upsert,
                "state": next_state if not bool(args.disable_state) else {},
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
