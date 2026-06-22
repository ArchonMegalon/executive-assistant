#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "https://app.teable.ai"
DEFAULT_TABLE_NAME = "ea_environment_secrets_recovery"
DEFAULT_ENV_FILES = (ROOT / ".env", ROOT / ".env.local", ROOT / "ea" / ".env")
REQUIRED_DEFAULT_ENV_FILES = (ROOT / ".env", ROOT / ".env.local")
SECRET_FILE_MARKERS = ("JSON_FILE", "CREDENTIALS_FILE", "KEY_FILE", "TOKEN_FILE", "SECRET_FILE", "CONFIG_FILE")
DEFAULT_LOCAL_SECRET_FILE_GLOBS = (
    "config/*.local.json",
    "config/*api_keys*.json",
    "config/*accounts*.json",
    "config/*client_secret*.json",
    "config/*slot_owners*.json",
    "config/audiobook_*",
    "config/whatsapp_audiobook_*",
)
LOCAL_SECRET_FILE_AUDIT_GLOBS = (
    *DEFAULT_LOCAL_SECRET_FILE_GLOBS,
    "config/*credential*.json",
    "config/*secret*.json",
)
COMPOSE_REQUIRED_ENV_IGNORE = {"HOME"}
SECRET_MARKERS = (
    "API_KEY",
    "TOKEN",
    "PASSWORD",
    "SECRET",
    "CREDENTIAL",
    "PRIVATE_KEY",
    "ACCESS_KEY",
    "DATABASE_URL",
    "WEBHOOK_SECRET",
    "CLIENT_SECRET",
)

ENV_SECRET_FIELDS: list[dict[str, object]] = [
    {"name": "projection_id", "type": "singleLineText"},
    {"name": "env_name", "type": "singleLineText"},
    {"name": "env_value_secret", "type": "longText"},
    {"name": "value_sha256", "type": "singleLineText"},
    {"name": "value_present", "type": "checkbox"},
    {"name": "value_length", "type": "number"},
    {"name": "secret_kind", "type": "singleLineText"},
    {"name": "provider_guess", "type": "singleLineText"},
    {"name": "source_path", "type": "singleLineText"},
    {"name": "source_scope", "type": "singleLineText"},
    {"name": "restore_enabled", "type": "checkbox"},
    {"name": "last_synced_at", "type": "singleLineText"},
    {"name": "notes", "type": "longText"},
]


def _dotenv_value(name: str, *, env_file: Path = ROOT / ".env") -> str:
    direct = str(os.environ.get(name) or "").strip()
    if direct:
        return direct
    if not env_file.is_file():
        return ""
    prefix = f"{name}="
    for raw_line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith(prefix):
            continue
        return _parse_env_value(line[len(prefix) :])
    return ""


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


def _read_env_file(path: Path) -> list[tuple[str, str]]:
    if not path.is_file():
        return []
    rows: list[tuple[str, str]] = []
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        rows.append((key, _parse_env_value(raw_value)))
    return rows


def _is_secret_name(name: str) -> bool:
    upper = name.upper()
    return any(marker in upper for marker in SECRET_MARKERS)


def _secret_kind(name: str) -> str:
    upper = name.upper()
    if "PASSWORD" in upper:
        return "password"
    if "API_KEY" in upper or upper.endswith("_KEY") or "ACCESS_KEY" in upper:
        return "api_key"
    if "TOKEN" in upper:
        return "token"
    if "DATABASE_URL" in upper:
        return "database_url"
    if "CLIENT_SECRET" in upper or "WEBHOOK_SECRET" in upper or "SECRET" in upper:
        return "secret"
    if "CREDENTIAL" in upper:
        return "credential"
    return "config"


