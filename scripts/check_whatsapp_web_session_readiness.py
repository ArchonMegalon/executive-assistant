#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
for path in (ROOT / "ea", ROOT, SCRIPT_DIR):
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.whatsapp_web_session_readiness import check_whatsapp_web_session_readiness  # noqa: E402


DEFAULT_PRINCIPAL_ENV_NAMES = (
    "EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID",
    "EA_WHATSAPP_DEFAULT_PRINCIPAL_ID",
    "EA_DEFAULT_PRINCIPAL_ID",
)


def _repo_env_value(name: str) -> str:
    normalized_name = str(name or "").strip()
    if not normalized_name:
        return ""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return ""
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != normalized_name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value.strip()
    return ""


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or _repo_env_value(name) or default).strip()


def _first_env(names: tuple[str, ...]) -> str:
    for name in names:
        value = _env(name)
        if value:
            return value
    return ""


def _default_principal_id() -> str:
    return _first_env(DEFAULT_PRINCIPAL_ENV_NAMES) or "principal-default"


def _load_json_file(path: str) -> object:
    raw = Path(path).read_text(encoding="utf-8")
    return json.loads(raw or "{}")


def _dictish(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _binding_from_json(value: object, *, binding_id: str = "") -> SimpleNamespace | None:
    if isinstance(value, dict) and isinstance(value.get("bindings"), list):
        return _binding_from_json(value["bindings"], binding_id=binding_id)
    if isinstance(value, list):
        candidates = [item for item in value if isinstance(item, dict)]
        if binding_id:
            candidates = [item for item in candidates if str(item.get("binding_id") or "").strip() == binding_id]
        else:
            candidates = [
                item
                for item in candidates
                if str(item.get("connector_name") or "").strip() == "whatsapp_web_session"
            ]
        if not candidates:
            return None
        value = candidates[0]
    if not isinstance(value, dict):
        return None
    return SimpleNamespace(
        binding_id=str(value.get("binding_id") or "").strip(),
        principal_id=str(value.get("principal_id") or "").strip(),
        connector_name=str(value.get("connector_name") or "").strip(),
        external_account_ref=str(value.get("external_account_ref") or "").strip(),
        scope_json=dict(value.get("scope_json") or value.get("scope") or {}),
        auth_metadata_json=dict(value.get("auth_metadata_json") or value.get("auth_metadata") or {}),
        status=str(value.get("status") or "").strip(),
        created_at=str(value.get("created_at") or "").strip(),
        updated_at=str(value.get("updated_at") or "").strip(),
    )


def _binding_from_row(row: object) -> SimpleNamespace | None:
    if row is None:
        return None
    values = tuple(row)
    if len(values) < 9:
        return None
    return SimpleNamespace(
        binding_id=str(values[0] or "").strip(),
        principal_id=str(values[1] or "").strip(),
        connector_name=str(values[2] or "").strip(),
        external_account_ref=str(values[3] or "").strip(),
        scope_json=_dictish(values[4]),
        auth_metadata_json=_dictish(values[5]),
        status=str(values[6] or "").strip(),
        created_at=str(values[7] or "").strip(),
        updated_at=str(values[8] or "").strip(),
    )


def _should_fallback_to_latest_binding(*, binding_id: str = "", principal_id: str = "") -> bool:
    normalized_binding_id = str(binding_id or "").strip()
    normalized_principal_id = str(principal_id or "").strip()
    return normalized_binding_id in {"", "ea-whatsapp-web-session"} and normalized_principal_id in {"", "principal-default"}


def _latest_enabled_binding_from_json(value: object) -> SimpleNamespace | None:
    if isinstance(value, dict) and isinstance(value.get("bindings"), list):
        return _latest_enabled_binding_from_json(value["bindings"])
    if not isinstance(value, list):
        return None
    candidates = [
        item
        for item in value
        if isinstance(item, dict) and str(item.get("connector_name") or "").strip() == "whatsapp_web_session"
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            0 if str(item.get("status") or "").strip() == "enabled" else 1,
            str(item.get("updated_at") or "").strip(),
            str(item.get("binding_id") or "").strip(),
        ),
        reverse=False,
    )
    return _binding_from_json(candidates[0])


