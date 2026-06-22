#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from scripts.source_state_head import resolve_source_state_head
except ModuleNotFoundError:  # pragma: no cover - script execution path
    from source_state_head import resolve_source_state_head


ROOT = Path(__file__).resolve().parents[1]
EA_PATH = ROOT / "ea"
for candidate in (ROOT, EA_PATH):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.domain.models import ObservationEvent  # noqa: E402
from app.services.channel_runtime import build_channel_runtime  # noqa: E402
from app.settings import get_settings  # noqa: E402


DEFAULT_OUTPUT = ROOT / ".codex-studio/published/telegram_video_delivery_live.generated.json"
EVENT_TYPE = "telegram.video_delivery_receipt"
RECEIPT_TYPE = "telegram_video_delivery"
TRUSTED_SOURCE_HOSTS = {"api.telegram.org"}
DEFAULT_RUNTIME_ENV_FILES = (ROOT / ".env", ROOT / ".env.local")
DEFAULT_DOCKER_POSTGRES_CONTAINERS = ("ea-db",)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256_text(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _parse_env_value(raw: str) -> str:
    value = str(raw or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_runtime_env_files(paths: tuple[Path, ...]) -> dict[str, object]:
    loaded_files: list[str] = []
    loaded_count = 0
    for path in paths:
        candidate = path if path.is_absolute() else ROOT / path
        if not candidate.exists():
            continue
        try:
            loaded_files.append(candidate.relative_to(ROOT).as_posix())
        except ValueError:
            loaded_files.append("[external_path]")
        try:
            lines = candidate.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line.removeprefix("export ").strip()
            name, raw_value = line.split("=", 1)
            name = name.strip()
            if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name):
                continue
            if os.environ.get(name):
                continue
            value = _parse_env_value(raw_value)
            if not value:
                continue
            os.environ[name] = value
            loaded_count += 1
    return {
        "files": loaded_files,
        "loaded_count": loaded_count,
        "storage_backend_present": bool(os.environ.get("EA_STORAGE_BACKEND")),
        "database_url_present": bool(os.environ.get("DATABASE_URL")),
    }


def _list_strings(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    normalized = str(value or "").strip()
    return [normalized] if normalized else []


def _observation_from_dict(raw: dict[str, Any]) -> ObservationEvent:
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        payload = raw.get("payload_json")
    return ObservationEvent(
        observation_id=str(raw.get("observation_id") or raw.get("id") or "").strip(),
        principal_id=str(raw.get("principal_id") or "").strip(),
        channel=str(raw.get("channel") or "").strip(),
        event_type=str(raw.get("event_type") or "").strip(),
        payload=dict(payload or {}),
        created_at=str(raw.get("created_at") or "").strip(),
        source_id=str(raw.get("source_id") or "").strip(),
        external_id=str(raw.get("external_id") or "").strip(),
        dedupe_key=str(raw.get("dedupe_key") or "").strip(),
        auth_context_json=dict(raw.get("auth_context_json") or {}),
        raw_payload_uri=str(raw.get("raw_payload_uri") or "").strip(),
    )


def _normalize_observation(value: ObservationEvent | dict[str, Any]) -> ObservationEvent:
    if isinstance(value, ObservationEvent):
        return value
    return _observation_from_dict(dict(value or {}))


def _load_observations_json(path: Path) -> list[ObservationEvent]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        rows = payload.get("observations") or payload.get("events") or []
    else:
        rows = payload
    if not isinstance(rows, list):
        return []
    return [_normalize_observation(row) for row in rows if isinstance(row, dict)]


def _runtime_observations(*, limit: int, principal_id: str = "") -> list[ObservationEvent]:
    runtime = build_channel_runtime(settings=get_settings())
    return runtime.list_recent_observations(limit=limit, principal_id=principal_id or None)


def _sql_literal(value: object) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _telegram_delivery_sql(*, limit: int, principal_id: str = "") -> str:
    capped_limit = max(1, min(5000, int(limit or 100)))
    where = [f"event_type = {_sql_literal(EVENT_TYPE)}"]
    normalized_principal = str(principal_id or "").strip()
    if normalized_principal:
        where.append(f"principal_id = {_sql_literal(normalized_principal)}")
    return f"""
SELECT json_build_object(
  'observation_id', observation_id,
  'principal_id', principal_id,
  'channel', channel,
  'event_type', event_type,
  'payload', payload_json,
  'created_at', created_at::text,
  'source_id', source_id,
  'external_id', external_id,
  'dedupe_key', dedupe_key,
  'auth_context_json', auth_context_json,
  'raw_payload_uri', raw_payload_uri
)::text
FROM observation_events
WHERE {' AND '.join(where)}
ORDER BY created_at DESC, observation_id DESC
LIMIT {capped_limit}
"""


def _principal_where_clause(principal_id: str = "") -> str:
    normalized_principal = str(principal_id or "").strip()
    if not normalized_principal:
        return ""
    return f" AND principal_id = {_sql_literal(normalized_principal)}"


def _docker_psql_lines(container_name: str, sql: str, *, timeout: int = 20) -> tuple[list[str], str]:
    proc = subprocess.run(
        [
            "docker",
            "exec",
            "-e",
            f"EA_LIVE_SQL={sql}",
            container_name,
            "sh",
            "-lc",
            'psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-${POSTGRES_USER:-postgres}}" -tA -c "$EA_LIVE_SQL"',
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        return [], f"exit_{proc.returncode}:{(proc.stderr or proc.stdout or '')[:160]}"
    return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()], ""


def _first_int(lines: list[str]) -> int:
    if not lines:
        return 0
    try:
        return max(int(str(lines[0]).strip() or "0"), 0)
    except ValueError:
        return 0


def _parse_pipe_count_rows(lines: list[str], *field_names: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in lines:
        parts = str(line or "").split("|")
        if len(parts) != len(field_names) + 1:
            continue
        try:
            count = max(int(parts[-1] or "0"), 0)
        except ValueError:
            continue
        row: dict[str, object] = {field: parts[index] for index, field in enumerate(field_names)}
        row["count"] = count
        rows.append(row)
    return rows


def _docker_postgres_diagnostics(container_name: str, *, principal_id: str = "") -> dict[str, object]:
    principal_where = _principal_where_clause(principal_id)
    diagnostics: dict[str, object] = {"status": "pass"}
    queries: dict[str, str] = {
        "telegram_observation_count": (
            "select count(*) from observation_events "
            f"where channel = 'telegram'{principal_where};"
        ),
        "telegram_video_related_observation_count": (
            "select count(*) from observation_events "
            f"where channel = 'telegram'{principal_where} "
            "and (event_type ilike '%video%' or payload_json::text ilike '%video%');"
        ),
        "telegram_video_delivery_receipt_count": (
            "select count(*) from observation_events "
            f"where event_type = '{EVENT_TYPE}'{principal_where};"
        ),
        "telegram_video_sent_text_ack_count": (
            "select count(*) from observation_events "
            f"where channel = 'telegram'{principal_where} "
            "and event_type in ('telegram.reply_sent', 'telegram.reply_async_sent') "
            "and lower(payload_json::text) like '%rendered and sent a short video reply%';"
        ),
        "telegram_event_type_counts": (
            "select event_type || '|' || count(*) from observation_events "
            f"where channel = 'telegram'{principal_where} "
            "group by event_type order by count(*) desc, event_type asc limit 20;"
        ),
        "telegram_video_related_event_type_counts": (
            "select event_type || '|' || count(*) from observation_events "
            f"where channel = 'telegram'{principal_where} "
            "and (event_type ilike '%video%' or payload_json::text ilike '%video%') "
            "group by event_type order by count(*) desc, event_type asc limit 20;"
        ),
        "delivery_outbox_table": "select coalesce(to_regclass('public.delivery_outbox')::text, '');",
    }
    errors: dict[str, str] = {}
    for key, sql in queries.items():
        lines, error = _docker_psql_lines(container_name, sql)
        if error:
            errors[key] = error
            continue
        if key.endswith("_counts"):
            diagnostics[key] = _parse_pipe_count_rows(lines, "event_type")
        elif key == "delivery_outbox_table":
            diagnostics[key] = bool(lines and lines[0] == "delivery_outbox")
        else:
            diagnostics[key] = _first_int(lines)

    if diagnostics.get("delivery_outbox_table") is True:
        for key, sql in {
            "delivery_outbox_channel_status_counts": (
                "select channel || '|' || status || '|' || count(*) from delivery_outbox "
                "group by channel, status order by count(*) desc, channel asc, status asc limit 20;"
            ),
            "telegram_delivery_outbox_video_count": (
                "select count(*) from delivery_outbox "
                "where channel = 'telegram' "
                "and (content::text ilike '%video%' or metadata_json::text ilike '%video%' or receipt_json::text ilike '%video%');"
            ),
        }.items():
            lines, error = _docker_psql_lines(container_name, sql)
            if error:
                errors[key] = error
                continue
            if key.endswith("_counts"):
                diagnostics[key] = _parse_pipe_count_rows(lines, "channel", "status")
            else:
                diagnostics[key] = _first_int(lines)

    if errors:
        diagnostics["status"] = "partial"
        diagnostics["errors"] = errors
    telegram_count = int(diagnostics.get("telegram_observation_count") or 0)
    video_related_count = int(diagnostics.get("telegram_video_related_observation_count") or 0)
    delivery_receipt_count = int(diagnostics.get("telegram_video_delivery_receipt_count") or 0)
    video_sent_text_ack_count = int(diagnostics.get("telegram_video_sent_text_ack_count") or 0)
    outbox_video_count = int(diagnostics.get("telegram_delivery_outbox_video_count") or 0)
    if delivery_receipt_count > 0:
        interpretation = "video_delivery_receipts_present_but_no_valid_sent_receipt"
    elif video_sent_text_ack_count > 0:
        interpretation = "telegram_video_sent_text_ack_without_delivery_receipt"
    elif outbox_video_count > 0:
        interpretation = "telegram_video_outbox_present_without_live_delivery_receipt"
    elif video_related_count > 0:
        interpretation = "telegram_video_related_turns_seen_without_delivery_receipt"
    elif telegram_count > 0:
        interpretation = "telegram_activity_seen_without_video_delivery_request"
    else:
        interpretation = "no_telegram_activity_seen"
    diagnostics["interpretation"] = interpretation
    diagnostics["privacy"] = {
        "raw_payloads_included": False,
        "raw_message_text_included": False,
        "raw_chat_ids_included": False,
        "raw_message_ids_included": False,
    }
    return diagnostics


def _docker_container_candidates() -> tuple[str, ...]:
    raw = str(os.environ.get("EA_TELEGRAM_LIVE_RECEIPT_POSTGRES_CONTAINERS") or "").strip()
    values = [item.strip() for item in raw.split(",") if item.strip()] if raw else list(DEFAULT_DOCKER_POSTGRES_CONTAINERS)
    return tuple(dict.fromkeys(values))


def _docker_postgres_observations(*, limit: int, principal_id: str = "") -> tuple[list[ObservationEvent], dict[str, object], str]:
    metadata: dict[str, object] = {
        "attempted": True,
        "containers": [],
        "selected_container": "",
        "status": "not_attempted",
    }
    sql = _telegram_delivery_sql(limit=limit, principal_id=principal_id)
    errors: list[str] = []
    for container in _docker_container_candidates():
        container_name = str(container or "").strip()
        if not container_name:
            continue
        containers = list(metadata.get("containers") or [])
        containers.append(container_name)
        metadata["containers"] = containers
        lines, error = _docker_psql_lines(container_name, sql)
        if error:
            errors.append(f"{container_name}:{error}")
            continue
        rows: list[ObservationEvent] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except Exception:
                continue
            if isinstance(parsed, dict):
                rows.append(_normalize_observation(parsed))
        metadata["selected_container"] = container_name
        metadata["status"] = "pass"
        metadata["row_count"] = len(rows)
        metadata["diagnostics"] = _docker_postgres_diagnostics(container_name, principal_id=principal_id)
        return rows, metadata, ""
    metadata["status"] = "blocked"
    return [], metadata, "; ".join(errors) or "docker_postgres_query_failed"


def _source_video_context(payload: dict[str, Any]) -> dict[str, Any]:
    source_video = payload.get("source_video")
    if not isinstance(source_video, dict):
        return {}
    allowed_keys = {
        "has_source_video",
        "source_url_raw_stored",
        "source_url_sha256",
        "source_host",
        "source_path_redacted",
        "source_video_duration_seconds",
        "source_video_reference_board_present",
        "source_video_reference_frame_count",
    }
    return {key: source_video.get(key) for key in sorted(allowed_keys) if key in source_video}


def _validate_source_video_context(source_video: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if source_video.get("has_source_video") is not True:
        failures.append("source_video_missing")
    if source_video.get("source_url_raw_stored") is not False:
        failures.append("source_url_not_redacted")
    if not str(source_video.get("source_url_sha256") or "").strip():
        failures.append("source_url_hash_missing")
    host = str(source_video.get("source_host") or "").strip().lower()
    if host not in TRUSTED_SOURCE_HOSTS:
        failures.append("source_host_not_trusted")
    redacted_path = str(source_video.get("source_path_redacted") or "")
    if not redacted_path.strip():
        failures.append("source_path_redacted_missing")
    redacted_lower = redacted_path.lower()
    if ":" in redacted_path or "secret" in redacted_lower or "token" in redacted_lower:
        failures.append("source_path_redaction_failed")
    if "/bot" in redacted_lower and "bot<redacted>" not in redacted_lower:
        failures.append("telegram_bot_token_not_redacted")
    return failures


def _validate_observation(event: ObservationEvent) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if str(event.channel or "").strip().lower() != "telegram":
        failures.append("channel_not_telegram")
    if str(event.event_type or "").strip() != EVENT_TYPE:
        failures.append("event_type_mismatch")
    payload = dict(event.payload or {})
    if str(payload.get("receipt_type") or "").strip() != RECEIPT_TYPE:
        failures.append("receipt_type_mismatch")
    if str(payload.get("status") or "").strip().lower() != "sent":
        failures.append("delivery_not_sent")
    if str(payload.get("delivery_kind") or "").strip().lower() != "video":
        failures.append("delivery_kind_not_video")
    if str(payload.get("telegram_method") or "").strip() != "sendVideo":
        failures.append("telegram_method_not_send_video")
    if not _list_strings(payload.get("message_ids")):
        failures.append("message_ids_missing")
    if not str(payload.get("provider") or "").strip():
        failures.append("provider_missing")
    if not str(event.observation_id or "").strip():
        failures.append("observation_id_missing")
    if not str(event.created_at or "").strip():
        failures.append("created_at_missing")
    failures.extend(_validate_source_video_context(_source_video_context(payload)))
    return not failures, list(dict.fromkeys(failures))


def _selected_observation_payload(event: ObservationEvent) -> dict[str, Any]:
    payload = dict(event.payload or {})
    chat_id = payload.get("chat_id")
    source_message_id = payload.get("source_message_id") or event.external_id
    sent_message_ids = _list_strings(payload.get("message_ids"))
    return {
        "observation_id": str(event.observation_id or "").strip(),
        "principal_id_sha256": _sha256_text(event.principal_id),
        "channel": str(event.channel or "").strip(),
        "event_type": str(event.event_type or "").strip(),
        "created_at": str(event.created_at or "").strip(),
        "source_id_sha256": _sha256_text(event.source_id),
        "source_message_id_sha256": _sha256_text(source_message_id),
        "dedupe_key_sha256": _sha256_text(event.dedupe_key),
        "chat_id_present": bool(str(chat_id or "").strip()),
        "chat_id_sha256": _sha256_text(chat_id),
        "provider": str(payload.get("provider") or "").strip(),
        "delivery_kind": str(payload.get("delivery_kind") or "").strip(),
        "telegram_method": str(payload.get("telegram_method") or "").strip(),
        "status": str(payload.get("status") or "").strip(),
        "sent_message_ids": sent_message_ids,
        "sent_message_count": len(sent_message_ids),
        "source_video": _source_video_context(payload),
    }


def _candidate_summary(event: ObservationEvent, failures: list[str]) -> dict[str, Any]:
    payload = dict(event.payload or {})
    return {
        "observation_id": str(event.observation_id or "").strip(),
        "created_at": str(event.created_at or "").strip(),
        "event_type": str(event.event_type or "").strip(),
        "status": str(payload.get("status") or "").strip(),
        "provider": str(payload.get("provider") or "").strip(),
        "failed_codes": failures,
    }


def _live_receipt_next_action(*, failed_codes: list[str], selected: ObservationEvent | None) -> str:
    codes = set(failed_codes)
    if selected is not None and not codes:
        return ""
    if "observation_load_failed" in codes:
        return "fix_live_observation_source_then_rerun_receipt"
    if "video_sent_text_ack_without_delivery_receipt" in codes:
        return "fix_runtime_to_record_sendVideo_delivery_receipt_before_claiming_video_sent"
    if "valid_sent_video_observation_missing" in codes:
        return "inspect_failed_delivery_candidates_and_fix_sendVideo_receipt_fields"
    if "live_observation_missing" in codes:
        return "trigger_real_telegram_video_edit_request_and_wait_for_sendVideo_receipt"
    return "rerun_live_telegram_video_delivery_probe"


def build_receipt(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    observations: list[ObservationEvent | dict[str, Any]] | None = None,
    observation_source: str = "runtime",
    principal_id: str = "",
    limit: int = 100,
    generated_at: str | None = None,
    load_error: str = "",
    runtime_env: dict[str, object] | None = None,
) -> dict[str, Any]:
    rows = [_normalize_observation(row) for row in list(observations or [])]
    candidates = [
        event
        for event in rows
        if str(event.event_type or "").strip() == EVENT_TYPE
        or str(dict(event.payload or {}).get("receipt_type") or "").strip() == RECEIPT_TYPE
    ]
    selected: ObservationEvent | None = None
    failed_candidates: list[dict[str, Any]] = []
    for event in candidates:
        ok, failures = _validate_observation(event)
        if ok and selected is None:
            selected = event
            continue
        failed_candidates.append(_candidate_summary(event, failures))

    failed_codes: list[str] = []
    if load_error:
        failed_codes.append("observation_load_failed")
    if not candidates and not load_error:
        failed_codes.append("live_observation_missing")
    if candidates and selected is None:
        failed_codes.append("valid_sent_video_observation_missing")
    diagnostics = dict(dict(dict(runtime_env or {}).get("docker_postgres_fallback") or {}).get("diagnostics") or {})
    if int(diagnostics.get("telegram_video_sent_text_ack_count") or 0) > 0 and selected is None:
        failed_codes.append("video_sent_text_ack_without_delivery_receipt")
    status = "pass" if selected is not None and not load_error else "blocked"
    unique_failed_codes = list(dict.fromkeys(failed_codes))
    payload: dict[str, Any] = {
        "contract_name": "ea.telegram_video_delivery_live_receipt",
        "generated_at": generated_at or _utc_now(),
        "generated_by": "scripts/materialize_telegram_video_delivery_live_receipt.py",
        "source_git_head": resolve_source_state_head(ROOT),
        "head_semantics": "source_state",
        "output_path": _display_path(output_path),
        "status": status,
        "gold_claim_allowed": status == "pass",
        "claim": "Telegram video delivery has live operator proof only when a real Telegram delivery observation records status=sent, sent message IDs, and a privacy-redacted source-video context.",
        "observation_source": observation_source,
        "runtime_env": dict(runtime_env or {}),
        "principal_id_filter_sha256": _sha256_text(principal_id),
        "limit": max(1, min(5000, int(limit or 100))),
        "delivery_observation_event_type": EVENT_TYPE,
        "required_receipt_type": RECEIPT_TYPE,
        "required_status": "sent",
        "delivery_observation_requirements": {
            "channel": "telegram",
            "event_type": EVENT_TYPE,
            "receipt_type": RECEIPT_TYPE,
            "status": "sent",
            "delivery_kind": "video",
            "telegram_method": "sendVideo",
            "message_ids_required": True,
            "source_video_context_required": True,
        },
        "privacy": {
            "raw_chat_id_stored": False,
            "raw_source_message_id_stored": False,
            "raw_source_video_url_stored": False,
            "source_video_context_requires_redacted_path": True,
        },
        "candidate_count": len(candidates),
        "selected_observation": _selected_observation_payload(selected) if selected is not None else None,
        "failed_candidate_count": len(failed_candidates),
        "failed_candidates": failed_candidates[:20],
        "failed_codes": unique_failed_codes,
        "next_action": _live_receipt_next_action(failed_codes=unique_failed_codes, selected=selected),
        "blocking_reason": "" if status == "pass" else (load_error or ", ".join(unique_failed_codes)),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the live Telegram video delivery receipt.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--observations-json", type=Path)
    parser.add_argument("--env-file", action="append", type=Path, default=None)
    parser.add_argument("--no-local-env", action="store_true")
    parser.add_argument("--principal-id", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()

    load_error = ""
    source = "runtime"
    runtime_env = {"files": [], "loaded_count": 0, "storage_backend_present": False, "database_url_present": False}
    try:
        if not bool(args.no_local_env):
            runtime_env = _load_runtime_env_files(tuple(args.env_file or DEFAULT_RUNTIME_ENV_FILES))
        if args.observations_json:
            observations = _load_observations_json(args.observations_json)
            source = f"observations_json:{args.observations_json.as_posix()}"
        else:
            try:
                observations = _runtime_observations(limit=args.limit, principal_id=args.principal_id)
            except Exception as runtime_exc:
                docker_rows, docker_metadata, docker_error = _docker_postgres_observations(
                    limit=args.limit,
                    principal_id=args.principal_id,
                )
                runtime_env["docker_postgres_fallback"] = docker_metadata
                if not docker_error:
                    observations = docker_rows
                    source = f"docker_postgres:{docker_metadata.get('selected_container') or 'unknown'}"
                else:
                    observations = []
                    load_error = f"{type(runtime_exc).__name__}: {runtime_exc}; docker_fallback: {docker_error}"
    except Exception as exc:
        observations = []
        load_error = f"{type(exc).__name__}: {exc}"

    receipt = build_receipt(
        output_path=args.output,
        observations=observations,
        observation_source=source,
        principal_id=args.principal_id,
        limit=args.limit,
        load_error=load_error,
        runtime_env=runtime_env,
    )
    print(json.dumps({"status": receipt["status"], "output": args.output.as_posix()}))
    if args.require_pass and receipt["status"] != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