def _provider_guess(name: str) -> str:
    upper = name.upper()
    prefixes = (
        "EA_AUDIOBOOKSHELF",
        "EA_GOOGLE",
        "EA_TELEGRAM",
        "EA_WHATSAPP",
        "ONEMIN",
        "UNMIXR",
        "BROWSERACT",
        "TEABLE",
        "EMAILIT",
        "PAYPAL",
        "PAYFUNNELS",
        "PRODUCTLIFT",
        "PROMPTING_SYSTEMS",
        "MAGICFIT",
        "MARKUPGO",
        "HEDY",
        "APPROVETHIS",
        "DOCUMENTATION_AI",
        "RAFTER",
        "PIXEFY",
        "SOUNDMADESEN",
        "FINETUNING_AI",
        "BLIPAI",
        "CLICKRANK_AI",
        "FASTESTVPN",
        "POSTGRES",
        "DATABASE",
        "CLOUDFLARE",
        "CF_ACCESS",
    )
    for prefix in prefixes:
        if upper.startswith(prefix):
            return prefix.lower()
    return upper.split("_", 1)[0].lower()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_env_secret_rows(
    *,
    env_files: tuple[Path, ...] = DEFAULT_ENV_FILES,
    include_values: bool = False,
    include_non_secret: bool = True,
    host_profile: str = "ea-prod",
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    now = _now_iso()
    seen: set[tuple[str, str]] = set()
    for path in env_files:
        source_scope = _env_file_source_scope(path)
        for key, value in _read_env_file(path):
            is_secret = _is_secret_name(key)
            if not is_secret and not include_non_secret:
                continue
            identity = (source_scope, key)
            if identity in seen:
                continue
            seen.add(identity)
            encoded = value.encode("utf-8")
            rows.append(
                {
                    "projection_id": f"{host_profile}:{source_scope}:{key}",
                    "env_name": key,
                    "env_value_secret": value if include_values else "",
                    "value_sha256": hashlib.sha256(encoded).hexdigest() if include_values and value else "",
                    "value_present": bool(value) if include_values else False,
                    "value_length": len(value) if include_values else 0,
                    "secret_kind": _secret_kind(key) if is_secret else "config",
                    "provider_guess": _provider_guess(key),
                    "source_path": str(path),
                    "source_scope": source_scope,
                    "restore_enabled": True,
                    "last_synced_at": now,
                    "notes": "secret_value_stored_in_teable" if include_values else "metadata_only_secret_value_omitted",
                }
            )
    return rows


def _env_file_source_scope(path: Path) -> str:
    path = Path(path)
    if path == ROOT / ".env":
        return "ea_root"
    if path == ROOT / ".env.local":
        return "ea_root_local"
    if path == ROOT / "ea" / ".env":
        return "ea_service"
    return "ea_service"


def _resolve_env_referenced_file(value: str) -> Path:
    candidate = Path(str(value or "").strip())
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def _normalize_env_file_path(path: Path) -> Path:
    resolved = Path(path)
    if resolved.is_absolute():
        return resolved
    if resolved.as_posix() in {".env", "./.env"}:
        return ROOT / ".env"
    if resolved.as_posix() in {".env.local", "./.env.local"}:
        return ROOT / ".env.local"
    if resolved.as_posix() in {"ea/.env", "./ea/.env"}:
        return ROOT / "ea" / ".env"
    if (ROOT / resolved).is_file():
        return ROOT / resolved
    return ROOT / resolved


def _looks_like_secret_file_env(name: str) -> bool:
    upper = name.upper()
    return any(marker in upper for marker in SECRET_FILE_MARKERS)


def _uses_default_env_files(env_files: tuple[Path, ...]) -> bool:
    return tuple(_normalize_env_file_path(item) for item in env_files) == DEFAULT_ENV_FILES


def _coerce_env_files_from_args(values: list[str]) -> tuple[Path, ...]:
    return tuple(_normalize_env_file_path(Path(item)) for item in values)


def audit_default_env_files(env_files: tuple[Path, ...] = DEFAULT_ENV_FILES) -> dict[str, Any]:
    if not _uses_default_env_files(env_files):
        return {"status": "skipped", "missing_required_env_files": []}
    missing_required = [str(path) for path in REQUIRED_DEFAULT_ENV_FILES if not path.is_file()]
    return {
        "status": "pass" if not missing_required else "fail",
        "missing_required_env_files": missing_required,
    }


def _local_secret_file_candidates() -> list[Path]:
    candidates: set[Path] = set()
    for pattern in LOCAL_SECRET_FILE_AUDIT_GLOBS:
        for path in ROOT.glob(pattern):
            if path.is_file() and not _is_example_secret_file(path):
                candidates.add(path)
    return sorted(candidates)


def _is_example_secret_file(path: Path) -> bool:
    name = path.name.lower()
    return ".example." in name or name.endswith(".example")


def audit_local_secret_file_coverage(
    *,
    env_files: tuple[Path, ...] = DEFAULT_ENV_FILES,
    host_profile: str = "ea-prod",
) -> dict[str, Any]:
    if not _uses_default_env_files(env_files):
        return {
            "status": "skipped",
            "candidate_count": 0,
            "covered_count": 0,
            "uncovered_count": 0,
            "uncovered_paths": [],
        }
    covered_paths = {
        str(row.get("source_path") or "")
        for row in build_referenced_secret_file_rows(env_files=env_files, host_profile=host_profile)
        if str(row.get("source_scope") or "") == "ea_file"
    }
    candidates = [str(path) for path in _local_secret_file_candidates()]
    uncovered = [path for path in candidates if path not in covered_paths]
    return {
        "status": "pass" if not uncovered else "fail",
        "candidate_count": len(candidates),
        "covered_count": len([path for path in candidates if path in covered_paths]),
        "uncovered_count": len(uncovered),
        "uncovered_paths": uncovered[:20],
    }


def audit_compose_required_env_coverage(
    *,
    env_files: tuple[Path, ...] = DEFAULT_ENV_FILES,
) -> dict[str, Any]:
    if not _uses_default_env_files(env_files):
        return {"status": "skipped", "missing_required_compose_env": []}
    recovered_env_names = {
        key
        for path in env_files
        for key, _value in _read_env_file(path)
    }
    missing: set[str] = set()
    for compose_path in ROOT.glob("docker-compose*.yml"):
        if not compose_path.is_file():
            continue
        for expression in re.findall(r"\$\{([^}]+)\}", compose_path.read_text(encoding="utf-8", errors="ignore")):
            name = re.split(r"[:?+\-]", expression, 1)[0].strip()
            if not name or name in COMPOSE_REQUIRED_ENV_IGNORE:
                continue
            has_default_or_error = any(marker in expression for marker in (":-", "-", ":?", "?"))
            if has_default_or_error:
                continue
            if name not in recovered_env_names:
                missing.add(name)
    return {
        "status": "pass" if not missing else "fail",
        "missing_required_compose_env": sorted(missing),
    }


def build_referenced_secret_file_rows(
    *,
    env_files: tuple[Path, ...] = DEFAULT_ENV_FILES,
    host_profile: str = "ea-prod",
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    now = _now_iso()
    seen: set[Path] = set()
    candidates: list[tuple[str, Path]] = []
    for env_file in env_files:
        for key, value in _read_env_file(env_file):
            if not value or not _looks_like_secret_file_env(key):
                continue
            path = _resolve_env_referenced_file(value)
            candidates.append((key, path))
    if _uses_default_env_files(env_files):
        for pattern in DEFAULT_LOCAL_SECRET_FILE_GLOBS:
            for path in sorted(ROOT.glob(pattern)):
                if _is_example_secret_file(path):
                    continue
                candidates.append((f"LOCAL_SECRET_FILE:{path.relative_to(ROOT).as_posix()}", path))
    for key, path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        content = path.read_text(encoding="utf-8", errors="ignore")
        encoded = content.encode("utf-8")
        rows.append(
            {
                "projection_id": f"{host_profile}:ea_file:{path}",
                "env_name": key,
                "env_value_secret": base64.b64encode(encoded).decode("ascii"),
                "value_sha256": hashlib.sha256(encoded).hexdigest() if content else "",
                "value_present": bool(content),
                "value_length": len(content),
                "secret_kind": "secret_file",
                "provider_guess": _provider_guess(key),
                "source_path": str(path),
                "source_scope": "ea_file",
                "restore_enabled": True,
                "last_synced_at": now,
                "notes": "referenced_secret_file_base64_stored_in_teable",
            }
        )
    return rows


def build_recovery_rows(
    *,
    env_files: tuple[Path, ...] = DEFAULT_ENV_FILES,
    include_values: bool = False,
    include_non_secret: bool = True,
    include_referenced_files: bool = True,
    host_profile: str = "ea-prod",
) -> list[dict[str, object]]:
    rows = build_env_secret_rows(
        env_files=env_files,
        include_values=include_values,
        include_non_secret=include_non_secret,
        host_profile=host_profile,
    )
    if include_referenced_files:
        file_rows = build_referenced_secret_file_rows(env_files=env_files, host_profile=host_profile)
        if not include_values:
            for row in file_rows:
                row["env_value_secret"] = ""
                row["value_sha256"] = ""
                row["value_present"] = False
                row["value_length"] = 0
                row["notes"] = "metadata_only_secret_file_value_omitted"
        rows.extend(file_rows)
    return rows


def _teable_request(
    *,
    method: str,
    url: str,
    api_key: str,
    body: dict[str, Any] | None = None,
) -> Any:
    data = None if body is None else json.dumps(body, ensure_ascii=True).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://app.teable.ai",
            "Referer": "https://app.teable.ai/",
            "User-Agent": "Mozilla/5.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "ignore")[:800]
        except Exception:
            detail = str(exc)[:800]
        raise SystemExit(f"teable_http_error:{exc.code}:{detail}") from exc
    except Exception as exc:
        raise SystemExit(f"teable_request_failed:{exc}") from exc
    if not raw.strip():
        return {}
    try:
        loaded = json.loads(raw)
    except Exception as exc:
        raise SystemExit(f"teable_response_invalid_json:{exc}") from exc
    return loaded if loaded is not None else {}


def create_table(*, base_url: str, api_key: str, base_id: str, table_name: str) -> str:
    created = _teable_request(
        method="POST",
        url=f"{base_url.rstrip('/')}/api/base/{urllib.parse.quote(base_id)}/table/",
        api_key=api_key,
        body={"name": table_name, "fields": ENV_SECRET_FIELDS, "fieldKeyType": "name"},
    )
    table_id = str(created.get("id") or "").strip()
    if not table_id:
        raise SystemExit("teable_create_table_missing_id")
    return table_id


def discover_table_id(*, base_url: str, api_key: str, table_name: str) -> str:
    spaces_payload = _teable_request(method="GET", url=f"{base_url.rstrip('/')}/api/space", api_key=api_key)
    spaces: list[dict[str, Any]]
    if isinstance(spaces_payload, list):
        spaces = [dict(item) for item in spaces_payload if isinstance(item, dict)]
    else:
        spaces = [dict(item) for item in spaces_payload.get("spaces") or [] if isinstance(item, dict)]
    normalized_table_name = str(table_name or "").strip()
    for space in spaces:
        space_id = str(space.get("id") or "").strip()
        if not space_id:
            continue
        bases_payload = _teable_request(
            method="GET",
            url=f"{base_url.rstrip('/')}/api/space/{urllib.parse.quote(space_id)}/base",
            api_key=api_key,
        )
        bases = bases_payload if isinstance(bases_payload, list) else bases_payload.get("bases") or []
        for base in [dict(item) for item in bases if isinstance(item, dict)]:
            base_id = str(base.get("id") or "").strip()
            if not base_id:
                continue
            tables_payload = _teable_request(
                method="GET",
                url=f"{base_url.rstrip('/')}/api/base/{urllib.parse.quote(base_id)}/table",
                api_key=api_key,
            )
            tables = tables_payload if isinstance(tables_payload, list) else tables_payload.get("tables") or []
            for table in [dict(item) for item in tables if isinstance(item, dict)]:
                if str(table.get("name") or "").strip() == normalized_table_name:
                    table_id = str(table.get("id") or "").strip()
                    if table_id:
                        return table_id
    return ""


def _existing_record_snapshots(
    *, base_url: str, api_key: str, table_id: str, key_field: str = "projection_id"
) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    skip = 0
    take = 1000
    while True:
        query = urllib.parse.urlencode({"fieldKeyType": "name", "cellFormat": "json", "take": take, "skip": skip})
        payload = _teable_request(
            method="GET",
            url=f"{base_url.rstrip('/')}/api/table/{urllib.parse.quote(table_id)}/record?{query}",
            api_key=api_key,
        )
        records = [dict(item) for item in payload.get("records") or [] if isinstance(item, dict)]
        for record in records:
            fields = dict(record.get("fields") or {})
            key_value = str(fields.get(key_field) or "").strip()
            record_id = str(record.get("id") or "").strip()
            if key_value and record_id:
                stored_secret_hash = _stored_secret_hash_from_fields(fields)
                found[key_value] = {
                    "record_id": record_id,
                    "value_sha256": str(fields.get("value_sha256") or "").strip(),
                    "stored_secret_hash": stored_secret_hash,
                    "value_length": str(fields.get("value_length") or "").strip(),
                }
        if len(records) < take:
            break
        skip += take
    return found


def _existing_record_ids(*, base_url: str, api_key: str, table_id: str, key_field: str = "projection_id") -> dict[str, str]:
    return {
        projection_id: str(snapshot.get("record_id") or "").strip()
        for projection_id, snapshot in _existing_record_snapshots(
            base_url=base_url,
            api_key=api_key,
            table_id=table_id,
            key_field=key_field,
        ).items()
    }


def sync_rows(
    *,
    base_url: str,
    api_key: str,
    table_id: str,
    rows: list[dict[str, object]],
    preserve_blank_secret_values: bool = False,
) -> dict[str, int]:
    existing = _existing_record_snapshots(base_url=base_url, api_key=api_key, table_id=table_id)
    created = 0
    updated = 0
    skipped = 0
    pending_creates: list[dict[str, object]] = []
    for row in rows:
        projection_id = str(row.get("projection_id") or "").strip()
        if not projection_id:
            raise SystemExit("projection_id_missing")
        snapshot = existing.get(projection_id) or {}
        record_id = str(snapshot.get("record_id") or "").strip()
        if record_id:
            normalized_row = dict(row)
            if preserve_blank_secret_values and not str(normalized_row.get("env_value_secret") or ""):
                skipped += 1
                continue
            current_hash = str(snapshot.get("value_sha256") or "").strip()
            current_stored_hash = str(snapshot.get("stored_secret_hash") or "").strip()
            next_hash = str(normalized_row.get("value_sha256") or "").strip()
            if current_hash and current_hash == next_hash and (not next_hash or current_stored_hash == next_hash):
                skipped += 1
                continue
            _teable_request(
                method="PATCH",
                url=f"{base_url.rstrip('/')}/api/table/{urllib.parse.quote(table_id)}/record/{urllib.parse.quote(record_id)}",
                api_key=api_key,
                body={"fieldKeyType": "name", "typecast": True, "record": {"fields": normalized_row}},
            )
            updated += 1
            continue
        pending_creates.append({"fields": row})
    for start in range(0, len(pending_creates), 50):
        chunk = pending_creates[start : start + 50]
        if not chunk:
            continue
        response = _teable_request(
            method="POST",
            url=f"{base_url.rstrip('/')}/api/table/{urllib.parse.quote(table_id)}/record",
            api_key=api_key,
            body={"fieldKeyType": "name", "typecast": True, "records": chunk},
        )
        created += len(response.get("records") or chunk)
    return {"created": created, "updated": updated, "skipped": skipped, "total": len(rows)}


def _list_records(*, base_url: str, api_key: str, table_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    skip = 0
    take = 1000
    while True:
        query = urllib.parse.urlencode({"fieldKeyType": "name", "cellFormat": "json", "take": take, "skip": skip})
        payload = _teable_request(
            method="GET",
            url=f"{base_url.rstrip('/')}/api/table/{urllib.parse.quote(table_id)}/record?{query}",
            api_key=api_key,
        )
        records = [dict(item) for item in payload.get("records") or [] if isinstance(item, dict)]
        rows.extend([dict(item.get("fields") or {}) for item in records])
        if len(records) < take:
            break
        skip += take
    return rows


def _format_env_value(value: str) -> str:
    if value == "":
        return ""
    if all(ch not in value for ch in "\n\r#'\" \t") and not value.startswith(("export ", "$")):
        return value
    return json.dumps(value, ensure_ascii=True)


def _decode_file_secret_cell(value: str) -> str:
    try:
        decoded = base64.b64decode(str(value or "").encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError, ValueError):
        return str(value or "")
    return decoded.decode("utf-8", errors="ignore")


def _stored_secret_value_from_record(row: dict[str, Any]) -> str:
    value = str(row.get("env_value_secret") or "")
    if str(row.get("source_scope") or "").strip() == "ea_file":
        return _decode_file_secret_cell(value)
    return value


def _stored_secret_hash_from_fields(fields: dict[str, Any]) -> str:
    value = _stored_secret_value_from_record(fields)
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def _matches_host_profile(row: dict[str, Any], host_profile: str) -> bool:
    projection_id = str(row.get("projection_id") or "").strip()
    if not projection_id:
        return True
    return projection_id.startswith(f"{host_profile}:")


def _restore_enabled(row: dict[str, Any]) -> bool:
    if "restore_enabled" not in row:
        return str(row.get("notes") or "").strip() != "disabled_stale_not_in_current_env"
    value = row.get("restore_enabled", True)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"false", "0", "no", "off", ""}:
            return False
        return True
    return bool(value)


def _backup_existing_file(path: Path) -> str:
    if not path.exists():
        return ""
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = path.with_name(f"{path.name}.{suffix}.bak")
    counter = 1
    while backup_path.exists():
        backup_path = path.with_name(f"{path.name}.{suffix}.{counter}.bak")
        counter += 1
    shutil.copy2(path, backup_path)
    return str(backup_path)


def _write_private_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


def _mapped_secret_file_output_path(source_path: Path, output_root: Path | None) -> Path:
    if output_root is None:
        return source_path
    if source_path.is_absolute():
        try:
            relative = source_path.relative_to(ROOT)
        except ValueError:
            relative = Path(*source_path.parts[1:])
        return output_root / relative
    return output_root / source_path


def _restorable_rows_for_scope(records: list[dict[str, Any]], *, host_profile: str, source_scope: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in records:
        if not _matches_host_profile(row, host_profile):
            continue
        if str(row.get("source_scope") or "").strip() != source_scope:
            continue
        if not _restore_enabled(row):
            continue
        rows.append(row)
    return rows


def _fail_if_restorable_values_missing(rows: list[dict[str, Any]]) -> None:
    missing: list[str] = []
    for row in rows:
        env_name = str(row.get("env_name") or "").strip()
        value_present = row.get("value_present")
        try:
            value_length = int(row.get("value_length") or 0)
        except (TypeError, ValueError):
            value_length = 0
        value_declared_present = (
            value_present is True
            or bool(str(row.get("value_sha256") or "").strip())
            or value_length > 0
        )
        if not env_name or not value_declared_present:
            continue
        if not _stored_secret_value_from_record(row):
            source_scope = str(row.get("source_scope") or "").strip()
            missing.append(f"{source_scope}:{env_name}" if source_scope else env_name)
    if missing:
        raise SystemExit(f"teable_restore_missing_secret_values:{','.join(missing[:20])}")


def _restore_value_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def _verify_restored_env_file(rows: list[dict[str, Any]], output_path: Path, source_scope: str) -> dict[str, Any]:
    restored_values = dict(_read_env_file(output_path))
    mismatches: list[str] = []
    verified = 0
    for row in rows:
        key = str(row.get("env_name") or "").strip()
        if not key:
            continue
        expected_hash = _restore_value_hash(_stored_secret_value_from_record(row))
        restored_hash = _restore_value_hash(restored_values.get(key, ""))
        if restored_hash != expected_hash:
            mismatches.append(f"{source_scope}:{key}")
            continue
        verified += 1
    return {"hash_verified": verified, "hash_mismatch_keys": mismatches[:20]}


def restore_env_file(
    *,
    base_url: str,
    api_key: str,
    table_id: str,
    output_path: Path,
    source_scope: str,
    host_profile: str = "ea-prod",
    backup_existing: bool = True,
) -> dict[str, Any]:
    records = _list_records(base_url=base_url, api_key=api_key, table_id=table_id)
    rows = _restorable_rows_for_scope(records, host_profile=host_profile, source_scope=source_scope)
    _fail_if_restorable_values_missing(rows)
    values: dict[str, str] = {}
    for row in rows:
        key = str(row.get("env_name") or "").strip()
        if not key:
            continue
        values[key] = str(row.get("env_value_secret") or "")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = _backup_existing_file(output_path) if backup_existing else ""
    lines = [
        "# Rebuilt from Teable environment secret backup.",
        f"# Generated at {_now_iso()}.",
        "# Keep this file out of git.",
    ]
    for key in sorted(values):
        lines.append(f"{key}={_format_env_value(values[key])}")
    _write_private_text(output_path, "\n".join(lines) + "\n")
    verification = _verify_restored_env_file(rows, output_path, source_scope)
    return {"restored": len(values), "backup_path": backup_path, **verification}


def restore_referenced_secret_files(
    *,
    base_url: str,
    api_key: str,
    table_id: str,
    host_profile: str = "ea-prod",
    output_root: Path | None = None,
    backup_existing: bool = True,
) -> dict[str, Any]:
    records = _list_records(base_url=base_url, api_key=api_key, table_id=table_id)
    rows = _restorable_rows_for_scope(records, host_profile=host_profile, source_scope="ea_file")
    _fail_if_restorable_values_missing(rows)
    restored = 0
    backup_paths: list[str] = []
    restored_paths: list[str] = []
    hash_verified = 0
    hash_mismatch_paths: list[str] = []
    for row in rows:
        raw_path = str(row.get("source_path") or "").strip()
        if not raw_path:
            continue
        output_path = _mapped_secret_file_output_path(Path(raw_path), output_root)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path = _backup_existing_file(output_path) if backup_existing else ""
        if backup_path:
            backup_paths.append(backup_path)
        expected_value = _stored_secret_value_from_record(row)
        _write_private_text(output_path, expected_value)
        restored_paths.append(str(output_path))
        restored_value = output_path.read_text(encoding="utf-8")
        if _restore_value_hash(restored_value) == _restore_value_hash(expected_value):
            hash_verified += 1
        else:
            hash_mismatch_paths.append(str(output_path))
        restored += 1
    return {
        "restored_files": restored,
        "file_backup_paths": backup_paths,
        "restored_file_paths": restored_paths,
        "hash_verified": hash_verified,
        "hash_mismatch_paths": hash_mismatch_paths[:20],
    }


def bootstrap_env_files(
    *,
    base_url: str,
    api_key: str,
    table_id: str,
    root_env_path: Path,
    local_env_path: Path | None = None,
    service_env_path: Path,
    host_profile: str = "ea-prod",
    referenced_file_output_root: Path | None = None,
    backup_existing: bool = True,
) -> dict[str, Any]:
    effective_local_env_path = local_env_path or root_env_path.with_name(".env.local")
    root_result = restore_env_file(
        base_url=base_url,
        api_key=api_key,
        table_id=table_id,
        output_path=root_env_path,
        source_scope="ea_root",
        host_profile=host_profile,
        backup_existing=backup_existing,
    )
    local_result = restore_env_file(
        base_url=base_url,
        api_key=api_key,
        table_id=table_id,
        output_path=effective_local_env_path,
        source_scope="ea_root_local",
        host_profile=host_profile,
        backup_existing=backup_existing,
    )
    service_result = restore_env_file(
        base_url=base_url,
        api_key=api_key,
        table_id=table_id,
        output_path=service_env_path,
        source_scope="ea_service",
        host_profile=host_profile,
        backup_existing=backup_existing,
    )
    file_result = restore_referenced_secret_files(
        base_url=base_url,
        api_key=api_key,
        table_id=table_id,
        host_profile=host_profile,
        output_root=referenced_file_output_root,
        backup_existing=backup_existing,
    )
    return {
        "root_env_path": str(root_env_path),
        "root_restored": int(root_result.get("restored") or 0),
        "root_hash_verified": int(root_result.get("hash_verified") or 0),
        "root_hash_mismatch_keys": list(root_result.get("hash_mismatch_keys") or []),
        "root_backup_path": str(root_result.get("backup_path") or ""),
        "local_env_path": str(effective_local_env_path),
        "local_restored": int(local_result.get("restored") or 0),
        "local_hash_verified": int(local_result.get("hash_verified") or 0),
        "local_hash_mismatch_keys": list(local_result.get("hash_mismatch_keys") or []),
        "local_backup_path": str(local_result.get("backup_path") or ""),
        "service_env_path": str(service_env_path),
        "service_restored": int(service_result.get("restored") or 0),
        "service_hash_verified": int(service_result.get("hash_verified") or 0),
        "service_hash_mismatch_keys": list(service_result.get("hash_mismatch_keys") or []),
        "service_backup_path": str(service_result.get("backup_path") or ""),
        "referenced_files_restored": int(file_result.get("restored_files") or 0),
        "referenced_file_hash_verified": int(file_result.get("hash_verified") or 0),
        "referenced_file_hash_mismatch_paths": list(file_result.get("hash_mismatch_paths") or []),
        "referenced_file_backup_count": len(file_result.get("file_backup_paths") or []),
        "referenced_file_paths": list(file_result.get("restored_file_paths") or []),
    }


def _file_mode(path: Path) -> str:
    return oct(path.stat().st_mode & 0o777)


def verify_drill_result(result: dict[str, Any]) -> dict[str, Any]:
    drill_dir = Path(str(result.get("drill_output_dir") or ""))
    expected_paths = [
        Path(str(result.get("root_env_path") or "")),
        Path(str(result.get("service_env_path") or "")),
    ]
    if str(result.get("local_env_path") or "").strip():
        expected_paths.insert(1, Path(str(result.get("local_env_path") or "")))
    expected_paths.extend(Path(str(path)) for path in result.get("referenced_file_paths") or [])
    missing_paths = [str(path) for path in expected_paths if not path.is_file()]
    wrong_modes = [
        {"path": str(path), "mode": _file_mode(path)}
        for path in expected_paths
        if path.is_file() and (path.stat().st_mode & 0o777) != 0o600
    ]
    drill_dir_mode = _file_mode(drill_dir) if drill_dir.is_dir() else ""
    count_mismatch = []
    if int(result.get("referenced_files_restored") or 0) != len(result.get("referenced_file_paths") or []):
        count_mismatch.append("referenced_files_restored")
    if int(result.get("root_hash_verified") or 0) != int(result.get("root_restored") or 0):
        count_mismatch.append("root_hash_verified")
    if int(result.get("local_hash_verified") or 0) != int(result.get("local_restored") or 0):
        count_mismatch.append("local_hash_verified")
    if int(result.get("service_hash_verified") or 0) != int(result.get("service_restored") or 0):
        count_mismatch.append("service_hash_verified")
    if int(result.get("referenced_file_hash_verified") or 0) != int(result.get("referenced_files_restored") or 0):
        count_mismatch.append("referenced_file_hash_verified")
    hash_mismatches = (
        list(result.get("root_hash_mismatch_keys") or [])
        + list(result.get("local_hash_mismatch_keys") or [])
        + list(result.get("service_hash_mismatch_keys") or [])
        + list(result.get("referenced_file_hash_mismatch_paths") or [])
    )
    status = (
        "pass"
        if drill_dir_mode == "0o700" and not missing_paths and not wrong_modes and not count_mismatch and not hash_mismatches
        else "fail"
    )
    return {
        "status": status,
        "drill_dir_mode": drill_dir_mode,
        "checked_file_count": len(expected_paths),
        "missing_paths": missing_paths,
        "wrong_modes": wrong_modes,
        "count_mismatch": count_mismatch,
        "hash_mismatches": hash_mismatches[:20],
    }


def drill_bootstrap_restore(
    *,
    base_url: str,
    api_key: str,
    table_id: str,
    host_profile: str = "ea-prod",
    output_dir: Path | None = None,
) -> dict[str, Any]:
    drill_root = output_dir or Path(tempfile.mkdtemp(prefix="ea-teable-recovery-drill-"))
    drill_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    drill_root.chmod(0o700)
    result = bootstrap_env_files(
        base_url=base_url,
        api_key=api_key,
        table_id=table_id,
        root_env_path=drill_root / ".env",
        local_env_path=drill_root / ".env.local",
        service_env_path=drill_root / "ea" / ".env",
        host_profile=host_profile,
        referenced_file_output_root=drill_root,
        backup_existing=False,
    )
    result.update({"drill_output_dir": str(drill_root), "contains_secret_material": True})
    result["drill_verification"] = verify_drill_result(result)
    return result


def verify_recovery_table(
    *,
    base_url: str,
    api_key: str,
    table_id: str,
    env_files: tuple[Path, ...] = DEFAULT_ENV_FILES,
    host_profile: str = "ea-prod",
) -> dict[str, Any]:
    env_file_audit = audit_default_env_files(env_files)
    expected_rows = build_recovery_rows(env_files=env_files, include_values=True, host_profile=host_profile)
    expected_projection_ids = {
        str(row.get("projection_id") or "").strip()
        for row in expected_rows
        if str(row.get("projection_id") or "").strip()
    }
    records = _list_records(base_url=base_url, api_key=api_key, table_id=table_id)
    records_by_projection = {
        str(row.get("projection_id") or "").strip(): row
        for row in records
        if str(row.get("projection_id") or "").strip()
    }
    same_hash = 0
    missing: list[str] = []
    different: list[str] = []
    missing_secret_values: list[str] = []
    for row in expected_rows:
        projection_id = str(row.get("projection_id") or "").strip()
        env_name = str(row.get("env_name") or "").strip()
        source_scope = str(row.get("source_scope") or "").strip()
        label = f"{source_scope}:{env_name}" if source_scope and env_name else projection_id
        stored = records_by_projection.get(projection_id)
        if not stored:
            missing.append(label)
            continue
        expected_value = str(row.get("env_value_secret") or "")
        stored_value = _stored_secret_value_from_record(stored)
        expected_hash = str(row.get("value_sha256") or "").strip()
        stored_value_hash = hashlib.sha256(stored_value.encode("utf-8")).hexdigest() if stored_value else ""
        if expected_value and not stored_value:
            missing_secret_values.append(label)
            continue
        if stored_value_hash == expected_hash:
            same_hash += 1
            continue
        different.append(label)
    restored_by_scope: dict[str, int] = {"ea_root": 0, "ea_root_local": 0, "ea_service": 0}
    file_restore_count = 0
    extra_restorable = _extra_restorable_rows(
        records=records,
        expected_projection_ids=expected_projection_ids,
        host_profile=host_profile,
    )
    local_file_coverage = audit_local_secret_file_coverage(env_files=env_files, host_profile=host_profile)
    compose_env_coverage = audit_compose_required_env_coverage(env_files=env_files)
    for row in records:
        if not _matches_host_profile(row, host_profile):
            continue
        if not _restore_enabled(row):
            continue
        projection_id = str(row.get("projection_id") or "").strip()
        scope = str(row.get("source_scope") or "").strip()
        env_name = str(row.get("env_name") or "").strip()
        if scope in restored_by_scope and env_name:
            restored_by_scope[scope] += 1
        if scope == "ea_file" and env_name:
            file_restore_count += 1
    status = (
        "pass"
        if env_file_audit.get("status") != "fail"
        and not missing
        and not different
        and not missing_secret_values
        and not extra_restorable
        and local_file_coverage.get("status") != "fail"
        and compose_env_coverage.get("status") != "fail"
        and same_hash == len(expected_rows)
        else "fail"
    )
    return {
        "status": status,
        "table_id": table_id,
        "expected_rows": len(expected_rows),
        "same_hash": same_hash,
        "missing_count": len(missing),
        "different_hash_count": len(different),
        "missing_secret_value_count": len(missing_secret_values),
        "extra_restorable_count": len(extra_restorable),
        "missing_required_env_file_count": len(env_file_audit.get("missing_required_env_files") or []),
        "uncovered_local_secret_file_count": int(local_file_coverage.get("uncovered_count") or 0),
        "missing_required_compose_env_count": len(compose_env_coverage.get("missing_required_compose_env") or []),
        "missing_required_env_files": list(env_file_audit.get("missing_required_env_files") or []),
        "missing_keys": missing[:20],
        "different_hash_keys": different[:20],
        "missing_secret_value_keys": missing_secret_values[:20],
        "extra_restorable_keys": [str(item.get("label") or "") for item in extra_restorable[:20]],
        "uncovered_local_secret_file_paths": list(local_file_coverage.get("uncovered_paths") or []),
        "missing_required_compose_env": list(compose_env_coverage.get("missing_required_compose_env") or []),
        "root_restore_count": restored_by_scope["ea_root"],
        "local_restore_count": restored_by_scope["ea_root_local"],
        "service_restore_count": restored_by_scope["ea_service"],
        "referenced_file_restore_count": file_restore_count,
    }


def _extra_restorable_rows(
    *,
    records: list[dict[str, Any]],
    expected_projection_ids: set[str],
    host_profile: str,
) -> list[dict[str, str]]:
    extra: list[dict[str, str]] = []
    for row in records:
        if not _matches_host_profile(row, host_profile):
            continue
        if not _restore_enabled(row):
            continue
        projection_id = str(row.get("projection_id") or "").strip()
        if not projection_id or projection_id in expected_projection_ids:
            continue
        scope = str(row.get("source_scope") or "").strip()
        env_name = str(row.get("env_name") or "").strip()
        label = f"{scope}:{env_name}" if scope and env_name else projection_id
        extra.append({"projection_id": projection_id, "label": label})
    return extra


def disable_extra_restorable_rows(
    *,
    base_url: str,
    api_key: str,
    table_id: str,
    env_files: tuple[Path, ...] = DEFAULT_ENV_FILES,
    host_profile: str = "ea-prod",
) -> dict[str, Any]:
    env_file_audit = audit_default_env_files(env_files)
    if env_file_audit.get("status") == "fail":
        raise SystemExit(
            "teable_disable_extras_env_file_audit_failed:"
            + ",".join(str(item) for item in env_file_audit.get("missing_required_env_files") or [])
        )
    expected_rows = build_recovery_rows(env_files=env_files, include_values=True, host_profile=host_profile)
    expected_projection_ids = {
        str(row.get("projection_id") or "").strip()
        for row in expected_rows
        if str(row.get("projection_id") or "").strip()
    }
    records = _list_records(base_url=base_url, api_key=api_key, table_id=table_id)
    extras = _extra_restorable_rows(
        records=records,
        expected_projection_ids=expected_projection_ids,
        host_profile=host_profile,
    )
    snapshots = _existing_record_snapshots(base_url=base_url, api_key=api_key, table_id=table_id)
    disabled = 0
    skipped_missing_record_id: list[str] = []
    now = _now_iso()
    for extra in extras:
        projection_id = str(extra.get("projection_id") or "").strip()
        record_id = str((snapshots.get(projection_id) or {}).get("record_id") or "").strip()
        if not record_id:
            skipped_missing_record_id.append(str(extra.get("label") or projection_id))
            continue
        _teable_request(
            method="PATCH",
            url=f"{base_url.rstrip('/')}/api/table/{urllib.parse.quote(table_id)}/record/{urllib.parse.quote(record_id)}",
            api_key=api_key,
            body={
                "fieldKeyType": "name",
                "typecast": True,
                "record": {
                    "fields": {
                        "restore_enabled": False,
                        "last_synced_at": now,
                        "notes": "disabled_stale_not_in_current_env",
                    }
                },
            },
        )
        disabled += 1
    return {
        "status": "disabled",
        "table_id": table_id,
        "disabled_count": disabled,
        "extra_restorable_count": len(extras),
        "disabled_keys": [str(item.get("label") or "") for item in extras[:20]],
        "skipped_missing_record_id": skipped_missing_record_id[:20],
    }


def check_recovery_ready(
    *,
    base_url: str,
    api_key: str,
    table_id: str,
    env_files: tuple[Path, ...] = DEFAULT_ENV_FILES,
    host_profile: str = "ea-prod",
    drill_output_dir: Path | None = None,
) -> dict[str, Any]:
    table_verification = verify_recovery_table(
        base_url=base_url,
        api_key=api_key,
        table_id=table_id,
        env_files=env_files,
        host_profile=host_profile,
    )
    drill = drill_bootstrap_restore(
        base_url=base_url,
        api_key=api_key,
        table_id=table_id,
        host_profile=host_profile,
        output_dir=drill_output_dir,
    )
    drill_output_removed = False
    if drill_output_dir is None:
        raw_drill_dir = str(drill.get("drill_output_dir") or "").strip()
        drill_dir = Path(raw_drill_dir) if raw_drill_dir else None
        if drill_dir is not None and drill_dir.is_dir():
            shutil.rmtree(drill_dir)
            drill_output_removed = True
    status = (
        "pass"
        if table_verification.get("status") == "pass"
        and dict(drill.get("drill_verification") or {}).get("status") == "pass"
        else "fail"
    )
    return {
        "status": status,
        "table_verification": table_verification,
        "drill": drill,
        "drill_output_removed": drill_output_removed,
    }


def _recover_referenced_file_output_root(root_env_path: Path, local_env_path: Path, service_env_path: Path) -> Path | None:
    if root_env_path == ROOT / ".env" and local_env_path == ROOT / ".env.local" and service_env_path == ROOT / "ea" / ".env":
        return None
    if service_env_path == root_env_path.parent / "ea" / ".env":
        return root_env_path.parent
    return None


def _is_default_recovery_output(root_env_path: Path, local_env_path: Path, service_env_path: Path) -> bool:
    return (
        root_env_path == ROOT / ".env"
        and local_env_path == ROOT / ".env.local"
        and service_env_path == ROOT / "ea" / ".env"
    )


def verify_restored_outputs_from_table(
    *,
    base_url: str,
    api_key: str,
    table_id: str,
    root_env_path: Path,
    local_env_path: Path,
    service_env_path: Path,
    referenced_file_paths: list[str],
    referenced_file_output_root: Path | None = None,
    host_profile: str = "ea-prod",
) -> dict[str, Any]:
    records = _list_records(base_url=base_url, api_key=api_key, table_id=table_id)
    root_rows = _restorable_rows_for_scope(records, host_profile=host_profile, source_scope="ea_root")
    local_rows = _restorable_rows_for_scope(records, host_profile=host_profile, source_scope="ea_root_local")
    service_rows = _restorable_rows_for_scope(records, host_profile=host_profile, source_scope="ea_service")
    file_rows = _restorable_rows_for_scope(records, host_profile=host_profile, source_scope="ea_file")
    _fail_if_restorable_values_missing(root_rows + local_rows + service_rows + file_rows)
    root_verification = _verify_restored_env_file(root_rows, root_env_path, "ea_root")
    local_verification = _verify_restored_env_file(local_rows, local_env_path, "ea_root_local")
    service_verification = _verify_restored_env_file(service_rows, service_env_path, "ea_service")
    output_root = referenced_file_output_root
    if output_root is None and service_env_path == root_env_path.parent / "ea" / ".env":
        output_root = root_env_path.parent
    file_path_set = {str(Path(path)) for path in referenced_file_paths}
    file_missing = [str(path) for path in referenced_file_paths if not Path(path).is_file()]
    file_wrong_modes = [
        {"path": str(path), "mode": _file_mode(Path(path))}
        for path in referenced_file_paths
        if Path(path).is_file() and (Path(path).stat().st_mode & 0o777) != 0o600
    ]
    hash_mismatch_paths: list[str] = []
    file_hash_verified = 0
    for row in file_rows:
        source_path = Path(str(row.get("source_path") or ""))
        expected_value = _stored_secret_value_from_record(row)
        expected_hash = _restore_value_hash(expected_value)
        matching_path = str(_mapped_secret_file_output_path(source_path, output_root))
        if not matching_path or matching_path not in file_path_set or not Path(matching_path).is_file():
            hash_mismatch_paths.append(str(source_path))
            continue
        restored_value = Path(matching_path).read_text(encoding="utf-8")
        if _restore_value_hash(restored_value) == expected_hash:
            file_hash_verified += 1
            continue
        hash_mismatch_paths.append(matching_path)
    status = (
        "pass"
        if int(root_verification.get("hash_verified") or 0) == len(root_rows)
        and int(local_verification.get("hash_verified") or 0) == len(local_rows)
        and int(service_verification.get("hash_verified") or 0) == len(service_rows)
        and file_hash_verified == len(file_rows)
        and len(file_path_set) == len(file_rows)
        and not list(root_verification.get("hash_mismatch_keys") or [])
        and not list(local_verification.get("hash_mismatch_keys") or [])
        and not list(service_verification.get("hash_mismatch_keys") or [])
        and not file_missing
        and not file_wrong_modes
        and not hash_mismatch_paths
        else "fail"
    )
    return {
        "status": status,
        "table_id": table_id,
        "expected_rows": len(root_rows) + len(local_rows) + len(service_rows) + len(file_rows),
        "same_hash": int(root_verification.get("hash_verified") or 0)
        + int(local_verification.get("hash_verified") or 0)
        + int(service_verification.get("hash_verified") or 0)
        + file_hash_verified,
        "root_restore_count": len(root_rows),
        "local_restore_count": len(local_rows),
        "service_restore_count": len(service_rows),
        "referenced_file_restore_count": len(file_rows),
        "missing_count": 0,
        "different_hash_count": len(root_verification.get("hash_mismatch_keys") or [])
        + len(local_verification.get("hash_mismatch_keys") or [])
        + len(service_verification.get("hash_mismatch_keys") or [])
        + len(hash_mismatch_paths),
        "missing_secret_value_count": 0,
        "extra_restorable_count": 0,
        "missing_required_env_file_count": 0,
        "uncovered_local_secret_file_count": 0,
        "missing_keys": [],
        "different_hash_keys": (
            list(root_verification.get("hash_mismatch_keys") or [])
            + list(local_verification.get("hash_mismatch_keys") or [])
            + list(service_verification.get("hash_mismatch_keys") or [])
            + hash_mismatch_paths
        )[:20],
        "missing_secret_value_keys": [],
        "extra_restorable_keys": [],
        "missing_required_env_files": [],
        "uncovered_local_secret_file_paths": [],
        "missing_restored_file_paths": file_missing[:20],
        "wrong_restored_file_modes": file_wrong_modes[:20],
    }


def local_recovery_status(
    *,
    base_url: str,
    api_key: str,
    table_id: str,
    root_env_path: Path,
    local_env_path: Path,
    service_env_path: Path,
    host_profile: str = "ea-prod",
) -> dict[str, Any]:
    records = _list_records(base_url=base_url, api_key=api_key, table_id=table_id)
    root_rows = _restorable_rows_for_scope(records, host_profile=host_profile, source_scope="ea_root")
    local_rows = _restorable_rows_for_scope(records, host_profile=host_profile, source_scope="ea_root_local")
    service_rows = _restorable_rows_for_scope(records, host_profile=host_profile, source_scope="ea_service")
    file_rows = _restorable_rows_for_scope(records, host_profile=host_profile, source_scope="ea_file")
    _fail_if_restorable_values_missing(root_rows + local_rows + service_rows + file_rows)

    missing_paths: list[str] = []
    wrong_modes: list[dict[str, str]] = []
    hash_mismatches: list[str] = []

    env_checks = (
        ("ea_root", root_rows, root_env_path),
        ("ea_root_local", local_rows, local_env_path),
        ("ea_service", service_rows, service_env_path),
    )
    env_hash_verified = 0
    for source_scope, rows, output_path in env_checks:
        if rows and not output_path.is_file():
            missing_paths.append(str(output_path))
            hash_mismatches.extend(
                f"{source_scope}:{str(row.get('env_name') or '').strip()}" for row in rows[:20] if row.get("env_name")
            )
            continue
        if rows and (output_path.stat().st_mode & 0o777) != 0o600:
            wrong_modes.append({"path": str(output_path), "mode": _file_mode(output_path)})
        verification = _verify_restored_env_file(rows, output_path, source_scope)
        env_hash_verified += int(verification.get("hash_verified") or 0)
        hash_mismatches.extend(list(verification.get("hash_mismatch_keys") or []))

    file_hash_verified = 0
    for row in file_rows:
        raw_path = str(row.get("source_path") or "").strip()
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.is_file():
            missing_paths.append(str(path))
            hash_mismatches.append(str(path))
            continue
        if (path.stat().st_mode & 0o777) != 0o600:
            wrong_modes.append({"path": str(path), "mode": _file_mode(path)})
        expected_value = _stored_secret_value_from_record(row)
        restored_value = path.read_text(encoding="utf-8")
        if _restore_value_hash(restored_value) == _restore_value_hash(expected_value):
            file_hash_verified += 1
        else:
            hash_mismatches.append(str(path))

    expected_rows = len(root_rows) + len(local_rows) + len(service_rows) + len(file_rows)
    same_hash = env_hash_verified + file_hash_verified
    status = "pass" if same_hash == expected_rows and not missing_paths and not wrong_modes and not hash_mismatches else "fail"
    return {
        "status": status,
        "table_id": table_id,
        "expected_rows": expected_rows,
        "same_hash": same_hash,
        "root_restore_count": len(root_rows),
        "local_restore_count": len(local_rows),
        "service_restore_count": len(service_rows),
        "referenced_file_restore_count": len(file_rows),
        "missing_artifact_count": len(missing_paths),
        "wrong_mode_count": len(wrong_modes),
        "different_hash_count": len(hash_mismatches),
        "missing_artifact_paths": missing_paths[:20],
        "wrong_modes": wrong_modes[:20],
        "different_hash_keys": hash_mismatches[:20],
    }


def ensure_local_recovery(
    *,
    base_url: str,
    api_key: str,
    table_id: str,
    root_env_path: Path,
    local_env_path: Path,
    service_env_path: Path,
    host_profile: str = "ea-prod",
    backup_existing: bool = True,
) -> dict[str, Any]:
    first_status = local_recovery_status(
        base_url=base_url,
        api_key=api_key,
        table_id=table_id,
        root_env_path=root_env_path,
        local_env_path=local_env_path,
        service_env_path=service_env_path,
        host_profile=host_profile,
    )
    if first_status.get("status") == "pass":
        return {
            "status": "ensured",
            "table_id": table_id,
            "recovered": False,
            "mode_repairs": 0,
            "local_status": first_status,
        }
    if (
        int(first_status.get("missing_artifact_count") or 0) == 0
        and int(first_status.get("different_hash_count") or 0) == 0
        and int(first_status.get("wrong_mode_count") or 0) > 0
    ):
        repaired = 0
        for item in first_status.get("wrong_modes") or []:
            path = Path(str(dict(item).get("path") or ""))
            if path.is_file():
                path.chmod(0o600)
                repaired += 1
        repaired_status = local_recovery_status(
            base_url=base_url,
            api_key=api_key,
            table_id=table_id,
            root_env_path=root_env_path,
            local_env_path=local_env_path,
            service_env_path=service_env_path,
            host_profile=host_profile,
        )
        return {
            "status": "ensured" if repaired_status.get("status") == "pass" else "failed",
            "table_id": table_id,
            "recovered": False,
            "mode_repairs": repaired,
            "local_status": repaired_status,
            "initial_local_status": first_status,
        }
    recovery = recover_from_teable(
        base_url=base_url,
        api_key=api_key,
        table_id=table_id,
        root_env_path=root_env_path,
        local_env_path=local_env_path,
        service_env_path=service_env_path,
        host_profile=host_profile,
        backup_existing=backup_existing,
    )
    return {
        "status": "ensured" if recovery.get("status") == "recovered" else "failed",
        "table_id": table_id,
        "recovered": recovery.get("status") == "recovered",
        "mode_repairs": 0,
        "local_status": recovery.get("verification", {}),
        "initial_local_status": first_status,
        "recovery": recovery,
    }


def _path_mode_if_file(path: Path) -> str:
    return _file_mode(path) if path.is_file() else ""


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def build_recovery_proof(
    *,
    status: str,
    table_id: str,
    host_profile: str,
    root_env_path: Path,
    local_env_path: Path,
    service_env_path: Path,
    bootstrap: dict[str, Any],
    verification: dict[str, Any],
) -> dict[str, Any]:
    referenced_file_paths = [str(path) for path in list(bootstrap.get("referenced_file_paths") or []) if str(path)]
    env_files = [
        {
            "scope": "ea_root",
            "path": str(root_env_path),
            "restored": _int_value(bootstrap.get("root_restored")),
            "hash_verified": _int_value(bootstrap.get("root_hash_verified")),
            "hash_mismatch_count": len(list(bootstrap.get("root_hash_mismatch_keys") or [])),
            "backup_created": bool(str(bootstrap.get("root_backup_path") or "").strip()),
            "mode": _path_mode_if_file(root_env_path),
        },
        {
            "scope": "ea_root_local",
            "path": str(local_env_path),
            "restored": _int_value(bootstrap.get("local_restored")),
            "hash_verified": _int_value(bootstrap.get("local_hash_verified")),
            "hash_mismatch_count": len(list(bootstrap.get("local_hash_mismatch_keys") or [])),
            "backup_created": bool(str(bootstrap.get("local_backup_path") or "").strip()),
            "mode": _path_mode_if_file(local_env_path),
        },
        {
            "scope": "ea_service",
            "path": str(service_env_path),
            "restored": _int_value(bootstrap.get("service_restored")),
            "hash_verified": _int_value(bootstrap.get("service_hash_verified")),
            "hash_mismatch_count": len(list(bootstrap.get("service_hash_mismatch_keys") or [])),
            "backup_created": bool(str(bootstrap.get("service_backup_path") or "").strip()),
            "mode": _path_mode_if_file(service_env_path),
        },
    ]
    return {
        "contract_name": "ea.teable_env_recovery_proof.v1",
        "generated_at": _now_iso(),
        "status": status,
        "table_id": table_id,
        "host_profile": host_profile,
        "secret_values_redacted": True,
        "env_files": env_files,
        "referenced_files": {
            "restored": _int_value(bootstrap.get("referenced_files_restored")),
            "hash_verified": _int_value(bootstrap.get("referenced_file_hash_verified")),
            "hash_mismatch_count": len(list(bootstrap.get("referenced_file_hash_mismatch_paths") or [])),
            "backup_count": _int_value(bootstrap.get("referenced_file_backup_count")),
            "path_count": len(referenced_file_paths),
            "paths": referenced_file_paths[:20],
            "modes": [
                {"path": path, "mode": _path_mode_if_file(Path(path))}
                for path in referenced_file_paths[:20]
            ],
        },
        "verification": {
            "status": str(verification.get("status") or ""),
            "expected_rows": _int_value(verification.get("expected_rows")),
            "same_hash": _int_value(verification.get("same_hash")),
            "missing_count": _int_value(verification.get("missing_count")),
            "different_hash_count": _int_value(verification.get("different_hash_count")),
            "missing_secret_value_count": _int_value(verification.get("missing_secret_value_count")),
            "extra_restorable_count": _int_value(verification.get("extra_restorable_count")),
        },
    }


def recover_from_teable(
    *,
    base_url: str,
    api_key: str,
    table_id: str,
    root_env_path: Path,
    local_env_path: Path | None = None,
    service_env_path: Path,
    host_profile: str = "ea-prod",
    backup_existing: bool = True,
) -> dict[str, Any]:
    effective_local_env_path = local_env_path or root_env_path.with_name(".env.local")
    bootstrap = bootstrap_env_files(
        base_url=base_url,
        api_key=api_key,
        table_id=table_id,
        root_env_path=root_env_path,
        local_env_path=effective_local_env_path,
        service_env_path=service_env_path,
        host_profile=host_profile,
        referenced_file_output_root=_recover_referenced_file_output_root(
            root_env_path, effective_local_env_path, service_env_path
        ),
        backup_existing=backup_existing,
    )
    bootstrap_ok = (
        int(bootstrap.get("root_hash_verified") or 0) == int(bootstrap.get("root_restored") or 0)
        and int(bootstrap.get("local_hash_verified") or 0) == int(bootstrap.get("local_restored") or 0)
        and int(bootstrap.get("service_hash_verified") or 0) == int(bootstrap.get("service_restored") or 0)
        and int(bootstrap.get("referenced_file_hash_verified") or 0) == int(bootstrap.get("referenced_files_restored") or 0)
        and not list(bootstrap.get("root_hash_mismatch_keys") or [])
        and not list(bootstrap.get("local_hash_mismatch_keys") or [])
        and not list(bootstrap.get("service_hash_mismatch_keys") or [])
        and not list(bootstrap.get("referenced_file_hash_mismatch_paths") or [])
    )
    if _is_default_recovery_output(root_env_path, effective_local_env_path, service_env_path):
        verification = verify_recovery_table(
            base_url=base_url,
            api_key=api_key,
            table_id=table_id,
            env_files=(root_env_path, effective_local_env_path, service_env_path),
            host_profile=host_profile,
        )
    else:
        verification = verify_restored_outputs_from_table(
            base_url=base_url,
            api_key=api_key,
            table_id=table_id,
            root_env_path=root_env_path,
            local_env_path=effective_local_env_path,
            service_env_path=service_env_path,
            referenced_file_paths=[str(path) for path in bootstrap.get("referenced_file_paths") or []],
            referenced_file_output_root=_recover_referenced_file_output_root(
                root_env_path, effective_local_env_path, service_env_path
            ),
            host_profile=host_profile,
        )
    status = "recovered" if bootstrap_ok and verification.get("status") == "pass" else "failed"
    return {
        "status": status,
        "recovery_proof": build_recovery_proof(
            status=status,
            table_id=table_id,
            host_profile=host_profile,
            root_env_path=root_env_path,
            local_env_path=effective_local_env_path,
            service_env_path=service_env_path,
            bootstrap=bootstrap,
            verification=verification,
        ),
        "bootstrap": bootstrap,
        "verification": verification,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Back up or restore EA environment variables through Teable.")
    parser.add_argument(
        "command",
        choices=(
            "backup",
            "restore",
            "bootstrap",
            "recover",
            "drill",
            "check",
            "disable-extras",
            "verify",
            "local-status",
            "ensure-local",
            "preview-fields",
        ),
    )
    parser.add_argument("--base-url", default=_dotenv_value("TEABLE_BASE_URL") or DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=_dotenv_value("TEABLE_API_KEY"))
    parser.add_argument("--base-id", default=_dotenv_value("EA_ENV_TEABLE_BASE_ID"))
    parser.add_argument("--table-id", default=_dotenv_value("EA_ENV_TEABLE_TABLE_ID"))
    parser.add_argument("--table-name", default=_dotenv_value("EA_ENV_TEABLE_TABLE_NAME") or DEFAULT_TABLE_NAME)
    parser.add_argument("--create-table", action="store_true")
    parser.add_argument("--include-values", action="store_true")
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--secrets-only", action="store_true")
    parser.add_argument("--no-referenced-files", action="store_true")
    parser.add_argument("--host-profile", default=_dotenv_value("EA_ENV_TEABLE_HOST_PROFILE") or "ea-prod")
    parser.add_argument("--env-file", action="append", default=[])
    parser.add_argument("--output-path", default=str(ROOT / ".env"))
    parser.add_argument("--root-output-path", default=str(ROOT / ".env"))
    parser.add_argument("--local-output-path", default=str(ROOT / ".env.local"))
    parser.add_argument("--service-output-path", default=str(ROOT / "ea" / ".env"))
    parser.add_argument("--drill-output-dir", default="")
    parser.add_argument("--source-scope", choices=("ea_root", "ea_root_local", "ea_service"), default="ea_root")
    parser.add_argument("--no-backup-existing", action="store_true")
    parser.add_argument(
        "--require-seeded-api-key",
        action="store_true",
        help="Require TEABLE_API_KEY to be present in the process environment instead of restored local env files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "preview-fields":
        print(json.dumps({"table_name": args.table_name, "fields": ENV_SECRET_FIELDS}, indent=2, ensure_ascii=True))
        return 0
    if args.require_seeded_api_key and not str(os.environ.get("TEABLE_API_KEY") or "").strip():
        raise SystemExit("teable_seeded_api_key_required")
    api_key = str(args.api_key or "").strip()
    if not api_key:
        raise SystemExit("teable_missing_api_key")
    base_url = str(args.base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    table_id = str(args.table_id or "").strip()
    if args.create_table:
        base_id = str(args.base_id or "").strip()
        if not base_id:
            raise SystemExit("teable_base_id_required_to_create_table")
        table_id = create_table(base_url=base_url, api_key=api_key, base_id=base_id, table_name=str(args.table_name))
    if not table_id:
        table_id = discover_table_id(base_url=base_url, api_key=api_key, table_name=str(args.table_name))
    if not table_id:
        raise SystemExit("teable_table_id_missing")

    if args.command == "backup":
        if not args.include_values and not args.metadata_only:
            raise SystemExit("teable_backup_requires_include_values_or_metadata_only")
        env_files = _coerce_env_files_from_args(args.env_file) if args.env_file else DEFAULT_ENV_FILES
        include_values = bool(args.include_values and not args.metadata_only)
        rows = build_recovery_rows(
            env_files=env_files,
            include_values=include_values,
            include_non_secret=not bool(args.secrets_only),
            include_referenced_files=not bool(args.no_referenced_files),
            host_profile=str(args.host_profile or "ea-prod"),
        )
        result = sync_rows(
            base_url=base_url,
            api_key=api_key,
            table_id=table_id,
            rows=rows,
            preserve_blank_secret_values=not include_values,
        )
        result.update({"status": "synced", "table_id": table_id, "secret_values_included": include_values})
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0

    if args.command == "bootstrap":
        result = bootstrap_env_files(
            base_url=base_url,
            api_key=api_key,
            table_id=table_id,
            root_env_path=Path(args.root_output_path),
            local_env_path=Path(args.local_output_path),
            service_env_path=Path(args.service_output_path),
            host_profile=str(args.host_profile or "ea-prod"),
            backup_existing=not bool(args.no_backup_existing),
        )
        result.update({"status": "bootstrapped", "table_id": table_id})
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0

    if args.command == "recover":
        result = recover_from_teable(
            base_url=base_url,
            api_key=api_key,
            table_id=table_id,
            root_env_path=Path(args.root_output_path),
            local_env_path=Path(args.local_output_path),
            service_env_path=Path(args.service_output_path),
            host_profile=str(args.host_profile or "ea-prod"),
            backup_existing=not bool(args.no_backup_existing),
        )
        result.update({"table_id": table_id})
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0 if result.get("status") == "recovered" else 1

    if args.command == "drill":
        drill_output_dir = str(args.drill_output_dir or "").strip()
        result = drill_bootstrap_restore(
            base_url=base_url,
            api_key=api_key,
            table_id=table_id,
            host_profile=str(args.host_profile or "ea-prod"),
            output_dir=Path(drill_output_dir) if drill_output_dir else None,
        )
        result.update({"status": "drilled", "table_id": table_id})
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0

    if args.command == "check":
        env_files = _coerce_env_files_from_args(args.env_file) if args.env_file else DEFAULT_ENV_FILES
        drill_output_dir = str(args.drill_output_dir or "").strip()
        result = check_recovery_ready(
            base_url=base_url,
            api_key=api_key,
            table_id=table_id,
            env_files=env_files,
            host_profile=str(args.host_profile or "ea-prod"),
            drill_output_dir=Path(drill_output_dir) if drill_output_dir else None,
        )
        result.update({"table_id": table_id})
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0 if result.get("status") == "pass" else 1

    if args.command == "disable-extras":
        env_files = _coerce_env_files_from_args(args.env_file) if args.env_file else DEFAULT_ENV_FILES
        result = disable_extra_restorable_rows(
            base_url=base_url,
            api_key=api_key,
            table_id=table_id,
            env_files=env_files,
            host_profile=str(args.host_profile or "ea-prod"),
        )
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0

    if args.command == "verify":
        env_files = _coerce_env_files_from_args(args.env_file) if args.env_file else DEFAULT_ENV_FILES
        result = verify_recovery_table(
            base_url=base_url,
            api_key=api_key,
            table_id=table_id,
            env_files=env_files,
            host_profile=str(args.host_profile or "ea-prod"),
        )
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0 if result.get("status") == "pass" else 1

    if args.command == "local-status":
        result = local_recovery_status(
            base_url=base_url,
            api_key=api_key,
            table_id=table_id,
            root_env_path=Path(args.root_output_path),
            local_env_path=Path(args.local_output_path),
            service_env_path=Path(args.service_output_path),
            host_profile=str(args.host_profile or "ea-prod"),
        )
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0 if result.get("status") == "pass" else 1

    if args.command == "ensure-local":
        result = ensure_local_recovery(
            base_url=base_url,
            api_key=api_key,
            table_id=table_id,
            root_env_path=Path(args.root_output_path),
            local_env_path=Path(args.local_output_path),
            service_env_path=Path(args.service_output_path),
            host_profile=str(args.host_profile or "ea-prod"),
            backup_existing=not bool(args.no_backup_existing),
        )
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0 if result.get("status") == "ensured" else 1

    result = restore_env_file(
        base_url=base_url,
        api_key=api_key,
        table_id=table_id,
        output_path=Path(args.output_path),
        source_scope=str(args.source_scope),
        host_profile=str(args.host_profile or "ea-prod"),
        backup_existing=not bool(args.no_backup_existing),
    )
    result.update({"status": "restored", "table_id": table_id, "output_path": str(args.output_path)})
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