def _binding_from_postgres(database_url: str, *, binding_id: str = "", principal_id: str = "") -> SimpleNamespace | None:
    try:
        import psycopg
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("psycopg_required") from exc

    normalized_binding_id = str(binding_id or "").strip()
    normalized_principal_id = str(principal_id or "").strip()
    select_columns = """
        binding_id,
        principal_id,
        connector_name,
        external_account_ref,
        scope_json,
        auth_metadata_json,
        status,
        created_at::text,
        updated_at::text
    """
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            if normalized_binding_id:
                cur.execute(
                    f"""
                    SELECT {select_columns}
                    FROM connector_bindings
                    WHERE binding_id = %s
                    LIMIT 1
                    """,
                    (normalized_binding_id,),
                )
            elif normalized_principal_id:
                cur.execute(
                    f"""
                    SELECT {select_columns}
                    FROM connector_bindings
                    WHERE principal_id = %s
                      AND connector_name = 'whatsapp_web_session'
                    ORDER BY
                        CASE WHEN status = 'enabled' THEN 0 ELSE 1 END,
                        updated_at DESC
                    LIMIT 1
                    """,
                    (normalized_principal_id,),
                )
            else:
                cur.execute(
                    f"""
                    SELECT {select_columns}
                    FROM connector_bindings
                    WHERE connector_name = 'whatsapp_web_session'
                    ORDER BY
                        CASE WHEN status = 'enabled' THEN 0 ELSE 1 END,
                        updated_at DESC
                    LIMIT 1
                    """
                )
                return _binding_from_row(cur.fetchone())
            binding = _binding_from_row(cur.fetchone())
            if binding is not None:
                return binding
            if _should_fallback_to_latest_binding(binding_id=normalized_binding_id, principal_id=normalized_principal_id):
                cur.execute(
                    f"""
                    SELECT {select_columns}
                    FROM connector_bindings
                    WHERE connector_name = 'whatsapp_web_session'
                    ORDER BY
                        CASE WHEN status = 'enabled' THEN 0 ELSE 1 END,
                        updated_at DESC
                    LIMIT 1
                    """
                )
                return _binding_from_row(cur.fetchone())
            return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check an EA WhatsApp Web session binding for send readiness.")
    parser.add_argument("--binding-json", default=_env("EA_WHATSAPP_WEB_READINESS_BINDING_JSON"))
    parser.add_argument("--database-url", default=_env("DATABASE_URL"))
    parser.add_argument("--binding-id", default=_env("EA_WHATSAPP_WEB_DEFAULT_BINDING_ID", "ea-whatsapp-web-session"))
    parser.add_argument("--principal-id", default=_default_principal_id())
    parser.add_argument("--probe-session", action="store_true")
    return parser.parse_args()


def build_report(args: argparse.Namespace) -> dict[str, object]:
    binding_path = str(args.binding_json or "").strip()
    database_url = str(getattr(args, "database_url", "") or "").strip()
    binding_id = str(args.binding_id or "").strip()
    principal_id = str(args.principal_id or "").strip()
    if binding_path:
        path = Path(binding_path)
        if not path.exists():
            return {
                "ready": False,
                "reason": "binding_json_not_found",
                "binding_id": binding_id,
                "principal_id": principal_id,
            }
        try:
            payload = _load_json_file(str(path))
        except Exception:
            return {
                "ready": False,
                "reason": "binding_json_invalid",
                "binding_id": binding_id,
                "principal_id": principal_id,
            }
        binding = _binding_from_json(payload, binding_id=binding_id)
        if binding is None and _should_fallback_to_latest_binding(binding_id=binding_id, principal_id=principal_id):
            binding = _latest_enabled_binding_from_json(payload)
    elif database_url:
        try:
            binding = _binding_from_postgres(database_url, binding_id=binding_id, principal_id=principal_id)
        except Exception as exc:
            return {
                "ready": False,
                "reason": "database_lookup_failed",
                "error_type": type(exc).__name__,
                "binding_id": binding_id,
                "principal_id": principal_id,
            }
    else:
        return {
            "ready": False,
            "reason": "binding_json_or_database_url_required",
            "binding_id": binding_id,
            "principal_id": principal_id,
        }
    if binding is None:
        return {
            "ready": False,
            "reason": "binding_not_found",
            "binding_id": binding_id,
            "principal_id": principal_id,
        }
    effective_binding_id = str(getattr(binding, "binding_id", "") or binding_id).strip()
    effective_principal_id = str(getattr(binding, "principal_id", "") or principal_id).strip()
    readiness = check_whatsapp_web_session_readiness(
        tool_runtime=None,
        principal_id=effective_principal_id,
        binding_id=effective_binding_id,
        binding=binding,
        probe_session=bool(args.probe_session),
    )
    return readiness.as_dict()


def main() -> int:
    args = parse_args()
    report = build_report(args)
    print(json.dumps(report, sort_keys=True))
    return 0 if bool(report.get("ready")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
