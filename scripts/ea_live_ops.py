#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
EA_ROOT = ROOT / "ea"
SCRIPT_DIR = ROOT / "scripts"
for path in (EA_ROOT, ROOT, SCRIPT_DIR):
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _load_dotenv_if_present(path: Path) -> None:
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        normalized = value.strip()
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"'", '"'}:
            normalized = normalized[1:-1]
        os.environ[key] = normalized


_load_dotenv_if_present(ROOT / ".env")
_load_dotenv_if_present(EA_ROOT / ".env")

import check_whatsapp_web_session_readiness as readiness_script  # noqa: E402
import materialize_google_workspace_oauth_readiness as google_workspace_oauth_readiness  # noqa: E402
import materialize_pushbullet_delivery_readiness as pushbullet_delivery_readiness  # noqa: E402
import materialize_whatsapp_web_action_processor_readiness as whatsapp_action_processor_readiness  # noqa: E402
import verify_pocket_audio_archive as pocket_audio_archive_verifier  # noqa: E402
from app.container import build_container  # noqa: E402
from app.services import whatsapp_web_session_delivery  # noqa: E402
from app.services.audiobook_epub_pipeline import audiobook_runtime_preflight  # noqa: E402
from app.services.proactive_ooda_operator_actions import proactive_next_action_surface  # noqa: E402
from app.services.proactive_ooda_runtime_artifacts import approval_callback_runtime_summary, load_runtime_artifact_bundle  # noqa: E402
from app.services.proactive_ooda_telegram_approval import expire_stale_proactive_ooda_telegram_approval_callbacks  # noqa: E402
from app.services.responses_upstream import _provider_health_report  # noqa: E402
from app.services.telegram_delivery import send_telegram_message_for_principal  # noqa: E402
from app.services.tool_runtime import build_tool_runtime  # noqa: E402
from app.settings import get_settings, settings_with_storage_backend  # noqa: E402
from app.services.tool_execution_browseract_adapter import BrowserActToolAdapter  # noqa: E402


DEFAULT_SESSION_API_BASE_URL = "http://127.0.0.1:8098"
DEFAULT_READINESS_RECEIPT_FILENAME = "whatsapp_web_action_processor_readiness.generated.json"
DEFAULT_READINESS_RECEIPT_PATH = ROOT / ".codex-studio" / "published" / DEFAULT_READINESS_RECEIPT_FILENAME
DEFAULT_GOOGLE_WORKSPACE_OAUTH_READINESS_PATH = Path(
    str(getattr(google_workspace_oauth_readiness, "DEFAULT_OUTPUT", ROOT / ".codex-studio" / "published" / "ea_google_workspace_oauth_readiness.generated.json"))
)
DEFAULT_GOOGLE_WORKSPACE_OAUTH_RECEIPT_MAX_AGE_SECONDS = 7200.0
DEFAULT_RUNTIME_CONTAINER = "ea-api"
DEFAULT_TELEGRAM_READINESS_TIMEOUT_SECONDS = 75.0
DEFAULT_WHATSAPP_WEB_COMPOSE_FILE = ROOT / "docker-compose.whatsapp-web-session.yml"
DEFAULT_WHATSAPP_WEB_ACTION_PROCESSOR_SERVICE = "ea-whatsapp-web-action-processor"
DEFAULT_PROACTIVE_OODA_COMPOSE_FILE = ROOT / "docker-compose.yml"
DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE = "ea-proactive-ooda"
DEFAULT_PROACTIVE_SOURCE_COVERAGE_TIMEOUT_SECONDS = 60.0
DEFAULT_EXPANDED_PROACTIVE_SOURCE_COVERAGE_TIMEOUT_SECONDS = 180.0
DEFAULT_EA_COMPOSE_PROJECT_NAME = "ea"
DEFAULT_MYMEDIA_ALEXA_CONTAINER = "mymediaalexa"
DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL = "http://127.0.0.1:52051"
DEFAULT_MYMEDIA_ALEXA_PUBLIC_BASE_URL = ""
DEFAULT_MYMEDIA_ALEXA_PUBLIC_TUNNEL_ORIGIN_URL = ""
DEFAULT_MYMEDIA_ALEXA_CLOUDFLARE_TUNNEL_NAME = "chummer-run"
DEFAULT_MYMEDIA_ALEXA_CF_ACCESS_ENV_FILE = "/docker/fleet/secrets/codexliz-cf-access.env"
DEFAULT_MYMEDIA_ALEXA_RUNTIME_DEFAULTS_PATH = ROOT / ".state" / "mymedia-alexa" / "runtime-defaults.json"
DEFAULT_MYMEDIA_ALEXA_ACCESS_APP_NAME = "My Media"
DEFAULT_MYMEDIA_ALEXA_ACCESS_EMAILS = ""
DEFAULT_MYMEDIA_ALEXA_CLOUDFLARE_EXCEPTION_BASE_HOSTS = ""
DEFAULT_MYMEDIA_ALEXA_PUBLIC_SURFACE_REPAIR_RECEIPT = (
    ROOT / ".state" / "mymedia-alexa" / "public-console-repair.receipt.json"
)
DEFAULT_MYMEDIA_ALEXA_CONSOLE_API_REPAIR_RECEIPT = (
    ROOT / ".state" / "mymedia-alexa" / "console-api-repair.receipt.json"
)
DEFAULT_MYMEDIA_ALEXA_PAIRING_DIR = ROOT / ".runtime" / "mymedia-amazon-pairing"
DEFAULT_MYMEDIA_ALEXA_SETUP_PATH = "/index.html#!/setup"
DEFAULT_MYMEDIA_ALEXA_AMAZON_OTP_CHANNEL = "whatsapp"
DEFAULT_MYMEDIA_ALEXA_AMAZON_PHONE_SUFFIX = ""
DEFAULT_MYMEDIA_ALEXA_PAIRING_SESSION_MAX_AGE_SECONDS = 1800.0
DEFAULT_SONARR_BASE_URL = "http://127.0.0.1:8989"
DEFAULT_SONARR_CONFIG_PATH = Path("/docker/arr-v2/sonarr/config.xml")
DEFAULT_SONARR_STAGING_ROOT = Path("/mnt/pcloud/staging/downloads")
DEFAULT_SONARR_TV_RECEIPT_DIR = ROOT / ".state" / "sonarr-tv"
DEFAULT_SONARR_METADATA_STALL_AGE_SECONDS = 3600.0
DEFAULT_SONARR_FFPROBE_TIMEOUT_SECONDS = 15.0
DEFAULT_SONARR_QUEUE_REPLACEMENT_MIN_AGE_SECONDS = 300.0
DEFAULT_ONEMIN_OWNER_LEDGER_PATH = ROOT / "config" / "onemin_slot_owners.json"
DEFAULT_ONEMIN_OWNER_LEDGER_LOCAL_PATH = ROOT / "config" / "onemin_slot_owners.local.json"
DEFAULT_ONEMIN_DIRECT_REFRESH_STATE_DIR = ROOT / ".state" / "onemin-direct-refresh"
DEFAULT_ONEMIN_DIRECT_REFRESH_BATCH_SIZE = 1
DEFAULT_ONEMIN_DIRECT_REFRESH_BATCH_BACKOFF_SECONDS = 1.0
DEFAULT_ONEMIN_DIRECT_REFRESH_MAX_RATE_LIMIT_SLEEP_SECONDS = 120.0
OPERATOR_STREAM_OFFICE_LOOP = "office_loop"
OPERATOR_STREAM_OFFICE_SETUP = "office_setup"
OPERATOR_STREAM_RECOVERY = "recovery"
OPERATOR_STREAM_MEDIA_MEMORIAL = "media_memorial"
DEFAULT_TELEGRAM_OPERATOR_STREAMS = (
    OPERATOR_STREAM_OFFICE_LOOP,
    OPERATOR_STREAM_OFFICE_SETUP,
    OPERATOR_STREAM_RECOVERY,
)

MYMEDIA_WATCHFOLDER_STATUS_LABELS: dict[int, str] = {
    0: "queued",
    1: "scanning",
    2: "serving",
    3: "error",
    4: "indexing",
}
MYMEDIA_CONNECTION_STATUS_LABELS: dict[int, str] = {
    0: "not_connected",
    1: "connecting",
    2: "connected",
}
MYMEDIA_ALLOW_EXTERNAL_ACCESS_LABELS: dict[str, str] = {
    "0": "disabled",
    "1": "static_ip",
    "2": "push",
}

PROACTIVE_SOURCE_COVERAGE_LANES: tuple[dict[str, object], ...] = (
    {
        "key": "postgres_observations",
        "label": "Postgres observations",
        "next_action": "verify_postgres_observation_source",
    },
    {
        "key": "google_workspace",
        "label": "Google workspace",
        "next_action": "reauthorize_or_sync_google_workspace_sources",
    },
    {
        "key": "pocket_ai_audio_transcripts",
        "label": "Pocket.ai audio transcripts",
        "next_action": "sync_pocket_ai_audio_transcripts",
        "required_event_types": ("pocket_recording_archive_indexed",),
    },
    {
        "key": "calendar_and_renewal_signals",
        "label": "Calendar and renewal signals",
        "next_action": "sync_calendar_and_renewal_sources",
    },
    {
        "key": "relationship_and_occasion_signals",
        "label": "Relationship and occasion signals",
        "next_action": "refresh_relationship_and_occasion_sources",
    },
    {
        "key": "shopping_and_vendor_signals",
        "label": "Shopping and vendor signals",
        "next_action": "sync_shopping_and_vendor_sources",
    },
    {
        "key": "commitment_and_deadline_signals",
        "label": "Commitment and deadline signals",
        "next_action": "sync_commitment_and_deadline_sources",
    },
    {
        "key": "durable_profile_and_location_context",
        "label": "Durable profile and location context",
        "next_action": "refresh_principal_profile_context",
    },
)


def _telegram_readiness_timeout_seconds(timeout_seconds: float | None = None) -> float:
    if timeout_seconds is not None:
        try:
            return max(float(timeout_seconds), 5.0)
        except (TypeError, ValueError):
            pass
    try:
        return max(
            float(_env("EA_TELEGRAM_READINESS_TIMEOUT_SECONDS", str(DEFAULT_TELEGRAM_READINESS_TIMEOUT_SECONDS))),
            5.0,
        )
    except ValueError:
        return DEFAULT_TELEGRAM_READINESS_TIMEOUT_SECONDS


def _telegram_dry_run_timeout_seconds(timeout_seconds: float | None = None) -> float:
    try:
        return max(float(timeout_seconds or 30.0), 30.0)
    except (TypeError, ValueError):
        return 30.0
PROACTIVE_SOURCE_COVERAGE_LANE_KEYS = tuple(row["key"] for row in PROACTIVE_SOURCE_COVERAGE_LANES)


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


OPERATOR_READINESS_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
OPERATOR_READINESS_SCRIPT_SUFFIXES = (".py", ".sh", ".ps1", ".bash", ".zsh", ".rb", ".js", ".cjs", ".mjs", ".ts")
OPERATOR_READINESS_REASON_PREFIXES = {
    "pushbullet_client_missing",
    "pushbullet_token_missing",
}


def _operator_readiness_public_reason(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    public_parts: list[str] = []
    for raw_part in text.split(","):
        part = str(raw_part or "").strip()
        if not part:
            continue
        prefix, separator, _suffix = part.partition(":")
        if separator and prefix in OPERATOR_READINESS_REASON_PREFIXES:
            part = prefix
        public_parts.append(part)
    return ",".join(public_parts)


def _operator_readiness_redact_local_path(path: str) -> str:
    parts = str(path or "").split("/")
    if len(parts) == 4 and parts[1] == "sessions" and parts[3] == "pair":
        parts[2] = "redacted"
    return "/".join(parts)


def _operator_readiness_looks_like_windows_absolute_path(text: str) -> bool:
    raw = str(text or "").strip()
    return (
        len(raw) >= 3
        and raw[0].isalpha()
        and raw[1] == ":"
        and raw[2] in {"/", "\\"}
    ) or raw.startswith("\\\\")


def _operator_readiness_local_source_label(path_text: str) -> str:
    normalized = str(path_text or "").replace("\\", "/").rstrip("/")
    if not normalized:
        return "host-local-file:redacted"
    basename = normalized.split("/")[-1]
    lowered = basename.lower()
    if lowered.endswith(OPERATOR_READINESS_SCRIPT_SUFFIXES):
        return f"script:{basename}"
    if basename:
        return f"host-local-file:{basename}"
    return "host-local-file:redacted"


def _operator_readiness_script_source_label(text: str) -> str:
    raw = str(text or "").strip()
    lowered = raw.lower()
    for suffix in OPERATOR_READINESS_SCRIPT_SUFFIXES:
        if not lowered.endswith(suffix):
            continue
        trimmed = raw[: -len(suffix)]
        token = trimmed.replace("\\", "/").split("/")[-1].split(".")[-1].strip()
        if token:
            return f"script:{token}{suffix}"
    return ""


def _operator_readiness_public_href(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    host = (parsed.hostname or "").strip().lower()
    if parsed.scheme in {"http", "https"} and host in OPERATOR_READINESS_LOOPBACK_HOSTS:
        sanitized_path = _operator_readiness_redact_local_path(parsed.path or "/")
        fragment = f"#{parsed.fragment}" if parsed.fragment else ""
        return f"host-local://{sanitized_path}{fragment}"
    if parsed.scheme == "host-local":
        sanitized_path = _operator_readiness_redact_local_path(parsed.path or "/")
        fragment = f"#{parsed.fragment}" if parsed.fragment else ""
        return f"host-local://{sanitized_path}{fragment}"
    return text


def _operator_readiness_public_source_ref(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme == "script":
        return text
    if parsed.scheme == "file":
        return _operator_readiness_local_source_label(parsed.path or "")
    if parsed.scheme in {"http", "https", "host-local"}:
        return _operator_readiness_public_href(text)
    if text.startswith("/") or _operator_readiness_looks_like_windows_absolute_path(text):
        return _operator_readiness_local_source_label(text)
    script_label = _operator_readiness_script_source_label(text)
    if script_label:
        return script_label
    normalized = text.replace("\\", "/").rstrip("/")
    basename = normalized.split("/")[-1].lower() if normalized else ""
    if ("/" in text or "\\" in text) and basename.endswith(OPERATOR_READINESS_SCRIPT_SUFFIXES):
        return _operator_readiness_local_source_label(text)
    return text


def _operator_readiness_public_action_fields(
    *,
    action: object,
    href: object,
    label: object,
    method: object,
) -> tuple[str, str, str]:
    normalized_action = str(action or "").strip()
    surface = proactive_next_action_surface(normalized_action)
    surface_href = str(surface.get("href") or "").strip()
    if surface_href:
        return (
            surface_href,
            str(surface.get("label") or label or "").strip(),
            str(surface.get("method") or method or "").strip().lower(),
        )
    return (
        _operator_readiness_public_href(href),
        str(label or "").strip(),
        str(method or "").strip().lower(),
    )


def _operator_readiness_public_list_count(value: object) -> int:
    if not isinstance(value, list):
        return 0
    return len([str(item).strip() for item in value if str(item).strip()])


def _operator_readiness_public_details(component: Mapping[str, object]) -> dict[str, object]:
    details = dict(component.get("details") or {})
    if not details:
        return {}
    action = str(component.get("next_action") or "").strip()
    public: dict[str, object] = {}
    for field, value in details.items():
        if value is None:
            continue
        if field == "account_label":
            public["account_label_present"] = bool(str(value or "").strip())
            continue
        if field in {"principal_id", "binding_id"} or field.endswith("_principal_id") or field.endswith("_binding_id"):
            public[f"{field}_present"] = bool(str(value or "").strip())
            continue
        if field == "required_client_keys":
            public["required_client_count"] = _operator_readiness_public_list_count(value)
            continue
        if field == "missing_client_keys":
            public["missing_client_count"] = _operator_readiness_public_list_count(value)
            continue
        if field == "missing_token_keys":
            public["missing_token_count"] = _operator_readiness_public_list_count(value)
            continue
        if field in {"session_ref", "effective_session_ref"} or field.endswith("_session_ref"):
            public[f"{field}_present"] = bool(str(value or "").strip())
            continue
        if field == "qr_svg_path":
            public[field] = "host-local-file:redacted" if str(value or "").strip() else ""
            continue
        if field.endswith("_href"):
            href, label, method = _operator_readiness_public_action_fields(
                action=action,
                href=value,
                label=details.get("next_action_label"),
                method=details.get("next_action_method"),
            )
            public[field] = href
            if field == "next_action_href":
                public["next_action_label"] = label
                public["next_action_method"] = method
            continue
        if field.endswith("_url"):
            public[field] = _operator_readiness_public_href(value)
            continue
        if field.endswith("_path"):
            public[field] = _operator_readiness_public_source_ref(value)
            continue
        if field == "reason" or field.endswith("_reason"):
            public[field] = _operator_readiness_public_reason(value)
            continue
        public[field] = value
    return public


def _operator_readiness_public_detail_fields(key: str) -> set[str]:
    allowed: set[str] = set()
    for field in OPERATOR_READINESS_DETAIL_FIELDS.get(str(key or "").strip(), ()):
        if field == "account_label":
            allowed.add("account_label_present")
            continue
        if field == "required_client_keys":
            allowed.add("required_client_count")
            continue
        if field == "missing_client_keys":
            allowed.add("missing_client_count")
            continue
        if field == "missing_token_keys":
            allowed.add("missing_token_count")
            continue
        if field in {"principal_id", "binding_id"} or field.endswith("_principal_id") or field.endswith("_binding_id"):
            allowed.add(f"{field}_present")
            continue
        if field in {"session_ref", "effective_session_ref"} or field.endswith("_session_ref"):
            allowed.add(f"{field}_present")
            continue
        allowed.add(field)
    return allowed


def _operator_readiness_public_component(component: Mapping[str, object]) -> dict[str, object]:
    public = dict(component)
    href, label, method = _operator_readiness_public_action_fields(
        action=component.get("next_action"),
        href=component.get("next_action_href"),
        label=component.get("next_action_label"),
        method=component.get("next_action_method"),
    )
    public["reason"] = _operator_readiness_public_reason(component.get("reason"))
    public["next_action_href"] = href
    public["next_action_label"] = label
    public["next_action_method"] = method
    public["source"] = _operator_readiness_public_source_ref(component.get("source"))
    public["details"] = _operator_readiness_public_details(component)
    return public


def _operator_readiness_public_next_actions(
    actions: Sequence[Mapping[str, object]],
) -> list[dict[str, str]]:
    public_actions: list[dict[str, str]] = []
    for item in actions:
        action = str(item.get("action") or "").strip()
        href, label, method = _operator_readiness_public_action_fields(
            action=action,
            href=item.get("href"),
            label=item.get("label"),
            method=item.get("method"),
        )
        public_actions.append(
            {
                "component_key": str(item.get("component_key") or "").strip(),
                "component_label": str(item.get("component_label") or "").strip(),
                "action": action,
                "reason": _operator_readiness_public_reason(item.get("reason")),
                "href": href,
                "label": label,
                "method": method,
            }
        )
    return public_actions


def _operator_readiness_public_report(report: Mapping[str, object]) -> dict[str, object]:
    public = dict(report)
    components = [dict(item) for item in list(report.get("components") or []) if isinstance(item, dict)]
    next_actions = [dict(item) for item in list(report.get("next_actions") or []) if isinstance(item, dict)]
    supplemental_next_actions = [
        dict(item) for item in list(report.get("supplemental_next_actions") or []) if isinstance(item, dict)
    ]
    public["components"] = [_operator_readiness_public_component(item) for item in components]
    public["next_actions"] = _operator_readiness_public_next_actions(next_actions)
    public["supplemental_next_actions"] = _operator_readiness_public_next_actions(supplemental_next_actions)
    public["source"] = _operator_readiness_public_source_ref(report.get("source"))
    if public["next_actions"]:
        first = dict(public["next_actions"][0])
        public["next_action_href"] = str(first.get("href") or "").strip()
        public["next_action_label"] = str(first.get("label") or "").strip()
        public["next_action_method"] = str(first.get("method") or "").strip()
    else:
        public["next_action_href"] = _operator_readiness_public_href(report.get("next_action_href"))
        public["next_action_label"] = str(report.get("next_action_label") or "").strip()
        public["next_action_method"] = str(report.get("next_action_method") or "").strip().lower()
    return public


def _normalize_operator_streams(values: object) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        raw_values = [part.strip() for part in values.split(",")]
    else:
        raw_values = [str(item or "").strip() for item in list(values or [])]
    aliases = {
        "default": DEFAULT_TELEGRAM_OPERATOR_STREAMS,
        "office": DEFAULT_TELEGRAM_OPERATOR_STREAMS,
        "office_only": DEFAULT_TELEGRAM_OPERATOR_STREAMS,
        "office_loop": (OPERATOR_STREAM_OFFICE_LOOP,),
        "office-loop": (OPERATOR_STREAM_OFFICE_LOOP,),
        "office_setup": (OPERATOR_STREAM_OFFICE_SETUP,),
        "office-setup": (OPERATOR_STREAM_OFFICE_SETUP,),
        "recovery": (OPERATOR_STREAM_RECOVERY,),
        "media": (OPERATOR_STREAM_MEDIA_MEMORIAL,),
        "media_memorial": (OPERATOR_STREAM_MEDIA_MEMORIAL,),
        "all": ("*",),
        "*": ("*",),
    }
    normalized: list[str] = []
    for value in raw_values:
        if not value:
            continue
        for item in aliases.get(value.lower(), (value,)):
            token = str(item or "").strip()
            if token and token not in normalized:
                normalized.append(token)
    return tuple(normalized)


def _effective_telegram_operator_streams(values: object = None) -> tuple[str, ...]:
    configured = _normalize_operator_streams(values)
    if configured:
        return configured
    configured = _normalize_operator_streams(_env("EA_LIVE_OPS_TELEGRAM_OPERATOR_STREAMS"))
    return configured or DEFAULT_TELEGRAM_OPERATOR_STREAMS


def _telegram_operator_stream_allowed(
    operator_stream: str,
    *,
    allowed_operator_streams: tuple[str, ...],
) -> bool:
    normalized_stream = str(operator_stream or "").strip()
    if not normalized_stream:
        return True
    if "*" in set(allowed_operator_streams):
        return True
    return normalized_stream in allowed_operator_streams


def _suppressed_telegram_delivery(
    *,
    principal_id: str,
    operator_stream: str,
    allowed_operator_streams: tuple[str, ...],
    observed_at: str,
    source: str,
    delivery_transport: str = "telegram_bot",
) -> dict[str, object]:
    return {
        "sent": False,
        "reason": "operator_stream_not_allowed",
        "ready": False,
        "readiness_probe_ok": False,
        "readiness_status": "suppressed_by_stream_policy",
        "readiness_reason": "operator_stream_not_allowed",
        "principal_id": str(principal_id or "").strip(),
        "delivery_transport": str(delivery_transport or "telegram_bot").strip() or "telegram_bot",
        "operator_stream": str(operator_stream or "").strip(),
        "allowed_operator_streams": list(allowed_operator_streams),
        "next_action": "",
        "next_action_href": "",
        "next_action_label": "",
        "next_action_method": "",
        "observed_at": observed_at,
        "source": source,
    }


def _add_telegram_operator_streams_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--telegram-operator-streams",
        default="",
        help=(
            "Comma-separated operator streams allowed to send over Telegram for this command. "
            "Defaults to office_loop,office_setup,recovery; use media or all to widen."
        ),
    )


def _add_timeout_seconds_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=argparse.SUPPRESS,
        help="Runtime probe timeout in seconds. May be placed before or after the subcommand.",
    )


def _docker_cli_available() -> bool:
    return shutil.which("docker") is not None


def _docker_compose_project_env() -> dict[str, str]:
    env = dict(os.environ)
    if not str(env.get("COMPOSE_PROJECT_NAME") or "").strip():
        configured = (
            str(env.get("EA_LIVE_OPS_COMPOSE_PROJECT_NAME") or "").strip()
            or str(env.get("EA_COMPOSE_PROJECT_NAME") or "").strip()
            or DEFAULT_EA_COMPOSE_PROJECT_NAME
        )
        env["COMPOSE_PROJECT_NAME"] = configured
    return env


def _use_in_process_proactive_runtime_fallback() -> bool:
    if _env_truthy("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", default=False):
        return False
    if _docker_cli_available():
        return False
    return bool(_env("EA_ROLE")) or ROOT.as_posix() == "/app"


def _prefer_host_runtime_proactive_probe() -> bool:
    if _use_in_process_proactive_runtime_fallback():
        return True
    if _env_truthy("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", default=False):
        return False
    return _env_truthy("EA_LIVE_OPS_PREFER_HOST_RUNTIME_PROACTIVE_PROBE", default=False)


def _proactive_runtime_root() -> Path:
    return ROOT


def _host_proactive_runtime_state_dir(root: Path) -> Path:
    return root / "state"


def _proactive_runtime_inputs() -> dict[str, object]:
    root = _proactive_runtime_root()
    if root.as_posix() == "/app":
        default_state_path = "/data/provider-ledger/proactive_ooda_notified.json"
        default_receipt_path = ""
        default_stage_packet_dir = ""
        default_safe_work_result_dir = ""
    else:
        state_dir = _host_proactive_runtime_state_dir(root)
        default_state_path = (state_dir / "proactive_ooda_notified.json").as_posix()
        default_receipt_path = (state_dir / "proactive_ooda_latest_run.generated.json").as_posix()
        default_stage_packet_dir = (state_dir / "proactive_ooda_stage_packets").as_posix()
        default_safe_work_result_dir = (state_dir / "proactive_ooda_safe_work_results").as_posix()
    return {
        "root": root,
        "state_path": _env("EA_PROACTIVE_OODA_STATE_PATH", default_state_path) or default_state_path,
        "receipt_path": _env("EA_PROACTIVE_OODA_RECEIPT_PATH", default_receipt_path),
        "stage_packet_dir": _env("EA_PROACTIVE_OODA_STAGE_PACKET_DIR", default_stage_packet_dir),
        "safe_work_result_dir": _env("EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR", default_safe_work_result_dir),
    }


def _default_whatsapp_principal_id() -> str:
    return _env("EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID") or _env("EA_WHATSAPP_DEFAULT_PRINCIPAL_ID", "principal-default")


def _default_proactive_principal_id() -> str:
    return _env("EA_PROACTIVE_OODA_PRINCIPAL_ID") or _env("EA_DEFAULT_PRINCIPAL_ID") or _default_whatsapp_principal_id()


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _digits(value: object) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _normalize_phone_hint(value: object) -> str:
    raw = str(value or "").strip()
    return raw if raw in {"*", "default"} else _digits(raw)


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _read_json_file(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _path_readable(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.R_OK)
    except Exception:
        return False


def _expand_candidate_paths(raw_path: str) -> tuple[Path, ...]:
    normalized = str(raw_path or "").strip()
    if not normalized:
        return ()
    candidate = Path(os.path.expandvars(os.path.expanduser(normalized)))
    if candidate.is_absolute():
        return (candidate,)
    filename = candidate.name
    return (
        candidate,
        ROOT / candidate,
        EA_ROOT / candidate,
        ROOT / "config" / filename,
        EA_ROOT / "config" / filename,
    )


def _resolve_onemin_owner_ledger_path(path_text: str = "") -> Path | None:
    configured = str(path_text or "").strip()
    env_configured = _env("EA_RESPONSES_ONEMIN_OWNER_LEDGER_PATH")
    candidates: list[Path] = []
    for raw in (
        configured,
        env_configured,
        DEFAULT_ONEMIN_OWNER_LEDGER_LOCAL_PATH.as_posix(),
        DEFAULT_ONEMIN_OWNER_LEDGER_PATH.as_posix(),
    ):
        for candidate in _expand_candidate_paths(raw):
            if candidate not in candidates:
                candidates.append(candidate)
    for candidate in candidates:
        if _path_readable(candidate):
            return candidate
    return None


def _load_onemin_owner_rows_for_live_ops(owner_ledger_path: str = "") -> tuple[Path | None, list[dict[str, str]], str]:
    resolved = _resolve_onemin_owner_ledger_path(owner_ledger_path)
    if resolved is None:
        return None, [], "owner_ledger_missing"
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except Exception:
        return resolved, [], "owner_ledger_unreadable"
    if isinstance(payload, dict):
        items = payload.get("slots") if isinstance(payload.get("slots"), list) else payload.get("owners")
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    rows: list[dict[str, str]] = []
    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        account_label = str(item.get("account_name") or item.get("slot_env_name") or "").strip()
        owner_email = str(item.get("owner_email") or item.get("email") or "").strip()
        owner_name = str(item.get("owner_name") or item.get("name") or "").strip()
        slot = str(item.get("slot") or "").strip()
        if not account_label or not owner_email:
            continue
        rows.append(
            {
                "account_name": account_label,
                "owner_email": owner_email,
                "owner_name": owner_name,
                "slot": slot,
            }
        )
    if not rows:
        return resolved, [], "owner_ledger_empty"
    return resolved, rows, ""


def _onemin_direct_refresh_output_path(path_text: str = "") -> Path:
    configured = str(path_text or "").strip()
    if configured:
        return Path(os.path.expandvars(os.path.expanduser(configured)))
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return DEFAULT_ONEMIN_DIRECT_REFRESH_STATE_DIR / f"onemin_direct_refresh_{timestamp}.json"


def _onemin_direct_refresh_resume_labels(output_path: Path) -> set[str]:
    payload = _read_json_file(output_path)
    labels: set[str] = set()
    for row in list(payload.get("results") or []):
        if not isinstance(row, Mapping):
            continue
        account_label = str(row.get("account_label") or "").strip()
        if account_label:
            labels.add(account_label)
    return labels


def _onemin_direct_refresh_candidate_receipt_paths(path_text: str = "") -> tuple[Path, ...]:
    configured = str(path_text or "").strip()
    candidates: list[Path] = []
    if configured:
        for candidate in _expand_candidate_paths(configured):
            if candidate not in candidates:
                candidates.append(candidate)
        return tuple(candidates)
    for pattern in (
        DEFAULT_ONEMIN_DIRECT_REFRESH_STATE_DIR / "onemin_direct_refresh*.json",
        ROOT / "state" / "onemin_direct_refresh*.json",
        EA_ROOT / "state" / "onemin_direct_refresh*.json",
    ):
        for candidate in sorted(pattern.parent.glob(pattern.name)):
            if candidate not in candidates:
                candidates.append(candidate)
    return tuple(candidates)


def _load_latest_onemin_direct_refresh_receipt(path_text: str = "") -> tuple[Path | None, dict[str, object], str]:
    candidates = _onemin_direct_refresh_candidate_receipt_paths(path_text)
    if not candidates:
        return None, {}, "receipt_missing"
    valid_receipts: list[tuple[Path, dict[str, object]]] = []
    first_unreadable: Path | None = None
    for candidate in candidates:
        if not _path_readable(candidate):
            continue
        payload = _read_json_file(candidate)
        if payload:
            valid_receipts.append((candidate, payload))
        elif first_unreadable is None:
            first_unreadable = candidate
    if not valid_receipts:
        if first_unreadable is not None:
            return first_unreadable, {}, "receipt_unreadable"
        return None, {}, "receipt_missing"

    def _sort_key(item: tuple[Path, dict[str, object]]) -> tuple[int, str, float]:
        candidate, payload = item
        status = str(payload.get("status") or "").strip()
        observed_at = str(payload.get("observed_at") or payload.get("generated_at") or "").strip()
        try:
            mtime = float(candidate.stat().st_mtime)
        except OSError:
            mtime = 0.0
        return (1 if status != "dry_run" else 0, observed_at, mtime)

    selected_path, selected_payload = max(valid_receipts, key=_sort_key)
    return selected_path, selected_payload, ""


def _onemin_direct_refresh_posture_telegram_delivery(
    value: Mapping[str, object] | None,
) -> dict[str, object]:
    delivery = dict(value or {})
    message_ids = [str(item).strip() for item in list(delivery.get("message_ids") or []) if str(item).strip()]
    message_count = int(delivery.get("message_count") or 0)
    if message_count <= 0 and message_ids:
        message_count = len(message_ids)
    reason = str(delivery.get("reason") or "").strip()
    return {
        "checked": bool(delivery),
        "sent": bool(delivery.get("sent")),
        "reason": reason,
        "ready": bool(delivery.get("ready")),
        "message_count": max(message_count, 0),
        "observed_at": str(delivery.get("observed_at") or "").strip(),
        "source": str(delivery.get("source") or "").strip(),
        "dry_run": reason == "dry_run",
    }


def _operator_text_for_onemin_direct_refresh_posture(report: Mapping[str, object]) -> str:
    controls = dict(report.get("controls") or {}) if isinstance(report.get("controls"), Mapping) else {}
    telegram_delivery = (
        dict(report.get("telegram_delivery") or {}) if isinstance(report.get("telegram_delivery"), Mapping) else {}
    )
    pieces = [
        f"onemin_direct_refresh_posture status={report.get('status') or 'unknown'}",
        f"checked={str(bool(report.get('checked'))).lower()}",
    ]
    if report.get("receipt_name"):
        pieces.append(f"receipt={report['receipt_name']}")
    if report.get("selected_account_count") not in (None, ""):
        pieces.append(f"selected={report['selected_account_count']}")
    if report.get("current_run_refreshed_count") not in (None, ""):
        pieces.append(f"refreshed_now={report['current_run_refreshed_count']}")
    if report.get("error_count") not in (None, ""):
        pieces.append(f"errors={report['error_count']}")
    if report.get("rate_limited") is not None:
        pieces.append(f"rate_limited={str(bool(report.get('rate_limited'))).lower()}")
    if controls.get("batch_size") not in (None, ""):
        pieces.append(f"batch_size={controls['batch_size']}")
    if controls.get("max_rate_limit_sleep_seconds") not in (None, ""):
        pieces.append(f"max_rl_sleep={controls['max_rate_limit_sleep_seconds']}")
    if telegram_delivery.get("checked"):
        pieces.append(f"telegram={telegram_delivery.get('reason') or 'checked'}")
    if report.get("next_action"):
        pieces.append(f"next={report['next_action']}")
    return "; ".join(str(item) for item in pieces if str(item).strip())


def probe_onemin_direct_refresh_posture(
    *,
    receipt_path: str = "",
    output_format: str = "json",
) -> dict[str, object]:
    resolved_path, receipt, load_reason = _load_latest_onemin_direct_refresh_receipt(receipt_path)
    controls = {
        "batch_size": max(int(receipt.get("batch_size") or DEFAULT_ONEMIN_DIRECT_REFRESH_BATCH_SIZE), 1),
        "batch_backoff_seconds": max(
            float(receipt.get("batch_backoff_seconds") or DEFAULT_ONEMIN_DIRECT_REFRESH_BATCH_BACKOFF_SECONDS),
            0.0,
        ),
        "max_rate_limit_sleep_seconds": max(
            float(
                receipt.get("max_rate_limit_sleep_seconds")
                or DEFAULT_ONEMIN_DIRECT_REFRESH_MAX_RATE_LIMIT_SLEEP_SECONDS
            ),
            0.0,
        ),
        "continue_on_rate_limit": bool(
            receipt.get("continue_on_rate_limit")
            if "continue_on_rate_limit" in receipt
            else True
        ),
        "refresh_transport": str(receipt.get("refresh_transport") or "direct_provider_api").strip(),
        "proxy_mode": str(receipt.get("proxy_mode") or "direct_no_ui_proxy").strip(),
        "controls_inferred_from_defaults": any(
            key not in receipt
            for key in (
                "batch_size",
                "batch_backoff_seconds",
                "max_rate_limit_sleep_seconds",
                "continue_on_rate_limit",
                "refresh_transport",
                "proxy_mode",
            )
        ),
        "single_account_batch_mode": max(int(receipt.get("batch_size") or DEFAULT_ONEMIN_DIRECT_REFRESH_BATCH_SIZE), 1)
        <= 1,
    }
    if not receipt:
        report: dict[str, object] = {
            "checked": False,
            "probe_ok": False,
            "status": "receipt_unreadable" if load_reason == "receipt_unreadable" else "not_checked",
            "source": "",
            "observed_at": "",
            "reason": load_reason or "receipt_missing",
            "next_action": "",
            "ready": False,
            "receipt_name": resolved_path.name if resolved_path is not None else "",
            "selected_account_count": 0,
            "pending_account_count": 0,
            "owner_row_count": 0,
            "attempted_count": 0,
            "current_run_refreshed_count": 0,
            "refreshed_count": 0,
            "error_count": 0,
            "error_code_counts": {},
            "rate_limited": False,
            "remaining_credits_total": None,
            "remaining_credits_min": None,
            "remaining_credits_max": None,
            "next_topup_at_earliest": "",
            "next_topup_at_latest": "",
            "controls": controls,
            "telegram_delivery": {
                "checked": False,
                "sent": False,
                "reason": "",
                "ready": False,
                "message_count": 0,
                "observed_at": "",
                "source": "",
                "dry_run": False,
            },
            "privacy": {
                "raw_owner_email_exposed": False,
                "raw_login_secret_exposed": False,
                "raw_telegram_chat_ref_exposed": False,
            },
        }
    else:
        report = {
            "checked": True,
            "probe_ok": True,
            "status": str(receipt.get("status") or "unknown").strip() or "unknown",
            "source": f"private_receipt:{resolved_path.name}" if resolved_path is not None else "private_receipt",
            "observed_at": str(receipt.get("observed_at") or receipt.get("generated_at") or "").strip(),
            "reason": str(receipt.get("reason") or "").strip(),
            "next_action": str(receipt.get("next_action") or "").strip(),
            "ready": bool(receipt.get("ready")),
            "receipt_name": resolved_path.name if resolved_path is not None else "",
            "selected_account_count": int(receipt.get("selected_account_count") or 0),
            "pending_account_count": int(receipt.get("pending_account_count") or 0),
            "owner_row_count": int(receipt.get("owner_row_count") or 0),
            "attempted_count": int(receipt.get("attempted_count") or 0),
            "current_run_refreshed_count": int(receipt.get("current_run_refreshed_count") or 0),
            "refreshed_count": int(receipt.get("refreshed_count") or 0),
            "error_count": int(receipt.get("error_count") or 0),
            "error_code_counts": {
                str(key).strip(): int(value or 0)
                for key, value in dict(receipt.get("error_code_counts") or {}).items()
                if str(key).strip()
            },
            "rate_limited": bool(receipt.get("rate_limited")),
            "remaining_credits_total": receipt.get("remaining_credits_total"),
            "remaining_credits_min": receipt.get("remaining_credits_min"),
            "remaining_credits_max": receipt.get("remaining_credits_max"),
            "next_topup_at_earliest": str(receipt.get("next_topup_at_earliest") or "").strip(),
            "next_topup_at_latest": str(receipt.get("next_topup_at_latest") or "").strip(),
            "controls": controls,
            "telegram_delivery": _onemin_direct_refresh_posture_telegram_delivery(
                receipt.get("telegram_delivery") if isinstance(receipt.get("telegram_delivery"), Mapping) else {}
            ),
            "privacy": {
                "raw_owner_email_exposed": False,
                "raw_login_secret_exposed": False,
                "raw_telegram_chat_ref_exposed": False,
            },
        }
    next_action_surface = _next_action_surface_fields(str(report.get("next_action") or ""))
    for key, value in next_action_surface.items():
        if not str(report.get(key) or "").strip():
            report[key] = value
    if output_format == "operator":
        report["operator_text"] = _operator_text_for_onemin_direct_refresh_posture(report)
    return report


@contextmanager
def _temporary_env(overrides: Mapping[str, object]):
    previous: dict[str, str | None] = {}
    try:
        for key, value in overrides.items():
            previous[key] = os.environ.get(key)
            if value in (None, ""):
                os.environ.pop(key, None)
            else:
                os.environ[str(key)] = str(value)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _mymedia_runtime_defaults_path() -> Path:
    configured = _env("EA_MYMEDIA_ALEXA_RUNTIME_DEFAULTS_PATH")
    if configured:
        return Path(os.path.expandvars(os.path.expanduser(configured)))
    return DEFAULT_MYMEDIA_ALEXA_RUNTIME_DEFAULTS_PATH


def _mymedia_runtime_defaults() -> dict[str, object]:
    return _read_json_file(_mymedia_runtime_defaults_path())


def _mymedia_runtime_default_value(
    *,
    env_names: tuple[str, ...],
    payload_keys: tuple[str, ...],
    default: str = "",
) -> str:
    for env_name in env_names:
        configured = _env(env_name)
        if configured:
            return configured
    payload = _mymedia_runtime_defaults()
    for key in payload_keys:
        configured = str(payload.get(key) or "").strip()
        if configured:
            return configured
    return str(default or "").strip()


def _runtime_readiness_receipt_path() -> Path:
    configured = _env("EA_WHATSAPP_WEB_ACTION_PROCESSOR_READINESS_PATH")
    if configured:
        return Path(configured)
    ledger_dir = _env("EA_RESPONSES_PROVIDER_LEDGER_DIR", "/data/provider-ledger") or "/data/provider-ledger"
    return Path(ledger_dir) / "provider-health-cache" / DEFAULT_READINESS_RECEIPT_FILENAME


def _whatsapp_readiness_receipt() -> dict[str, object]:
    ordered: list[Path] = []
    for candidate in (_runtime_readiness_receipt_path(), DEFAULT_READINESS_RECEIPT_PATH):
        if candidate not in ordered:
            ordered.append(candidate)
    for candidate in ordered:
        payload = _read_json_file(candidate)
        if payload:
            return payload
    return {}


def _request_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: dict[str, object] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers=headers or {},
        data=None if body is None else json.dumps(body).encode("utf-8"),
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def _request_json_value(
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: dict[str, object] | None = None,
    timeout: float = 15.0,
) -> object:
    request = urllib.request.Request(
        url,
        headers=headers or {},
        data=None if body is None else json.dumps(body).encode("utf-8"),
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    if not payload.strip():
        return {}
    try:
        return json.loads(payload)
    except Exception:
        return {}


def _request_json_response(
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: dict[str, object] | None = None,
    timeout: float = 15.0,
) -> tuple[int, dict[str, Any], str]:
    request = urllib.request.Request(
        url,
        headers=headers or {},
        data=None if body is None else json.dumps(body).encode("utf-8"),
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return int(getattr(response, "status", 200) or 200), dict(payload) if isinstance(payload, dict) else {}, ""
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {}
        return int(getattr(exc, "code", 0) or 0), dict(payload) if isinstance(payload, dict) else {}, ""
    except Exception as exc:
        return 0, {}, type(exc).__name__


def _request_bytes(
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers=headers or {}, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = str(response.headers.get("Content-Type") or "").strip()
        return response.read(), content_type


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def _request_text_response(
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
    max_bytes: int = 8192,
) -> tuple[int, dict[str, str], str, str]:
    request = urllib.request.Request(url, headers=headers or {}, method=method)
    opener = urllib.request.build_opener(_NoRedirectHandler)
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = response.read(max(int(max_bytes or 8192), 0)).decode("utf-8", errors="replace")
            response_headers = {str(key or ""): str(value or "") for key, value in response.headers.items()}
            return int(getattr(response, "status", 200) or 200), response_headers, payload, ""
    except urllib.error.HTTPError as exc:
        try:
            payload = exc.read(max(int(max_bytes or 8192), 0)).decode("utf-8", errors="replace")
        except Exception:
            payload = ""
        response_headers = {str(key or ""): str(value or "") for key, value in exc.headers.items()}
        return int(getattr(exc, "code", 0) or 0), response_headers, payload, ""
    except Exception as exc:
        return 0, {}, "", type(exc).__name__


def _header_value(headers: Mapping[str, str], name: str) -> str:
    target = str(name or "").strip().lower()
    for key, value in headers.items():
        if str(key or "").strip().lower() == target:
            return str(value or "").strip()
    return ""


def _read_env_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        current_key, value = line.split("=", 1)
        if current_key.strip() != key:
            continue
        normalized = value.strip()
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"'", '"'}:
            normalized = normalized[1:-1]
        return normalized
    return ""


def _json_from_stdout(stdout: str) -> dict[str, Any]:
    text = str(stdout or "").strip()
    try:
        payload = json.loads(text)
    except Exception:
        payload = None
        for line in reversed(text.splitlines()):
            try:
                payload = json.loads(line.strip())
                break
            except Exception:
                continue
        if payload is None:
            return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _jsonify_runtime_value(value: object) -> object:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(key): _jsonify_runtime_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify_runtime_value(item) for item in value]
    return value


def _compact_text(value: object, *, limit: int = 140) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    if len(text) <= max(int(limit or 1), 1):
        return text
    clipped = max(int(limit or 1) - 3, 1)
    return f"{text[:clipped].rstrip()}..."


def _load_json_dict(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _string_list(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _proactive_source_row_terms(row: Mapping[str, object]) -> set[str]:
    terms: set[str] = set()
    for key in ("channel", "event_type"):
        value = str(row.get(key) or "").strip().lower()
        if value:
            terms.add(value)
    for key in ("payload_keys", "hints"):
        for value in _string_list(row.get(key)):
            normalized = value.strip().lower()
            if normalized:
                terms.add(normalized)
    return terms


def _terms_contain(terms: set[str], *needles: str) -> bool:
    return any(needle in term for term in terms for needle in needles)


PROACTIVE_SOURCE_COVERAGE_EXCLUDED_EVENT_TYPES = frozenset(
    {
        "property_scout_sync_completed",
        "assistant_property_task_auto_closed",
    }
)
PROACTIVE_SOURCE_COVERAGE_EXCLUDED_EVENT_PREFIXES = (
    "property_",
    "assistant_property_",
)


def _source_coverage_event_type(row: Mapping[str, object]) -> str:
    return str(row.get("event_type") or "").strip()


def _source_coverage_event_excluded(event_type: object) -> bool:
    normalized = str(event_type or "").strip().lower()
    if not normalized:
        return False
    if normalized in PROACTIVE_SOURCE_COVERAGE_EXCLUDED_EVENT_TYPES:
        return True
    return any(normalized.startswith(prefix) for prefix in PROACTIVE_SOURCE_COVERAGE_EXCLUDED_EVENT_PREFIXES)


def _proactive_source_lane_matches(row: Mapping[str, object], lane_key: str) -> bool:
    terms = _proactive_source_row_terms(row)
    channel = str(row.get("channel") or "").strip().lower()
    event_type = str(row.get("event_type") or "").strip().lower()
    if lane_key == "google_workspace":
        return _terms_contain(terms, "google_workspace", "gmail", "google", "calendar")
    if lane_key == "pocket_ai_audio_transcripts":
        return (
            event_type == "pocket_recording_archive_indexed"
            or _terms_contain(terms, "pocket_ai_audio_transcripts", "pocket", "recording", "transcript")
        )
    if lane_key == "calendar_and_renewal_signals":
        return _terms_contain(terms, "calendar_and_renewal_signals", "calendar", "renewal", "subscription", "appointment")
    if lane_key == "relationship_and_occasion_signals":
        return _terms_contain(
            terms,
            "relationship_and_occasion_signals",
            "relationship",
            "occasion",
            "birthday",
            "anniversary",
            "family",
        )
    if lane_key == "shopping_and_vendor_signals":
        return _terms_contain(
            terms,
            "shopping_and_vendor_signals",
            "shopping",
            "vendor",
            "supplier",
            "provider",
            "purchase",
            "amazon",
            "draft",
            "shortlist",
        )
    if lane_key == "commitment_and_deadline_signals":
        return _terms_contain(
            terms,
            "commitment_and_deadline_signals",
            "commitment",
            "deadline",
            "due",
            "followup",
            "follow-up",
            "appointment",
            "booking",
        )
    if lane_key == "durable_profile_and_location_context":
        return _terms_contain(
            terms,
            "durable_profile_and_location_context",
            "profile",
            "preference",
            "location",
            "locality",
            "address",
            "context",
        )
    if lane_key == "postgres_observations":
        return bool(channel or event_type)
    return False


def _latest_observed_at(rows: list[Mapping[str, object]]) -> str:
    return max((str(row.get("created_at") or "").strip() for row in rows if str(row.get("created_at") or "").strip()), default="")


def _event_types(rows: list[Mapping[str, object]]) -> list[str]:
    values = sorted({str(row.get("event_type") or "").strip() for row in rows if str(row.get("event_type") or "").strip()})
    return values[:8]


def _missing_required_event_types(rows: list[Mapping[str, object]], required_event_types: tuple[str, ...]) -> list[str]:
    observed = {str(row.get("event_type") or "").strip().lower() for row in rows}
    return [event_type for event_type in required_event_types if event_type.lower() not in observed]


def _pocket_audio_archive_evidence() -> dict[str, object]:
    archive_root = Path(
        _env("EA_POCKET_AUDIO_ARCHIVE_ROOT", str(pocket_audio_archive_verifier.DEFAULT_ARCHIVE_ROOT))
        or pocket_audio_archive_verifier.DEFAULT_ARCHIVE_ROOT.as_posix()
    ).expanduser()
    container = _env("EA_POSTGRES_CONTAINER", "ea-db") or "ea-db"
    user = _env("POSTGRES_USER", "postgres") or "postgres"
    database = _env("POSTGRES_DB", "ea_smoke_runtime") or "ea_smoke_runtime"
    try:
        index_rows = pocket_audio_archive_verifier.load_index_rows(
            container=container,
            user=user,
            database=database,
        )
        completion_rows = pocket_audio_archive_verifier.load_completion_rows(
            container=container,
            user=user,
            database=database,
        )
        receipt = pocket_audio_archive_verifier.build_receipt(
            archive_root=archive_root,
            index_rows=index_rows,
            completion_rows=completion_rows,
        )
    except Exception as exc:
        return {
            "checked": False,
            "status": "probe_failed",
            "transcript_ingest_ready": False,
            "evidence_mode": "",
            "latest_backfill_event_type": "",
            "latest_completion_event_type": "",
            "blocking_reason": _compact_text(str(exc), limit=200) or type(exc).__name__,
            "next_action": "sync_pocket_ai_audio_transcripts",
        }
    latest_backfill = dict(receipt.get("latest_backfill") or {})
    latest_completion = dict(receipt.get("latest_completion") or {})
    database_index = dict(receipt.get("database_index") or {})
    failures = [str(item or "").strip() for item in list(receipt.get("failures") or []) if str(item or "").strip()]
    return {
        "checked": True,
        "status": str(receipt.get("status") or "").strip(),
        "transcript_ingest_ready": bool(receipt.get("transcript_ingest_ready")),
        "evidence_mode": str(receipt.get("evidence_mode") or "").strip(),
        "latest_backfill_event_type": str(latest_backfill.get("event_type") or "").strip(),
        "latest_completion_event_type": str(latest_completion.get("event_type") or "").strip(),
        "latest_backfill_created_at": str(latest_backfill.get("created_at") or "").strip(),
        "latest_completion_created_at": str(latest_completion.get("created_at") or "").strip(),
        "archived_total": int(latest_backfill.get("archived_total") or 0),
        "dismissed_total": int(latest_backfill.get("archive_dismissed_total") or 0),
        "failed_total": int(latest_backfill.get("archive_failed_total") or 0),
        "distinct_recording_total": int(database_index.get("latest_distinct_recording_total") or 0),
        "blocking_reason": failures[0] if failures else "",
        "next_action": str(receipt.get("next_action") or "").strip() or "sync_pocket_ai_audio_transcripts",
    }


def _proactive_source_coverage_report(
    *,
    principal_id: str,
    rows: list[Mapping[str, object]],
    observation_repository: str,
    observed_at: str,
    observation_limit: int,
    source: str = "docker_compose_exec",
    pocket_archive_evidence: Mapping[str, object] | None = None,
) -> dict[str, object]:
    rows = [
        dict(row)
        for row in rows
        if not _source_coverage_event_excluded(_source_coverage_event_type(row))
    ]
    repository = str(observation_repository or "").strip()
    row_count = len(rows)
    lanes: list[dict[str, object]] = []
    for lane in PROACTIVE_SOURCE_COVERAGE_LANES:
        lane_key = str(lane["key"])
        if lane_key == "postgres_observations":
            matched = list(rows) if "postgres" in repository.lower() else []
        else:
            matched = [row for row in rows if _proactive_source_lane_matches(row, lane_key)]
        required_event_types = tuple(str(item).strip() for item in tuple(lane.get("required_event_types") or ()) if str(item).strip())
        missing_required_event_types = _missing_required_event_types(matched, required_event_types)
        required_event_type_observed = not missing_required_event_types
        observed = bool(matched) and required_event_type_observed
        status = "observed" if observed else "missing_required_event_type" if matched and missing_required_event_types else "not_observed"
        evidence_event_types = _event_types(matched)
        record_count = len(matched)
        latest_observed_at = _latest_observed_at(matched)
        if (
            lane_key == "pocket_ai_audio_transcripts"
            and not observed
            and bool(dict(pocket_archive_evidence or {}).get("transcript_ingest_ready"))
        ):
            archive_evidence = dict(pocket_archive_evidence or {})
            observed = True
            status = "observed_via_archive_evidence"
            required_event_type_observed = True
            missing_required_event_types = []
            supplemental_event_types = [
                str(archive_evidence.get("latest_backfill_event_type") or "").strip(),
                str(archive_evidence.get("latest_completion_event_type") or "").strip(),
            ]
            evidence_event_types = sorted({item for item in supplemental_event_types if item})[:8]
            record_count = max(
                len(matched),
                int(archive_evidence.get("distinct_recording_total") or 0),
                int(archive_evidence.get("archived_total") or 0),
            )
            latest_observed_at = (
                str(archive_evidence.get("latest_backfill_created_at") or "").strip()
                or str(archive_evidence.get("latest_completion_created_at") or "").strip()
                or latest_observed_at
            )
        lanes.append(
            {
                "key": lane_key,
                "label": str(lane["label"]),
                "status": status,
                "observed": observed,
                "record_count": record_count,
                "latest_observed_at": latest_observed_at,
                "evidence_event_types": evidence_event_types,
                "required_event_types": list(required_event_types),
                "required_event_type_observed": required_event_type_observed,
                "missing_required_event_types": missing_required_event_types,
                "next_action": "" if observed else str(lane["next_action"]),
                "raw_payload_exposed": False,
                "raw_transcript_text_exposed": False,
                "raw_credential_exposed": False,
            }
        )
    missing_lane_keys = [str(row["key"]) for row in lanes if not bool(row.get("observed"))]
    observed_lane_count = len(lanes) - len(missing_lane_keys)
    status = (
        "repaired"
        if not missing_lane_keys and row_count > 0
        else "ready_with_gaps"
        if row_count > 0
        else "no_recent_observations"
    )
    report: dict[str, object] = {
        "probe_ok": True,
        "checked": True,
        "status": status,
        "principal_id": str(principal_id or "").strip(),
        "source": source,
        "observed_at": observed_at,
        "observation_repository": repository,
        "observation_limit": int(observation_limit or 0),
        "observation_row_count": row_count,
        "lane_count": len(lanes),
        "observed_lane_count": observed_lane_count,
        "missing_lane_keys": missing_lane_keys,
        "lanes": lanes,
        "privacy": {
            "raw_rows_exposed": False,
            "raw_payload_exposed": False,
            "raw_transcript_text_exposed": False,
            "raw_credential_exposed": False,
            "source_ids_hashed": True,
        },
    }
    return report


def _prefer_in_process_source_coverage_probe() -> bool:
    if _use_in_process_proactive_runtime_fallback():
        return True
    if _env_truthy("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", default=False):
        return False
    if _env("DATABASE_URL"):
        return True
    return _env_truthy("EA_LIVE_OPS_PREFER_HOST_RUNTIME_PROACTIVE_PROBE", default=False)


def _source_coverage_hash_present(value: object) -> bool:
    return bool(str(value or "").strip())


def _source_coverage_walk(value: object):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key or "")
            yield from _source_coverage_walk(item)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _source_coverage_walk(item)
        return
    if isinstance(value, (str, int, float, bool)):
        yield str(value or "")


def _source_coverage_hints(row: object, payload: Mapping[str, object]) -> list[str]:
    text = " ".join(
        (
            str(getattr(row, "channel", "") or ""),
            str(getattr(row, "event_type", "") or ""),
            str(getattr(row, "source_id", "") or ""),
            str(getattr(row, "external_id", "") or ""),
            " ".join(_source_coverage_walk(payload)),
        )
    ).lower()
    specs = {
        "google_workspace": ("google", "gmail", "calendar", "workspace"),
        "pocket_ai_audio_transcripts": ("pocket", "pocket.ai", "recording", "transcript"),
        "calendar_and_renewal_signals": ("calendar", "renewal", "subscription", "appointment"),
        "relationship_and_occasion_signals": ("relationship", "occasion", "birthday", "anniversary", "wife", "family"),
        "shopping_and_vendor_signals": ("shopping", "vendor", "supplier", "provider", "purchase", "amazon", "shortlist", "draft"),
        "commitment_and_deadline_signals": ("commitment", "deadline", "due", "followup", "follow-up", "appointment", "booking"),
        "durable_profile_and_location_context": ("profile", "preference", "location", "locality", "address", "context"),
    }
    return sorted(key for key, needles in specs.items() if any(needle in text for needle in needles))


def _probe_proactive_source_coverage_in_process_report(
    *,
    principal_id: str,
    observation_limit: int,
    observed_at: str,
) -> dict[str, object]:
    with _suppress_container_postgres_fallback_warning():
        container = build_container()
    runtime = container.channel_runtime
    repo = getattr(runtime, "_observations", None)
    observation_repository = type(repo).__name__ if repo is not None else ""
    if "postgres" not in observation_repository.lower():
        raise RuntimeError(f"in_process_source_coverage_repo_not_postgres:{observation_repository or 'missing'}")
    rows: list[dict[str, object]] = []
    for row in runtime.list_recent_observations(limit=observation_limit, principal_id=principal_id):
        row_payload = dict(getattr(row, "payload", {}) or {})
        event_type = str(getattr(row, "event_type", "") or "").strip()
        if _source_coverage_event_excluded(event_type):
            continue
        rows.append(
            {
                "channel": str(getattr(row, "channel", "") or "").strip(),
                "event_type": event_type,
                "created_at": str(getattr(row, "created_at", "") or "").strip(),
                "payload_keys": sorted(str(key) for key in row_payload.keys()),
                "hints": _source_coverage_hints(row, row_payload),
                "source_id_sha256_present": _source_coverage_hash_present(getattr(row, "source_id", "") or ""),
                "external_id_sha256_present": _source_coverage_hash_present(getattr(row, "external_id", "") or ""),
                "raw_payload_exposed": False,
            }
        )
    pocket_archive_evidence: dict[str, object] = {}
    if not any(_proactive_source_lane_matches(row, "pocket_ai_audio_transcripts") for row in rows):
        pocket_archive_evidence = _pocket_audio_archive_evidence()
    return _proactive_source_coverage_report(
        principal_id=principal_id,
        rows=rows,
        observation_repository=observation_repository,
        observed_at=observed_at,
        observation_limit=observation_limit,
        source="in_process_runtime:proactive_source_coverage",
        pocket_archive_evidence=pocket_archive_evidence,
    )


@contextmanager
def _suppress_container_postgres_fallback_warning():
    logger = logging.getLogger("ea.container")

    class _PostgresFallbackFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            try:
                message = record.getMessage()
            except Exception:
                message = str(getattr(record, "msg", "") or "")
            return "postgres runtime profile unavailable, switching whole container to memory" not in message

    noise_filter = _PostgresFallbackFilter()
    logger.addFilter(noise_filter)
    try:
        yield
    finally:
        logger.removeFilter(noise_filter)


def _finalize_proactive_source_coverage_report(
    report: Mapping[str, object],
    *,
    output_format: str,
) -> dict[str, object]:
    finalized = dict(report)
    finalized.update(_next_action_surface_fields(str(finalized.get("next_action") or "")))
    if output_format == "operator" and not str(finalized.get("operator_text") or "").strip():
        missing = [str(item) for item in list(finalized.get("missing_lane_keys") or [])]
        missing_text = ",".join(missing[:4])
        if len(missing) > 4:
            missing_text += f"+{len(missing) - 4}"
        finalized["operator_text"] = (
            f"proactive_source_coverage status={finalized['status']}; "
            f"observed={int(finalized['observed_lane_count'])}/{int(finalized['lane_count'])}; "
            f"rows={int(finalized['observation_row_count'])}; missing={missing_text or 'none'}"
        )
    return finalized


def _should_expand_source_coverage_window(report: Mapping[str, object], *, observation_limit: int) -> bool:
    if int(observation_limit or 0) >= 4000:
        return False
    if not bool(report.get("probe_ok")):
        return False
    if str(report.get("blocking_reason") or "").strip():
        return False
    if not list(report.get("missing_lane_keys") or []):
        return False
    return int(report.get("observation_row_count") or 0) >= max(int(observation_limit or 0), 1)


def _docker_compose_exec_json(
    *,
    compose_file: str,
    service: str,
    command: list[str],
    timeout_seconds: float,
) -> tuple[int, dict[str, Any], str, str]:
    effective_timeout = max(float(timeout_seconds or 1.0), 1.0)
    timeout_label = f"{effective_timeout:g}s"
    exec_command = [
        "docker",
        "compose",
        "-f",
        compose_file,
        "exec",
        "-T",
        service,
        "timeout",
        "--kill-after=2s",
        timeout_label,
        *command,
    ]
    try:
        completed = subprocess.run(
            exec_command,
            cwd=ROOT,
            env=_docker_compose_project_env(),
            capture_output=True,
            text=True,
            check=False,
            start_new_session=True,
            timeout=effective_timeout + 5.0,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
        return (
            124,
            {
                "ok": False,
                "timed_out": True,
                "reason": f"TimeoutExpired:{effective_timeout:g}s",
                "timeout_seconds": effective_timeout,
            },
            stdout,
            stderr,
        )
    payload = _json_from_stdout(str(completed.stdout or ""))
    if int(completed.returncode or 0) == 124 and not payload:
        payload = {
            "ok": False,
            "timed_out": True,
            "reason": f"TimeoutExpired:{effective_timeout:g}s",
            "timeout_seconds": effective_timeout,
        }
    return (
        int(completed.returncode or 0),
        payload,
        str(completed.stdout or ""),
        str(completed.stderr or ""),
    )


def _remaining_probe_timeout(deadline: float, *, minimum: float = 1.0) -> float:
    return max(float(deadline) - time.monotonic(), minimum)


def _probe_deadline_expired(deadline: float, *, minimum: float = 1.0) -> bool:
    return (float(deadline) - time.monotonic()) <= minimum


def _path_text(value: object) -> str:
    if isinstance(value, Path):
        return value.as_posix()
    return str(value or "").strip()


def _callback_row_status(row: Mapping[str, object]) -> str:
    return str(row.get("status") or "").strip().lower()


def _callback_row_expires_at_timestamp(value: object) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return 0.0


def _callback_row_is_live(row: Mapping[str, object]) -> bool:
    expires_at = _callback_row_expires_at_timestamp(row.get("expires_at"))
    return expires_at <= 0.0 or expires_at > datetime.now(UTC).timestamp()


def _proactive_runtime_bundle_snapshot(
    *,
    prefer_browse_backed_delivery: bool = False,
) -> tuple[dict[str, object], dict[str, object]]:
    inputs = _proactive_runtime_inputs()
    bundle = dict(
        load_runtime_artifact_bundle(
            root=Path(inputs["root"]),
            state_path=str(inputs["state_path"]),
            receipt_path=str(inputs["receipt_path"]),
            stage_packet_dir=str(inputs["stage_packet_dir"]),
            safe_work_result_dir=str(inputs["safe_work_result_dir"]),
            prefer_browse_backed_delivery=prefer_browse_backed_delivery,
        )
    )
    return inputs, bundle


def _probe_proactive_artifacts_in_process_payload(
    *,
    prefer_browse_backed_delivery: bool = False,
) -> dict[str, object]:
    _inputs, bundle = _proactive_runtime_bundle_snapshot(
        prefer_browse_backed_delivery=prefer_browse_backed_delivery,
    )
    stage_packet = dict(bundle.get("stage_packet") or {})
    safe_work_result = dict(bundle.get("safe_work_result") or {})
    callback_dir_value = bundle.get("approval_callback_dir")
    callback_dir = callback_dir_value if isinstance(callback_dir_value, Path) else Path(str(callback_dir_value or ""))
    summary = approval_callback_runtime_summary(
        approval_callback_dir=callback_dir,
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    )
    return {
        "probe_ok": True,
        "prefer_browse_backed_delivery": bool(prefer_browse_backed_delivery),
        "state_path": _path_text(bundle.get("state_path")),
        "run_receipt_path": _path_text(bundle.get("run_receipt_path")),
        "action_required_only_quiet_receipt_path": _path_text(bundle.get("action_required_only_quiet_receipt_path")),
        "stage_packet_dir": _path_text(bundle.get("stage_packet_dir")),
        "safe_work_result_dir": _path_text(bundle.get("safe_work_result_dir")),
        "approval_outcome_path": _path_text(bundle.get("approval_outcome_path")),
        "approval_callback_dir": callback_dir.as_posix(),
        "approval_callback_dir_exists": bool(summary.get("approval_callback_dir_exists")),
        "approval_callback_dir_writable": bool(summary.get("approval_callback_dir_writable")),
        "approval_callback_record_count": int(summary.get("approval_callback_record_count") or 0),
        "approval_callback_pending_count": int(summary.get("approval_callback_pending_count") or 0),
        "approval_callback_raw_pending_count": int(summary.get("approval_callback_raw_pending_count") or 0),
        "approval_callback_live_pending_count": int(summary.get("approval_callback_live_pending_count") or 0),
        "approval_callback_unexpired_pending_count": int(summary.get("approval_callback_unexpired_pending_count") or 0),
        "approval_callback_noncurrent_pending_count": int(summary.get("approval_callback_noncurrent_pending_count") or 0),
        "approval_callback_expired_pending_count": int(summary.get("approval_callback_expired_pending_count") or 0),
        "approval_callback_stale_pending_count": int(summary.get("approval_callback_stale_pending_count") or 0),
        "approval_callback_recorded_count": int(summary.get("approval_callback_recorded_count") or 0),
        "approval_callback_expired_count": int(summary.get("approval_callback_expired_count") or 0),
        "approval_callback_superseded_count": int(summary.get("approval_callback_superseded_count") or 0),
        "approval_callback_terminal_count": int(summary.get("approval_callback_terminal_count") or 0),
        "current_packet_callback_record_count": int(summary.get("current_packet_callback_record_count") or 0),
        "current_packet_callback_pending_count": int(summary.get("current_packet_callback_pending_count") or 0),
        "current_packet_callback_raw_pending_count": int(summary.get("current_packet_callback_raw_pending_count") or 0),
        "current_packet_callback_expired_pending_count": int(summary.get("current_packet_callback_expired_pending_count") or 0),
        "current_packet_callback_stale_pending_count": int(summary.get("current_packet_callback_stale_pending_count") or 0),
        "current_packet_callback_recorded_count": int(summary.get("current_packet_callback_recorded_count") or 0),
        "current_packet_callback_expired_count": int(summary.get("current_packet_callback_expired_count") or 0),
        "current_packet_callback_superseded_count": int(summary.get("current_packet_callback_superseded_count") or 0),
        "current_packet_live_callback_record_count": int(summary.get("current_packet_live_callback_record_count") or 0),
        "current_packet_live_pending_count": int(summary.get("current_packet_live_pending_count") or 0),
        "current_packet_callback_latest_status": str(summary.get("current_packet_callback_latest_status") or "").strip(),
        "current_packet_callback_latest_expired": bool(summary.get("current_packet_callback_latest_expired")),
        "current_packet_callback_latest_created_at": str(summary.get("current_packet_callback_latest_created_at") or "").strip(),
        "current_packet_callback_latest_expires_at": str(summary.get("current_packet_callback_latest_expires_at") or "").strip(),
        "current_packet_callback_latest_age_seconds": int(summary.get("current_packet_callback_latest_age_seconds") or 0),
        "current_packet_callback_latest_seconds_until_expiry": int(
            summary.get("current_packet_callback_latest_seconds_until_expiry") or 0
        ),
        "current_packet_callback_outcome": dict(bundle.get("current_packet_callback_outcome") or {}),
        "stage_packet_path": _path_text(bundle.get("stage_packet_path")),
        "safe_work_result_path": _path_text(bundle.get("safe_work_result_path")),
        "artifact_filter_reason": str(bundle.get("artifact_filter_reason") or "").strip(),
        "flat_search_enabled": bool(bundle.get("flat_search_enabled")),
        "run_receipt": dict(bundle.get("run_receipt") or {}),
        "action_required_only_quiet_receipt": dict(bundle.get("action_required_only_quiet_receipt") or {}),
        "stage_packet": stage_packet,
        "safe_work_result": safe_work_result,
        "approval_outcome": dict(bundle.get("approval_outcome") or {}),
    }


def _probe_proactive_approval_capture_in_process_payload(*, principal_id: str) -> dict[str, object]:
    from app.services.proactive_ooda_telegram_approval import _approval_callback_principal_candidates
    from app.services.telegram_delivery import _telegram_bot_registry, resolve_primary_telegram_binding

    _inputs, bundle = _proactive_runtime_bundle_snapshot()
    stage_packet = dict(bundle.get("stage_packet") or {})
    safe_work_result = dict(bundle.get("safe_work_result") or {})
    packet_ref = _proactive_stage_packet_ref(stage_packet)
    staged_artifact_ref = _proactive_staged_artifact_ref(safe_work_result)
    callback_dir_value = bundle.get("approval_callback_dir")
    callback_dir = callback_dir_value if isinstance(callback_dir_value, Path) else Path(str(callback_dir_value or ""))
    rows: list[dict[str, object]] = []
    if callback_dir.is_dir():
        for candidate in callback_dir.glob("*.json"):
            try:
                record = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(record, dict):
                rows.append(record)
    live_pending_rows = [
        row for row in rows if _callback_row_status(row) == "pending" and _callback_row_is_live(row)
    ]
    current_rows = [
        row
        for row in rows
        if str(row.get("packet_ref") or "").strip() == packet_ref
        and str(row.get("staged_artifact_ref") or "").strip() == staged_artifact_ref
    ]
    if not current_rows and len(live_pending_rows) == 1:
        inferred_row = dict(live_pending_rows[0] or {})
        inferred_packet_ref = str(inferred_row.get("packet_ref") or "").strip()
        inferred_staged_artifact_ref = str(inferred_row.get("staged_artifact_ref") or "").strip()
        if inferred_packet_ref and inferred_staged_artifact_ref:
            packet_ref = inferred_packet_ref
            staged_artifact_ref = inferred_staged_artifact_ref
            current_rows = [inferred_row]
    current_rows.sort(key=lambda row: str(row.get("created_at") or ""))
    current_live_pending_rows = [
        row for row in current_rows if _callback_row_status(row) == "pending" and _callback_row_is_live(row)
    ]
    latest = current_live_pending_rows[-1] if current_live_pending_rows else (current_rows[-1] if current_rows else {})
    record_principal_hash = str(latest.get("principal_id_hash") or "").strip()
    container = build_container()
    candidates = tuple(
        _approval_callback_principal_candidates(
            container=container,
            principal_id=str(principal_id or "").strip(),
            include_delivery_defaults=True,
        )
    )
    candidate_hashes = tuple(_hash_text(candidate) for candidate in candidates if str(candidate or "").strip())
    principal_match_ready = bool(record_principal_hash and record_principal_hash in candidate_hashes)
    binding = resolve_primary_telegram_binding(container.tool_runtime, principal_id=str(principal_id or "").strip())
    telegram_reason = ""
    chat_ref = ""
    bot_key = ""
    bot_token_present = False
    if binding is None:
        telegram_reason = "telegram_binding_not_found"
    else:
        metadata = dict(getattr(binding, "auth_metadata_json", None) or {})
        chat_ref = str(metadata.get("default_chat_ref") or getattr(binding, "external_account_ref", "") or "").strip()
        bot_key = str(metadata.get("bot_key") or "default").strip() or "default"
        token = str(dict((_telegram_bot_registry().get(bot_key) or {})).get("token") or "").strip()
        bot_token_present = bool(token)
        if not chat_ref:
            telegram_reason = "telegram_chat_ref_missing"
        elif not bot_token_present:
            telegram_reason = "telegram_bot_token_missing"
    summary = approval_callback_runtime_summary(
        approval_callback_dir=callback_dir,
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    )
    latest_created_at = str(latest.get("created_at") or "").strip()
    latest_expires_at = str(latest.get("expires_at") or "").strip()
    latest_age_seconds = _utc_age_seconds(latest_created_at) or 0
    latest_expires_at_dt = _parse_utc_datetime(latest_expires_at)
    latest_seconds_until_expiry = (
        max(0, int((latest_expires_at_dt - datetime.now(UTC)).total_seconds()))
        if latest_expires_at_dt is not None
        else 0
    )
    return {
        "ok": True,
        "callback_dir_exists": callback_dir.is_dir(),
        "callback_record_count": len(rows),
        "current_packet_ref_sha256": _hash_text(packet_ref),
        "current_staged_artifact_ref_sha256": _hash_text(staged_artifact_ref),
        "current_packet_refs_present": bool(packet_ref and staged_artifact_ref),
        "current_packet_callback_record_count": len(current_rows),
        "current_packet_live_pending_count": len(current_live_pending_rows),
        "current_packet_callback_latest_status": str(
            summary.get("current_packet_callback_latest_status") or latest.get("status") or ""
        ).strip(),
        "current_packet_callback_latest_expired": bool(
            summary.get("current_packet_callback_latest_expired")
            if summary.get("current_packet_callback_latest_status")
            else bool(latest) and not _callback_row_is_live(latest)
        ),
        "current_packet_callback_latest_age_seconds": int(
            summary.get("current_packet_callback_latest_age_seconds")
            or latest_age_seconds
        ),
        "current_packet_callback_latest_seconds_until_expiry": int(
            summary.get("current_packet_callback_latest_seconds_until_expiry")
            or latest_seconds_until_expiry
        ),
        "callback_principal_hash_present": bool(record_principal_hash),
        "candidate_principal_hash_count": len(set(candidate_hashes)),
        "principal_match_ready": principal_match_ready,
        "telegram_binding_ready": not bool(telegram_reason),
        "telegram_blocking_reason": telegram_reason,
        "telegram_chat_ref_present": bool(chat_ref),
        "telegram_chat_ref_sha256": _hash_text(chat_ref),
        "telegram_bot_key_present": bool(bot_key),
        "telegram_bot_token_present": bot_token_present,
        "privacy": {
            "raw_callback_token_exposed": False,
            "raw_principal_id_exposed": False,
            "raw_chat_ref_exposed": False,
            "raw_packet_ref_exposed": False,
            "raw_staged_artifact_ref_exposed": False,
        },
    }


def _record_current_proactive_approval_in_process(
    *,
    principal_id: str,
    outcome: str,
    evidence: str,
    actor: str,
    source_kind: str,
    expected_packet_ref: str,
    expected_staged_artifact_ref: str,
) -> dict[str, object]:
    from app.services.proactive_ooda_approval_reissue import record_current_proactive_ooda_approval_outcome

    inputs = _proactive_runtime_inputs()
    result = record_current_proactive_ooda_approval_outcome(
        principal_id=str(principal_id or "").strip(),
        outcome=str(outcome or "").strip(),
        evidence=str(evidence or "").strip(),
        actor=str(actor or "").strip(),
        root=Path(inputs["root"]),
        state_path=str(inputs["state_path"]),
        receipt_path=str(inputs["receipt_path"]),
        stage_packet_dir=str(inputs["stage_packet_dir"]),
        safe_work_result_dir=str(inputs["safe_work_result_dir"]),
        source_kind=str(source_kind or "").strip() or "operator",
        expected_packet_ref=str(expected_packet_ref or "").strip(),
        expected_staged_artifact_ref=str(expected_staged_artifact_ref or "").strip(),
    )
    return dict(_jsonify_runtime_value(result))


def _docker_compose_service_command(
    *,
    compose_file: str,
    command: list[str],
    timeout_seconds: float,
) -> dict[str, object]:
    effective_compose_file = str(compose_file or DEFAULT_WHATSAPP_WEB_COMPOSE_FILE).strip()
    try:
        completed = subprocess.run(
            ["docker", "compose", "-f", effective_compose_file, *command],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "exit_code": 124,
            "reason": f"TimeoutExpired:{float(timeout_seconds):g}s",
            "stdout_present": False,
            "stderr_present": False,
        }
    except Exception as exc:
        return {
            "ok": False,
            "exit_code": 127,
            "reason": type(exc).__name__,
            "stdout_present": False,
            "stderr_present": False,
        }
    exit_code = int(completed.returncode or 0)
    return {
        "ok": exit_code == 0,
        "exit_code": exit_code,
        "reason": "ok" if exit_code == 0 else f"docker_compose_exit_{exit_code}",
        "stdout_present": bool(str(completed.stdout or "").strip()),
        "stderr_present": bool(str(completed.stderr or "").strip()),
    }


def _docker_inspect_container_json(
    container_name: str,
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    effective_container_name = str(container_name or "").strip()
    if not effective_container_name:
        return {}
    try:
        completed = subprocess.run(
            ["docker", "inspect", effective_container_name],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(float(timeout_seconds or 15.0), 1.0),
        )
    except Exception:
        return {}
    if int(completed.returncode or 0) != 0:
        return {}
    try:
        payload = json.loads(str(completed.stdout or "[]"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        return {}
    return dict(payload[0])


def _host_root_disk_posture() -> dict[str, object]:
    try:
        usage = shutil.disk_usage("/")
    except Exception:
        return {
            "usage_percent": None,
            "available_bytes": None,
            "available_gb": None,
        }
    total = int(usage.total or 0)
    free = int(usage.free or 0)
    usage_percent = round(((total - free) / total) * 100.0, 1) if total > 0 else None
    return {
        "usage_percent": usage_percent,
        "available_bytes": free,
        "available_gb": round(free / (1024 ** 3), 2),
    }


def _container_state_error_kind(state: Mapping[str, object]) -> str:
    error = str(state.get("Error") or "").strip().lower()
    if "no space left on device" in error:
        return "host_disk_pressure"
    if bool(state.get("OOMKilled")):
        return "oom_killed"
    if error:
        return "container_error"
    try:
        exit_code = int(state.get("ExitCode") or 0)
    except Exception:
        exit_code = 0
    if exit_code == 137:
        return "terminated_137"
    return ""


def _docker_restart_container(
    container_name: str,
    *,
    timeout_seconds: float = 30.0,
) -> dict[str, object]:
    normalized_container_name = str(container_name or "").strip()
    if not normalized_container_name:
        return {
            "ok": False,
            "exit_code": 127,
            "reason": "container_name_missing",
            "stdout_present": False,
            "stderr_present": False,
        }
    try:
        completed = subprocess.run(
            ["docker", "restart", normalized_container_name],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(float(timeout_seconds or 30.0), 1.0),
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "exit_code": 124,
            "reason": f"TimeoutExpired:{float(timeout_seconds):g}s",
            "stdout_present": False,
            "stderr_present": False,
        }
    except Exception as exc:
        return {
            "ok": False,
            "exit_code": 127,
            "reason": type(exc).__name__,
            "stdout_present": False,
            "stderr_present": False,
        }
    exit_code = int(completed.returncode or 0)
    return {
        "ok": exit_code == 0,
        "exit_code": exit_code,
        "reason": "ok" if exit_code == 0 else f"docker_restart_exit_{exit_code}",
        "stdout_present": bool(str(completed.stdout or "").strip()),
        "stderr_present": bool(str(completed.stderr or "").strip()),
    }


def _http_error_payload(exc: urllib.error.HTTPError) -> dict[str, Any]:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except Exception:
        payload = {}
    result = dict(payload) if isinstance(payload, dict) else {}
    result.setdefault("status_code", int(getattr(exc, "code", 0) or 0))
    result.setdefault("reason", str(result.get("reason") or getattr(exc, "reason", "") or type(exc).__name__))
    return result


def _runtime_container_name() -> str:
    return _env("EA_RUNTIME_CONTAINER", DEFAULT_RUNTIME_CONTAINER)


def _runtime_container_exec_json(
    *,
    code: str,
    timeout_seconds: float = 20.0,
) -> tuple[int, dict[str, Any], str]:
    container = _runtime_container_name()
    if not container:
        return 127, {"ok": False, "reason": "runtime_container_unconfigured"}, ""
    effective_timeout = max(float(timeout_seconds or 20.0), 1.0)
    try:
        proc = subprocess.run(
            ["docker", "exec", container, "timeout", "--kill-after=2s", f"{effective_timeout:g}s", "python3", "-c", code],
            text=True,
            capture_output=True,
            check=False,
            timeout=effective_timeout + 5.0,
        )
    except subprocess.TimeoutExpired:
        return 124, {"ok": False, "reason": f"TimeoutExpired:{effective_timeout:g}s"}, container
    except Exception as exc:
        return 127, {"ok": False, "reason": type(exc).__name__}, container
    payload = _json_from_stdout(str(proc.stdout or ""))
    if int(proc.returncode or 0) == 124:
        payload.setdefault("ok", False)
        payload.setdefault("reason", f"TimeoutExpired:{effective_timeout:g}s")
    elif int(proc.returncode or 0) != 0:
        payload.setdefault("ok", False)
        payload.setdefault("reason", f"runtime_container_exec_exit_{int(proc.returncode or 0)}")
    return int(proc.returncode or 0), payload, container


def _runtime_container_stage_file(
    local_path: Path,
    *,
    timeout_seconds: float = 20.0,
) -> tuple[bool, str, str, str]:
    container = _runtime_container_name()
    if not container:
        return False, "", "", "runtime_container_unconfigured"
    try:
        resolved = local_path.resolve()
        stat = resolved.stat()
    except OSError:
        return False, container, "", "local_file_missing"
    suffix = re.sub(r"[^A-Za-z0-9_.-]+", "-", resolved.suffix or ".bin")[:24] or ".bin"
    digest = hashlib.sha256(f"{resolved}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8")).hexdigest()[:16]
    remote_path = f"/tmp/ea-live-ops-document-{digest}{suffix}"
    try:
        payload = resolved.read_bytes()
    except OSError:
        return False, container, "", "local_file_unreadable"
    try:
        write_proc = subprocess.run(
            ["docker", "exec", "-i", container, "sh", "-lc", f"cat > {remote_path!r} && chmod 600 {remote_path!r}"],
            input=payload,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return False, container, "", f"stage_write_timeout:{float(timeout_seconds):g}s"
    except Exception as exc:
        return False, container, "", type(exc).__name__
    if int(write_proc.returncode or 0) != 0:
        return False, container, remote_path, f"stage_write_exit_{int(write_proc.returncode or 0)}"
    return True, container, remote_path, ""


def _runtime_container_remove_file(container: str, remote_path: str, *, timeout_seconds: float = 10.0) -> None:
    if not str(container or "").strip() or not str(remote_path or "").strip():
        return
    try:
        subprocess.run(
            ["docker", "exec", container, "rm", "-f", str(remote_path)],
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except Exception:
        return


def _runtime_container_preflight(*, timeout_seconds: float = 45.0) -> dict[str, object]:
    code = (
        "import json\n"
        "from app.services.audiobook_epub_pipeline import audiobook_runtime_preflight\n"
        "print(json.dumps(audiobook_runtime_preflight(), sort_keys=True))\n"
    )
    exit_code, payload, _container_name = _runtime_container_exec_json(
        code=code,
        timeout_seconds=max(float(timeout_seconds or 45.0), 1.0),
    )
    if exit_code != 0:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _sanitized_unmixr_credit_balance(payload: Mapping[str, object]) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    allowed_error_types = {
        "Exception",
        "HTTPError",
        "JSONDecodeError",
        "OSError",
        "TimeoutError",
        "URLError",
        "UnicodeDecodeError",
        "ValueError",
    }

    def _nonnegative_int(value: object, *, maximum: int | None = None) -> int:
        try:
            normalized = max(int(value or 0), 0)
        except (TypeError, ValueError, OverflowError):
            normalized = 0
        return min(normalized, maximum) if maximum is not None else normalized

    for index, raw_row in enumerate(list(payload.get("rows") or []), start=1):
        if not isinstance(raw_row, Mapping):
            continue
        http_status = _nonnegative_int(raw_row.get("http_status"), maximum=599)
        row: dict[str, object] = {"slot": index, "http_status": http_status}
        if http_status == 200:
            row.update(
                {
                    "prebuilt_credits": _nonnegative_int(raw_row.get("prebuilt_credits")),
                    "cloned_credits": _nonnegative_int(raw_row.get("cloned_credits")),
                    "cloned_profile": _nonnegative_int(raw_row.get("cloned_profile")),
                }
            )
        else:
            error_type = str(raw_row.get("error_type") or "Exception").strip()
            row["error_type"] = error_type if error_type in allowed_error_types else "Exception"
        rows.append(row)

    successful = [row for row in rows if int(row.get("http_status") or 0) == 200]
    prebuilt = [int(row.get("prebuilt_credits") or 0) for row in successful]
    cloned = [int(row.get("cloned_credits") or 0) for row in successful]
    observed_at = str(payload.get("observed_at") or "").strip()
    try:
        parsed_observed_at = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        if parsed_observed_at.tzinfo is None:
            raise ValueError("timezone_required")
        observed_at = parsed_observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError):
        observed_at = _utc_now()

    return {
        "contract_name": "ea.unmixr_credit_balance.v1",
        "status": "pass" if successful else "probe_failed",
        "observed_at": observed_at,
        "configured_slot_count": len(rows),
        "successful_slot_count": len(successful),
        "positive_prebuilt_slot_count": sum(1 for value in prebuilt if value > 0),
        "prebuilt_credits_min": min(prebuilt) if prebuilt else 0,
        "prebuilt_credits_max": max(prebuilt) if prebuilt else 0,
        "cloned_credits_min": min(cloned) if cloned else 0,
        "cloned_credits_max": max(cloned) if cloned else 0,
        "rows": rows,
        "raw_credentials_exposed": False,
        "raw_response_bodies_exposed": False,
    }


def _runtime_container_unmixr_credit_balance(*, timeout_seconds: float = 30.0) -> dict[str, object]:
    code = """
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from app.services.memorial_openvoice import _unmixr_api_key_slots

rows = []
for index, (_label, api_key) in enumerate(_unmixr_api_key_slots(), start=1):
    row = {"slot": index}
    try:
        request = urllib.request.Request(
            "https://unmixr.com/api/v1/credit-balance/",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
            credits = dict(payload.get("credits") or {}) if isinstance(payload, dict) else {}
            row.update(
                {
                    "http_status": int(getattr(response, "status", 200) or 200),
                    "prebuilt_credits": int(credits.get("prebuilt_credits") or 0),
                    "cloned_credits": int(credits.get("cloned_credits") or 0),
                    "cloned_profile": int(credits.get("cloned_profile") or 0),
                }
            )
    except urllib.error.HTTPError as exc:
        row.update({"http_status": int(exc.code), "error_type": "HTTPError"})
    except Exception as exc:
        row.update({"http_status": 0, "error_type": type(exc).__name__})
    rows.append(row)

successful = [row for row in rows if int(row.get("http_status") or 0) == 200]
prebuilt = [int(row.get("prebuilt_credits") or 0) for row in successful]
cloned = [int(row.get("cloned_credits") or 0) for row in successful]
print(
    json.dumps(
        {
            "contract_name": "ea.unmixr_credit_balance.v1",
            "status": "pass" if successful else "probe_failed",
            "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "configured_slot_count": len(rows),
            "successful_slot_count": len(successful),
            "positive_prebuilt_slot_count": sum(1 for value in prebuilt if value > 0),
            "prebuilt_credits_min": min(prebuilt) if prebuilt else 0,
            "prebuilt_credits_max": max(prebuilt) if prebuilt else 0,
            "cloned_credits_min": min(cloned) if cloned else 0,
            "cloned_credits_max": max(cloned) if cloned else 0,
            "rows": rows,
            "raw_credentials_exposed": False,
            "raw_response_bodies_exposed": False,
        },
        sort_keys=True,
    )
)
""".strip()
    exit_code, payload, container = _runtime_container_exec_json(
        code=code,
        timeout_seconds=max(float(timeout_seconds or 30.0), 1.0),
    )
    if exit_code != 0 or not isinstance(payload, dict):
        raw_reason = str(payload.get("reason") or "").strip() if isinstance(payload, dict) else ""
        if exit_code == 124 or raw_reason.startswith("TimeoutExpired"):
            reason = "runtime_container_timeout"
        elif raw_reason == "runtime_container_unconfigured":
            reason = raw_reason
        else:
            reason = f"runtime_container_exec_exit_{exit_code}"
        return {
            "contract_name": "ea.unmixr_credit_balance.v1",
            "status": "probe_failed",
            "reason": reason,
            "runtime_container": container,
            "raw_credentials_exposed": False,
            "raw_response_bodies_exposed": False,
        }
    return _sanitized_unmixr_credit_balance(payload)


@lru_cache(maxsize=1)
def _container():
    return build_container(settings=settings_with_storage_backend(get_settings(), "memory"))


def _provider_display_name(provider_key: str) -> str:
    try:
        state = _container().provider_registry.binding_state(provider_key)
    except Exception:
        state = None
    if state is not None and str(state.display_name or "").strip():
        return str(state.display_name)
    return provider_key.replace("_", " ")


def _normalize_provider_key(value: object) -> str:
    fallback = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    try:
        registry = _container().provider_registry
        normalizer = getattr(registry, "_normalize_provider_key", None)
    except Exception:
        return fallback
    if callable(normalizer):
        normalized = str(normalizer(value) or "").strip()
        return normalized or fallback
    return fallback


def _operator_text_for_provider(report: dict[str, object]) -> str:
    pieces = [
        f"provider={report.get('provider_key')}",
        f"state={report.get('status')}",
    ]
    if report.get("account_label"):
        pieces.append(f"account={report['account_label']}")
    if report.get("remaining") not in (None, "") and report.get("unit"):
        pieces.append(f"remaining={report['remaining']} {report['unit']}")
    if report.get("refresh_at"):
        pieces.append(f"refresh_at={report['refresh_at']}")
    if report.get("observed_at"):
        pieces.append(f"observed_at={report['observed_at']}")
    if report.get("source"):
        pieces.append(f"source={report['source']}")
    raw = report.get("raw") if isinstance(report.get("raw"), dict) else {}
    for field_name, label in (
        ("live_ready_slot_count", "live_ready_slots"),
        ("live_positive_balance_slot_count", "positive_slots"),
        ("account_count", "accounts"),
    ):
        if raw.get(field_name) not in (None, ""):
            pieces.append(f"{label}={raw[field_name]}")
    return "; ".join(str(item) for item in pieces if str(item).strip())


def _pushbullet_reason_from_receipt(receipt: Mapping[str, object]) -> str:
    missing_setup = _string_list(receipt.get("missing_setup"))
    if missing_setup:
        return ",".join(missing_setup[:3])
    for item in list(receipt.get("live_probes") or []):
        if not isinstance(item, Mapping):
            continue
        status = str(item.get("status") or "").strip()
        if status and status != "pass":
            reason = str(item.get("reason") or status).strip() or status
            client_key = str(item.get("client_key") or "").strip()
            return f"{client_key}:{reason}" if client_key else reason
    return ""


def _operator_text_for_pushbullet(report: Mapping[str, object]) -> str:
    raw = dict(report.get("raw") or {}) if isinstance(report.get("raw"), Mapping) else {}
    pieces = [
        f"pushbullet_readiness status={report.get('status') or 'unknown'}",
        f"ready={str(bool(report.get('ready'))).lower()}",
    ]
    if report.get("account_label"):
        pieces.append(f"account={report['account_label']}")
    if report.get("reason"):
        pieces.append(f"reason={report['reason']}")
    required_client_keys = _string_list(raw.get("required_client_keys"))
    if required_client_keys:
        pieces.append(f"required_clients={len(required_client_keys)}")
    if raw.get("configured_required_client_count") is not None:
        pieces.append(f"configured_required={int(raw.get('configured_required_client_count') or 0)}")
    if raw.get("token_present_required_client_count") is not None:
        pieces.append(f"token_ready={int(raw.get('token_present_required_client_count') or 0)}")
    missing_client_keys = _string_list(raw.get("missing_client_keys"))
    if missing_client_keys:
        pieces.append(f"missing_clients={','.join(missing_client_keys)}")
    missing_token_keys = _string_list(raw.get("missing_token_keys"))
    if missing_token_keys:
        pieces.append(f"missing_tokens={','.join(missing_token_keys)}")
    if report.get("next_action"):
        pieces.append(f"next={report['next_action']}")
    if report.get("observed_at"):
        pieces.append(f"observed_at={report['observed_at']}")
    if report.get("source"):
        pieces.append(f"source={report['source']}")
    return "; ".join(str(item) for item in pieces if str(item).strip())


def _pushbullet_account_label_from_receipt(receipt: Mapping[str, object]) -> tuple[str, str]:
    explicit_label = str(receipt.get("account_label") or "").strip()
    explicit_basis = str(receipt.get("account_label_basis") or "").strip()
    if explicit_label:
        return explicit_label, explicit_basis

    required_client_keys = _string_list(receipt.get("required_client_keys"))
    default_client_ref = str(receipt.get("default_client_ref") or "").strip()
    clients = [
        dict(item)
        for item in list(receipt.get("clients") or [])
        if isinstance(item, Mapping) and str(item.get("client_key") or "").strip()
    ]
    by_key = {str(item.get("client_key") or "").strip(): item for item in clients}
    if "default" in required_client_keys:
        if "default" in by_key:
            return "default", "literal_default_client"
        if default_client_ref:
            if default_client_ref in by_key:
                return f"default->{default_client_ref}", "default_client_ref"
            return f"default->{default_client_ref}(missing)", "default_client_ref_missing"
        return "default(missing)", "default_client_missing"
    for key in required_client_keys:
        if key in by_key:
            return key, "required_client"
    if required_client_keys:
        return f"{required_client_keys[0]}(missing)", "required_client_missing"
    if by_key:
        first_key = next(iter(sorted(by_key)))
        return first_key, "configured_client"
    return "", "missing"


def _provider_cost_pressure_runtime_code(window: str, principal_id: str) -> str:
    return "\n".join(
        (
            "import json, os, time",
            "from datetime import datetime, timezone",
            "from pathlib import Path",
            f"window = {json.dumps(str(window or '24h'))}",
            f"principal_id = {json.dumps(str(principal_id or '').strip())}",
            "def _window_seconds(value):",
            "    normalized = str(value or '24h').strip().lower()",
            "    if normalized == '7d':",
            "        return 604800.0",
            "    if normalized == '1h':",
            "        return 3600.0",
            "    return 86400.0",
            "def _num(value, default=0):",
            "    try:",
            "        if value in (None, ''):",
            "            return default",
            "        return float(value)",
            "    except Exception:",
            "        return default",
            "def _int(value, default=0):",
            "    return int(_num(value, default))",
            "aliases = {'1min': 'onemin', '1minai': 'onemin', '1min_ai': 'onemin', 'magicx': 'magixai', 'magicxai': 'magixai', 'gemini': 'gemini_vortex'}",
            "def _provider_key(value):",
            "    key = str(value or '').strip().lower().replace('-', '_').replace(' ', '_').replace('.', '')",
            "    return aliases.get(key, key)",
            "def _order(env_name, default):",
            "    raw = str(os.getenv(env_name, default) or default)",
            "    ordered = []",
            "    for item in raw.split(','):",
            "        key = _provider_key(item)",
            "        if key and key not in ordered:",
            "            ordered.append(key)",
            "    fallback = [_provider_key(item) for item in default.split(',') if _provider_key(item)]",
            "    return ordered or fallback",
            "ledger_dir = Path(os.getenv('EA_RESPONSES_PROVIDER_LEDGER_DIR') or '/data/provider-ledger')",
            "if not ledger_dir.exists() and Path('state').exists():",
            "    ledger_dir = Path('state')",
            "cache_path = ledger_dir / 'provider-health-cache' / 'lightweight.json'",
            "provider_health = {}",
            "cache_payload = {}",
            "try:",
            "    cache_payload = json.loads(cache_path.read_text(encoding='utf-8'))",
            "    provider_health = dict(cache_payload.get('payload') or {})",
            "except Exception:",
            "    provider_health = {}",
            "providers = dict(provider_health.get('providers') or {})",
            "provider_config = dict(provider_health.get('provider_config') or {})",
            "onemin = dict(providers.get('onemin') or {})",
            "soft_cap = _int(os.getenv('EA_RESPONSES_GEMINI_VORTEX_TOKEN_SOFT_CAP_24H') or provider_config.get('gemini_vortex_token_soft_cap_24h'), 200000)",
            "soft_cap_window = _num(os.getenv('EA_RESPONSES_GEMINI_VORTEX_TOKEN_SOFT_CAP_WINDOW_SECONDS') or provider_config.get('gemini_vortex_token_soft_cap_window_seconds'), 86400.0)",
            "now = time.time()",
            "dispatch_path = ledger_dir / 'provider_dispatch_events.jsonl'",
            "def _token_summary(seconds):",
            "    tokens_in = 0",
            "    tokens_out = 0",
            "    total_tokens = 0",
            "    count = 0",
            "    if dispatch_path.exists():",
            "        try:",
            "            lines = dispatch_path.read_text(encoding='utf-8', errors='ignore').splitlines()",
            "        except Exception:",
            "            lines = []",
            "        for line in lines:",
            "            if not line.strip():",
            "                continue",
            "            try:",
            "                row = json.loads(line)",
            "            except Exception:",
            "                continue",
            "            if str(row.get('provider_key') or '').strip() != 'gemini_vortex':",
            "                continue",
            "            if principal_id and str(row.get('principal_id') or '').strip() != principal_id:",
            "                continue",
            "            happened_at = _num(row.get('happened_at'), 0.0)",
            "            if happened_at <= 0 or now - happened_at > float(seconds):",
            "                continue",
            "            row_in = _int(row.get('tokens_in'), 0)",
            "            row_out = _int(row.get('tokens_out'), 0)",
            "            row_total = _int(row.get('total_tokens'), row_in + row_out)",
            "            tokens_in += max(row_in, 0)",
            "            tokens_out += max(row_out, 0)",
            "            total_tokens += max(row_total, 0)",
            "            count += 1",
            "    state = 'unlimited' if soft_cap <= 0 else 'soft_cap_exceeded' if total_tokens >= soft_cap else 'within_soft_cap'",
            "    return {'window_seconds': float(seconds), 'request_count': count, 'tokens_in': tokens_in, 'tokens_out': tokens_out, 'total_tokens': total_tokens, 'soft_cap_tokens': soft_cap, 'state': state}",
            "selected = _token_summary(_window_seconds(window))",
            "usage_24h = _token_summary(soft_cap_window or 86400.0)",
            "configured_slots = _int(onemin.get('configured_slots') or onemin.get('slot_count'), 0)",
            "ready_slots = _int(onemin.get('live_dispatchable_slot_count') or onemin.get('live_ready_slot_count') or onemin.get('ready_slot_count'), 0)",
            "degraded_slots = _int(onemin.get('degraded_slot_count') or onemin.get('observed_error_slot_count'), 0)",
            "unknown_slots = max(configured_slots - ready_slots - degraded_slots, 0)",
            "payload = {",
            "    'ok': True,",
            "    'observed_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),",
            "    'window': window,",
            "    'provider_order': _order('EA_RESPONSES_PROVIDER_ORDER', 'onemin,magixai,gemini_vortex'),",
            "    'groundwork_provider_order': _order('EA_RESPONSES_GROUNDWORK_PROVIDER_ORDER', 'onemin,magixai,gemini_vortex'),",
            "    'cheap_provider_order': _order('EA_RESPONSES_CHEAP_PROVIDER_ORDER', 'onemin,magixai,gemini_vortex'),",
            "    'hard_provider_order': _order('EA_RESPONSES_HARD_PROVIDER_ORDER', 'onemin,magixai,gemini_vortex'),",
            "    'cost_gated_lanes': ['audit', 'fast', 'groundwork', 'overflow', 'review', 'review_light'],",
            "    'gemini_token_usage': {",
            "        'provider_key': 'gemini_vortex',",
            "        'billing_truth_boundary': 'token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth',",
            "        'selected_window': selected,",
            "        '24h': usage_24h,",
            "    },",
            "    'onemin_capacity': {",
            "        'configured_slots': configured_slots,",
            "        'ready_slots': ready_slots,",
            "        'degraded_slots': degraded_slots,",
            "        'unknown_slots': unknown_slots,",
            "        'state': str(onemin.get('state') or ''),",
            "    },",
            "    'onemin_aggregate': {",
            "        'sum_free_credits': onemin.get('live_remaining_credits_total') if onemin.get('live_remaining_credits_total') is not None else onemin.get('estimated_remaining_credits_total'),",
            "        'remaining_percent_total': onemin.get('actual_remaining_percent_of_max') if onemin.get('actual_remaining_percent_of_max') is not None else onemin.get('remaining_percent_of_max'),",
            "        'current_pace_burn_credits_per_hour': onemin.get('estimated_burn_credits_per_hour'),",
            "        'hours_remaining_at_current_pace': onemin.get('estimated_hours_remaining_at_current_pace'),",
            "        'burn_basis': onemin.get('burn_estimate_basis') or onemin.get('credit_estimation_mode'),",
            "        'last_probe_at': onemin.get('last_probe_at') or onemin.get('last_actual_balance_at'),",
            "    },",
            "    'onemin_billing_aggregate': {",
            "        'sum_free_credits': onemin.get('actual_remaining_credits_total') if onemin.get('actual_remaining_credits_total') is not None else onemin.get('estimated_remaining_credits_total'),",
            "        'remaining_percent_total': onemin.get('actual_remaining_percent_of_max') if onemin.get('actual_remaining_percent_of_max') is not None else onemin.get('remaining_percent_of_max'),",
            "        'next_topup_at': onemin.get('next_topup_at'),",
            "        'hours_until_next_topup': onemin.get('hours_until_next_topup'),",
            "        'depletes_before_next_topup': onemin.get('depletes_before_next_topup'),",
            "        'basis_summary': onemin.get('balance_basis_summary'),",
            "    },",
            "    'fast_lane_route': {},",
            "}",
            "print(json.dumps(payload, sort_keys=True, default=str))",
        )
    )


def _runtime_provider_cost_pressure_payload(
    *,
    window: str,
    principal_id: str,
    timeout_seconds: float,
) -> tuple[int, dict[str, Any], str]:
    return _runtime_container_exec_json(
        code=_provider_cost_pressure_runtime_code(window, principal_id),
        timeout_seconds=timeout_seconds,
    )


def _provider_cost_pressure_payload_from_host(*, window: str, principal_id: str) -> dict[str, Any]:
    try:
        code = _provider_cost_pressure_runtime_code(window, principal_id)
        namespace: dict[str, Any] = {}
        # Reuse the same extraction contract as the runtime path without exposing the full status report.
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=dict(os.environ),
            capture_output=True,
            text=True,
            check=False,
            timeout=30.0,
        )
        if int(completed.returncode or 0) != 0:
            return {"ok": False, "reason": f"host_probe_exit_{int(completed.returncode or 0)}"}
        return _json_from_stdout(completed.stdout)
    except Exception as exc:
        return {"ok": False, "reason": type(exc).__name__}


def _number_or_none(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _provider_cost_pressure_report(
    *,
    payload: Mapping[str, object],
    source: str,
    observed_at: str,
    output_format: str = "json",
) -> dict[str, object]:
    provider_order = [str(item or "").strip() for item in list(payload.get("provider_order") or []) if str(item or "").strip()]
    fast_lane_route = dict(payload.get("fast_lane_route") or {})
    fast_order = [
        str(item or "").strip()
        for item in list(payload.get("fast_provider_order") or fast_lane_route.get("effective_order") or provider_order)
        if str(item or "").strip()
    ]
    groundwork_order = [
        str(item or "").strip()
        for item in list(payload.get("groundwork_provider_order") or [])
        if str(item or "").strip()
    ]
    cheap_order = [str(item or "").strip() for item in list(payload.get("cheap_provider_order") or []) if str(item or "").strip()]
    hard_order = [str(item or "").strip() for item in list(payload.get("hard_provider_order") or []) if str(item or "").strip()]
    gemini = dict(payload.get("gemini_token_usage") or {})
    selected = dict(gemini.get("selected_window") or {})
    usage_24h = dict(gemini.get("24h") or {})
    onemin_capacity = dict(payload.get("onemin_capacity") or {})
    onemin_aggregate = dict(payload.get("onemin_aggregate") or {})
    onemin_billing = dict(payload.get("onemin_billing_aggregate") or {})
    total_tokens_24h = int(usage_24h.get("total_tokens") or 0)
    soft_cap_tokens = int(usage_24h.get("soft_cap_tokens") or selected.get("soft_cap_tokens") or 0)
    soft_cap_percent = None
    if soft_cap_tokens > 0:
        soft_cap_percent = round((float(total_tokens_24h) / float(soft_cap_tokens)) * 100.0, 2)
    token_state = str(usage_24h.get("state") or selected.get("state") or "").strip() or "unknown"
    onemin_ready_slots = int(onemin_capacity.get("ready_slots") or 0)
    onemin_configured_slots = int(onemin_capacity.get("configured_slots") or 0)
    onemin_unknown_slots = int(onemin_capacity.get("unknown_slots") or 0)
    onemin_state = str(onemin_capacity.get("state") or "").strip().lower()
    onemin_probe_pending = bool(
        onemin_ready_slots <= 0
        and onemin_configured_slots > 0
        and (onemin_unknown_slots > 0 or onemin_state == "unknown")
    )
    onemin_usable = onemin_ready_slots > 0 or onemin_probe_pending
    onemin_first = bool(provider_order and provider_order[0] == "onemin")
    fast_onemin_first = bool(fast_order and fast_order[0] == "onemin")
    cheap_onemin_first = bool(cheap_order and cheap_order[0] == "onemin")
    groundwork_onemin_first = bool(groundwork_order and groundwork_order[0] == "onemin")
    hard_onemin_first = bool(hard_order and hard_order[0] == "onemin")
    onemin_preferred_whenever_usable = (
        onemin_first
        and fast_onemin_first
        and cheap_onemin_first
        and groundwork_onemin_first
        and hard_onemin_first
    )
    billing_truth_boundary = str(gemini.get("billing_truth_boundary") or "").strip()
    cost_control_active = (
        onemin_preferred_whenever_usable
        and billing_truth_boundary == "token_ledger_is_cost_pressure_telemetry_not_google_cloud_billing_truth"
        and token_state in {"within_soft_cap", "soft_cap_exceeded", "unlimited"}
    )
    if not cost_control_active:
        status = "misconfigured"
    elif token_state == "soft_cap_exceeded":
        status = "gemini_soft_cap_exceeded"
    elif onemin_probe_pending:
        status = "active_cost_control_onemin_probe_pending"
    elif not onemin_usable:
        status = "active_cost_control_onemin_not_live_ready"
    else:
        status = "active_cost_control"
    if token_state == "soft_cap_exceeded":
        gemini_background_gate = "closed"
    elif token_state == "unlimited":
        gemini_background_gate = "unlimited"
    else:
        gemini_background_gate = "open"
    routing_decision = (
        "prefer_onemin_background_and_remove_gemini_from_cost_gated_background_lanes"
        if token_state == "soft_cap_exceeded"
        else "prefer_onemin_background_pending_probe_with_gemini_fallback_only"
        if onemin_probe_pending
        else "prefer_onemin_background_when_usable"
        if onemin_usable
        else "keep_onemin_first_but_use_cost_gated_fallback_until_onemin_ready"
    )
    report: dict[str, object] = {
        "probe_ok": True,
        "status": status,
        "observed_at": str(payload.get("observed_at") or observed_at).strip(),
        "source": source,
        "window": str(payload.get("window") or "").strip(),
        "primary_background_provider": provider_order[0] if provider_order else "",
        "provider_order": provider_order,
        "fast_provider_order": fast_order,
        "groundwork_provider_order": groundwork_order,
        "cheap_provider_order": cheap_order,
        "hard_provider_order": hard_order,
        "cost_sensitive_lanes": [str(item or "").strip() for item in list(payload.get("cost_gated_lanes") or []) if str(item or "").strip()],
        "onemin_preferred_when_speed_is_not_critical": onemin_first and groundwork_onemin_first,
        "onemin_preferred_whenever_usable": onemin_preferred_whenever_usable,
        "onemin_usable": onemin_usable,
        "onemin_probe_pending": onemin_probe_pending,
        "onemin_ready_slots": onemin_ready_slots,
        "onemin_configured_slots": onemin_configured_slots,
        "onemin_unknown_slots": onemin_unknown_slots,
        "onemin_remaining_credits": _number_or_none(
            onemin_billing.get("sum_free_credits")
            if onemin_billing.get("sum_free_credits") not in (None, "")
            else onemin_aggregate.get("sum_free_credits")
        ),
        "onemin_remaining_percent_total": _number_or_none(
            onemin_billing.get("remaining_percent_total")
            if onemin_billing.get("remaining_percent_total") not in (None, "")
            else onemin_aggregate.get("remaining_percent_total")
        ),
        "onemin_next_topup_at": str(onemin_billing.get("next_topup_at") or "").strip(),
        "onemin_burn_basis": str(onemin_aggregate.get("burn_basis") or "").strip(),
        "gemini_provider_key": str(gemini.get("provider_key") or "gemini_vortex").strip(),
        "gemini_token_tracking": {
            "billing_truth_boundary": billing_truth_boundary,
            "selected_window": selected,
            "24h": usage_24h,
            "soft_cap_percent_24h": soft_cap_percent,
            "background_cost_gate": gemini_background_gate,
            "explicit_gemini_requests_allowed": True,
        },
        "routing_decision": routing_decision,
        "privacy": {
            "raw_prompt_or_response_text_exposed": False,
            "raw_provider_secret_exposed": False,
            "raw_google_cloud_billing_account_exposed": False,
            "raw_provider_slots_exposed": False,
        },
    }
    if output_format == "operator":
        report["operator_text"] = (
            "provider_cost_pressure "
            f"status={status} "
            f"gemini_24h_tokens={total_tokens_24h}/{soft_cap_tokens or 'unlimited'} "
            f"gemini_gate={gemini_background_gate} "
            f"onemin_ready_slots={onemin_ready_slots} "
            f"onemin_probe_pending={'1' if onemin_probe_pending else '0'} "
            f"primary={report['primary_background_provider']} "
            f"decision={routing_decision} "
            f"observed_at={report['observed_at']}"
        )
    return report


def probe_provider_cost_pressure(
    *,
    window: str = "24h",
    principal_id: str = "",
    timeout_seconds: float = 30.0,
    output_format: str = "json",
) -> dict[str, object]:
    observed_at = _utc_now()
    code, payload, runtime_container = _runtime_provider_cost_pressure_payload(
        window=window,
        principal_id=principal_id,
        timeout_seconds=timeout_seconds,
    )
    source = (
        f"runtime_container_exec:{runtime_container}:provider_ledger_cache"
        if runtime_container
        else "runtime_container_exec:provider_ledger_cache"
    )
    if code != 0 or not bool(payload.get("ok")):
        host_payload = _provider_cost_pressure_payload_from_host(window=window, principal_id=principal_id)
        if bool(host_payload.get("ok")):
            payload = host_payload
            source = "host_process:provider_ledger_cache"
        else:
            reason = str(payload.get("reason") or host_payload.get("reason") or f"exit_{code}").strip()
            report = {
                "probe_ok": False,
                "status": "probe_failed",
                "observed_at": observed_at,
                "source": source,
                "window": str(window or "").strip(),
                "blocking_reason": _compact_text(reason, limit=220),
                "privacy": {
                    "raw_prompt_or_response_text_exposed": False,
                    "raw_provider_secret_exposed": False,
                    "raw_google_cloud_billing_account_exposed": False,
                    "raw_provider_slots_exposed": False,
                },
            }
            if output_format == "operator":
                report["operator_text"] = (
                    "provider_cost_pressure "
                    f"status=probe_failed reason={str(report['blocking_reason'])} observed_at={observed_at}"
                )
            return report
    return _provider_cost_pressure_report(
        payload=payload,
        source=source,
        observed_at=observed_at,
        output_format=output_format,
    )


def _unmixr_runtime_operational_status(preflight: dict[str, object]) -> str:
    provider_payload = dict(preflight.get("provider") or {})
    checks = {
        str(row.get("key") or "").strip(): str(row.get("status") or "").strip()
        for row in preflight.get("checks") or []
        if isinstance(row, dict) and str(row.get("key") or "").strip()
    }
    blocking_checks = (
        "telegram_audiobook_enabled",
        "jobs_root_durable",
        "jobs_root_writable",
        "external_tts_enabled",
        "unmixr_auto_render_enabled",
        "voice_catalog_configured",
    )
    if any(checks.get(key) == "fail" for key in blocking_checks):
        return "fail"
    if int(provider_payload.get("voice_catalog_count") or 0) < int(provider_payload.get("voice_audition_min_candidates") or 3):
        return "fail"
    if int(provider_payload.get("api_key_slot_count") or 0) <= 0:
        return "fail"
    return "pass"


def _runtime_container_onemin_aggregate() -> tuple[dict[str, object], dict[str, object]]:
    code = (
        "import json\n"
        "try:\n"
        "    from app.container import build_container\n"
        "    from app.services.responses_upstream import _provider_health_report\n"
        "    container = build_container()\n"
        "    aggregate = container.onemin_manager.aggregate_snapshot(\n"
        "        provider_health=_provider_health_report(), binding_rows=[], principal_id=''\n"
        "    )\n"
        "    print(json.dumps({'ok': True, 'aggregate': aggregate}, sort_keys=True, default=str))\n"
        "except Exception as exc:\n"
        "    print(json.dumps({'ok': False, 'reason': type(exc).__name__}, sort_keys=True))\n"
    )
    exit_code, payload, container_name = _runtime_container_exec_json(code=code, timeout_seconds=30.0)
    probe = {
        "source": "runtime_container_exec",
        "runtime_container": container_name,
        "exit_code": exit_code,
        "reason": str(payload.get("reason") or "").strip(),
    }
    if exit_code == 0 and bool(payload.get("ok")) and isinstance(payload.get("aggregate"), dict):
        return dict(payload["aggregate"]), probe
    if not probe["reason"]:
        probe["reason"] = "runtime_onemin_aggregate_unavailable"
    return {}, probe


def _host_onemin_aggregate() -> tuple[dict[str, object], dict[str, object]]:
    try:
        provider_health = _provider_health_report()
        aggregate = _container().onemin_manager.aggregate_snapshot(
            provider_health=provider_health,
            binding_rows=[],
            principal_id="",
        )
    except Exception as exc:
        return {}, {
            "source": "host_app_container",
            "reason": type(exc).__name__,
        }
    return dict(aggregate) if isinstance(aggregate, dict) else {}, {
        "source": "host_app_container",
        "reason": "",
    }


def _float_or_none(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _int_or_none(value: object) -> int | None:
    numeric = _float_or_none(value)
    return None if numeric is None else int(numeric)


def _onemin_live_ops_status(aggregate: Mapping[str, object]) -> tuple[str, str]:
    explicit = str(aggregate.get("state") or "").strip().lower()
    if explicit and explicit != "unknown":
        return explicit, "aggregate_state"

    live_dispatchable_slot_count = _int_or_none(aggregate.get("live_dispatchable_slot_count"))
    if live_dispatchable_slot_count is not None:
        if live_dispatchable_slot_count > 0:
            return "ready", "live_dispatchable_slot_count"
        positive_slots = _int_or_none(aggregate.get("live_positive_balance_slot_count")) or 0
        positive_accounts = _int_or_none(aggregate.get("live_positive_balance_account_count")) or 0
        return ("degraded", "funded_without_dispatchable_slots") if max(positive_slots, positive_accounts) > 0 else ("unavailable", "no_dispatchable_slots")

    for field_name in ("live_ready_slot_count", "live_ready_account_count"):
        value = _int_or_none(aggregate.get(field_name))
        if value is not None and value > 0:
            return "ready", field_name

    for field_name in ("live_positive_balance_slot_count", "live_positive_balance_account_count"):
        value = _int_or_none(aggregate.get(field_name))
        if value is not None and value > 0:
            return "degraded", field_name

    remaining = _float_or_none(aggregate.get("live_remaining_credits_total") or aggregate.get("sum_free_credits"))
    if remaining is not None and remaining > 0:
        return "degraded", "positive_remaining_credits"
    return explicit or "unknown", "aggregate_state_unknown"


def _onemin_report_from_aggregate(
    aggregate: Mapping[str, object],
    *,
    source: str,
    observed_at: str,
    raw_probe: Mapping[str, object],
) -> dict[str, object]:
    status, status_basis = _onemin_live_ops_status(aggregate)
    if str(aggregate.get("scope") or "").strip() == "all_accounts" and status == "ready":
        display_status = "repaired"
    else:
        display_status = status
    accounts = [dict(row) for row in aggregate.get("accounts") or [] if isinstance(row, dict)]
    latest_snapshot = max(
        (str(row.get("last_billing_snapshot_at") or "").strip() for row in accounts if str(row.get("last_billing_snapshot_at") or "").strip()),
        default="",
    )
    next_topup = min(
        (str(row.get("next_topup_at") or "").strip() for row in accounts if str(row.get("next_topup_at") or "").strip()),
        default="",
    )
    return {
        "provider_key": "onemin",
        "display_name": _provider_display_name("onemin"),
        "status": display_status,
        "remaining": aggregate.get("live_remaining_credits_total", aggregate.get("sum_free_credits")),
        "unit": "credits",
        "refresh_at": next_topup or latest_snapshot,
        "observed_at": latest_snapshot or observed_at,
        "account_label": "",
        "source": source,
        "raw": {
            "status_basis": status_basis,
            "status": status,
            "account_count": aggregate.get("account_count"),
            "ready_account_count": aggregate.get("ready_account_count"),
            "live_positive_balance_account_count": aggregate.get("live_positive_balance_account_count"),
            "live_ready_account_count": aggregate.get("live_ready_account_count"),
            "slot_count": aggregate.get("slot_count"),
            "global_configured_slot_count": aggregate.get("global_configured_slot_count"),
            "live_positive_balance_slot_count": aggregate.get("live_positive_balance_slot_count"),
            "live_ready_slot_count": aggregate.get("live_ready_slot_count"),
            "live_dispatchable_slot_count": aggregate.get("live_dispatchable_slot_count"),
            "live_remaining_percent_of_max": aggregate.get("live_remaining_percent_of_max"),
            "actual_remaining_percent_of_max": aggregate.get("actual_remaining_percent_of_max"),
            "current_burn_credits_per_hour": aggregate.get("current_burn_credits_per_hour"),
            "burn_basis": aggregate.get("burn_basis"),
            "active_lease_count": aggregate.get("active_lease_count"),
            "estimated_hours_remaining_at_current_pace": aggregate.get("estimated_hours_remaining_at_current_pace"),
            "scope": aggregate.get("scope"),
            "probe": dict(raw_probe),
        },
    }


def _onemin_probe_failed_report(
    *,
    observed_at: str,
    runtime_probe: Mapping[str, object],
    host_probe: Mapping[str, object],
) -> dict[str, object]:
    runtime_reason = str(runtime_probe.get("reason") or "").strip()
    host_reason = str(host_probe.get("reason") or "").strip()
    reason = runtime_reason or host_reason or "onemin_probe_unavailable"
    return {
        "provider_key": "onemin",
        "display_name": _provider_display_name("onemin"),
        "status": "probe_failed",
        "remaining": None,
        "unit": "credits",
        "refresh_at": "",
        "observed_at": observed_at,
        "account_label": "",
        "source": "runtime_container_exec + host_app_container_fallback",
        "raw": {
            "probe_ok": False,
            "reason": reason,
            "runtime_probe": dict(runtime_probe),
            "host_probe": dict(host_probe),
        },
    }


def probe_pushbullet_delivery(*, timeout_seconds: float = 20.0, output_format: str = "json") -> dict[str, object]:
    observed_at = _utc_now()
    try:
        receipt = pushbullet_delivery_readiness.build_receipt(
            probe_live=True,
            timeout_seconds=max(float(timeout_seconds or 20.0), 1.0),
        )
    except Exception as exc:
        report = {
            "provider_key": "pushbullet",
            "display_name": _provider_display_name("pushbullet"),
            "status": "probe_failed",
            "remaining": None,
            "unit": "",
        "refresh_at": "",
        "observed_at": observed_at,
        "account_label": "",
        "account_label_basis": "",
        "ready": False,
        "probe_ok": False,
        "reason": type(exc).__name__,
            "next_action": "inspect_pushbullet_delivery",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
            "source": "scripts.materialize_pushbullet_delivery_readiness.py",
            "raw": {
                "probe_ok": False,
                "exception_type": type(exc).__name__,
                "raw_email_exposed": False,
                "raw_token_exposed": False,
            },
        }
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_pushbullet(report)
        return report

    coverage = dict(receipt.get("client_coverage") or {})
    operator_action = dict(receipt.get("operator_action") or {})
    status = str(receipt.get("status") or "unknown").strip() or "unknown"
    account_label, account_label_basis = _pushbullet_account_label_from_receipt(receipt)
    report = {
        "provider_key": "pushbullet",
        "display_name": _provider_display_name("pushbullet"),
        "status": status,
        "remaining": None,
        "unit": "",
        "refresh_at": "",
        "observed_at": str(receipt.get("generated_at") or observed_at).strip() or observed_at,
        "account_label": account_label,
        "account_label_basis": account_label_basis,
        "ready": status in {"ready_configured", "ready_live_verified"},
        "probe_ok": True,
        "reason": _pushbullet_reason_from_receipt(receipt),
        "required_client_keys": _string_list(receipt.get("required_client_keys")),
        "configured_required_client_count": int(coverage.get("configured_required_client_count") or 0),
        "token_present_required_client_count": int(coverage.get("token_present_required_client_count") or 0),
        "missing_client_keys": _string_list(coverage.get("missing_client_keys")),
        "missing_token_keys": _string_list(coverage.get("missing_token_keys")),
        "next_action": str(operator_action.get("next_action") or "").strip(),
        "next_action_href": str(operator_action.get("next_action_href") or "").strip(),
        "next_action_label": str(operator_action.get("next_action_label") or "").strip(),
        "next_action_method": str(operator_action.get("next_action_method") or "").strip(),
        "source": str(receipt.get("generated_by") or "scripts.materialize_pushbullet_delivery_readiness.py").strip(),
        "raw": {
            "provider": str(receipt.get("provider") or "pushbullet").strip() or "pushbullet",
            "client_count": int(receipt.get("client_count") or 0),
            "multi_client_expected": bool(receipt.get("multi_client_expected")),
            "required_client_keys": _string_list(receipt.get("required_client_keys")),
            "account_label_basis": account_label_basis,
            "configured_client_count": int(coverage.get("configured_client_count") or 0),
            "configured_required_client_count": int(coverage.get("configured_required_client_count") or 0),
            "token_present_required_client_count": int(coverage.get("token_present_required_client_count") or 0),
            "missing_client_keys": _string_list(coverage.get("missing_client_keys")),
            "missing_token_keys": _string_list(coverage.get("missing_token_keys")),
            "default_client_ref": str(receipt.get("default_client_ref") or "").strip(),
            "missing_setup": _string_list(receipt.get("missing_setup")),
            "live_probe_count": len(list(receipt.get("live_probes") or [])),
            "live_probes": [
                dict(item)
                for item in list(receipt.get("live_probes") or [])
                if isinstance(item, Mapping)
            ],
            "raw_email_exposed": False,
            "raw_token_exposed": False,
        },
    }
    if output_format == "operator":
        report["operator_text"] = _operator_text_for_pushbullet(report)
    return report


def probe_provider(provider: str, *, output_format: str = "json", timeout_seconds: float = 20.0) -> dict[str, object]:
    provider_key = _normalize_provider_key(provider)
    if provider_key == "onemin":
        observed_at = _utc_now()
        aggregate, runtime_probe = _runtime_container_onemin_aggregate()
        if aggregate:
            report = _onemin_report_from_aggregate(
                aggregate,
                source="runtime_container_exec:onemin_manager.aggregate_snapshot",
                observed_at=observed_at,
                raw_probe=runtime_probe,
            )
        else:
            aggregate, host_probe = _host_onemin_aggregate()
            if aggregate:
                report = _onemin_report_from_aggregate(
                    aggregate,
                    source="host_app_container:onemin_manager.aggregate_snapshot",
                    observed_at=observed_at,
                    raw_probe={"runtime_probe": dict(runtime_probe), "host_probe": dict(host_probe)},
                )
            else:
                report = _onemin_probe_failed_report(
                    observed_at=observed_at,
                    runtime_probe=runtime_probe,
                    host_probe=host_probe,
                )
    elif provider_key == "pushbullet":
        report = probe_pushbullet_delivery(
            timeout_seconds=max(float(timeout_seconds or 20.0), 1.0),
            output_format=output_format,
        )
    elif provider_key == "unmixr":
        runtime_preflight = _runtime_container_preflight(
            timeout_seconds=max(float(timeout_seconds or 20.0), 45.0)
        )
        preflight_source = "runtime_container" if runtime_preflight else "host_fallback"
        preflight = runtime_preflight or audiobook_runtime_preflight()
        provider_payload = dict(preflight.get("provider") or {})
        credit_balance = (
            _runtime_container_unmixr_credit_balance(
                timeout_seconds=max(float(timeout_seconds or 20.0), 30.0)
            )
            if runtime_preflight
            else {}
        )
        credit_balance_ready = str(credit_balance.get("status") or "").strip() == "pass"
        configured_slot_count = int(
            credit_balance.get("configured_slot_count")
            or provider_payload.get("api_key_slot_count")
            or 0
        )
        successful_slot_count = int(credit_balance.get("successful_slot_count") or 0)
        positive_slot_count = int(credit_balance.get("positive_prebuilt_slot_count") or 0)
        operational_status = _unmixr_runtime_operational_status(preflight)
        if not runtime_preflight and operational_status == "pass":
            operational_status = "warn"
        elif runtime_preflight and not credit_balance_ready and operational_status == "pass":
            operational_status = "warn"
        elif credit_balance_ready and positive_slot_count <= 0:
            operational_status = "fail"
        elif credit_balance_ready and (
            successful_slot_count < configured_slot_count
            or positive_slot_count < successful_slot_count
        ):
            operational_status = "warn"
        report = {
            "provider_key": "unmixr",
            "display_name": _provider_display_name("unmixr"),
            "status": operational_status,
            "remaining": (
                int(credit_balance.get("prebuilt_credits_min") or 0)
                if credit_balance_ready
                else provider_payload.get("api_key_slot_count")
            ),
            "unit": (
                "prebuilt_character_credits_min_per_slot"
                if credit_balance_ready
                else "configured_api_key_slots"
            ),
            "refresh_at": "",
            "observed_at": str(
                (credit_balance.get("observed_at") if credit_balance_ready else "")
                or preflight.get("observed_at")
                or ""
            ).strip(),
            "account_label": "",
            "source": str(
                (credit_balance.get("contract_name") if credit_balance_ready else "")
                or preflight.get("contract_name")
                or "ea.telegram_epub_audiobook_runtime_preflight.v1"
            ),
            "raw": {
                "voice_catalog_count": provider_payload.get("voice_catalog_count"),
                "voice_discovery_enabled": provider_payload.get("voice_discovery_enabled"),
                "unmixr_auto_render_enabled": provider_payload.get("unmixr_auto_render_enabled"),
                "voice_audition_min_candidates": provider_payload.get("voice_audition_min_candidates"),
                "runtime_container": _runtime_container_name(),
                "preflight_execution_source": preflight_source,
                "runtime_preflight_available": bool(runtime_preflight),
                "credit_balance": credit_balance,
                "preflight_status": str(preflight.get("status") or "").strip(),
                "preflight_failed_checks": list(preflight.get("failed_checks") or []),
                "preflight_warned_checks": list(preflight.get("warned_checks") or []),
            },
        }
    else:
        state = _container().provider_registry.binding_state(provider_key)
        report = {
            "provider_key": provider_key,
            "display_name": _provider_display_name(provider_key),
            "status": str(getattr(state, "state", "") or getattr(state, "status", "") or "unknown").strip() or "unknown",
            "remaining": None,
            "unit": "",
            "refresh_at": "",
            "observed_at": str(getattr(state, "updated_at", "") or "").strip(),
            "account_label": "",
            "source": "provider_registry.binding_state",
            "raw": {
                "enabled": bool(getattr(state, "enabled", False)),
                "executable": bool(getattr(state, "executable", False)),
                "health_state": str(getattr(state, "health_state", "") or "").strip(),
                "capabilities": list(getattr(state, "capabilities", ()) or ()),
            },
        }
    if output_format == "operator" and provider_key != "pushbullet":
        report["operator_text"] = _operator_text_for_provider(report)
    return report


def _operator_text_for_onemin_direct_refresh(report: Mapping[str, object]) -> str:
    pieces = [
        f"onemin_direct_refresh status={report.get('status') or 'unknown'}",
        f"ready={str(bool(report.get('ready'))).lower()}",
    ]
    for field_name, label in (
        ("selected_account_count", "selected"),
        ("resume_success_count", "resumed"),
        ("current_run_refreshed_count", "refreshed_now"),
        ("refreshed_count", "refreshed_total"),
        ("error_count", "errors"),
    ):
        if report.get(field_name) not in (None, ""):
            pieces.append(f"{label}={report[field_name]}")
    if report.get("rate_limited") is not None:
        pieces.append(f"rate_limited={str(bool(report.get('rate_limited'))).lower()}")
    if report.get("remaining_credits_total") not in (None, ""):
        pieces.append(f"remaining_total={report['remaining_credits_total']}")
    if report.get("next_topup_at_earliest"):
        pieces.append(f"next_topup={report['next_topup_at_earliest']}")
    if report.get("output_json"):
        pieces.append(f"receipt={Path(str(report['output_json'])).name}")
    return "; ".join(str(item) for item in pieces if str(item).strip())


def _onemin_direct_refresh_telegram_text(report: Mapping[str, object]) -> str:
    error_counts = dict(report.get("error_code_counts") or {}) if isinstance(report.get("error_code_counts"), Mapping) else {}
    error_summary = ", ".join(
        f"{key}={value}"
        for key, value in sorted(
            ((str(key or "").strip(), int(value or 0)) for key, value in error_counts.items() if str(key or "").strip()),
            key=lambda item: item[0],
        )[:3]
    )
    lines = [
        f"1minAI direct refresh: {report.get('status') or 'unknown'}",
        (
            f"Selected {int(report.get('selected_account_count') or 0)}, "
            f"refreshed now {int(report.get('current_run_refreshed_count') or 0)}, "
            f"refreshed total {int(report.get('refreshed_count') or 0)}."
        ),
        (
            f"Errors {int(report.get('error_count') or 0)}; "
            f"rate limited {'yes' if bool(report.get('rate_limited')) else 'no'}."
        ),
    ]
    if report.get("remaining_credits_total") not in (None, ""):
        lines.append(
            "Credits across refreshed accounts: "
            f"{report['remaining_credits_total']} total "
            f"(min {report.get('remaining_credits_min')}, max {report.get('remaining_credits_max')})."
        )
    if report.get("next_topup_at_earliest"):
        lines.append(
            "Observed next topups: "
            f"{report['next_topup_at_earliest']} to {report.get('next_topup_at_latest') or report['next_topup_at_earliest']}."
        )
    if error_summary:
        lines.append(f"Error codes: {error_summary}.")
    if report.get("next_action"):
        lines.append(f"Next action: {report['next_action']}.")
    if report.get("output_json"):
        lines.append(f"Receipt: {Path(str(report['output_json'])).name}.")
    return "\n".join(line for line in lines if str(line).strip())


def _summarize_onemin_direct_refresh_results(results: list[dict[str, object]]) -> dict[str, object]:
    remaining_values = [
        float(item.get("remaining_credits") or 0.0)
        for item in results
        if item.get("remaining_credits") not in (None, "")
    ]
    next_topups = sorted(
        str(item.get("next_topup_at") or "").strip()
        for item in results
        if str(item.get("next_topup_at") or "").strip()
    )
    return {
        "remaining_credits_total": round(sum(remaining_values), 2) if remaining_values else None,
        "remaining_credits_min": round(min(remaining_values), 2) if remaining_values else None,
        "remaining_credits_max": round(max(remaining_values), 2) if remaining_values else None,
        "next_topup_at_earliest": next_topups[0] if next_topups else "",
        "next_topup_at_latest": next_topups[-1] if next_topups else "",
    }


def _run_onemin_direct_api_refresh(
    *,
    owner_ledger_path: Path,
    account_labels: list[str],
    account_login_credentials: dict[str, dict[str, str]],
    timeout_seconds: float,
    batch_size: int,
    batch_backoff_seconds: float,
    max_rate_limit_sleep_seconds: float,
    continue_on_rate_limit: bool,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], int, int, bool]:
    from app.api.routes import providers as providers_route

    env_overrides = {
        "EA_RESPONSES_ONEMIN_OWNER_LEDGER_PATH": owner_ledger_path.as_posix(),
        "ONEMIN_DIRECT_API_BATCH_SIZE": str(max(int(batch_size or 1), 1)),
        "ONEMIN_DIRECT_API_BATCH_BACKOFF_SECONDS": str(max(float(batch_backoff_seconds or 0.0), 0.0)),
        "ONEMIN_DIRECT_API_MAX_RATE_LIMIT_SLEEP_SECONDS": str(max(float(max_rate_limit_sleep_seconds or 0.0), 0.0)),
        "ONEMIN_DIRECT_API_PROXY_SERVER": None,
        "ONEMIN_DIRECT_API_PROXY_POOL": None,
        "ONEMIN_DIRECT_API_PROXY_USERNAME": None,
        "ONEMIN_DIRECT_API_PROXY_PASSWORD": None,
        "EA_ONEMIN_DIRECT_API_PROXY_SERVER": None,
        "EA_ONEMIN_DIRECT_API_PROXY_POOL": None,
        "EA_ONEMIN_DIRECT_API_PROXY_USERNAME": None,
        "EA_ONEMIN_DIRECT_API_PROXY_PASSWORD": None,
        "EA_UI_BROWSER_PROXY_SERVER": None,
        "EA_UI_BROWSER_PROXY_POOL": None,
        "EA_UI_BROWSER_PROXY_USERNAME": None,
        "EA_UI_BROWSER_PROXY_PASSWORD": None,
        "EA_UI_BROWSER_PROXY_BYPASS": None,
    }
    with _temporary_env(env_overrides):
        clear_quarantine = getattr(providers_route, "_clear_onemin_direct_api_quarantine", None)
        if callable(clear_quarantine):
            clear_quarantine()
        return providers_route._refresh_onemin_via_provider_api(
            include_members=False,
            timeout_seconds=max(int(float(timeout_seconds or 180.0)), 30),
            all_accounts=True,
            continue_on_rate_limit=bool(continue_on_rate_limit),
            account_labels={str(item).strip() for item in account_labels if str(item).strip()},
            account_login_credentials=dict(account_login_credentials),
        )


def refresh_onemin_direct_api(
    *,
    account_labels: list[str] | tuple[str, ...] | None = None,
    max_accounts: int = 0,
    owner_ledger_path: str = "",
    output_json: str = "",
    batch_size: int = DEFAULT_ONEMIN_DIRECT_REFRESH_BATCH_SIZE,
    batch_backoff_seconds: float = DEFAULT_ONEMIN_DIRECT_REFRESH_BATCH_BACKOFF_SECONDS,
    max_rate_limit_sleep_seconds: float = DEFAULT_ONEMIN_DIRECT_REFRESH_MAX_RATE_LIMIT_SLEEP_SECONDS,
    continue_on_rate_limit: bool = True,
    send_telegram_to_principal: str = "",
    dry_run: bool = False,
    timeout_seconds: float = 180.0,
    output_format: str = "json",
    telegram_operator_streams: tuple[str, ...] | str | None = None,
) -> dict[str, object]:
    observed_at = _utc_now()
    operator_stream = OPERATOR_STREAM_RECOVERY
    allowed_operator_streams = _effective_telegram_operator_streams(telegram_operator_streams)
    effective_batch_size = max(int(batch_size or 1), 1)
    effective_batch_backoff_seconds = max(float(batch_backoff_seconds or 0.0), 0.0)
    effective_max_rate_limit_sleep_seconds = max(float(max_rate_limit_sleep_seconds or 0.0), 0.0)
    effective_continue_on_rate_limit = bool(continue_on_rate_limit)
    resolved_owner_ledger_path, all_owner_rows, owner_row_reason = _load_onemin_owner_rows_for_live_ops(owner_ledger_path)
    resolved_output_path = _onemin_direct_refresh_output_path(output_json)
    prior_payload = _read_json_file(resolved_output_path)
    prior_results = [dict(item) for item in list(prior_payload.get("results") or []) if isinstance(item, Mapping)]
    prior_success_labels = {
        str(item.get("account_label") or "").strip()
        for item in prior_results
        if str(item.get("account_label") or "").strip()
    }
    requested_labels = [str(value or "").strip() for value in list(account_labels or []) if str(value or "").strip()]
    selected_rows = [
        dict(row)
        for row in all_owner_rows
        if not requested_labels or str(row.get("account_name") or "").strip() in set(requested_labels)
    ]
    if max_accounts > 0:
        selected_rows = selected_rows[: max(int(max_accounts), 0)]
    pending_rows = [
        dict(row)
        for row in selected_rows
        if str(row.get("account_name") or "").strip() not in prior_success_labels
    ]
    password = _env("ONEMIN_DEFAULT_PASSWORD")
    report: dict[str, object] = {
        "probe_ok": True,
        "ready": False,
        "status": "unknown",
        "reason": "",
        "operator_stream": operator_stream,
        "allowed_operator_streams": list(allowed_operator_streams),
        "selected_account_count": len(selected_rows),
        "owner_row_count": len(all_owner_rows),
        "resume_success_count": len(prior_success_labels),
        "pending_account_count": len(pending_rows),
        "current_run_refreshed_count": 0,
        "refreshed_count": len(prior_results),
        "attempted_count": 0,
        "error_count": 0,
        "rate_limited": False,
        "current_run_error_code_counts": {},
        "error_code_counts": {},
        "remaining_credits_total": None,
        "remaining_credits_min": None,
        "remaining_credits_max": None,
        "next_topup_at_earliest": "",
        "next_topup_at_latest": "",
        "results": prior_results,
        "errors": [],
        "owner_ledger_path": resolved_owner_ledger_path.as_posix() if resolved_owner_ledger_path is not None else "",
        "output_json": resolved_output_path.as_posix(),
        "source": "scripts.ea_live_ops.refresh_onemin_direct_api",
        "observed_at": observed_at,
        "refresh_transport": "direct_provider_api",
        "proxy_mode": "direct_no_ui_proxy",
        "batch_size": effective_batch_size,
        "batch_backoff_seconds": effective_batch_backoff_seconds,
        "max_rate_limit_sleep_seconds": effective_max_rate_limit_sleep_seconds,
        "continue_on_rate_limit": effective_continue_on_rate_limit,
        "telegram_delivery": {},
    }
    if resolved_owner_ledger_path is None:
        report["probe_ok"] = False
        report["status"] = "blocked_owner_ledger_missing"
        report["reason"] = owner_row_reason or "owner_ledger_missing"
        report["next_action"] = "repair_onemin_owner_ledger_projection"
    elif not all_owner_rows:
        report["probe_ok"] = False
        report["status"] = "blocked_no_accounts"
        report["reason"] = owner_row_reason or "owner_ledger_empty"
        report["next_action"] = "repair_onemin_owner_ledger_projection"
    elif not password and not dry_run:
        report["probe_ok"] = False
        report["status"] = "blocked_password_missing"
        report["reason"] = "onemin_password_missing"
        report["next_action"] = "configure_onemin_default_password"
    elif not pending_rows:
        report["ready"] = True
        report["status"] = "already_refreshed"
        report["reason"] = "all_selected_accounts_already_refreshed"
        report["next_action"] = ""
    elif dry_run:
        report["status"] = "dry_run"
        report["reason"] = "dry_run"
        report["next_action"] = "resume_onemin_direct_refresh"
    else:
        run_started = time.time()
        refresh_exception: Exception | None = None
        account_login_credentials = {
            str(row.get("account_name") or "").strip(): {
                "login_email": str(row.get("owner_email") or "").strip(),
                "login_password": password,
            }
            for row in pending_rows
            if str(row.get("account_name") or "").strip() and str(row.get("owner_email") or "").strip()
        }
        try:
            billing_results, _member_results, errors, attempted_count, skipped_count, rate_limited = _run_onemin_direct_api_refresh(
                owner_ledger_path=resolved_owner_ledger_path,
                account_labels=[str(row.get("account_name") or "").strip() for row in pending_rows],
                account_login_credentials=account_login_credentials,
                timeout_seconds=max(float(timeout_seconds or 180.0), 30.0),
                batch_size=effective_batch_size,
                batch_backoff_seconds=effective_batch_backoff_seconds,
                max_rate_limit_sleep_seconds=effective_max_rate_limit_sleep_seconds,
                continue_on_rate_limit=effective_continue_on_rate_limit,
            )
        except Exception as exc:
            refresh_exception = exc
            report.update(
                {
                    "probe_ok": False,
                    "status": "failed",
                    "reason": type(exc).__name__,
                    "next_action": "inspect_onemin_direct_refresh_runtime",
                    "error_count": 1,
                    "errors": [
                        {
                            "account_label": "",
                            "error": (str(exc).strip() or type(exc).__name__)[:400],
                            "error_code": type(exc).__name__,
                        }
                    ],
                    "duration_seconds": round(time.time() - run_started, 3),
                }
            )
            billing_results = []
            errors = []
            attempted_count = 0
            skipped_count = 0
            rate_limited = False
        current_results = []
        for row in billing_results:
            if not isinstance(row, Mapping):
                continue
            account_label = str(row.get("account_label") or "").strip()
            if not account_label:
                continue
            current_results.append(
                {
                    "account_label": account_label,
                    "remaining_credits": row.get("remaining_credits"),
                    "next_topup_at": str(row.get("next_topup_at") or "").strip(),
                    "refresh_backend": str(row.get("refresh_backend") or "").strip(),
                    "observed_at": str(row.get("observed_at") or observed_at).strip() or observed_at,
                }
            )
        all_results_by_label: dict[str, dict[str, object]] = {
            str(item.get("account_label") or "").strip(): dict(item)
            for item in prior_results
            if str(item.get("account_label") or "").strip()
        }
        for row in current_results:
            all_results_by_label[str(row.get("account_label") or "").strip()] = dict(row)
        all_results = list(all_results_by_label.values())
        normalized_errors: list[dict[str, object]] = []
        current_error_code_counts: dict[str, int] = {}
        for row in errors:
            if not isinstance(row, Mapping):
                continue
            account_label = str(row.get("account_label") or "").strip()
            error_text = str(row.get("error") or "").strip()
            error_code = error_text.partition(":")[0].strip() or "unknown_error"
            current_error_code_counts[error_code] = current_error_code_counts.get(error_code, 0) + 1
            normalized_errors.append(
                {
                    "account_label": account_label,
                    "error": error_text[:400],
                    "error_code": error_code,
                }
            )
        if refresh_exception is None:
            report.update(
                {
                    "ready": bool(len(all_results) >= len(selected_rows) and not normalized_errors),
                    "status": (
                        "ready"
                        if len(all_results) >= len(selected_rows) and not normalized_errors
                        else "partial_rate_limited"
                        if rate_limited and current_results
                        else "rate_limited"
                        if rate_limited
                        else "partial"
                        if current_results
                        else "failed"
                    ),
                    "reason": (
                        "refreshed"
                        if len(all_results) >= len(selected_rows) and not normalized_errors
                        else "cloudflare_rate_limited"
                        if rate_limited
                        else "partial_refresh_with_errors"
                        if current_results
                        else "refresh_failed"
                    ),
                    "next_action": (
                        ""
                        if len(all_results) >= len(selected_rows) and not normalized_errors
                        else "resume_onemin_direct_refresh_after_cooldown"
                        if rate_limited
                        else "review_onemin_refresh_errors_and_resume"
                        if normalized_errors
                        else "resume_onemin_direct_refresh"
                    ),
                    "current_run_refreshed_count": len(current_results),
                    "refreshed_count": len(all_results),
                    "attempted_count": int(attempted_count or 0),
                    "skipped_count": int(skipped_count or 0),
                    "error_count": len(normalized_errors),
                    "rate_limited": bool(rate_limited),
                    "current_run_error_code_counts": current_error_code_counts,
                    "error_code_counts": current_error_code_counts,
                    "results": all_results,
                    "errors": normalized_errors,
                    "duration_seconds": round(time.time() - run_started, 3),
                }
            )
    report.update(_summarize_onemin_direct_refresh_results([dict(item) for item in list(report.get("results") or []) if isinstance(item, Mapping)]))
    report.update(_next_action_surface_fields(str(report.get("next_action") or "")))
    report["operator_text"] = _operator_text_for_onemin_direct_refresh(report)
    if str(send_telegram_to_principal or "").strip():
        if not _telegram_operator_stream_allowed(operator_stream, allowed_operator_streams=allowed_operator_streams):
            report["telegram_delivery"] = _suppressed_telegram_delivery(
                principal_id=str(send_telegram_to_principal or "").strip(),
                operator_stream=operator_stream,
                allowed_operator_streams=allowed_operator_streams,
                observed_at=observed_at,
                source="scripts.ea_live_ops.refresh_onemin_direct_api",
            )
        else:
            report["telegram_delivery"] = send_telegram(
                principal_id=str(send_telegram_to_principal or "").strip(),
                text=_onemin_direct_refresh_telegram_text(report),
                dry_run=bool(dry_run),
                timeout_seconds=max(float(timeout_seconds or 180.0), 30.0),
            )
    if output_format == "operator":
        report["operator_text"] = _operator_text_for_onemin_direct_refresh(report)
    _write_private_json(resolved_output_path, report)
    return report


def _operator_text_for_whatsapp_readiness(report: Mapping[str, object]) -> str:
    pieces = [
        f"whatsapp_readiness status={report.get('status') or 'unknown'}",
        f"ready={str(bool(report.get('ready'))).lower()}",
    ]
    if report.get("reason"):
        pieces.append(f"reason={report['reason']}")
    if report.get("next_action"):
        pieces.append(f"next={report['next_action']}")
    if report.get("effective_session_ref"):
        pieces.append(f"session={report['effective_session_ref']}")
    if report.get("sidecar_status"):
        pieces.append(f"sidecar={report['sidecar_status']}")
    if report.get("sidecar_qr_required") or report.get("sidecar_qr_present"):
        pieces.append(
            "qr="
            f"required:{str(bool(report.get('sidecar_qr_required'))).lower()}"
            f",present:{str(bool(report.get('sidecar_qr_present'))).lower()}"
            f",age_seconds:{int(report.get('sidecar_qr_age_seconds') or 0)}"
            f",fresh:{str(bool(report.get('sidecar_qr_fresh'))).lower()}"
        )
    pieces.append(f"processor={str(bool(report.get('processor_container_enabled'))).lower()}")
    pieces.append(f"state_fresh={str(bool(report.get('state_fresh'))).lower()}")
    if report.get("generated_at"):
        pieces.append(f"generated_at={report['generated_at']}")
    if report.get("source"):
        pieces.append(f"source={report['source']}")
    return "; ".join(str(item) for item in pieces if str(item).strip())


def _operator_text_for_whatsapp_pairing(report: Mapping[str, object]) -> str:
    pieces = [
        f"whatsapp_pairing status={report.get('status') or 'unknown'}",
        f"ready={str(bool(report.get('ready'))).lower()}",
    ]
    if report.get("reason"):
        pieces.append(f"reason={report['reason']}")
    if report.get("next_action"):
        pieces.append(f"next={report['next_action']}")
    if report.get("session_ref"):
        pieces.append(f"session={report['session_ref']}")
    if report.get("sidecar_status"):
        pieces.append(f"sidecar={report['sidecar_status']}")
    pieces.append(f"qr_present={str(bool(report.get('qr_present'))).lower()}")
    pieces.append(f"qr_required={str(bool(report.get('qr_required'))).lower()}")
    if report.get("qr_age_seconds") is not None:
        pieces.append(f"qr_age_seconds={int(report.get('qr_age_seconds') or 0)}")
    pieces.append(f"qr_fresh={str(bool(report.get('qr_fresh'))).lower()}")
    if report.get("pair_url_scope"):
        pieces.append(f"pair_url_scope={report['pair_url_scope']}")
    if report.get("qr_svg_written") is not None:
        pieces.append(f"qr_svg_written={str(bool(report.get('qr_svg_written'))).lower()}")
    if report.get("telegram_sent") is not None:
        pieces.append(f"telegram_sent={str(bool(report.get('telegram_sent'))).lower()}")
    if report.get("telegram_reason"):
        pieces.append(f"telegram_reason={report['telegram_reason']}")
    if report.get("observed_at"):
        pieces.append(f"observed_at={report['observed_at']}")
    if report.get("source"):
        pieces.append(f"source={report['source']}")
    return "; ".join(str(item) for item in pieces if str(item).strip())


def _operator_text_for_telegram_readiness(report: Mapping[str, object]) -> str:
    pieces = [
        f"telegram_readiness status={report.get('status') or 'unknown'}",
        f"ready={str(bool(report.get('ready'))).lower()}",
    ]
    if report.get("reason"):
        pieces.append(f"reason={report['reason']}")
    if report.get("next_action"):
        pieces.append(f"next={report['next_action']}")
    if report.get("principal_id"):
        pieces.append(f"principal={report['principal_id']}")
    if report.get("binding_id"):
        pieces.append(f"binding={report['binding_id']}")
    pieces.append(f"chat_ref_present={str(bool(report.get('chat_ref_present'))).lower()}")
    pieces.append(f"bot_token_present={str(bool(report.get('bot_token_present'))).lower()}")
    if report.get("bot_key"):
        pieces.append(f"bot_key={report['bot_key']}")
    if report.get("bot_handle"):
        pieces.append(f"bot_handle={report['bot_handle']}")
    if report.get("observed_at"):
        pieces.append(f"observed_at={report['observed_at']}")
    if report.get("source"):
        pieces.append(f"source={report['source']}")
    return "; ".join(str(item) for item in pieces if str(item).strip())


def _operator_text_for_teable_recovery(report: Mapping[str, object]) -> str:
    pieces = [
        f"teable_recovery status={report.get('status') or 'unknown'}",
        f"verify={report.get('verify_status') or 'unknown'}",
        f"local={report.get('local_status') or 'unknown'}",
    ]
    if report.get("reason"):
        pieces.append(f"reason={report['reason']}")
    if report.get("next_action"):
        pieces.append(f"next={report['next_action']}")
    pieces.append(f"table_id_present={str(bool(report.get('table_id_present'))).lower()}")
    if report.get("expected_rows") is not None:
        pieces.append(f"expected_rows={int(report.get('expected_rows') or 0)}")
    if report.get("same_hash") is not None:
        pieces.append(f"same_hash={int(report.get('same_hash') or 0)}")
    pieces.append(
        "restore="
        f"root:{int(report.get('root_restore_count') or 0)}"
        f",local:{int(report.get('local_restore_count') or 0)}"
        f",service:{int(report.get('service_restore_count') or 0)}"
        f",referenced:{int(report.get('referenced_file_restore_count') or 0)}"
    )
    pieces.append(f"missing={int(report.get('missing_artifact_count') or report.get('missing_count') or 0)}")
    pieces.append(f"wrong_modes={int(report.get('wrong_mode_count') or 0)}")
    pieces.append(f"different_hash={int(report.get('different_hash_count') or 0)}")
    mismatch_samples = [str(item or "").strip() for item in list(report.get("different_hash_key_samples") or []) if str(item or "").strip()]
    if mismatch_samples:
        pieces.append(f"drift={','.join(mismatch_samples[:4])}")
    if report.get("observed_at"):
        pieces.append(f"observed_at={report['observed_at']}")
    if report.get("source"):
        pieces.append(f"source={report['source']}")
    return "; ".join(str(item) for item in pieces if str(item).strip())


def _operator_text_for_mymedia_alexa(report: Mapping[str, object]) -> str:
    pieces = [
        f"mymedia_alexa status={report.get('status') or 'unknown'}",
        f"ready={str(bool(report.get('ready'))).lower()}",
    ]
    if report.get("reason"):
        pieces.append(f"reason={report['reason']}")
    if report.get("next_action"):
        pieces.append(f"next={report['next_action']}")
    if report.get("container_name"):
        pieces.append(f"container={report['container_name']}")
    pieces.append(f"container_running={str(bool(report.get('container_running'))).lower()}")
    if int(report.get("container_exit_code") or 0):
        pieces.append(f"exit_code={int(report.get('container_exit_code') or 0)}")
    if report.get("container_error_kind"):
        pieces.append(f"container_error={report['container_error_kind']}")
    if report.get("host_disk_pressure_detected") is not None:
        pieces.append(f"host_disk_pressure={str(bool(report.get('host_disk_pressure_detected'))).lower()}")
    pieces.append(f"api_reachable={str(bool(report.get('api_reachable'))).lower()}")
    pieces.append(f"pairing_ready={str(bool(report.get('pairing_ready'))).lower()}")
    if report.get("pairing_session_pending") is not None:
        pieces.append(f"pairing_session_pending={str(bool(report.get('pairing_session_pending'))).lower()}")
    if report.get("pairing_resume_ready") is not None:
        pieces.append(f"pairing_resume_ready={str(bool(report.get('pairing_resume_ready'))).lower()}")
    if report.get("pairing_session_surface_kind"):
        pieces.append(f"pairing_session_surface={report['pairing_session_surface_kind']}")
    if report.get("connection_status"):
        pieces.append(f"connection={report['connection_status']}")
    if report.get("remote_access_mode"):
        pieces.append(f"external_access={report['remote_access_mode']}")
    pieces.append(f"public_ip_present={str(bool(report.get('public_ip_present'))).lower()}")
    pieces.append(f"watchfolders={int(report.get('watch_folder_count') or 0)}")
    pieces.append(f"tracks={int(report.get('tracks') or 0)}")
    pieces.append(f"scan_pending={str(bool(report.get('library_scan_pending'))).lower()}")
    pieces.append(f"scan_blocked_by_pairing={str(bool(report.get('library_scan_blocked_by_pairing'))).lower()}")
    if report.get("public_surface_configured") is not None:
        pieces.append(f"public_surface_configured={str(bool(report.get('public_surface_configured'))).lower()}")
    if report.get("public_surface_probe_attempted") is not None:
        pieces.append(f"public_surface_probed={str(bool(report.get('public_surface_probe_attempted'))).lower()}")
    if report.get("public_surface_status"):
        pieces.append(f"public_surface_status={report['public_surface_status']}")
    if report.get("public_surface_ready") is not None:
        pieces.append(f"public_surface_ready={str(bool(report.get('public_surface_ready'))).lower()}")
    if report.get("public_surface_access_protected") is not None:
        pieces.append(
            f"public_surface_access_protected={str(bool(report.get('public_surface_access_protected'))).lower()}"
        )
    if report.get("public_surface_reason"):
        pieces.append(f"public_surface_reason={report['public_surface_reason']}")
    if report.get("observed_at"):
        pieces.append(f"observed_at={report['observed_at']}")
    if report.get("source"):
        pieces.append(f"source={report['source']}")
    return "; ".join(str(item) for item in pieces if str(item).strip())


def _xml_local_name(tag: object) -> str:
    return str(tag or "").rsplit("}", 1)[-1].strip()


def _xml_child_text(parent: ET.Element, name: str) -> str:
    for child in list(parent):
        if _xml_local_name(child.tag) == name:
            return str(child.text or "").strip()
    return ""


def _mymedia_connection_status_label(value: object) -> str:
    try:
        return MYMEDIA_CONNECTION_STATUS_LABELS[int(value or 0)]
    except Exception:
        return "unknown"


def _mymedia_watchfolder_status_label(value: object) -> str:
    try:
        return MYMEDIA_WATCHFOLDER_STATUS_LABELS[int(value or 0)]
    except Exception:
        return "unknown"


def _mymedia_allow_external_access_mode(value: object) -> str:
    normalized = str(value or "").strip()
    return MYMEDIA_ALLOW_EXTERNAL_ACCESS_LABELS.get(normalized, "unknown" if normalized else "")


def _mymedia_preferences_snapshot(preferences_path: Path) -> dict[str, object]:
    report: dict[str, object] = {
        "preferences_present": False,
        "label_present": False,
        "refresh_token_present": False,
        "paired_user_present": False,
        "public_ip_present": False,
        "remote_access_mode": "",
    }
    try:
        root = ET.fromstring(preferences_path.read_text(encoding="utf-8"))
    except Exception:
        return report
    report.update(
        {
            "preferences_present": True,
            "label_present": bool(_xml_child_text(root, "Label")),
            "refresh_token_present": bool(_xml_child_text(root, "RefreshToken")),
            "paired_user_present": bool(_xml_child_text(root, "PairedUser")),
            "public_ip_present": bool(_xml_child_text(root, "UseIP4Address")),
            "remote_access_mode": _mymedia_allow_external_access_mode(_xml_child_text(root, "AllowExternalAccess")),
        }
    )
    return report


def _mymedia_messages_snapshot(messages_path: Path) -> dict[str, object]:
    report: dict[str, object] = {
        "messages_present": False,
        "message_count": 0,
        "warning_count": 0,
        "error_count": 0,
    }
    try:
        root = ET.fromstring(messages_path.read_text(encoding="utf-8"))
    except Exception:
        return report
    warning_count = 0
    error_count = 0
    message_count = 0
    for entry in list(root):
        if _xml_local_name(entry.tag) != "Entry":
            continue
        value = next((child for child in list(entry) if _xml_local_name(child.tag) == "Value"), None)
        if value is None:
            continue
        message_count += 1
        message_type = _xml_child_text(value, "MessageType").strip().lower()
        if message_type == "warning":
            warning_count += 1
        elif message_type == "error":
            error_count += 1
    report.update(
        {
            "messages_present": True,
            "message_count": message_count,
            "warning_count": warning_count,
            "error_count": error_count,
        }
    )
    return report


def _mymedia_api_json(
    url: str,
    *,
    method: str = "GET",
    body: Mapping[str, object] | None = None,
    timeout_seconds: float = 15.0,
) -> tuple[bool, dict[str, Any], int, str]:
    try:
        request_body = dict(body) if body is not None else None
        payload = _request_json(
            method=str(method or "GET").upper(),
            url=url,
            headers={"Content-Type": "application/json"} if request_body is not None else None,
            body=request_body,
            timeout=max(float(timeout_seconds or 15.0), 1.0),
        )
        return True, payload, 200, ""
    except urllib.error.HTTPError as exc:
        payload = _http_error_payload(exc)
        return False, payload, int(getattr(exc, "code", 0) or 0), _compact_text(
            payload.get("reason") or getattr(exc, "reason", "") or type(exc).__name__,
            limit=80,
        )
    except Exception as exc:
        return False, {}, 0, type(exc).__name__


def _mymedia_action_surface(*, base_url: str, next_action: str) -> tuple[str, str, str]:
    normalized_base_url = str(base_url or "").rstrip("/")
    if next_action in {
        "complete_amazon_pairing_for_mymedia",
        "complete_amazon_pairing_then_rescan_library",
        "enter_mymedia_amazon_pairing_code",
        "approve_mymedia_amazon_consent",
    }:
        href = f"{normalized_base_url}/index.html#!/setup" if normalized_base_url else ""
        return href, "Open My Media setup" if href else "", "get" if href else ""
    if next_action in {
        "add_mymedia_watch_folder",
        "repair_mymedia_watch_folder",
        "rescan_mymedia_library",
        "wait_for_mymedia_library_scan",
    }:
        href = f"{normalized_base_url}/index.html#!/tables" if normalized_base_url else ""
        return href, "Open Watch Folders" if href else "", "get" if href else ""
    if next_action == "configure_mymedia_external_access":
        href = f"{normalized_base_url}/index.html#!/settings" if normalized_base_url else ""
        return href, "Open My Media settings" if href else "", "get" if href else ""
    if next_action in {"inspect_mymedia_amazon_connection", "inspect_mymedia_console_api", "repair_mymedia_console_api"}:
        href = f"{normalized_base_url}/index.html" if normalized_base_url else ""
        return href, "Open My Media console" if href else "", "get" if href else ""
    return "", "", ""


def _mymedia_public_surface_probe(
    base_url: str,
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, object]:
    normalized_base_url = str(base_url or "").strip().rstrip("/")
    scope = _url_scope(normalized_base_url)
    default_href = normalized_base_url if scope == "public" else ""
    default_label = "Open public My Media URL" if default_href else ""
    default_method = "get" if default_href else ""
    report: dict[str, object] = {
        "configured": bool(normalized_base_url),
        "base_url_scope": scope,
        "probe_attempted": False,
        "ready": False,
        "status": "not_configured" if not normalized_base_url else "not_public",
        "reason": "" if not normalized_base_url else "mymedia_public_console_url_not_public",
        "http_status_code": 0,
        "access_protected": False,
        "cloudflare_blocked": False,
        "redirect_host": "",
        "content_type": "",
        "next_action": "" if not normalized_base_url else "configure_public_mymedia_console_url",
        "next_action_href": default_href,
        "next_action_label": default_label,
        "next_action_method": default_method,
        "source": "http.public_surface_probe",
    }
    if not normalized_base_url:
        return report
    if scope != "public":
        return report

    public_host = str(urllib.parse.urlparse(normalized_base_url).hostname or "").strip().lower()
    status_code, headers, body, error = _request_text_response(
        method="GET",
        url=normalized_base_url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": "ea-live-ops/1.0",
        },
        timeout=max(float(timeout_seconds or 15.0), 1.0),
        max_bytes=8192,
    )
    content_type = _header_value(headers, "Content-Type")
    location = _header_value(headers, "Location")
    redirect_host = str(urllib.parse.urlparse(location).hostname or "").strip().lower()
    www_authenticate = _header_value(headers, "WWW-Authenticate").lower()
    normalized_body = " ".join(str(body or "").split()).strip().lower()
    access_protected = "cloudflare-access" in www_authenticate or redirect_host.endswith("cloudflareaccess.com")
    cloudflare_blocked = bool(
        status_code == 403
        and (
            "sorry, you have been blocked" in normalized_body
            or "attention required!" in normalized_body
            or ("cloudflare" in normalized_body and "blocked" in normalized_body)
        )
    )
    same_host_redirect = bool(location) and (not redirect_host or redirect_host == public_host)
    report.update(
        {
            "probe_attempted": True,
            "http_status_code": status_code,
            "access_protected": access_protected,
            "cloudflare_blocked": cloudflare_blocked,
            "redirect_host": redirect_host,
            "content_type": content_type,
        }
    )
    if error:
        report.update(
            {
                "status": "probe_failed",
                "reason": "mymedia_public_console_probe_failed",
                "next_action": "inspect_mymedia_public_console_route",
            }
        )
        return report
    if access_protected:
        report.update(
            {
                "ready": True,
                "status": "access_protected",
                "reason": "",
                "next_action": "",
            }
        )
        return report
    if 200 <= status_code < 300:
        report.update(
            {
                "ready": True,
                "status": "reachable",
                "reason": "",
                "next_action": "",
            }
        )
        return report
    if 300 <= status_code < 400 and same_host_redirect:
        report.update(
            {
                "ready": True,
                "status": "redirecting",
                "reason": "",
                "next_action": "",
            }
        )
        return report
    if cloudflare_blocked:
        report.update(
            {
                "status": "blocked_by_cloudflare",
                "reason": "mymedia_public_console_blocked_by_cloudflare",
                "next_action": "repair_mymedia_public_console_route",
            }
        )
        return report
    if status_code == 404:
        report.update(
            {
                "status": "route_not_found",
                "reason": "mymedia_public_console_route_not_found",
                "next_action": "repair_mymedia_public_console_route",
            }
        )
        return report
    if 500 <= status_code < 600:
        report.update(
            {
                "status": "origin_error",
                "reason": "mymedia_public_console_origin_error",
                "next_action": "inspect_mymedia_public_console_origin",
            }
        )
        return report
    if status_code in {401, 403}:
        report.update(
            {
                "status": "access_denied",
                "reason": "mymedia_public_console_access_denied",
                "next_action": "inspect_mymedia_public_console_access",
            }
        )
        return report
    report.update(
        {
            "status": "http_error",
            "reason": "mymedia_public_console_http_error",
            "next_action": "inspect_mymedia_public_console_route",
        }
    )
    return report


def _mymedia_public_surface_tunnel_origin(
    web_base_url: str,
    *,
    explicit_origin_url: str = "",
) -> str:
    candidate = str(explicit_origin_url or "").strip() or str(web_base_url or "").strip()
    if not candidate:
        return ""
    parsed = urllib.parse.urlparse(candidate)
    scheme = str(parsed.scheme or "").strip().lower() or "http"
    hostname = str(parsed.hostname or "").strip().lower()
    if not hostname:
        return ""
    host = "172.17.0.1" if hostname in {"127.0.0.1", "localhost", "::1"} else hostname
    netloc = host
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    return urllib.parse.urlunparse((scheme, netloc, "", "", "", ""))


def _cloudflare_headers() -> dict[str, str]:
    return {
        "X-Auth-Email": _env("CLOUDFLARE_EMAIL"),
        "X-Auth-Key": _env("CLOUDFLARE_GLOBAL_API_KEY"),
        "Content-Type": "application/json",
    }


def _cloudflare_auth_ready() -> bool:
    headers = _cloudflare_headers()
    return bool(str(headers.get("X-Auth-Email") or "").strip() and str(headers.get("X-Auth-Key") or "").strip())


def _host_zone_name(hostname: str) -> str:
    host = str(hostname or "").strip().lower()
    parts = [part for part in host.split(".") if part]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def _cloudflare_lookup_zone_for_host(hostname: str, *, timeout_seconds: float) -> dict[str, object]:
    host = str(hostname or "").strip().lower()
    if not host:
        return {"ok": False, "reason": "cloudflare_host_missing"}
    if not _cloudflare_auth_ready():
        return {"ok": False, "reason": "cloudflare_credentials_missing"}
    zone_name = _host_zone_name(host)
    status_code, payload, error = _request_json_response(
        method="GET",
        url=f"https://api.cloudflare.com/client/v4/zones?name={urllib.parse.quote(zone_name, safe='')}",
        headers=_cloudflare_headers(),
        timeout=max(float(timeout_seconds or 15.0), 1.0),
    )
    if error:
        return {"ok": False, "reason": "cloudflare_zone_lookup_failed", "error": error}
    results = [dict(item) for item in list(payload.get("result") or []) if isinstance(item, dict)]
    zone = next((item for item in results if str(item.get("name") or "").strip().lower() == zone_name), {})
    zone_id = str(zone.get("id") or "").strip()
    account_id = str(dict(zone.get("account") or {}).get("id") or "").strip()
    if status_code < 200 or status_code >= 300 or not zone_id or not account_id:
        return {"ok": False, "reason": "cloudflare_zone_not_found", "zone_name": zone_name}
    return {
        "ok": True,
        "reason": "",
        "zone_id": zone_id,
        "account_id": account_id,
        "zone_name": zone_name,
    }


def _cloudflare_lookup_named_tunnel(account_id: str, tunnel_name: str, *, timeout_seconds: float) -> dict[str, object]:
    normalized_account_id = str(account_id or "").strip()
    normalized_tunnel_name = str(tunnel_name or "").strip()
    if not normalized_account_id or not normalized_tunnel_name:
        return {"ok": False, "reason": "cloudflare_tunnel_lookup_config_missing"}
    status_code, payload, error = _request_json_response(
        method="GET",
        url=f"https://api.cloudflare.com/client/v4/accounts/{urllib.parse.quote(normalized_account_id, safe='')}/cfd_tunnel?per_page=100",
        headers=_cloudflare_headers(),
        timeout=max(float(timeout_seconds or 15.0), 1.0),
    )
    if error:
        return {"ok": False, "reason": "cloudflare_tunnel_lookup_failed", "error": error}
    results = [dict(item) for item in list(payload.get("result") or []) if isinstance(item, dict)]
    tunnel = next((item for item in results if str(item.get("name") or "").strip() == normalized_tunnel_name), {})
    tunnel_id = str(tunnel.get("id") or "").strip()
    if status_code < 200 or status_code >= 300 or not tunnel_id:
        return {"ok": False, "reason": "cloudflare_tunnel_not_found", "tunnel_name": normalized_tunnel_name}
    return {
        "ok": True,
        "reason": "",
        "tunnel_id": tunnel_id,
        "tunnel_name": normalized_tunnel_name,
        "tunnel_domain": f"{tunnel_id}.cfargotunnel.com",
    }


def _cloudflare_upsert_dns_record(
    zone_id: str,
    *,
    host_name: str,
    target_name: str,
    proxied: bool = True,
    timeout_seconds: float,
) -> dict[str, object]:
    normalized_zone_id = str(zone_id or "").strip()
    normalized_host_name = str(host_name or "").strip().lower()
    normalized_target_name = str(target_name or "").strip().lower()
    if not normalized_zone_id or not normalized_host_name or not normalized_target_name:
        return {"ok": False, "reason": "cloudflare_dns_config_missing"}
    list_url = (
        f"https://api.cloudflare.com/client/v4/zones/{urllib.parse.quote(normalized_zone_id, safe='')}"
        f"/dns_records?name={urllib.parse.quote(normalized_host_name, safe='')}&per_page=100"
    )
    status_code, payload, error = _request_json_response(
        method="GET",
        url=list_url,
        headers=_cloudflare_headers(),
        timeout=max(float(timeout_seconds or 15.0), 1.0),
    )
    if error:
        return {"ok": False, "reason": "cloudflare_dns_lookup_failed", "error": error}
    results = [dict(item) for item in list(payload.get("result") or []) if isinstance(item, dict)]
    existing = next((item for item in results if str(item.get("name") or "").strip().lower() == normalized_host_name), {})
    existing_id = str(existing.get("id") or "").strip()
    existing_type = str(existing.get("type") or "").strip().upper()
    existing_content = str(existing.get("content") or "").strip().lower()
    existing_proxied = bool(existing.get("proxied"))
    if existing_id and existing_type == "CNAME" and existing_content == normalized_target_name and existing_proxied is bool(proxied):
        return {
            "ok": True,
            "reason": "",
            "changed": False,
            "record_present": True,
            "record_type": "CNAME",
            "record_proxied": existing_proxied,
        }
    body = {
        "type": "CNAME",
        "name": normalized_host_name,
        "content": normalized_target_name,
        "proxied": bool(proxied),
        "ttl": 1,
    }
    if existing_id:
        update_url = (
            f"https://api.cloudflare.com/client/v4/zones/{urllib.parse.quote(normalized_zone_id, safe='')}"
            f"/dns_records/{urllib.parse.quote(existing_id, safe='')}"
        )
        update_status, update_payload, update_error = _request_json_response(
            method="PATCH",
            url=update_url,
            headers=_cloudflare_headers(),
            body=body,
            timeout=max(float(timeout_seconds or 15.0), 1.0),
        )
        if update_error or update_status < 200 or update_status >= 300:
            return {"ok": False, "reason": "cloudflare_dns_update_failed", "error": update_error}
    else:
        create_url = f"https://api.cloudflare.com/client/v4/zones/{urllib.parse.quote(normalized_zone_id, safe='')}/dns_records"
        create_status, create_payload, create_error = _request_json_response(
            method="POST",
            url=create_url,
            headers=_cloudflare_headers(),
            body=body,
            timeout=max(float(timeout_seconds or 15.0), 1.0),
        )
        if create_error or create_status < 200 or create_status >= 300:
            return {"ok": False, "reason": "cloudflare_dns_create_failed", "error": create_error}
    return {
        "ok": True,
        "reason": "",
        "changed": True,
        "record_present": True,
        "record_type": "CNAME",
        "record_proxied": bool(proxied),
    }


def _cloudflare_upsert_tunnel_ingress(
    account_id: str,
    tunnel_id: str,
    *,
    public_host: str,
    service_url: str,
    timeout_seconds: float,
) -> dict[str, object]:
    normalized_account_id = str(account_id or "").strip()
    normalized_tunnel_id = str(tunnel_id or "").strip()
    normalized_public_host = str(public_host or "").strip().lower()
    normalized_service_url = str(service_url or "").strip()
    if not normalized_account_id or not normalized_tunnel_id or not normalized_public_host or not normalized_service_url:
        return {"ok": False, "reason": "cloudflare_tunnel_ingress_config_missing"}
    config_url = (
        f"https://api.cloudflare.com/client/v4/accounts/{urllib.parse.quote(normalized_account_id, safe='')}"
        f"/cfd_tunnel/{urllib.parse.quote(normalized_tunnel_id, safe='')}/configurations"
    )
    status_code, payload, error = _request_json_response(
        method="GET",
        url=config_url,
        headers=_cloudflare_headers(),
        timeout=max(float(timeout_seconds or 15.0), 1.0),
    )
    if error:
        return {"ok": False, "reason": "cloudflare_tunnel_config_lookup_failed", "error": error}
    config = dict(dict(payload.get("result") or {}).get("config") or {})
    ingress = [dict(item) for item in list(config.get("ingress") or []) if isinstance(item, dict)]
    existing = next((item for item in ingress if str(item.get("hostname") or "").strip().lower() == normalized_public_host), {})
    existing_service = str(existing.get("service") or "").strip()
    if existing and existing_service == normalized_service_url:
        return {
            "ok": True,
            "reason": "",
            "changed": False,
            "route_present": True,
            "service_url": normalized_service_url,
        }
    filtered = [item for item in ingress if str(item.get("hostname") or "").strip().lower() != normalized_public_host]
    insert_at = len(filtered)
    for index, item in enumerate(filtered):
        if not str(item.get("hostname") or "").strip() and str(item.get("service") or "").strip() == "http_status:404":
            insert_at = index
            break
    filtered.insert(insert_at, {"hostname": normalized_public_host, "service": normalized_service_url, "originRequest": {}})
    body = {
        "config": {
            "ingress": filtered,
            "warp-routing": dict(config.get("warp-routing") or {"enabled": False}),
        }
    }
    update_status, update_payload, update_error = _request_json_response(
        method="PUT",
        url=config_url,
        headers=_cloudflare_headers(),
        body=body,
        timeout=max(float(timeout_seconds or 15.0), 1.0),
    )
    if update_error or update_status < 200 or update_status >= 300:
        return {"ok": False, "reason": "cloudflare_tunnel_config_update_failed", "error": update_error}
    return {
        "ok": True,
        "reason": "",
        "changed": True,
        "route_present": True,
        "service_url": normalized_service_url,
    }


def _cloudflare_lookup_access_service_token(
    account_id: str,
    *,
    access_env_file: str,
    service_token_name: str = "",
    timeout_seconds: float,
) -> dict[str, object]:
    normalized_account_id = str(account_id or "").strip()
    if not normalized_account_id:
        return {"ok": False, "reason": "cloudflare_access_account_missing"}
    configured_name = str(service_token_name or _env("EA_MYMEDIA_ALEXA_CF_SERVICE_TOKEN_NAME", "")).strip()
    env_file = Path(str(access_env_file or DEFAULT_MYMEDIA_ALEXA_CF_ACCESS_ENV_FILE))
    client_id = str(_env("EA_MYMEDIA_ALEXA_CF_ACCESS_CLIENT_ID", "") or _read_env_value(env_file, "CODEXLIZ_CF_ACCESS_CLIENT_ID")).strip()
    if not configured_name and not client_id:
        return {"ok": False, "reason": "cloudflare_access_service_token_selector_missing"}
    status_code, payload, error = _request_json_response(
        method="GET",
        url=(
            f"https://api.cloudflare.com/client/v4/accounts/{urllib.parse.quote(normalized_account_id, safe='')}"
            "/access/service_tokens?per_page=200"
        ),
        headers=_cloudflare_headers(),
        timeout=max(float(timeout_seconds or 15.0), 1.0),
    )
    if error:
        return {"ok": False, "reason": "cloudflare_access_service_token_lookup_failed", "error": error}
    results = [dict(item) for item in list(payload.get("result") or []) if isinstance(item, dict)]
    token = next(
        (
            item
            for item in results
            if (
                (configured_name and str(item.get("name") or "").strip() == configured_name)
                or (not configured_name and str(item.get("client_id") or "").strip() == client_id)
            )
        ),
        {},
    )
    token_id = str(token.get("id") or "").strip()
    if status_code < 200 or status_code >= 300 or not token_id:
        return {"ok": False, "reason": "cloudflare_access_service_token_missing"}
    return {
        "ok": True,
        "reason": "",
        "service_token_id": token_id,
        "service_token_name": str(token.get("name") or "").strip(),
    }


def _cloudflare_upsert_access_app(
    zone_id: str,
    *,
    public_host: str,
    access_app_name: str,
    access_emails_csv: str,
    service_token_id: str = "",
    timeout_seconds: float,
) -> dict[str, object]:
    normalized_zone_id = str(zone_id or "").strip()
    normalized_public_host = str(public_host or "").strip().lower()
    normalized_app_name = str(access_app_name or DEFAULT_MYMEDIA_ALEXA_ACCESS_APP_NAME).strip()
    emails = [item.strip() for item in str(access_emails_csv or "").split(",") if item.strip()]
    if not normalized_zone_id or not normalized_public_host:
        return {"ok": False, "reason": "cloudflare_access_app_config_missing"}
    if not emails:
        return {"ok": True, "reason": "cloudflare_access_email_allowlist_missing", "changed": False, "skipped": True}
    if not str(service_token_id or "").strip():
        return {"ok": True, "reason": "cloudflare_access_service_token_missing", "changed": False, "skipped": True}
    apps_url = f"https://api.cloudflare.com/client/v4/zones/{urllib.parse.quote(normalized_zone_id, safe='')}/access/apps"
    status_code, payload, error = _request_json_response(
        method="GET",
        url=f"{apps_url}?per_page=200",
        headers=_cloudflare_headers(),
        timeout=max(float(timeout_seconds or 15.0), 1.0),
    )
    if error:
        return {"ok": False, "reason": "cloudflare_access_app_lookup_failed", "error": error}
    results = [dict(item) for item in list(payload.get("result") or []) if isinstance(item, dict)]
    existing = next(
        (
            item
            for item in results
            if normalized_public_host == str(item.get("domain") or "").strip().lower()
            or normalized_public_host in [str(domain or "").strip().lower() for domain in list(item.get("self_hosted_domains") or [])]
        ),
        {},
    )
    existing_app_id = str(existing.get("id") or "").strip()
    policies = [
        {
            "name": f"{normalized_app_name} service token",
            "decision": "non_identity",
            "include": [{"service_token": {"token_id": str(service_token_id).strip()}}],
            "exclude": [],
            "require": [],
            "precedence": 1,
        },
        {
            "name": f"{normalized_app_name} email allow",
            "decision": "allow",
            "include": [{"email": {"email": email}} for email in emails],
            "exclude": [],
            "require": [],
            "precedence": 2,
        },
    ]
    already_ok = False
    if existing:
        current_domains = [str(domain or "").strip().lower() for domain in list(existing.get("self_hosted_domains") or [])]
        current_policy_token_ids = {
            str(dict(include.get("service_token") or {}).get("token_id") or "").strip()
            for policy in list(existing.get("policies") or [])
            if isinstance(policy, dict)
            for include in list(policy.get("include") or [])
            if isinstance(include, dict)
        }
        current_email_set = {
            str(dict(include.get("email") or {}).get("email") or "").strip().lower()
            for policy in list(existing.get("policies") or [])
            if isinstance(policy, dict)
            for include in list(policy.get("include") or [])
            if isinstance(include, dict)
        }
        already_ok = (
            normalized_public_host == str(existing.get("domain") or "").strip().lower()
            and normalized_public_host in current_domains
            and str(service_token_id).strip() in current_policy_token_ids
            and {email.lower() for email in emails}.issubset(current_email_set)
        )
    if already_ok:
        return {"ok": True, "reason": "", "changed": False, "app_present": True}
    body = {
        "type": "self_hosted",
        "name": normalized_app_name,
        "domain": normalized_public_host,
        "self_hosted_domains": [normalized_public_host],
        "destinations": [{"type": "public", "uri": normalized_public_host}],
        "app_launcher_visible": True,
        "allowed_idps": [],
        "auto_redirect_to_identity": False,
        "session_duration": "24h",
        "http_only_cookie_attribute": True,
        "enable_binding_cookie": False,
        "options_preflight_bypass": False,
        "policies": policies,
    }
    if existing_app_id:
        update_status, update_payload, update_error = _request_json_response(
            method="PUT",
            url=f"{apps_url}/{urllib.parse.quote(existing_app_id, safe='')}",
            headers=_cloudflare_headers(),
            body=body,
            timeout=max(float(timeout_seconds or 15.0), 1.0),
        )
        if update_error or update_status < 200 or update_status >= 300:
            return {"ok": False, "reason": "cloudflare_access_app_update_failed", "error": update_error}
    else:
        create_status, create_payload, create_error = _request_json_response(
            method="POST",
            url=apps_url,
            headers=_cloudflare_headers(),
            body=body,
            timeout=max(float(timeout_seconds or 15.0), 1.0),
        )
        if create_error or create_status < 200 or create_status >= 300:
            return {"ok": False, "reason": "cloudflare_access_app_create_failed", "error": create_error}
    return {"ok": True, "reason": "", "changed": True, "app_present": True}


def _cloudflare_expression_add_host_exception(
    expression: str,
    *,
    required_existing_hosts: list[str],
    new_host: str,
) -> str:
    normalized_expression = str(expression or "")
    target_host = str(new_host or "").strip().lower()
    match_hosts = {str(item or "").strip().lower() for item in required_existing_hosts if str(item or "").strip()}
    if not normalized_expression or not target_host or not match_hosts:
        return normalized_expression

    def _replace(match: re.Match[str]) -> str:
        raw_hosts = match.group(1)
        hosts = [item.strip().lower() for item in re.findall(r'"([^"]+)"', raw_hosts)]
        if target_host in hosts or not any(host in match_hosts for host in hosts):
            return match.group(0)
        hosts.append(target_host)
        rendered = " ".join(f'"{host}"' for host in hosts)
        return f"http.host in {{{rendered}}}"

    return re.sub(r"http\.host\s+in\s+\{([^}]*)\}", _replace, normalized_expression)


def _cloudflare_patch_private_host_block_exceptions(
    zone_id: str,
    *,
    public_host: str,
    required_existing_hosts: list[str],
    timeout_seconds: float,
) -> dict[str, object]:
    normalized_zone_id = str(zone_id or "").strip()
    normalized_public_host = str(public_host or "").strip().lower()
    match_hosts = [str(item or "").strip().lower() for item in required_existing_hosts if str(item or "").strip()]
    if not normalized_zone_id or not normalized_public_host or not match_hosts:
        return {"ok": True, "reason": "cloudflare_firewall_exception_hosts_missing", "changed": False, "skipped": True}
    rulesets_status, rulesets_payload, rulesets_error = _request_json_response(
        method="GET",
        url=f"https://api.cloudflare.com/client/v4/zones/{urllib.parse.quote(normalized_zone_id, safe='')}/rulesets",
        headers=_cloudflare_headers(),
        timeout=max(float(timeout_seconds or 15.0), 1.0),
    )
    if rulesets_error:
        return {"ok": False, "reason": "cloudflare_firewall_ruleset_lookup_failed", "error": rulesets_error}
    rulesets = [dict(item) for item in list(rulesets_payload.get("result") or []) if isinstance(item, dict)]
    ruleset = next(
        (
            item
            for item in rulesets
            if str(item.get("phase") or "").strip() == "http_request_firewall_custom"
            and str(item.get("kind") or "").strip() == "zone"
        ),
        {},
    )
    ruleset_id = str(ruleset.get("id") or "").strip()
    if rulesets_status < 200 or rulesets_status >= 300 or not ruleset_id:
        return {"ok": True, "reason": "", "changed": False, "skipped": True, "patched_rule_count": 0}
    detail_status, detail_payload, detail_error = _request_json_response(
        method="GET",
        url=(
            f"https://api.cloudflare.com/client/v4/zones/{urllib.parse.quote(normalized_zone_id, safe='')}"
            f"/rulesets/{urllib.parse.quote(ruleset_id, safe='')}"
        ),
        headers=_cloudflare_headers(),
        timeout=max(float(timeout_seconds or 15.0), 1.0),
    )
    if detail_error:
        return {"ok": False, "reason": "cloudflare_firewall_ruleset_detail_failed", "error": detail_error}
    rules = [dict(item) for item in list(dict(detail_payload.get("result") or {}).get("rules") or []) if isinstance(item, dict)]
    patched_rule_count = 0
    candidate_rule_count = 0
    for rule in rules:
        if str(rule.get("action") or "").strip() != "block":
            continue
        updated_expression = _cloudflare_expression_add_host_exception(
            str(rule.get("expression") or ""),
            required_existing_hosts=match_hosts,
            new_host=normalized_public_host,
        )
        if updated_expression == str(rule.get("expression") or ""):
            continue
        candidate_rule_count += 1
        rule_id = str(rule.get("id") or "").strip()
        if not rule_id:
            return {"ok": False, "reason": "cloudflare_firewall_rule_id_missing"}
        body: dict[str, object] = {
            "action": str(rule.get("action") or "").strip(),
            "expression": updated_expression,
            "enabled": bool(rule.get("enabled", True)),
        }
        if "description" in rule:
            body["description"] = rule.get("description")
        if "action_parameters" in rule:
            body["action_parameters"] = rule.get("action_parameters")
        if "logging" in rule:
            body["logging"] = rule.get("logging")
        patch_status, patch_payload, patch_error = _request_json_response(
            method="PATCH",
            url=(
                f"https://api.cloudflare.com/client/v4/zones/{urllib.parse.quote(normalized_zone_id, safe='')}"
                f"/rulesets/{urllib.parse.quote(ruleset_id, safe='')}/rules/{urllib.parse.quote(rule_id, safe='')}"
            ),
            headers=_cloudflare_headers(),
            body=body,
            timeout=max(float(timeout_seconds or 15.0), 1.0),
        )
        if patch_error or patch_status < 200 or patch_status >= 300:
            return {"ok": False, "reason": "cloudflare_firewall_rule_patch_failed", "error": patch_error}
        patched_rule_count += 1
    return {
        "ok": True,
        "reason": "",
        "changed": patched_rule_count > 0,
        "patched_rule_count": patched_rule_count,
        "candidate_rule_count": candidate_rule_count,
    }


def _sync_env_to_teable_json(command: str, *, timeout_seconds: float) -> tuple[int, dict[str, object], str]:
    try:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "sync_env_to_teable.py"), command],
            check=False,
            capture_output=True,
            text=True,
            timeout=max(float(timeout_seconds), 1.0),
            cwd=str(ROOT),
        )
    except subprocess.TimeoutExpired:
        return 124, {}, "timeout"
    except Exception as exc:
        return 1, {}, type(exc).__name__
    payload: dict[str, object] = {}
    try:
        parsed = json.loads(str(completed.stdout or "{}"))
        if isinstance(parsed, dict):
            payload = dict(parsed)
    except json.JSONDecodeError:
        payload = {}
    return completed.returncode, payload, str(completed.stderr or "").strip()[:160]


def _hash_text(value: object) -> str:
    normalized = str(value or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def _int_payload(payload: Mapping[str, object], key: str) -> int:
    try:
        return int(payload.get(key) or 0)
    except Exception:
        return 0


def probe_mymedia_alexa(
    *,
    container_name: str = "",
    web_base_url: str = "",
    public_web_base_url: str = "",
    timeout_seconds: float = 15.0,
    output_format: str = "json",
) -> dict[str, object]:
    observed_at = _utc_now()
    observed_now = _parse_utc_datetime(observed_at)
    effective_container_name = str(
        container_name or _env("EA_MYMEDIA_ALEXA_CONTAINER", DEFAULT_MYMEDIA_ALEXA_CONTAINER)
    ).strip() or DEFAULT_MYMEDIA_ALEXA_CONTAINER
    effective_web_base_url = str(
        web_base_url or _env("EA_MYMEDIA_ALEXA_WEB_BASE_URL", DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL)
    ).strip() or DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL
    effective_public_web_base_url = str(
        public_web_base_url or _env("EA_MYMEDIA_ALEXA_PUBLIC_BASE_URL", DEFAULT_MYMEDIA_ALEXA_PUBLIC_BASE_URL)
    ).strip()

    inspect_payload = _docker_inspect_container_json(
        effective_container_name,
        timeout_seconds=max(float(timeout_seconds or 15.0), 1.0),
    )
    if not inspect_payload:
        report = {
            "probe_ok": False,
            "ready": False,
            "status": "probe_failed",
            "reason": "mymedia_container_inspect_failed",
            "next_action": "inspect_mymedia_alexa_container",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
            "container_name": effective_container_name,
            "container_running": False,
            "api_reachable": False,
            "pairing_ready": False,
            "watch_folder_count": 0,
            "tracks": 0,
            "library_scan_pending": False,
            "library_scan_blocked_by_pairing": False,
            "observed_at": observed_at,
            "source": "docker.inspect+mymedia.api+xml_mount",
            "privacy": {
                "raw_refresh_token_exposed": False,
                "raw_paired_user_exposed": False,
                "raw_watch_folder_paths_exposed": False,
                "raw_public_ip_exposed": False,
            },
        }
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_mymedia_alexa(report)
        return report

    state = dict(inspect_payload.get("State") or {})
    mounts = [dict(item) for item in list(inspect_payload.get("Mounts") or []) if isinstance(item, dict)]
    data_mount = next(
        (item for item in mounts if str(item.get("Destination") or "").strip() == "/datadir"),
        {},
    )
    data_dir = Path(str(data_mount.get("Source") or "").strip()) if str(data_mount.get("Source") or "").strip() else None
    preferences = _mymedia_preferences_snapshot(data_dir / "Preferences.xml") if data_dir is not None else {}
    messages = _mymedia_messages_snapshot(data_dir / "Messages.xml") if data_dir is not None else {}

    summary_ok, summary_payload, summary_status_code, summary_reason = _mymedia_api_json(
        f"{effective_web_base_url.rstrip('/')}/api/Summary",
        timeout_seconds=timeout_seconds,
    )
    watchfolders_ok, watchfolders_payload, watchfolders_status_code, watchfolders_reason = _mymedia_api_json(
        f"{effective_web_base_url.rstrip('/')}/api/WatchFolders",
        timeout_seconds=timeout_seconds,
    )
    login_ok, _login_payload, login_status_code, login_reason = _mymedia_api_json(
        f"{effective_web_base_url.rstrip('/')}/api/Login",
        timeout_seconds=timeout_seconds,
    )

    summary = dict(summary_payload.get("GetSummaryInfoResult") or {}) if summary_ok else {}
    watchfolders = (
        [
            dict(item)
            for item in list(watchfolders_payload.get("GetWatchFoldersResult") or [])
            if isinstance(item, dict)
        ]
        if watchfolders_ok
        else []
    )
    watch_folder_states = [_mymedia_watchfolder_status_label(item.get("Status")) for item in watchfolders]
    watch_folder_count = len(watchfolders)
    watch_folder_error_count = sum(
        1
        for item, state_label in zip(watchfolders, watch_folder_states)
        if state_label == "error" or int(item.get("Errors") or 0) > 0
    )
    library_scan_pending = any(state_label in {"queued", "scanning", "indexing"} for state_label in watch_folder_states)
    tracks = int(summary.get("Tracks") or 0)
    connection_status = _mymedia_connection_status_label(summary.get("ConnectionStatus"))
    pairing_ready = bool(preferences.get("refresh_token_present")) or login_ok
    library_scan_blocked_by_pairing = bool(not pairing_ready and library_scan_pending and tracks == 0 and watch_folder_count > 0)
    remote_access_mode = str(preferences.get("remote_access_mode") or "").strip()
    public_ip_present = bool(preferences.get("public_ip_present"))
    external_access_ready = remote_access_mode == "push" or (remote_access_mode == "static_ip" and public_ip_present)
    container_running = bool(state.get("Running"))
    api_reachable = summary_ok and watchfolders_ok
    try:
        container_exit_code = int(state.get("ExitCode") or 0)
    except Exception:
        container_exit_code = 0
    container_oom_killed = bool(state.get("OOMKilled"))
    container_error_kind = _container_state_error_kind(state)
    host_root_disk = _host_root_disk_posture()
    host_disk_pressure_detected = container_error_kind == "host_disk_pressure"
    pairing_artifact_cleanup = (
        _mymedia_pairing_cleanup_runtime_artifacts()
        if pairing_ready
        else {"attempted": False, "removed_count": 0, "root_removed": False, "errors": []}
    )
    pairing_session = _mymedia_pairing_session_status(now=observed_now)
    public_surface = _mymedia_public_surface_probe(
        effective_public_web_base_url,
        timeout_seconds=min(max(float(timeout_seconds or 15.0), 1.0), 15.0),
    )

    reason = ""
    next_action = ""
    status = "ready"
    ready = False
    if not container_running:
        status = "blocked_runtime_unavailable"
        if host_disk_pressure_detected:
            reason = "host_disk_pressure_prevented_container_start"
            next_action = "recover_host_disk_pressure_then_start_mymedia_alexa"
        else:
            reason = "mymedia_container_not_running"
            next_action = "start_mymedia_alexa_container"
    elif not api_reachable:
        status = "blocked_console_unreachable"
        reason = "mymedia_console_api_unreachable"
        next_action = "repair_mymedia_console_api"
    elif not pairing_ready:
        status = "blocked_pairing_required"
        reason = "amazon_account_not_paired"
        if bool(pairing_session.get("resume_ready")):
            next_action = (
                "approve_mymedia_amazon_consent"
                if str(pairing_session.get("surface_kind") or "") == "consent_required"
                else "enter_mymedia_amazon_pairing_code"
            )
        else:
            next_action = (
                "complete_amazon_pairing_then_rescan_library"
                if library_scan_blocked_by_pairing
                else "complete_amazon_pairing_for_mymedia"
            )
    elif watch_folder_count == 0:
        status = "blocked_watch_folder_missing"
        reason = "mymedia_watch_folder_missing"
        next_action = "add_mymedia_watch_folder"
    elif watch_folder_error_count > 0:
        status = "blocked_watch_folder_error"
        reason = "mymedia_watch_folder_error"
        next_action = "repair_mymedia_watch_folder"
    elif not external_access_ready:
        status = "blocked_external_access_not_ready"
        reason = "mymedia_external_access_not_ready"
        next_action = "configure_mymedia_external_access"
    elif connection_status == "connecting":
        status = "blocked_connection_pending"
        reason = "amazon_connection_pending"
        next_action = "inspect_mymedia_amazon_connection"
    elif connection_status != "connected":
        status = "blocked_connection_not_ready"
        reason = "amazon_connection_not_ready"
        next_action = "inspect_mymedia_amazon_connection"
    elif library_scan_pending:
        if tracks > 0:
            status = "ready_library_scan_in_progress"
            reason = "mymedia_library_scan_in_progress"
            next_action = "wait_for_mymedia_library_scan"
            ready = True
        else:
            status = "blocked_library_scan_pending"
            reason = "mymedia_library_scan_pending"
            next_action = "rescan_mymedia_library"
    elif tracks <= 0:
        status = "blocked_library_empty"
        reason = "mymedia_library_empty"
        next_action = "rescan_mymedia_library"
    else:
        ready = True

    next_action_href, next_action_label, next_action_method = _mymedia_action_surface(
        base_url=effective_web_base_url,
        next_action=next_action,
    )
    report = {
        "probe_ok": True,
        "ready": ready,
        "status": status,
        "reason": reason,
        "next_action": next_action,
        "next_action_href": next_action_href,
        "next_action_label": next_action_label,
        "next_action_method": next_action_method,
        "container_name": effective_container_name,
        "container_running": container_running,
        "container_state_status": str(state.get("Status") or "").strip(),
        "container_exit_code": container_exit_code,
        "container_oom_killed": container_oom_killed,
        "container_error_kind": container_error_kind,
        "host_disk_pressure_detected": host_disk_pressure_detected,
        "host_root_usage_percent": host_root_disk.get("usage_percent"),
        "host_root_available_bytes": host_root_disk.get("available_bytes"),
        "host_root_available_gb": host_root_disk.get("available_gb"),
        "data_mount_present": bool(data_mount),
        "preferences_present": bool(preferences.get("preferences_present")),
        "messages_present": bool(messages.get("messages_present")),
        "api_reachable": api_reachable,
        "api_http_status_codes": {
            "summary": summary_status_code,
            "watchfolders": watchfolders_status_code,
            "login": login_status_code,
        },
        "api_error_reasons": {
            "summary": summary_reason,
            "watchfolders": watchfolders_reason,
            "login": login_reason,
        },
        "pairing_ready": pairing_ready,
        "pairing_session_pending": bool(pairing_session.get("pending_surface")),
        "pairing_resume_ready": bool(pairing_session.get("resume_ready")),
        "pairing_session_stale": bool(pairing_session.get("stale")),
        "pairing_session_age_seconds": pairing_session.get("age_seconds"),
        "pairing_session_max_age_seconds": pairing_session.get("max_age_seconds"),
        "pairing_session_captured_at": str(pairing_session.get("captured_at") or "").strip(),
        "pairing_session_surface_kind": str(pairing_session.get("surface_kind") or "").strip(),
        "pairing_session_otp_channel": str(pairing_session.get("otp_channel") or "").strip(),
        "pairing_session_phone_suffix": str(pairing_session.get("phone_suffix") or "").strip(),
        "pairing_artifact_cleanup_attempted": bool(pairing_artifact_cleanup.get("attempted")),
        "pairing_artifact_cleanup_removed_count": int(pairing_artifact_cleanup.get("removed_count") or 0),
        "pairing_artifact_cleanup_error_count": len(
            [item for item in list(pairing_artifact_cleanup.get("errors") or []) if str(item).strip()]
        ),
        "refresh_token_present": bool(preferences.get("refresh_token_present")),
        "paired_user_present": bool(preferences.get("paired_user_present")),
        "remote_access_mode": remote_access_mode,
        "public_ip_present": public_ip_present,
        "connection_status": connection_status,
        "watch_folder_count": watch_folder_count,
        "watch_folder_states": watch_folder_states[:5],
        "watch_folder_error_count": watch_folder_error_count,
        "tracks": tracks,
        "albums": int(summary.get("Albums") or 0),
        "artists": int(summary.get("Artists") or 0),
        "genres": int(summary.get("Genres") or 0),
        "library_scan_pending": library_scan_pending,
        "library_scan_blocked_by_pairing": library_scan_blocked_by_pairing,
        "message_count": int(messages.get("message_count") or 0),
        "message_warning_count": int(messages.get("warning_count") or 0),
        "message_error_count": int(messages.get("error_count") or 0),
        "web_base_url_scope": _url_scope(effective_web_base_url),
        "public_surface_configured": bool(public_surface.get("configured")),
        "public_surface_scope": str(public_surface.get("base_url_scope") or "").strip(),
        "public_surface_probe_attempted": bool(public_surface.get("probe_attempted")),
        "public_surface_ready": bool(public_surface.get("ready")),
        "public_surface_status": str(public_surface.get("status") or "").strip(),
        "public_surface_reason": str(public_surface.get("reason") or "").strip(),
        "public_surface_http_status_code": int(public_surface.get("http_status_code") or 0),
        "public_surface_access_protected": bool(public_surface.get("access_protected")),
        "public_surface_cloudflare_blocked": bool(public_surface.get("cloudflare_blocked")),
        "public_surface_redirect_host": str(public_surface.get("redirect_host") or "").strip(),
        "public_surface_content_type": str(public_surface.get("content_type") or "").strip(),
        "public_surface_next_action": str(public_surface.get("next_action") or "").strip(),
        "public_surface_next_action_href": str(public_surface.get("next_action_href") or "").strip(),
        "public_surface_next_action_label": str(public_surface.get("next_action_label") or "").strip(),
        "public_surface_next_action_method": str(public_surface.get("next_action_method") or "").strip(),
        "public_surface_source": str(public_surface.get("source") or "").strip(),
        "observed_at": observed_at,
        "source": "docker.inspect+mymedia.api+xml_mount",
        "privacy": {
            "raw_refresh_token_exposed": False,
            "raw_paired_user_exposed": False,
            "raw_watch_folder_paths_exposed": False,
            "raw_public_ip_exposed": False,
            "raw_pairing_resume_url_exposed": False,
            "raw_public_surface_redirect_exposed": False,
            "raw_public_surface_response_body_exposed": False,
        },
    }
    if output_format == "operator":
        report["operator_text"] = _operator_text_for_mymedia_alexa(report)
    return report


def _operator_text_for_mymedia_rescan(report: Mapping[str, object]) -> str:
    parts = [
        f"mymedia_rescan status={report.get('status') or 'unknown'}",
        f"ready={str(bool(report.get('ready'))).lower()}",
    ]
    reason = str(report.get("reason") or "").strip()
    next_action = str(report.get("next_action") or "").strip()
    if reason:
        parts.append(f"reason={reason}")
    if next_action:
        parts.append(f"next={next_action}")
    if "request_accepted" in report:
        parts.append(f"request_accepted={str(bool(report.get('request_accepted'))).lower()}")
    if "http_status_code" in report:
        parts.append(f"http={int(report.get('http_status_code') or 0)}")
    if "clear_history" in report:
        parts.append(f"clear_history={str(bool(report.get('clear_history'))).lower()}")
    if "watch_folder_count" in report:
        parts.append(f"watchfolders={int(report.get('watch_folder_count') or 0)}")
    if "tracks" in report:
        parts.append(f"tracks={int(report.get('tracks') or 0)}")
    if "library_scan_pending" in report:
        parts.append(f"scan_pending={str(bool(report.get('library_scan_pending'))).lower()}")
    observed_at = str(report.get("observed_at") or "").strip()
    source = str(report.get("source") or "").strip()
    if observed_at:
        parts.append(f"observed_at={observed_at}")
    if source:
        parts.append(f"source={source}")
    return "; ".join(parts)


def _operator_text_for_mymedia_console_api_repair(report: Mapping[str, object]) -> str:
    parts = [
        f"mymedia_console_api status={report.get('status') or 'unknown'}",
        f"ready={str(bool(report.get('ready'))).lower()}",
    ]
    reason = str(report.get("reason") or "").strip()
    next_action = str(report.get("next_action") or "").strip()
    if reason:
        parts.append(f"reason={reason}")
    if next_action:
        parts.append(f"next={next_action}")
    parts.append(f"restart_attempted={str(bool(report.get('restart_attempted'))).lower()}")
    if report.get("restart_ok") is not None:
        parts.append(f"restart_ok={str(bool(report.get('restart_ok'))).lower()}")
    parts.append(f"api_recovered={str(bool(report.get('api_recovered'))).lower()}")
    if report.get("pre_probe_status"):
        parts.append(f"before={report['pre_probe_status']}")
    if report.get("post_probe_status"):
        parts.append(f"after={report['post_probe_status']}")
    if report.get("observed_at"):
        parts.append(f"observed_at={report['observed_at']}")
    if report.get("source"):
        parts.append(f"source={report['source']}")
    return "; ".join(str(item) for item in parts if str(item).strip())


def rescan_mymedia_library(
    *,
    web_base_url: str = "",
    clear_history: bool = False,
    timeout_seconds: float = 15.0,
    output_format: str = "json",
) -> dict[str, object]:
    observed_at = _utc_now()
    effective_web_base_url = str(
        web_base_url or _env("EA_MYMEDIA_ALEXA_WEB_BASE_URL", DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL)
    ).strip() or DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL
    request_timeout = max(float(timeout_seconds or 15.0), 1.0)
    pre_probe = probe_mymedia_alexa(
        container_name=_env("EA_MYMEDIA_ALEXA_CONTAINER", DEFAULT_MYMEDIA_ALEXA_CONTAINER),
        web_base_url=effective_web_base_url,
        timeout_seconds=min(request_timeout, 15.0),
        output_format="json",
    )
    request_body = {"clearHistory": bool(clear_history)}
    report = {
        "probe_ok": False,
        "ready": False,
        "status": "probe_failed",
        "reason": str(pre_probe.get("reason") or "mymedia_rescan_pre_probe_failed").strip(),
        "next_action": str(pre_probe.get("next_action") or "").strip(),
        "next_action_href": str(pre_probe.get("next_action_href") or "").strip(),
        "next_action_label": str(pre_probe.get("next_action_label") or "").strip(),
        "next_action_method": str(pre_probe.get("next_action_method") or "").strip(),
        "request_accepted": False,
        "http_status_code": 0,
        "clear_history": bool(clear_history),
        "container_name": str(pre_probe.get("container_name") or "").strip(),
        "container_running": bool(pre_probe.get("container_running")),
        "api_reachable": bool(pre_probe.get("api_reachable")),
        "pairing_ready": bool(pre_probe.get("pairing_ready")),
        "watch_folder_count": int(pre_probe.get("watch_folder_count") or 0),
        "watch_folder_states": list(pre_probe.get("watch_folder_states") or [])[:5],
        "tracks": int(pre_probe.get("tracks") or 0),
        "library_scan_pending": bool(pre_probe.get("library_scan_pending")),
        "library_scan_blocked_by_pairing": bool(pre_probe.get("library_scan_blocked_by_pairing")),
        "pre_probe_status": str(pre_probe.get("status") or "").strip(),
        "post_probe_status": "",
        "post_probe_reason": "",
        "observed_at": observed_at,
        "source": "mymedia.api.rescan",
        "privacy": {
            "raw_refresh_token_exposed": False,
            "raw_paired_user_exposed": False,
            "raw_watch_folder_paths_exposed": False,
            "raw_public_ip_exposed": False,
        },
    }
    if not bool(pre_probe.get("probe_ok")):
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_mymedia_rescan(report)
        return report
    if not bool(pre_probe.get("container_running")):
        report.update(
            {
                "status": "blocked_runtime_unavailable",
                "reason": str(pre_probe.get("reason") or "mymedia_container_not_running").strip(),
            }
        )
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_mymedia_rescan(report)
        return report
    if not bool(pre_probe.get("api_reachable")):
        report.update(
            {
                "status": "blocked_console_unreachable",
                "reason": str(pre_probe.get("reason") or "mymedia_console_api_unreachable").strip(),
            }
        )
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_mymedia_rescan(report)
        return report
    if not bool(pre_probe.get("pairing_ready")):
        report.update(
            {
                "status": "blocked_pairing_required",
                "reason": str(pre_probe.get("reason") or "amazon_account_not_paired").strip(),
            }
        )
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_mymedia_rescan(report)
        return report
    if int(pre_probe.get("watch_folder_count") or 0) <= 0:
        report.update(
            {
                "status": "blocked_watch_folder_missing",
                "reason": str(pre_probe.get("reason") or "mymedia_watch_folder_missing").strip(),
            }
        )
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_mymedia_rescan(report)
        return report
    if str(pre_probe.get("status") or "").strip() in {
        "blocked_watch_folder_error",
        "blocked_external_access_not_ready",
        "blocked_connection_pending",
        "blocked_connection_not_ready",
    }:
        report.update(
            {
                "status": str(pre_probe.get("status") or "probe_failed").strip(),
                "reason": str(pre_probe.get("reason") or "").strip(),
            }
        )
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_mymedia_rescan(report)
        return report

    request_ok, _request_payload, request_status_code, request_reason = _mymedia_api_json(
        f"{effective_web_base_url.rstrip('/')}/api/Rescan",
        method="POST",
        body=request_body,
        timeout_seconds=request_timeout,
    )
    report["http_status_code"] = request_status_code
    if not request_ok:
        report.update(
            {
                "status": "request_failed",
                "reason": str(request_reason or "mymedia_rescan_request_failed").strip(),
            }
        )
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_mymedia_rescan(report)
        return report

    post_probe = probe_mymedia_alexa(
        container_name=_env("EA_MYMEDIA_ALEXA_CONTAINER", DEFAULT_MYMEDIA_ALEXA_CONTAINER),
        web_base_url=effective_web_base_url,
        timeout_seconds=min(request_timeout, 15.0),
        output_format="json",
    )
    report.update(
        {
            "probe_ok": True,
            "request_accepted": True,
            "ready": bool(post_probe.get("ready")),
            "container_name": str(post_probe.get("container_name") or report.get("container_name") or "").strip(),
            "container_running": bool(post_probe.get("container_running")),
            "api_reachable": bool(post_probe.get("api_reachable")),
            "pairing_ready": bool(post_probe.get("pairing_ready")),
            "watch_folder_count": int(post_probe.get("watch_folder_count") or 0),
            "watch_folder_states": list(post_probe.get("watch_folder_states") or [])[:5],
            "tracks": int(post_probe.get("tracks") or 0),
            "library_scan_pending": bool(post_probe.get("library_scan_pending")),
            "library_scan_blocked_by_pairing": bool(post_probe.get("library_scan_blocked_by_pairing")),
            "post_probe_status": str(post_probe.get("status") or "").strip(),
            "post_probe_reason": str(post_probe.get("reason") or "").strip(),
        }
    )
    if bool(post_probe.get("ready")):
        report.update(
            {
                "status": "ready",
                "reason": "",
                "next_action": "",
                "next_action_href": "",
                "next_action_label": "",
                "next_action_method": "",
            }
        )
    elif str(post_probe.get("status") or "").strip() in {
        "blocked_watch_folder_missing",
        "blocked_watch_folder_error",
        "blocked_external_access_not_ready",
        "blocked_connection_pending",
        "blocked_connection_not_ready",
        "blocked_pairing_required",
    }:
        report.update(
            {
                "status": str(post_probe.get("status") or "request_failed").strip(),
                "reason": str(post_probe.get("reason") or "").strip(),
                "next_action": str(post_probe.get("next_action") or "").strip(),
                "next_action_href": str(post_probe.get("next_action_href") or "").strip(),
                "next_action_label": str(post_probe.get("next_action_label") or "").strip(),
                "next_action_method": str(post_probe.get("next_action_method") or "").strip(),
            }
        )
    else:
        next_action = "wait_for_mymedia_library_scan"
        next_action_href, next_action_label, next_action_method = _mymedia_action_surface(
            base_url=effective_web_base_url,
            next_action=next_action,
        )
        report.update(
            {
                "status": "scan_requested",
                "reason": "mymedia_library_scan_requested",
                "next_action": next_action,
                "next_action_href": next_action_href,
                "next_action_label": next_action_label,
                "next_action_method": next_action_method,
            }
        )
    if output_format == "operator":
        report["operator_text"] = _operator_text_for_mymedia_rescan(report)
    return report


def repair_mymedia_console_api(
    *,
    container_name: str = "",
    web_base_url: str = "",
    timeout_seconds: float = 45.0,
    output_format: str = "json",
) -> dict[str, object]:
    observed_at = _utc_now()
    effective_container_name = str(
        container_name or _env("EA_MYMEDIA_ALEXA_CONTAINER", DEFAULT_MYMEDIA_ALEXA_CONTAINER)
    ).strip() or DEFAULT_MYMEDIA_ALEXA_CONTAINER
    effective_web_base_url = str(
        web_base_url or _env("EA_MYMEDIA_ALEXA_WEB_BASE_URL", DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL)
    ).strip() or DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL
    request_timeout = max(float(timeout_seconds or 45.0), 1.0)
    receipt_path = DEFAULT_MYMEDIA_ALEXA_CONSOLE_API_REPAIR_RECEIPT
    pre_probe = probe_mymedia_alexa(
        container_name=effective_container_name,
        web_base_url=effective_web_base_url,
        timeout_seconds=min(request_timeout, 15.0),
        output_format="json",
    )
    report = {
        "probe_ok": bool(pre_probe.get("probe_ok")),
        "ready": False,
        "status": "probe_failed",
        "reason": str(pre_probe.get("reason") or "mymedia_console_api_pre_probe_failed").strip(),
        "next_action": str(pre_probe.get("next_action") or "").strip(),
        "next_action_href": str(pre_probe.get("next_action_href") or "").strip(),
        "next_action_label": str(pre_probe.get("next_action_label") or "").strip(),
        "next_action_method": str(pre_probe.get("next_action_method") or "").strip(),
        "container_name": effective_container_name,
        "container_running": bool(pre_probe.get("container_running")),
        "api_reachable": bool(pre_probe.get("api_reachable")),
        "restart_attempted": False,
        "restart_ok": None,
        "restart_reason": "",
        "api_recovered": bool(pre_probe.get("api_reachable")),
        "pre_probe_status": str(pre_probe.get("status") or "").strip(),
        "post_probe_status": "",
        "post_probe_reason": "",
        "before_probe": pre_probe,
        "after_probe": pre_probe,
        "observed_at": observed_at,
        "source": "docker.restart+mymedia.probe",
        "privacy": {
            "raw_refresh_token_exposed": False,
            "raw_paired_user_exposed": False,
            "raw_watch_folder_paths_exposed": False,
            "raw_public_ip_exposed": False,
        },
    }

    def _finalize(updated: dict[str, object]) -> dict[str, object]:
        updated["receipt_path"] = str(receipt_path)
        _write_private_json(receipt_path, updated)
        if output_format == "operator":
            updated["operator_text"] = _operator_text_for_mymedia_console_api_repair(updated)
        return updated

    if not bool(pre_probe.get("probe_ok")):
        return _finalize(report)
    if not bool(pre_probe.get("container_running")):
        report.update(
            {
                "status": "repair_blocked",
                "reason": str(pre_probe.get("reason") or "mymedia_container_not_running").strip(),
                "next_action": "start_mymedia_alexa_container",
            }
        )
        next_action_href, next_action_label, next_action_method = _mymedia_action_surface(
            base_url=effective_web_base_url,
            next_action=str(report.get("next_action") or "").strip(),
        )
        report["next_action_href"] = next_action_href
        report["next_action_label"] = next_action_label
        report["next_action_method"] = next_action_method
        return _finalize(report)
    if bool(pre_probe.get("api_reachable")):
        report.update(
            {
                "ready": True,
                "status": "ready",
                "reason": "",
                "next_action": str(pre_probe.get("next_action") or "").strip(),
                "next_action_href": str(pre_probe.get("next_action_href") or "").strip(),
                "next_action_label": str(pre_probe.get("next_action_label") or "").strip(),
                "next_action_method": str(pre_probe.get("next_action_method") or "").strip(),
            }
        )
        return _finalize(report)

    restart = _docker_restart_container(effective_container_name, timeout_seconds=min(request_timeout, 30.0))
    report.update(
        {
            "restart_attempted": True,
            "restart_ok": bool(restart.get("ok")),
            "restart_reason": str(restart.get("reason") or "").strip(),
        }
    )
    if not bool(restart.get("ok")):
        report.update(
            {
                "status": "repair_failed",
                "reason": str(restart.get("reason") or "docker_restart_failed").strip(),
                "next_action": "inspect_mymedia_console_api",
            }
        )
        next_action_href, next_action_label, next_action_method = _mymedia_action_surface(
            base_url=effective_web_base_url,
            next_action=str(report.get("next_action") or "").strip(),
        )
        report["next_action_href"] = next_action_href
        report["next_action_label"] = next_action_label
        report["next_action_method"] = next_action_method
        return _finalize(report)

    deadline = time.monotonic() + min(request_timeout, 60.0)
    post_probe = pre_probe
    while True:
        post_probe = probe_mymedia_alexa(
            container_name=effective_container_name,
            web_base_url=effective_web_base_url,
            timeout_seconds=min(max(request_timeout / 3.0, 5.0), 15.0),
            output_format="json",
        )
        if bool(post_probe.get("api_reachable")) or time.monotonic() >= deadline:
            break
        time.sleep(2.0)
    report.update(
        {
            "ready": bool(post_probe.get("ready")),
            "status": "repaired" if bool(post_probe.get("api_reachable")) else "repair_failed",
            "reason": str(post_probe.get("reason") or "").strip(),
            "next_action": str(post_probe.get("next_action") or "").strip(),
            "next_action_href": str(post_probe.get("next_action_href") or "").strip(),
            "next_action_label": str(post_probe.get("next_action_label") or "").strip(),
            "next_action_method": str(post_probe.get("next_action_method") or "").strip(),
            "container_running": bool(post_probe.get("container_running")),
            "api_reachable": bool(post_probe.get("api_reachable")),
            "api_recovered": bool(post_probe.get("api_reachable")),
            "post_probe_status": str(post_probe.get("status") or "").strip(),
            "post_probe_reason": str(post_probe.get("reason") or "").strip(),
            "after_probe": post_probe,
        }
    )
    return _finalize(report)


def _mymedia_pairing_root(output_dir: str = "") -> Path:
    return Path(output_dir or _env("EA_MYMEDIA_ALEXA_PAIRING_DIR", str(DEFAULT_MYMEDIA_ALEXA_PAIRING_DIR)))


def _mymedia_pairing_state_path(output_dir: str = "") -> Path:
    return _mymedia_pairing_root(output_dir) / "storage_state.json"


def _mymedia_pairing_session_path(output_dir: str = "") -> Path:
    return _mymedia_pairing_root(output_dir) / "session.json"


def _mymedia_pairing_screenshot_path(output_dir: str = "") -> Path:
    return _mymedia_pairing_root(output_dir) / "surface.png"


def _mymedia_pairing_cleanup_runtime_artifacts(output_dir: str = "") -> dict[str, object]:
    root = _mymedia_pairing_root(output_dir)
    candidates = (
        _mymedia_pairing_state_path(output_dir),
        _mymedia_pairing_session_path(output_dir),
        _mymedia_pairing_screenshot_path(output_dir),
    )
    removed_count = 0
    errors: list[str] = []
    for path in candidates:
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
                removed_count += 1
            elif path.is_dir():
                shutil.rmtree(path)
                removed_count += 1
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append(f"{path.name}:{type(exc).__name__}")
    root_removed = False
    try:
        if root.is_dir() and not any(root.iterdir()):
            root.rmdir()
            root_removed = True
    except OSError:
        root_removed = False
    return {
        "attempted": removed_count > 0 or bool(errors),
        "removed_count": removed_count,
        "root_removed": root_removed,
        "errors": errors,
    }


def _write_private_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, path)


def _operator_text_for_mymedia_public_surface_repair(report: Mapping[str, object]) -> str:
    before = dict(report.get("before_public_surface") or {})
    after = dict(report.get("after_public_surface") or {})
    parts = [
        f"mymedia_public_surface status={report.get('status') or 'unknown'}",
        f"ready={str(bool(report.get('ready'))).lower()}",
    ]
    reason = str(report.get("reason") or "").strip()
    next_action = str(report.get("next_action") or "").strip()
    if reason:
        parts.append(f"reason={reason}")
    if next_action:
        parts.append(f"next={next_action}")
    if report.get("public_host"):
        parts.append(f"host={report['public_host']}")
    if before.get("status"):
        parts.append(f"before={before['status']}")
    if after.get("status"):
        parts.append(f"after={after['status']}")
    parts.append(f"dns_changed={str(bool(report.get('dns_changed'))).lower()}")
    parts.append(f"tunnel_changed={str(bool(report.get('tunnel_changed'))).lower()}")
    parts.append(f"access_changed={str(bool(report.get('access_app_changed'))).lower()}")
    parts.append(f"firewall_changed={str(bool(report.get('firewall_changed'))).lower()}")
    if report.get("firewall_patched_rule_count") is not None:
        parts.append(f"firewall_rules={int(report.get('firewall_patched_rule_count') or 0)}")
    if report.get("receipt_path"):
        parts.append(f"receipt={report['receipt_path']}")
    if report.get("observed_at"):
        parts.append(f"observed_at={report['observed_at']}")
    if report.get("source"):
        parts.append(f"source={report['source']}")
    return "; ".join(str(item) for item in parts if str(item).strip())


def repair_mymedia_public_surface(
    *,
    web_base_url: str = "",
    public_web_base_url: str = "",
    public_tunnel_origin_url: str = "",
    timeout_seconds: float = 30.0,
    output_format: str = "json",
) -> dict[str, object]:
    observed_at = _utc_now()
    request_timeout = max(float(timeout_seconds or 30.0), 1.0)
    effective_web_base_url = str(
        web_base_url or _env("EA_MYMEDIA_ALEXA_WEB_BASE_URL", DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL)
    ).strip() or DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL
    effective_public_web_base_url = str(
        public_web_base_url or _env("EA_MYMEDIA_ALEXA_PUBLIC_BASE_URL", DEFAULT_MYMEDIA_ALEXA_PUBLIC_BASE_URL)
    ).strip()
    effective_public_tunnel_origin = _mymedia_public_surface_tunnel_origin(
        effective_web_base_url,
        explicit_origin_url=str(
            public_tunnel_origin_url
            or _env("EA_MYMEDIA_ALEXA_PUBLIC_TUNNEL_ORIGIN_URL", DEFAULT_MYMEDIA_ALEXA_PUBLIC_TUNNEL_ORIGIN_URL)
        ).strip(),
    )
    effective_tunnel_name = str(
        _env("EA_MYMEDIA_ALEXA_CLOUDFLARE_TUNNEL_NAME", DEFAULT_MYMEDIA_ALEXA_CLOUDFLARE_TUNNEL_NAME)
    ).strip() or DEFAULT_MYMEDIA_ALEXA_CLOUDFLARE_TUNNEL_NAME
    effective_access_env_file = str(
        _env("EA_MYMEDIA_ALEXA_CF_ACCESS_ENV_FILE", DEFAULT_MYMEDIA_ALEXA_CF_ACCESS_ENV_FILE)
    ).strip() or DEFAULT_MYMEDIA_ALEXA_CF_ACCESS_ENV_FILE
    effective_access_emails = _mymedia_runtime_default_value(
        env_names=("EA_MYMEDIA_ALEXA_ACCESS_EMAILS",),
        payload_keys=("access_emails",),
        default=DEFAULT_MYMEDIA_ALEXA_ACCESS_EMAILS,
    )
    effective_access_app_name = str(
        _env("EA_MYMEDIA_ALEXA_ACCESS_APP_NAME", DEFAULT_MYMEDIA_ALEXA_ACCESS_APP_NAME)
    ).strip() or DEFAULT_MYMEDIA_ALEXA_ACCESS_APP_NAME
    exception_base_hosts = [
        item.strip().lower()
        for item in _mymedia_runtime_default_value(
            env_names=("EA_MYMEDIA_ALEXA_CLOUDFLARE_EXCEPTION_BASE_HOSTS",),
            payload_keys=("cloudflare_exception_base_hosts",),
            default=DEFAULT_MYMEDIA_ALEXA_CLOUDFLARE_EXCEPTION_BASE_HOSTS,
        ).split(",")
        if item.strip()
    ]
    receipt_path = DEFAULT_MYMEDIA_ALEXA_PUBLIC_SURFACE_REPAIR_RECEIPT

    def _finalize(report: dict[str, object]) -> dict[str, object]:
        report["receipt_path"] = str(receipt_path)
        report.setdefault(
            "privacy",
            {
                "raw_api_key_exposed": False,
                "raw_service_token_exposed": False,
                "raw_access_client_id_exposed": False,
                "raw_public_surface_redirect_exposed": False,
            },
        )
        _write_private_json(receipt_path, report)
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_mymedia_public_surface_repair(report)
        return report

    before = _mymedia_public_surface_probe(
        effective_public_web_base_url,
        timeout_seconds=min(request_timeout, 15.0),
    )
    public_host = str(urllib.parse.urlparse(effective_public_web_base_url).hostname or "").strip().lower()
    report: dict[str, object] = {
        "probe_ok": True,
        "ready": False,
        "status": "repair_incomplete",
        "reason": str(before.get("reason") or "").strip(),
        "next_action": str(before.get("next_action") or "").strip(),
        "next_action_href": str(before.get("next_action_href") or "").strip(),
        "next_action_label": str(before.get("next_action_label") or "").strip(),
        "next_action_method": str(before.get("next_action_method") or "").strip(),
        "public_host": public_host,
        "public_web_base_url": effective_public_web_base_url,
        "expected_tunnel_origin_url": effective_public_tunnel_origin,
        "tunnel_name": effective_tunnel_name,
        "dns_changed": False,
        "tunnel_changed": False,
        "access_app_changed": False,
        "firewall_changed": False,
        "firewall_patched_rule_count": 0,
        "before_public_surface": before,
        "after_public_surface": before,
        "observed_at": observed_at,
        "source": "cloudflare.dns+tunnel+access+ruleset",
    }
    if not bool(before.get("configured")):
        report.update(
            {
                "probe_ok": False,
                "status": "not_configured",
                "reason": "mymedia_public_console_url_not_configured",
                "next_action": "configure_public_mymedia_console_url",
            }
        )
        return _finalize(report)
    if str(before.get("base_url_scope") or "").strip() != "public":
        report.update(
            {
                "probe_ok": False,
                "status": "not_public",
                "reason": "mymedia_public_console_url_not_public",
                "next_action": "configure_public_mymedia_console_url",
            }
        )
        return _finalize(report)
    if not public_host or not effective_public_tunnel_origin:
        report.update(
            {
                "probe_ok": False,
                "status": "repair_blocked",
                "reason": "mymedia_public_console_origin_missing",
                "next_action": "configure_public_mymedia_console_url",
            }
        )
        return _finalize(report)
    if not _cloudflare_auth_ready():
        report.update(
            {
                "probe_ok": False,
                "status": "repair_blocked",
                "reason": "cloudflare_credentials_missing",
                "next_action": "configure_cloudflare_credentials_for_mymedia_public_surface",
            }
        )
        return _finalize(report)

    zone = _cloudflare_lookup_zone_for_host(public_host, timeout_seconds=request_timeout)
    if not bool(zone.get("ok")):
        report.update(
            {
                "status": "repair_blocked",
                "reason": str(zone.get("reason") or "cloudflare_zone_not_found").strip(),
                "next_action": "inspect_mymedia_public_console_route",
            }
        )
        return _finalize(report)
    account_id = str(zone.get("account_id") or "").strip()
    zone_id = str(zone.get("zone_id") or "").strip()
    report["zone_name"] = str(zone.get("zone_name") or "").strip()

    tunnel = _cloudflare_lookup_named_tunnel(account_id, effective_tunnel_name, timeout_seconds=request_timeout)
    if not bool(tunnel.get("ok")):
        report.update(
            {
                "status": "repair_blocked",
                "reason": str(tunnel.get("reason") or "cloudflare_tunnel_not_found").strip(),
                "next_action": "inspect_mymedia_public_console_route",
            }
        )
        return _finalize(report)
    report["tunnel_domain"] = str(tunnel.get("tunnel_domain") or "").strip()

    dns_step = _cloudflare_upsert_dns_record(
        zone_id,
        host_name=public_host,
        target_name=str(tunnel.get("tunnel_domain") or "").strip(),
        proxied=True,
        timeout_seconds=request_timeout,
    )
    report["dns_changed"] = bool(dns_step.get("changed"))
    report["dns_record_present"] = bool(dns_step.get("record_present"))
    if not bool(dns_step.get("ok")):
        report.update(
            {
                "status": "repair_failed",
                "reason": str(dns_step.get("reason") or "cloudflare_dns_update_failed").strip(),
                "next_action": "inspect_mymedia_public_console_route",
            }
        )
        return _finalize(report)

    tunnel_step = _cloudflare_upsert_tunnel_ingress(
        account_id,
        str(tunnel.get("tunnel_id") or "").strip(),
        public_host=public_host,
        service_url=effective_public_tunnel_origin,
        timeout_seconds=request_timeout,
    )
    report["tunnel_changed"] = bool(tunnel_step.get("changed"))
    report["tunnel_route_present"] = bool(tunnel_step.get("route_present"))
    if not bool(tunnel_step.get("ok")):
        report.update(
            {
                "status": "repair_failed",
                "reason": str(tunnel_step.get("reason") or "cloudflare_tunnel_config_update_failed").strip(),
                "next_action": "inspect_mymedia_public_console_route",
            }
        )
        return _finalize(report)

    token = _cloudflare_lookup_access_service_token(
        account_id,
        access_env_file=effective_access_env_file,
        service_token_name=str(_env("EA_MYMEDIA_ALEXA_CF_SERVICE_TOKEN_NAME", "")).strip(),
        timeout_seconds=request_timeout,
    )
    access_step = _cloudflare_upsert_access_app(
        zone_id,
        public_host=public_host,
        access_app_name=effective_access_app_name,
        access_emails_csv=effective_access_emails,
        service_token_id=str(token.get("service_token_id") or "").strip(),
        timeout_seconds=request_timeout,
    )
    report["access_app_changed"] = bool(access_step.get("changed"))
    report["access_app_present"] = bool(access_step.get("app_present"))
    report["access_app_skipped"] = bool(access_step.get("skipped"))
    report["access_app_reason"] = str(access_step.get("reason") or "").strip()
    if not bool(access_step.get("ok")):
        report.update(
            {
                "status": "repair_failed",
                "reason": str(access_step.get("reason") or "cloudflare_access_app_update_failed").strip(),
                "next_action": "inspect_mymedia_public_console_access",
            }
        )
        return _finalize(report)

    firewall_step = _cloudflare_patch_private_host_block_exceptions(
        zone_id,
        public_host=public_host,
        required_existing_hosts=exception_base_hosts,
        timeout_seconds=request_timeout,
    )
    report["firewall_changed"] = bool(firewall_step.get("changed"))
    report["firewall_patched_rule_count"] = int(firewall_step.get("patched_rule_count") or 0)
    report["firewall_skipped"] = bool(firewall_step.get("skipped"))
    if not bool(firewall_step.get("ok")):
        report.update(
            {
                "status": "repair_failed",
                "reason": str(firewall_step.get("reason") or "cloudflare_firewall_rule_patch_failed").strip(),
                "next_action": "inspect_mymedia_public_console_access",
            }
        )
        return _finalize(report)

    if any(
        bool(report.get(key))
        for key in ("dns_changed", "tunnel_changed", "access_app_changed", "firewall_changed")
    ):
        time.sleep(2.0)

    after = before
    for _ in range(3):
        after = _mymedia_public_surface_probe(
            effective_public_web_base_url,
            timeout_seconds=min(request_timeout, 15.0),
        )
        if bool(after.get("ready")):
            break
        time.sleep(1.0)
    report["after_public_surface"] = after
    report["ready"] = bool(after.get("ready"))
    report["next_action"] = str(after.get("next_action") or "").strip()
    report["next_action_href"] = str(after.get("next_action_href") or "").strip()
    report["next_action_label"] = str(after.get("next_action_label") or "").strip()
    report["next_action_method"] = str(after.get("next_action_method") or "").strip()

    changed = any(
        bool(report.get(key))
        for key in ("dns_changed", "tunnel_changed", "access_app_changed", "firewall_changed")
    )
    if bool(after.get("ready")):
        report["status"] = "repaired" if changed else "ready"
        report["reason"] = ""
        report["next_action"] = ""
        report["next_action_href"] = ""
        report["next_action_label"] = ""
        report["next_action_method"] = ""
    else:
        report["status"] = "repair_incomplete" if changed else "no_change"
        report["reason"] = str(after.get("reason") or before.get("reason") or "mymedia_public_console_not_ready").strip()
    return _finalize(report)


def _mymedia_pairing_capture_existing_resume_bundle(output_dir: str = "", *, now: datetime | None = None) -> dict[str, object]:
    session_status = _mymedia_pairing_session_status(output_dir, now=now)
    state_path = _mymedia_pairing_state_path(output_dir)
    session_path = _mymedia_pairing_session_path(output_dir)
    screenshot_path = _mymedia_pairing_screenshot_path(output_dir)
    if not bool(session_status.get("resume_ready")):
        return dict(session_status)
    snapshot = dict(session_status)
    snapshot["state_bytes"] = state_path.read_bytes() if state_path.exists() else b""
    snapshot["session_bytes"] = session_path.read_bytes() if session_path.exists() else b""
    snapshot["screenshot_bytes"] = screenshot_path.read_bytes() if screenshot_path.exists() else b""
    return snapshot


def _mymedia_pairing_restore_resume_bundle(bundle: Mapping[str, object], output_dir: str = "") -> bool:
    if not bool(bundle.get("resume_ready")):
        return False
    state_bytes = bundle.get("state_bytes")
    session_bytes = bundle.get("session_bytes")
    if not isinstance(state_bytes, (bytes, bytearray)) or not isinstance(session_bytes, (bytes, bytearray)):
        return False
    root = _mymedia_pairing_root(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    state_path = _mymedia_pairing_state_path(output_dir)
    session_path = _mymedia_pairing_session_path(output_dir)
    state_path.write_bytes(bytes(state_bytes))
    session_path.write_bytes(bytes(session_bytes))
    state_path.chmod(0o600)
    session_path.chmod(0o600)
    screenshot_bytes = bundle.get("screenshot_bytes")
    screenshot_path = _mymedia_pairing_screenshot_path(output_dir)
    if isinstance(screenshot_bytes, (bytes, bytearray)) and screenshot_bytes:
        screenshot_path.write_bytes(bytes(screenshot_bytes))
        screenshot_path.chmod(0o600)
    return True


def _mymedia_setup_url(*, web_base_url: str, setup_url: str = "") -> str:
    explicit = str(setup_url or "").strip()
    if explicit:
        return explicit
    normalized_base = str(web_base_url or "").rstrip("/")
    return f"{normalized_base}{DEFAULT_MYMEDIA_ALEXA_SETUP_PATH}" if normalized_base else DEFAULT_MYMEDIA_ALEXA_SETUP_PATH


def _mymedia_pairing_surface_kind(url: str, body_text: str) -> dict[str, object]:
    normalized_text = " ".join(str(body_text or "").split()).strip().lower()
    parsed = urllib.parse.urlparse(str(url or "").strip())
    host = str(parsed.hostname or "").strip().lower()
    path = str(parsed.path or "").strip()
    local_console_host = host in {"", "127.0.0.1", "localhost", "::1", "0.0.0.0"}
    invalid_code = any(
        marker in normalized_text
        for marker in (
            "code is not valid",
            "code you entered is not valid",
            "invalid code",
            "incorrect code",
            "incorrect otp",
            "expired code",
            "one time password (otp) you entered is not valid",
        )
    )
    if local_console_host and "welcome to my media for alexa" in normalized_text and "pair your server" in normalized_text:
        kind = "setup_intro"
    elif host.endswith("amazon.com") and (
        ("sign in" in normalized_text and "enter mobile number or email" in normalized_text)
        or "enter email or mobile phone number" in normalized_text
        or (
            "password" in normalized_text
            and (
                "forgot password" in normalized_text
                or "sign in with a passkey" in normalized_text
                or "passkey" in normalized_text
            )
        )
    ):
        kind = "amazon_signin"
    elif host.endswith("amazon.com") and (
        "choose where you'd like to receive or generate the code" in normalized_text
        or "choose where you would like to receive or generate the code" in normalized_text
        or "wähle aus, wo du den code erhalten oder generieren möchtest" in normalized_text
        or "otp senden" in normalized_text
        or "send otp" in normalized_text
    ):
        kind = "mfa_route_selection"
    elif host.endswith("amazon.com") and (
        "code eingeben" in normalized_text
        or "enter code" in normalized_text
        or "security code" in normalized_text
        or "verification code" in normalized_text
        or "look on whatsapp for a message" in normalized_text
        or "schau auf whatsapp" in normalized_text
        or "two-step verification" in normalized_text
        or "zwei-schritt-verifizierung" in normalized_text
    ):
        kind = "waiting_for_code"
    elif host.endswith("amazon.com") and (
        "/ap/oa" in path.lower()
        or "authorize" in normalized_text
        or "authorise" in normalized_text
        or "allow access" in normalized_text
        or "share your name and email address" in normalized_text
        or "login with amazon" in normalized_text
    ):
        kind = "consent_required"
    elif local_console_host and "my media for alexa" in normalized_text and "settings" in normalized_text and "messages" in normalized_text:
        kind = "local_console"
    else:
        kind = "unknown"
    return {
        "kind": kind,
        "invalid_code": invalid_code,
        "current_host": host,
        "current_path": path,
        "current_url_sha256": _hash_text(url),
    }


def _mymedia_pairing_route_matches(text: str, *, otp_channel: str, phone_suffix: str) -> bool:
    normalized = " ".join(str(text or "").split()).strip().lower()
    digits = _digits(normalized)
    suffix = _digits(phone_suffix)
    channel = str(otp_channel or "").strip().lower()
    if suffix and suffix not in digits:
        return False
    if channel == "sms":
        return "sms" in normalized or "text message" in normalized or "text me" in normalized
    if channel == "call":
        return "call" in normalized or "phone call" in normalized or "anrufen" in normalized
    return "whatsapp" in normalized


def _mymedia_pairing_route_request_issue(
    text: str,
    *,
    otp_channel: str,
    phone_suffix: str,
) -> dict[str, object] | None:
    normalized = " ".join(str(text or "").split()).strip().lower()
    suffix = _digits(phone_suffix)
    channel = str(otp_channel or "").strip().lower()
    if (
        "please wait at least one minute before requesting another code" in normalized
        or "bitte warte mindestens eine minute bevor du einen weiteren code anforderst" in normalized
    ):
        return {
            "status": "blocked_pairing_code_request_cooldown",
            "reason": "mymedia_pairing_code_request_cooldown",
            "next_action": "wait_before_retrying_mymedia_pairing_code",
            "blockers": ["mfa_code_request_cooldown"],
        }
    if channel == "sms" and (
        "unable to send an sms" in normalized or "keine sms" in normalized or "wir können derzeit keine sms" in normalized
    ):
        return {
            "status": "blocked_pairing_route_unavailable",
            "reason": "mymedia_pairing_route_unavailable",
            "next_action": "switch_mymedia_pairing_route",
            "blockers": ["mfa_route_unavailable"],
            "failed_route": _mymedia_pairing_route_label(otp_channel=channel, phone_suffix=suffix),
        }
    return None


def _mymedia_pairing_route_label(*, otp_channel: str, phone_suffix: str) -> str:
    normalized_channel = str(otp_channel or "").strip().lower() or "whatsapp"
    suffix = _digits(phone_suffix)
    if suffix:
        return f"{normalized_channel}:*{suffix}"
    return normalized_channel


def _operator_text_for_mymedia_pairing(report: Mapping[str, object]) -> str:
    pieces = [
        f"mymedia_pairing status={report.get('status') or 'unknown'}",
        f"ready={str(bool(report.get('ready'))).lower()}",
    ]
    if report.get("reason"):
        pieces.append(f"reason={report['reason']}")
    if report.get("next_action"):
        pieces.append(f"next={report['next_action']}")
    if report.get("surface_kind"):
        pieces.append(f"surface={report['surface_kind']}")
    if report.get("site"):
        pieces.append(f"site={report['site']}")
    if report.get("otp_channel"):
        pieces.append(f"otp_channel={report['otp_channel']}")
    if report.get("phone_suffix"):
        pieces.append(f"phone_suffix=*{report['phone_suffix']}")
    if report.get("attempt_status"):
        pieces.append(f"attempt={report['attempt_status']}")
    if report.get("attempt_failed_route"):
        pieces.append(f"attempted_route={report['attempt_failed_route']}")
    if report.get("previous_actionable_handoff_preserved") is not None:
        pieces.append(
            f"previous_handoff_preserved={str(bool(report.get('previous_actionable_handoff_preserved'))).lower()}"
        )
    pieces.append(f"code_entry_ready={str(bool(report.get('code_entry_ready'))).lower()}")
    pieces.append(f"state_written={str(bool(report.get('state_written'))).lower()}")
    if report.get("telegram_sent") is not None:
        pieces.append(f"telegram_sent={str(bool(report.get('telegram_sent'))).lower()}")
    if report.get("observed_at"):
        pieces.append(f"observed_at={report['observed_at']}")
    if report.get("source"):
        pieces.append(f"source={report['source']}")
    return "; ".join(str(item) for item in pieces if str(item).strip())


def _mymedia_pairing_waiting_telegram_text(report: Mapping[str, object]) -> str:
    lines = [
        "My Media for Alexa pairing is waiting for an Amazon security code.",
        f"otp_channel={str(report.get('otp_channel') or '').strip() or 'unknown'}",
        f"phone_suffix=*{str(report.get('phone_suffix') or '').strip() or 'unknown'}",
        "action=Reply in Codex with the current 6-digit code to finish My Media pairing.",
    ]
    return "\n".join(line for line in lines if str(line).strip()).strip()


def _mymedia_pairing_action_required_telegram_text(report: Mapping[str, object]) -> str:
    surface_kind = str(report.get("surface_kind") or "").strip()
    next_action = str(report.get("next_action") or "").strip()
    if surface_kind == "consent_required" or next_action == "approve_mymedia_amazon_consent":
        lines = [
            "My Media for Alexa pairing is waiting for Amazon consent.",
            f"site={str(report.get('site') or '').strip() or 'unknown'}",
            "action=Return to Codex and approve the pending Amazon consent step to finish My Media pairing.",
        ]
        return "\n".join(line for line in lines if str(line).strip()).strip()
    return _mymedia_pairing_waiting_telegram_text(report)


def _mymedia_pairing_with_telegram_delivery(
    report: Mapping[str, object],
    *,
    principal_id: str,
    timeout_seconds: float,
    dry_run: bool = False,
    telegram_operator_streams: tuple[str, ...] | str | None = None,
) -> dict[str, object]:
    updated = dict(report)
    updated.setdefault("telegram_delivery", {})
    operator_stream = OPERATOR_STREAM_MEDIA_MEMORIAL
    allowed_operator_streams = _effective_telegram_operator_streams(telegram_operator_streams)
    updated["operator_stream"] = operator_stream
    updated["allowed_operator_streams"] = list(allowed_operator_streams)
    if not str(principal_id or "").strip():
        return updated
    if str(updated.get("status") or "").strip() not in {"waiting_for_code", "consent_required"}:
        return updated
    if not _telegram_operator_stream_allowed(operator_stream, allowed_operator_streams=allowed_operator_streams):
        telegram = _suppressed_telegram_delivery(
            principal_id=str(principal_id or "").strip(),
            operator_stream=operator_stream,
            allowed_operator_streams=allowed_operator_streams,
            observed_at=str(updated.get("observed_at") or _utc_now()).strip() or _utc_now(),
            source="scripts.ea_live_ops.mymedia_pairing",
        )
    else:
        telegram = send_telegram(
            principal_id=str(principal_id or "").strip(),
            text=_mymedia_pairing_action_required_telegram_text(updated),
            dry_run=bool(dry_run),
            timeout_seconds=min(max(float(timeout_seconds or 45.0), 1.0), 30.0),
        )
    updated.update(
        {
            "telegram_sent": bool(telegram.get("sent")),
            "telegram_reason": str(telegram.get("reason") or "").strip(),
            "telegram_principal_id": str(telegram.get("principal_id") or principal_id or "").strip(),
            "telegram_message_count": int(telegram.get("message_count") or 0),
            "telegram_chat_ref_present": bool(telegram.get("chat_ref_present")),
            "telegram_chat_ref_sha256": str(telegram.get("chat_ref_sha256") or "").strip(),
        }
    )
    updated["telegram_delivery"] = telegram
    return updated


def _mymedia_pairing_fill_first_visible(page: Any, selectors: tuple[str, ...], value: str) -> str:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.is_visible(timeout=1000):
                locator.fill(value)
                return selector
        except Exception:
            continue
    return ""


def _mymedia_pairing_wait_for_visible_selector(page: Any, selectors: tuple[str, ...], *, timeout_seconds: float) -> str:
    deadline = time.monotonic() + max(float(timeout_seconds or 10.0), 1.0)
    while time.monotonic() <= deadline:
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if locator.is_visible(timeout=500):
                    return selector
            except Exception:
                continue
        try:
            page.wait_for_timeout(500)
        except Exception:
            time.sleep(0.5)
    return ""


def _mymedia_pairing_click_submit(page: Any, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        try:
            locator = page.get_by_role("button", name=re.compile(pattern, re.I)).first
            if locator.count() and locator.is_enabled():
                locator.click()
                return pattern
        except Exception:
            continue
    for selector in ("input[type='submit']", "button[type='submit']"):
        locator = page.locator(selector).first
        try:
            if locator.count() and locator.is_enabled():
                locator.click(force=True)
                return selector
        except Exception:
            continue
    return ""


def _mymedia_pairing_wait_for_surface(page: Any, *, timeout_seconds: float) -> tuple[dict[str, object], str]:
    deadline = time.monotonic() + max(float(timeout_seconds or 45.0), 1.0)
    last_text = ""
    last_surface = _mymedia_pairing_surface_kind(page.url, last_text)
    while time.monotonic() <= deadline:
        try:
            last_text = (page.locator("body").inner_text() or "")[:8000]
        except Exception:
            last_text = ""
        last_surface = _mymedia_pairing_surface_kind(page.url, last_text)
        if str(last_surface.get("kind") or "") != "unknown":
            return last_surface, last_text
        page.wait_for_timeout(1000)
    return last_surface, last_text


def _mymedia_pairing_capture_runtime_state(
    *,
    context: Any,
    page: Any,
    otp_channel: str,
    phone_suffix: str,
    surface: Mapping[str, object],
    body_text: str,
    output_dir: str,
) -> dict[str, object]:
    state_path = _mymedia_pairing_state_path(output_dir)
    session_path = _mymedia_pairing_session_path(output_dir)
    screenshot_path = _mymedia_pairing_screenshot_path(output_dir)
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(state_path))
        state_path.chmod(0o600)
        state_written = True
    except Exception:
        state_written = False
    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
        screenshot_path.chmod(0o600)
        screenshot_written = True
    except Exception:
        screenshot_written = False
    session_payload = {
        "resume_url": str(page.url or "").strip(),
        "otp_channel": str(otp_channel or "").strip().lower(),
        "phone_suffix": _digits(phone_suffix),
        "surface_kind": str(surface.get("kind") or "").strip(),
        "site": str(surface.get("current_host") or "").strip(),
        "current_path": str(surface.get("current_path") or "").strip(),
        "current_url_sha256": str(surface.get("current_url_sha256") or "").strip(),
        "body_text_sha256": _hash_text(body_text),
        "captured_at": _utc_now(),
    }
    _write_private_json(session_path, session_payload)
    return {
        "state_path": str(state_path),
        "session_path": str(session_path),
        "screenshot_path": str(screenshot_path) if screenshot_written else "",
        "state_written": state_written,
        "session_written": True,
        "screenshot_written": screenshot_written,
    }


def _mymedia_pairing_load_session(output_dir: str) -> dict[str, object]:
    return _read_json_file(_mymedia_pairing_session_path(output_dir))


def _mymedia_pairing_session_age_seconds(captured_at: object, *, now: datetime | None = None) -> int | None:
    raw = str(captured_at or "").strip()
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    return max(0, int((current - parsed.astimezone(UTC)).total_seconds()))


def _parse_utc_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc_age_seconds(value: object, *, now: datetime | None = None) -> int | None:
    parsed = _parse_utc_datetime(value)
    if parsed is None:
        return None
    current = now or datetime.now(UTC)
    return max(0, int((current - parsed).total_seconds()))


def _mymedia_pairing_session_status(output_dir: str = "", *, now: datetime | None = None) -> dict[str, object]:
    session = _mymedia_pairing_load_session(output_dir)
    state_path = _mymedia_pairing_state_path(output_dir)
    session_path = _mymedia_pairing_session_path(output_dir)
    surface_kind = str(session.get("surface_kind") or "").strip()
    otp_channel = str(session.get("otp_channel") or "").strip().lower()
    phone_suffix = _digits(session.get("phone_suffix") or "")
    resume_url_present = bool(str(session.get("resume_url") or "").strip())
    age_seconds = _mymedia_pairing_session_age_seconds(session.get("captured_at"), now=now)
    try:
        max_age_seconds = max(
            int(
                float(
                    _env(
                        "EA_MYMEDIA_ALEXA_PAIRING_SESSION_MAX_AGE_SECONDS",
                        str(DEFAULT_MYMEDIA_ALEXA_PAIRING_SESSION_MAX_AGE_SECONDS),
                    )
                    or DEFAULT_MYMEDIA_ALEXA_PAIRING_SESSION_MAX_AGE_SECONDS
                )
            ),
            1,
        )
    except (TypeError, ValueError):
        max_age_seconds = int(DEFAULT_MYMEDIA_ALEXA_PAIRING_SESSION_MAX_AGE_SECONDS)
    pending_surface = surface_kind in {"waiting_for_code", "consent_required"}
    session_fresh = age_seconds is not None and age_seconds <= max_age_seconds
    session_stale = bool(pending_surface and age_seconds is not None and age_seconds > max_age_seconds)
    state_present = state_path.exists()
    session_present = session_path.exists()
    resume_ready = bool(resume_url_present and state_present and session_present and pending_surface and session_fresh)
    return {
        "session_present": session_present,
        "state_present": state_present,
        "resume_url_present": resume_url_present,
        "pending_surface": pending_surface,
        "resume_ready": resume_ready,
        "stale": session_stale,
        "surface_kind": surface_kind,
        "otp_channel": otp_channel,
        "phone_suffix": phone_suffix,
        "age_seconds": age_seconds,
        "max_age_seconds": max_age_seconds,
        "captured_at": str(session.get("captured_at") or "").strip(),
        "site": str(session.get("site") or "").strip(),
        "current_path": str(session.get("current_path") or "").strip(),
    }


def _mymedia_pairing_saved_session_report(
    *,
    web_base_url: str,
    observed_at: str,
    output_dir: str = "",
    now: datetime | None = None,
) -> dict[str, object]:
    session = _mymedia_pairing_load_session(output_dir)
    session_status = _mymedia_pairing_session_status(output_dir, now=now)
    surface_kind = str(session_status.get("surface_kind") or "").strip()
    waiting_for_code = surface_kind == "waiting_for_code"
    next_action = "approve_mymedia_amazon_consent" if surface_kind == "consent_required" else "enter_mymedia_amazon_pairing_code"
    next_action_href, next_action_label, next_action_method = _mymedia_action_surface(
        base_url=web_base_url,
        next_action=next_action,
    )
    return {
        "probe_ok": True,
        "ready": False,
        "status": "consent_required" if surface_kind == "consent_required" else "waiting_for_code",
        "reason": "amazon_oauth_consent_pending" if surface_kind == "consent_required" else "mfa_code_requested",
        "next_action": next_action,
        "next_action_href": next_action_href,
        "next_action_label": next_action_label,
        "next_action_method": next_action_method,
        "surface_kind": surface_kind,
        "site": str(session_status.get("site") or session.get("site") or "").strip(),
        "current_path": str(session_status.get("current_path") or session.get("current_path") or "").strip(),
        "otp_channel": str(session_status.get("otp_channel") or "").strip(),
        "phone_suffix": str(session_status.get("phone_suffix") or "").strip(),
        "code_entry_ready": waiting_for_code,
        "state_written": bool(session_status.get("state_present")),
        "session_written": bool(session_status.get("session_present")),
        "pairing_resume_ready": bool(session_status.get("resume_ready")),
        "pairing_session_pending": bool(session_status.get("pending_surface")),
        "pairing_session_stale": bool(session_status.get("stale")),
        "pairing_session_age_seconds": session_status.get("age_seconds"),
        "pairing_session_max_age_seconds": session_status.get("max_age_seconds"),
        "pairing_session_captured_at": str(session_status.get("captured_at") or "").strip(),
        "notification_policy": "action_required_only",
        "work_type": "handoff",
        "stop_condition": "human_challenge_required",
        "blockers": ["mfa_code_required"] if waiting_for_code else [],
        "observed_at": observed_at,
        "source": "mymedia_setup.saved_session",
        "privacy": {
            "raw_credentials_exposed": False,
            "raw_amazon_url_exposed": False,
        },
    }


def _mymedia_pairing_preserve_previous_actionable_handoff(
    report: Mapping[str, object],
    *,
    previous_bundle: Mapping[str, object] | None,
    web_base_url: str,
    observed_at: str,
    output_dir: str = "",
    now: datetime | None = None,
) -> dict[str, object]:
    current = dict(report)
    bundle = dict(previous_bundle or {})
    degraded_status = str(current.get("status") or "").strip()
    if degraded_status not in {
        "blocked_pairing_route_unavailable",
        "blocked_pairing_code_request_cooldown",
        "blocked_pairing_surface_unknown",
    }:
        return current
    if not bool(bundle.get("resume_ready")):
        return current
    if not _mymedia_pairing_restore_resume_bundle(bundle, output_dir):
        return current
    restored_status = _mymedia_pairing_session_status(output_dir, now=now)
    if not bool(restored_status.get("resume_ready")):
        return current
    preserved = _mymedia_pairing_saved_session_report(
        web_base_url=web_base_url,
        observed_at=observed_at,
        output_dir=output_dir,
        now=now,
    )
    preserved.update(
        {
            "source": "mymedia_setup.saved_session_preserved",
            "previous_actionable_handoff_preserved": True,
            "attempt_status": degraded_status,
            "attempt_reason": str(current.get("reason") or "").strip(),
            "attempt_surface_kind": str(current.get("surface_kind") or "").strip(),
            "attempt_failed_route": str(current.get("failed_route") or current.get("selected_route") or "").strip(),
        }
    )
    return preserved


def _mymedia_pairing_approve_consent_if_present(page: Any) -> bool:
    surface, body_text = _mymedia_pairing_wait_for_surface(page, timeout_seconds=5.0)
    if str(surface.get("kind") or "") != "consent_required":
        return False
    text = " ".join(str(body_text or "").split()).strip().lower()
    if "allow" not in text and "authorize" not in text and "authorise" not in text:
        return False
    clicked = _mymedia_pairing_click_submit(page, ("allow", "authorize", "authorise", "continue", "approve"))
    return bool(clicked)


def trigger_mymedia_amazon_pairing(
    *,
    web_base_url: str = "",
    setup_url: str = "",
    otp_channel: str = "",
    phone_suffix: str = "",
    send_telegram_to_principal: str = "",
    dry_run: bool = False,
    timeout_seconds: float = 45.0,
    output_format: str = "json",
    output_dir: str = "",
    telegram_operator_streams: tuple[str, ...] | str | None = None,
) -> dict[str, object]:
    observed_at = _utc_now()
    observed_now = _parse_utc_datetime(observed_at)
    effective_web_base_url = str(
        web_base_url or _env("EA_MYMEDIA_ALEXA_WEB_BASE_URL", DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL)
    ).strip() or DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL
    effective_setup_url = _mymedia_setup_url(web_base_url=effective_web_base_url, setup_url=setup_url)
    effective_otp_channel = (
        str(
            otp_channel
            or _mymedia_runtime_default_value(
                env_names=("EA_MYMEDIA_ALEXA_AMAZON_OTP_CHANNEL", "AMAZON_OTP_CHANNEL"),
                payload_keys=("amazon_otp_channel",),
                default=DEFAULT_MYMEDIA_ALEXA_AMAZON_OTP_CHANNEL,
            )
            or DEFAULT_MYMEDIA_ALEXA_AMAZON_OTP_CHANNEL
        )
        .strip()
        .lower()
        or DEFAULT_MYMEDIA_ALEXA_AMAZON_OTP_CHANNEL
    )
    effective_phone_suffix = _digits(
        phone_suffix
        or _mymedia_runtime_default_value(
            env_names=("EA_MYMEDIA_ALEXA_AMAZON_PHONE_SUFFIX", "AMAZON_OTP_SUFFIX"),
            payload_keys=("amazon_phone_suffix",),
            default=DEFAULT_MYMEDIA_ALEXA_AMAZON_PHONE_SUFFIX,
        )
        or DEFAULT_MYMEDIA_ALEXA_AMAZON_PHONE_SUFFIX
    )
    previous_bundle = _mymedia_pairing_capture_existing_resume_bundle(output_dir, now=observed_now)
    login_email = _env("AMAZON_ACCOUNT_EMAIL")
    login_password = BrowserActToolAdapter._amazon_login_password()

    pre_probe = probe_mymedia_alexa(
        container_name=_env("EA_MYMEDIA_ALEXA_CONTAINER", DEFAULT_MYMEDIA_ALEXA_CONTAINER),
        web_base_url=effective_web_base_url,
        timeout_seconds=min(max(float(timeout_seconds or 45.0), 1.0), 15.0),
        output_format="json",
    )
    if bool(pre_probe.get("pairing_ready")):
        report = {
            "probe_ok": True,
            "ready": True,
            "status": "already_paired",
            "reason": "",
            "next_action": str(pre_probe.get("next_action") or "").strip(),
            "surface_kind": "local_console",
            "site": _url_scope(effective_web_base_url),
            "otp_channel": effective_otp_channel,
            "phone_suffix": effective_phone_suffix,
            "code_entry_ready": False,
            "state_written": False,
            "observed_at": observed_at,
            "source": "mymedia_setup.playwright",
            "mymedia_probe_status": str(pre_probe.get("status") or "").strip(),
            "privacy": {
                "raw_credentials_exposed": False,
                "raw_amazon_url_exposed": False,
            },
        }
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_mymedia_pairing(report)
        return report
    if dry_run:
        report = {
            "probe_ok": True,
            "ready": False,
            "status": "dry_run",
            "reason": "",
            "next_action": "request_mymedia_pairing_code",
            "surface_kind": "dry_run",
            "site": urllib.parse.urlparse(effective_setup_url).hostname or "localhost",
            "otp_channel": effective_otp_channel,
            "phone_suffix": effective_phone_suffix,
            "code_entry_ready": False,
            "state_written": False,
            "observed_at": observed_at,
            "source": "mymedia_setup.playwright",
            "privacy": {
                "raw_credentials_exposed": False,
                "raw_amazon_url_exposed": False,
            },
        }
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_mymedia_pairing(report)
        return report
    if not login_email or not login_password:
        report = {
            "probe_ok": False,
            "ready": False,
            "status": "blocked_credentials_missing",
            "reason": "amazon_credentials_missing",
            "next_action": "configure_amazon_credentials",
            "surface_kind": "",
            "site": urllib.parse.urlparse(effective_setup_url).hostname or "localhost",
            "otp_channel": effective_otp_channel,
            "phone_suffix": effective_phone_suffix,
            "code_entry_ready": False,
            "state_written": False,
            "observed_at": observed_at,
            "source": "mymedia_setup.playwright",
            "privacy": {
                "raw_credentials_exposed": False,
                "raw_amazon_url_exposed": False,
            },
        }
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_mymedia_pairing(report)
        return report
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        report = {
            "probe_ok": False,
            "ready": False,
            "status": "blocked_browser_runtime_unavailable",
            "reason": "browser_runtime_unavailable",
            "next_action": "install_playwright_runtime",
            "surface_kind": "",
            "site": urllib.parse.urlparse(effective_setup_url).hostname or "localhost",
            "otp_channel": effective_otp_channel,
            "phone_suffix": effective_phone_suffix,
            "code_entry_ready": False,
            "state_written": False,
            "observed_at": observed_at,
            "source": "mymedia_setup.playwright",
            "privacy": {
                "raw_credentials_exposed": False,
                "raw_amazon_url_exposed": False,
            },
        }
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_mymedia_pairing(report)
        return report

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(viewport={"width": 1440, "height": 1200}, locale="en-US")
        page = context.new_page()
        page.set_default_timeout(int(max(float(timeout_seconds or 45.0), 1.0) * 1000))
        try:
            page.goto(effective_setup_url, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            surface, body_text = _mymedia_pairing_wait_for_surface(page, timeout_seconds=min(timeout_seconds, 15.0))
            if str(surface.get("kind") or "") == "setup_intro":
                checkbox = page.locator("input[type='checkbox']").first
                if checkbox.count():
                    checkbox.check(force=True)
                next_clicked = _mymedia_pairing_click_submit(page, ("next",))
                if not next_clicked:
                    raise RuntimeError("mymedia_setup_next_unavailable")
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(2000)
                surface, body_text = _mymedia_pairing_wait_for_surface(page, timeout_seconds=min(timeout_seconds, 20.0))
            if str(surface.get("kind") or "") == "amazon_signin":
                email_selector = _mymedia_pairing_fill_first_visible(
                    page,
                    ("input[name='email']", "input#ap_email", "input[type='email']", "input[type='text']"),
                    login_email,
                )
                if not email_selector:
                    raise RuntimeError("mymedia_amazon_email_input_missing")
                clicked = _mymedia_pairing_click_submit(page, ("continue",))
                if not clicked:
                    raise RuntimeError("mymedia_amazon_continue_unavailable")
                try:
                    page.wait_for_load_state("domcontentloaded")
                except Exception:
                    pass
                page.wait_for_timeout(1000)
                password_selectors = ("input[name='password']", "input#ap_password", "input[type='password']")
                first_visible_password_selector = _mymedia_pairing_wait_for_visible_selector(
                    page,
                    password_selectors,
                    timeout_seconds=min(timeout_seconds, 10.0),
                )
                ordered_password_selectors = (
                    (first_visible_password_selector,) + tuple(
                        selector for selector in password_selectors if selector != first_visible_password_selector
                    )
                    if first_visible_password_selector
                    else password_selectors
                )
                password_selector = _mymedia_pairing_fill_first_visible(
                    page,
                    ordered_password_selectors,
                    login_password,
                )
                if not password_selector:
                    raise RuntimeError("mymedia_amazon_password_input_missing")
                clicked = _mymedia_pairing_click_submit(page, ("sign in", "anmelden"))
                if not clicked:
                    raise RuntimeError("mymedia_amazon_signin_unavailable")
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(2000)
                surface, body_text = _mymedia_pairing_wait_for_surface(page, timeout_seconds=min(timeout_seconds, 20.0))
            selected_route = ""
            if str(surface.get("kind") or "") == "mfa_route_selection":
                options = page.locator("input[type='radio']")
                option_count = options.count()
                for index in range(option_count):
                    option = options.nth(index)
                    option_id = str(option.get_attribute("id") or "").strip()
                    option_text = ""
                    if option_id:
                        try:
                            option_text = str(page.locator(f"label[for='{option_id}']").inner_text() or "").strip()
                        except Exception:
                            option_text = ""
                    if not option_text:
                        try:
                            option_text = str(
                                option.locator("xpath=ancestor::*[self::div or self::li or self::fieldset][1]").inner_text() or ""
                            ).strip()
                        except Exception:
                            option_text = ""
                    if not _mymedia_pairing_route_matches(
                        option_text,
                        otp_channel=effective_otp_channel,
                        phone_suffix=effective_phone_suffix,
                    ):
                        continue
                    option.check(force=True)
                    selected_route = _mymedia_pairing_route_label(
                        otp_channel=effective_otp_channel,
                        phone_suffix=effective_phone_suffix,
                    )
                    break
                if not selected_route:
                    raise RuntimeError("mymedia_pairing_route_not_found")
                clicked = _mymedia_pairing_click_submit(page, ("otp senden", "send otp", "send code", "continue"))
                if not clicked:
                    raise RuntimeError("mymedia_pairing_otp_send_unavailable")
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(2000)
                surface, body_text = _mymedia_pairing_wait_for_surface(page, timeout_seconds=min(timeout_seconds, 20.0))
            capture = _mymedia_pairing_capture_runtime_state(
                context=context,
                page=page,
                otp_channel=effective_otp_channel,
                phone_suffix=effective_phone_suffix,
                surface=surface,
                body_text=body_text,
                output_dir=output_dir,
            )
            report = {
                "probe_ok": False,
                "ready": False,
                "status": "blocked_pairing_surface_unknown",
                "reason": "mymedia_pairing_surface_unknown",
                "next_action": "inspect_mymedia_pairing_surface",
                "surface_kind": str(surface.get("kind") or "").strip(),
                "site": str(surface.get("current_host") or "").strip(),
                "current_path": str(surface.get("current_path") or "").strip(),
                "current_url_sha256": str(surface.get("current_url_sha256") or "").strip(),
                "otp_channel": effective_otp_channel,
                "phone_suffix": effective_phone_suffix,
                "selected_route": selected_route,
                "code_entry_ready": False,
                "state_written": bool(capture.get("state_written")),
                "session_written": bool(capture.get("session_written")),
                "screenshot_written": bool(capture.get("screenshot_written")),
                "state_path": str(capture.get("state_path") or ""),
                "session_path": str(capture.get("session_path") or ""),
                "screenshot_path": str(capture.get("screenshot_path") or ""),
                "notification_policy": "action_required_only",
                "work_type": "handoff",
                "stop_condition": "human_challenge_required",
                "blockers": ["mfa_code_required"],
                "privacy": {
                    "raw_credentials_exposed": False,
                    "raw_amazon_url_exposed": False,
                },
                "observed_at": observed_at,
                "source": "mymedia_setup.playwright",
            }
            surface_kind = str(surface.get("kind") or "").strip()
            if surface_kind == "waiting_for_code":
                report.update(
                    {
                        "probe_ok": True,
                        "status": "waiting_for_code",
                        "reason": "mfa_code_requested",
                        "next_action": "enter_mymedia_amazon_pairing_code",
                        "code_entry_ready": True,
                        "stop_condition": "mfa_required",
                    }
                )
            elif surface_kind == "consent_required":
                report.update(
                    {
                        "probe_ok": True,
                        "status": "consent_required",
                        "reason": "amazon_oauth_consent_pending",
                        "next_action": "approve_mymedia_amazon_consent",
                        "code_entry_ready": False,
                        "blockers": [],
                    }
                )
            elif surface_kind == "local_console":
                post_probe = probe_mymedia_alexa(
                    container_name=_env("EA_MYMEDIA_ALEXA_CONTAINER", DEFAULT_MYMEDIA_ALEXA_CONTAINER),
                    web_base_url=effective_web_base_url,
                    timeout_seconds=min(max(float(timeout_seconds or 45.0), 1.0), 15.0),
                    output_format="json",
                )
                report.update(
                    {
                        "probe_ok": bool(post_probe.get("pairing_ready")),
                        "ready": bool(post_probe.get("pairing_ready")),
                        "status": "paired" if bool(post_probe.get("pairing_ready")) else "local_console_without_pairing",
                        "reason": "" if bool(post_probe.get("pairing_ready")) else "pairing_not_confirmed_after_login",
                        "next_action": str(post_probe.get("next_action") or "").strip(),
                        "code_entry_ready": False,
                        "blockers": [],
                        "mymedia_probe_status": str(post_probe.get("status") or "").strip(),
                    }
                )
            elif surface_kind == "mfa_route_selection" and selected_route:
                route_issue = _mymedia_pairing_route_request_issue(
                    body_text,
                    otp_channel=effective_otp_channel,
                    phone_suffix=effective_phone_suffix,
                )
                if route_issue:
                    report.update(route_issue)
            report = _mymedia_pairing_preserve_previous_actionable_handoff(
                report,
                previous_bundle=previous_bundle,
                web_base_url=effective_web_base_url,
                observed_at=observed_at,
                output_dir=output_dir,
                now=observed_now,
            )
            report = _mymedia_pairing_with_telegram_delivery(
                report,
                principal_id=str(send_telegram_to_principal or "").strip(),
                timeout_seconds=timeout_seconds,
                telegram_operator_streams=telegram_operator_streams,
            )
            if output_format == "operator":
                report["operator_text"] = _operator_text_for_mymedia_pairing(report)
            return report
        finally:
            browser.close()


def send_mymedia_amazon_pairing_telegram(
    *,
    web_base_url: str = "",
    otp_channel: str = "",
    phone_suffix: str = "",
    telegram_principal_id: str = "",
    dry_run: bool = False,
    timeout_seconds: float = 45.0,
    output_format: str = "json",
    output_dir: str = "",
    telegram_operator_streams: tuple[str, ...] | str | None = None,
) -> dict[str, object]:
    observed_at = _utc_now()
    observed_now = _parse_utc_datetime(observed_at)
    effective_web_base_url = str(
        web_base_url or _env("EA_MYMEDIA_ALEXA_WEB_BASE_URL", DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL)
    ).strip() or DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL
    requested_otp_channel = str(otp_channel or "").strip().lower()
    requested_phone_suffix = _digits(phone_suffix)
    effective_otp_channel = (
        str(
            requested_otp_channel
            or _mymedia_runtime_default_value(
                env_names=("EA_MYMEDIA_ALEXA_AMAZON_OTP_CHANNEL", "AMAZON_OTP_CHANNEL"),
                payload_keys=("amazon_otp_channel",),
                default=DEFAULT_MYMEDIA_ALEXA_AMAZON_OTP_CHANNEL,
            )
            or DEFAULT_MYMEDIA_ALEXA_AMAZON_OTP_CHANNEL
        )
        .strip()
        .lower()
        or DEFAULT_MYMEDIA_ALEXA_AMAZON_OTP_CHANNEL
    )
    effective_phone_suffix = _digits(
        requested_phone_suffix
        or _mymedia_runtime_default_value(
            env_names=("EA_MYMEDIA_ALEXA_AMAZON_PHONE_SUFFIX", "AMAZON_OTP_SUFFIX"),
            payload_keys=("amazon_phone_suffix",),
            default=DEFAULT_MYMEDIA_ALEXA_AMAZON_PHONE_SUFFIX,
        )
        or DEFAULT_MYMEDIA_ALEXA_AMAZON_PHONE_SUFFIX
    )
    effective_principal_id = str(telegram_principal_id or _default_proactive_principal_id() or "").strip()
    pre_probe = probe_mymedia_alexa(
        container_name=_env("EA_MYMEDIA_ALEXA_CONTAINER", DEFAULT_MYMEDIA_ALEXA_CONTAINER),
        web_base_url=effective_web_base_url,
        timeout_seconds=min(max(float(timeout_seconds or 45.0), 1.0), 15.0),
        output_format="json",
    )
    if bool(pre_probe.get("pairing_ready")):
        report = {
            "probe_ok": True,
            "ready": True,
            "status": "already_paired",
            "reason": "no_operator_action_required",
            "next_action": str(pre_probe.get("next_action") or "").strip(),
            "surface_kind": "local_console",
            "site": _url_scope(effective_web_base_url),
            "otp_channel": effective_otp_channel,
            "phone_suffix": effective_phone_suffix,
            "code_entry_ready": False,
            "state_written": False,
            "observed_at": observed_at,
            "source": "mymedia_pairing.telegram",
            "telegram_delivery": {
                "sent": False,
                "reason": "no_operator_action_required",
                "principal_id": effective_principal_id,
                "delivery_transport": "telegram_bot",
                "observed_at": observed_at,
                "source": "scripts.ea_live_ops.send_mymedia_amazon_pairing_telegram",
            },
            "privacy": {
                "raw_credentials_exposed": False,
                "raw_amazon_url_exposed": False,
            },
        }
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_mymedia_pairing(report)
        return report
    if str(pre_probe.get("status") or "").strip() != "blocked_pairing_required":
        report = {
            "probe_ok": bool(pre_probe.get("probe_ok")),
            "ready": False,
            "status": str(pre_probe.get("status") or "blocked_pairing_unavailable").strip() or "blocked_pairing_unavailable",
            "reason": str(pre_probe.get("reason") or "").strip() or "mymedia_pairing_not_actionable",
            "next_action": str(pre_probe.get("next_action") or "").strip(),
            "surface_kind": str(pre_probe.get("pairing_session_surface_kind") or "").strip(),
            "site": str(pre_probe.get("web_base_url_scope") or _url_scope(effective_web_base_url)).strip(),
            "otp_channel": effective_otp_channel,
            "phone_suffix": effective_phone_suffix,
            "code_entry_ready": False,
            "state_written": False,
            "observed_at": observed_at,
            "source": "mymedia_pairing.telegram",
            "telegram_delivery": {
                "sent": False,
                "reason": "no_actionable_pairing_state",
                "principal_id": effective_principal_id,
                "delivery_transport": "telegram_bot",
                "observed_at": observed_at,
                "source": "scripts.ea_live_ops.send_mymedia_amazon_pairing_telegram",
            },
            "privacy": {
                "raw_credentials_exposed": False,
                "raw_amazon_url_exposed": False,
            },
        }
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_mymedia_pairing(report)
        return report
    pairing_session = _mymedia_pairing_session_status(output_dir, now=observed_now)
    session_channel = str(pairing_session.get("otp_channel") or "").strip().lower()
    session_suffix = _digits(pairing_session.get("phone_suffix") or "")
    route_matches = (
        (not requested_otp_channel or not session_channel or session_channel == requested_otp_channel)
        and (not requested_phone_suffix or not session_suffix or session_suffix == requested_phone_suffix)
    )
    if bool(pairing_session.get("resume_ready")) and route_matches:
        report = _mymedia_pairing_saved_session_report(
            web_base_url=effective_web_base_url,
            observed_at=observed_at,
            output_dir=output_dir,
            now=observed_now,
        )
        report = _mymedia_pairing_with_telegram_delivery(
            report,
            principal_id=effective_principal_id,
            timeout_seconds=timeout_seconds,
            dry_run=bool(dry_run),
            telegram_operator_streams=telegram_operator_streams,
        )
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_mymedia_pairing(report)
        return report
    report = trigger_mymedia_amazon_pairing(
        web_base_url=effective_web_base_url,
        otp_channel=effective_otp_channel,
        phone_suffix=effective_phone_suffix,
        send_telegram_to_principal=("" if bool(dry_run) else effective_principal_id),
        dry_run=bool(dry_run),
        timeout_seconds=timeout_seconds,
        output_format="json",
        output_dir=output_dir,
        telegram_operator_streams=telegram_operator_streams,
    )
    if bool(dry_run):
        report = _mymedia_pairing_with_telegram_delivery(
            report,
            principal_id=effective_principal_id,
            timeout_seconds=timeout_seconds,
            dry_run=True,
            telegram_operator_streams=telegram_operator_streams,
        )
    elif "telegram_delivery" not in report:
        report["telegram_delivery"] = {}
    if output_format == "operator":
        report["operator_text"] = _operator_text_for_mymedia_pairing(report)
    return report


def submit_mymedia_amazon_pairing_code(
    *,
    otp_code: str,
    web_base_url: str = "",
    timeout_seconds: float = 45.0,
    output_format: str = "json",
    output_dir: str = "",
) -> dict[str, object]:
    observed_at = _utc_now()
    effective_web_base_url = str(
        web_base_url or _env("EA_MYMEDIA_ALEXA_WEB_BASE_URL", DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL)
    ).strip() or DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL
    normalized_code = str(otp_code or "").strip()
    session = _mymedia_pairing_load_session(output_dir)
    state_path = _mymedia_pairing_state_path(output_dir)
    resume_url = str(session.get("resume_url") or "").strip()
    effective_otp_channel = str(session.get("otp_channel") or DEFAULT_MYMEDIA_ALEXA_AMAZON_OTP_CHANNEL).strip().lower()
    effective_phone_suffix = _digits(session.get("phone_suffix") or "")
    if not normalized_code:
        report = {
            "probe_ok": False,
            "ready": False,
            "status": "blocked_code_missing",
            "reason": "otp_code_missing",
            "next_action": "enter_mymedia_amazon_pairing_code",
            "surface_kind": "",
            "site": "",
            "otp_channel": effective_otp_channel,
            "phone_suffix": effective_phone_suffix,
            "code_entry_ready": False,
            "state_written": bool(state_path.exists()),
            "observed_at": observed_at,
            "source": "mymedia_setup.playwright",
            "privacy": {
                "raw_credentials_exposed": False,
                "raw_amazon_url_exposed": False,
            },
        }
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_mymedia_pairing(report)
        return report
    if not resume_url or not state_path.exists():
        report = {
            "probe_ok": False,
            "ready": False,
            "status": "blocked_session_missing",
            "reason": "mymedia_pairing_session_missing",
            "next_action": "trigger_mymedia_amazon_pairing",
            "surface_kind": "",
            "site": "",
            "otp_channel": effective_otp_channel,
            "phone_suffix": effective_phone_suffix,
            "code_entry_ready": False,
            "state_written": False,
            "observed_at": observed_at,
            "source": "mymedia_setup.playwright",
            "privacy": {
                "raw_credentials_exposed": False,
                "raw_amazon_url_exposed": False,
            },
        }
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_mymedia_pairing(report)
        return report
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        report = {
            "probe_ok": False,
            "ready": False,
            "status": "blocked_browser_runtime_unavailable",
            "reason": "browser_runtime_unavailable",
            "next_action": "install_playwright_runtime",
            "surface_kind": "",
            "site": "",
            "otp_channel": effective_otp_channel,
            "phone_suffix": effective_phone_suffix,
            "code_entry_ready": False,
            "state_written": False,
            "observed_at": observed_at,
            "source": "mymedia_setup.playwright",
            "privacy": {
                "raw_credentials_exposed": False,
                "raw_amazon_url_exposed": False,
            },
        }
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_mymedia_pairing(report)
        return report

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1200},
            locale="en-US",
            storage_state=str(state_path),
        )
        page = context.new_page()
        page.set_default_timeout(int(max(float(timeout_seconds or 45.0), 1.0) * 1000))
        try:
            page.goto(resume_url, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            surface, body_text = _mymedia_pairing_wait_for_surface(page, timeout_seconds=min(timeout_seconds, 15.0))
            if str(surface.get("kind") or "") == "consent_required":
                _mymedia_pairing_approve_consent_if_present(page)
                page.wait_for_timeout(2000)
                surface, body_text = _mymedia_pairing_wait_for_surface(page, timeout_seconds=min(timeout_seconds, 10.0))
            if str(surface.get("kind") or "") != "waiting_for_code":
                report = {
                    "probe_ok": False,
                    "ready": False,
                    "status": "blocked_code_surface_missing",
                    "reason": "mymedia_pairing_code_surface_missing",
                    "next_action": "trigger_mymedia_amazon_pairing",
                    "surface_kind": str(surface.get("kind") or "").strip(),
                    "site": str(surface.get("current_host") or "").strip(),
                    "otp_channel": effective_otp_channel,
                    "phone_suffix": effective_phone_suffix,
                    "code_entry_ready": False,
                    "state_written": True,
                    "observed_at": observed_at,
                    "source": "mymedia_setup.playwright",
                    "privacy": {
                        "raw_credentials_exposed": False,
                        "raw_amazon_url_exposed": False,
                    },
                }
                if output_format == "operator":
                    report["operator_text"] = _operator_text_for_mymedia_pairing(report)
                return report
            otp_selector = _mymedia_pairing_fill_first_visible(
                page,
                (
                    "input[name='otpCode']",
                    "input[name='code']",
                    "input[inputmode='numeric']",
                    "input[type='tel']",
                    "input[type='number']",
                    "input[type='text']",
                ),
                normalized_code,
            )
            if not otp_selector:
                raise RuntimeError("mymedia_pairing_code_input_missing")
            clicked = _mymedia_pairing_click_submit(page, ("sign in", "anmelden", "submit", "continue"))
            if not clicked:
                raise RuntimeError("mymedia_pairing_code_submit_unavailable")
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2000)
            end_deadline = time.monotonic() + max(float(timeout_seconds or 45.0), 1.0)
            while time.monotonic() <= end_deadline:
                surface, body_text = _mymedia_pairing_wait_for_surface(page, timeout_seconds=5.0)
                if str(surface.get("kind") or "") == "consent_required":
                    if not _mymedia_pairing_approve_consent_if_present(page):
                        break
                    page.wait_for_load_state("domcontentloaded")
                    page.wait_for_timeout(2000)
                    continue
                if str(surface.get("kind") or "") in {"local_console", "waiting_for_code"}:
                    break
                page.wait_for_timeout(1000)
            capture = _mymedia_pairing_capture_runtime_state(
                context=context,
                page=page,
                otp_channel=effective_otp_channel,
                phone_suffix=effective_phone_suffix,
                surface=surface,
                body_text=body_text,
                output_dir=output_dir,
            )
            post_probe = probe_mymedia_alexa(
                container_name=_env("EA_MYMEDIA_ALEXA_CONTAINER", DEFAULT_MYMEDIA_ALEXA_CONTAINER),
                web_base_url=effective_web_base_url,
                timeout_seconds=min(max(float(timeout_seconds or 45.0), 1.0), 15.0),
                output_format="json",
            )
            report = {
                "probe_ok": False,
                "ready": False,
                "status": "blocked_pairing_not_confirmed",
                "reason": "pairing_not_confirmed_after_code_submit",
                "next_action": "inspect_mymedia_pairing_surface",
                "surface_kind": str(surface.get("kind") or "").strip(),
                "site": str(surface.get("current_host") or "").strip(),
                "current_path": str(surface.get("current_path") or "").strip(),
                "current_url_sha256": str(surface.get("current_url_sha256") or "").strip(),
                "otp_channel": effective_otp_channel,
                "phone_suffix": effective_phone_suffix,
                "code_entry_ready": str(surface.get("kind") or "") == "waiting_for_code",
                "state_written": bool(capture.get("state_written")),
                "session_written": bool(capture.get("session_written")),
                "screenshot_written": bool(capture.get("screenshot_written")),
                "state_path": str(capture.get("state_path") or ""),
                "session_path": str(capture.get("session_path") or ""),
                "screenshot_path": str(capture.get("screenshot_path") or ""),
                "mymedia_probe_status": str(post_probe.get("status") or "").strip(),
                "notification_policy": "action_required_only",
                "work_type": "handoff",
                "stop_condition": "account_review_ready_for_user_decision",
                "blockers": [],
                "privacy": {
                    "raw_credentials_exposed": False,
                    "raw_amazon_url_exposed": False,
                },
                "observed_at": observed_at,
                "source": "mymedia_setup.playwright",
            }
            if bool(post_probe.get("pairing_ready")):
                report.update(
                    {
                        "probe_ok": True,
                        "ready": bool(post_probe.get("ready")),
                        "status": "paired" if bool(post_probe.get("ready")) else "paired_library_pending",
                        "reason": "" if bool(post_probe.get("ready")) else str(post_probe.get("reason") or "").strip(),
                        "next_action": str(post_probe.get("next_action") or "").strip(),
                        "blockers": [],
                    }
                )
            elif bool(surface.get("invalid_code")):
                report.update(
                    {
                        "status": "blocked_invalid_code",
                        "reason": "mymedia_pairing_code_rejected",
                        "next_action": "trigger_mymedia_amazon_pairing",
                        "blockers": ["mfa_code_required"],
                    }
                )
            elif str(surface.get("kind") or "") == "waiting_for_code":
                report.update(
                    {
                        "status": "blocked_code_still_required",
                        "reason": "mymedia_pairing_code_not_accepted",
                        "next_action": "trigger_mymedia_amazon_pairing",
                        "blockers": ["mfa_code_required"],
                    }
                )
            if output_format == "operator":
                report["operator_text"] = _operator_text_for_mymedia_pairing(report)
            return report
        finally:
            browser.close()


def _sonarr_config_path(config_path: str = "") -> Path:
    configured = str(config_path or _env("EA_SONARR_CONFIG_PATH", str(DEFAULT_SONARR_CONFIG_PATH))).strip()
    return Path(os.path.expanduser(os.path.expandvars(configured or str(DEFAULT_SONARR_CONFIG_PATH))))


def _sonarr_staging_root(staging_root: str = "") -> Path:
    configured = str(staging_root or _env("EA_SONARR_STAGING_ROOT", str(DEFAULT_SONARR_STAGING_ROOT))).strip()
    return Path(os.path.expanduser(os.path.expandvars(configured or str(DEFAULT_SONARR_STAGING_ROOT))))


def _read_xml_api_key(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return ""
    return str(root.findtext("ApiKey") or "").strip()


def _sonarr_headers(api_key: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "X-Api-Key": str(api_key or "").strip(),
    }


def _sonarr_request_json_value(
    *,
    base_url: str,
    api_key: str,
    path: str,
    method: str = "GET",
    body: dict[str, object] | None = None,
    timeout_seconds: float = 15.0,
) -> object:
    normalized_base_url = str(base_url or DEFAULT_SONARR_BASE_URL).rstrip("/")
    normalized_path = path if str(path or "").startswith("/") else f"/{path}"
    headers = _sonarr_headers(api_key)
    if body is not None:
        headers = {**headers, "Content-Type": "application/json"}
    return _request_json_value(
        method=method,
        url=f"{normalized_base_url}{normalized_path}",
        headers=headers,
        body=body,
        timeout=max(float(timeout_seconds or 15.0), 1.0),
    )


def _sonarr_list_queue(*, base_url: str, api_key: str, timeout_seconds: float) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    page = 1
    while True:
        payload = _sonarr_request_json_value(
            base_url=base_url,
            api_key=api_key,
            path=f"/api/v3/queue?page={page}&pageSize=500",
            timeout_seconds=timeout_seconds,
            body=None,
            method="GET",
        )
        if not isinstance(payload, dict):
            break
        records = payload.get("records")
        if not isinstance(records, list) or not records:
            break
        rows.extend(dict(item) for item in records if isinstance(item, dict))
        total_records = int(payload.get("totalRecords") or len(rows))
        if len(rows) >= total_records:
            break
        page += 1
    return rows


def _sonarr_compact_episode_list(values: list[int], *, limit: int = 10) -> str:
    ordered = [int(item) for item in values if int(item) > 0]
    if not ordered:
        return ""
    if len(ordered) <= max(int(limit or 1), 1):
        return ",".join(str(item) for item in ordered)
    visible = max(int(limit or 1) - 1, 1)
    return ",".join(str(item) for item in ordered[:visible]) + ",..."


def _sonarr_series_title_tokens(value: object) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if len(token) >= 3 and token not in {"season", "episode", "web", "1080p", "720p", "264", "265"}
    }


def _sonarr_series_title_score(title: str, candidate_name: str) -> int:
    title_tokens = _sonarr_series_title_tokens(title)
    candidate_tokens = _sonarr_series_title_tokens(candidate_name)
    return len(title_tokens & candidate_tokens)


def _sonarr_episode_number_from_text(text: object, *, season_number: int) -> int | None:
    pattern = re.compile(rf"\bS{int(season_number):02d}E(\d{{2}})\b", re.IGNORECASE)
    match = pattern.search(str(text or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _sonarr_candidate_episode_files(path: Path, *, season_number: int) -> list[Path]:
    supported_suffixes = {".mkv", ".mp4", ".avi", ".m4v"}
    if path.is_file():
        return [path] if path.suffix.lower() in supported_suffixes else []
    if not path.is_dir():
        return []
    files: list[Path] = []
    for candidate in sorted(path.rglob("*")):
        if not candidate.is_file() or candidate.suffix.lower() not in supported_suffixes:
            continue
        if _sonarr_episode_number_from_text(candidate.name, season_number=season_number) is None:
            continue
        files.append(candidate)
    return files


def _iso_to_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _age_seconds(value: object, *, now: datetime | None = None) -> int | None:
    observed = _iso_to_datetime(value)
    if observed is None:
        return None
    effective_now = now or datetime.now(UTC)
    age = (effective_now - observed).total_seconds()
    try:
        return max(int(age), 0)
    except (TypeError, ValueError):
        return None


def _sonarr_queue_is_metadata_only(row: Mapping[str, object]) -> bool:
    error_message = str(row.get("errorMessage") or "").strip().lower()
    if "downloading metadata" not in error_message:
        return False
    tracked_state = str(row.get("trackedDownloadState") or row.get("tracked_download_state") or "").strip().lower()
    return tracked_state in {"downloading", "queued", "metadata", ""}


def _sonarr_series_target_dir(series_path: str, *, season_folder: bool, season_number: int) -> Path:
    base = Path(str(series_path or "").strip())
    if not season_folder:
        return base
    return base / f"Season {int(season_number)}"


def _sonarr_target_has_episode(path: Path, *, season_number: int, episode_number: int) -> bool:
    if not path.exists():
        return False
    marker = f"S{int(season_number):02d}E{int(episode_number):02d}"
    for candidate in path.glob(f"*{marker}*"):
        if candidate.is_file():
            return True
    return False


def _sonarr_target_episode_files(path: Path, *, season_number: int, episode_number: int) -> list[Path]:
    if not path.exists():
        return []
    marker = f"S{int(season_number):02d}E{int(episode_number):02d}"
    return sorted(candidate for candidate in path.glob(f"*{marker}*") if candidate.is_file())


def _sonarr_quarantine_dir(*, series_path: str, series_id: int, season_number: int) -> Path:
    series_root = Path(str(series_path or "").strip())
    if series_root.exists():
        return series_root.parent / ".ea-sonarr-quarantine" / f"series-{int(series_id or 0) or 'lookup'}" / f"season-{int(season_number):02d}"
    return DEFAULT_SONARR_TV_RECEIPT_DIR / "quarantine" / f"series-{int(series_id or 0) or 'lookup'}-season-{int(season_number):02d}"


def _sonarr_unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    counter = 1
    while True:
        candidate = path.with_name(f"{stem}.{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _sonarr_probe_file_playability(path: Path, *, timeout_seconds: float) -> dict[str, object]:
    ffprobe = shutil.which(str(os.environ.get("EA_FFPROBE_BIN") or "ffprobe").strip() or "ffprobe")
    if not ffprobe:
        return {
            "path": path.as_posix(),
            "ok": False,
            "probed": False,
            "method": "ffprobe_unavailable",
            "reason": "ffprobe_unavailable",
            "detail": "",
        }
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "json",
                path.as_posix(),
            ],
            capture_output=True,
            text=True,
            timeout=max(float(timeout_seconds or DEFAULT_SONARR_FFPROBE_TIMEOUT_SECONDS), 1.0),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "path": path.as_posix(),
            "ok": False,
            "probed": True,
            "method": "ffprobe",
            "reason": "ffprobe_timeout",
            "detail": "timeout",
        }
    stdout = str(completed.stdout or "").strip()
    stderr = str(completed.stderr or "").strip()
    detail = stderr or stdout
    if completed.returncode != 0:
        return {
            "path": path.as_posix(),
            "ok": False,
            "probed": True,
            "method": "ffprobe",
            "reason": "ffprobe_invalid_media",
            "detail": _compact_text(detail, limit=200),
        }
    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return {
            "path": path.as_posix(),
            "ok": False,
            "probed": True,
            "method": "ffprobe",
            "reason": "ffprobe_invalid_json",
            "detail": _compact_text(stdout, limit=200),
        }
    streams = [dict(item) for item in list(payload.get("streams") or []) if isinstance(item, dict)]
    codec_name = str((streams[0] if streams else {}).get("codec_name") or "").strip().lower()
    if not codec_name:
        return {
            "path": path.as_posix(),
            "ok": False,
            "probed": True,
            "method": "ffprobe",
            "reason": "ffprobe_missing_video_stream",
            "detail": "",
        }
    return {
        "path": path.as_posix(),
        "ok": True,
        "probed": True,
        "method": "ffprobe",
        "reason": "",
        "detail": codec_name,
    }


def _sonarr_staging_candidates(
    *,
    series_title: str,
    season_number: int,
    target_episode_numbers: list[int],
    staging_root: Path,
) -> list[dict[str, object]]:
    if not staging_root.exists() or not staging_root.is_dir():
        return []
    target_lookup = {int(item) for item in target_episode_numbers if int(item) > 0}
    title_tokens = _sonarr_series_title_tokens(series_title)
    candidates: list[dict[str, object]] = []
    for entry in sorted(staging_root.iterdir()):
        if not entry.exists():
            continue
        title_score = _sonarr_series_title_score(series_title, entry.name)
        if title_score < min(2, max(len(title_tokens), 1)):
            continue
        episode_files = _sonarr_candidate_episode_files(entry, season_number=season_number)
        if not episode_files:
            continue
        episode_numbers = sorted(
            {
                int(number)
                for number in (
                    _sonarr_episode_number_from_text(item.name, season_number=season_number) for item in episode_files
                )
                if number is not None
            }
        )
        if not episode_numbers:
            continue
        matching_targets = sorted(number for number in episode_numbers if number in target_lookup)
        candidates.append(
            {
                "name": entry.name,
                "path": entry.as_posix(),
                "title_score": title_score,
                "episode_numbers": episode_numbers,
                "matching_target_episode_numbers": matching_targets,
                "cover_count": len(matching_targets),
                "file_count": len(episode_files),
            }
        )
    candidates.sort(
        key=lambda item: (
            -int(item.get("cover_count") or 0),
            -int(item.get("file_count") or 0),
            -int(item.get("title_score") or 0),
            str(item.get("name") or ""),
        )
    )
    return candidates


def _sonarr_candidate_metrics(
    candidate: Mapping[str, object],
    *,
    season_number: int,
    target_episode_numbers: list[int],
    timeout_seconds: float,
) -> dict[str, object]:
    updated = dict(candidate)
    target_lookup = {int(item) for item in target_episode_numbers if int(item) > 0}
    valid_matching_episode_numbers: list[int] = []
    invalid_matching_episode_numbers: list[int] = []
    candidate_path = Path(str(candidate.get("path") or ""))
    for file_path in _sonarr_candidate_episode_files(candidate_path, season_number=season_number):
        episode_number = _sonarr_episode_number_from_text(file_path.name, season_number=season_number)
        if episode_number is None or int(episode_number) not in target_lookup:
            continue
        probe_result = _sonarr_probe_file_playability(
            file_path,
            timeout_seconds=min(timeout_seconds, DEFAULT_SONARR_FFPROBE_TIMEOUT_SECONDS),
        )
        if bool(probe_result.get("probed")) and not bool(probe_result.get("ok")):
            invalid_matching_episode_numbers.append(int(episode_number))
            continue
        valid_matching_episode_numbers.append(int(episode_number))
    updated["valid_matching_episode_numbers"] = sorted({int(item) for item in valid_matching_episode_numbers if int(item) > 0})
    updated["invalid_matching_episode_numbers"] = sorted({int(item) for item in invalid_matching_episode_numbers if int(item) > 0})
    updated["valid_cover_count"] = len(list(updated.get("valid_matching_episode_numbers") or []))
    updated["invalid_cover_count"] = len(list(updated.get("invalid_matching_episode_numbers") or []))
    return updated


def _sonarr_wait_for_command(
    *,
    base_url: str,
    api_key: str,
    command_id: int,
    timeout_seconds: float,
) -> dict[str, object]:
    deadline = time.monotonic() + max(float(timeout_seconds or 15.0), 1.0)
    last_payload: dict[str, object] = {}
    while True:
        payload = _sonarr_request_json_value(
            base_url=base_url,
            api_key=api_key,
            path=f"/api/v3/command/{int(command_id)}",
            timeout_seconds=min(max(float(timeout_seconds or 15.0) / 3.0, 5.0), 15.0),
        )
        last_payload = dict(payload) if isinstance(payload, dict) else {}
        status = str(last_payload.get("status") or "").strip().lower()
        if status in {"completed", "failed", "aborted"} or time.monotonic() >= deadline:
            if status == "":
                last_payload["status"] = "timeout"
            return last_payload
        time.sleep(2.0)


def _sonarr_request_command(
    *,
    base_url: str,
    api_key: str,
    name: str,
    body: dict[str, object],
    timeout_seconds: float,
    retry_http_errors: int = 1,
) -> dict[str, object]:
    attempts = 0
    while True:
        attempts += 1
        try:
            payload = _sonarr_request_json_value(
                base_url=base_url,
                api_key=api_key,
                path="/api/v3/command",
                method="POST",
                body={"name": str(name or "").strip(), **dict(body or {})},
                timeout_seconds=min(timeout_seconds, 20.0),
            )
            command_payload = dict(payload) if isinstance(payload, dict) else {}
            command_id = int(command_payload.get("id") or 0)
            if command_id <= 0:
                return {
                    "ok": False,
                    "command_id": 0,
                    "status": "request_missing_command_id",
                    "attempts": attempts,
                }
            command_report = _sonarr_wait_for_command(
                base_url=base_url,
                api_key=api_key,
                command_id=command_id,
                timeout_seconds=min(timeout_seconds, 60.0),
            )
            status = str(command_report.get("status") or "").strip()
            return {
                "ok": status not in {"failed", "aborted", "timeout"},
                "command_id": command_id,
                "status": status,
                "attempts": attempts,
            }
        except urllib.error.HTTPError as exc:
            if attempts > max(int(retry_http_errors or 0), 0):
                return {
                    "ok": False,
                    "command_id": 0,
                    "status": f"request_failed:http_{int(exc.code)}",
                    "attempts": attempts,
                }
            time.sleep(min(float(attempts), 3.0))
        except Exception as exc:
            return {
                "ok": False,
                "command_id": 0,
                "status": f"request_failed:{type(exc).__name__}",
                "attempts": attempts,
            }


def _sonarr_delete_queue_rows(
    *,
    base_url: str,
    api_key: str,
    queue_ids: list[int],
    timeout_seconds: float,
    remove_from_client: bool = True,
    blocklist: bool = False,
    skip_redownload: bool = False,
) -> dict[str, object]:
    if not queue_ids:
        return {"ok": True, "removed_count": 0}
    payload = _sonarr_request_json_value(
        base_url=base_url,
        api_key=api_key,
        path=(
            "/api/v3/queue/bulk"
            f"?removeFromClient={str(bool(remove_from_client)).lower()}"
            f"&blocklist={str(bool(blocklist)).lower()}"
            f"&skipRedownload={str(bool(skip_redownload)).lower()}"
        ),
        method="DELETE",
        body={"ids": queue_ids},
        timeout_seconds=timeout_seconds,
    )
    return {
        "ok": True,
        "removed_count": len(queue_ids),
        "response": dict(payload) if isinstance(payload, dict) else {},
    }


def _sonarr_queue_row_episode_snapshot(row: Mapping[str, object]) -> dict[str, int]:
    episode = dict(row.get("episode") or {}) if isinstance(row.get("episode"), Mapping) else {}
    return {
        "series_id": int(row.get("seriesId") or 0),
        "episode_id": int(episode.get("id") or row.get("episodeId") or 0),
        "season_number": int(episode.get("seasonNumber") or row.get("seasonNumber") or 0),
        "episode_number": int(episode.get("episodeNumber") or row.get("episodeNumber") or 0),
    }


def _sonarr_list_releases_for_episode(
    *,
    base_url: str,
    api_key: str,
    episode_id: int,
    timeout_seconds: float,
) -> list[dict[str, object]]:
    payload = _sonarr_request_json_value(
        base_url=base_url,
        api_key=api_key,
        path=f"/api/v3/release?episodeId={int(episode_id)}",
        timeout_seconds=timeout_seconds,
        body=None,
        method="GET",
    )
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, dict)]


def _sonarr_release_matches_exact_episode(
    release: Mapping[str, object],
    *,
    season_number: int,
    episode_number: int,
) -> bool:
    mapped_season = int(release.get("mappedSeasonNumber") or release.get("seasonNumber") or 0)
    if mapped_season != int(season_number):
        return False
    mapped_numbers = [
        int(item)
        for item in list(release.get("mappedEpisodeNumbers") or release.get("episodeNumbers") or [])
        if int(item) > 0
    ]
    return mapped_numbers == [int(episode_number)]


def _sonarr_release_rejections_allow_manual_grab(rejections: object) -> bool:
    normalized = [str(item or "").strip().lower() for item in list(rejections or []) if str(item or "").strip()]
    if not normalized:
        return True
    allowed_markers = (
        "release in queue already",
        "release is already queued",
        "already in queue",
        "already grabbed",
    )
    return all(any(marker in item for marker in allowed_markers) for item in normalized)


def _sonarr_release_info_hash(release: Mapping[str, object]) -> str:
    return (
        str(
            release.get("infoHash")
            or release.get("torrentInfoHash")
            or release.get("releaseHash")
            or ""
        )
        .strip()
        .lower()
    )


def _sonarr_release_resolution(release: Mapping[str, object]) -> int:
    quality = dict(release.get("quality") or {}) if isinstance(release.get("quality"), Mapping) else {}
    quality_detail = dict(quality.get("quality") or {}) if isinstance(quality.get("quality"), Mapping) else {}
    return int(quality_detail.get("resolution") or 0)


def _sonarr_pick_replacement_release(
    releases: list[dict[str, object]],
    *,
    season_number: int,
    episode_number: int,
    current_download_id: str,
) -> dict[str, object]:
    current_hash = str(current_download_id or "").strip().lower()
    exact_matches = []
    for release in releases:
        if not _sonarr_release_matches_exact_episode(release, season_number=season_number, episode_number=episode_number):
            continue
        if not bool(release.get("downloadAllowed")):
            continue
        if not _sonarr_release_rejections_allow_manual_grab(release.get("rejections")):
            continue
        info_hash = _sonarr_release_info_hash(release)
        if info_hash and info_hash == current_hash:
            continue
        seeders = max(int(release.get("seeders") or 0), 0)
        if seeders <= 0:
            continue
        exact_matches.append(dict(release))
    if not exact_matches:
        return {}

    def _sorted_bucket(min_resolution: int) -> list[dict[str, object]]:
        bucket = [item for item in exact_matches if _sonarr_release_resolution(item) >= min_resolution]
        bucket.sort(
            key=lambda item: (
                int(item.get("seeders") or 0),
                0 if "av1" in str(item.get("title") or "").lower() else 1,
                int(item.get("qualityWeight") or 0),
                int(item.get("size") or 0),
                str(item.get("title") or ""),
            ),
            reverse=True,
        )
        return bucket

    for minimum_resolution in (1080, 720, 0):
        bucket = _sorted_bucket(minimum_resolution)
        if bucket:
            return dict(bucket[0])
    return {}


def _sonarr_grab_release(
    *,
    base_url: str,
    api_key: str,
    release: Mapping[str, object],
    timeout_seconds: float,
) -> dict[str, object]:
    try:
        payload = _sonarr_request_json_value(
            base_url=base_url,
            api_key=api_key,
            path="/api/v3/release",
            method="POST",
            body=dict(release),
            timeout_seconds=min(timeout_seconds, 20.0),
        )
        return {
            "ok": True,
            "response": dict(payload) if isinstance(payload, dict) else {},
        }
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "status": f"http_{int(exc.code)}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": type(exc).__name__,
        }


def _resolve_series_by_title(series_rows: list[dict[str, object]], series_title: str) -> dict[str, object]:
    normalized_lookup = " ".join(re.findall(r"[a-z0-9]+", str(series_title or "").lower()))
    if not normalized_lookup:
        return {}
    direct_matches = []
    for row in series_rows:
        title = str(row.get("title") or "").strip()
        normalized_title = " ".join(re.findall(r"[a-z0-9]+", title.lower()))
        if normalized_title == normalized_lookup:
            direct_matches.append(row)
    if direct_matches:
        return dict(sorted(direct_matches, key=lambda item: int(item.get("id") or 0))[0])
    scored = []
    for row in series_rows:
        score = _sonarr_series_title_score(series_title, str(row.get("title") or ""))
        if score <= 0:
            continue
        scored.append((score, str(row.get("title") or ""), row))
    if not scored:
        return {}
    scored.sort(key=lambda item: (-item[0], item[1]))
    return dict(scored[0][2])


def _probe_sonarr_tv_season_state(
    *,
    series_id: int | None,
    series_title: str,
    season_number: int,
    sonarr_base_url: str,
    sonarr_config_path: Path,
    staging_root: Path,
    timeout_seconds: float,
) -> dict[str, object]:
    observed_at = _utc_now()
    report: dict[str, object] = {
        "probe_ok": False,
        "ready": False,
        "status": "probe_failed",
        "reason": "sonarr_probe_uninitialized",
        "next_action": "",
        "next_action_href": "",
        "next_action_label": "",
        "next_action_method": "",
        "series_id": int(series_id or 0),
        "series_title": str(series_title or "").strip(),
        "season_number": int(season_number),
        "season_episode_count": 0,
        "season_episode_file_count": 0,
        "missing_episode_ids": [],
        "missing_episode_numbers": [],
        "have_episode_numbers": [],
        "media_info_missing_episode_numbers": [],
        "media_info_missing_count": 0,
        "unreadable_episode_numbers": [],
        "unreadable_episode_count": 0,
        "unreadable_episode_file_names": [],
        "episode_file_probe_method": "",
        "episode_file_probe_detail": "",
        "metadata_queue_items": [],
        "metadata_queue_episode_numbers": [],
        "metadata_queue_count": 0,
        "stale_metadata_queue_items": [],
        "stale_metadata_queue_count": 0,
        "staging_root": staging_root.as_posix(),
        "staging_root_exists": staging_root.exists(),
        "staging_candidates": [],
        "staging_candidate_count": 0,
        "selected_staging_candidate": {},
        "selected_staging_candidate_name": "",
        "selected_staging_candidate_cover_count": 0,
        "sonarr_base_url": str(sonarr_base_url or DEFAULT_SONARR_BASE_URL).rstrip("/"),
        "sonarr_config_path": sonarr_config_path.as_posix(),
        "source": "sonarr.api+filesystem",
        "observed_at": observed_at,
        "privacy": {
            "raw_api_key_exposed": False,
            "raw_download_client_credentials_exposed": False,
        },
    }
    if not sonarr_config_path.exists():
        report["reason"] = "sonarr_config_missing"
        return report
    api_key = _read_xml_api_key(sonarr_config_path)
    if not api_key:
        report["reason"] = "sonarr_api_key_missing"
        return report
    try:
        series_payload = _sonarr_request_json_value(
            base_url=sonarr_base_url,
            api_key=api_key,
            path="/api/v3/series",
            timeout_seconds=timeout_seconds,
        )
        episode_payload = []
        episode_file_payload = []
        queue_rows = []
        if isinstance(series_payload, list):
            series_rows = [dict(item) for item in series_payload if isinstance(item, dict)]
        else:
            series_rows = []
        selected_series = {}
        if series_id is not None and int(series_id or 0) > 0:
            for row in series_rows:
                if int(row.get("id") or 0) == int(series_id):
                    selected_series = row
                    break
        elif str(series_title or "").strip():
            selected_series = _resolve_series_by_title(series_rows, str(series_title or "").strip())
        if not selected_series:
            report.update(
                {
                    "probe_ok": True,
                    "status": "blocked_series_not_found",
                    "reason": "sonarr_series_not_found",
                    "next_action": "verify_sonarr_series_lookup",
                }
            )
            return report
        resolved_series_id = int(selected_series.get("id") or 0)
        report["series_id"] = resolved_series_id
        report["series_title"] = str(selected_series.get("title") or report["series_title"] or "").strip()
        report["series_path"] = str(selected_series.get("path") or "").strip()
        report["series_monitored"] = bool(selected_series.get("monitored"))
        report["series_type"] = str(selected_series.get("seriesType") or "").strip()
        report["season_folder"] = bool(selected_series.get("seasonFolder", True))

        episode_payload = _sonarr_request_json_value(
            base_url=sonarr_base_url,
            api_key=api_key,
            path=f"/api/v3/episode?seriesId={resolved_series_id}",
            timeout_seconds=timeout_seconds,
        )
        episode_file_payload = _sonarr_request_json_value(
            base_url=sonarr_base_url,
            api_key=api_key,
            path=f"/api/v3/episodefile?seriesId={resolved_series_id}",
            timeout_seconds=timeout_seconds,
        )
        queue_rows = _sonarr_list_queue(
            base_url=sonarr_base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        report["reason"] = f"sonarr_api_probe_failed:{type(exc).__name__}"
        return report

    episode_rows = [dict(item) for item in episode_payload if isinstance(item, dict)] if isinstance(episode_payload, list) else []
    episode_file_rows = [dict(item) for item in episode_file_payload if isinstance(item, dict)] if isinstance(episode_file_payload, list) else []
    season_rows = [row for row in episode_rows if int(row.get("seasonNumber") or 0) == int(season_number)]
    if not season_rows:
        report.update(
            {
                "probe_ok": True,
                "status": "blocked_season_not_found",
                "reason": "sonarr_season_not_found",
                "next_action": "verify_sonarr_season_lookup",
            }
        )
        return report

    season_rows.sort(key=lambda item: int(item.get("episodeNumber") or 0))
    season_stats = {}
    for item in list(selected_series.get("seasons") or []):
        row = dict(item) if isinstance(item, dict) else {}
        if int(row.get("seasonNumber") or 0) == int(season_number):
            season_stats = row
            break
    report["season_monitored"] = bool(season_stats.get("monitored", True))

    have_episode_numbers = [int(row.get("episodeNumber") or 0) for row in season_rows if bool(row.get("hasFile"))]
    missing_episode_numbers = [int(row.get("episodeNumber") or 0) for row in season_rows if not bool(row.get("hasFile"))]
    missing_episode_ids = [int(row.get("id") or 0) for row in season_rows if not bool(row.get("hasFile")) and int(row.get("id") or 0) > 0]
    episodes_by_id = {int(row.get("id") or 0): row for row in season_rows if int(row.get("id") or 0) > 0}
    episode_files_by_id = {int(row.get("id") or 0): row for row in episode_file_rows if int(row.get("id") or 0) > 0}

    metadata_queue_items: list[dict[str, object]] = []
    now = _iso_to_datetime(_utc_now()) or datetime.now(UTC)
    for row in queue_rows:
        if int(row.get("seriesId") or 0) != int(report.get("series_id") or 0):
            continue
        current_season = int(row.get("seasonNumber") or 0)
        episode_number = int(row.get("episodeNumber") or 0)
        episode_id = int(row.get("episodeId") or 0)
        if current_season <= 0 and episode_id in episodes_by_id:
            current_season = int(episodes_by_id[episode_id].get("seasonNumber") or 0)
        if episode_number <= 0 and episode_id in episodes_by_id:
            episode_number = int(episodes_by_id[episode_id].get("episodeNumber") or 0)
        if current_season != int(season_number) or episode_number <= 0:
            continue
        if not _sonarr_queue_is_metadata_only(row):
            continue
        added_at = str(row.get("added") or "").strip()
        age_seconds = _age_seconds(added_at, now=now)
        episode_has_file = bool(row.get("episodeHasFile")) or episode_number in have_episode_numbers
        item = {
            "id": int(row.get("id") or 0),
            "episode_id": episode_id,
            "episode_number": episode_number,
            "season_number": current_season,
            "title": str(row.get("title") or "").strip(),
            "status": str(row.get("status") or "").strip(),
            "tracked_download_state": str(row.get("trackedDownloadState") or "").strip(),
            "error_message": str(row.get("errorMessage") or "").strip(),
            "added": added_at,
            "age_seconds": age_seconds,
            "episode_has_file": episode_has_file,
            "is_stale": bool(episode_has_file) or (age_seconds is not None and age_seconds >= int(DEFAULT_SONARR_METADATA_STALL_AGE_SECONDS)),
        }
        metadata_queue_items.append(item)

    metadata_queue_items.sort(key=lambda item: int(item.get("episode_number") or 0))
    stale_metadata_queue_items = [dict(item) for item in metadata_queue_items if bool(item.get("is_stale"))]

    media_info_missing_episode_numbers: list[int] = []
    unreadable_episode_numbers: list[int] = []
    unreadable_episode_file_names: list[str] = []
    file_probe_method = ""
    file_probe_details: list[str] = []
    for row in season_rows:
        if not bool(row.get("hasFile")):
            continue
        episode_number = int(row.get("episodeNumber") or 0)
        episode_file_id = int(row.get("episodeFileId") or 0)
        episode_file_row = dict(episode_files_by_id.get(episode_file_id) or {})
        media_info = dict(episode_file_row.get("mediaInfo") or {}) if isinstance(episode_file_row.get("mediaInfo"), dict) else {}
        path_text = str(episode_file_row.get("path") or "").strip()
        if not media_info:
            media_info_missing_episode_numbers.append(episode_number)
        if not path_text:
            unreadable_episode_numbers.append(episode_number)
            continue
        probe_result = _sonarr_probe_file_playability(Path(path_text), timeout_seconds=min(timeout_seconds, DEFAULT_SONARR_FFPROBE_TIMEOUT_SECONDS))
        if not file_probe_method:
            file_probe_method = str(probe_result.get("method") or "").strip()
        if not bool(probe_result.get("probed")):
            continue
        if not bool(probe_result.get("ok")):
            unreadable_episode_numbers.append(episode_number)
            unreadable_episode_file_names.append(Path(path_text).name)
            reason = str(probe_result.get("reason") or "").strip()
            detail = str(probe_result.get("detail") or "").strip()
            file_probe_details.append(f"E{episode_number:02d}:{reason}{':' + detail if detail else ''}")

    unreadable_episode_numbers = sorted({int(item) for item in unreadable_episode_numbers if int(item) > 0})
    media_info_missing_episode_numbers = sorted({int(item) for item in media_info_missing_episode_numbers if int(item) > 0})
    repair_episode_numbers = sorted(set(missing_episode_numbers) | set(unreadable_episode_numbers))
    staging_candidates = _sonarr_staging_candidates(
        series_title=str(report.get("series_title") or ""),
        season_number=season_number,
        target_episode_numbers=repair_episode_numbers,
        staging_root=staging_root,
    )
    staging_candidates = [
        _sonarr_candidate_metrics(
            candidate,
            season_number=season_number,
            target_episode_numbers=repair_episode_numbers,
            timeout_seconds=timeout_seconds,
        )
        for candidate in staging_candidates
    ]
    staging_candidates.sort(
        key=lambda item: (
            -int(item.get("valid_cover_count") or 0),
            -int(item.get("cover_count") or 0),
            -int(item.get("file_count") or 0),
            -int(item.get("title_score") or 0),
            str(item.get("name") or ""),
        )
    )
    selected_staging_candidate = (
        dict(staging_candidates[0])
        if staging_candidates and int(staging_candidates[0].get("valid_cover_count") or 0) > 0
        else {}
    )

    report.update(
        {
            "probe_ok": True,
            "reason": "",
            "series_title": str(report.get("series_title") or ""),
            "season_episode_count": len(season_rows),
            "season_episode_file_count": len(have_episode_numbers),
            "have_episode_numbers": have_episode_numbers,
            "missing_episode_ids": missing_episode_ids,
            "missing_episode_numbers": missing_episode_numbers,
            "media_info_missing_episode_numbers": media_info_missing_episode_numbers,
            "media_info_missing_count": len(media_info_missing_episode_numbers),
            "unreadable_episode_numbers": unreadable_episode_numbers,
            "unreadable_episode_count": len(unreadable_episode_numbers),
            "unreadable_episode_file_names": unreadable_episode_file_names,
            "episode_file_probe_method": file_probe_method,
            "episode_file_probe_detail": _compact_text(", ".join(file_probe_details), limit=400),
            "metadata_queue_items": metadata_queue_items,
            "metadata_queue_episode_numbers": [int(item.get("episode_number") or 0) for item in metadata_queue_items],
            "metadata_queue_count": len(metadata_queue_items),
            "stale_metadata_queue_items": stale_metadata_queue_items,
            "stale_metadata_queue_count": len(stale_metadata_queue_items),
            "staging_candidates": staging_candidates,
            "staging_candidate_count": len(staging_candidates),
            "selected_staging_candidate": selected_staging_candidate,
            "selected_staging_candidate_name": str(selected_staging_candidate.get("name") or "").strip(),
            "selected_staging_candidate_cover_count": int(
                selected_staging_candidate.get("valid_cover_count")
                or selected_staging_candidate.get("cover_count")
                or 0
            ),
        }
    )
    ready = not missing_episode_numbers and not metadata_queue_items and not unreadable_episode_numbers and not media_info_missing_episode_numbers
    status = "ready"
    reason = ""
    next_action = ""
    if not ready:
        if unreadable_episode_numbers and selected_staging_candidate:
            status = "blocked_unreadable_files_have_staging_candidate"
            reason = "sonarr_unreadable_episodes_have_staging_candidate"
            next_action = "repair_sonarr_tv_season"
        elif unreadable_episode_numbers:
            status = "blocked_unreadable_episode_files"
            reason = "sonarr_unreadable_episode_files"
            next_action = "repair_sonarr_tv_season"
        elif missing_episode_numbers and selected_staging_candidate:
            status = "blocked_staging_import_available"
            reason = "sonarr_missing_episodes_have_staging_candidate"
            next_action = "repair_sonarr_tv_season"
        elif stale_metadata_queue_items:
            status = "blocked_stale_metadata_queue"
            reason = "sonarr_stale_metadata_queue"
            next_action = "repair_sonarr_tv_season"
        elif metadata_queue_items:
            status = "ready_with_recovery_action"
            reason = "sonarr_metadata_queue_downloading_metadata"
            next_action = "wait_for_download_client_or_reprobe_sonarr_tv_season"
        elif missing_episode_numbers:
            status = "blocked_missing_episodes"
            reason = "sonarr_missing_episodes"
            next_action = "search_sonarr_missing_episodes"
        elif media_info_missing_episode_numbers:
            status = "ready_with_recovery_action"
            reason = "sonarr_episode_file_media_info_missing"
            next_action = "repair_sonarr_tv_season"
    report.update(
        {
            "ready": ready and status == "ready",
            "status": status,
            "reason": reason,
            "next_action": next_action,
        }
    )
    return report


def _operator_text_for_sonarr_tv_season(report: Mapping[str, object]) -> str:
    series_title = _compact_text(report.get("series_title"), limit=80)
    parts = [
        f"sonarr_tv_season status={report.get('status') or 'unknown'}",
        f"ready={str(bool(report.get('ready'))).lower()}",
    ]
    if series_title:
        parts.append(f"series={series_title}")
    if int(report.get("season_number") or 0) > 0:
        parts.append(f"season={int(report.get('season_number') or 0)}")
    total = int(report.get("season_episode_count") or 0)
    have = int(report.get("season_episode_file_count") or 0)
    if total > 0:
        parts.append(f"have={have}/{total}")
    missing_episode_numbers = [int(item) for item in list(report.get("missing_episode_numbers") or []) if int(item) > 0]
    if missing_episode_numbers:
        parts.append(f"missing={len(missing_episode_numbers)}[{_sonarr_compact_episode_list(missing_episode_numbers)}]")
    unreadable_episode_numbers = [int(item) for item in list(report.get("unreadable_episode_numbers") or []) if int(item) > 0]
    if unreadable_episode_numbers:
        parts.append(f"unreadable={len(unreadable_episode_numbers)}[{_sonarr_compact_episode_list(unreadable_episode_numbers)}]")
    media_info_missing = [int(item) for item in list(report.get("media_info_missing_episode_numbers") or []) if int(item) > 0]
    if media_info_missing:
        parts.append(f"media_info_missing={len(media_info_missing)}[{_sonarr_compact_episode_list(media_info_missing)}]")
    metadata_episode_numbers = [int(item) for item in list(report.get("metadata_queue_episode_numbers") or []) if int(item) > 0]
    if metadata_episode_numbers:
        parts.append(f"metadata_queue={len(metadata_episode_numbers)}[{_sonarr_compact_episode_list(metadata_episode_numbers)}]")
    stale_count = int(report.get("stale_metadata_queue_count") or 0)
    if stale_count > 0:
        parts.append(f"stale_metadata_queue={stale_count}")
    file_probe_method = str(report.get("episode_file_probe_method") or "").strip()
    if file_probe_method:
        parts.append(f"file_probe={file_probe_method}")
    staging_candidate_name = _compact_text(report.get("selected_staging_candidate_name"), limit=60)
    if staging_candidate_name:
        parts.append(
            f"staging_candidate={staging_candidate_name} cover={int(report.get('selected_staging_candidate_cover_count') or 0)}"
        )
    reason = str(report.get("reason") or "").strip()
    if reason:
        parts.append(f"reason={reason}")
    next_action = str(report.get("next_action") or "").strip()
    if next_action:
        parts.append(f"next={next_action}")
    observed_at = str(report.get("observed_at") or "").strip()
    if observed_at:
        parts.append(f"observed_at={observed_at}")
    source = str(report.get("source") or "").strip()
    if source:
        parts.append(f"source={source}")
    return "; ".join(parts)


def _operator_text_for_sonarr_tv_season_repair(report: Mapping[str, object]) -> str:
    parts = [
        f"sonarr_tv_season_repair status={report.get('status') or 'unknown'}",
        f"ready={str(bool(report.get('ready'))).lower()}",
    ]
    if report.get("series_title"):
        parts.append(f"series={_compact_text(report.get('series_title'), limit=80)}")
    if int(report.get("season_number") or 0) > 0:
        parts.append(f"season={int(report.get('season_number') or 0)}")
    moved_count = int(report.get("moved_file_count") or 0)
    if moved_count > 0:
        parts.append(f"moved={moved_count}[{_sonarr_compact_episode_list(list(report.get('moved_episode_numbers') or []))}]")
    quarantined_count = int(report.get("quarantined_file_count") or 0)
    if quarantined_count > 0:
        parts.append(
            f"quarantined={quarantined_count}[{_sonarr_compact_episode_list(list(report.get('quarantined_episode_numbers') or []))}]"
        )
    if report.get("refresh_requested") is not None:
        parts.append(f"refresh_requested={str(bool(report.get('refresh_requested'))).lower()}")
    if report.get("refresh_status"):
        parts.append(f"refresh_status={report['refresh_status']}")
    removed_count = int(report.get("queue_rows_removed") or 0)
    if removed_count > 0:
        parts.append(
            f"queue_removed={removed_count}[{_sonarr_compact_episode_list(list(report.get('removed_queue_episode_numbers') or []))}]"
        )
    replacement_count = int(report.get("replacement_grab_count") or 0)
    if replacement_count > 0:
        parts.append(
            f"replacement_grabbed={replacement_count}[{_sonarr_compact_episode_list(list(report.get('replacement_episode_numbers') or []))}]"
        )
    if report.get("rescan_requested") is not None:
        parts.append(f"rescan_requested={str(bool(report.get('rescan_requested'))).lower()}")
    if report.get("rescan_status"):
        parts.append(f"rescan_status={report['rescan_status']}")
    if report.get("search_requested") is not None:
        parts.append(f"search_requested={str(bool(report.get('search_requested'))).lower()}")
    if report.get("search_status"):
        parts.append(f"search_status={report['search_status']}")
    missing_after = [int(item) for item in list(report.get("missing_episode_numbers_after") or []) if int(item) > 0]
    if missing_after:
        parts.append(f"missing_after={len(missing_after)}[{_sonarr_compact_episode_list(missing_after)}]")
    unreadable_after = [int(item) for item in list(report.get("unreadable_episode_numbers_after") or []) if int(item) > 0]
    if unreadable_after:
        parts.append(f"unreadable_after={len(unreadable_after)}[{_sonarr_compact_episode_list(unreadable_after)}]")
    metadata_after = [int(item) for item in list(report.get("metadata_queue_episode_numbers_after") or []) if int(item) > 0]
    if metadata_after:
        parts.append(f"metadata_after={len(metadata_after)}[{_sonarr_compact_episode_list(metadata_after)}]")
    reason = str(report.get("reason") or "").strip()
    if reason:
        parts.append(f"reason={reason}")
    next_action = str(report.get("next_action") or "").strip()
    if next_action:
        parts.append(f"next={next_action}")
    if report.get("receipt_path"):
        parts.append(f"receipt={report['receipt_path']}")
    if report.get("observed_at"):
        parts.append(f"observed_at={report['observed_at']}")
    if report.get("source"):
        parts.append(f"source={report['source']}")
    return "; ".join(str(item) for item in parts if str(item).strip())


def probe_sonarr_tv_season(
    *,
    series_id: int | None = None,
    series_title: str = "",
    season_number: int,
    sonarr_base_url: str = "",
    sonarr_config_path: str = "",
    staging_root: str = "",
    timeout_seconds: float = 20.0,
    output_format: str = "json",
) -> dict[str, object]:
    effective_base_url = str(sonarr_base_url or _env("EA_SONARR_BASE_URL", DEFAULT_SONARR_BASE_URL)).strip() or DEFAULT_SONARR_BASE_URL
    report = _probe_sonarr_tv_season_state(
        series_id=None if series_id is None else int(series_id),
        series_title=str(series_title or "").strip(),
        season_number=int(season_number),
        sonarr_base_url=effective_base_url,
        sonarr_config_path=_sonarr_config_path(sonarr_config_path),
        staging_root=_sonarr_staging_root(staging_root),
        timeout_seconds=max(float(timeout_seconds or 20.0), 1.0),
    )
    if output_format == "operator":
        report["operator_text"] = _operator_text_for_sonarr_tv_season(report)
    return report


def repair_sonarr_tv_season(
    *,
    series_id: int | None = None,
    series_title: str = "",
    season_number: int,
    sonarr_base_url: str = "",
    sonarr_config_path: str = "",
    staging_root: str = "",
    timeout_seconds: float = 45.0,
    output_format: str = "json",
) -> dict[str, object]:
    observed_at = _utc_now()
    effective_base_url = str(sonarr_base_url or _env("EA_SONARR_BASE_URL", DEFAULT_SONARR_BASE_URL)).strip() or DEFAULT_SONARR_BASE_URL
    effective_config_path = _sonarr_config_path(sonarr_config_path)
    effective_staging_root = _sonarr_staging_root(staging_root)
    request_timeout = max(float(timeout_seconds or 45.0), 1.0)
    pre_probe = probe_sonarr_tv_season(
        series_id=series_id,
        series_title=series_title,
        season_number=season_number,
        sonarr_base_url=effective_base_url,
        sonarr_config_path=effective_config_path.as_posix(),
        staging_root=effective_staging_root.as_posix(),
        timeout_seconds=min(request_timeout, 20.0),
        output_format="json",
    )
    resolved_series_id = int(pre_probe.get("series_id") or series_id or 0)
    receipt_path = DEFAULT_SONARR_TV_RECEIPT_DIR / f"series-{resolved_series_id or 'lookup'}-season-{int(season_number):02d}.repair.receipt.json"
    report: dict[str, object] = {
        "probe_ok": bool(pre_probe.get("probe_ok")),
        "ready": False,
        "status": "probe_failed",
        "reason": str(pre_probe.get("reason") or "sonarr_tv_season_repair_pre_probe_failed").strip(),
        "next_action": str(pre_probe.get("next_action") or "").strip(),
        "next_action_href": "",
        "next_action_label": "",
        "next_action_method": "",
        "series_id": resolved_series_id,
        "series_title": str(pre_probe.get("series_title") or series_title or "").strip(),
        "season_number": int(season_number),
        "sonarr_base_url": effective_base_url.rstrip("/"),
        "sonarr_config_path": effective_config_path.as_posix(),
        "staging_root": effective_staging_root.as_posix(),
        "moved_file_count": 0,
        "moved_episode_numbers": [],
        "move_errors": [],
        "quarantined_file_count": 0,
        "quarantined_episode_numbers": [],
        "quarantine_errors": [],
        "quarantine_dir": "",
        "refresh_requested": False,
        "refresh_command_id": 0,
        "refresh_status": "",
        "rescan_requested": False,
        "rescan_command_id": 0,
        "rescan_status": "",
        "search_requested": False,
        "search_command_id": 0,
        "search_status": "",
        "search_episode_numbers": [],
        "replacement_queue_rows_removed": 0,
        "replacement_episode_numbers": [],
        "replacement_titles": [],
        "replacement_grab_count": 0,
        "replacement_errors": [],
        "queued_missing_episode_numbers_after": [],
        "queue_rows_removed": 0,
        "removed_queue_episode_numbers": [],
        "pre_probe_status": str(pre_probe.get("status") or "").strip(),
        "post_probe_status": "",
        "post_cleanup_status": "",
        "missing_episode_numbers_after": list(pre_probe.get("missing_episode_numbers") or []),
        "unreadable_episode_numbers_after": list(pre_probe.get("unreadable_episode_numbers") or []),
        "metadata_queue_episode_numbers_after": list(pre_probe.get("metadata_queue_episode_numbers") or []),
        "before_probe": pre_probe,
        "after_probe": pre_probe,
        "observed_at": observed_at,
        "source": "ffprobe+filesystem.move+sonarr.command+queue.delete+sonarr.release",
        "privacy": {
            "raw_api_key_exposed": False,
            "raw_download_client_credentials_exposed": False,
        },
    }

    def _finalize(updated: dict[str, object]) -> dict[str, object]:
        updated["receipt_path"] = str(receipt_path)
        _write_private_json(receipt_path, updated)
        if output_format == "operator":
            updated["operator_text"] = _operator_text_for_sonarr_tv_season_repair(updated)
        return updated

    if not bool(pre_probe.get("probe_ok")):
        return _finalize(report)
    if str(pre_probe.get("status") or "").strip() in {"blocked_series_not_found", "blocked_season_not_found"}:
        report["status"] = "repair_blocked"
        return _finalize(report)

    moved_episode_numbers: list[int] = []
    move_errors: list[str] = []
    quarantined_episode_numbers: list[int] = []
    quarantine_errors: list[str] = []
    missing_before = {int(item) for item in list(pre_probe.get("missing_episode_numbers") or []) if int(item) > 0}
    unreadable_before = {int(item) for item in list(pre_probe.get("unreadable_episode_numbers") or []) if int(item) > 0}
    media_info_missing_before = {int(item) for item in list(pre_probe.get("media_info_missing_episode_numbers") or []) if int(item) > 0}
    staging_candidates = [dict(item) for item in list(pre_probe.get("staging_candidates") or []) if isinstance(item, dict)]
    target_dir = _sonarr_series_target_dir(
        str(pre_probe.get("series_path") or "").strip(),
        season_folder=bool(pre_probe.get("season_folder", True)),
        season_number=int(season_number),
    )
    if unreadable_before:
        quarantine_dir = _sonarr_quarantine_dir(
            series_path=str(pre_probe.get("series_path") or "").strip(),
            series_id=resolved_series_id or int(pre_probe.get("series_id") or 0),
            season_number=int(season_number),
        )
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        report["quarantine_dir"] = quarantine_dir.as_posix()
        for episode_number in sorted(unreadable_before):
            for file_path in _sonarr_target_episode_files(target_dir, season_number=int(season_number), episode_number=int(episode_number)):
                destination = _sonarr_unique_destination(quarantine_dir / file_path.name)
                try:
                    file_path.replace(destination)
                except Exception as exc:
                    quarantine_errors.append(f"{file_path.name}:{type(exc).__name__}")
                    continue
                quarantined_episode_numbers.append(int(episode_number))
        report["quarantined_file_count"] = len(quarantined_episode_numbers)
        report["quarantined_episode_numbers"] = sorted(quarantined_episode_numbers)
        report["quarantine_errors"] = quarantine_errors

    repair_episode_numbers = missing_before | unreadable_before
    candidate_rows = [
        candidate
        for candidate in staging_candidates
        if int(candidate.get("valid_cover_count") or candidate.get("cover_count") or 0) > 0
    ]
    if repair_episode_numbers and candidate_rows:
        target_dir.mkdir(parents=True, exist_ok=True)
        for candidate_row in candidate_rows:
            for file_path in _sonarr_candidate_episode_files(Path(str(candidate_row.get("path") or "")), season_number=int(season_number)):
                episode_number = _sonarr_episode_number_from_text(file_path.name, season_number=int(season_number))
                if episode_number is None or int(episode_number) not in repair_episode_numbers:
                    continue
                probe_result = _sonarr_probe_file_playability(
                    file_path,
                    timeout_seconds=min(request_timeout, DEFAULT_SONARR_FFPROBE_TIMEOUT_SECONDS),
                )
                if bool(probe_result.get("probed")) and not bool(probe_result.get("ok")):
                    move_errors.append(
                        f"{file_path.name}:{str(probe_result.get('reason') or 'invalid_media').strip() or 'invalid_media'}"
                    )
                    continue
                if _sonarr_target_has_episode(target_dir, season_number=int(season_number), episode_number=int(episode_number)):
                    continue
                destination = target_dir / file_path.name
                try:
                    shutil.move(file_path.as_posix(), destination.as_posix())
                except Exception as exc:
                    move_errors.append(f"{file_path.name}:{type(exc).__name__}")
                    continue
                moved_episode_numbers.append(int(episode_number))
        report["moved_file_count"] = len(moved_episode_numbers)
        report["moved_episode_numbers"] = sorted(moved_episode_numbers)
        report["move_errors"] = move_errors

    command_should_refresh = bool(moved_episode_numbers or quarantined_episode_numbers or media_info_missing_before)
    if command_should_refresh:
        api_key = _read_xml_api_key(effective_config_path)
        report["refresh_requested"] = True
        refresh_result = _sonarr_request_command(
            base_url=effective_base_url,
            api_key=api_key,
            name="RefreshSeries",
            body={"seriesId": resolved_series_id},
            timeout_seconds=request_timeout,
        )
        report["refresh_command_id"] = int(refresh_result.get("command_id") or 0)
        report["refresh_status"] = str(refresh_result.get("status") or "").strip()
        report["rescan_requested"] = True
        rescan_result = _sonarr_request_command(
            base_url=effective_base_url,
            api_key=api_key,
            name="RescanSeries",
            body={"seriesId": resolved_series_id},
            timeout_seconds=request_timeout,
        )
        report["rescan_command_id"] = int(rescan_result.get("command_id") or 0)
        report["rescan_status"] = str(rescan_result.get("status") or "").strip()

    post_probe = probe_sonarr_tv_season(
        series_id=resolved_series_id or series_id,
        series_title=str(pre_probe.get("series_title") or series_title or "").strip(),
        season_number=season_number,
        sonarr_base_url=effective_base_url,
        sonarr_config_path=effective_config_path.as_posix(),
        staging_root=effective_staging_root.as_posix(),
        timeout_seconds=min(request_timeout, 20.0),
        output_format="json",
    )
    report["post_probe_status"] = str(post_probe.get("status") or "").strip()
    report["after_probe"] = post_probe

    cleanup_items = []
    have_after = {int(item) for item in list(post_probe.get("have_episode_numbers") or []) if int(item) > 0}
    for item in list(post_probe.get("metadata_queue_items") or []):
        row = dict(item) if isinstance(item, dict) else {}
        episode_number = int(row.get("episode_number") or 0)
        if episode_number <= 0:
            continue
        if episode_number in have_after or bool(row.get("episode_has_file")) or bool(row.get("is_stale")):
            cleanup_items.append(row)
    cleanup_ids = [int(item.get("id") or 0) for item in cleanup_items if int(item.get("id") or 0) > 0]
    cleanup_ids = sorted(set(cleanup_ids))
    if cleanup_ids:
        api_key = _read_xml_api_key(effective_config_path)
        try:
            cleanup_result = _sonarr_delete_queue_rows(
                base_url=effective_base_url,
                api_key=api_key,
                queue_ids=cleanup_ids,
                timeout_seconds=min(request_timeout, 20.0),
            )
            if bool(cleanup_result.get("ok")):
                report["queue_rows_removed"] = int(cleanup_result.get("removed_count") or 0)
                report["removed_queue_episode_numbers"] = sorted(
                    {
                        int(item.get("episode_number") or 0)
                        for item in cleanup_items
                        if int(item.get("episode_number") or 0) > 0
                    }
                )
        except Exception as exc:
            report["queue_cleanup_error"] = type(exc).__name__

    final_probe = post_probe
    if cleanup_ids:
        final_probe = probe_sonarr_tv_season(
            series_id=resolved_series_id or series_id,
            series_title=str(pre_probe.get("series_title") or series_title or "").strip(),
            season_number=season_number,
            sonarr_base_url=effective_base_url,
            sonarr_config_path=effective_config_path.as_posix(),
            staging_root=effective_staging_root.as_posix(),
            timeout_seconds=min(request_timeout, 20.0),
            output_format="json",
        )
    report["post_cleanup_status"] = str(final_probe.get("status") or "").strip()
    report["after_probe"] = final_probe
    report["missing_episode_numbers_after"] = list(final_probe.get("missing_episode_numbers") or [])
    report["unreadable_episode_numbers_after"] = list(final_probe.get("unreadable_episode_numbers") or [])
    report["metadata_queue_episode_numbers_after"] = list(final_probe.get("metadata_queue_episode_numbers") or [])
    report["series_title"] = str(final_probe.get("series_title") or report.get("series_title") or "").strip()
    report["series_id"] = int(final_probe.get("series_id") or report.get("series_id") or 0)

    api_key = _read_xml_api_key(effective_config_path)
    missing_episode_numbers_after = [
        int(item) for item in list(final_probe.get("missing_episode_numbers") or []) if int(item) > 0
    ]
    missing_episode_numbers_after_lookup = set(missing_episode_numbers_after)
    missing_episode_ids_after = [int(item) for item in list(final_probe.get("missing_episode_ids") or []) if int(item) > 0]
    missing_id_to_number = {
        int(episode_id): int(episode_number)
        for episode_id, episode_number in zip(missing_episode_ids_after, missing_episode_numbers_after, strict=False)
        if int(episode_id) > 0 and int(episode_number) > 0
    }
    metadata_episode_number_by_queue_id = {
        int(item.get("id") or 0): int(item.get("episode_number") or 0)
        for item in list(final_probe.get("metadata_queue_items") or [])
        if isinstance(item, Mapping) and int(item.get("id") or 0) > 0 and int(item.get("episode_number") or 0) > 0
    }
    metadata_episode_number_by_episode_id = {
        int(item.get("episode_id") or 0): int(item.get("episode_number") or 0)
        for item in list(final_probe.get("metadata_queue_items") or [])
        if isinstance(item, Mapping) and int(item.get("episode_id") or 0) > 0 and int(item.get("episode_number") or 0) > 0
    }
    replacement_episode_numbers: list[int] = []
    replacement_titles: list[str] = []
    replacement_errors: list[str] = []
    queue_rows_current = _sonarr_list_queue(
        base_url=effective_base_url,
        api_key=api_key,
        timeout_seconds=min(request_timeout, 20.0),
    )
    replacement_rows: list[dict[str, object]] = []
    for row in queue_rows_current:
        snapshot = _sonarr_queue_row_episode_snapshot(row)
        episode_id = int(snapshot.get("episode_id") or 0)
        episode_number = int(snapshot.get("episode_number") or 0)
        if episode_number <= 0:
            episode_number = int(metadata_episode_number_by_queue_id.get(int(row.get("id") or 0)) or 0)
        if episode_number <= 0 and episode_id > 0:
            episode_number = int(metadata_episode_number_by_episode_id.get(episode_id) or missing_id_to_number.get(episode_id) or 0)
        if int(snapshot.get("series_id") or 0) != resolved_series_id:
            continue
        if int(snapshot.get("season_number") or 0) != int(season_number):
            continue
        if episode_number <= 0 or episode_id <= 0 or episode_number not in missing_episode_numbers_after_lookup:
            continue
        error_message = str(row.get("errorMessage") or "").strip().lower()
        if not (_sonarr_queue_is_metadata_only(row) or "stalled with no connections" in error_message):
            continue
        age_seconds = _age_seconds(row.get("added"))
        if age_seconds is not None and age_seconds < int(DEFAULT_SONARR_QUEUE_REPLACEMENT_MIN_AGE_SECONDS):
            continue
        replacement_rows.append(dict(row))
    for row in replacement_rows:
        snapshot = _sonarr_queue_row_episode_snapshot(row)
        episode_number = int(snapshot.get("episode_number") or 0)
        episode_id = int(snapshot.get("episode_id") or 0)
        queue_id = int(row.get("id") or 0)
        if episode_number <= 0:
            episode_number = int(metadata_episode_number_by_queue_id.get(queue_id) or 0)
        if episode_number <= 0 and episode_id > 0:
            episode_number = int(metadata_episode_number_by_episode_id.get(episode_id) or missing_id_to_number.get(episode_id) or 0)
        if queue_id <= 0 or episode_id <= 0 or episode_number <= 0:
            continue
        releases = _sonarr_list_releases_for_episode(
            base_url=effective_base_url,
            api_key=api_key,
            episode_id=episode_id,
            timeout_seconds=min(request_timeout, 20.0),
        )
        replacement = _sonarr_pick_replacement_release(
            releases,
            season_number=int(season_number),
            episode_number=episode_number,
            current_download_id=str(row.get("downloadId") or "").strip(),
        )
        if not replacement:
            replacement_errors.append(f"S{int(season_number):02d}E{episode_number:02d}:no_viable_replacement")
            continue
        try:
            removal = _sonarr_delete_queue_rows(
                base_url=effective_base_url,
                api_key=api_key,
                queue_ids=[queue_id],
                timeout_seconds=min(request_timeout, 20.0),
                blocklist=True,
                skip_redownload=True,
            )
        except Exception as exc:
            replacement_errors.append(f"S{int(season_number):02d}E{episode_number:02d}:delete_{type(exc).__name__}")
            continue
        if not bool(removal.get("ok")):
            replacement_errors.append(f"S{int(season_number):02d}E{episode_number:02d}:delete_failed")
            continue
        grab = _sonarr_grab_release(
            base_url=effective_base_url,
            api_key=api_key,
            release=replacement,
            timeout_seconds=min(request_timeout, 20.0),
        )
        if not bool(grab.get("ok")):
            replacement_errors.append(
                f"S{int(season_number):02d}E{episode_number:02d}:grab_{str(grab.get('status') or 'failed').strip() or 'failed'}"
            )
            continue
        replacement_episode_numbers.append(episode_number)
        replacement_titles.append(str(replacement.get("title") or "").strip())
    report["replacement_queue_rows_removed"] = len(replacement_episode_numbers)
    report["replacement_grab_count"] = len(replacement_episode_numbers)
    report["replacement_episode_numbers"] = sorted({int(item) for item in replacement_episode_numbers if int(item) > 0})
    report["replacement_titles"] = [item for item in replacement_titles if item]
    report["replacement_errors"] = replacement_errors
    if replacement_episode_numbers:
        final_probe = probe_sonarr_tv_season(
            series_id=resolved_series_id or series_id,
            series_title=str(pre_probe.get("series_title") or series_title or "").strip(),
            season_number=season_number,
            sonarr_base_url=effective_base_url,
            sonarr_config_path=effective_config_path.as_posix(),
            staging_root=effective_staging_root.as_posix(),
            timeout_seconds=min(request_timeout, 20.0),
            output_format="json",
        )
        report["post_cleanup_status"] = str(final_probe.get("status") or "").strip()
        report["after_probe"] = final_probe
        report["missing_episode_numbers_after"] = list(final_probe.get("missing_episode_numbers") or [])
        report["unreadable_episode_numbers_after"] = list(final_probe.get("unreadable_episode_numbers") or [])
        report["metadata_queue_episode_numbers_after"] = list(final_probe.get("metadata_queue_episode_numbers") or [])
        report["series_title"] = str(final_probe.get("series_title") or report.get("series_title") or "").strip()
        report["series_id"] = int(final_probe.get("series_id") or report.get("series_id") or 0)

    missing_episode_ids_after = [int(item) for item in list(final_probe.get("missing_episode_ids") or []) if int(item) > 0]
    missing_episode_numbers_after = [
        int(item) for item in list(final_probe.get("missing_episode_numbers") or []) if int(item) > 0
    ]
    missing_id_to_number = {
        int(episode_id): int(episode_number)
        for episode_id, episode_number in zip(missing_episode_ids_after, missing_episode_numbers_after, strict=False)
        if int(episode_id) > 0 and int(episode_number) > 0
    }
    queue_rows_current = _sonarr_list_queue(
        base_url=effective_base_url,
        api_key=api_key,
        timeout_seconds=min(request_timeout, 20.0),
    )
    queued_missing_episode_ids: set[int] = set()
    queued_missing_episode_numbers: set[int] = set()
    for row in queue_rows_current:
        snapshot = _sonarr_queue_row_episode_snapshot(row)
        episode_id = int(snapshot.get("episode_id") or 0)
        episode_number = int(snapshot.get("episode_number") or 0)
        if int(snapshot.get("series_id") or 0) != resolved_series_id:
            continue
        if int(snapshot.get("season_number") or 0) != int(season_number):
            continue
        if episode_id in missing_episode_ids_after:
            queued_missing_episode_ids.add(episode_id)
        if episode_number <= 0 and episode_id > 0:
            episode_number = int(missing_id_to_number.get(episode_id) or 0)
        if episode_number > 0 and episode_number in set(missing_episode_numbers_after):
            queued_missing_episode_numbers.add(episode_number)
    report["queued_missing_episode_numbers_after"] = sorted(queued_missing_episode_numbers)

    search_episode_ids = [item for item in missing_episode_ids_after if item not in queued_missing_episode_ids]
    if search_episode_ids:
        report["search_requested"] = True
        report["search_episode_numbers"] = [
            int(item)
            for item in list(final_probe.get("missing_episode_numbers") or [])
            if int(item) > 0 and int(item) not in queued_missing_episode_numbers
        ]
        search_result = _sonarr_request_command(
            base_url=effective_base_url,
            api_key=api_key,
            name="EpisodeSearch",
            body={"episodeIds": search_episode_ids},
            timeout_seconds=request_timeout,
        )
        report["search_command_id"] = int(search_result.get("command_id") or 0)
        report["search_status"] = str(search_result.get("status") or "").strip()
        final_probe = probe_sonarr_tv_season(
            series_id=resolved_series_id or series_id,
            series_title=str(pre_probe.get("series_title") or series_title or "").strip(),
            season_number=season_number,
            sonarr_base_url=effective_base_url,
            sonarr_config_path=effective_config_path.as_posix(),
            staging_root=effective_staging_root.as_posix(),
            timeout_seconds=min(request_timeout, 20.0),
            output_format="json",
        )
        report["post_cleanup_status"] = str(final_probe.get("status") or "").strip()
        report["after_probe"] = final_probe
        report["missing_episode_numbers_after"] = list(final_probe.get("missing_episode_numbers") or [])
        report["unreadable_episode_numbers_after"] = list(final_probe.get("unreadable_episode_numbers") or [])
        report["metadata_queue_episode_numbers_after"] = list(final_probe.get("metadata_queue_episode_numbers") or [])
        report["series_title"] = str(final_probe.get("series_title") or report.get("series_title") or "").strip()
        report["series_id"] = int(final_probe.get("series_id") or report.get("series_id") or 0)

    if bool(final_probe.get("ready")):
        report.update(
            {
                "ready": True,
                "status": (
                    "repaired"
                    if int(report.get("moved_file_count") or 0) > 0
                    or int(report.get("queue_rows_removed") or 0) > 0
                    or int(report.get("quarantined_file_count") or 0) > 0
                    else "ready"
                ),
                "reason": "",
                "next_action": "",
            }
        )
        return _finalize(report)

    if (
        int(report.get("moved_file_count") or 0) > 0
        or int(report.get("queue_rows_removed") or 0) > 0
        or int(report.get("replacement_grab_count") or 0) > 0
        or int(report.get("quarantined_file_count") or 0) > 0
        or bool(report.get("search_requested"))
    ):
        queued_missing_after = [int(item) for item in list(report.get("queued_missing_episode_numbers_after") or []) if int(item) > 0]
        report.update(
            {
                "ready": False,
                "status": (
                    "recovery_in_progress"
                    if bool(report.get("search_requested")) or queued_missing_after
                    else "repair_incomplete"
                ),
                "reason": (
                    "sonarr_episode_search_requested"
                    if bool(report.get("search_requested"))
                    else (
                        "sonarr_missing_episodes_already_queued"
                        if queued_missing_after
                        else str(final_probe.get("reason") or "sonarr_tv_season_still_blocked").strip()
                    )
                ),
                "next_action": (
                    "wait_for_download_client_or_reprobe_sonarr_tv_season"
                    if bool(report.get("search_requested")) or queued_missing_after
                    else str(final_probe.get("next_action") or "").strip()
                ),
            }
        )
        return _finalize(report)

    report.update(
        {
            "ready": False,
            "status": "repair_blocked",
            "reason": str(pre_probe.get("reason") or "sonarr_tv_season_repair_blocked").strip(),
            "next_action": str(pre_probe.get("next_action") or "").strip(),
        }
    )
    return _finalize(report)


def probe_teable_recovery(
    *,
    output_format: str = "json",
    timeout_seconds: float = 30.0,
) -> dict[str, object]:
    observed_at = _utc_now()
    verify_exit, verify_payload, verify_stderr = _sync_env_to_teable_json("verify", timeout_seconds=timeout_seconds)
    local_exit, local_payload, local_stderr = _sync_env_to_teable_json("local-status", timeout_seconds=timeout_seconds)
    verify_status = str(verify_payload.get("status") or ("probe_failed" if verify_exit else "unknown")).strip()
    local_status = str(local_payload.get("status") or ("probe_failed" if local_exit else "unknown")).strip()
    table_id = str(verify_payload.get("table_id") or local_payload.get("table_id") or "").strip()
    missing_artifact_count = _int_payload(local_payload, "missing_artifact_count")
    wrong_mode_count = _int_payload(local_payload, "wrong_mode_count")
    different_hash_count = max(_int_payload(verify_payload, "different_hash_count"), _int_payload(local_payload, "different_hash_count"))
    missing_count = _int_payload(verify_payload, "missing_count")
    missing_secret_value_count = _int_payload(verify_payload, "missing_secret_value_count")
    extra_restorable_count = _int_payload(verify_payload, "extra_restorable_count")
    uncovered_local_secret_file_count = _int_payload(verify_payload, "uncovered_local_secret_file_count")
    different_hash_key_samples = [
        str(item or "").strip()
        for item in (
            list(verify_payload.get("different_hash_keys") or [])
            + list(local_payload.get("different_hash_keys") or [])
        )
        if str(item or "").strip()
    ]
    different_hash_key_samples = list(dict.fromkeys(different_hash_key_samples))[:10]
    probe_ok = bool(verify_payload) and bool(local_payload)
    ready = (
        probe_ok
        and verify_exit == 0
        and local_exit == 0
        and verify_status == "pass"
        and local_status == "pass"
        and missing_artifact_count == 0
        and wrong_mode_count == 0
        and different_hash_count == 0
        and missing_count == 0
        and missing_secret_value_count == 0
        and extra_restorable_count == 0
        and uncovered_local_secret_file_count == 0
    )
    reason = ""
    next_action = ""
    if not probe_ok:
        reason = "teable_recovery_probe_failed"
        next_action = "inspect_teable_recovery_probe"
    elif wrong_mode_count:
        reason = "teable_recovery_local_secret_mode_drift"
        next_action = "chmod_referenced_secret_files_owner_only"
    elif missing_artifact_count:
        reason = "teable_recovery_local_artifacts_missing"
        next_action = "restore_missing_teable_recovery_artifacts"
    elif different_hash_count:
        reason = "teable_recovery_local_hash_drift"
        next_action = "run_env_recover_teable_or_refresh_backup_after_review"
    elif verify_status != "pass" or verify_exit != 0:
        reason = "teable_recovery_verify_failed"
        next_action = "run_make_env_check_teable_or_repair_teable_recovery_table"
    elif local_status != "pass" or local_exit != 0:
        reason = "teable_recovery_local_status_failed"
        next_action = "inspect_teable_recovery_local_status"
    report = {
        "probe_ok": probe_ok,
        "ready": ready,
        "status": "ready" if ready else "blocked" if probe_ok else "probe_failed",
        "reason": reason,
        "next_action": next_action,
        "verify_status": verify_status,
        "verify_exit_code": verify_exit,
        "local_status": local_status,
        "local_exit_code": local_exit,
        "table_id_present": bool(table_id),
        "table_id_sha256": _hash_text(table_id),
        "expected_rows": max(_int_payload(verify_payload, "expected_rows"), _int_payload(local_payload, "expected_rows")),
        "same_hash": max(_int_payload(verify_payload, "same_hash"), _int_payload(local_payload, "same_hash")),
        "root_restore_count": max(_int_payload(verify_payload, "root_restore_count"), _int_payload(local_payload, "root_restore_count")),
        "local_restore_count": max(_int_payload(verify_payload, "local_restore_count"), _int_payload(local_payload, "local_restore_count")),
        "service_restore_count": max(_int_payload(verify_payload, "service_restore_count"), _int_payload(local_payload, "service_restore_count")),
        "referenced_file_restore_count": max(
            _int_payload(verify_payload, "referenced_file_restore_count"),
            _int_payload(local_payload, "referenced_file_restore_count"),
        ),
        "missing_count": missing_count,
        "missing_artifact_count": missing_artifact_count,
        "wrong_mode_count": wrong_mode_count,
        "different_hash_count": different_hash_count,
        "missing_secret_value_count": missing_secret_value_count,
        "extra_restorable_count": extra_restorable_count,
        "uncovered_local_secret_file_count": uncovered_local_secret_file_count,
        "wrong_mode_paths": [
            str(dict(item).get("path") or "").strip()
            for item in list(local_payload.get("wrong_modes") or [])
            if isinstance(item, dict) and str(dict(item).get("path") or "").strip()
        ][:10],
        "different_hash_key_samples": different_hash_key_samples,
        "observed_at": observed_at,
        "source": "sync_env_to_teable.verify+local_status",
    }
    if verify_stderr:
        report["verify_error"] = verify_stderr
    if local_stderr:
        report["local_error"] = local_stderr
    if output_format == "operator":
        report["operator_text"] = _operator_text_for_teable_recovery(report)
    return report


def _telegram_readiness_payload_from_host(*, principal_id: str) -> dict[str, object]:
    try:
        from app.settings import get_settings
        from app.services.telegram_delivery import (
            TELEGRAM_IDENTITY_CONNECTOR,
            _telegram_binding_principal_candidates,
            _telegram_bot_registry,
        )
        from app.services.tool_runtime import build_tool_runtime
    except Exception as exc:
        return {"ok": False, "ready": False, "status": "probe_failed", "reason": type(exc).__name__}

    try:
        tool_runtime = build_tool_runtime(get_settings())
        candidates = list(_telegram_binding_principal_candidates(str(principal_id or "").strip()))
        ranked: list[tuple[tuple[object, ...], object]] = []
        for candidate_index, binding_principal_id in enumerate(candidates):
            for row in tool_runtime.list_connector_bindings(binding_principal_id, limit=200):
                if str(getattr(row, "connector_name", "") or "").strip() != TELEGRAM_IDENTITY_CONNECTOR:
                    continue
                if str(getattr(row, "status", "") or "").strip().lower() != "enabled":
                    continue
                metadata = dict(getattr(row, "auth_metadata_json", None) or {})
                chat_ref = str(metadata.get("default_chat_ref") or getattr(row, "external_account_ref", "") or "").strip()
                if not chat_ref:
                    continue
                numeric = 1 if chat_ref.isdigit() else 0
                plausible_numeric = 1 if numeric and int(chat_ref) > 1000 else 0
                ranked.append(
                    (
                        (plausible_numeric, numeric, -candidate_index, str(getattr(row, "updated_at", "") or "")),
                        row,
                    )
                )
        ranked.sort(key=lambda item: item[0], reverse=True)
        binding = ranked[0][1] if ranked else None
        if binding is None:
            return {"ok": True, "ready": False, "status": "blocked", "reason": "telegram_binding_not_found"}

        metadata = dict(getattr(binding, "auth_metadata_json", None) or {})
        chat_ref = str(metadata.get("default_chat_ref") or getattr(binding, "external_account_ref", "") or "").strip()
        bot_key = str(metadata.get("bot_key") or "default").strip() or "default"
        config = dict((_telegram_bot_registry().get(bot_key) or {}))
        token_present = bool(str(config.get("token") or "").strip())
        bot_handle = str(metadata.get("bot_handle") or config.get("handle") or "").strip()
        reason = ""
        if not chat_ref:
            reason = "telegram_chat_ref_missing"
        elif not token_present:
            reason = "telegram_bot_token_missing"
        ready = not reason
        return {
            "ok": True,
            "ready": ready,
            "status": "ready" if ready else "blocked",
            "reason": reason,
            "binding_id": str(getattr(binding, "binding_id", "") or "").strip(),
            "principal_id": str(getattr(binding, "principal_id", "") or principal_id or "").strip(),
            "binding_status": str(getattr(binding, "status", "") or "").strip(),
            "chat_ref_present": bool(chat_ref),
            "chat_ref_sha256": _hash_text(chat_ref) if chat_ref else "",
            "bot_key": bot_key,
            "bot_handle": bot_handle,
            "bot_token_present": token_present,
        }
    except Exception as exc:
        return {"ok": False, "ready": False, "status": "probe_failed", "reason": type(exc).__name__}


def probe_telegram_readiness(
    *,
    principal_id: str,
    timeout_seconds: float | None = None,
    output_format: str = "json",
) -> dict[str, object]:
    observed_at = _utc_now()
    source = "runtime_container_exec:telegram_delivery.local_binding_scan"
    code = (
        "import hashlib, json, os\n"
        "principal_id = "
        + json.dumps(str(principal_id or "").strip())
        + "\n"
        "try:\n"
        "    from app.settings import get_settings\n"
        "    from app.services.telegram_delivery import TELEGRAM_IDENTITY_CONNECTOR, _telegram_binding_principal_candidates, _telegram_bot_registry\n"
        "    from app.services.tool_runtime import build_tool_runtime\n"
        "    tool_runtime = build_tool_runtime(get_settings())\n"
        "    candidates = list(_telegram_binding_principal_candidates(principal_id))\n"
        "    ranked = []\n"
        "    for candidate_index, binding_principal_id in enumerate(candidates):\n"
        "        for row in tool_runtime.list_connector_bindings(binding_principal_id, limit=200):\n"
        "            if str(getattr(row, 'connector_name', '') or '').strip() != TELEGRAM_IDENTITY_CONNECTOR:\n"
        "                continue\n"
        "            if str(getattr(row, 'status', '') or '').strip().lower() != 'enabled':\n"
        "                continue\n"
        "            metadata = dict(getattr(row, 'auth_metadata_json', None) or {})\n"
        "            chat_ref = str(metadata.get('default_chat_ref') or getattr(row, 'external_account_ref', '') or '').strip()\n"
        "            if not chat_ref:\n"
        "                continue\n"
        "            numeric = 1 if chat_ref.isdigit() else 0\n"
        "            plausible_numeric = 1 if numeric and int(chat_ref) > 1000 else 0\n"
        "            ranked.append(((plausible_numeric, numeric, -candidate_index, str(getattr(row, 'updated_at', '') or '')), row))\n"
        "    ranked.sort(key=lambda item: item[0], reverse=True)\n"
        "    binding = ranked[0][1] if ranked else None\n"
        "    if binding is None:\n"
        "        print(json.dumps({'ok': True, 'ready': False, 'status': 'blocked', 'reason': 'telegram_binding_not_found'}), flush=True)\n"
        "        os._exit(0)\n"
        "    else:\n"
        "        metadata = dict(getattr(binding, 'auth_metadata_json', None) or {})\n"
        "        chat_ref = str(metadata.get('default_chat_ref') or getattr(binding, 'external_account_ref', '') or '').strip()\n"
        "        bot_key = str(metadata.get('bot_key') or 'default').strip() or 'default'\n"
        "        config = dict((_telegram_bot_registry().get(bot_key) or {}))\n"
        "        token_present = bool(str(config.get('token') or '').strip())\n"
        "        bot_handle = str(metadata.get('bot_handle') or config.get('handle') or '').strip()\n"
        "        reason = ''\n"
        "        if not chat_ref:\n"
        "            reason = 'telegram_chat_ref_missing'\n"
        "        elif not token_present:\n"
        "            reason = 'telegram_bot_token_missing'\n"
        "        ready = not reason\n"
        "        payload = {\n"
        "            'ok': True,\n"
        "            'ready': ready,\n"
        "            'status': 'ready' if ready else 'blocked',\n"
        "            'reason': reason,\n"
        "            'binding_id': str(getattr(binding, 'binding_id', '') or '').strip(),\n"
        "            'principal_id': str(getattr(binding, 'principal_id', '') or principal_id or '').strip(),\n"
        "            'binding_status': str(getattr(binding, 'status', '') or '').strip(),\n"
        "            'chat_ref_present': bool(chat_ref),\n"
        "            'chat_ref_sha256': hashlib.sha256(chat_ref.encode('utf-8')).hexdigest() if chat_ref else '',\n"
        "            'bot_key': bot_key,\n"
        "            'bot_handle': bot_handle,\n"
        "            'bot_token_present': token_present,\n"
        "        }\n"
        "        print(json.dumps(payload, sort_keys=True), flush=True)\n"
        "        os._exit(0)\n"
        "except Exception as exc:\n"
        "    print(json.dumps({'ok': False, 'ready': False, 'status': 'probe_failed', 'reason': type(exc).__name__}, sort_keys=True), flush=True)\n"
        "    os._exit(0)\n"
    )
    effective_timeout_seconds = _telegram_readiness_timeout_seconds(timeout_seconds)
    exit_code, payload, runtime_container = _runtime_container_exec_json(code=code, timeout_seconds=effective_timeout_seconds)
    payload_status = str(payload.get("status") or "probe_failed").strip() or "probe_failed"
    if exit_code != 0 or not bool(payload):
        host_payload = _telegram_readiness_payload_from_host(principal_id=str(principal_id or "").strip())
        host_status = str(host_payload.get("status") or "probe_failed").strip() or "probe_failed"
        host_ok = bool(host_payload.get("ok", host_status != "probe_failed"))
        if bool(host_payload) and host_ok and host_status != "probe_failed":
            payload = host_payload
            payload_status = host_status
            exit_code = 0
            source = "host_process:telegram_delivery.local_binding_scan"
    payload_status = str(payload.get("status") or "probe_failed").strip() or "probe_failed"
    payload_ok = bool(payload.get("ok", payload_status != "probe_failed"))
    report = {
        "probe_ok": exit_code == 0 and bool(payload) and payload_ok and payload_status != "probe_failed",
        "ready": bool(payload.get("ready")) if exit_code == 0 else False,
        "status": payload_status,
        "reason": str(payload.get("reason") or "").strip() or (f"runtime_container_exec_exit_{exit_code}" if exit_code else ""),
        "next_action": "",
        "principal_id": str(payload.get("principal_id") or principal_id or "").strip(),
        "binding_id": str(payload.get("binding_id") or "").strip(),
        "binding_status": str(payload.get("binding_status") or "").strip(),
        "chat_ref_present": bool(payload.get("chat_ref_present")),
        "chat_ref_sha256": str(payload.get("chat_ref_sha256") or "").strip(),
        "bot_key": str(payload.get("bot_key") or "").strip(),
        "bot_handle": str(payload.get("bot_handle") or "").strip(),
        "bot_token_present": bool(payload.get("bot_token_present")),
        "runtime_container": runtime_container,
        "timeout_seconds": effective_timeout_seconds,
        "observed_at": observed_at,
        "source": source,
    }
    if report["status"] == "blocked":
        if report["reason"] == "telegram_binding_not_found":
            report["next_action"] = "connect_telegram_identity_binding"
        elif report["reason"] == "telegram_chat_ref_missing":
            report["next_action"] = "repair_telegram_chat_binding"
        elif report["reason"] == "telegram_bot_token_missing":
            report["next_action"] = "configure_telegram_bot_token"
    elif report["status"] == "probe_failed":
        report["next_action"] = "inspect_telegram_readiness_runtime_probe"
    if output_format == "operator":
        report["operator_text"] = _operator_text_for_telegram_readiness(report)
    return report


def probe_whatsapp_readiness(
    *,
    refresh: bool = True,
    receipt_path: str = "",
    output_format: str = "json",
    volatile: bool = False,
) -> dict[str, object]:
    observed_at = _utc_now()
    source = "materialize_whatsapp_web_action_processor_readiness"
    try:
        if refresh:
            if volatile:
                source = "materialize_whatsapp_web_action_processor_readiness:volatile"
                with tempfile.TemporaryDirectory(prefix="ea-whatsapp-readiness-") as tmpdir:
                    output_path = Path(tmpdir) / DEFAULT_READINESS_RECEIPT_FILENAME
                    payload = whatsapp_action_processor_readiness.build_whatsapp_web_action_processor_readiness(
                        output_path=output_path
                    )
            else:
                output_path = Path(str(receipt_path or whatsapp_action_processor_readiness.DEFAULT_OUTPUT))
                payload = whatsapp_action_processor_readiness.build_whatsapp_web_action_processor_readiness(output_path=output_path)
        else:
            source = "receipt_file"
            output_path = Path(str(receipt_path or DEFAULT_READINESS_RECEIPT_PATH))
            payload = _read_json_file(output_path)
    except Exception as exc:
        report = {
            "probe_ok": False,
            "status": "probe_failed",
            "ready": False,
            "reason": type(exc).__name__,
            "reasons": [type(exc).__name__],
            "next_action": "inspect_whatsapp_action_processor_readiness_probe",
            "observed_at": observed_at,
            "source": source,
        }
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_whatsapp_readiness(report)
        return report

    receipt = dict(payload) if isinstance(payload, dict) else {}
    report = {
        "probe_ok": bool(receipt),
        "status": str(receipt.get("status") or "missing").strip() or "missing",
        "ready": bool(receipt.get("ready")),
        "reason": str(receipt.get("reason") or "").strip(),
        "reasons": [str(item or "").strip() for item in list(receipt.get("reasons") or []) if str(item or "").strip()],
        "next_action": str(receipt.get("next_action") or "").strip(),
        "generated_at": str(receipt.get("generated_at") or "").strip(),
        "observed_at": observed_at,
        "source": source,
        "volatile": bool(refresh and volatile),
        "output_path": str(receipt.get("output_path") or receipt_path or DEFAULT_READINESS_RECEIPT_PATH).strip(),
        "source_git_head": str(receipt.get("source_git_head") or "").strip(),
        "effective_session_ref": str(receipt.get("effective_session_ref") or "").strip(),
        "effective_session_ref_source": str(receipt.get("effective_session_ref_source") or "").strip(),
        "sidecar_ready": bool(receipt.get("sidecar_ready")),
        "sidecar_status": str(receipt.get("sidecar_status") or "").strip(),
        "sidecar_qr_required": bool(receipt.get("sidecar_qr_required")),
        "sidecar_qr_present": bool(receipt.get("sidecar_qr_present")),
        "sidecar_qr_age_seconds": int(receipt.get("sidecar_qr_age_seconds") or 0),
        "sidecar_qr_fresh": bool(receipt.get("sidecar_qr_fresh")),
        "processor_container_enabled": bool(receipt.get("processor_container_enabled")),
        "processor_callback_secret_present": bool(receipt.get("processor_callback_secret_present")),
        "api_callback_secret_present": bool(receipt.get("api_callback_secret_present")),
        "state_fresh": bool(receipt.get("state_fresh")),
        "state_age_seconds": int(receipt.get("state_age_seconds") or 0),
        "runtime_ready_claim_allowed": bool(receipt.get("runtime_ready_claim_allowed")),
        "live_delivery_claim_allowed": bool(receipt.get("live_delivery_claim_allowed")),
    }
    report = _normalize_whatsapp_readiness_action(report)
    if output_format == "operator":
        report["operator_text"] = _operator_text_for_whatsapp_readiness(report)
    return report


def _normalize_whatsapp_readiness_action(report: Mapping[str, object]) -> dict[str, object]:
    normalized = dict(report)
    next_action = str(normalized.get("next_action") or "").strip()
    sidecar_status = str(normalized.get("sidecar_status") or "").strip()
    qr_required = bool(normalized.get("sidecar_qr_required"))
    qr_present = bool(normalized.get("sidecar_qr_present"))
    if (
        (qr_required or qr_present or sidecar_status == "qr_required")
        and next_action in {"", "restore_whatsapp_web_session_sidecar_readiness"}
    ):
        normalized["receipt_next_action"] = next_action
        normalized["next_action"] = "scan_whatsapp_web_qr"
    return normalized


def _operator_text_for_whatsapp_action_processor_repair(report: Mapping[str, object]) -> str:
    pieces = [
        f"whatsapp_action_processor_repair status={report.get('status') or 'unknown'}",
        f"repaired={str(bool(report.get('repaired'))).lower()}",
    ]
    if report.get("reason"):
        pieces.append(f"reason={report['reason']}")
    if report.get("next_action"):
        pieces.append(f"next={report['next_action']}")
    if report.get("compose_file"):
        pieces.append(f"compose={report['compose_file']}")
    if report.get("service"):
        pieces.append(f"service={report['service']}")
    if report.get("start_exit_code") is not None:
        pieces.append(f"start_exit={int(report.get('start_exit_code') or 0)}")
    if report.get("fallback_exit_code") is not None:
        pieces.append(f"fallback_exit={int(report.get('fallback_exit_code') or 0)}")
    if report.get("processor_container_enabled") is not None:
        pieces.append(f"processor={str(bool(report.get('processor_container_enabled'))).lower()}")
    if report.get("sidecar_status"):
        pieces.append(f"sidecar={report['sidecar_status']}")
    if report.get("observed_at"):
        pieces.append(f"observed_at={report['observed_at']}")
    return "; ".join(str(item) for item in pieces if str(item).strip())


def repair_whatsapp_action_processor(
    *,
    compose_file: str = "",
    service: str = "",
    dry_run: bool = False,
    timeout_seconds: float = 60.0,
    output_format: str = "json",
) -> dict[str, object]:
    observed_at = _utc_now()
    effective_compose_file = str(compose_file or DEFAULT_WHATSAPP_WEB_COMPOSE_FILE).strip()
    effective_service = str(service or DEFAULT_WHATSAPP_WEB_ACTION_PROCESSOR_SERVICE).strip()
    before = _normalize_whatsapp_readiness_action(
        probe_whatsapp_readiness(refresh=True, output_format="json", volatile=True)
    )
    if dry_run:
        report = {
            "probe_ok": True,
            "status": "dry_run",
            "ready": bool(before.get("ready")),
            "repaired": False,
            "reason": "dry_run",
            "next_action": str(before.get("next_action") or "").strip(),
            "compose_file": effective_compose_file,
            "service": effective_service,
            "before_status": str(before.get("status") or "").strip(),
            "before_reason": str(before.get("reason") or "").strip(),
            "processor_container_enabled": bool(before.get("processor_container_enabled")),
            "sidecar_status": str(before.get("sidecar_status") or "").strip(),
            "observed_at": observed_at,
            "source": "docker_compose_repair:whatsapp_action_processor",
        }
        if output_format == "operator":
            report["operator_text"] = _operator_text_for_whatsapp_action_processor_repair(report)
        return report

    start_result = _docker_compose_service_command(
        compose_file=effective_compose_file,
        command=["start", effective_service],
        timeout_seconds=timeout_seconds,
    )
    fallback_result: dict[str, object] = {}
    if not bool(start_result.get("ok")):
        fallback_result = _docker_compose_service_command(
            compose_file=effective_compose_file,
            command=["up", "-d", "--no-deps", effective_service],
            timeout_seconds=timeout_seconds,
        )
    after = _normalize_whatsapp_readiness_action(
        probe_whatsapp_readiness(refresh=True, output_format="json", volatile=True)
    )
    processor_enabled = bool(after.get("processor_container_enabled"))
    command_ok = bool(start_result.get("ok")) or bool(fallback_result.get("ok"))
    repaired = bool(command_ok and processor_enabled)
    if repaired and bool(after.get("ready")):
        status = "repaired"
    elif repaired:
        status = "repaired_with_actions"
    else:
        status = "repair_failed"
    reason = "" if repaired else str(fallback_result.get("reason") or start_result.get("reason") or after.get("reason") or "").strip()
    report = {
        "probe_ok": command_ok,
        "status": status,
        "ready": bool(after.get("ready")),
        "repaired": repaired,
        "reason": reason,
        "next_action": str(after.get("next_action") or "").strip(),
        "compose_file": effective_compose_file,
        "service": effective_service,
        "before_status": str(before.get("status") or "").strip(),
        "before_reason": str(before.get("reason") or "").strip(),
        "after_status": str(after.get("status") or "").strip(),
        "after_reason": str(after.get("reason") or "").strip(),
        "start_exit_code": int(start_result.get("exit_code") or 0),
        "start_stdout_present": bool(start_result.get("stdout_present")),
        "start_stderr_present": bool(start_result.get("stderr_present")),
        "fallback_attempted": bool(fallback_result),
        "fallback_exit_code": int(fallback_result.get("exit_code") or 0) if fallback_result else None,
        "fallback_stdout_present": bool(fallback_result.get("stdout_present")) if fallback_result else False,
        "fallback_stderr_present": bool(fallback_result.get("stderr_present")) if fallback_result else False,
        "processor_container_enabled": processor_enabled,
        "sidecar_status": str(after.get("sidecar_status") or "").strip(),
        "state_fresh": bool(after.get("state_fresh")),
        "observed_at": observed_at,
        "source": "docker_compose_repair:whatsapp_action_processor",
    }
    if output_format == "operator":
        report["operator_text"] = _operator_text_for_whatsapp_action_processor_repair(report)
    return report


def probe_proactive_route(
    *,
    principal_id: str,
    compose_file: str = "",
    runtime_service: str = "",
    receipt_path: str = "",
    timeout_seconds: float = 60.0,
    include_artifact_probe: bool = True,
    output_format: str = "json",
) -> dict[str, object]:
    effective_compose_file = str(compose_file or _env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE))).strip()
    effective_runtime_service = str(runtime_service or _env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE)).strip()
    effective_timeout_seconds = max(float(timeout_seconds or 60.0), 1.0)
    live_receipt_timeout_reserve = min(max(effective_timeout_seconds * 0.1, 1.0), 5.0)
    route_artifact_budget_seconds = max(effective_timeout_seconds - live_receipt_timeout_reserve, 1.0)
    route_artifact_deadline = time.monotonic() + route_artifact_budget_seconds
    probe_deadline = route_artifact_deadline + live_receipt_timeout_reserve
    observed_at = _utc_now()
    artifact_probe: dict[str, object] = {}
    route_source = "docker_compose_exec"
    if not effective_compose_file or not effective_runtime_service:
        next_action = "configure_proactive_runtime_probe"
        report = {
            "probe_ok": False,
            "status": "probe_failed",
            "principal_id": str(principal_id or "").strip(),
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": "runtime_probe_configuration_missing",
            "next_action": next_action,
            "route_report": {},
            "live_receipt": {},
            "live_receipt_checked": False,
        }
        report.update(_next_action_surface_fields(next_action))
        if output_format == "operator":
            report["operator_text"] = "proactive route probe failed; configure runtime probe inputs"
        return report

    route_command = [
        sys.executable if _prefer_host_runtime_proactive_probe() else "python",
        str(ROOT / "scripts" / "verify_proactive_ooda.py") if _prefer_host_runtime_proactive_probe() else "/app/scripts/verify_proactive_ooda.py",
        "--principal-id",
        str(principal_id or "").strip(),
        "--skip-observation-source",
        "--skip-workspace-source",
        "--no-require-source",
        "--no-require-telegram",
        "--delivery-route-mode",
        "lightweight",
    ]
    if _prefer_host_runtime_proactive_probe():
        route_source = "host_python_exec"
        route_code, route_payload, route_stdout, route_stderr = _host_python_exec_json(
            command=route_command,
            timeout_seconds=_remaining_probe_timeout(route_artifact_deadline),
        )
    else:
        route_code, route_payload, route_stdout, route_stderr = _docker_compose_exec_json(
            compose_file=effective_compose_file,
            service=effective_runtime_service,
            command=route_command,
            timeout_seconds=_remaining_probe_timeout(route_artifact_deadline),
        )
    if bool(route_payload.get("timed_out")):
        next_action = "inspect_proactive_runtime_container"
        reason = str(route_payload.get("reason") or f"TimeoutExpired:{float(timeout_seconds):g}s").strip()
        report = {
            "probe_ok": False,
            "status": "probe_failed",
            "principal_id": str(principal_id or "").strip(),
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": route_source,
            "blocking_reason": f"runtime_route_probe_timed_out:{reason}",
            "next_action": next_action,
            "route_report": {},
            "live_receipt": {},
            "live_receipt_checked": False,
            "timed_out": True,
            "timeout_seconds": float(route_payload.get("timeout_seconds") or effective_timeout_seconds),
            "stderr_excerpt": route_stderr.strip()[:200],
            "stdout_excerpt": route_stdout.strip()[:200],
        }
        report.update(_next_action_surface_fields(next_action))
        if output_format == "operator":
            report["operator_text"] = f"proactive route probe timed out; inspect {effective_runtime_service}"
        return report
    if not route_payload:
        next_action = "inspect_proactive_runtime_container"
        report = {
            "probe_ok": False,
            "status": "probe_failed",
            "principal_id": str(principal_id or "").strip(),
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": route_source,
            "blocking_reason": f"runtime_route_probe_failed:exit_{route_code}",
            "next_action": next_action,
            "route_report": {},
            "live_receipt": {},
            "live_receipt_checked": False,
            "stderr_excerpt": route_stderr.strip()[:200],
            "stdout_excerpt": route_stdout.strip()[:200],
        }
        report.update(_next_action_surface_fields(next_action))
        if output_format == "operator":
            report["operator_text"] = f"proactive route probe failed; inspect {effective_runtime_service}"
        return report

    effective_receipt_path = str(receipt_path or "").strip()
    receipt_command = [
        "python",
        "/app/scripts/verify_proactive_ooda_live_receipt.py",
    ]
    if effective_receipt_path:
        receipt_command.extend(["--receipt-path", effective_receipt_path])
    if _probe_deadline_expired(probe_deadline):
        live_receipt_payload = {
            "ok": False,
            "receipt_path": effective_receipt_path,
            "notification_status": "probe_skipped",
            "delivery_channel": "",
            "delivery_next_action": "inspect_proactive_runtime_container",
            "delivery_route_error": "",
            "delivery_recovery_hint": "",
            "errors": [f"TimeoutExpired:{effective_timeout_seconds:g}s"],
            "timed_out": True,
            "timeout_seconds": effective_timeout_seconds,
        }
    else:
        if _prefer_host_runtime_proactive_probe():
            _, live_receipt_payload, _, _ = _host_python_exec_json(
                command=[
                    sys.executable,
                    str(ROOT / "scripts" / "verify_proactive_ooda_live_receipt.py"),
                    *([] if not effective_receipt_path else ["--receipt-path", effective_receipt_path]),
                ],
                timeout_seconds=_remaining_probe_timeout(probe_deadline),
            )
        else:
            _, live_receipt_payload, _, _ = _docker_compose_exec_json(
                compose_file=effective_compose_file,
                service=effective_runtime_service,
                command=receipt_command,
                timeout_seconds=_remaining_probe_timeout(probe_deadline),
            )
    live_receipt_timed_out = bool(live_receipt_payload.get("timed_out"))
    if live_receipt_timed_out:
        live_receipt_payload = {
            "ok": False,
            "receipt_path": effective_receipt_path,
            "notification_status": "probe_timed_out",
            "delivery_channel": "",
            "delivery_next_action": "inspect_proactive_runtime_container",
            "delivery_route_error": "",
            "delivery_recovery_hint": "",
            "errors": [str(live_receipt_payload.get("reason") or f"TimeoutExpired:{effective_timeout_seconds:g}s").strip()],
            "timed_out": True,
            "timeout_seconds": float(live_receipt_payload.get("timeout_seconds") or effective_timeout_seconds),
        }
    if not include_artifact_probe:
        artifact_probe = {}
    elif _probe_deadline_expired(probe_deadline):
        artifact_probe = {
            "probe_ok": False,
            "status": "probe_skipped",
            "source": "docker_compose_exec",
            "blocking_reason": f"runtime_artifact_probe_skipped:live_probe_budget_exhausted:{effective_timeout_seconds:g}s",
            "timed_out": True,
            "timeout_seconds": effective_timeout_seconds,
        }
    else:
        try:
            artifact_probe = probe_proactive_artifacts(
                compose_file=effective_compose_file,
                runtime_service=effective_runtime_service,
                timeout_seconds=_remaining_probe_timeout(probe_deadline),
                output_format="json",
            )
        except Exception:
            artifact_probe = {}
    if not effective_receipt_path:
        if bool(artifact_probe.get("probe_ok")) and str(artifact_probe.get("run_receipt_path") or "").strip():
            effective_receipt_path = str(artifact_probe.get("run_receipt_path") or "").strip()
        elif not str(live_receipt_payload.get("receipt_path") or "").strip():
            live_receipt_payload["receipt_path"] = effective_receipt_path
    route_payload = _reconcile_route_payload_with_live_receipt(
        route_payload=route_payload,
        live_receipt_payload=live_receipt_payload,
    )
    delivery_route = dict(route_payload.get("delivery_route") or {})
    delivery_guard = dict(route_payload.get("delivery_guard") or {})
    runtime_errors = [str(item).strip() for item in list(route_payload.get("errors") or []) if str(item).strip()]
    if live_receipt_timed_out:
        runtime_errors.append("live_receipt_probe_timed_out")
    route_ready = bool(delivery_route.get("ready"))
    route_error = str(delivery_route.get("route_error") or "").strip()
    delivery_state = str(delivery_guard.get("delivery_state") or "").strip()
    deferred_reason = str(delivery_guard.get("deferred_reason") or "").strip()
    only_live_receipt_timeout = (
        route_ready
        and not route_error
        and route_payload.get("ok") is not False
        and runtime_errors == ["live_receipt_probe_timed_out"]
    )
    live_receipt_recovery_error = _live_receipt_runtime_recovery_error(live_receipt_payload)
    if delivery_state == "deferred":
        status = "deferred"
    elif runtime_errors or route_payload.get("ok") is False:
        status = "ready_with_recovery_action" if only_live_receipt_timeout else "blocked_local_runtime"
    elif live_receipt_recovery_error:
        status = "ready_with_recovery_action" if route_ready and not route_error else "blocked_local_runtime"
    elif route_ready and route_error:
        status = "ready_with_recovery_action"
    elif route_ready:
        status = "ready"
    else:
        status = "blocked"
    followthrough_next_action = _proactive_approval_followthrough_next_action(
        artifact_probe=artifact_probe,
        route_ready=route_ready,
        selected_channel=str(delivery_route.get("selected_channel") or "").strip(),
        live_receipt_payload=live_receipt_payload,
    )
    route_next_action = str(delivery_route.get("next_action") or "").strip()
    guard_next_action = _proactive_guard_next_action(deferred_reason)
    runtime_next_action = _proactive_runtime_error_next_action(runtime_errors)
    live_receipt_next_action = str(live_receipt_payload.get("delivery_next_action") or "").strip()
    if delivery_state == "deferred":
        next_action = str(
            guard_next_action
            or route_next_action
            or runtime_next_action
            or live_receipt_next_action
            or "inspect_proactive_delivery_route"
        ).strip()
    elif runtime_errors or route_payload.get("ok") is False:
        next_action = str(
            runtime_next_action
            or route_next_action
            or live_receipt_next_action
            or "repair_proactive_runtime_inputs"
        ).strip()
    elif live_receipt_recovery_error:
        next_action = str(
            live_receipt_next_action
            or _proactive_runtime_error_next_action([live_receipt_recovery_error])
            or "repair_proactive_runtime_inputs"
        ).strip()
    else:
        ready_default_action = (
            ""
            if status == "ready" and bool(live_receipt_payload.get("ok"))
            else "inspect_proactive_delivery_route"
        )
        next_action = str(
            followthrough_next_action
            or route_next_action
            or guard_next_action
            or runtime_next_action
            or live_receipt_next_action
            or ready_default_action
        ).strip()
    blocking_reason = str(
        route_error
        or deferred_reason
        or (runtime_errors[0] if runtime_errors else "")
        or live_receipt_recovery_error
        or ""
    ).strip()
    report = {
        "probe_ok": True,
        "status": status,
        "principal_id": str(principal_id or "").strip(),
        "compose_file": effective_compose_file,
        "runtime_service": effective_runtime_service,
        "observed_at": observed_at,
        "source": route_source,
        "delivery_route_ready": route_ready,
        "selected_channel": str(delivery_route.get("selected_channel") or "").strip(),
        "selected_transport": str(delivery_route.get("selected_transport") or "").strip(),
        "selected_by": str(delivery_route.get("selected_by") or "").strip(),
        "available_channels": [str(item or "").strip() for item in list(delivery_route.get("available_channels") or []) if str(item or "").strip()],
        "blocking_reason": blocking_reason,
        "recovery_hint": str(delivery_route.get("recovery_hint") or "").strip(),
        "next_action": next_action,
        "approval_capture_surface_ready": bool(artifact_probe.get("current_packet_live_pending_count") or 0) > 0,
        "approval_capture_surface_pending_count": int(artifact_probe.get("current_packet_live_pending_count") or 0),
        "route_report": route_payload,
        "artifact_probe": artifact_probe,
        "live_receipt": live_receipt_payload,
        "live_receipt_checked": bool(live_receipt_payload),
    }
    report.update(_next_action_surface_fields(next_action))
    if output_format == "operator":
        route_label = str(delivery_route.get("selected_channel") or "none").strip() or "none"
        recovery = str(delivery_route.get("recovery_hint") or "").strip()
        tail = f"; next={next_action}" if next_action else ""
        if recovery:
            tail = f"{tail}; recovery={recovery}"
        report["operator_text"] = (
            f"proactive_route status={status}; route={route_label}; "
            f"ready={str(route_ready).lower()}; source={route_source}{tail}"
        )
    return report


def _reconcile_route_payload_with_live_receipt(
    *,
    route_payload: Mapping[str, object],
    live_receipt_payload: Mapping[str, object],
) -> dict[str, object]:
    payload = dict(route_payload or {})
    if not _live_receipt_proves_delivery_route(live_receipt_payload):
        return payload
    route = dict(payload.get("delivery_route") or {})
    route_error = str(route.get("route_error") or "").strip()
    if bool(route.get("ready")) and not route_error:
        return payload
    selected_channel = _live_receipt_selected_channel(live_receipt_payload)
    selected_transport = selected_channel or "telegram"
    live_route = dict(route)
    live_route.update(
        {
            "ready": True,
            "selected_channel": selected_channel,
            "selected_transport": selected_transport,
            "selected_by": str(route.get("selected_by") or "").strip() or "live_receipt",
            "selected_reason": (
                str(route.get("selected_reason") or "").strip()
                or "Latest host-visible live receipt proves delivery succeeded."
            ),
            "available_channels": _merged_nonempty_text_list(route.get("available_channels"), [selected_channel]),
            "errors": [
                item
                for item in [str(entry).strip() for entry in list(route.get("errors") or []) if str(entry).strip()]
                if item != "telegram_notification_not_configured"
            ],
            "route_error": "",
            "recovery_hint": "",
            "next_action": "",
        }
    )
    payload["delivery_route"] = live_route
    warnings = [str(item).strip() for item in list(payload.get("warnings") or []) if str(item).strip()]
    note = "live_receipt_route_override_applied"
    if note not in warnings:
        warnings.append(note)
    payload["warnings"] = warnings
    return payload


def _live_receipt_proves_delivery_route(live_receipt_payload: Mapping[str, object]) -> bool:
    payload = dict(live_receipt_payload or {})
    if not bool(payload.get("ok")):
        return False
    if str(payload.get("delivery_mode") or "").strip() != "telegram_sent":
        return False
    if int(payload.get("delivery_message_count") or 0) < 1 and int(payload.get("telegram_message_count") or 0) < 1:
        return False
    return bool(_live_receipt_selected_channel(payload))


def _live_receipt_selected_channel(live_receipt_payload: Mapping[str, object]) -> str:
    payload = dict(live_receipt_payload or {})
    channel = str(payload.get("delivery_channel") or "").strip().lower()
    if channel:
        return channel
    if int(payload.get("telegram_message_count") or 0) > 0:
        return "telegram"
    return ""


def _merged_nonempty_text_list(*values: object) -> list[str]:
    ordered: list[str] = []
    for value in values:
        items = value if isinstance(value, (list, tuple, set)) else [value]
        for item in items:
            normalized = str(item or "").strip()
            if normalized and normalized not in ordered:
                ordered.append(normalized)
    return ordered


def _proactive_guard_next_action(reason: str) -> str:
    normalized = str(reason or "").strip()
    if normalized == "deferred_by_operator_pause":
        return "clear_proactive_operator_pause"
    if normalized == "deferred_by_quiet_hours":
        return "resume_after_quiet_hours"
    if normalized == "deferred_by_interruption_budget":
        return "wait_for_interruption_budget_window"
    if normalized == "deferred_by_unarmed_send":
        return "arm_proactive_send_for_live_delivery"
    return ""


def _proactive_runtime_error_next_action(errors: list[str]) -> str:
    first = str(errors[0] if errors else "").strip()
    if first.startswith("google_workspace_signal_source_unhealthy:"):
        return "reauthorize_google_workspace_binding"
    if first.startswith("followthrough_"):
        return "repair_proactive_operator_runtime_posture"
    if first:
        return "repair_proactive_runtime_inputs"
    return ""


def _live_receipt_runtime_recovery_error(live_receipt_payload: Mapping[str, object]) -> str:
    if bool(live_receipt_payload.get("ok")):
        return ""
    for item in [str(entry).strip() for entry in list(live_receipt_payload.get("errors") or []) if str(entry).strip()]:
        if item.startswith("followthrough_"):
            return item
    return ""


def _next_action_surface_fields(action: str) -> dict[str, str]:
    surface = proactive_next_action_surface(action)
    normalized = str(action or "").strip()
    if normalized == "review_proactive_draft_queue" and not any(
        str(surface.get(key) or "").strip() for key in ("href", "label", "method")
    ):
        surface = {"href": "/app/queue", "label": "Open queue", "method": "get"}
    return {
        "next_action_href": str(surface.get("href") or "").strip(),
        "next_action_label": str(surface.get("label") or "").strip(),
        "next_action_method": str(surface.get("method") or "").strip(),
    }


def _proactive_approval_followthrough_next_action(
    *,
    artifact_probe: Mapping[str, object],
    route_ready: bool,
    selected_channel: str,
    live_receipt_payload: Mapping[str, object],
) -> str:
    if not route_ready:
        return ""
    if str(selected_channel or "").strip() != "telegram":
        return ""
    if not bool(live_receipt_payload.get("ok")):
        return ""
    if int(artifact_probe.get("current_packet_live_pending_count") or 0) <= 0:
        return ""
    return "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"


def _sha256_text(value: str) -> str:
    normalized = str(value or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def _approval_outcome_matches_current_packet(
    *,
    approval_outcome: Mapping[str, object],
    stage_packet: Mapping[str, object],
    safe_work_result: Mapping[str, object],
) -> bool:
    if not bool(approval_outcome.get("approval_outcome_recorded")):
        return False
    packet_ref = _proactive_stage_packet_ref(stage_packet)
    staged_artifact_ref = _proactive_staged_artifact_ref(safe_work_result)
    expected_packet_hash = _sha256_text(packet_ref)
    expected_artifact_hash = _sha256_text(staged_artifact_ref)
    outcome_packet_hash = str(approval_outcome.get("packet_ref_sha256") or "").strip()
    outcome_artifact_hash = str(approval_outcome.get("staged_artifact_sha256") or "").strip()
    if not outcome_packet_hash and not outcome_artifact_hash:
        return False
    if outcome_packet_hash and outcome_packet_hash != expected_packet_hash:
        return False
    if outcome_artifact_hash and outcome_artifact_hash != expected_artifact_hash:
        return False
    return bool((outcome_packet_hash and expected_packet_hash) or (outcome_artifact_hash and expected_artifact_hash))


def _proactive_current_packet_summary(
    *,
    stage_packet: Mapping[str, object],
    safe_work_result: Mapping[str, object],
    approval_outcome: Mapping[str, object],
    current_packet_callback_outcome: Mapping[str, object] | None = None,
    current_packet_live_pending_count: int,
    current_packet_callback_record_count: int,
    current_packet_callback_latest_status: str,
) -> dict[str, object]:
    stage = dict(stage_packet.get("stage") or {}) if isinstance(stage_packet, Mapping) else {}
    stage_payload = dict(stage.get("payload") or {}) if isinstance(stage.get("payload"), Mapping) else {}
    recommended = dict(safe_work_result.get("recommended_option_or_draft") or {}) if isinstance(safe_work_result, Mapping) else {}
    recommended_value = dict(recommended.get("value") or {}) if isinstance(recommended.get("value"), Mapping) else {}
    shortlist = [dict(row) for row in list(safe_work_result.get("shortlist") or []) if isinstance(row, Mapping)]
    outcome_recorded = _approval_outcome_matches_current_packet(
        approval_outcome=approval_outcome,
        stage_packet=stage_packet,
        safe_work_result=safe_work_result,
    )
    if not outcome_recorded and current_packet_callback_outcome:
        outcome_recorded = _approval_outcome_matches_current_packet(
            approval_outcome=current_packet_callback_outcome,
            stage_packet=stage_packet,
            safe_work_result=safe_work_result,
        )
    if outcome_recorded:
        status = str(approval_outcome.get("status") or "recorded").strip() or "recorded"
    elif int(current_packet_live_pending_count or 0) > 0:
        status = "pending_approval"
    elif int(current_packet_callback_record_count or 0) > 0:
        status = str(current_packet_callback_latest_status or "callback_recorded").strip() or "callback_recorded"
    elif stage_packet or safe_work_result:
        status = "staged"
    else:
        status = "missing"
    recommended_label = _compact_text(
        recommended_value.get("label")
        or recommended_value.get("title")
        or recommended.get("value")
        or "",
        limit=80,
    )
    recommended_url = _compact_text(
        recommended_value.get("final_url")
        or recommended_value.get("url")
        or recommended_value.get("link")
        or safe_work_result.get("staged_action_url")
        or stage_payload.get("approval_url")
        or "",
        limit=180,
    )
    return {
        "present": bool(stage_packet or safe_work_result),
        "status": status,
        "packet_ref": _proactive_stage_packet_ref(stage_packet),
        "staged_artifact_ref": _proactive_staged_artifact_ref(safe_work_result),
        "observe": _compact_text(stage_packet.get("observe"), limit=160),
        "decide": _compact_text(stage_packet.get("decide"), limit=160),
        "act": _compact_text(stage_packet.get("act"), limit=160),
        "stage_kind": _compact_text(stage.get("kind"), limit=60),
        "stage_summary": _compact_text(stage.get("summary") or safe_work_result.get("summary"), limit=180),
        "approval_prompt": _compact_text(
            safe_work_result.get("approval_prompt")
            or stage_payload.get("approval_prompt")
            or "",
            limit=220,
        ),
        "recommended_label": recommended_label,
        "recommended_url": recommended_url,
        "staged_action_url": _compact_text(
            safe_work_result.get("staged_action_url")
            or stage_payload.get("approval_url")
            or "",
            limit=180,
        ),
        "shortlist_count": len(shortlist),
        "approval_outcome_matches_current_packet": outcome_recorded,
    }


def probe_proactive_artifacts(
    *,
    compose_file: str = "",
    runtime_service: str = "",
    timeout_seconds: float = 60.0,
    output_format: str = "json",
    prefer_browse_backed_delivery: bool = False,
    prefer_host_runtime: bool = False,
) -> dict[str, object]:
    effective_compose_file = str(compose_file or _env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE))).strip()
    effective_runtime_service = str(runtime_service or _env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE)).strip()
    observed_at = _utc_now()
    if not effective_compose_file or not effective_runtime_service:
        report = {
            "probe_ok": False,
            "status": "probe_failed",
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": "runtime_probe_configuration_missing",
        }
        if output_format == "operator":
            report["operator_text"] = "proactive artifact probe failed; configure runtime probe inputs"
        return report

    command = [
        "python",
        "-c",
        (
            "import json, os\n"
            "from datetime import datetime, timezone\n"
            "from pathlib import Path\n"
            "from app.services.proactive_ooda_runtime_artifacts import load_runtime_artifact_bundle\n"
            "from app.services.proactive_ooda_telegram_approval import default_proactive_ooda_telegram_approval_callback_dir\n"
            "root = Path('/app')\n"
            "state_path = os.getenv('EA_PROACTIVE_OODA_STATE_PATH') or '/data/provider-ledger/proactive_ooda_notified.json'\n"
            "receipt_path = os.getenv('EA_PROACTIVE_OODA_RECEIPT_PATH') or ''\n"
            "stage_packet_dir = os.getenv('EA_PROACTIVE_OODA_STAGE_PACKET_DIR') or ''\n"
            "safe_work_result_dir = os.getenv('EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR') or ''\n"
            f"prefer_browse_backed_delivery = {bool(prefer_browse_backed_delivery)!r}\n"
            "bundle = load_runtime_artifact_bundle(root=root, state_path=state_path, receipt_path=receipt_path, stage_packet_dir=stage_packet_dir, safe_work_result_dir=safe_work_result_dir, prefer_browse_backed_delivery=prefer_browse_backed_delivery)\n"
            "callback_dir = default_proactive_ooda_telegram_approval_callback_dir(root=root, state_path=state_path, receipt_path=receipt_path)\n"
            "def _text(path):\n"
            "    return '' if path is None else path.as_posix()\n"
            "def _dir_writable(path):\n"
            "    probe = path if path.exists() else path.parent\n"
            "    while not probe.exists() and probe != probe.parent:\n"
            "        probe = probe.parent\n"
            "    try:\n"
            "        return os.access(probe, os.W_OK)\n"
            "    except Exception:\n"
            "        return False\n"
            "def _expires_at_ts(value):\n"
            "    text = str(value or '').strip()\n"
            "    if not text:\n"
            "        return 0.0\n"
            "    if text.endswith('Z'):\n"
            "        text = text[:-1] + '+00:00'\n"
            "    try:\n"
            "        return datetime.fromisoformat(text).timestamp()\n"
            "    except Exception:\n"
            "        return 0.0\n"
            "now_ts = datetime.now(timezone.utc).timestamp()\n"
            "def _is_live(row):\n"
            "    expires = _expires_at_ts(row.get('expires_at'))\n"
            "    return expires <= 0.0 or expires > now_ts\n"
            "def _is_live_pending(row):\n"
            "    return str(row.get('status') or '').strip() == 'pending' and _is_live(row)\n"
            "def _status(row):\n"
            "    return str(row.get('status') or '').strip().lower()\n"
            "def _matches_current(row):\n"
            "    return (\n"
            "        bool(current_packet_ref and current_artifact_ref)\n"
            "        and str(row.get('packet_ref') or '').strip() == current_packet_ref\n"
            "        and str(row.get('staged_artifact_ref') or '').strip() == current_artifact_ref\n"
            "    )\n"
            "callback_rows = []\n"
            "if callback_dir.is_dir():\n"
            "    for candidate in callback_dir.glob('*.json'):\n"
            "        try:\n"
            "            payload = json.loads(candidate.read_text(encoding='utf-8'))\n"
            "        except Exception:\n"
            "            continue\n"
            "        if isinstance(payload, dict):\n"
            "            callback_rows.append(payload)\n"
            "stage_packet = dict(bundle.get('stage_packet') or {})\n"
            "safe_work_result = dict(bundle.get('safe_work_result') or {})\n"
            "current_packet_ref = str(stage_packet.get('packet_ref') or stage_packet.get('packet_id') or '').strip()\n"
            "current_artifact_ref = str(safe_work_result.get('result_ref') or '').strip()\n"
            "if not current_artifact_ref:\n"
            "    result_id = str(safe_work_result.get('result_id') or '').strip()\n"
            "    current_artifact_ref = f'safe_work_result:{result_id}' if result_id else ''\n"
            "current_packet_rows = [\n"
            "    row for row in callback_rows\n"
            "    if str(row.get('packet_ref') or '').strip() == current_packet_ref\n"
            "    and str(row.get('staged_artifact_ref') or '').strip() == current_artifact_ref\n"
            "]\n"
            "if int(bundle.get('current_packet_live_pending_count') or 0) <= 0:\n"
            "    current_packet_rows = []\n"
            "current_packet_rows.sort(key=lambda row: str(row.get('created_at') or ''))\n"
            "current_packet_latest = current_packet_rows[-1] if current_packet_rows else {}\n"
            "def _parse_dt(value):\n"
            "    text = str(value or '').strip()\n"
            "    if not text:\n"
            "        return None\n"
            "    normalized = text[:-1] + '+00:00' if text.endswith('Z') else text\n"
            "    try:\n"
            "        parsed = datetime.fromisoformat(normalized)\n"
            "    except Exception:\n"
            "        return None\n"
            "    if parsed.tzinfo is None:\n"
            "        parsed = parsed.replace(tzinfo=timezone.utc)\n"
            "    return parsed.astimezone(timezone.utc)\n"
            "def _age_seconds(value):\n"
            "    parsed = _parse_dt(value)\n"
            "    return max(int((datetime.now(timezone.utc) - parsed).total_seconds()), 0) if parsed else 0\n"
            "def _seconds_until(value):\n"
            "    parsed = _parse_dt(value)\n"
            "    return max(int((parsed - datetime.now(timezone.utc)).total_seconds()), 0) if parsed else 0\n"
            "current_latest_created_at = str(current_packet_latest.get('created_at') or '').strip()\n"
            "current_latest_expires_at = str(current_packet_latest.get('expires_at') or '').strip()\n"
            "pending_rows = [row for row in callback_rows if _status(row) == 'pending']\n"
            "current_live_pending_rows = [row for row in current_packet_rows if _is_live_pending(row)]\n"
            "unexpired_pending_rows = [row for row in pending_rows if _is_live(row)]\n"
            "expired_pending_rows = [row for row in pending_rows if not _is_live(row)]\n"
            "noncurrent_pending_rows = [row for row in pending_rows if not _matches_current(row)]\n"
            "stale_pending_rows = [row for row in pending_rows if (not _is_live(row)) or (not _matches_current(row))]\n"
            "recorded_rows = [row for row in callback_rows if _status(row) in ('approved','rejected','deferred','dismissed')]\n"
            "expired_rows = [row for row in callback_rows if _status(row) == 'expired']\n"
            "superseded_rows = [row for row in callback_rows if _status(row) == 'superseded']\n"
            "terminal_rows = [row for row in callback_rows if _status(row) in ('approved','rejected','deferred','dismissed','expired','superseded')]\n"
            "current_pending_rows = [row for row in current_packet_rows if _status(row) == 'pending']\n"
            "current_expired_pending_rows = [row for row in current_pending_rows if not _is_live(row)]\n"
            "current_expired_rows = [row for row in current_packet_rows if _status(row) == 'expired']\n"
            "current_superseded_rows = [row for row in current_packet_rows if _status(row) == 'superseded']\n"
            "print(json.dumps({\n"
            "  'probe_ok': True,\n"
            "  'prefer_browse_backed_delivery': prefer_browse_backed_delivery,\n"
            "  'state_path': _text(bundle.get('state_path')),\n"
            "  'run_receipt_path': _text(bundle.get('run_receipt_path')),\n"
            "  'action_required_only_quiet_receipt_path': _text(bundle.get('action_required_only_quiet_receipt_path')),\n"
            "  'stage_packet_dir': _text(bundle.get('stage_packet_dir')),\n"
            "  'safe_work_result_dir': _text(bundle.get('safe_work_result_dir')),\n"
            "  'approval_outcome_path': _text(bundle.get('approval_outcome_path')),\n"
            "  'approval_callback_dir': _text(callback_dir),\n"
            "  'approval_callback_dir_exists': callback_dir.is_dir(),\n"
            "  'approval_callback_dir_writable': _dir_writable(callback_dir),\n"
            "  'approval_callback_record_count': len(callback_rows),\n"
            "  'approval_callback_pending_count': len(current_live_pending_rows),\n"
            "  'approval_callback_raw_pending_count': len(pending_rows),\n"
            "  'approval_callback_live_pending_count': len(current_live_pending_rows),\n"
            "  'approval_callback_unexpired_pending_count': len(unexpired_pending_rows),\n"
            "  'approval_callback_noncurrent_pending_count': len(noncurrent_pending_rows),\n"
            "  'approval_callback_expired_pending_count': len(expired_pending_rows),\n"
            "  'approval_callback_stale_pending_count': len(stale_pending_rows),\n"
            "  'approval_callback_recorded_count': len(recorded_rows),\n"
            "  'approval_callback_expired_count': len(expired_rows),\n"
            "  'approval_callback_superseded_count': len(superseded_rows),\n"
            "  'approval_callback_terminal_count': len(terminal_rows),\n"
            "  'current_packet_callback_record_count': len(current_packet_rows),\n"
            "  'current_packet_callback_pending_count': len(current_pending_rows),\n"
            "  'current_packet_callback_raw_pending_count': len(current_pending_rows),\n"
            "  'current_packet_callback_expired_pending_count': len(current_expired_pending_rows),\n"
            "  'current_packet_callback_stale_pending_count': len(current_expired_pending_rows),\n"
            "  'current_packet_callback_recorded_count': sum(1 for row in current_packet_rows if _status(row) in ('approved','rejected','deferred','dismissed')),\n"
            "  'current_packet_callback_expired_count': len(current_expired_rows),\n"
            "  'current_packet_callback_superseded_count': len(current_superseded_rows),\n"
            "  'current_packet_live_callback_record_count': sum(1 for row in current_packet_rows if _is_live(row)),\n"
            "  'current_packet_live_pending_count': sum(1 for row in current_packet_rows if _is_live_pending(row)),\n"
            "  'current_packet_callback_latest_status': str(current_packet_latest.get('status') or '').strip(),\n"
            "  'current_packet_callback_latest_expired': bool(current_packet_latest) and (not _is_live(current_packet_latest)),\n"
            "  'current_packet_callback_latest_created_at': current_latest_created_at,\n"
            "  'current_packet_callback_latest_expires_at': current_latest_expires_at,\n"
            "  'current_packet_callback_latest_age_seconds': _age_seconds(current_latest_created_at),\n"
            "  'current_packet_callback_latest_seconds_until_expiry': _seconds_until(current_latest_expires_at),\n"
            "  'current_packet_callback_outcome': bundle.get('current_packet_callback_outcome') or {},\n"
            "  'stage_packet_path': _text(bundle.get('stage_packet_path')),\n"
            "  'safe_work_result_path': _text(bundle.get('safe_work_result_path')),\n"
            "  'artifact_filter_reason': str(bundle.get('artifact_filter_reason') or '').strip(),\n"
            "  'flat_search_enabled': bool(bundle.get('flat_search_enabled')),\n"
            "  'run_receipt': bundle.get('run_receipt') or {},\n"
            "  'action_required_only_quiet_receipt': bundle.get('action_required_only_quiet_receipt') or {},\n"
            "  'stage_packet': bundle.get('stage_packet') or {},\n"
            "  'safe_work_result': bundle.get('safe_work_result') or {},\n"
            "  'approval_outcome': bundle.get('approval_outcome') or {},\n"
            "}, sort_keys=True))\n"
        ),
    ]
    source = "docker_compose_exec"
    use_host_runtime = False
    if not _env_truthy("EA_LIVE_OPS_FORCE_DOCKER_COMPOSE_EXEC", default=False):
        use_host_runtime = bool(prefer_host_runtime) or _prefer_host_runtime_proactive_probe()
    if use_host_runtime:
        source = "in_process_runtime"
        try:
            code = 0
            payload = _probe_proactive_artifacts_in_process_payload(
                prefer_browse_backed_delivery=prefer_browse_backed_delivery,
            )
            stdout = json.dumps(payload, sort_keys=True)
            stderr = ""
        except Exception as exc:
            code = 127
            payload = {}
            stdout = ""
            stderr = f"{type(exc).__name__}:{str(exc or '').strip()}"
    else:
        code, payload, stdout, stderr = _docker_compose_exec_json(
            compose_file=effective_compose_file,
            service=effective_runtime_service,
            command=command,
            timeout_seconds=timeout_seconds,
        )
    if bool(payload.get("timed_out")):
        reason = str(payload.get("reason") or f"TimeoutExpired:{float(timeout_seconds):g}s").strip()
        report = {
            "probe_ok": False,
            "status": "probe_failed",
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": source,
            "blocking_reason": f"runtime_artifact_probe_timed_out:{reason}",
            "timed_out": True,
            "timeout_seconds": float(payload.get("timeout_seconds") or timeout_seconds),
            "stdout_excerpt": stdout.strip()[:200],
            "stderr_excerpt": stderr.strip()[:200],
        }
        if output_format == "operator":
            report["operator_text"] = f"proactive artifact probe timed out; inspect {effective_runtime_service}"
        return report
    if not payload:
        report = {
            "probe_ok": False,
            "status": "probe_failed",
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": source,
            "blocking_reason": f"runtime_artifact_probe_failed:exit_{code}",
            "stdout_excerpt": stdout.strip()[:200],
            "stderr_excerpt": stderr.strip()[:200],
        }
        if output_format == "operator":
            report["operator_text"] = f"proactive artifact probe failed; inspect {effective_runtime_service}"
        return report

    report = {
        "probe_ok": True,
        "status": "ok",
        "prefer_browse_backed_delivery": bool(payload.get("prefer_browse_backed_delivery")),
        "compose_file": effective_compose_file,
        "runtime_service": effective_runtime_service,
        "observed_at": observed_at,
        "source": source,
        "state_path": str(payload.get("state_path") or "").strip(),
        "run_receipt_path": str(payload.get("run_receipt_path") or "").strip(),
        "action_required_only_quiet_receipt_path": str(payload.get("action_required_only_quiet_receipt_path") or "").strip(),
        "stage_packet_dir": str(payload.get("stage_packet_dir") or "").strip(),
        "safe_work_result_dir": str(payload.get("safe_work_result_dir") or "").strip(),
        "approval_outcome_path": str(payload.get("approval_outcome_path") or "").strip(),
        "approval_callback_dir": str(payload.get("approval_callback_dir") or "").strip(),
        "approval_callback_dir_exists": bool(payload.get("approval_callback_dir_exists")),
        "approval_callback_dir_writable": bool(payload.get("approval_callback_dir_writable")),
        "approval_callback_record_count": int(payload.get("approval_callback_record_count") or 0),
        "approval_callback_pending_count": int(payload.get("approval_callback_pending_count") or 0),
        "approval_callback_raw_pending_count": int(payload.get("approval_callback_raw_pending_count") or payload.get("approval_callback_pending_count") or 0),
        "approval_callback_live_pending_count": int(payload.get("approval_callback_live_pending_count") or payload.get("approval_callback_pending_count") or 0),
        "approval_callback_unexpired_pending_count": int(payload.get("approval_callback_unexpired_pending_count") or payload.get("approval_callback_live_pending_count") or 0),
        "approval_callback_noncurrent_pending_count": int(payload.get("approval_callback_noncurrent_pending_count") or 0),
        "approval_callback_expired_pending_count": int(payload.get("approval_callback_expired_pending_count") or 0),
        "approval_callback_stale_pending_count": int(payload.get("approval_callback_stale_pending_count") or 0),
        "approval_callback_recorded_count": int(payload.get("approval_callback_recorded_count") or 0),
        "approval_callback_expired_count": int(payload.get("approval_callback_expired_count") or 0),
        "approval_callback_superseded_count": int(payload.get("approval_callback_superseded_count") or 0),
        "approval_callback_terminal_count": int(payload.get("approval_callback_terminal_count") or 0),
        "current_packet_callback_record_count": int(payload.get("current_packet_callback_record_count") or 0),
        "current_packet_callback_pending_count": int(payload.get("current_packet_callback_pending_count") or 0),
        "current_packet_callback_raw_pending_count": int(
            payload.get("current_packet_callback_raw_pending_count") or payload.get("current_packet_callback_pending_count") or 0
        ),
        "current_packet_callback_expired_pending_count": int(payload.get("current_packet_callback_expired_pending_count") or 0),
        "current_packet_callback_stale_pending_count": int(payload.get("current_packet_callback_stale_pending_count") or 0),
        "current_packet_callback_recorded_count": int(payload.get("current_packet_callback_recorded_count") or 0),
        "current_packet_callback_expired_count": int(payload.get("current_packet_callback_expired_count") or 0),
        "current_packet_callback_superseded_count": int(payload.get("current_packet_callback_superseded_count") or 0),
        "current_packet_live_callback_record_count": int(payload.get("current_packet_live_callback_record_count") or 0),
        "current_packet_live_pending_count": int(payload.get("current_packet_live_pending_count") or 0),
        "current_packet_callback_latest_status": str(payload.get("current_packet_callback_latest_status") or "").strip(),
        "current_packet_callback_latest_expired": bool(payload.get("current_packet_callback_latest_expired")),
        "current_packet_callback_latest_created_at": str(payload.get("current_packet_callback_latest_created_at") or "").strip(),
        "current_packet_callback_latest_expires_at": str(payload.get("current_packet_callback_latest_expires_at") or "").strip(),
        "current_packet_callback_latest_age_seconds": int(payload.get("current_packet_callback_latest_age_seconds") or 0),
        "current_packet_callback_latest_seconds_until_expiry": int(
            payload.get("current_packet_callback_latest_seconds_until_expiry") or 0
        ),
        "current_packet_callback_outcome": dict(payload.get("current_packet_callback_outcome") or {}),
        "stage_packet_path": str(payload.get("stage_packet_path") or "").strip(),
        "safe_work_result_path": str(payload.get("safe_work_result_path") or "").strip(),
        "artifact_filter_reason": str(payload.get("artifact_filter_reason") or "").strip(),
        "flat_search_enabled": bool(payload.get("flat_search_enabled")),
        "run_receipt": dict(payload.get("run_receipt") or {}),
        "action_required_only_quiet_receipt": dict(payload.get("action_required_only_quiet_receipt") or {}),
        "stage_packet": dict(payload.get("stage_packet") or {}),
        "safe_work_result": dict(payload.get("safe_work_result") or {}),
        "approval_outcome": dict(payload.get("approval_outcome") or {}),
    }
    report["current_packet"] = _proactive_current_packet_summary(
        stage_packet=dict(report.get("stage_packet") or {}),
        safe_work_result=dict(report.get("safe_work_result") or {}),
        approval_outcome=dict(report.get("approval_outcome") or {}),
        current_packet_callback_outcome=dict(report.get("current_packet_callback_outcome") or {}),
        current_packet_live_pending_count=int(report.get("current_packet_live_pending_count") or 0),
        current_packet_callback_record_count=int(report.get("current_packet_callback_record_count") or 0),
        current_packet_callback_latest_status=str(report.get("current_packet_callback_latest_status") or "").strip(),
    )
    report["approval_outcome_matches_current_packet"] = bool(
        dict(report.get("current_packet") or {}).get("approval_outcome_matches_current_packet")
    )
    if output_format == "operator":
        current_packet = dict(report.get("current_packet") or {})
        detail_parts = [
            f"packet_status={str(current_packet.get('status') or '').strip() or 'missing'}",
        ]
        if str(current_packet.get("decide") or "").strip():
            detail_parts.append(f"decide={str(current_packet.get('decide') or '').strip()}")
        if str(current_packet.get("recommended_label") or "").strip():
            detail_parts.append(f"recommend={str(current_packet.get('recommended_label') or '').strip()}")
        if str(current_packet.get("staged_action_url") or "").strip():
            detail_parts.append(f"link={str(current_packet.get('staged_action_url') or '').strip()}")
        report["operator_text"] = (
            "proactive_artifacts "
            f"run_receipt={str(bool(report['run_receipt'])).lower()} "
            f"stage_packet={str(bool(report['stage_packet'])).lower()} "
            f"safe_work_result={str(bool(report['safe_work_result'])).lower()} "
            f"approval_outcome={str(bool(report['approval_outcome'])).lower()} "
            f"approval_outcome_current={str(bool(report['approval_outcome_matches_current_packet'])).lower()} "
            f"approval_surface={str(bool(report['approval_callback_dir_writable'] and report['approval_callback_dir'] and int(report['current_packet_live_pending_count']) > 0)).lower()} "
            f"callback_records={int(report['approval_callback_record_count'])} "
            f"callback_live_pending={int(report['approval_callback_live_pending_count'])} "
            f"callback_stale_pending={int(report['approval_callback_stale_pending_count'])} "
            f"callback_noncurrent_pending={int(report['approval_callback_noncurrent_pending_count'])} "
            f"callback_expired={int(report['approval_callback_expired_count'])} "
            f"callback_superseded={int(report['approval_callback_superseded_count'])} "
            f"current_packet_callbacks={int(report['current_packet_callback_record_count'])} "
            f"current_packet_live_pending={int(report['current_packet_live_pending_count'])} "
            + " ".join(detail_parts)
        )
    return report


def _proactive_action_required_quiet_probe_code(
    *,
    principal_id: str,
    root_path: str,
    ledger_dir: str,
) -> str:
    return "\n".join(
        (
            "import json, os, subprocess, sys",
            "from datetime import datetime, timezone",
            "from pathlib import Path",
            f"root = Path({json.dumps(str(root_path or '/app'))})",
            f"ledger_dir = Path({json.dumps(str(ledger_dir or '/data/provider-ledger'))})",
            f"principal_id = {json.dumps(str(principal_id or '').strip())}",
            "ledger_dir.mkdir(parents=True, exist_ok=True)",
            "signal_path = ledger_dir / 'proactive_ooda_action_required_quiet_probe_signals.generated.json'",
            "receipt_path = ledger_dir / 'proactive_ooda_action_required_quiet_probe.generated.json'",
            "source_ref = 'live_ops:action_required_quiet_probe:' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')",
            "signals = [{",
            "    'source_ref': source_ref,",
            "    'signal_type': 'opportunity',",
            "    'channel': 'assistant_opportunity',",
            "    'title': 'Decision needed for EA quiet-delivery proof',",
            "    'summary': 'Approve the internal proactive OODA delivery-policy proof. No external action is staged.',",
            "    'counterparty': 'EA',",
            "    'payload': {'tags': ['live_ops', 'action_required_only', 'quiet_delivery_probe']},",
            "}]",
            "signal_path.write_text(json.dumps(signals, ensure_ascii=True, sort_keys=True) + '\\n', encoding='utf-8')",
            "env = dict(os.environ)",
            "env['EA_PROACTIVE_OODA_PERSIST_RECEIPTS'] = '0'",
            "cmd = [",
            "    sys.executable, str(root / 'scripts' / 'run_proactive_ooda.py'),",
            "    '--principal-id', principal_id or 'principal-default',",
            "    '--signals-json', str(signal_path),",
            "    '--state-path', str(ledger_dir / 'proactive_ooda_notified.json'),",
            "    '--receipt-path', str(receipt_path),",
            "    '--max-items', '1',",
            "    '--skip-observation-source',",
            "    '--skip-workspace-source',",
            "    '--no-include-goal-action-queue',",
            "    '--armed-send',",
            "    '--no-paused',",
            "    '--quiet-hours-start', '',",
            "    '--quiet-hours-end', '',",
            "    '--interruption-budget-limit', '0',",
            "    '--no-stage-packets',",
            "    '--no-safe-work-results',",
            "    '--action-required-delivery-only',",
            "    '--no-mirror-delivery-proof',",
            "    '--no-teable-sync',",
            "]",
            "proc = subprocess.run(cmd, cwd=str(root), env=env, capture_output=True, text=True, check=False)",
            "def _load_json(path):",
            "    try:",
            "        payload = json.loads(path.read_text(encoding='utf-8'))",
            "    except Exception:",
            "        return {}",
            "    return payload if isinstance(payload, dict) else {}",
            "def _last_json(text):",
            "    stripped = str(text or '').strip()",
            "    if not stripped:",
            "        return {}",
            "    try:",
            "        payload = json.loads(stripped)",
            "        return payload if isinstance(payload, dict) else {}",
            "    except Exception:",
            "        pass",
            "    for line in reversed(stripped.splitlines()):",
            "        try:",
            "            payload = json.loads(line.strip())",
            "        except Exception:",
            "            continue",
            "        return payload if isinstance(payload, dict) else {}",
            "    return {}",
            "def _message_count(payload):",
            "    total = 0",
            "    for key in ('telegram_message_ids', 'delivery_message_ids', 'message_ids'):",
            "        value = payload.get(key)",
            "        if isinstance(value, (list, tuple)):",
            "            total += len([item for item in value if str(item or '').strip()])",
            "        elif str(value or '').strip():",
            "            total += 1",
            "    return total",
            "def _quiet(payload):",
            "    return (",
            "        bool(payload)",
            "        and not bool(payload.get('dry_run'))",
            "        and str(payload.get('notification_status') or '').strip().lower() == 'deferred'",
            "        and str(payload.get('error_code') or '').strip() == 'no_user_action_required'",
            "        and int(payload.get('item_count') or 0) > 0",
            "        and _message_count(payload) == 0",
            "    )",
            "receipt = _load_json(receipt_path)",
            "archive_path = ''",
            "archive_dir = receipt_path.parent / 'proactive_ooda_run_receipts'",
            "if archive_dir.is_dir():",
            "    for candidate in sorted(archive_dir.glob('*.json'), key=lambda path: path.stat().st_mtime, reverse=True):",
            "        archived = _load_json(candidate)",
            "        if _quiet(archived):",
            "            archive_path = candidate.as_posix()",
            "            break",
            "runner_payload = _last_json(proc.stdout)",
            "quiet = _quiet(receipt)",
            "message_count = _message_count(receipt)",
            "status = 'quiet_receipt_created' if proc.returncode == 0 and quiet else 'probe_failed'",
            "print(json.dumps({",
            "    'probe_ok': proc.returncode == 0 and quiet,",
            "    'status': status,",
            "    'runner_returncode': int(proc.returncode or 0),",
            "    'runner_payload_seen': bool(runner_payload),",
            "    'principal_id_hash': str(receipt.get('principal_id_hash') or ''),",
            "    'signal_path': signal_path.as_posix(),",
            "    'receipt_path': receipt_path.as_posix(),",
            "    'archive_path': archive_path,",
            "    'notification_status': str(receipt.get('notification_status') or ''),",
            "    'error_code': str(receipt.get('error_code') or ''),",
            "    'item_count': int(receipt.get('item_count') or 0),",
            "    'dry_run': bool(receipt.get('dry_run')),",
            "    'message_count': message_count,",
            "    'telegram_message_count': len(receipt.get('telegram_message_ids') or []),",
            "    'delivery_message_count': len(receipt.get('delivery_message_ids') or []),",
            "    'quiet_receipt_proves_action_required_only': quiet,",
            "    'action_required_delivery_only': True,",
            "    'telegram_notification_suppressed': quiet,",
            "    'raw_signal_exposed': False,",
            "    'raw_notification_text_exposed': False,",
            "    'raw_credentials_exposed': False,",
            "    'stderr_excerpt': str(proc.stderr or '').strip()[:240],",
            "}, sort_keys=True))",
            "raise SystemExit(0 if proc.returncode == 0 and quiet else 2)",
        )
    )


def _run_proactive_action_required_quiet_probe_in_process(
    *,
    principal_id: str,
    timeout_seconds: float,
) -> tuple[int, dict[str, Any], str, str]:
    root = _proactive_runtime_root()
    ledger_dir = Path(_env("EA_RESPONSES_PROVIDER_LEDGER_DIR", str(root / "state")) or str(root / "state"))
    code = _proactive_action_required_quiet_probe_code(
        principal_id=principal_id,
        root_path=root.as_posix(),
        ledger_dir=ledger_dir.as_posix(),
    )
    effective_timeout = max(float(timeout_seconds or 1.0), 1.0)
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=root,
            env=dict(os.environ),
            capture_output=True,
            text=True,
            check=False,
            start_new_session=True,
            timeout=effective_timeout + 5.0,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
        return (
            124,
            {
                "ok": False,
                "timed_out": True,
                "reason": f"TimeoutExpired:{effective_timeout:g}s",
                "timeout_seconds": effective_timeout,
            },
            stdout,
            stderr,
        )
    stdout = str(completed.stdout or "")
    return int(completed.returncode or 0), _json_from_stdout(stdout), stdout, str(completed.stderr or "")


def _host_python_exec_json(
    *,
    command: list[str],
    timeout_seconds: float,
) -> tuple[int, dict[str, Any], str, str]:
    effective_timeout = max(float(timeout_seconds or 1.0), 1.0)
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=dict(os.environ),
            capture_output=True,
            text=True,
            check=False,
            start_new_session=True,
            timeout=effective_timeout + 5.0,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
        return (
            124,
            {
                "ok": False,
                "timed_out": True,
                "reason": f"TimeoutExpired:{effective_timeout:g}s",
                "timeout_seconds": effective_timeout,
            },
            stdout,
            stderr,
        )
    stdout = str(completed.stdout or "")
    return int(completed.returncode or 0), _json_from_stdout(stdout), stdout, str(completed.stderr or "")


def probe_proactive_action_required_quiet(
    *,
    principal_id: str = "",
    compose_file: str = "",
    runtime_service: str = "",
    timeout_seconds: float = 60.0,
    output_format: str = "json",
) -> dict[str, object]:
    effective_compose_file = str(compose_file or _env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE))).strip()
    effective_runtime_service = str(runtime_service or _env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE)).strip()
    effective_principal_id = str(principal_id or _default_proactive_principal_id()).strip()
    observed_at = _utc_now()
    if not effective_compose_file or not effective_runtime_service:
        report = {
            "probe_ok": False,
            "status": "probe_failed",
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "principal_id": effective_principal_id,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": "runtime_probe_configuration_missing",
        }
        if output_format == "operator":
            report["operator_text"] = "proactive quiet-delivery probe failed; configure runtime probe inputs"
        return report

    command = [
        "python",
        "-c",
        _proactive_action_required_quiet_probe_code(
            principal_id=effective_principal_id,
            root_path="/app",
            ledger_dir="/data/provider-ledger",
        ),
    ]
    source = "docker_compose_exec"
    if _use_in_process_proactive_runtime_fallback():
        source = "in_process_runtime"
        code, payload, stdout, stderr = _run_proactive_action_required_quiet_probe_in_process(
            principal_id=effective_principal_id,
            timeout_seconds=timeout_seconds,
        )
    else:
        code, payload, stdout, stderr = _docker_compose_exec_json(
            compose_file=effective_compose_file,
            service=effective_runtime_service,
            command=command,
            timeout_seconds=timeout_seconds,
        )
    if bool(payload.get("timed_out")):
        reason = str(payload.get("reason") or f"TimeoutExpired:{float(timeout_seconds):g}s").strip()
        report = {
            "probe_ok": False,
            "status": "probe_failed",
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "principal_id": effective_principal_id,
            "observed_at": observed_at,
            "source": source,
            "blocking_reason": f"runtime_quiet_delivery_probe_timed_out:{reason}",
            "timed_out": True,
            "timeout_seconds": float(payload.get("timeout_seconds") or timeout_seconds),
            "stdout_excerpt": stdout.strip()[:200],
            "stderr_excerpt": stderr.strip()[:200],
        }
        if output_format == "operator":
            report["operator_text"] = "proactive quiet-delivery probe timed out; inspect ea-proactive-ooda"
        return report
    if not payload:
        report = {
            "probe_ok": False,
            "status": "probe_failed",
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "principal_id": effective_principal_id,
            "observed_at": observed_at,
            "source": source,
            "blocking_reason": f"runtime_quiet_delivery_probe_failed:exit_{code}",
            "stdout_excerpt": stdout.strip()[:200],
            "stderr_excerpt": stderr.strip()[:200],
        }
        if output_format == "operator":
            report["operator_text"] = "proactive quiet-delivery probe failed; inspect ea-proactive-ooda"
        return report

    quiet_proof = bool(payload.get("quiet_receipt_proves_action_required_only"))
    probe_ok = bool(payload.get("probe_ok")) and quiet_proof and int(payload.get("message_count") or 0) == 0
    report = {
        "probe_ok": probe_ok,
        "status": "quiet_receipt_created" if probe_ok else "probe_failed",
        "compose_file": effective_compose_file,
        "runtime_service": effective_runtime_service,
        "principal_id": effective_principal_id,
        "observed_at": observed_at,
        "source": source,
        "runner_returncode": int(payload.get("runner_returncode") or code or 0),
        "runner_payload_seen": bool(payload.get("runner_payload_seen")),
        "receipt_path": str(payload.get("receipt_path") or "").strip(),
        "archive_path": str(payload.get("archive_path") or "").strip(),
        "notification_status": str(payload.get("notification_status") or "").strip(),
        "error_code": str(payload.get("error_code") or "").strip(),
        "item_count": int(payload.get("item_count") or 0),
        "dry_run": bool(payload.get("dry_run")),
        "message_count": int(payload.get("message_count") or 0),
        "telegram_message_count": int(payload.get("telegram_message_count") or 0),
        "delivery_message_count": int(payload.get("delivery_message_count") or 0),
        "action_required_delivery_only": bool(payload.get("action_required_delivery_only")),
        "telegram_notification_suppressed": bool(payload.get("telegram_notification_suppressed")),
        "quiet_receipt_proves_action_required_only": quiet_proof,
        "raw_signal_exposed": bool(payload.get("raw_signal_exposed")),
        "raw_notification_text_exposed": bool(payload.get("raw_notification_text_exposed")),
        "raw_credentials_exposed": bool(payload.get("raw_credentials_exposed")),
    }
    if not probe_ok:
        report["blocking_reason"] = (
            "quiet_receipt_missing_or_noisy"
            if int(report["runner_returncode"]) == 0
            else f"runtime_quiet_delivery_probe_failed:exit_{int(report['runner_returncode'])}"
        )
        report["stderr_excerpt"] = str(payload.get("stderr_excerpt") or stderr or "").strip()[:240]
    if output_format == "operator":
        report["operator_text"] = (
            "proactive_action_required_quiet "
            f"status={str(report['status'])} "
            f"quiet={str(bool(report['quiet_receipt_proves_action_required_only'])).lower()} "
            f"messages={int(report['message_count'])} "
            f"error={str(report['error_code']) or 'none'} "
            f"receipt={str(report['receipt_path'])}"
        )
    return report


def cleanup_proactive_approval_callbacks(
    *,
    compose_file: str = "",
    runtime_service: str = "",
    timeout_seconds: float = 60.0,
    execute: bool = False,
    supersede_noncurrent: bool = True,
    output_format: str = "json",
) -> dict[str, object]:
    effective_compose_file = str(compose_file or _env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE))).strip()
    effective_runtime_service = str(runtime_service or _env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE)).strip()
    observed_at = _utc_now()
    artifact_probe = probe_proactive_artifacts(
        compose_file=effective_compose_file,
        runtime_service=effective_runtime_service,
        timeout_seconds=timeout_seconds,
        output_format="json",
    )
    before = _proactive_callback_cleanup_counts(artifact_probe)
    base_report: dict[str, object] = {
        "probe_ok": bool(artifact_probe.get("probe_ok")),
        "status": "probe_failed" if not bool(artifact_probe.get("probe_ok")) else "dry_run",
        "source": "docker_compose_exec",
        "compose_file": effective_compose_file,
        "runtime_service": effective_runtime_service,
        "observed_at": observed_at,
        "execute": bool(execute),
        "mutated": False,
        "supersede_noncurrent": bool(supersede_noncurrent),
        "before": before,
        "after": {},
        "expired_count": 0,
        "superseded_count": 0,
        "inspected_count": 0,
        "skipped_count": 0,
        "error_count": 0,
        "would_expire_count": int(before.get("expired_pending_count") or 0),
        "would_supersede_count": int(before.get("noncurrent_pending_count") or 0) if supersede_noncurrent else 0,
        "callback_dir_exists": bool(artifact_probe.get("approval_callback_dir_exists")),
        "callback_dir_writable": bool(artifact_probe.get("approval_callback_dir_writable")),
        "callback_dir_present": bool(str(artifact_probe.get("approval_callback_dir") or "").strip()),
    }
    if not bool(artifact_probe.get("probe_ok")):
        report = {
            **base_report,
            "blocking_reason": str(artifact_probe.get("blocking_reason") or "artifact_probe_failed").strip(),
            "next_action": "inspect_proactive_runtime_artifacts",
        }
        if output_format == "operator":
            report["operator_text"] = "proactive_callback_cleanup status=probe_failed next=inspect_proactive_runtime_artifacts"
        return report
    if not bool(artifact_probe.get("approval_callback_dir_writable")):
        report = {
            **base_report,
            "status": "blocked",
            "blocking_reason": "approval_callback_dir_not_writable",
            "next_action": "restore_proactive_approval_callback_dir_write_access",
        }
        if output_format == "operator":
            report["operator_text"] = "proactive_callback_cleanup status=blocked reason=approval_callback_dir_not_writable"
        return report
    if not execute:
        cleanup_needed = bool(int(base_report["would_expire_count"]) or int(base_report["would_supersede_count"]))
        report = {
            **base_report,
            "status": "dry_run" if cleanup_needed else "clean",
            "next_action": (
                "rerun_with_execute_to_expire_or_supersede_stale_callbacks"
                if cleanup_needed
                else "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"
            ),
        }
        if output_format == "operator":
            report["operator_text"] = _proactive_callback_cleanup_operator_text(report)
        return report

    command = [
        "python",
        "-c",
        (
            "import json, sys\n"
            "from pathlib import Path\n"
            "for value in ('/app', '/app/ea', '/app/scripts'):\n"
            "    if value not in sys.path:\n"
            "        sys.path.insert(0, value)\n"
            "from app.services.proactive_ooda_telegram_approval import expire_stale_proactive_ooda_telegram_approval_callbacks\n"
            "payload = json.loads(sys.argv[1])\n"
            "result = expire_stale_proactive_ooda_telegram_approval_callbacks(\n"
            "    root=Path('/app'),\n"
            "    state_path=payload.get('state_path') or '/data/provider-ledger/proactive_ooda_notified.json',\n"
            "    receipt_path=payload.get('receipt_path') or '',\n"
            "    callback_dir=payload.get('callback_dir') or '',\n"
            "    supersede_noncurrent=bool(payload.get('supersede_noncurrent')),\n"
            ")\n"
            "print(json.dumps(result, sort_keys=True))\n"
        ),
        _json_dumps(
            {
                "state_path": str(artifact_probe.get("state_path") or "").strip(),
                "receipt_path": str(artifact_probe.get("run_receipt_path") or "").strip(),
                "callback_dir": str(artifact_probe.get("approval_callback_dir") or "").strip(),
                "supersede_noncurrent": bool(supersede_noncurrent),
            }
        ),
    ]
    source = "docker_compose_exec:proactive_callback_cleanup"
    if _use_in_process_proactive_runtime_fallback():
        source = "in_process_runtime:proactive_callback_cleanup"
        try:
            code = 0
            inputs = _proactive_runtime_inputs()
            payload = expire_stale_proactive_ooda_telegram_approval_callbacks(
                root=Path(inputs["root"]),
                state_path=str(artifact_probe.get("state_path") or inputs.get("state_path") or ""),
                receipt_path=str(artifact_probe.get("run_receipt_path") or inputs.get("receipt_path") or ""),
                callback_dir=str(artifact_probe.get("approval_callback_dir") or ""),
                supersede_noncurrent=bool(supersede_noncurrent),
            )
            stdout = json.dumps(payload, sort_keys=True)
            stderr = ""
        except Exception as exc:
            code = 127
            payload = {}
            stdout = ""
            stderr = f"{type(exc).__name__}:{str(exc or '').strip()}"
    else:
        code, payload, stdout, stderr = _docker_compose_exec_json(
            compose_file=effective_compose_file,
            service=effective_runtime_service,
            command=command,
            timeout_seconds=timeout_seconds,
        )
    if not payload:
        report = {
            **base_report,
            "source": source,
            "status": "cleanup_failed",
            "blocking_reason": f"cleanup_failed:exit_{code}",
            "next_action": "inspect_proactive_runtime_container",
            "stdout_excerpt": stdout.strip()[:200],
            "stderr_excerpt": stderr.strip()[:200],
        }
        if output_format == "operator":
            report["operator_text"] = f"proactive_callback_cleanup status=cleanup_failed next=inspect {effective_runtime_service}"
        return report

    after_probe = probe_proactive_artifacts(
        compose_file=effective_compose_file,
        runtime_service=effective_runtime_service,
        timeout_seconds=timeout_seconds,
        output_format="json",
    )
    expired_count = int(payload.get("expired_count") or 0)
    superseded_count = int(payload.get("superseded_count") or 0)
    report = {
        **base_report,
        "source": source,
        "probe_ok": bool(after_probe.get("probe_ok")),
        "status": "cleaned" if expired_count or superseded_count else "clean",
        "mutated": bool(expired_count or superseded_count),
        "cleanup_status": str(payload.get("status") or "").strip(),
        "expired_count": expired_count,
        "superseded_count": superseded_count,
        "inspected_count": int(payload.get("inspected_count") or 0),
        "skipped_count": int(payload.get("skipped_count") or 0),
        "error_count": int(payload.get("error_count") or 0),
        "after": _proactive_callback_cleanup_counts(after_probe),
        "active_packet_ref_sha256": str(payload.get("active_packet_ref_sha256") or "").strip(),
        "active_staged_artifact_ref_sha256": str(payload.get("active_staged_artifact_ref_sha256") or "").strip(),
        "next_action": "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
    }
    if int(report["error_count"]) > 0:
        report["status"] = "partial"
        report["next_action"] = "inspect_proactive_callback_cleanup_errors"
    if output_format == "operator":
        report["operator_text"] = _proactive_callback_cleanup_operator_text(report)
    return report


def _proactive_callback_cleanup_counts(report: Mapping[str, object]) -> dict[str, int]:
    return {
        "record_count": int(report.get("approval_callback_record_count") or 0),
        "raw_pending_count": int(report.get("approval_callback_raw_pending_count") or report.get("approval_callback_pending_count") or 0),
        "live_pending_count": int(report.get("approval_callback_live_pending_count") or report.get("approval_callback_pending_count") or 0),
        "stale_pending_count": int(report.get("approval_callback_stale_pending_count") or 0),
        "noncurrent_pending_count": int(report.get("approval_callback_noncurrent_pending_count") or 0),
        "expired_pending_count": int(report.get("approval_callback_expired_pending_count") or 0),
        "expired_count": int(report.get("approval_callback_expired_count") or 0),
        "superseded_count": int(report.get("approval_callback_superseded_count") or 0),
        "current_packet_live_pending_count": int(report.get("current_packet_live_pending_count") or 0),
    }


def _proactive_callback_cleanup_operator_text(report: Mapping[str, object]) -> str:
    before = dict(report.get("before") or {})
    after = dict(report.get("after") or {})
    pieces = [
        "proactive_callback_cleanup",
        f"status={str(report.get('status') or '').strip() or 'unknown'}",
        f"execute={str(bool(report.get('execute'))).lower()}",
        f"stale_before={int(before.get('stale_pending_count') or 0)}",
        f"noncurrent_before={int(before.get('noncurrent_pending_count') or 0)}",
        f"expired={int(report.get('expired_count') or 0)}",
        f"superseded={int(report.get('superseded_count') or 0)}",
    ]
    if after:
        pieces.append(f"stale_after={int(after.get('stale_pending_count') or 0)}")
        pieces.append(f"noncurrent_after={int(after.get('noncurrent_pending_count') or 0)}")
    else:
        pieces.append(f"would_expire={int(report.get('would_expire_count') or 0)}")
        pieces.append(f"would_supersede={int(report.get('would_supersede_count') or 0)}")
    if str(report.get("next_action") or "").strip():
        pieces.append(f"next={str(report.get('next_action') or '').strip()}")
    return " ".join(pieces)


def _proactive_approval_capture_operator_text(report: Mapping[str, object]) -> str:
    pieces = [
        "proactive_approval_capture",
        f"status={str(report.get('status') or '').strip() or 'unknown'}",
        f"principal_match={str(bool(report.get('principal_match_ready'))).lower()}",
        f"telegram_ready={str(bool(report.get('telegram_binding_ready'))).lower()}",
        f"current_pending={int(report.get('current_packet_live_pending_count') or 0)}",
        f"callback_status={str(report.get('current_packet_callback_latest_status') or '').strip() or 'missing'}",
        f"age_seconds={int(report.get('current_packet_callback_latest_age_seconds') or 0)}",
        f"expires_in_seconds={int(report.get('current_packet_callback_latest_seconds_until_expiry') or 0)}",
    ]
    if str(report.get("blocking_reason") or "").strip():
        pieces.append(f"reason={str(report.get('blocking_reason') or '').strip()}")
    if str(report.get("next_action") or "").strip():
        pieces.append(f"next={str(report.get('next_action') or '').strip()}")
    if str(report.get("source") or "").strip():
        pieces.append(f"source={str(report.get('source') or '').strip()}")
    return " ".join(pieces)


def probe_proactive_approval_capture(
    *,
    principal_id: str,
    compose_file: str = "",
    runtime_service: str = "",
    timeout_seconds: float = 60.0,
    output_format: str = "json",
) -> dict[str, object]:
    effective_compose_file = str(compose_file or _env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE))).strip()
    effective_runtime_service = str(runtime_service or _env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE)).strip()
    observed_at = _utc_now()
    if not effective_compose_file or not effective_runtime_service:
        report = {
            "probe_ok": False,
            "ready": False,
            "status": "probe_failed",
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": "runtime_probe_configuration_missing",
            "next_action": "configure_proactive_runtime_probe",
        }
        report.update(_next_action_surface_fields(str(report.get("next_action") or "")))
        if output_format == "operator":
            report["operator_text"] = _proactive_approval_capture_operator_text(report)
        return report

    command = [
        "python",
        "-c",
        (
            "import hashlib, json, os, sys\n"
            "from datetime import datetime, timezone\n"
            "from pathlib import Path\n"
            "from app.container import build_container\n"
            "from app.services.proactive_ooda_runtime_artifacts import load_runtime_artifact_bundle\n"
            "from app.services.proactive_ooda_telegram_approval import (\n"
            "    _approval_callback_principal_candidates,\n"
            "    default_proactive_ooda_telegram_approval_callback_dir,\n"
            ")\n"
            "from app.services.telegram_delivery import resolve_primary_telegram_binding, _telegram_bot_registry\n"
            "payload = json.loads(sys.argv[1])\n"
            "principal_id = str(payload.get('principal_id') or '').strip()\n"
            "root = Path('/app')\n"
            "state_path = os.getenv('EA_PROACTIVE_OODA_STATE_PATH') or '/data/provider-ledger/proactive_ooda_notified.json'\n"
            "receipt_path = os.getenv('EA_PROACTIVE_OODA_RECEIPT_PATH') or ''\n"
            "stage_packet_dir = os.getenv('EA_PROACTIVE_OODA_STAGE_PACKET_DIR') or ''\n"
            "safe_work_result_dir = os.getenv('EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR') or ''\n"
            "def _hash(value):\n"
            "    text = str(value or '').strip()\n"
            "    return hashlib.sha256(text.encode('utf-8')).hexdigest() if text else ''\n"
            "def _parse_dt(value):\n"
            "    text = str(value or '').strip()\n"
            "    if not text:\n"
            "        return None\n"
            "    normalized = text[:-1] + '+00:00' if text.endswith('Z') else text\n"
            "    try:\n"
            "        parsed = datetime.fromisoformat(normalized)\n"
            "    except Exception:\n"
            "        return None\n"
            "    if parsed.tzinfo is None:\n"
            "        parsed = parsed.replace(tzinfo=timezone.utc)\n"
            "    return parsed.astimezone(timezone.utc)\n"
            "def _age_seconds(value):\n"
            "    parsed = _parse_dt(value)\n"
            "    return max(int((datetime.now(timezone.utc) - parsed).total_seconds()), 0) if parsed else 0\n"
            "def _seconds_until(value):\n"
            "    parsed = _parse_dt(value)\n"
            "    return max(int((parsed - datetime.now(timezone.utc)).total_seconds()), 0) if parsed else 0\n"
            "def _is_live(row):\n"
            "    parsed = _parse_dt(row.get('expires_at'))\n"
            "    return parsed is None or parsed > datetime.now(timezone.utc)\n"
            "def _status(row):\n"
            "    return str(row.get('status') or '').strip().lower()\n"
            "def _current_refs(bundle):\n"
            "    stage_packet = dict(bundle.get('stage_packet') or {})\n"
            "    safe_work_result = dict(bundle.get('safe_work_result') or {})\n"
            "    packet_ref = str(stage_packet.get('packet_ref') or stage_packet.get('packet_id') or '').strip()\n"
            "    artifact_ref = str(safe_work_result.get('result_ref') or '').strip()\n"
            "    if not artifact_ref:\n"
            "        result_id = str(safe_work_result.get('result_id') or '').strip()\n"
            "        artifact_ref = f'safe_work_result:{result_id}' if result_id else ''\n"
            "    return packet_ref, artifact_ref\n"
            "container = build_container()\n"
            "bundle = load_runtime_artifact_bundle(root=root, state_path=state_path, receipt_path=receipt_path, stage_packet_dir=stage_packet_dir, safe_work_result_dir=safe_work_result_dir)\n"
            "callback_dir = default_proactive_ooda_telegram_approval_callback_dir(root=root, state_path=state_path, receipt_path=receipt_path)\n"
            "packet_ref, artifact_ref = _current_refs(bundle)\n"
            "rows = []\n"
            "if callback_dir.is_dir():\n"
            "    for candidate in callback_dir.glob('*.json'):\n"
            "        try:\n"
            "            record = json.loads(candidate.read_text(encoding='utf-8'))\n"
            "        except Exception:\n"
            "            continue\n"
            "        if isinstance(record, dict):\n"
            "            rows.append(record)\n"
            "live_pending_rows = [row for row in rows if _status(row) == 'pending' and _is_live(row)]\n"
            "current_rows = [\n"
            "    row for row in rows\n"
            "    if str(row.get('packet_ref') or '').strip() == packet_ref\n"
            "    and str(row.get('staged_artifact_ref') or '').strip() == artifact_ref\n"
            "]\n"
            "if not current_rows and len(live_pending_rows) == 1:\n"
            "    inferred_row = dict(live_pending_rows[0] or {})\n"
            "    inferred_packet_ref = str(inferred_row.get('packet_ref') or '').strip()\n"
            "    inferred_artifact_ref = str(inferred_row.get('staged_artifact_ref') or '').strip()\n"
            "    if inferred_packet_ref and inferred_artifact_ref:\n"
            "        packet_ref = inferred_packet_ref\n"
            "        artifact_ref = inferred_artifact_ref\n"
            "        current_rows = [inferred_row]\n"
            "if int(bundle.get('current_packet_live_pending_count') or 0) <= 0:\n"
            "    current_rows = []\n"
            "current_live_pending_rows = [row for row in current_rows if _status(row) == 'pending' and _is_live(row)]\n"
            "current_rows.sort(key=lambda row: str(row.get('created_at') or ''))\n"
            "current_live_pending_rows.sort(key=lambda row: str(row.get('created_at') or ''))\n"
            "latest = current_live_pending_rows[-1] if current_live_pending_rows else (current_rows[-1] if current_rows else {})\n"
            "record_principal_hash = str(latest.get('principal_id_hash') or '').strip()\n"
            "candidates = tuple(_approval_callback_principal_candidates(container=container, principal_id=principal_id, include_delivery_defaults=True))\n"
            "candidate_hashes = tuple(_hash(candidate) for candidate in candidates if str(candidate or '').strip())\n"
            "principal_match_ready = bool(record_principal_hash and record_principal_hash in candidate_hashes)\n"
            "binding = resolve_primary_telegram_binding(container.tool_runtime, principal_id=principal_id)\n"
            "telegram_reason = ''\n"
            "chat_ref = ''\n"
            "bot_key = ''\n"
            "bot_token_present = False\n"
            "if binding is None:\n"
            "    telegram_reason = 'telegram_binding_not_found'\n"
            "else:\n"
            "    metadata = dict(getattr(binding, 'auth_metadata_json', None) or {})\n"
            "    chat_ref = str(metadata.get('default_chat_ref') or getattr(binding, 'external_account_ref', '') or '').strip()\n"
            "    bot_key = str(metadata.get('bot_key') or 'default').strip() or 'default'\n"
            "    token = str(dict((_telegram_bot_registry().get(bot_key) or {})).get('token') or '').strip()\n"
            "    bot_token_present = bool(token)\n"
            "    if not chat_ref:\n"
            "        telegram_reason = 'telegram_chat_ref_missing'\n"
            "    elif not bot_token_present:\n"
            "        telegram_reason = 'telegram_bot_token_missing'\n"
            "latest_created_at = str(latest.get('created_at') or '').strip()\n"
            "latest_expires_at = str(latest.get('expires_at') or '').strip()\n"
            "print(json.dumps({\n"
            "    'ok': True,\n"
            "    'callback_dir_exists': callback_dir.is_dir(),\n"
            "    'callback_record_count': len(rows),\n"
            "    'current_packet_ref_sha256': _hash(packet_ref),\n"
            "    'current_staged_artifact_ref_sha256': _hash(artifact_ref),\n"
            "    'current_packet_refs_present': bool(packet_ref and artifact_ref),\n"
            "    'current_packet_callback_record_count': len(current_rows),\n"
            "    'current_packet_live_pending_count': len(current_live_pending_rows),\n"
            "    'current_packet_callback_latest_status': str(latest.get('status') or '').strip(),\n"
            "    'current_packet_callback_latest_expired': bool(latest) and not _is_live(latest),\n"
            "    'current_packet_callback_latest_age_seconds': _age_seconds(latest_created_at),\n"
            "    'current_packet_callback_latest_seconds_until_expiry': _seconds_until(latest_expires_at),\n"
            "    'callback_principal_hash_present': bool(record_principal_hash),\n"
            "    'candidate_principal_hash_count': len(set(candidate_hashes)),\n"
            "    'principal_match_ready': principal_match_ready,\n"
            "    'telegram_binding_ready': not bool(telegram_reason),\n"
            "    'telegram_blocking_reason': telegram_reason,\n"
            "    'telegram_chat_ref_present': bool(chat_ref),\n"
            "    'telegram_chat_ref_sha256': _hash(chat_ref),\n"
            "    'telegram_bot_key_present': bool(bot_key),\n"
            "    'telegram_bot_token_present': bot_token_present,\n"
            "    'privacy': {\n"
            "        'raw_callback_token_exposed': False,\n"
            "        'raw_principal_id_exposed': False,\n"
            "        'raw_chat_ref_exposed': False,\n"
            "        'raw_packet_ref_exposed': False,\n"
            "        'raw_staged_artifact_ref_exposed': False,\n"
            "    },\n"
            "}, sort_keys=True))\n"
        ),
        _json_dumps({"principal_id": str(principal_id or "").strip()}),
    ]
    source = "docker_compose_exec:proactive_approval_capture"
    if _use_in_process_proactive_runtime_fallback():
        source = "in_process_runtime:proactive_approval_capture"
        try:
            code = 0
            payload = _probe_proactive_approval_capture_in_process_payload(
                principal_id=str(principal_id or "").strip(),
            )
            stdout = json.dumps(payload, sort_keys=True)
            stderr = ""
        except Exception as exc:
            code = 127
            payload = {}
            stdout = ""
            stderr = f"{type(exc).__name__}:{str(exc or '').strip()}"
    else:
        code, payload, stdout, stderr = _docker_compose_exec_json(
            compose_file=effective_compose_file,
            service=effective_runtime_service,
            command=command,
            timeout_seconds=timeout_seconds,
        )
    if not payload:
        report = {
            "probe_ok": False,
            "ready": False,
            "status": "probe_failed",
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": source,
            "blocking_reason": f"runtime_approval_capture_probe_failed:exit_{code}",
            "next_action": "inspect_proactive_approval_capture_runtime_probe",
            "stdout_excerpt": stdout.strip()[:200],
            "stderr_excerpt": stderr.strip()[:200],
        }
        report.update(_next_action_surface_fields(str(report.get("next_action") or "")))
        if output_format == "operator":
            report["operator_text"] = _proactive_approval_capture_operator_text(report)
        return report

    current_refs_present = bool(payload.get("current_packet_refs_present"))
    current_pending = int(payload.get("current_packet_live_pending_count") or 0)
    duplicate_live_pending_count = max(current_pending - 1, 0)
    callback_hash_present = bool(payload.get("callback_principal_hash_present"))
    principal_match_ready = bool(payload.get("principal_match_ready"))
    telegram_ready = bool(payload.get("telegram_binding_ready"))
    telegram_reason = str(payload.get("telegram_blocking_reason") or "").strip()
    ready = bool(current_refs_present and current_pending == 1 and callback_hash_present and principal_match_ready and telegram_ready)
    blocking_reason = ""
    next_action = ""
    if not current_refs_present:
        blocking_reason = "current_packet_refs_missing"
        next_action = "regenerate_proactive_ooda_stage_packet"
    elif current_pending <= 0:
        blocking_reason = "current_packet_approval_callback_missing"
        next_action = "reissue_proactive_approval"
    elif duplicate_live_pending_count > 0:
        blocking_reason = "duplicate_live_approval_callbacks"
        next_action = "cleanup_proactive_approval_callbacks"
    elif not callback_hash_present:
        blocking_reason = "approval_callback_principal_hash_missing"
        next_action = "reissue_proactive_approval"
    elif not principal_match_ready:
        blocking_reason = "approval_callback_principal_mismatch_risk"
        next_action = "repair_proactive_approval_principal_aliases"
    elif not telegram_ready:
        blocking_reason = telegram_reason or "telegram_binding_not_ready"
        if blocking_reason == "telegram_binding_not_found":
            next_action = "connect_telegram_identity_binding"
        elif blocking_reason == "telegram_chat_ref_missing":
            next_action = "repair_telegram_chat_binding"
        elif blocking_reason == "telegram_bot_token_missing":
            next_action = "configure_telegram_bot_token"
        else:
            next_action = "repair_telegram_delivery_binding"
    else:
        next_action = "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome"

    report = {
        "probe_ok": bool(payload.get("ok", True)),
        "ready": ready,
        "status": "ready" if ready else "blocked",
        "compose_file": effective_compose_file,
        "runtime_service": effective_runtime_service,
        "observed_at": observed_at,
        "source": source,
        "blocking_reason": blocking_reason,
        "next_action": next_action,
        "callback_dir_exists": bool(payload.get("callback_dir_exists")),
        "callback_record_count": int(payload.get("callback_record_count") or 0),
        "current_packet_ref_sha256": str(payload.get("current_packet_ref_sha256") or "").strip(),
        "current_staged_artifact_ref_sha256": str(payload.get("current_staged_artifact_ref_sha256") or "").strip(),
        "current_packet_refs_present": current_refs_present,
        "current_packet_callback_record_count": int(payload.get("current_packet_callback_record_count") or 0),
        "current_packet_live_pending_count": current_pending,
        "current_packet_duplicate_live_pending_count": duplicate_live_pending_count,
        "current_packet_callback_latest_status": str(payload.get("current_packet_callback_latest_status") or "").strip(),
        "current_packet_callback_latest_expired": bool(payload.get("current_packet_callback_latest_expired")),
        "current_packet_callback_latest_age_seconds": int(payload.get("current_packet_callback_latest_age_seconds") or 0),
        "current_packet_callback_latest_seconds_until_expiry": int(
            payload.get("current_packet_callback_latest_seconds_until_expiry") or 0
        ),
        "callback_principal_hash_present": callback_hash_present,
        "candidate_principal_hash_count": int(payload.get("candidate_principal_hash_count") or 0),
        "principal_match_ready": principal_match_ready,
        "telegram_binding_ready": telegram_ready,
        "telegram_blocking_reason": telegram_reason,
        "telegram_chat_ref_present": bool(payload.get("telegram_chat_ref_present")),
        "telegram_chat_ref_sha256": str(payload.get("telegram_chat_ref_sha256") or "").strip(),
        "telegram_bot_key_present": bool(payload.get("telegram_bot_key_present")),
        "telegram_bot_token_present": bool(payload.get("telegram_bot_token_present")),
        "privacy": {
            "raw_callback_token_exposed": False,
            "raw_principal_id_exposed": False,
            "raw_chat_ref_exposed": False,
            "raw_packet_ref_exposed": False,
            "raw_staged_artifact_ref_exposed": False,
        },
    }
    report.update(_next_action_surface_fields(next_action))
    if output_format == "operator":
        report["operator_text"] = _proactive_approval_capture_operator_text(report)
    return report


def probe_proactive_gmail_draft(
    *,
    principal_id: str,
    compose_file: str = "",
    runtime_service: str = "",
    state_path: str = "",
    receipt_path: str = "",
    stage_packet_dir: str = "",
    safe_work_result_dir: str = "",
    timeout_seconds: float = 60.0,
    output_format: str = "json",
) -> dict[str, object]:
    effective_compose_file = str(compose_file or _env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE))).strip()
    effective_runtime_service = str(runtime_service or _env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE)).strip()
    observed_at = _utc_now()
    if not effective_compose_file or not effective_runtime_service:
        report = {
            "probe_ok": False,
            "status": "probe_failed",
            "principal_id": str(principal_id or "").strip(),
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": "runtime_probe_configuration_missing",
            "next_action": "configure_proactive_runtime_probe",
        }
        report.update(_next_action_surface_fields(str(report.get("next_action") or "")))
        if output_format == "operator":
            report["operator_text"] = "proactive_gmail_draft probe failed; configure runtime probe inputs"
        return report

    command = [
        "python",
        "-c",
        (
            "import json, sys\n"
            "from app.container import build_container\n"
            "from app.services.proactive_ooda_telegram_approval import inspect_latest_telegram_gmail_draft_followthrough\n"
            "from app.services.proactive_telegram_binding import resolve_proactive_telegram_chat_id\n"
            "from app.services.telegram_delivery import resolve_primary_telegram_binding\n"
            "payload = json.loads(sys.argv[1])\n"
            "container = build_container()\n"
            "report = inspect_latest_telegram_gmail_draft_followthrough(\n"
            "    container=container,\n"
            "    principal_id=str(payload.get('principal_id') or '').strip(),\n"
            "    state_path=str(payload.get('state_path') or '').strip(),\n"
            "    receipt_path=str(payload.get('receipt_path') or '').strip(),\n"
            "    stage_packet_dir=str(payload.get('stage_packet_dir') or '').strip(),\n"
            "    safe_work_result_dir=str(payload.get('safe_work_result_dir') or '').strip(),\n"
            ")\n"
            "binding = resolve_primary_telegram_binding(container.tool_runtime, principal_id=str(payload.get('principal_id') or '').strip())\n"
            "metadata = dict(getattr(binding, 'auth_metadata_json', {}) or {}) if binding is not None else {}\n"
            "primary_chat_id = str(metadata.get('default_chat_ref') or getattr(binding, 'external_account_ref', '') or '').strip() if binding is not None else ''\n"
            "report.update({\n"
            "    'telegram_primary_binding_principal_id': str(getattr(binding, 'principal_id', '') or '').strip() if binding is not None else '',\n"
            "    'telegram_primary_chat_id': primary_chat_id,\n"
            "    'telegram_proactive_chat_id': resolve_proactive_telegram_chat_id(principal_id=str(payload.get('principal_id') or '').strip()),\n"
            "})\n"
            "print(json.dumps(report, sort_keys=True))\n"
        ),
        _json_dumps(
            {
                "principal_id": str(principal_id or "").strip(),
                "state_path": str(state_path or "").strip(),
                "receipt_path": str(receipt_path or "").strip(),
                "stage_packet_dir": str(stage_packet_dir or "").strip(),
                "safe_work_result_dir": str(safe_work_result_dir or "").strip(),
            }
        ),
    ]
    code, payload, stdout, stderr = _docker_compose_exec_json(
        compose_file=effective_compose_file,
        service=effective_runtime_service,
        command=command,
        timeout_seconds=timeout_seconds,
    )
    if not payload:
        report = {
            "probe_ok": False,
            "status": "probe_failed",
            "principal_id": str(principal_id or "").strip(),
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": f"runtime_gmail_draft_probe_failed:exit_{code}",
            "next_action": "inspect_proactive_runtime_container",
            "stdout_excerpt": stdout.strip()[:200],
            "stderr_excerpt": stderr.strip()[:200],
        }
        report.update(_next_action_surface_fields(str(report.get("next_action") or "")))
        if output_format == "operator":
            report["operator_text"] = f"proactive_gmail_draft probe failed; inspect {effective_runtime_service}"
        return report

    status = str(payload.get("status") or "").strip() or "unknown"
    reason = str(payload.get("reason") or "").strip()
    next_action = _proactive_gmail_draft_next_action(reason=reason, status=status)
    next_action_surface = dict(payload.get("next_action_surface") or {})
    if (
        next_action
        and not any(str(next_action_surface.get(key) or "").strip() for key in ("href", "label", "method"))
    ):
        next_action_surface = _next_action_surface_fields(next_action)
    report = {
        "probe_ok": True,
        "status": status,
        "principal_id": str(principal_id or "").strip(),
        "compose_file": effective_compose_file,
        "runtime_service": effective_runtime_service,
        "observed_at": observed_at,
        "source": "docker_compose_exec",
        "staged_principal_id": str(payload.get("principal_id") or "").strip(),
        "packet_ref": str(payload.get("packet_ref") or "").strip(),
        "staged_artifact_ref": str(payload.get("staged_artifact_ref") or "").strip(),
        "source_observation_id": str(payload.get("source_observation_id") or "").strip(),
        "source_created_at": str(payload.get("source_created_at") or "").strip(),
        "action": str(payload.get("action") or "").strip(),
        "work_type": str(payload.get("work_type") or "").strip(),
        "blocking_reason": reason,
        "recipient_email_present": bool(str(payload.get("recipient_email") or "").strip()),
        "draft_body_present": bool(payload.get("draft_body_present")),
        "subject": str(payload.get("subject") or "").strip(),
        "google_binding_id": str(payload.get("google_binding_id") or "").strip(),
        "google_binding_principal_id": str(payload.get("google_binding_principal_id") or "").strip(),
        "google_account_email": str(payload.get("google_account_email") or "").strip(),
        "expected_google_account_email": str(payload.get("expected_google_account_email") or "").strip(),
        "google_token_status": str(payload.get("google_token_status") or "").strip(),
        "google_reauth_required_reason": str(payload.get("google_reauth_required_reason") or "").strip(),
        "google_gmail_draft_scope_present": bool(payload.get("google_gmail_draft_scope_present")),
        "google_account_count": int(payload.get("google_account_count") or 0),
        "execution_observation_present": bool(payload.get("execution_observation_present")),
        "execution_status": str(payload.get("execution_status") or "").strip(),
        "execution_saved_at": str(payload.get("execution_saved_at") or "").strip(),
        "recipient_email_hash_present": bool(payload.get("recipient_email_sha256_present")),
        "gmail_draft_id_hash_present": bool(payload.get("gmail_draft_id_sha256_present")),
        "gmail_message_id_hash_present": bool(payload.get("gmail_message_id_sha256_present")),
        "draft_folder_url_hash_present": bool(payload.get("draft_folder_url_sha256_present")),
        "raw_execution_payload_exposed": bool(payload.get("raw_execution_payload_exposed")),
        "telegram_primary_binding_principal_id": str(payload.get("telegram_primary_binding_principal_id") or "").strip(),
        "telegram_primary_chat_id": str(payload.get("telegram_primary_chat_id") or "").strip(),
        "telegram_proactive_chat_id": str(payload.get("telegram_proactive_chat_id") or "").strip(),
        "next_action": next_action,
        "next_action_href": str(next_action_surface.get("next_action_href") or next_action_surface.get("href") or "").strip(),
        "next_action_label": str(next_action_surface.get("next_action_label") or next_action_surface.get("label") or "").strip(),
        "next_action_method": str(next_action_surface.get("next_action_method") or next_action_surface.get("method") or "").strip(),
        "raw": payload,
    }
    if output_format == "operator":
        pieces = [
            f"proactive_gmail_draft status={report['status']}",
            f"action={str(report.get('action') or '').strip() or 'none'}",
        ]
        if str(report.get("google_account_email") or "").strip():
            pieces.append(f"account={report['google_account_email']}")
        if str(report.get("expected_google_account_email") or "").strip():
            pieces.append(f"expected={report['expected_google_account_email']}")
        if str(report.get("google_token_status") or "").strip():
            pieces.append(f"token={report['google_token_status']}")
        if bool(report.get("execution_observation_present")):
            pieces.append(f"execution={str(report.get('execution_status') or '').strip() or 'recorded'}")
        if bool(report.get("gmail_draft_id_hash_present")):
            pieces.append("draft_hash=true")
        if str(report.get("telegram_proactive_chat_id") or "").strip():
            pieces.append(f"proactive_chat={report['telegram_proactive_chat_id']}")
        if str(report.get("blocking_reason") or "").strip():
            pieces.append(f"reason={report['blocking_reason']}")
        if str(report.get("next_action") or "").strip():
            pieces.append(f"next={report['next_action']}")
        report["operator_text"] = "; ".join(pieces)
    return report


def _proactive_stage_packet_ref(stage_packet: Mapping[str, object]) -> str:
    return str(stage_packet.get("packet_ref") or stage_packet.get("packet_id") or "").strip()


def _proactive_staged_artifact_ref(safe_work_result: Mapping[str, object]) -> str:
    result_ref = str(safe_work_result.get("result_ref") or "").strip()
    if result_ref:
        return result_ref
    result_id = str(safe_work_result.get("result_id") or "").strip()
    return f"safe_work_result:{result_id}" if result_id else ""


def _normalize_proactive_outcome(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"approve", "approved", "accept", "accepted"}:
        return "approved"
    if normalized in {"reject", "rejected", "deny", "denied", "decline", "declined"}:
        return "rejected"
    if normalized in {"defer", "deferred", "later"}:
        return "deferred"
    if normalized in {"dismiss", "dismissed"}:
        return "dismissed"
    return normalized or "missing"


def _proactive_gmail_draft_next_action(*, reason: str = "", status: str = "") -> str:
    normalized = str(reason or "").strip().lower()
    if normalized in {
        "google_oauth_binding_not_found",
        "google_oauth_invalid_grant",
        "google_oauth_refresh_failed",
        "google_oauth_account_mismatch",
        "google_gmail_draft_scope_missing",
        "google_gmail_refresh_token_missing",
        "google_gmail_access_token_missing",
        "google_gmail_sender_missing",
    }:
        return "reauthorize_google_workspace_binding"
    if normalized in {"approved_stage_packet_missing", "approved_safe_work_result_missing", "staged_refs_missing"}:
        return "inspect_proactive_runtime_artifacts"
    if normalized == "approved_draft_body_missing":
        return "inspect_proactive_runtime_artifacts"
    normalized_status = str(status or "").strip().lower()
    if normalized_status == "no_pending_draft":
        return "review_proactive_draft_queue"
    return ""


def probe_proactive_source_coverage(
    *,
    principal_id: str,
    compose_file: str = "",
    runtime_service: str = "",
    observation_limit: int = 400,
    timeout_seconds: float = DEFAULT_PROACTIVE_SOURCE_COVERAGE_TIMEOUT_SECONDS,
    output_format: str = "json",
) -> dict[str, object]:
    effective_compose_file = str(compose_file or _env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE))).strip()
    effective_runtime_service = str(runtime_service or _env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE)).strip()
    effective_timeout_seconds = max(float(timeout_seconds or DEFAULT_PROACTIVE_SOURCE_COVERAGE_TIMEOUT_SECONDS), 1.0)
    observed_at = _utc_now()
    if not effective_compose_file or not effective_runtime_service:
        report = {
            "probe_ok": False,
            "checked": False,
            "status": "probe_failed",
            "principal_id": str(principal_id or "").strip(),
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": "runtime_probe_configuration_missing",
            "next_action": "configure_proactive_runtime_probe",
            "lanes": [],
            "missing_lane_keys": list(PROACTIVE_SOURCE_COVERAGE_LANE_KEYS),
        }
        if output_format == "operator":
            report["operator_text"] = "proactive_source_coverage probe failed; configure runtime probe inputs"
        return _finalize_proactive_source_coverage_report(report, output_format=output_format)

    limit = max(1, min(5000, int(observation_limit or 400)))
    if _prefer_in_process_source_coverage_probe():
        try:
            report = _probe_proactive_source_coverage_in_process_report(
                principal_id=str(principal_id or "").strip(),
                observation_limit=limit,
                observed_at=observed_at,
            )
            missing_next_action = next(
                (
                    str(dict(lane).get("next_action") or "").strip()
                    for lane in list(report.get("lanes") or [])
                    if not bool(dict(lane).get("observed"))
                ),
                "",
            )
            report.update(
                {
                    "compose_file": effective_compose_file,
                    "runtime_service": effective_runtime_service,
                    "blocking_reason": "",
                    "next_action": missing_next_action,
                }
            )
            if _should_expand_source_coverage_window(report, observation_limit=limit):
                expanded_limit = min(max(limit * 10, 1000), 4000)
                if expanded_limit > limit:
                    return probe_proactive_source_coverage(
                        principal_id=principal_id,
                        compose_file=effective_compose_file,
                        runtime_service=effective_runtime_service,
                        observation_limit=expanded_limit,
                        timeout_seconds=effective_timeout_seconds,
                        output_format=output_format,
                    )
            repaired_report = dict(report)
            if str(repaired_report.get("status") or "").strip() == "repaired":
                repaired_report["status"] = "ready"
            return _finalize_proactive_source_coverage_report(repaired_report, output_format=output_format)
        except Exception:
            pass

    command = [
        "python",
        "-c",
        (
            "import hashlib, json, os, sys\n"
            "from app.container import build_container\n"
            "payload = json.loads(sys.argv[1])\n"
            "principal_id = str(payload.get('principal_id') or '').strip()\n"
            "limit = max(1, min(5000, int(payload.get('observation_limit') or 400)))\n"
            "container = build_container()\n"
            "runtime = container.channel_runtime\n"
            "repo = getattr(runtime, '_observations', None)\n"
            "def _sha(value):\n"
            "    text = str(value or '').strip()\n"
            "    return hashlib.sha256(text.encode('utf-8')).hexdigest() if text else ''\n"
            "def _walk(value):\n"
            "    if isinstance(value, dict):\n"
            "        for key, item in value.items():\n"
            "            yield str(key or '')\n"
            "            yield from _walk(item)\n"
            "    elif isinstance(value, (list, tuple, set)):\n"
            "        for item in value:\n"
            "            yield from _walk(item)\n"
            "    elif isinstance(value, (str, int, float, bool)):\n"
            "        yield str(value or '')\n"
            "def _hints(row, payload):\n"
            "    text = ' '.join([str(getattr(row, 'channel', '') or ''), str(getattr(row, 'event_type', '') or ''), str(getattr(row, 'source_id', '') or ''), str(getattr(row, 'external_id', '') or ''), ' '.join(_walk(payload))]).lower()\n"
            "    specs = {\n"
            "        'google_workspace': ('google', 'gmail', 'calendar', 'workspace'),\n"
            "        'pocket_ai_audio_transcripts': ('pocket', 'pocket.ai', 'recording', 'transcript'),\n"
            "        'calendar_and_renewal_signals': ('calendar', 'renewal', 'subscription', 'appointment'),\n"
            "        'relationship_and_occasion_signals': ('relationship', 'occasion', 'birthday', 'anniversary', 'wife', 'family'),\n"
            "        'shopping_and_vendor_signals': ('shopping', 'vendor', 'supplier', 'provider', 'purchase', 'amazon', 'shortlist', 'draft'),\n"
            "        'commitment_and_deadline_signals': ('commitment', 'deadline', 'due', 'followup', 'follow-up', 'appointment', 'booking'),\n"
            "        'durable_profile_and_location_context': ('profile', 'preference', 'location', 'locality', 'address', 'context'),\n"
            "    }\n"
            "    return sorted(key for key, needles in specs.items() if any(needle in text for needle in needles))\n"
            "rows = []\n"
            "PROPERTY_EVENT_TYPES_TO_EXCLUDE = {\n"
            "    'property_scout_sync_completed',\n"
            "    'assistant_property_task_auto_closed',\n"
            "}\n"
            "PROPERTY_EVENT_PREFIXES_TO_EXCLUDE = ('property_', 'assistant_property_')\n"
            "def _excluded_event_type(value):\n"
            "    normalized = str(value or '').strip().lower()\n"
            "    if not normalized:\n"
            "        return False\n"
            "    if normalized in PROPERTY_EVENT_TYPES_TO_EXCLUDE:\n"
            "        return True\n"
            "    return any(normalized.startswith(prefix) for prefix in PROPERTY_EVENT_PREFIXES_TO_EXCLUDE)\n"
            "for row in runtime.list_recent_observations(limit=limit, principal_id=principal_id):\n"
            "    row_payload = dict(getattr(row, 'payload', {}) or {})\n"
            "    if _excluded_event_type(getattr(row, 'event_type', '')):\n"
            "        continue\n"
            "    rows.append({\n"
            "        'channel': str(getattr(row, 'channel', '') or '').strip(),\n"
            "        'event_type': str(getattr(row, 'event_type', '') or '').strip(),\n"
            "        'created_at': str(getattr(row, 'created_at', '') or '').strip(),\n"
            "        'payload_keys': sorted(str(key) for key in row_payload.keys()),\n"
            "        'hints': _hints(row, row_payload),\n"
            "        'source_id_sha256_present': bool(_sha(getattr(row, 'source_id', '') or '')),\n"
            "        'external_id_sha256_present': bool(_sha(getattr(row, 'external_id', '') or '')),\n"
            "        'raw_payload_exposed': False,\n"
            "    })\n"
            "print(json.dumps({\n"
            "    'probe_ok': True,\n"
            "    'observation_repository': type(repo).__name__ if repo is not None else '',\n"
            "    'rows': rows,\n"
            "}, sort_keys=True))\n"
        ),
        _json_dumps(
            {
                "principal_id": str(principal_id or "").strip(),
                "observation_limit": limit,
            }
        ),
    ]
    code, payload, stdout, stderr = _docker_compose_exec_json(
        compose_file=effective_compose_file,
        service=effective_runtime_service,
        command=command,
        timeout_seconds=effective_timeout_seconds,
    )
    if not payload or payload.get("probe_ok") is False or payload.get("ok") is False:
        reason = str(payload.get("reason") or "").strip() if payload else ""
        report = {
            "probe_ok": False,
            "checked": False,
            "status": "probe_failed",
            "principal_id": str(principal_id or "").strip(),
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": reason or f"runtime_source_coverage_probe_failed:exit_{code}",
            "next_action": "inspect_proactive_runtime_container",
            "stdout_excerpt": stdout.strip()[:200],
            "stderr_excerpt": stderr.strip()[:200],
            "lanes": [],
            "missing_lane_keys": list(PROACTIVE_SOURCE_COVERAGE_LANE_KEYS),
        }
        if output_format == "operator":
            report["operator_text"] = f"proactive_source_coverage probe failed; inspect {effective_runtime_service}"
        return _finalize_proactive_source_coverage_report(report, output_format=output_format)

    rows = [dict(row) for row in list(payload.get("rows") or []) if isinstance(row, Mapping)]
    pocket_archive_evidence: dict[str, object] = {}
    if not any(_proactive_source_lane_matches(row, "pocket_ai_audio_transcripts") for row in rows):
        pocket_archive_evidence = _pocket_audio_archive_evidence()
    report = _proactive_source_coverage_report(
        principal_id=str(principal_id or "").strip(),
        rows=rows,
        observation_repository=str(payload.get("observation_repository") or "").strip(),
        observed_at=observed_at,
        observation_limit=limit,
        pocket_archive_evidence=pocket_archive_evidence,
    )
    missing_next_action = next(
        (str(dict(lane).get("next_action") or "").strip() for lane in list(report.get("lanes") or []) if not bool(dict(lane).get("observed"))),
        "",
    )
    report.update(
        {
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "blocking_reason": "",
            "next_action": missing_next_action,
        }
    )
    if _should_expand_source_coverage_window(report, observation_limit=limit):
        expanded_limit = min(max(limit * 10, 1000), 4000)
        if expanded_limit > limit:
            expanded_timeout_seconds = max(
                effective_timeout_seconds,
                DEFAULT_EXPANDED_PROACTIVE_SOURCE_COVERAGE_TIMEOUT_SECONDS,
            )
            return probe_proactive_source_coverage(
                principal_id=principal_id,
                compose_file=effective_compose_file,
                runtime_service=effective_runtime_service,
                observation_limit=expanded_limit,
                timeout_seconds=expanded_timeout_seconds,
                output_format=output_format,
            )
    finalized_report = dict(report)
    if str(finalized_report.get("status") or "").strip() == "repaired":
        finalized_report["status"] = "ready"
    return _finalize_proactive_source_coverage_report(finalized_report, output_format=output_format)


def _pocket_transcript_sync_next_action(reason: str) -> str:
    normalized = str(reason or "").strip()
    detail = normalized.split(":", 1)[1].strip() if ":" in normalized else normalized
    if detail == "pocket_api_key_missing":
        return "configure_pocket_api_key"
    if detail.startswith("pocket_api_http_429:") or normalized.startswith("RuntimeError:pocket_api_http_429:"):
        return "retry_pocket_sync_after_provider_cooldown"
    if detail.startswith("pocket_api_unreachable:") or normalized.startswith("RuntimeError:pocket_api_unreachable:"):
        return "inspect_pocket_api_connectivity"
    if normalized:
        return "inspect_pocket_sync_runtime"
    return ""


def sync_pocket_transcripts(
    *,
    principal_id: str,
    mode: str = "incremental",
    limit: int = 10,
    compose_file: str = "",
    runtime_service: str = "",
    timeout_seconds: float = 120.0,
    output_format: str = "json",
) -> dict[str, object]:
    effective_compose_file = str(compose_file or _env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE))).strip()
    effective_runtime_service = str(runtime_service or _env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE)).strip()
    observed_at = _utc_now()
    normalized_mode = str(mode or "incremental").strip().lower().replace("_", "-")
    if normalized_mode not in {"incremental", "backfill", "archive-reindex"}:
        normalized_mode = "incremental"
    bounded_limit = max(0 if normalized_mode == "backfill" else 1, min(int(limit or 10), 250 if normalized_mode == "backfill" else 100))
    if not effective_compose_file or not effective_runtime_service:
        report = {
            "probe_ok": False,
            "synced": False,
            "status": "probe_failed",
            "principal_id": str(principal_id or "").strip(),
            "mode": normalized_mode,
            "limit": bounded_limit,
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": "runtime_probe_configuration_missing",
            "next_action": "configure_proactive_runtime_probe",
            "raw_payload_exposed": False,
            "raw_transcript_text_exposed": False,
            "raw_archive_path_exposed": False,
            "raw_credential_exposed": False,
        }
        report.update(_next_action_surface_fields(str(report.get("next_action") or "")))
        if output_format == "operator":
            report["operator_text"] = "pocket_transcript_sync status=probe_failed; next=configure_proactive_runtime_probe"
        return report

    command = [
        "python",
        "-c",
        (
            "import json, os, sys\n"
            "from app.container import build_container\n"
            "from app.product.service import build_product_service\n"
            "payload = json.loads(sys.argv[1])\n"
            "os.environ['EA_POCKET_ASSISTANT_AUTO_ACTIONS'] = 'manual_followup,none'\n"
            "os.environ['EA_POCKET_ASSISTANT_DANGEROUS_AUTO_ACTIONS'] = ''\n"
            "container = build_container()\n"
            "service = build_product_service(container)\n"
            "def _safe_reason(exc):\n"
            "    text = ' '.join(str(exc or '').split())[:200]\n"
            "    for secret_name in ('POCKET_API_KEY', 'EA_POCKET_API_KEY'):\n"
            "        secret = str(os.environ.get(secret_name) or '').strip()\n"
            "        if secret:\n"
            "            text = text.replace(secret, '[redacted]')\n"
            "    return f'{type(exc).__name__}:{text}' if text else type(exc).__name__\n"
            "principal_id = str(payload.get('principal_id') or '').strip()\n"
            "actor = str(payload.get('actor') or 'ea-live-ops').strip()\n"
            "mode = str(payload.get('mode') or 'incremental').strip()\n"
            "limit = int(payload.get('limit') or 10)\n"
            "keys = (\n"
            "    'generated_at','mode','total','synced_total','deduplicated_total','suppressed_total','failed_total',\n"
            "    'recording_total','staging_suppressed_total','archived_total','archive_dismissed_total','archive_failed_total',\n"
            "    'teable_index_status','teable_index_blocked_reason','teable_index_row_total','teable_index_sync_attempted',\n"
            "    'preference_evidence_total','preference_evidence_applied_total','assistant_trigger_total',\n"
            "    'assistant_trigger_executed_total','assistant_trigger_blocked_total','cursor_used','cursor_persisted',\n"
            "    'cursor_updated_at','cursor_recording_id','cursor_advanced','scan_truncated','location_matched_total',\n"
            "    'location_unmatched_total'\n"
            ")\n"
            "try:\n"
            "    if mode == 'archive-reindex':\n"
            "        result = service.reindex_pocket_audio_archive(principal_id=principal_id, actor=actor)\n"
            "    elif mode == 'backfill':\n"
            "        result = service.backfill_pocket_recordings(principal_id=principal_id, actor=actor, limit=limit)\n"
            "    else:\n"
            "        result = service.sync_pocket_recordings(principal_id=principal_id, actor=actor, limit=limit)\n"
            "    summary = {key: result.get(key) for key in keys if key in result}\n"
            "    print(json.dumps({\n"
            "        'ok': True,\n"
            "        'summary': summary,\n"
            "        'assistant_auto_actions': 'manual_followup,none',\n"
            "        'dangerous_auto_actions_enabled': False,\n"
            "    }, sort_keys=True))\n"
            "except RuntimeError as exc:\n"
            "    print(json.dumps({\n"
            "        'ok': False,\n"
            "        'reason': _safe_reason(exc),\n"
            "        'assistant_auto_actions': 'manual_followup,none',\n"
            "        'dangerous_auto_actions_enabled': False,\n"
            "    }, sort_keys=True))\n"
            "except Exception as exc:\n"
            "    print(json.dumps({\n"
            "        'ok': False,\n"
            "        'reason': _safe_reason(exc),\n"
            "        'assistant_auto_actions': 'manual_followup,none',\n"
            "        'dangerous_auto_actions_enabled': False,\n"
            "    }, sort_keys=True))\n"
        ),
        _json_dumps(
            {
                "principal_id": str(principal_id or "").strip(),
                "actor": "ea-live-ops",
                "mode": normalized_mode,
                "limit": bounded_limit,
            }
        ),
    ]
    code, payload, stdout, stderr = _docker_compose_exec_json(
        compose_file=effective_compose_file,
        service=effective_runtime_service,
        command=command,
        timeout_seconds=timeout_seconds,
    )
    if not payload:
        report = {
            "probe_ok": False,
            "synced": False,
            "status": "probe_failed",
            "principal_id": str(principal_id or "").strip(),
            "mode": normalized_mode,
            "limit": bounded_limit,
            "compose_file": effective_compose_file,
            "runtime_service": effective_runtime_service,
            "observed_at": observed_at,
            "source": "docker_compose_exec",
            "blocking_reason": f"runtime_pocket_transcript_sync_failed:exit_{code}",
            "next_action": "inspect_pocket_sync_runtime",
            "stdout_excerpt": stdout.strip()[:200],
            "stderr_excerpt": stderr.strip()[:200],
            "raw_payload_exposed": False,
            "raw_transcript_text_exposed": False,
            "raw_archive_path_exposed": False,
            "raw_credential_exposed": False,
        }
        report.update(_next_action_surface_fields(str(report.get("next_action") or "")))
        if output_format == "operator":
            report["operator_text"] = f"pocket_transcript_sync status=probe_failed; next=inspect_pocket_sync_runtime"
        return report

    summary = dict(payload.get("summary") or {})
    reason = str(payload.get("reason") or "").strip()
    ok = bool(payload.get("ok"))
    failed_total = int(summary.get("failed_total") or 0)
    archive_failed_total = int(summary.get("archive_failed_total") or 0)
    recording_total = int(summary.get("recording_total") or 0)
    teable_status = str(summary.get("teable_index_status") or "").strip()
    teable_blocked_reason = str(summary.get("teable_index_blocked_reason") or "").strip()
    if not ok:
        status = "throttled" if "pocket_api_http_429:" in reason else "blocked"
    elif failed_total or archive_failed_total or teable_status == "blocked":
        status = "completed_with_gaps"
    elif recording_total == 0:
        status = "no_new_recordings"
    else:
        status = "synced"
    next_action = _pocket_transcript_sync_next_action(reason)
    if ok and status == "completed_with_gaps":
        next_action = "inspect_pocket_sync_runtime"
    if ok and status in {"synced", "no_new_recordings"}:
        next_action = "probe_proactive_source_coverage"
    if teable_status == "blocked" and teable_blocked_reason:
        next_action = "inspect_teable_projection"
    report = {
        "probe_ok": True,
        "synced": ok,
        "status": status,
        "principal_id": str(principal_id or "").strip(),
        "mode": normalized_mode,
        "limit": bounded_limit,
        "compose_file": effective_compose_file,
        "runtime_service": effective_runtime_service,
        "observed_at": observed_at,
        "source": "docker_compose_exec",
        "blocking_reason": reason or teable_blocked_reason,
        "next_action": next_action,
        "recording_total": recording_total,
        "synced_total": int(summary.get("synced_total") or 0),
        "deduplicated_total": int(summary.get("deduplicated_total") or 0),
        "suppressed_total": int(summary.get("suppressed_total") or 0),
        "failed_total": failed_total,
        "archived_total": int(summary.get("archived_total") or 0),
        "archive_dismissed_total": int(summary.get("archive_dismissed_total") or 0),
        "archive_failed_total": archive_failed_total,
        "teable_index_status": teable_status,
        "teable_index_row_total": int(summary.get("teable_index_row_total") or 0),
        "teable_index_sync_attempted": bool(summary.get("teable_index_sync_attempted")),
        "assistant_trigger_total": int(summary.get("assistant_trigger_total") or 0),
        "assistant_trigger_executed_total": int(summary.get("assistant_trigger_executed_total") or 0),
        "assistant_trigger_blocked_total": int(summary.get("assistant_trigger_blocked_total") or 0),
        "assistant_auto_actions": str(payload.get("assistant_auto_actions") or "").strip(),
        "dangerous_auto_actions_enabled": bool(payload.get("dangerous_auto_actions_enabled")),
        "cursor_used": bool(summary.get("cursor_used")),
        "cursor_persisted": bool(summary.get("cursor_persisted")),
        "cursor_advanced": bool(summary.get("cursor_advanced")),
        "scan_truncated": bool(summary.get("scan_truncated")),
        "location_matched_total": int(summary.get("location_matched_total") or 0),
        "location_unmatched_total": int(summary.get("location_unmatched_total") or 0),
        "raw_payload_exposed": False,
        "raw_transcript_text_exposed": False,
        "raw_archive_path_exposed": False,
        "raw_credential_exposed": False,
    }
    report.update(_next_action_surface_fields(str(report.get("next_action") or "")))
    if output_format == "operator":
        pieces = [
            f"pocket_transcript_sync status={status}",
            f"mode={normalized_mode}",
            f"recordings={recording_total}",
            f"synced={int(report['synced_total'])}",
            f"archived={int(report['archived_total'])}",
            f"teable={teable_status or 'unknown'}",
        ]
        if reason or teable_blocked_reason:
            pieces.append(f"reason={reason or teable_blocked_reason}")
        if str(report.get("next_action") or "").strip():
            pieces.append(f"next={report['next_action']}")
        report["operator_text"] = "; ".join(pieces)
    return report


def record_proactive_approval(
    *,
    principal_id: str,
    outcome: str,
    evidence: str,
    actor: str = "operator-cli",
    source_kind: str = "operator",
    packet_ref: str = "",
    staged_artifact_ref: str = "",
    compose_file: str = "",
    runtime_service: str = "",
    timeout_seconds: float = 60.0,
    dry_run: bool = False,
    output_format: str = "json",
) -> dict[str, object]:
    effective_compose_file = str(compose_file or _env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE))).strip()
    effective_runtime_service = str(runtime_service or _env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE)).strip()
    observed_at = _utc_now()
    artifact_probe = probe_proactive_artifacts(
        compose_file=effective_compose_file,
        runtime_service=effective_runtime_service,
        timeout_seconds=timeout_seconds,
        output_format="json",
    )
    normalized_outcome = _normalize_proactive_outcome(outcome)
    resolved_packet_ref = str(packet_ref or "").strip() or _proactive_stage_packet_ref(dict(artifact_probe.get("stage_packet") or {}))
    resolved_staged_artifact_ref = str(staged_artifact_ref or "").strip() or _proactive_staged_artifact_ref(
        dict(artifact_probe.get("safe_work_result") or {})
    )
    current_packet_recordable = _current_proactive_approval_recordable(artifact_probe)
    approval_outcome_current = _approval_outcome_matches_current_packet(
        approval_outcome=dict(artifact_probe.get("approval_outcome") or {}),
        stage_packet=dict(artifact_probe.get("stage_packet") or {}),
        safe_work_result=dict(artifact_probe.get("safe_work_result") or {}),
    ) or bool(dict(artifact_probe.get("current_packet") or {}).get("approval_outcome_matches_current_packet"))
    live_pending_count = int(artifact_probe.get("current_packet_live_pending_count") or 0)
    manual_outcome_capture_ready = bool(current_packet_recordable and not approval_outcome_current)
    base_report: dict[str, object] = {
        "recorded": False,
        "reason": "",
        "principal_id_hash": _hash_text(principal_id),
        "outcome": normalized_outcome,
        "accepted": normalized_outcome == "approved",
        "evidence_present": bool(str(evidence or "").strip()),
        "actor_sha256": _hash_text(actor),
        "actor_present": bool(str(actor or "").strip()),
        "source_kind": str(source_kind or "").strip() or "operator",
        "packet_ref_sha256": _hash_text(resolved_packet_ref),
        "staged_artifact_ref_sha256": _hash_text(resolved_staged_artifact_ref),
        "current_packet_refs_present": bool(resolved_packet_ref and resolved_staged_artifact_ref),
        "compose_file": effective_compose_file,
        "runtime_service": effective_runtime_service,
        "observed_at": observed_at,
        "artifact_probe_summary": _redacted_proactive_artifact_probe_summary(
            artifact_probe=artifact_probe,
            packet_ref=resolved_packet_ref,
            staged_artifact_ref=resolved_staged_artifact_ref,
        ),
        "approval_capture_surface_ready": bool(live_pending_count == 1 or manual_outcome_capture_ready),
        "telegram_approval_surface_ready": bool(live_pending_count == 1),
        "manual_outcome_capture_ready": manual_outcome_capture_ready,
        "current_packet_approval_request_recordable": current_packet_recordable,
        "approval_outcome_matches_current_packet": approval_outcome_current,
        "approval_capture_surface_pending_count": live_pending_count,
        "approval_capture_surface_duplicate_pending_count": max(live_pending_count - 1, 0),
        "privacy": {
            "raw_principal_id_exposed": False,
            "raw_actor_exposed": False,
            "raw_evidence_exposed": False,
            "raw_packet_ref_exposed": False,
            "raw_staged_artifact_ref_exposed": False,
            "raw_artifact_probe_exposed": False,
        },
    }
    if not bool(artifact_probe.get("probe_ok")):
        report = {
            **base_report,
            "reason": "artifact_probe_failed",
            "blocking_reason": str(artifact_probe.get("blocking_reason") or "artifact_probe_failed").strip(),
            "next_action": "inspect_proactive_runtime_artifacts",
        }
        if output_format == "operator":
            report["operator_text"] = "proactive_approval status=probe_failed; next=inspect_proactive_runtime_artifacts"
        return report
    if not resolved_packet_ref or not resolved_staged_artifact_ref:
        report = {
            **base_report,
            "reason": "current_runtime_packet_unresolved",
            "blocking_reason": "current_runtime_packet_unresolved",
            "next_action": "inspect_proactive_runtime_artifacts",
        }
        if output_format == "operator":
            report["operator_text"] = "proactive_approval status=unresolved; next=inspect_proactive_runtime_artifacts"
        return report
    if dry_run:
        report = {
            **base_report,
            "reason": "dry_run",
            "next_action": "run_without_dry_run_to_record_outcome",
        }
        if output_format == "operator":
            report["operator_text"] = (
                "proactive_approval status=dry_run; "
                f"outcome={normalized_outcome}; packet_ref_sha256={_hash_text(resolved_packet_ref)}"
            )
        return report

    command = [
        "python",
        "-c",
        (
            "import json, sys\n"
            "from pathlib import Path\n"
            "for value in ('/app', '/app/ea', '/app/scripts'):\n"
            "    if value not in sys.path:\n"
            "        sys.path.insert(0, value)\n"
            "from app.services.proactive_ooda_approval_reissue import record_current_proactive_ooda_approval_outcome\n"
            "payload = json.loads(sys.argv[1])\n"
            "payload['root'] = Path(str(payload.get('root') or '/app'))\n"
            "result = record_current_proactive_ooda_approval_outcome(**payload)\n"
            "def _jsonify(value):\n"
            "    if isinstance(value, Path):\n"
            "        return value.as_posix()\n"
            "    if isinstance(value, dict):\n"
            "        return {k: _jsonify(v) for k, v in value.items()}\n"
            "    if isinstance(value, (list, tuple)):\n"
            "        return [_jsonify(v) for v in value]\n"
            "    return value\n"
            "print(json.dumps(_jsonify(result), sort_keys=True))\n"
        ),
        _json_dumps(
            {
                "principal_id": str(principal_id or "").strip(),
                "outcome": normalized_outcome,
                "evidence": str(evidence or "").strip(),
                "actor": str(actor or "").strip(),
                "root": "/app",
                "source_kind": str(source_kind or "").strip() or "operator",
                "state_path": str(artifact_probe.get("state_path") or "").strip(),
                "receipt_path": str(artifact_probe.get("run_receipt_path") or "").strip(),
                "stage_packet_dir": str(artifact_probe.get("stage_packet_dir") or "").strip(),
                "safe_work_result_dir": str(artifact_probe.get("safe_work_result_dir") or "").strip(),
                "expected_packet_ref": resolved_packet_ref,
                "expected_staged_artifact_ref": resolved_staged_artifact_ref,
            }
        ),
    ]
    source = "docker_compose_exec:record_proactive_approval"
    if _use_in_process_proactive_runtime_fallback():
        source = "in_process_runtime:record_proactive_approval"
        try:
            code = 0
            payload = _record_current_proactive_approval_in_process(
                principal_id=str(principal_id or "").strip(),
                outcome=normalized_outcome,
                evidence=str(evidence or "").strip(),
                actor=str(actor or "").strip(),
                source_kind=str(source_kind or "").strip() or "operator",
                expected_packet_ref=resolved_packet_ref,
                expected_staged_artifact_ref=resolved_staged_artifact_ref,
            )
            stdout = json.dumps(payload, sort_keys=True)
            stderr = ""
        except Exception as exc:
            code = 127
            payload = {}
            stdout = ""
            stderr = f"{type(exc).__name__}:{str(exc or '').strip()}"
    else:
        code, payload, stdout, stderr = _docker_compose_exec_json(
            compose_file=effective_compose_file,
            service=effective_runtime_service,
            command=command,
            timeout_seconds=timeout_seconds,
        )
    if not payload:
        report = {
            **base_report,
            "reason": f"record_failed:exit_{code}",
            "blocking_reason": f"record_failed:exit_{code}",
            "next_action": "inspect_proactive_runtime_container",
            "source": source,
            "stdout_excerpt": stdout.strip()[:200],
            "stderr_excerpt": stderr.strip()[:200],
        }
        if output_format == "operator":
            report["operator_text"] = f"proactive_approval status=record_failed; next=inspect {effective_runtime_service}"
        return report

    teable_sync = dict(payload.get("teable_sync") or {})
    runtime_status = str(payload.get("status") or "").strip()
    already_decided = runtime_status == "already_decided"
    recorded = runtime_status == "recorded" or already_decided
    report = {
        **base_report,
        "recorded": recorded,
        "reason": "recorded" if runtime_status == "recorded" else "already_decided" if already_decided else runtime_status or "record_not_confirmed",
        "accepted": bool(payload.get("approval_outcome_accepted")),
        "source": source,
        "approval_outcome": dict(payload),
        "approval_outcome_id": str(payload.get("approval_outcome_id") or "").strip(),
        "approval_outcome_status": str(payload.get("approval_outcome_status") or "").strip(),
        "approval_outcome_path": str(payload.get("approval_outcome_path") or "").strip(),
        "operator_status_path": str(payload.get("operator_status_path") or "").strip(),
        "gold_acceptance_path": str(payload.get("gold_acceptance_path") or "").strip(),
        "teable_sync": teable_sync,
    }
    if output_format == "operator":
        teable_status = str(teable_sync.get("status") or "unknown").strip() or "unknown"
        operator_status = "recorded" if recorded else runtime_status or "record_not_confirmed"
        report["operator_text"] = (
            f"proactive_approval status={operator_status}; "
            f"outcome={normalized_outcome}; accepted={str(bool(payload.get('approval_outcome_accepted'))).lower()}; "
            f"teable={teable_status}"
        )
    return report


def _redacted_proactive_artifact_probe_summary(
    *,
    artifact_probe: Mapping[str, object],
    packet_ref: str,
    staged_artifact_ref: str,
) -> dict[str, object]:
    current_packet = dict(artifact_probe.get("current_packet") or {})
    return {
        "probe_ok": bool(artifact_probe.get("probe_ok")),
        "source": str(artifact_probe.get("source") or "").strip(),
        "status": str(artifact_probe.get("status") or "").strip(),
        "run_receipt_present": bool(artifact_probe.get("run_receipt")),
        "stage_packet_present": bool(artifact_probe.get("stage_packet")),
        "safe_work_result_present": bool(artifact_probe.get("safe_work_result")),
        "approval_outcome_present": bool(artifact_probe.get("approval_outcome")),
        "approval_outcome_matches_current_packet": bool(
            artifact_probe.get("approval_outcome_matches_current_packet")
            or current_packet.get("approval_outcome_matches_current_packet")
        ),
        "current_packet_status": str(current_packet.get("status") or "").strip(),
        "current_packet_live_pending_count": int(artifact_probe.get("current_packet_live_pending_count") or 0),
        "current_packet_callback_record_count": int(artifact_probe.get("current_packet_callback_record_count") or 0),
        "packet_ref_sha256": _hash_text(packet_ref),
        "staged_artifact_ref_sha256": _hash_text(staged_artifact_ref),
        "raw_stage_packet_exposed": False,
        "raw_safe_work_result_exposed": False,
        "raw_approval_outcome_exposed": False,
        "raw_packet_ref_exposed": False,
        "raw_staged_artifact_ref_exposed": False,
    }


def _current_proactive_approval_recordable(artifact_probe: Mapping[str, object]) -> bool:
    stage_packet = dict(artifact_probe.get("stage_packet") or {})
    safe_work_result = dict(artifact_probe.get("safe_work_result") or {})
    packet_ref = _proactive_stage_packet_ref(stage_packet)
    staged_artifact_ref = _proactive_staged_artifact_ref(safe_work_result)
    stage_approval = dict(stage_packet.get("approval") or {})
    safe_work_approval = dict(safe_work_result.get("approval") or {})
    stage_payload = dict(dict(stage_packet.get("stage") or {}).get("payload") or {})
    approval_required = bool(stage_approval.get("required")) or bool(safe_work_approval.get("required"))
    approval_surface_present = bool(
        str(safe_work_result.get("approval_prompt") or stage_payload.get("approval_prompt") or "").strip()
        or str(safe_work_result.get("staged_action_url") or stage_payload.get("approval_url") or "").strip()
    )
    return bool(
        packet_ref
        and staged_artifact_ref
        and str(safe_work_result.get("status") or "").strip() == "staged_for_user_decision"
        and approval_required
        and approval_surface_present
    )


def reissue_proactive_approval(
    *,
    principal_id: str,
    compose_file: str = "",
    runtime_service: str = "",
    timeout_seconds: float = 60.0,
    dry_run: bool = False,
    force: bool = False,
    reissue_after_seconds: int = 0,
    output_format: str = "json",
) -> dict[str, object]:
    effective_compose_file = str(compose_file or _env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE))).strip()
    effective_runtime_service = str(runtime_service or _env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE)).strip()
    observed_at = _utc_now()
    artifact_probe = probe_proactive_artifacts(
        compose_file=effective_compose_file,
        runtime_service=effective_runtime_service,
        timeout_seconds=timeout_seconds,
        output_format="json",
    )
    base_report: dict[str, object] = {
        "sent": False,
        "reason": "",
        "principal_id": str(principal_id or "").strip(),
        "compose_file": effective_compose_file,
        "runtime_service": effective_runtime_service,
        "observed_at": observed_at,
        "artifact_probe": artifact_probe,
        "approval_capture_surface_ready_before": bool(artifact_probe.get("current_packet_live_pending_count") or 0) > 0,
        "approval_capture_surface_pending_count_before": int(artifact_probe.get("current_packet_live_pending_count") or 0),
    }
    if not bool(artifact_probe.get("probe_ok")):
        report = {
            **base_report,
            "reason": "artifact_probe_failed",
            "blocking_reason": str(artifact_probe.get("blocking_reason") or "artifact_probe_failed").strip(),
            "next_action": "inspect_proactive_runtime_artifacts",
        }
        if output_format == "operator":
            report["operator_text"] = "proactive_approval_reissue status=probe_failed; next=inspect_proactive_runtime_artifacts"
        return report

    command = [
        "python",
        "/app/scripts/reissue_proactive_ooda_approval.py",
        "--principal-id",
        str(principal_id or "").strip(),
        "--state-path",
        str(artifact_probe.get("state_path") or "").strip(),
        "--receipt-path",
        str(artifact_probe.get("run_receipt_path") or "").strip(),
        "--stage-packet-dir",
        str(artifact_probe.get("stage_packet_dir") or "").strip(),
        "--safe-work-result-dir",
        str(artifact_probe.get("safe_work_result_dir") or "").strip(),
    ]
    if dry_run:
        command.append("--dry-run")
    if force:
        command.append("--force")
    if int(reissue_after_seconds or 0) > 0:
        command.extend(["--reissue-after-seconds", str(max(int(reissue_after_seconds or 0), 0))])
    code, payload, stdout, stderr = _docker_compose_exec_json(
        compose_file=effective_compose_file,
        service=effective_runtime_service,
        command=command,
        timeout_seconds=timeout_seconds,
    )
    if not payload:
        report = {
            **base_report,
            "reason": f"reissue_failed:exit_{code}",
            "blocking_reason": f"reissue_failed:exit_{code}",
            "next_action": "inspect_proactive_runtime_container",
            "stdout_excerpt": stdout.strip()[:200],
            "stderr_excerpt": stderr.strip()[:200],
        }
        if output_format == "operator":
            report["operator_text"] = f"proactive_approval_reissue status=failed; next=inspect {effective_runtime_service}"
        return report
    status = str(payload.get("status") or "").strip()
    report = {
        **base_report,
        "sent": status == "sent",
        "reason": str(payload.get("reason") or status or "unknown").strip(),
        "status": status,
        "message_count": int(payload.get("message_count") or 0),
        "message_ids": [
            str(item or "").strip()
            for item in list(payload.get("message_ids") or [])
            if str(item or "").strip()
        ],
        "approval_surface": dict(payload.get("approval_surface") or {}),
        "packet_ref_sha256": str(payload.get("packet_ref_sha256") or "").strip(),
        "staged_artifact_ref_sha256": str(payload.get("staged_artifact_ref_sha256") or "").strip(),
        "approval_prompt_sha256": str(payload.get("approval_prompt_sha256") or "").strip(),
        "staged_action_url_sha256": str(payload.get("staged_action_url_sha256") or "").strip(),
        "has_staged_action_url": bool(payload.get("has_staged_action_url")),
        "stage_kind": str(payload.get("stage_kind") or "").strip(),
        "safe_work_status": str(payload.get("safe_work_status") or "").strip(),
    }
    if output_format == "operator":
        report["operator_text"] = (
            "proactive_approval_reissue "
            f"status={status or 'unknown'} "
            f"sent={str(status == 'sent').lower()} "
            f"messages={int(report['message_count'])} "
            f"surface={str(bool(dict(report.get('approval_surface') or {}).get('present'))).lower()}"
        )
    return report


def _load_whatsapp_binding(args: argparse.Namespace):
    binding_path = str(getattr(args, "binding_json", "") or "").strip()
    database_url = str(args.database_url or _env("DATABASE_URL")).strip()
    binding_id = str(args.binding_id or "").strip()
    principal_id = str(args.principal_id or "").strip()
    if binding_path:
        payload = readiness_script._load_json_file(binding_path)
        binding = readiness_script._binding_from_json(payload, binding_id=binding_id)
        if binding is None and readiness_script._should_fallback_to_latest_binding(binding_id=binding_id, principal_id=principal_id):
            binding = readiness_script._latest_enabled_binding_from_json(payload)
        if binding is not None:
            return binding
    if not database_url:
        return None
    binding = readiness_script._binding_from_postgres(
        database_url,
        binding_id=binding_id,
        principal_id=principal_id,
    )
    if binding is None and readiness_script._should_fallback_to_latest_binding(binding_id=binding_id, principal_id=principal_id):
        binding = readiness_script._binding_from_postgres(database_url, binding_id="", principal_id="")
    return binding


def _safe_load_whatsapp_binding(args: argparse.Namespace) -> tuple[Any | None, str]:
    try:
        return _load_whatsapp_binding(args), ""
    except Exception as exc:
        return None, type(exc).__name__


def _binding_lookup_report_fields(
    binding: Any | None,
    binding_lookup_error: str,
    *,
    recovered: bool = False,
    fallback_source: str = "",
) -> dict[str, object]:
    lookup_error = str(binding_lookup_error or "").strip()
    recovered_after_error = bool(lookup_error and recovered)
    status = (
        "degraded_sidecar_fallback"
        if recovered_after_error
        else "error"
        if lookup_error
        else "found"
        if binding is not None
        else "missing"
    )
    fields: dict[str, object] = {
        "binding_lookup_status": status,
        "binding_lookup_error": lookup_error,
        "binding_lookup_recovered": recovered_after_error,
    }
    if recovered_after_error:
        fields["binding_lookup_fallback_source"] = str(fallback_source or "sidecar").strip()
    return fields


def _session_headers_from_binding(binding: Any | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if binding is not None:
        config = _whatsapp_delivery_config(binding)
        token = str(config.get("token") or "").strip()
        header_name = str(config.get("auth_header_name") or "Authorization").strip() or "Authorization"
        header_prefix = str(config.get("auth_header_prefix") or "").strip()
    else:
        token = _env("EA_WHATSAPP_WEB_SESSION_API_TOKEN")
        header_name = _env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_NAME", "Authorization") or "Authorization"
        header_prefix = _env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_PREFIX", "Bearer ")
    if token:
        headers[header_name] = f"{header_prefix}{token}".strip()
    return headers


def _session_api_base_url(binding: Any | None, explicit_base_url: str = "") -> str:
    if str(explicit_base_url or "").strip():
        return str(explicit_base_url).rstrip("/")
    if binding is not None:
        config = _whatsapp_delivery_config(binding)
        template = str(config.get("endpoint_template") or "").strip()
        if "/sessions/" in template:
            return template.split("/sessions/", 1)[0].rstrip("/")
    return _env("EA_WHATSAPP_WEB_SESSION_API_BASE_URL", DEFAULT_SESSION_API_BASE_URL).rstrip("/")


def _whatsapp_delivery_config(binding: Any | None) -> dict[str, Any]:
    if binding is None:
        return {}
    try:
        return dict(whatsapp_web_session_delivery.resolve_whatsapp_web_session_delivery_config(binding))
    except Exception:
        return {}


def _session_ref(binding: Any | None, explicit_session_ref: str = "") -> str:
    if str(explicit_session_ref or "").strip():
        return str(explicit_session_ref).strip()
    if binding is not None:
        config = _whatsapp_delivery_config(binding)
        configured = str(config.get("session_ref") or "").strip()
        if configured:
            return configured
    env_value = _env("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF")
    if env_value:
        return env_value
    receipt = _whatsapp_readiness_receipt()
    return str(receipt.get("effective_session_ref") or receipt.get("session_ref") or "").strip()


def _sidecar_get(*, binding: Any | None, suffix: str, session_api_base_url: str = "", session_ref: str = "", timeout_seconds: float = 15.0) -> dict[str, Any]:
    base_url = _session_api_base_url(binding, session_api_base_url)
    effective_session_ref = urllib.parse.quote(_session_ref(binding, session_ref), safe="")
    return _request_json(
        method="GET",
        url=f"{base_url}/sessions/{effective_session_ref}/{suffix.lstrip('/')}",
        headers=_session_headers_from_binding(binding),
        timeout=timeout_seconds,
    )


def _sidecar_bytes(*, binding: Any | None, suffix: str, session_api_base_url: str = "", session_ref: str = "", timeout_seconds: float = 15.0) -> tuple[bytes, str, str]:
    base_url = _session_api_base_url(binding, session_api_base_url)
    effective_session_ref = urllib.parse.quote(_session_ref(binding, session_ref), safe="")
    url = f"{base_url}/sessions/{effective_session_ref}/{suffix.lstrip('/')}"
    payload, content_type = _request_bytes(
        method="GET",
        url=url,
        headers=_session_headers_from_binding(binding),
        timeout=timeout_seconds,
    )
    return payload, content_type, url


def _sidecar_post(*, binding: Any | None, suffix: str, body: dict[str, object], session_api_base_url: str = "", session_ref: str = "", timeout_seconds: float = 15.0) -> dict[str, Any]:
    base_url = _session_api_base_url(binding, session_api_base_url)
    effective_session_ref = urllib.parse.quote(_session_ref(binding, session_ref), safe="")
    return _request_json(
        method="POST",
        url=f"{base_url}/sessions/{effective_session_ref}/{suffix.lstrip('/')}",
        headers=_session_headers_from_binding(binding),
        body=body,
        timeout=timeout_seconds,
    )


def _match_route(route: dict[str, object], phone_hint: str) -> bool:
    normalized_hint = _normalize_phone_hint(phone_hint)
    if normalized_hint in {"", "*", "default"}:
        return str(route.get("route_key") or "").strip() in {"default", "*"}
    candidates = {
        _digits(route.get("inbound_number_digits")),
        _digits(route.get("route_key")),
    }
    return any(candidate.endswith(normalized_hint) for candidate in candidates if candidate)


def _recent_chat_ref_for_hint(conversations_payload: dict[str, object], phone_hint: str) -> str:
    return _recent_conversation_match(conversations_payload, phone_hint).get("chat_ref", "")


def _recent_sender_digits_for_hint(conversations_payload: dict[str, object], phone_hint: str) -> str:
    return _recent_conversation_match(conversations_payload, phone_hint, include_outbound_sender_digits=True).get("sender_digits", "")


def _recent_conversation_match(
    conversations_payload: dict[str, object],
    phone_hint: str,
    *,
    include_outbound_sender_digits: bool = False,
) -> dict[str, str]:
    normalized_hint = _normalize_phone_hint(phone_hint)
    if not normalized_hint or normalized_hint in {"*", "default"}:
        return {}
    matches: list[tuple[str, str, str]] = []
    for conversation in conversations_payload.get("conversations") or []:
        if not isinstance(conversation, dict):
            continue
        chat_ref = str(conversation.get("chat_ref") or "").strip()
        if not chat_ref:
            continue
        sender_candidates = {
            _digits(conversation.get("recipient")),
        }
        latest_message_timestamp = ""
        for message in conversation.get("messages") or []:
            if isinstance(message, dict):
                message_timestamp = str(message.get("message_timestamp") or "").strip()
                if message_timestamp > latest_message_timestamp:
                    latest_message_timestamp = message_timestamp
                direction = str(message.get("direction") or "").strip().lower()
                from_me = bool(message.get("from_me"))
                if include_outbound_sender_digits or (not from_me and direction != "outbound"):
                    sender_candidates.add(_digits(message.get("sender_digits")))
        matched_sender = next(
            (candidate for candidate in sorted(sender_candidates) if candidate and candidate.endswith(normalized_hint)),
            "",
        )
        if matched_sender:
            sort_timestamp = str(
                conversation.get("updated_at")
                or conversation.get("last_message_at")
                or conversation.get("timestamp")
                or latest_message_timestamp
                or ""
            ).strip()
            matches.append(
                (
                    sort_timestamp,
                    chat_ref,
                    matched_sender,
                )
            )
    matches.sort()
    if not matches:
        return {}
    _, chat_ref, sender_digits = matches[-1]
    return {"chat_ref": chat_ref, "sender_digits": sender_digits}


def resolve_whatsapp(phone_hint: str, *, args: argparse.Namespace) -> dict[str, object]:
    binding, binding_lookup_error = _safe_load_whatsapp_binding(args)
    normalized_hint = _normalize_phone_hint(phone_hint)
    try:
        routes_payload = _sidecar_get(
            binding=binding,
            suffix="heyy-ai-routes",
            session_api_base_url=str(getattr(args, "session_api_base_url", "") or "").strip(),
            session_ref=str(getattr(args, "session_ref", "") or "").strip(),
            timeout_seconds=float(getattr(args, "timeout_seconds", 15.0) or 15.0),
        )
    except urllib.error.HTTPError as exc:
        routes_payload = _http_error_payload(exc)
    except Exception as exc:
        routes_payload = {"ok": False, "reason": type(exc).__name__, "status": "unavailable", "status_code": 0}
    try:
        conversations_payload = _sidecar_get(
            binding=binding,
            suffix="conversations?take=50&messages=1&fetch_timeout_ms=5000",
            session_api_base_url=str(getattr(args, "session_api_base_url", "") or "").strip(),
            session_ref=str(getattr(args, "session_ref", "") or "").strip(),
            timeout_seconds=float(getattr(args, "timeout_seconds", 15.0) or 15.0),
        )
    except urllib.error.HTTPError as exc:
        conversations_payload = _http_error_payload(exc)
    except Exception as exc:
        conversations_payload = {"ok": False, "reason": type(exc).__name__, "status": "unavailable", "status_code": 0}
    routes = [dict(row) for row in routes_payload.get("routes") or [] if isinstance(row, dict)]
    matched_routes = [row for row in routes if _match_route(row, phone_hint)]
    recent_sender_digits = _recent_sender_digits_for_hint(conversations_payload, phone_hint)
    if recent_sender_digits:
        narrowed_routes = [
            row
            for row in matched_routes
            if _digits(row.get("inbound_number_digits") or row.get("route_key")).endswith(recent_sender_digits)
        ]
        if len(narrowed_routes) == 1:
            matched_routes = narrowed_routes
    route = matched_routes[0] if len(matched_routes) == 1 else {}
    recipient_digits = _digits(route.get("inbound_number_digits") or route.get("route_key") or recent_sender_digits)
    if not route and normalized_hint and recipient_digits == normalized_hint:
        recipient_digits = ""
    recipient_payload: dict[str, Any] = {}
    if recipient_digits:
        try:
            recipient_payload = _sidecar_get(
                binding=binding,
                suffix=f"recipients/{urllib.parse.quote(recipient_digits, safe='')}",
                session_api_base_url=str(getattr(args, "session_api_base_url", "") or "").strip(),
                session_ref=str(getattr(args, "session_ref", "") or "").strip(),
                timeout_seconds=float(getattr(args, "timeout_seconds", 15.0) or 15.0),
            )
        except Exception as exc:
            recipient_payload = {"registered": False, "reason": type(exc).__name__}
    chat_ref = str(recipient_payload.get("chat_ref") or "").strip() or _recent_chat_ref_for_hint(conversations_payload, phone_hint)
    routes_ready = bool(routes_payload.get("ok", True))
    route_reason = str(routes_payload.get("reason") or "").strip()
    conversations_ready = bool(conversations_payload.get("ok", True))
    sidecar_reason = str(conversations_payload.get("reason") or "").strip()
    status = (
        "resolved"
        if route
        else "ambiguous"
        if len(matched_routes) > 1
        else "unresolved"
    )
    if not routes_ready:
        status = "blocked"
    if not conversations_ready and status != "resolved":
        status = "blocked"
    binding_lookup_recovered = bool(binding_lookup_error and routes_ready and (conversations_ready or status == "resolved"))
    binding_lookup_reason = "" if binding_lookup_recovered else binding_lookup_error
    return {
        "status": status,
        "reason": route_reason if not routes_ready else sidecar_reason if not conversations_ready else binding_lookup_reason,
        "phone_hint": str(phone_hint or ""),
        "recipient_digits": recipient_digits,
        "binding_id": str(getattr(binding, "binding_id", "") or ""),
        "principal_id": str(getattr(binding, "principal_id", "") or ""),
        "session_ref": _session_ref(binding, str(getattr(args, "session_ref", "") or "").strip()),
        **_binding_lookup_report_fields(
            binding,
            binding_lookup_error,
            recovered=binding_lookup_recovered,
            fallback_source="whatsapp_web_session_sidecar",
        ),
        "route_key": str(route.get("route_key") or "").strip(),
        "ai_key": str(route.get("ai_key") or "").strip(),
        "ai_name": str(route.get("ai_name") or "").strip(),
        "auto_reply_enabled": bool(route.get("auto_reply_enabled")) if route else False,
        "chat_ref": chat_ref,
        "registered": bool(recipient_payload.get("registered")),
        "resolution_method": str(recipient_payload.get("resolution_method") or "").strip(),
        "chat_id_kind": str(recipient_payload.get("chat_id_kind") or "").strip(),
        "route_lookup_ready": routes_ready,
        "route_lookup_status": str(routes_payload.get("status") or "").strip(),
        "route_lookup_status_code": int(routes_payload.get("status_code") or 0),
        "conversation_lookup_ready": conversations_ready,
        "conversation_lookup_status": str(conversations_payload.get("status") or "").strip(),
        "conversation_lookup_status_code": int(conversations_payload.get("status_code") or 0),
        "candidate_count": len(matched_routes),
        "candidates": [
            {
                "route_key": str(item.get("route_key") or "").strip(),
                "inbound_number_digits": str(item.get("inbound_number_digits") or "").strip(),
                "ai_key": str(item.get("ai_key") or "").strip(),
                "ai_name": str(item.get("ai_name") or "").strip(),
            }
            for item in matched_routes[:5]
        ],
    }


def _operator_whatsapp_sidecar_body(*, resolution: dict[str, object], text: str) -> dict[str, object]:
    body: dict[str, object] = {
        "text": str(text or ""),
        "pre_reply_delay_min_seconds": 0,
        "pre_reply_delay_max_seconds": 0,
        "typing_delay_ms": 0,
        "typing_delay_ms_per_character": 0,
        "typing_status_enabled": False,
    }
    chat_ref = str(resolution.get("chat_ref") or "").strip()
    recipient_digits = str(resolution.get("recipient_digits") or "").strip()
    if chat_ref:
        body["chat_ref"] = chat_ref
    elif recipient_digits:
        body["to"] = recipient_digits
    return body


def _whatsapp_send_binding_lookup_fields(
    *,
    binding: Any | None,
    binding_lookup_error: str,
    resolution: Mapping[str, object],
) -> dict[str, object]:
    recovered = bool(
        binding_lookup_error
        and str(resolution.get("status") or "").strip() == "resolved"
    )
    return _binding_lookup_report_fields(
        binding,
        binding_lookup_error,
        recovered=recovered,
        fallback_source="whatsapp_web_session_sidecar_send",
    )


def _whatsapp_send_failure_report(
    *,
    reason: str,
    resolution: dict[str, object],
    binding: Any | None,
    binding_lookup_error: str,
    recipient_digits: str,
    chat_ref: str,
    retry_attempted: bool = False,
) -> dict[str, object]:
    return {
        "sent": False,
        "reason": str(reason or "send_failed").strip() or "send_failed",
        "binding_id": str(getattr(binding, "binding_id", "") or ""),
        "principal_id": str(getattr(binding, "principal_id", "") or ""),
        **_whatsapp_send_binding_lookup_fields(
            binding=binding,
            binding_lookup_error=binding_lookup_error,
            resolution=resolution,
        ),
        "recipient_digits": recipient_digits,
        "delivery_transport": "whatsapp_web_session_sidecar",
        "message_ids": [],
        "request_url_present": False,
        "chat_ref_used": bool(chat_ref),
        "retry_attempted": retry_attempted,
        "resolution": resolution,
    }


def send_whatsapp(*, phone_hint: str, text: str, args: argparse.Namespace) -> dict[str, object]:
    resolution = resolve_whatsapp(phone_hint, args=args)
    binding, binding_lookup_error = _safe_load_whatsapp_binding(args)
    recipient_digits = str(resolution.get("recipient_digits") or "").strip()
    chat_ref = str(resolution.get("chat_ref") or "").strip()
    if not recipient_digits:
        return {
            "sent": False,
            "reason": "recipient_unresolved",
            "resolution": resolution,
            **_whatsapp_send_binding_lookup_fields(
                binding=binding,
                binding_lookup_error=binding_lookup_error,
                resolution=resolution,
            ),
        }
    if str(resolution.get("status") or "").strip() == "blocked" and not bool(resolution.get("route_lookup_ready", True)):
        return {
            "sent": False,
            "reason": "route_lookup_unavailable",
            "resolution": resolution,
            **_whatsapp_send_binding_lookup_fields(
                binding=binding,
                binding_lookup_error=binding_lookup_error,
                resolution=resolution,
            ),
        }
    if bool(getattr(args, "dry_run", False)):
        return {
            "sent": False,
            "reason": "dry_run",
            "resolution": resolution,
            "binding_id": str(getattr(binding, "binding_id", "") or ""),
            "principal_id": str(getattr(binding, "principal_id", "") or ""),
            **_whatsapp_send_binding_lookup_fields(
                binding=binding,
                binding_lookup_error=binding_lookup_error,
                resolution=resolution,
            ),
            "recipient_digits": recipient_digits,
        }
    try:
        payload = _sidecar_post(
            binding=binding,
            suffix="messages",
            body=_operator_whatsapp_sidecar_body(resolution=resolution, text=text),
            session_api_base_url=str(getattr(args, "session_api_base_url", "") or "").strip(),
            session_ref=str(getattr(args, "session_ref", "") or "").strip(),
            timeout_seconds=float(getattr(args, "timeout_seconds", 15.0) or 15.0),
        )
    except Exception as exc:
        return _whatsapp_send_failure_report(
            reason=type(exc).__name__,
            resolution=resolution,
            binding=binding,
            binding_lookup_error=binding_lookup_error,
            recipient_digits=recipient_digits,
            chat_ref=chat_ref,
        )
    if not bool(payload.get("ok", True)) and chat_ref and recipient_digits and str(payload.get("reason") or "").strip() == "chat_ref_not_found":
        try:
            payload = _sidecar_post(
                binding=binding,
                suffix="messages",
                body={
                    "to": recipient_digits,
                    "text": str(text or ""),
                    "pre_reply_delay_min_seconds": 0,
                    "pre_reply_delay_max_seconds": 0,
                    "typing_delay_ms": 0,
                    "typing_delay_ms_per_character": 0,
                    "typing_status_enabled": False,
                },
                session_api_base_url=str(getattr(args, "session_api_base_url", "") or "").strip(),
                session_ref=str(getattr(args, "session_ref", "") or "").strip(),
                timeout_seconds=float(getattr(args, "timeout_seconds", 15.0) or 15.0),
            )
        except Exception as exc:
            return _whatsapp_send_failure_report(
                reason=type(exc).__name__,
                resolution=resolution,
                binding=binding,
                binding_lookup_error=binding_lookup_error,
                recipient_digits=recipient_digits,
                chat_ref=chat_ref,
                retry_attempted=True,
            )
    message_ids = [str(value or "").strip() for value in payload.get("message_ids") or [] if str(value or "").strip()]
    return {
        "sent": bool(payload.get("ok", True)),
        "reason": "sent" if bool(payload.get("ok", True)) else str(payload.get("reason") or "send_failed").strip(),
        "binding_id": str(getattr(binding, "binding_id", "") or ""),
        "principal_id": str(getattr(binding, "principal_id", "") or ""),
        **_whatsapp_send_binding_lookup_fields(
            binding=binding,
            binding_lookup_error=binding_lookup_error,
            resolution=resolution,
        ),
        "recipient_digits": recipient_digits,
        "delivery_transport": "whatsapp_web_session_sidecar",
        "message_ids": message_ids,
        "request_url_present": True,
        "chat_ref_used": bool(chat_ref),
        "resolution": resolution,
    }


def _sidecar_pairing_url(*, binding: Any | None, session_api_base_url: str = "", session_ref: str = "", suffix: str = "pair") -> str:
    base_url = _session_api_base_url(binding, session_api_base_url)
    effective_session_ref = urllib.parse.quote(_session_ref(binding, session_ref), safe="")
    return f"{base_url}/sessions/{effective_session_ref}/{suffix.lstrip('/')}"


def _url_scope(url: str) -> str:
    parsed = urllib.parse.urlparse(str(url or ""))
    host = str(parsed.hostname or "").strip().lower()
    if host in {"", "localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return "host_local"
    if "." not in host or host.endswith(".local") or host.endswith(".internal"):
        return "internal_network"
    return "public"


def _pairing_qr_output_path(session_ref: str, output_dir: str = "") -> Path:
    safe_ref = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(session_ref or "default").strip()).strip("-") or "default"
    root = Path(output_dir or _env("EA_WHATSAPP_WEB_PAIRING_QR_DIR", str(ROOT / ".runtime" / "whatsapp-pairing")))
    return root / f"{safe_ref}.svg"


def _write_pairing_qr_svg(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_bytes(payload)
    tmp.chmod(0o600)
    os.replace(tmp, path)


def _pair_url_actionable_from_telegram(pair_url_scope: str) -> bool:
    return str(pair_url_scope or "").strip() == "public"


def _whatsapp_pairing_telegram_caption(
    *,
    session_ref: str,
    status: str,
    qr_age_seconds: int | None,
    pair_url: str,
    pair_url_scope: str,
) -> str:
    lines = [
        "EA WhatsApp Web pairing is required.",
        f"session={str(session_ref or '').strip()}",
        f"status={str(status or '').strip()}",
        f"qr_age_seconds={qr_age_seconds if qr_age_seconds is not None else 'unknown'}",
        "action=Open WhatsApp > Linked devices > Link a device, then scan the attached QR.",
    ]
    if _pair_url_actionable_from_telegram(pair_url_scope):
        lines.append(f"pair_url={str(pair_url or '').strip()}")
    else:
        lines.append(f"pair_url_scope={str(pair_url_scope or '').strip() or 'unknown'}")
        lines.append("pair_url_note=Local pairing URLs are only usable from the EA host; use the attached QR on your phone.")
    return "\n".join(line for line in lines if str(line).strip()).strip()


def _qr_age_seconds(last_qr_at: object, *, now: datetime | None = None) -> int | None:
    raw = str(last_qr_at or "").strip()
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    return max(0, int((current - parsed.astimezone(UTC)).total_seconds()))


def send_telegram_document(
    *,
    principal_id: str,
    document_ref: str,
    caption: str = "",
    dry_run: bool = False,
    timeout_seconds: float = 30.0,
) -> dict[str, object]:
    normalized_principal_id = str(principal_id or "").strip()
    normalized_document_ref = str(document_ref or "").strip()
    normalized_caption = str(caption or "").strip()
    observed_at = _utc_now()
    effective_timeout_seconds = max(float(timeout_seconds or 30.0), 1.0)
    if not normalized_document_ref:
        return {
            "sent": False,
            "reason": "document_ref_missing",
            "principal_id": normalized_principal_id,
            "delivery_transport": "telegram_bot",
            "timeout_seconds": effective_timeout_seconds,
            "observed_at": observed_at,
            "source": "runtime_container_exec:telegram_delivery.send_telegram_document_for_principal",
        }
    if dry_run:
        readiness_timeout_seconds = _telegram_dry_run_timeout_seconds(effective_timeout_seconds)
        readiness = probe_telegram_readiness(
            principal_id=normalized_principal_id,
            timeout_seconds=readiness_timeout_seconds,
            output_format="json",
        )
        return {
            "sent": False,
            "reason": "dry_run",
            "readiness_probe_ok": bool(readiness.get("probe_ok")),
            "ready": bool(readiness.get("ready")),
            "readiness_status": str(readiness.get("status") or "").strip(),
            "readiness_reason": str(readiness.get("reason") or "").strip(),
            "principal_id": str(readiness.get("principal_id") or normalized_principal_id).strip(),
            "binding_id": str(readiness.get("binding_id") or "").strip(),
            "next_action": str(readiness.get("next_action") or "").strip(),
            "next_action_href": str(readiness.get("next_action_href") or "").strip(),
            "next_action_label": str(readiness.get("next_action_label") or "").strip(),
            "next_action_method": str(readiness.get("next_action_method") or "").strip(),
            "chat_ref_present": bool(readiness.get("chat_ref_present")),
            "chat_ref_sha256": str(readiness.get("chat_ref_sha256") or "").strip(),
            "bot_key": str(readiness.get("bot_key") or "").strip(),
            "bot_handle": str(readiness.get("bot_handle") or "").strip(),
            "bot_token_present": bool(readiness.get("bot_token_present")),
            "document_ref_present": bool(normalized_document_ref),
            "caption_present": bool(normalized_caption),
            "delivery_transport": "telegram_bot",
            "runtime_container": str(readiness.get("runtime_container") or "").strip(),
            "timeout_seconds": effective_timeout_seconds,
            "observed_at": observed_at,
            "source": "runtime_container_exec:telegram_delivery.send_telegram_document_for_principal",
        }
    document_ref_for_runtime = normalized_document_ref
    staged_container = ""
    staged_remote_path = ""
    local_file_staged = False
    if Path(normalized_document_ref).is_file():
        staged, staged_container, staged_remote_path, stage_reason = _runtime_container_stage_file(
            Path(normalized_document_ref),
            timeout_seconds=20.0,
        )
        if not staged:
            if staged_remote_path:
                _runtime_container_remove_file(staged_container, staged_remote_path)
            return {
                "sent": False,
                "reason": stage_reason or "telegram_document_stage_failed",
                "principal_id": normalized_principal_id,
                "delivery_transport": "telegram_bot",
                "document_ref_present": True,
                "local_file_staged": False,
                "runtime_container": staged_container,
                "observed_at": observed_at,
                "source": "runtime_container_exec:telegram_delivery.send_telegram_document_for_principal",
            }
        document_ref_for_runtime = staged_remote_path
        local_file_staged = True
    code = (
        "import hashlib, json, os\n"
        "principal_id = "
        + json.dumps(normalized_principal_id)
        + "\n"
        "document_ref = "
        + json.dumps(document_ref_for_runtime)
        + "\n"
        "caption = "
        + json.dumps(normalized_caption)
        + "\n"
        "try:\n"
        "    from app.settings import get_settings\n"
        "    from app.services.telegram_delivery import send_telegram_document_for_principal\n"
        "    from app.services.tool_runtime import build_tool_runtime\n"
        "    tool_runtime = build_tool_runtime(get_settings())\n"
        "    receipt = send_telegram_document_for_principal(tool_runtime, principal_id=principal_id, document_ref=document_ref, caption=caption)\n"
        "    chat_ref = str(getattr(receipt, 'chat_id', '') or '').strip()\n"
        "    message_ids = [str(item or '').strip() for item in (getattr(receipt, 'message_ids', ()) or ()) if str(item or '').strip()]\n"
        "    print(json.dumps({\n"
        "        'ok': True,\n"
        "        'sent': True,\n"
        "        'reason': 'sent',\n"
        "        'principal_id': str(getattr(receipt, 'principal_id', '') or principal_id or '').strip(),\n"
        "        'chat_ref_present': bool(chat_ref),\n"
        "        'chat_ref_sha256': hashlib.sha256(chat_ref.encode('utf-8')).hexdigest() if chat_ref else '',\n"
        "        'bot_key': str(getattr(receipt, 'bot_key', '') or '').strip(),\n"
        "        'bot_handle': str(getattr(receipt, 'bot_handle', '') or '').strip(),\n"
        "        'message_ids': message_ids,\n"
        "    }, sort_keys=True), flush=True)\n"
        "    os._exit(0)\n"
        "except Exception as exc:\n"
        "    reason = (str(exc).strip() or type(exc).__name__)[:160]\n"
        "    print(json.dumps({'ok': False, 'sent': False, 'reason': reason}, sort_keys=True), flush=True)\n"
        "    os._exit(0)\n"
    )
    try:
        exit_code, payload, runtime_container = _runtime_container_exec_json(code=code, timeout_seconds=45.0)
    finally:
        if staged_remote_path:
            _runtime_container_remove_file(staged_container, staged_remote_path)
    payload_ok = bool(payload.get("ok", False))
    sent = exit_code == 0 and payload_ok and bool(payload.get("sent"))
    reason = str(payload.get("reason") or "").strip() or (f"runtime_container_exec_exit_{exit_code}" if exit_code else "send_failed")
    message_ids = [str(item or "").strip() for item in payload.get("message_ids") or [] if str(item or "").strip()]
    return {
        "sent": sent,
        "reason": "sent" if sent else reason,
        "principal_id": str(payload.get("principal_id") or normalized_principal_id).strip(),
        "chat_ref_present": bool(payload.get("chat_ref_present")),
        "chat_ref_sha256": str(payload.get("chat_ref_sha256") or "").strip(),
        "bot_key": str(payload.get("bot_key") or "").strip(),
        "bot_handle": str(payload.get("bot_handle") or "").strip(),
        "delivery_transport": "telegram_bot",
        "message_ids": message_ids,
        "message_count": len(message_ids),
        "runtime_container": runtime_container,
        "document_ref_present": True,
        "local_file_staged": local_file_staged,
        "observed_at": observed_at,
        "source": "runtime_container_exec:telegram_delivery.send_telegram_document_for_principal",
    }


def send_telegram_video(
    *,
    principal_id: str,
    video_ref: str,
    caption: str = "",
    fallback_audio_text: str = "",
    fallback_audio_language: str = "",
    dry_run: bool = False,
    timeout_seconds: float = 30.0,
) -> dict[str, object]:
    normalized_principal_id = str(principal_id or "").strip()
    normalized_video_ref = str(video_ref or "").strip()
    normalized_caption = str(caption or "").strip()
    normalized_fallback_audio_text = str(fallback_audio_text or "").strip()
    normalized_fallback_audio_language = str(fallback_audio_language or "").strip()
    observed_at = _utc_now()
    effective_timeout_seconds = max(float(timeout_seconds or 30.0), 1.0)
    source = "runtime_container_exec:telegram_delivery.send_telegram_video_for_principal"
    if not normalized_video_ref:
        return {
            "sent": False,
            "reason": "video_ref_missing",
            "principal_id": normalized_principal_id,
            "delivery_transport": "telegram_bot",
            "timeout_seconds": effective_timeout_seconds,
            "observed_at": observed_at,
            "source": source,
        }
    if dry_run:
        readiness_timeout_seconds = _telegram_dry_run_timeout_seconds(effective_timeout_seconds)
        readiness = probe_telegram_readiness(
            principal_id=normalized_principal_id,
            timeout_seconds=readiness_timeout_seconds,
            output_format="json",
        )
        return {
            "sent": False,
            "reason": "dry_run",
            "readiness_probe_ok": bool(readiness.get("probe_ok")),
            "ready": bool(readiness.get("ready")),
            "readiness_status": str(readiness.get("status") or "").strip(),
            "readiness_reason": str(readiness.get("reason") or "").strip(),
            "principal_id": str(readiness.get("principal_id") or normalized_principal_id).strip(),
            "binding_id": str(readiness.get("binding_id") or "").strip(),
            "next_action": str(readiness.get("next_action") or "").strip(),
            "next_action_href": str(readiness.get("next_action_href") or "").strip(),
            "next_action_label": str(readiness.get("next_action_label") or "").strip(),
            "next_action_method": str(readiness.get("next_action_method") or "").strip(),
            "chat_ref_present": bool(readiness.get("chat_ref_present")),
            "chat_ref_sha256": str(readiness.get("chat_ref_sha256") or "").strip(),
            "bot_key": str(readiness.get("bot_key") or "").strip(),
            "bot_handle": str(readiness.get("bot_handle") or "").strip(),
            "bot_token_present": bool(readiness.get("bot_token_present")),
            "video_ref_present": True,
            "caption_present": bool(normalized_caption),
            "fallback_audio_text_present": bool(normalized_fallback_audio_text),
            "delivery_transport": "telegram_bot",
            "runtime_container": str(readiness.get("runtime_container") or "").strip(),
            "timeout_seconds": effective_timeout_seconds,
            "observed_at": observed_at,
            "source": source,
        }
    video_ref_for_runtime = normalized_video_ref
    staged_container = ""
    staged_remote_path = ""
    local_file_staged = False
    if Path(normalized_video_ref).is_file():
        staged, staged_container, staged_remote_path, stage_reason = _runtime_container_stage_file(
            Path(normalized_video_ref),
            timeout_seconds=20.0,
        )
        if not staged:
            if staged_remote_path:
                _runtime_container_remove_file(staged_container, staged_remote_path)
            return {
                "sent": False,
                "reason": stage_reason or "telegram_video_stage_failed",
                "principal_id": normalized_principal_id,
                "delivery_transport": "telegram_bot",
                "video_ref_present": True,
                "local_file_staged": False,
                "runtime_container": staged_container,
                "observed_at": observed_at,
                "source": source,
            }
        video_ref_for_runtime = staged_remote_path
        local_file_staged = True
    code = (
        "import hashlib, json, os\n"
        "principal_id = "
        + json.dumps(normalized_principal_id)
        + "\n"
        "video_ref = "
        + json.dumps(video_ref_for_runtime)
        + "\n"
        "caption = "
        + json.dumps(normalized_caption)
        + "\n"
        "fallback_audio_text = "
        + json.dumps(normalized_fallback_audio_text)
        + "\n"
        "fallback_audio_language = "
        + json.dumps(normalized_fallback_audio_language)
        + "\n"
        "try:\n"
        "    from app.settings import get_settings\n"
        "    from app.services.telegram_delivery import send_telegram_video_for_principal\n"
        "    from app.services.tool_runtime import build_tool_runtime\n"
        "    tool_runtime = build_tool_runtime(get_settings())\n"
        "    receipt = send_telegram_video_for_principal(tool_runtime, principal_id=principal_id, video_ref=video_ref, fallback_audio_text=fallback_audio_text, fallback_audio_language=fallback_audio_language, caption=caption)\n"
        "    chat_ref = str(getattr(receipt, 'chat_id', '') or '').strip()\n"
        "    message_ids = [str(item or '').strip() for item in (getattr(receipt, 'message_ids', ()) or ()) if str(item or '').strip()]\n"
        "    print(json.dumps({\n"
        "        'ok': True,\n"
        "        'sent': True,\n"
        "        'reason': 'sent',\n"
        "        'principal_id': str(getattr(receipt, 'principal_id', '') or principal_id or '').strip(),\n"
        "        'chat_ref_present': bool(chat_ref),\n"
        "        'chat_ref_sha256': hashlib.sha256(chat_ref.encode('utf-8')).hexdigest() if chat_ref else '',\n"
        "        'bot_key': str(getattr(receipt, 'bot_key', '') or '').strip(),\n"
        "        'bot_handle': str(getattr(receipt, 'bot_handle', '') or '').strip(),\n"
        "        'message_ids': message_ids,\n"
        "    }, sort_keys=True), flush=True)\n"
        "    os._exit(0)\n"
        "except Exception as exc:\n"
        "    reason = (str(exc).strip() or type(exc).__name__)[:160]\n"
        "    print(json.dumps({'ok': False, 'sent': False, 'reason': reason}, sort_keys=True), flush=True)\n"
        "    os._exit(0)\n"
    )
    try:
        exit_code, payload, runtime_container = _runtime_container_exec_json(
            code=code,
            timeout_seconds=max(effective_timeout_seconds, 120.0),
        )
    finally:
        if staged_remote_path:
            _runtime_container_remove_file(staged_container, staged_remote_path)
    payload_ok = bool(payload.get("ok", False))
    sent = exit_code == 0 and payload_ok and bool(payload.get("sent"))
    reason = str(payload.get("reason") or "").strip() or (f"runtime_container_exec_exit_{exit_code}" if exit_code else "send_failed")
    message_ids = [str(item or "").strip() for item in payload.get("message_ids") or [] if str(item or "").strip()]
    return {
        "sent": sent,
        "reason": "sent" if sent else reason,
        "principal_id": str(payload.get("principal_id") or normalized_principal_id).strip(),
        "chat_ref_present": bool(payload.get("chat_ref_present")),
        "chat_ref_sha256": str(payload.get("chat_ref_sha256") or "").strip(),
        "bot_key": str(payload.get("bot_key") or "").strip(),
        "bot_handle": str(payload.get("bot_handle") or "").strip(),
        "delivery_transport": "telegram_bot",
        "message_ids": message_ids,
        "message_count": len(message_ids),
        "runtime_container": runtime_container,
        "video_ref_present": True,
        "local_file_staged": local_file_staged,
        "observed_at": observed_at,
        "source": source,
    }


def probe_whatsapp_pairing(
    *,
    args: argparse.Namespace,
    output_format: str = "json",
    send_telegram_to_principal: str = "",
    dry_run: bool = False,
    write_qr_svg: bool = True,
    output_dir: str = "",
    telegram_operator_streams: tuple[str, ...] | str | None = None,
) -> dict[str, object]:
    observed_at = _utc_now()
    binding, binding_lookup_error = _safe_load_whatsapp_binding(args)
    base_url = _session_api_base_url(binding, str(getattr(args, "session_api_base_url", "") or "").strip())
    session_ref = _session_ref(binding, str(getattr(args, "session_ref", "") or "").strip())
    pair_url = _sidecar_pairing_url(binding=binding, session_api_base_url=base_url, session_ref=session_ref, suffix="pair")
    qr_svg_url = _sidecar_pairing_url(binding=binding, session_api_base_url=base_url, session_ref=session_ref, suffix="qr.svg")
    try:
        payload = _sidecar_get(
            binding=binding,
            suffix="qr",
            session_api_base_url=base_url,
            session_ref=session_ref,
            timeout_seconds=float(getattr(args, "timeout_seconds", 15.0) or 15.0),
        )
    except urllib.error.HTTPError as exc:
        payload = _http_error_payload(exc)
    except Exception as exc:
        payload = {"ok": False, "reason": type(exc).__name__, "status": "unavailable"}

    ok = bool(payload.get("ok", True))
    ready = bool(payload.get("ready"))
    qr_present = bool(payload.get("qr_present"))
    qr_required = bool(payload.get("qr_required"))
    sidecar_status = str(payload.get("status") or "").strip()
    reason = "" if ok else str(payload.get("reason") or "sidecar_qr_probe_failed").strip()
    age_seconds = _qr_age_seconds(payload.get("last_qr_at"))
    qr_fresh_seconds = 120
    qr_fresh = age_seconds is not None and age_seconds <= qr_fresh_seconds
    if ready:
        status = "ready"
        next_action = ""
    elif qr_present:
        status = "available"
        next_action = "scan_whatsapp_web_qr"
    elif ok:
        status = "waiting"
        next_action = "wait_for_whatsapp_web_qr"
    else:
        status = "blocked"
        next_action = "inspect_whatsapp_web_session_sidecar"

    qr_svg_path = _pairing_qr_output_path(session_ref, output_dir=output_dir)
    qr_svg_written = False
    qr_svg_error = ""
    if write_qr_svg and qr_present:
        try:
            svg_payload, content_type, _ = _sidecar_bytes(
                binding=binding,
                suffix="qr.svg",
                session_api_base_url=base_url,
                session_ref=session_ref,
                timeout_seconds=float(getattr(args, "timeout_seconds", 15.0) or 15.0),
            )
            if svg_payload:
                _write_pairing_qr_svg(qr_svg_path, svg_payload)
                qr_svg_written = True
            else:
                qr_svg_error = "empty_qr_svg"
        except Exception as exc:
            content_type = ""
            qr_svg_error = type(exc).__name__
    else:
        content_type = ""

    report: dict[str, object] = {
        "probe_ok": ok,
        "status": status,
        "ready": ready,
        "reason": reason,
        "operator_stream": OPERATOR_STREAM_MEDIA_MEMORIAL,
        "allowed_operator_streams": list(_effective_telegram_operator_streams(telegram_operator_streams)),
        "next_action": next_action,
        "session_ref": session_ref,
        **_binding_lookup_report_fields(
            binding,
            binding_lookup_error,
            recovered=bool(binding_lookup_error and ok),
            fallback_source="whatsapp_web_session_sidecar_qr",
        ),
        "sidecar_status": sidecar_status,
        "qr_present": qr_present,
        "qr_required": qr_required,
        "last_qr_at": str(payload.get("last_qr_at") or "").strip(),
        "qr_age_seconds": age_seconds,
        "qr_fresh": qr_fresh,
        "qr_fresh_seconds": qr_fresh_seconds,
        "pair_url": pair_url,
        "pair_url_scope": _url_scope(pair_url),
        "pair_url_actionable_from_telegram": _pair_url_actionable_from_telegram(_url_scope(pair_url)),
        "qr_svg_url": qr_svg_url,
        "qr_svg_content_type": content_type,
        "qr_svg_written": qr_svg_written,
        "qr_svg_path": str(qr_svg_path) if qr_svg_written else "",
        "qr_svg_error": qr_svg_error,
        "next_action_href": "",
        "next_action_label": "",
        "next_action_method": "",
        "observed_at": observed_at,
        "source": "whatsapp_web_session_sidecar.qr",
    }
    if next_action == "scan_whatsapp_web_qr":
        action_href = str(pair_url or "").strip()
        action_label = "Open WhatsApp pairing"
        if not action_href and qr_svg_written:
            action_href = str(qr_svg_path).strip()
            action_label = "Open WhatsApp QR"
        report["next_action_href"] = action_href
        report["next_action_label"] = action_label if action_href else ""
        report["next_action_method"] = "get" if action_href else ""

    if send_telegram_to_principal:
        allowed_operator_streams = _effective_telegram_operator_streams(telegram_operator_streams)
        pair_url_scope = str(report["pair_url_scope"])
        caption = _whatsapp_pairing_telegram_caption(
            session_ref=session_ref,
            status=sidecar_status or status,
            qr_age_seconds=age_seconds,
            pair_url=pair_url,
            pair_url_scope=pair_url_scope,
        )
        if not _telegram_operator_stream_allowed(
            OPERATOR_STREAM_MEDIA_MEMORIAL,
            allowed_operator_streams=allowed_operator_streams,
        ):
            telegram = _suppressed_telegram_delivery(
                principal_id=str(send_telegram_to_principal or "").strip(),
                operator_stream=OPERATOR_STREAM_MEDIA_MEMORIAL,
                allowed_operator_streams=allowed_operator_streams,
                observed_at=observed_at,
                source="whatsapp_web_session_sidecar.qr",
                delivery_transport="telegram_bot_document",
            )
        elif not qr_svg_written:
            telegram = {
                "sent": False,
                "reason": qr_svg_error or "qr_svg_not_written",
                "principal_id": str(send_telegram_to_principal or "").strip(),
                "delivery_transport": "telegram_bot",
            }
        else:
            telegram = send_telegram_document(
                principal_id=str(send_telegram_to_principal or "").strip(),
                document_ref=str(qr_svg_path),
                caption=caption,
                dry_run=dry_run,
            )
        report.update(
            {
                "telegram_sent": bool(telegram.get("sent")),
                "telegram_reason": str(telegram.get("reason") or "").strip(),
                "telegram_principal_id": str(telegram.get("principal_id") or send_telegram_to_principal or "").strip(),
                "telegram_message_count": int(telegram.get("message_count") or 0),
                "telegram_chat_ref_present": bool(telegram.get("chat_ref_present")),
                "telegram_chat_ref_sha256": str(telegram.get("chat_ref_sha256") or "").strip(),
                "telegram_delivery_transport": str(telegram.get("delivery_transport") or "").strip(),
                "telegram_caption_includes_pair_url": _pair_url_actionable_from_telegram(pair_url_scope),
            }
        )
    if output_format == "operator":
        report["operator_text"] = _operator_text_for_whatsapp_pairing(report)
    return report


OPERATOR_READINESS_DETAIL_FIELDS: dict[str, tuple[str, ...]] = {
    "telegram": (
        "principal_id",
        "binding_id",
        "binding_status",
        "chat_ref_present",
        "bot_key",
        "bot_handle",
        "bot_token_present",
        "runtime_container",
    ),
    "google_workspace_oauth": (
        "scope_bundle",
        "expected_google_email_present",
        "expected_google_domain",
        "observed_google_email_present",
        "observed_google_domain",
        "observed_google_account_matches_expected",
        "runtime_expected_google_email_present",
        "console_deep_link",
        "next_action_href",
        "next_action_label",
        "next_action_method",
        "last_receipt_status",
        "last_receipt_reason",
        "last_receipt_observed_at",
        "last_receipt_source",
        "last_receipt_age_seconds",
        "last_receipt_max_age_seconds",
        "last_receipt_fresh",
    ),
    "pushbullet": (
        "account_label",
        "account_label_basis",
        "required_client_keys",
        "configured_required_client_count",
        "token_present_required_client_count",
        "missing_client_keys",
        "missing_token_keys",
        "next_action_href",
        "next_action_label",
        "next_action_method",
    ),
    "onemin_direct_refresh": (
        "receipt_name",
        "selected_account_count",
        "pending_account_count",
        "owner_row_count",
        "attempted_count",
        "current_run_refreshed_count",
        "refreshed_count",
        "error_count",
        "rate_limited",
        "control_batch_size",
        "control_batch_backoff_seconds",
        "control_max_rate_limit_sleep_seconds",
        "control_continue_on_rate_limit",
        "control_refresh_transport",
        "control_proxy_mode",
        "control_controls_inferred_from_defaults",
        "control_single_account_batch_mode",
        "telegram_delivery_checked",
        "telegram_delivery_sent",
        "telegram_delivery_reason",
        "telegram_delivery_ready",
        "telegram_delivery_message_count",
    ),
    "whatsapp": (
        "effective_session_ref",
        "effective_session_ref_source",
        "sidecar_status",
        "sidecar_qr_required",
        "sidecar_qr_present",
        "sidecar_qr_age_seconds",
        "sidecar_qr_fresh",
        "processor_container_enabled",
        "state_fresh",
        "receipt_next_action",
    ),
    "whatsapp_pairing": (
        "session_ref",
        "binding_lookup_status",
        "sidecar_status",
        "qr_present",
        "qr_required",
        "qr_age_seconds",
        "qr_fresh",
        "pair_url_scope",
        "pair_url_actionable_from_telegram",
        "qr_svg_written",
        "qr_svg_path",
        "next_action_href",
        "next_action_label",
        "next_action_method",
        "telegram_caption_includes_pair_url",
    ),
    "teable_recovery": (
        "verify_status",
        "local_status",
        "table_id_present",
        "expected_rows",
        "same_hash",
        "root_restore_count",
        "local_restore_count",
        "service_restore_count",
        "referenced_file_restore_count",
        "missing_count",
        "missing_artifact_count",
        "wrong_mode_count",
        "different_hash_count",
        "different_hash_key_samples",
        "missing_secret_value_count",
        "extra_restorable_count",
        "uncovered_local_secret_file_count",
    ),
    "mymedia_alexa": (
        "container_name",
        "container_running",
        "container_state_status",
        "data_mount_present",
        "preferences_present",
        "messages_present",
        "api_reachable",
        "pairing_ready",
        "remote_access_mode",
        "public_ip_present",
        "connection_status",
        "watch_folder_count",
        "watch_folder_states",
        "watch_folder_error_count",
        "tracks",
        "albums",
        "artists",
        "genres",
        "library_scan_pending",
        "library_scan_blocked_by_pairing",
        "message_count",
        "message_warning_count",
        "message_error_count",
        "web_base_url_scope",
    ),
    "mymedia_pairing_telegram": (
        "principal_id",
        "surface_kind",
        "site",
        "otp_channel",
        "phone_suffix",
        "pairing_resume_ready",
        "pairing_session_pending",
        "pairing_session_stale",
        "pairing_session_age_seconds",
        "delivery_transport",
        "telegram_delivery_ready",
        "delivery_status",
        "delivery_reason",
        "bot_handle",
        "chat_ref_present",
        "chat_ref_sha256",
    ),
    "sonarr_tv_season": (
        "series_id",
        "series_title",
        "season_number",
        "season_monitored",
        "series_monitored",
        "season_episode_count",
        "season_episode_file_count",
        "missing_episode_numbers",
        "media_info_missing_count",
        "media_info_missing_episode_numbers",
        "unreadable_episode_count",
        "unreadable_episode_numbers",
        "episode_file_probe_method",
        "metadata_queue_count",
        "metadata_queue_episode_numbers",
        "stale_metadata_queue_count",
        "staging_candidate_count",
        "selected_staging_candidate_name",
        "selected_staging_candidate_cover_count",
    ),
    "proactive_route": (
        "principal_id",
        "runtime_service",
        "delivery_route_ready",
        "selected_channel",
        "selected_transport",
        "selected_by",
        "available_channels",
        "blocking_reason",
        "approval_capture_surface_ready",
        "approval_capture_surface_pending_count",
    ),
    "proactive_artifacts": (
        "runtime_service",
        "run_receipt_path",
        "action_required_only_quiet_receipt_path",
        "approval_callback_dir_exists",
        "approval_callback_dir_writable",
        "approval_callback_record_count",
        "approval_callback_live_pending_count",
        "approval_callback_stale_pending_count",
        "current_packet_live_pending_count",
        "current_packet_callback_latest_status",
        "approval_outcome_matches_current_packet",
    ),
}

OPERATOR_READINESS_READY_STATUSES: dict[str, set[str]] = {
    "telegram": {"ready"},
    "google_workspace_oauth": {"pass", "ready_manual_console_check"},
    "pushbullet": {"ready_configured", "ready_live_verified"},
    "onemin_direct_refresh": {"ready", "already_refreshed"},
    "whatsapp": {"ready"},
    "whatsapp_pairing": {"ready"},
    "teable_recovery": {"ready"},
    "mymedia_alexa": {"ready", "ready_library_scan_in_progress"},
    "mymedia_pairing_telegram": {"ready"},
    "sonarr_tv_season": {"ready", "ready_with_recovery_action"},
    "proactive_route": {"ready", "ready_with_recovery_action"},
    "proactive_artifacts": {"ok"},
}

OPERATOR_READINESS_STABLE_STATUSES: dict[str, set[str]] = {
    "telegram": {"ready"},
    "google_workspace_oauth": {"pass", "ready_manual_console_check"},
    "pushbullet": {"ready_configured", "ready_live_verified"},
    "onemin_direct_refresh": {"ready", "already_refreshed"},
    "whatsapp": {"ready"},
    "whatsapp_pairing": {"ready"},
    "teable_recovery": {"ready"},
    "mymedia_alexa": {"ready", "ready_library_scan_in_progress"},
    "mymedia_pairing_telegram": {"ready"},
    "sonarr_tv_season": {"ready"},
    "proactive_route": {"ready"},
    "proactive_artifacts": {"ok"},
}

OPERATOR_READINESS_NON_BLOCKING_ATTENTION_STATUSES: dict[str, set[str]] = {
    "pushbullet": {"blocked_setup_required"},
    "onemin_direct_refresh": {"rate_limited", "partial_rate_limited", "dry_run", "partial"},
    "mymedia_pairing_telegram": {"suppressed_by_stream_policy"},
}

OPERATOR_READINESS_ROUTE_SCOPED_COMPONENT_CHANNELS: dict[str, tuple[str, ...]] = {
    "pushbullet": ("pushbullet",),
    "onemin_direct_refresh": ("operator_support",),
    "whatsapp": ("whatsapp",),
    "whatsapp_pairing": ("whatsapp",),
}

OPERATOR_READINESS_ROUTE_SCOPED_DEFAULT_STEERING: dict[str, bool] = {
    "pushbullet": False,
    "onemin_direct_refresh": False,
    "whatsapp": True,
    "whatsapp_pairing": True,
}


def _operator_readiness_component(
    *,
    key: str,
    label: str,
    report: Mapping[str, object],
) -> dict[str, object]:
    if key == "whatsapp":
        report = _normalize_whatsapp_readiness_action(report)
    status = str(report.get("status") or "unknown").strip() or "unknown"
    ready = bool(report.get("ready")) or status in OPERATOR_READINESS_READY_STATUSES.get(key, {"ready"})
    probe_ok = bool(report.get("probe_ok", status not in {"probe_failed", "unavailable"}))
    details: dict[str, object] = {}
    for field in OPERATOR_READINESS_DETAIL_FIELDS.get(key, ()):
        value = report.get(field)
        if value is None:
            continue
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                continue
            details[field] = cleaned
        else:
            details[field] = value
    return {
        "key": key,
        "label": label,
        "probe_ok": probe_ok,
        "ready": ready,
        "status": status,
        "reason": str(report.get("reason") or report.get("blocking_reason") or "").strip(),
        "next_action": str(report.get("next_action") or "").strip(),
        "next_action_href": str(report.get("next_action_href") or "").strip(),
        "next_action_label": str(report.get("next_action_label") or "").strip(),
        "next_action_method": str(report.get("next_action_method") or "").strip(),
        "observed_at": str(report.get("observed_at") or "").strip(),
        "source": str(report.get("source") or "").strip(),
        "details": details,
    }


def _operator_readiness_failed_component(key: str, label: str, reason: str) -> dict[str, object]:
    return {
        "key": key,
        "label": label,
        "probe_ok": False,
        "ready": False,
        "status": "probe_failed",
        "reason": str(reason or "probe_failed").strip() or "probe_failed",
        "next_action": f"inspect_{key}_probe",
        "next_action_href": "",
        "next_action_label": "",
        "next_action_method": "",
        "observed_at": _utc_now(),
        "source": "ea_live_ops.aggregate",
        "details": {},
    }


def _operator_readiness_run_component(
    key: str,
    label: str,
    callback: Any,
) -> tuple[dict[str, object], dict[str, object]]:
    try:
        report = callback()
        normalized_report = dict(report) if isinstance(report, Mapping) else {}
        component = _operator_readiness_component(key=key, label=label, report=normalized_report)
        return component, normalized_report
    except Exception as exc:
        return _operator_readiness_failed_component(key, label, type(exc).__name__), {}


def _collect_operator_readiness_components(
    component_specs: list[tuple[str, str, Any]],
    *,
    per_component_timeout_seconds: float | None = None,
) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    if not component_specs:
        return [], {}
    normalized_timeout: float | None = None
    if per_component_timeout_seconds is not None:
        try:
            normalized_timeout = max(float(per_component_timeout_seconds), 0.05)
        except (TypeError, ValueError):
            normalized_timeout = 0.05
    if normalized_timeout is None and len(component_specs) == 1:
        key, label, callback = component_specs[0]
        component, report = _operator_readiness_run_component(key, label, callback)
        return [component], {key: {"component": component, "report": report}}
    if normalized_timeout is not None:
        started_at = time.monotonic()
        slots: dict[str, dict[str, object]] = {}
        for key, label, callback in component_specs:
            finished = threading.Event()
            slot: dict[str, object] = {"finished": finished, "value": None}

            def _runner(
                target_key: str = key,
                target_label: str = label,
                target_callback: Any = callback,
                target_slot: dict[str, object] = slot,
                target_finished: threading.Event = finished,
            ) -> None:
                try:
                    target_slot["value"] = _operator_readiness_run_component(target_key, target_label, target_callback)
                finally:
                    target_finished.set()

            thread = threading.Thread(
                target=_runner,
                name=f"ea-operator-readiness-{key}",
                daemon=True,
            )
            slot["thread"] = thread
            slots[key] = slot
            thread.start()

        deadline = started_at + normalized_timeout
        components: list[dict[str, object]] = []
        results_by_key: dict[str, dict[str, object]] = {}
        for key, label, _callback in component_specs:
            slot = slots[key]
            finished = slot["finished"]
            assert isinstance(finished, threading.Event)
            remaining = max(0.0, deadline - time.monotonic())
            if finished.wait(remaining):
                value = slot.get("value")
                if isinstance(value, tuple) and len(value) == 2:
                    component, report = value
                else:
                    component, report = _operator_readiness_failed_component(key, label, "probe_failed"), {}
            else:
                component, report = _operator_readiness_failed_component(key, label, "probe_timeout"), {}
            components.append(component)
            results_by_key[key] = {"component": component, "report": report}
        return components, results_by_key

    results_by_key: dict[str, dict[str, object]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(component_specs), 8)) as executor:
        futures = {
            key: executor.submit(_operator_readiness_run_component, key, label, callback)
            for key, label, callback in component_specs
        }
        components: list[dict[str, object]] = []
        for key, _label, _callback in component_specs:
            component, report = futures[key].result()
            components.append(component)
            results_by_key[key] = {"component": component, "report": report}
    return components, results_by_key


def _operator_readiness_component_requires_attention(component: Mapping[str, object]) -> bool:
    if not bool(component.get("probe_ok")):
        return True
    if not bool(component.get("ready")):
        return True
    key = str(component.get("key") or "").strip()
    status = str(component.get("status") or "").strip()
    stable_statuses = OPERATOR_READINESS_STABLE_STATUSES.get(key, {"ready"})
    return status not in stable_statuses


def _operator_readiness_pairing_qr_recovery_present(components: Sequence[Mapping[str, object]]) -> bool:
    return any(
        str(item.get("key") or "").strip() == "whatsapp_pairing"
        and str(item.get("next_action") or "").strip() == "scan_whatsapp_web_qr"
        for item in components
    )


def _operator_readiness_suppressed_keys(components: Sequence[Mapping[str, object]]) -> set[str]:
    if not _operator_readiness_pairing_qr_recovery_present(components):
        return set()
    return {
        str(item.get("key") or "").strip()
        for item in components
        if str(item.get("key") or "").strip() == "whatsapp"
        and str(item.get("next_action") or "").strip() == "scan_whatsapp_web_qr"
    }


def _operator_readiness_effective_components(
    components: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    hidden = _operator_readiness_suppressed_keys(components)
    return [
        item
        for item in components
        if str(item.get("key") or "").strip() and str(item.get("key") or "").strip() not in hidden
    ]


def _operator_readiness_selected_delivery_route(
    components: Sequence[Mapping[str, object]],
) -> tuple[str, str]:
    for item in _operator_readiness_effective_components(components):
        if str(item.get("key") or "").strip() != "proactive_route":
            continue
        details = dict(item.get("details") or {})
        selected_channel = str(details.get("selected_channel") or "").strip().lower()
        selected_transport = str(details.get("selected_transport") or "").strip().lower()
        if selected_channel or selected_transport:
            return selected_channel, selected_transport
    return "", ""


def _operator_readiness_component_can_steer(
    component: Mapping[str, object],
    components: Sequence[Mapping[str, object]],
) -> bool:
    key = str(component.get("key") or "").strip()
    if not key:
        return False
    scoped_channels = OPERATOR_READINESS_ROUTE_SCOPED_COMPONENT_CHANNELS.get(key, ())
    if not scoped_channels:
        return True
    selected_channel, selected_transport = _operator_readiness_selected_delivery_route(components)
    if selected_channel or selected_transport:
        return any(
            selected_channel == scoped_channel or scoped_channel in selected_transport
            for scoped_channel in scoped_channels
        )
    return OPERATOR_READINESS_ROUTE_SCOPED_DEFAULT_STEERING.get(key, True)


def _operator_readiness_steering_components(
    components: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    effective = _operator_readiness_effective_components(components)
    return [item for item in effective if _operator_readiness_component_can_steer(item, effective)]


def _operator_readiness_supplemental_components(
    components: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    effective = _operator_readiness_effective_components(components)
    return [item for item in effective if not _operator_readiness_component_can_steer(item, effective)]


def _operator_readiness_component_counts_as_blocked(component: Mapping[str, object]) -> bool:
    if not bool(component.get("probe_ok")) or bool(component.get("ready")):
        return False
    key = str(component.get("key") or "").strip()
    status = str(component.get("status") or "").strip()
    if status in OPERATOR_READINESS_NON_BLOCKING_ATTENTION_STATUSES.get(key, set()):
        return False
    return True


def _operator_readiness_blocked_component_keys(
    components: Sequence[Mapping[str, object]],
) -> list[str]:
    return [
        str(item.get("key") or "").strip()
        for item in _operator_readiness_steering_components(components)
        if _operator_readiness_component_counts_as_blocked(item)
    ]


def _operator_readiness_attention_component_keys(
    components: Sequence[Mapping[str, object]],
) -> list[str]:
    return [
        str(item.get("key") or "").strip()
        for item in _operator_readiness_steering_components(components)
        if _operator_readiness_component_requires_attention(item)
    ]


def _operator_readiness_probe_failed_component_keys(
    components: Sequence[Mapping[str, object]],
) -> list[str]:
    return [
        str(item.get("key") or "").strip()
        for item in _operator_readiness_steering_components(components)
        if not bool(item.get("probe_ok"))
    ]


def _operator_readiness_supplemental_blocked_component_keys(
    components: Sequence[Mapping[str, object]],
) -> list[str]:
    return [
        str(item.get("key") or "").strip()
        for item in _operator_readiness_supplemental_components(components)
        if _operator_readiness_component_counts_as_blocked(item)
    ]


def _operator_readiness_supplemental_attention_component_keys(
    components: Sequence[Mapping[str, object]],
) -> list[str]:
    return [
        str(item.get("key") or "").strip()
        for item in _operator_readiness_supplemental_components(components)
        if _operator_readiness_component_requires_attention(item)
    ]


def _operator_readiness_supplemental_probe_failed_component_keys(
    components: Sequence[Mapping[str, object]],
) -> list[str]:
    return [
        str(item.get("key") or "").strip()
        for item in _operator_readiness_supplemental_components(components)
        if not bool(item.get("probe_ok"))
    ]


def _operator_readiness_next_actions(
    components: Sequence[Mapping[str, object]],
) -> list[dict[str, str]]:
    has_pairing_qr_action = _operator_readiness_pairing_qr_recovery_present(components)
    next_actions: list[dict[str, str]] = []
    for item in _operator_readiness_steering_components(components):
        if not _operator_readiness_component_requires_attention(item):
            continue
        component_key = str(item.get("key") or "").strip()
        action = str(item.get("next_action") or "").strip()
        if not action:
            continue
        if has_pairing_qr_action and component_key == "whatsapp" and action == "scan_whatsapp_web_qr":
            continue
        next_actions.append(
            {
                "component_key": component_key,
                "component_label": str(item.get("label") or "").strip(),
                "action": action,
                "reason": str(item.get("reason") or "").strip(),
                "href": str(item.get("next_action_href") or "").strip(),
                "label": str(item.get("next_action_label") or "").strip(),
                "method": str(item.get("next_action_method") or "").strip(),
            }
        )
    return next_actions


def _operator_readiness_supplemental_next_actions(
    components: Sequence[Mapping[str, object]],
) -> list[dict[str, str]]:
    has_pairing_qr_action = _operator_readiness_pairing_qr_recovery_present(components)
    next_actions: list[dict[str, str]] = []
    for item in _operator_readiness_supplemental_components(components):
        if not _operator_readiness_component_requires_attention(item):
            continue
        component_key = str(item.get("key") or "").strip()
        action = str(item.get("next_action") or "").strip()
        if not action:
            continue
        if has_pairing_qr_action and component_key == "whatsapp" and action == "scan_whatsapp_web_qr":
            continue
        next_actions.append(
            {
                "component_key": component_key,
                "component_label": str(item.get("label") or "").strip(),
                "action": action,
                "reason": str(item.get("reason") or "").strip(),
                "href": str(item.get("next_action_href") or "").strip(),
                "label": str(item.get("next_action_label") or "").strip(),
                "method": str(item.get("next_action_method") or "").strip(),
            }
        )
    return next_actions


def _operator_text_for_operator_readiness(report: Mapping[str, object]) -> str:
    components = [dict(item) for item in list(report.get("components") or []) if isinstance(item, dict)]
    displayed_states = []
    for item in _operator_readiness_steering_components(components):
        key = str(item.get("key") or "").strip()
        status = str(item.get("status") or "").strip()
        if key == "proactive_route" and status == "ready_with_recovery_action":
            status = "ready"
        if key and key != "teable_recovery":
            displayed_states.append(f"{key}:{status}")
    displayed_supplemental_states = []
    for item in _operator_readiness_supplemental_components(components):
        key = str(item.get("key") or "").strip()
        status = str(item.get("status") or "").strip()
        if key == "proactive_route" and status == "ready_with_recovery_action":
            status = "ready"
        if key:
            displayed_supplemental_states.append(f"{key}:{status}")
    steering_states = ",".join(
        displayed_states
    )
    supplemental_states = ",".join(
        displayed_supplemental_states
    )
    pieces = [
        f"operator_readiness status={report.get('status') or 'unknown'}",
        f"ready={str(bool(report.get('ready'))).lower()}",
        f"components={len(components)}",
        f"attention={int(report.get('attention_required_count') or 0)}",
        f"blocked={int(report.get('blocked_count') or 0)}",
        f"probe_failed={int(report.get('probe_failed_count') or 0)}",
    ]
    supplemental_attention_count = int(report.get("supplemental_attention_count") or 0)
    supplemental_blocked_count = int(report.get("supplemental_blocked_count") or 0)
    supplemental_probe_failed_count = int(report.get("supplemental_probe_failed_count") or 0)
    if supplemental_attention_count or supplemental_blocked_count or supplemental_probe_failed_count:
        pieces.extend(
            [
                f"supplemental_attention={supplemental_attention_count}",
                f"supplemental_blocked={supplemental_blocked_count}",
                f"supplemental_probe_failed={supplemental_probe_failed_count}",
            ]
        )
    if steering_states:
        pieces.append(f"states={steering_states}")
    if supplemental_states:
        pieces.append(f"supplemental_states={supplemental_states}")
    next_actions = [dict(item) for item in list(report.get("next_actions") or []) if isinstance(item, dict)]
    if next_actions:
        first = next_actions[0]
        pieces.append(f"next={first.get('component_key')}:{first.get('action')}")
    supplemental_next_actions = [
        dict(item) for item in list(report.get("supplemental_next_actions") or []) if isinstance(item, dict)
    ]
    if supplemental_next_actions:
        first = supplemental_next_actions[0]
        pieces.append(f"supplemental_next={first.get('component_key')}:{first.get('action')}")
    if report.get("observed_at"):
        pieces.append(f"observed_at={report['observed_at']}")
    if report.get("source"):
        pieces.append(f"source={report['source']}")
    return "; ".join(str(item) for item in pieces if str(item).strip())


def _operator_readiness_int_value(value: object, *, default: int = 0) -> int:
    text = str(value or "").strip()
    if not text:
        return int(default)
    try:
        return int(text)
    except (TypeError, ValueError):
        return int(default)


def _operator_readiness_onemin_direct_refresh_report(report: Mapping[str, object]) -> dict[str, object]:
    normalized = dict(report or {})
    controls = dict(normalized.get("controls") or {}) if isinstance(normalized.get("controls"), Mapping) else {}
    telegram_delivery = (
        dict(normalized.get("telegram_delivery") or {})
        if isinstance(normalized.get("telegram_delivery"), Mapping)
        else {}
    )
    normalized.update(
        {
            "control_batch_size": int(controls.get("batch_size") or 0),
            "control_batch_backoff_seconds": float(controls.get("batch_backoff_seconds") or 0.0),
            "control_max_rate_limit_sleep_seconds": float(controls.get("max_rate_limit_sleep_seconds") or 0.0),
            "control_continue_on_rate_limit": bool(controls.get("continue_on_rate_limit")),
            "control_refresh_transport": str(controls.get("refresh_transport") or "").strip(),
            "control_proxy_mode": str(controls.get("proxy_mode") or "").strip(),
            "control_controls_inferred_from_defaults": bool(controls.get("controls_inferred_from_defaults")),
            "control_single_account_batch_mode": bool(controls.get("single_account_batch_mode")),
            "telegram_delivery_checked": bool(telegram_delivery.get("checked")),
            "telegram_delivery_sent": bool(telegram_delivery.get("sent")),
            "telegram_delivery_reason": str(telegram_delivery.get("reason") or "").strip(),
            "telegram_delivery_ready": bool(telegram_delivery.get("ready")),
            "telegram_delivery_message_count": int(telegram_delivery.get("message_count") or 0),
        }
    )
    return normalized


def _operator_readiness_sonarr_target(
    *,
    series_id: int | str | None = 0,
    series_title: str = "",
    season_number: int | str | None = 0,
) -> dict[str, object]:
    effective_series_id = _operator_readiness_int_value(
        series_id if series_id not in (None, "") else _env("EA_OPERATOR_READINESS_SONARR_SERIES_ID", "0"),
        default=0,
    )
    effective_series_title = str(
        series_title if str(series_title or "").strip() else _env("EA_OPERATOR_READINESS_SONARR_SERIES_TITLE", "")
    ).strip()
    effective_season_number = _operator_readiness_int_value(
        season_number if season_number not in (None, "") else _env("EA_OPERATOR_READINESS_SONARR_SEASON_NUMBER", "0"),
        default=0,
    )
    enabled = effective_season_number > 0 and (effective_series_id > 0 or bool(effective_series_title))
    return {
        "enabled": enabled,
        "series_id": effective_series_id,
        "series_title": effective_series_title,
        "season_number": effective_season_number,
    }


def _operator_readiness_proactive_artifacts_report_from_route(
    route_report: Mapping[str, object] | None,
) -> dict[str, object]:
    normalized_route_report = dict(route_report or {})
    artifact_probe = normalized_route_report.get("artifact_probe")
    if not isinstance(artifact_probe, Mapping):
        return {}
    report = dict(artifact_probe)
    if not report:
        return {}
    if not str(report.get("observed_at") or "").strip():
        report["observed_at"] = str(normalized_route_report.get("observed_at") or "").strip()
    if not str(report.get("source") or "").strip():
        route_source = str(normalized_route_report.get("source") or "").strip()
        report["source"] = f"{route_source}:artifact_probe" if route_source else "proactive_route.artifact_probe"
    return report


def probe_operator_readiness(
    *,
    args: argparse.Namespace,
    telegram_principal_id: str,
    proactive_principal_id: str,
    compose_file: str = "",
    runtime_service: str = "",
    receipt_path: str = "",
    timeout_seconds: float = 30.0,
    include_proactive: bool = True,
    include_pairing: bool = True,
    sonarr_series_id: int | str | None = 0,
    sonarr_series_title: str = "",
    sonarr_season_number: int | str | None = 0,
    output_format: str = "json",
    telegram_operator_streams: tuple[str, ...] | str | None = None,
) -> dict[str, object]:
    observed_at = _utc_now()
    components: list[dict[str, object]] = []
    sonarr_target = _operator_readiness_sonarr_target(
        series_id=sonarr_series_id,
        series_title=sonarr_series_title,
        season_number=sonarr_season_number,
    )
    expected_google_email = _default_google_workspace_expected_email()
    google_context = _google_workspace_oauth_probe_context_from_receipt()
    base_component_specs: list[tuple[str, str, Any]] = [
        (
            "telegram",
            "Telegram operator delivery",
            lambda: probe_telegram_readiness(
                principal_id=str(telegram_principal_id or "").strip(),
                timeout_seconds=timeout_seconds,
                output_format="json",
            ),
        ),
        (
            "google_workspace_oauth",
            "Google Workspace OAuth",
            lambda: (
                probe_google_workspace_oauth(
                    expected_google_email=expected_google_email,
                    scope_bundle=str(google_context.get("scope_bundle") or google_workspace_oauth_readiness.DEFAULT_SCOPE_BUNDLE).strip()
                    or google_workspace_oauth_readiness.DEFAULT_SCOPE_BUNDLE,
                    observed_error=str(google_context.get("observed_error") or "").strip(),
                    observed_google_email=(
                        expected_google_email
                        if str(google_context.get("observed_google_email") or "").strip() == "__expected__"
                        else str(google_context.get("observed_google_email") or "").strip()
                    ),
                    test_user_confirmed=bool(google_context.get("test_user_confirmed")),
                    probe_gcloud=True,
                    timeout_seconds=timeout_seconds,
                    output_format="json",
                    telegram_operator_streams=telegram_operator_streams,
                )
                if "@" in expected_google_email
                else _probe_google_workspace_oauth_without_runtime_expected_email(
                    scope_bundle=str(google_context.get("scope_bundle") or google_workspace_oauth_readiness.DEFAULT_SCOPE_BUNDLE).strip()
                    or google_workspace_oauth_readiness.DEFAULT_SCOPE_BUNDLE,
                    observed_error=str(google_context.get("observed_error") or "").strip(),
                    observed_google_email=str(google_context.get("observed_google_email") or "").strip(),
                    test_user_confirmed=bool(google_context.get("test_user_confirmed")),
                    timeout_seconds=timeout_seconds,
                )
            ),
        ),
        (
            "pushbullet",
            "Pushbullet operator delivery",
            lambda: probe_pushbullet_delivery(
                timeout_seconds=timeout_seconds,
                output_format="json",
            ),
        ),
        (
            "onemin_direct_refresh",
            "1min.AI direct refresh posture",
            lambda: _operator_readiness_onemin_direct_refresh_report(
                probe_onemin_direct_refresh_posture(output_format="json")
            ),
        ),
        (
            "whatsapp",
            "WhatsApp Web action processor",
            lambda: probe_whatsapp_readiness(refresh=True, output_format="json", volatile=True),
        ),
        (
            "teable_recovery",
            "Teable env recovery",
            lambda: probe_teable_recovery(output_format="json", timeout_seconds=timeout_seconds),
        ),
        (
            "mymedia_alexa",
            "My Media for Alexa",
            lambda: probe_mymedia_alexa(
                timeout_seconds=timeout_seconds,
                output_format="json",
            ),
        ),
    ]
    if bool(sonarr_target.get("enabled")):
        base_component_specs.append(
            (
                "sonarr_tv_season",
                "Sonarr TV season import",
                lambda: probe_sonarr_tv_season(
                    series_id=int(sonarr_target.get("series_id") or 0),
                    series_title=str(sonarr_target.get("series_title") or "").strip(),
                    season_number=int(sonarr_target.get("season_number") or 0),
                    timeout_seconds=timeout_seconds,
                    output_format="json",
                ),
            )
        )
    if include_proactive:
        base_component_specs.extend(
            [
                (
                    "proactive_route",
                    "Proactive OODA delivery route",
                    lambda: probe_proactive_route(
                        principal_id=str(proactive_principal_id or "").strip(),
                        compose_file=str(compose_file or "").strip(),
                        runtime_service=str(runtime_service or "").strip(),
                        receipt_path=str(receipt_path or "").strip(),
                        timeout_seconds=timeout_seconds,
                        include_artifact_probe=False,
                        output_format="json",
                    ),
                ),
            ]
        )
    _base_components, component_results = _collect_operator_readiness_components(
        base_component_specs,
        per_component_timeout_seconds=max(float(timeout_seconds or 30.0), 1.0) + 2.0,
    )
    if include_proactive:
        proactive_route_report = dict(dict(component_results.get("proactive_route") or {}).get("report") or {})
        proactive_artifacts_report = _operator_readiness_proactive_artifacts_report_from_route(proactive_route_report)
        if proactive_artifacts_report:
            proactive_artifacts_component = _operator_readiness_component(
                key="proactive_artifacts",
                label="Proactive OODA artifacts",
                report=proactive_artifacts_report,
            )
        else:
            proactive_artifacts_component, proactive_artifacts_report = _operator_readiness_run_component(
                "proactive_artifacts",
                "Proactive OODA artifacts",
                lambda: probe_proactive_artifacts(
                    compose_file=str(compose_file or "").strip(),
                    runtime_service=str(runtime_service or "").strip(),
                    timeout_seconds=timeout_seconds,
                    output_format="json",
                    prefer_host_runtime=True,
                ),
            )
        component_results["proactive_artifacts"] = {
            "component": proactive_artifacts_component,
            "report": proactive_artifacts_report,
        }

    pairing_components: dict[str, dict[str, object]] = {}
    whatsapp_component = dict(dict(component_results.get("whatsapp") or {}).get("component") or {})
    if include_pairing and (
        not bool(whatsapp_component.get("ready"))
        or bool(dict(whatsapp_component.get("details") or {}).get("sidecar_qr_required"))
        or bool(dict(whatsapp_component.get("details") or {}).get("sidecar_qr_present"))
    ):
        component, _report = _operator_readiness_run_component(
            "whatsapp_pairing",
            "WhatsApp Web pairing recovery",
            lambda: probe_whatsapp_pairing(
                args=args,
                output_format="json",
                write_qr_svg=True,
                telegram_operator_streams=telegram_operator_streams,
            ),
        )
        pairing_components["whatsapp_pairing"] = component
    mymedia_report = dict(dict(component_results.get("mymedia_alexa") or {}).get("report") or {})
    if include_pairing and _mymedia_pairing_requires_telegram_handoff(mymedia_report):
        component, _report = _operator_readiness_run_component(
            "mymedia_pairing_telegram",
            "My Media pairing Telegram handoff",
            lambda: probe_mymedia_pairing_telegram_readiness(
                principal_id=str(telegram_principal_id or "").strip(),
                timeout_seconds=timeout_seconds,
                output_format="json",
                telegram_operator_streams=telegram_operator_streams,
            ),
        )
        pairing_components["mymedia_pairing_telegram"] = component

    ordered_keys = [
        "telegram",
        "google_workspace_oauth",
        "pushbullet",
        "teable_recovery",
        "mymedia_alexa",
        "sonarr_tv_season",
        "proactive_route",
        "proactive_artifacts",
        "onemin_direct_refresh",
        "whatsapp",
        "whatsapp_pairing",
        "mymedia_pairing_telegram",
    ]
    components = []
    for key in ordered_keys:
        if key in pairing_components:
            components.append(pairing_components[key])
            continue
        component = dict(dict(component_results.get(key) or {}).get("component") or {})
        if component:
            components.append(component)

    probe_failed_component_keys = _operator_readiness_probe_failed_component_keys(components)
    blocked_component_keys = _operator_readiness_blocked_component_keys(components)
    attention_component_keys = _operator_readiness_attention_component_keys(components)
    supplemental_probe_failed_component_keys = _operator_readiness_supplemental_probe_failed_component_keys(components)
    supplemental_blocked_component_keys = _operator_readiness_supplemental_blocked_component_keys(components)
    supplemental_attention_component_keys = _operator_readiness_supplemental_attention_component_keys(components)
    probe_failed_count = len(probe_failed_component_keys)
    blocked_count = len(blocked_component_keys)
    attention_required_count = len(attention_component_keys)
    next_actions = _operator_readiness_next_actions(components)
    supplemental_next_actions = _operator_readiness_supplemental_next_actions(components)
    if probe_failed_count:
        status = "probe_failed"
    elif attention_required_count:
        status = "ready_with_actions"
    else:
        status = "ready"
    report = {
        "contract_name": "ea.operator_readiness.v1",
        "probe_ok": probe_failed_count == 0,
        "ready": status == "ready",
        "status": status,
        "component_count": len(components),
        "attention_required_count": attention_required_count,
        "blocked_count": blocked_count,
        "probe_failed_count": probe_failed_count,
        "supplemental_attention_count": len(supplemental_attention_component_keys),
        "supplemental_blocked_count": len(supplemental_blocked_component_keys),
        "supplemental_probe_failed_count": len(supplemental_probe_failed_component_keys),
        "sonarr_target_enabled": bool(sonarr_target.get("enabled")),
        "sonarr_target_series_id": int(sonarr_target.get("series_id") or 0),
        "sonarr_target_series_title": str(sonarr_target.get("series_title") or "").strip(),
        "sonarr_target_season_number": int(sonarr_target.get("season_number") or 0),
        "allowed_operator_streams": list(_effective_telegram_operator_streams(telegram_operator_streams)),
        "components": components,
        "steering_component_keys": [
            str(item.get("key") or "").strip()
            for item in _operator_readiness_steering_components(components)
            if str(item.get("key") or "").strip()
        ],
        "next_actions": next_actions,
        "next_action_href": str(next_actions[0].get("href") or "").strip() if next_actions else "",
        "next_action_label": str(next_actions[0].get("label") or "").strip() if next_actions else "",
        "next_action_method": str(next_actions[0].get("method") or "").strip() if next_actions else "",
        "supplemental_attention_component_keys": supplemental_attention_component_keys,
        "supplemental_blocked_component_keys": supplemental_blocked_component_keys,
        "supplemental_probe_failed_component_keys": supplemental_probe_failed_component_keys,
        "supplemental_next_actions": supplemental_next_actions,
        "observed_at": observed_at,
        "source": "ea_live_ops.aggregate",
    }
    public_report = _operator_readiness_public_report(report)
    if output_format == "operator":
        public_report["operator_text"] = _operator_text_for_operator_readiness(public_report)
    return public_report


def _mymedia_pairing_requires_telegram_handoff(report: Mapping[str, object]) -> bool:
    status = str(report.get("status") or "").strip()
    next_action = str(report.get("next_action") or "").strip()
    surface_kind = str(
        report.get("pairing_session_surface_kind") or report.get("surface_kind") or ""
    ).strip()
    return bool(
        status == "blocked_pairing_required"
        and next_action in {"enter_mymedia_amazon_pairing_code", "approve_mymedia_amazon_consent"}
        and bool(report.get("pairing_resume_ready"))
        and (
            bool(report.get("pairing_session_pending"))
            or surface_kind in {"waiting_for_code", "consent_required"}
        )
    )


def probe_mymedia_pairing_telegram_readiness(
    *,
    principal_id: str,
    timeout_seconds: float = 30.0,
    output_format: str = "json",
    output_dir: str = "",
    telegram_operator_streams: tuple[str, ...] | str | None = None,
) -> dict[str, object]:
    observed_at = _utc_now()
    handoff = send_mymedia_amazon_pairing_telegram(
        telegram_principal_id=str(principal_id or "").strip(),
        dry_run=True,
        timeout_seconds=timeout_seconds,
        output_format="json",
        output_dir=output_dir,
        telegram_operator_streams=telegram_operator_streams,
    )
    delivery = dict(handoff.get("telegram_delivery") or {}) if isinstance(handoff.get("telegram_delivery"), Mapping) else {}
    handoff_status = str(handoff.get("status") or "").strip()
    delivery_ready = bool(delivery.get("readiness_probe_ok", delivery.get("ready"))) and bool(delivery.get("ready"))
    actionable = handoff_status in {"waiting_for_code", "consent_required"}
    probe_ok = bool(handoff.get("probe_ok")) and (not actionable or bool(delivery))
    ready = bool(delivery_ready) or handoff_status == "already_paired"
    if ready:
        status = "ready"
        reason = ""
        next_action = ""
        next_action_href = ""
        next_action_label = ""
        next_action_method = ""
    else:
        status = (
            str(delivery.get("readiness_status") or "").strip()
            or handoff_status
            or ("probe_failed" if not probe_ok else "blocked")
        )
        reason = str(
            delivery.get("readiness_reason")
            or delivery.get("reason")
            or handoff.get("reason")
            or ""
        ).strip()
        next_action = str(delivery.get("next_action") or "").strip()
        next_action_href = str(delivery.get("next_action_href") or "").strip()
        next_action_label = str(delivery.get("next_action_label") or "").strip()
        next_action_method = str(delivery.get("next_action_method") or "").strip()
    report = {
        "probe_ok": probe_ok,
        "ready": ready,
        "status": status,
        "reason": reason,
        "next_action": next_action,
        "next_action_href": next_action_href,
        "next_action_label": next_action_label,
        "next_action_method": next_action_method,
        "principal_id": str(delivery.get("principal_id") or principal_id or "").strip(),
        "surface_kind": str(handoff.get("surface_kind") or "").strip(),
        "site": str(handoff.get("site") or "").strip(),
        "otp_channel": str(handoff.get("otp_channel") or "").strip(),
        "phone_suffix": str(handoff.get("phone_suffix") or "").strip(),
        "pairing_resume_ready": bool(handoff.get("pairing_resume_ready")),
        "pairing_session_pending": bool(handoff.get("pairing_session_pending")),
        "pairing_session_stale": bool(handoff.get("pairing_session_stale")),
        "pairing_session_age_seconds": handoff.get("pairing_session_age_seconds"),
        "operator_stream": str(handoff.get("operator_stream") or OPERATOR_STREAM_MEDIA_MEMORIAL).strip(),
        "allowed_operator_streams": list(
            handoff.get("allowed_operator_streams")
            or _effective_telegram_operator_streams(telegram_operator_streams)
        ),
        "delivery_transport": str(delivery.get("delivery_transport") or "telegram_bot").strip(),
        "telegram_delivery_ready": bool(delivery.get("ready")),
        "delivery_status": str(delivery.get("readiness_status") or "").strip(),
        "delivery_reason": "" if ready else reason,
        "bot_handle": str(delivery.get("bot_handle") or "").strip(),
        "chat_ref_present": bool(delivery.get("chat_ref_present")),
        "chat_ref_sha256": str(delivery.get("chat_ref_sha256") or "").strip(),
        "observed_at": str(handoff.get("observed_at") or observed_at).strip() or observed_at,
        "source": "mymedia_pairing.telegram_dry_run",
    }
    if output_format == "operator":
        report["operator_text"] = _operator_text_for_operator_readiness(
            {
                "status": status,
                "ready": ready,
                "components": [
                    _operator_readiness_component(
                        key="mymedia_pairing_telegram",
                        label="My Media pairing Telegram handoff",
                        report=report,
                    )
                ],
                "attention_required_count": 0 if ready else 1,
                "blocked_count": 0 if ready else 1,
                "probe_failed_count": 0 if probe_ok else 1,
                "observed_at": report["observed_at"],
                "source": report["source"],
                "next_actions": [],
            }
        )
    return report


def send_telegram(
    *,
    principal_id: str,
    text: str,
    dry_run: bool = False,
    timeout_seconds: float = 30.0,
) -> dict[str, object]:
    normalized_principal_id = str(principal_id or "").strip()
    normalized_text = str(text or "").strip()
    observed_at = _utc_now()
    effective_timeout_seconds = max(float(timeout_seconds or 30.0), 1.0)
    if not normalized_text:
        return {
            "sent": False,
            "reason": "text_missing",
            "principal_id": normalized_principal_id,
            "delivery_transport": "telegram_bot",
            "timeout_seconds": effective_timeout_seconds,
            "observed_at": observed_at,
            "source": "runtime_container_exec:telegram_delivery.send_telegram_message_for_principal",
        }
    if dry_run:
        readiness_timeout_seconds = _telegram_dry_run_timeout_seconds(effective_timeout_seconds)
        readiness = probe_telegram_readiness(
            principal_id=normalized_principal_id,
            timeout_seconds=readiness_timeout_seconds,
            output_format="json",
        )
        return {
            "sent": False,
            "reason": "dry_run",
            "readiness_probe_ok": bool(readiness.get("probe_ok")),
            "ready": bool(readiness.get("ready")),
            "readiness_status": str(readiness.get("status") or "").strip(),
            "readiness_reason": str(readiness.get("reason") or "").strip(),
            "principal_id": str(readiness.get("principal_id") or normalized_principal_id).strip(),
            "binding_id": str(readiness.get("binding_id") or "").strip(),
            "next_action": str(readiness.get("next_action") or "").strip(),
            "next_action_href": str(readiness.get("next_action_href") or "").strip(),
            "next_action_label": str(readiness.get("next_action_label") or "").strip(),
            "next_action_method": str(readiness.get("next_action_method") or "").strip(),
            "chat_ref_present": bool(readiness.get("chat_ref_present")),
            "chat_ref_sha256": str(readiness.get("chat_ref_sha256") or "").strip(),
            "bot_key": str(readiness.get("bot_key") or "").strip(),
            "bot_handle": str(readiness.get("bot_handle") or "").strip(),
            "bot_token_present": bool(readiness.get("bot_token_present")),
            "delivery_transport": "telegram_bot",
            "runtime_container": str(readiness.get("runtime_container") or "").strip(),
            "timeout_seconds": effective_timeout_seconds,
            "observed_at": observed_at,
            "source": "runtime_container_exec:telegram_delivery.send_telegram_message_for_principal",
        }
    def _send_in_process() -> dict[str, object]:
        receipt = send_telegram_message_for_principal(
            build_tool_runtime(get_settings()),
            principal_id=normalized_principal_id,
            text=normalized_text,
            disable_web_page_preview=True,
        )
        chat_ref = str(getattr(receipt, "chat_id", "") or "").strip()
        message_ids = [
            str(item or "").strip()
            for item in (getattr(receipt, "message_ids", ()) or ())
            if str(item or "").strip()
        ]
        return {
            "sent": True,
            "reason": "sent",
            "principal_id": str(getattr(receipt, "principal_id", "") or normalized_principal_id).strip(),
            "chat_ref_present": bool(chat_ref),
            "chat_ref_sha256": _hash_text(chat_ref) if chat_ref else "",
            "bot_key": str(getattr(receipt, "bot_key", "") or "").strip(),
            "bot_handle": str(getattr(receipt, "bot_handle", "") or "").strip(),
            "delivery_transport": "telegram_bot",
            "message_ids": message_ids,
            "message_count": len(message_ids),
            "runtime_container": "",
            "timeout_seconds": effective_timeout_seconds,
            "observed_at": observed_at,
            "source": "in_process:telegram_delivery.send_telegram_message_for_principal",
        }

    # Long-running host supervisors can be confined with a no-Docker AppArmor
    # profile.  In that lane, fail closed inside the governed host transport and
    # never probe or fall back through the runtime-container Docker path.
    if _env_truthy("EA_LIVE_OPS_TELEGRAM_IN_PROCESS_ONLY", default=False):
        try:
            return _send_in_process()
        except Exception as exc:
            return {
                "sent": False,
                "reason": type(exc).__name__,
                "principal_id": normalized_principal_id,
                "delivery_transport": "telegram_bot",
                "message_ids": [],
                "message_count": 0,
                "runtime_container": "",
                "timeout_seconds": effective_timeout_seconds,
                "observed_at": observed_at,
                "source": "in_process:telegram_delivery.send_telegram_message_for_principal",
            }

    code = (
        "import hashlib, json, os\n"
        "principal_id = "
        + json.dumps(normalized_principal_id)
        + "\n"
        "text = "
        + json.dumps(normalized_text)
        + "\n"
        "try:\n"
        "    from app.settings import get_settings\n"
        "    from app.services.telegram_delivery import send_telegram_message_for_principal\n"
        "    from app.services.tool_runtime import build_tool_runtime\n"
        "    tool_runtime = build_tool_runtime(get_settings())\n"
        "    receipt = send_telegram_message_for_principal(tool_runtime, principal_id=principal_id, text=text, disable_web_page_preview=True)\n"
        "    chat_ref = str(getattr(receipt, 'chat_id', '') or '').strip()\n"
        "    message_ids = [str(item or '').strip() for item in (getattr(receipt, 'message_ids', ()) or ()) if str(item or '').strip()]\n"
        "    print(json.dumps({\n"
        "        'ok': True,\n"
        "        'sent': True,\n"
        "        'reason': 'sent',\n"
        "        'principal_id': str(getattr(receipt, 'principal_id', '') or principal_id or '').strip(),\n"
        "        'chat_ref_present': bool(chat_ref),\n"
        "        'chat_ref_sha256': hashlib.sha256(chat_ref.encode('utf-8')).hexdigest() if chat_ref else '',\n"
        "        'bot_key': str(getattr(receipt, 'bot_key', '') or '').strip(),\n"
        "        'bot_handle': str(getattr(receipt, 'bot_handle', '') or '').strip(),\n"
        "        'message_ids': message_ids,\n"
        "    }, sort_keys=True), flush=True)\n"
        "    os._exit(0)\n"
        "except Exception as exc:\n"
        "    reason = (str(exc).strip() or type(exc).__name__)[:160]\n"
        "    print(json.dumps({'ok': False, 'sent': False, 'reason': reason}, sort_keys=True), flush=True)\n"
        "    os._exit(0)\n"
    )
    exit_code, payload, runtime_container = _runtime_container_exec_json(code=code, timeout_seconds=effective_timeout_seconds)
    runtime_reason = str(payload.get("reason") or "").strip()
    if runtime_reason in {"FileNotFoundError", "runtime_container_unconfigured", "runtime_container_exec_exit_127"}:
        try:
            return _send_in_process()
        except Exception as exc:
            payload = {"ok": False, "reason": str(exc).strip() or type(exc).__name__}
            runtime_container = ""
            exit_code = 127
    payload_ok = bool(payload.get("ok", False))
    sent = exit_code == 0 and payload_ok and bool(payload.get("sent"))
    reason = runtime_reason or (f"runtime_container_exec_exit_{exit_code}" if exit_code else "send_failed")
    message_ids = [str(item or "").strip() for item in payload.get("message_ids") or [] if str(item or "").strip()]
    return {
        "sent": sent,
        "reason": "sent" if sent else reason,
        "principal_id": str(payload.get("principal_id") or normalized_principal_id).strip(),
        "chat_ref_present": bool(payload.get("chat_ref_present")),
        "chat_ref_sha256": str(payload.get("chat_ref_sha256") or "").strip(),
        "bot_key": str(payload.get("bot_key") or "").strip(),
        "bot_handle": str(payload.get("bot_handle") or "").strip(),
        "delivery_transport": "telegram_bot",
        "message_ids": message_ids,
        "message_count": len(message_ids),
        "runtime_container": runtime_container,
        "timeout_seconds": effective_timeout_seconds,
        "observed_at": observed_at,
        "source": "runtime_container_exec:telegram_delivery.send_telegram_message_for_principal",
    }


def _google_workspace_oauth_direct_link(*, expected_google_email: str, scope_bundle: str) -> str:
    public_base = (_env("EA_PUBLIC_APP_BASE_URL", "https://myexternalbrain.com") or "https://myexternalbrain.com").rstrip("/")
    query: dict[str, str] = {
        "return_to": "/app/settings/google",
        "scope_bundle": str(scope_bundle or google_workspace_oauth_readiness.DEFAULT_SCOPE_BUNDLE).strip()
        or google_workspace_oauth_readiness.DEFAULT_SCOPE_BUNDLE,
    }
    normalized_email = str(expected_google_email or "").strip().lower()
    if "@" in normalized_email:
        query["expected_google_email"] = normalized_email
    return f"{public_base}/app/actions/google/connect?{urllib.parse.urlencode(query)}"


def _default_google_workspace_expected_email() -> str:
    return (
        _env("EA_GOOGLE_WORKSPACE_EXPECTED_EMAIL")
        or _env("EA_GOOGLE_OAUTH_EXPECTED_EMAIL")
        or ""
    ).strip().lower()


def _google_workspace_oauth_telegram_text(
    *,
    receipt: Mapping[str, object],
    expected_google_email: str,
    direct_auth_link: str,
) -> str:
    normalized_email = str(expected_google_email or "").strip().lower()
    operator_action = dict(receipt.get("operator_action") or {})
    gcloud_probe = dict(receipt.get("gcloud_probe") or {})
    oauth_client = dict(receipt.get("oauth_client") or {})
    lines: list[str] = []
    if "@" in normalized_email:
        lines.append(f"Google Full Workspace retry for {normalized_email}")
        lines.append("")
    instruction = str(operator_action.get("instruction") or "").strip()
    if instruction:
        lines.append(instruction)
        lines.append("")
    lines.extend(
        [
            "Auth link:",
            direct_auth_link,
            "",
            "Google Auth Platform Audience:",
            str(receipt.get("console_deep_link") or "").strip(),
        ]
    )
    oauth_project_id = str(gcloud_probe.get("oauth_project_id") or oauth_client.get("client_project_id") or "").strip()
    active_project = str(gcloud_probe.get("active_project") or "").strip()
    if oauth_project_id or active_project:
        lines.append("")
    if oauth_project_id:
        lines.append(f"OAuth project: {oauth_project_id}")
    if active_project and active_project != oauth_project_id:
        lines.append(f"Current gcloud project: {active_project}")
    return "\n".join(line for line in lines if line is not None).strip()


def _operator_text_for_google_workspace_oauth(report: Mapping[str, object]) -> str:
    missing_setup = [
        str(item).strip()
        for item in list(report.get("missing_setup") or [])
        if str(item).strip()
    ]
    telegram_delivery = dict(report.get("telegram_delivery") or {})
    parts = [
        f"google_workspace_oauth status={str(report.get('status') or '').strip() or 'unknown'}",
        f"action_required={bool(report.get('user_action_required'))}",
        f"missing={','.join(missing_setup) if missing_setup else 'none'}",
    ]
    next_action = str(report.get("next_action") or "").strip()
    if next_action:
        parts.append(f"next={next_action}")
    oauth_project_id = str(report.get("oauth_project_id") or "").strip()
    if oauth_project_id:
        parts.append(f"oauth_project={oauth_project_id}")
    gcloud_project = str(report.get("gcloud_project") or "").strip()
    if gcloud_project:
        parts.append(f"gcloud_project={gcloud_project}")
    runtime_expected_present = report.get("runtime_expected_google_email_present")
    if runtime_expected_present is not None:
        parts.append(f"runtime_expected_email_present={bool(runtime_expected_present)}")
    last_receipt_status = str(report.get("last_receipt_status") or "").strip()
    if last_receipt_status:
        parts.append(f"last_receipt_status={last_receipt_status}")
    last_receipt_age_seconds = report.get("last_receipt_age_seconds")
    if last_receipt_age_seconds is not None:
        parts.append(f"last_receipt_age_seconds={int(last_receipt_age_seconds)}")
    last_receipt_fresh = report.get("last_receipt_fresh")
    if last_receipt_fresh is not None:
        parts.append(f"last_receipt_fresh={bool(last_receipt_fresh)}")
    telegram_reason = str(telegram_delivery.get("reason") or "").strip()
    if telegram_reason:
        parts.append(f"telegram={telegram_reason}")
    parts.append(f"observed_at={str(report.get('observed_at') or '').strip()}")
    parts.append(f"source={str(report.get('source') or '').strip()}")
    return "; ".join(part for part in parts if part)


def _google_workspace_oauth_receipt_freshness(
    report: Mapping[str, object],
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    try:
        max_age_seconds = max(
            int(
                float(
                    _env(
                        "EA_GOOGLE_WORKSPACE_OAUTH_RECEIPT_MAX_AGE_SECONDS",
                        str(DEFAULT_GOOGLE_WORKSPACE_OAUTH_RECEIPT_MAX_AGE_SECONDS),
                    )
                    or DEFAULT_GOOGLE_WORKSPACE_OAUTH_RECEIPT_MAX_AGE_SECONDS
                )
            ),
            1,
        )
    except (TypeError, ValueError):
        max_age_seconds = int(DEFAULT_GOOGLE_WORKSPACE_OAUTH_RECEIPT_MAX_AGE_SECONDS)
    age_seconds = _utc_age_seconds(report.get("observed_at"), now=now)
    fresh = age_seconds is not None and age_seconds <= max_age_seconds
    return {
        "age_seconds": age_seconds,
        "max_age_seconds": max_age_seconds,
        "fresh": fresh,
    }


def _probe_google_workspace_oauth_without_runtime_expected_email(
    *,
    scope_bundle: str,
    observed_error: str,
    observed_google_email: str,
    test_user_confirmed: bool,
    timeout_seconds: float,
) -> dict[str, object]:
    observed_at = _utc_now()
    receipt_report = probe_google_workspace_oauth_receipt(output_format="json")
    receipt_freshness = _google_workspace_oauth_receipt_freshness(receipt_report)
    last_missing_setup = [
        str(item).strip()
        for item in list(receipt_report.get("missing_setup") or [])
        if str(item).strip()
    ]
    report = {
        "probe_ok": True,
        "ready": False,
        "status": "blocked_setup_required",
        "reason": "expected_google_email_missing",
        "scope_bundle": str(scope_bundle or receipt_report.get("scope_bundle") or google_workspace_oauth_readiness.DEFAULT_SCOPE_BUNDLE).strip()
        or google_workspace_oauth_readiness.DEFAULT_SCOPE_BUNDLE,
        "expected_google_email_present": False,
        "expected_google_domain": str(receipt_report.get("expected_google_domain") or "").strip(),
        "observed_google_email_present": bool(receipt_report.get("observed_google_email_present")),
        "observed_google_domain": str(receipt_report.get("observed_google_domain") or "").strip(),
        "observed_google_account_matches_expected": bool(receipt_report.get("observed_google_account_matches_expected")),
        "runtime_expected_google_email_present": False,
        "missing_setup": ["expected_google_email_missing", *[item for item in last_missing_setup if item != "expected_google_email_missing"]],
        "user_action_required": False,
        "next_action": "set_google_workspace_expected_email_and_refresh_receipt",
        "next_action_href": "/integrations/google",
        "next_action_label": "Configure Google auth",
        "next_action_method": "get",
        "delivery_policy": "queue_only",
        "console_deep_link": str(receipt_report.get("console_deep_link") or "").strip(),
        "auth_link_template": str(receipt_report.get("auth_link_template") or "").strip(),
        "oauth_project_id": str(receipt_report.get("oauth_project_id") or "").strip(),
        "oauth_project_number": str(receipt_report.get("oauth_project_number") or "").strip(),
        "gcloud_project": str(receipt_report.get("gcloud_project") or "").strip(),
        "gcloud_project_matches_oauth_project": bool(receipt_report.get("gcloud_project_matches_oauth_project")),
        "gcloud_account_present": bool(receipt_report.get("gcloud_account_present")),
        "action_context": {
            "scope_bundle": str(scope_bundle or "").strip(),
            "observed_error": str(observed_error or "").strip(),
            "observed_google_email_present": "@" in str(observed_google_email or "").strip().lower(),
            "test_user_confirmed": bool(test_user_confirmed),
            "timeout_seconds": max(float(timeout_seconds or 30.0), 1.0),
        },
        "gcloud_probe": dict(receipt_report.get("gcloud_probe") or {}),
        "privacy": {
            "raw_expected_google_email_exposed": False,
            "raw_auth_link_exposed": False,
        },
        "telegram_delivery": {},
        "last_receipt_status": str(receipt_report.get("status") or "").strip(),
        "last_receipt_reason": str(receipt_report.get("reason") or "").strip(),
        "last_receipt_observed_at": str(receipt_report.get("observed_at") or "").strip(),
        "last_receipt_source": str(receipt_report.get("source") or "").strip(),
        "last_receipt_age_seconds": receipt_freshness.get("age_seconds"),
        "last_receipt_max_age_seconds": receipt_freshness.get("max_age_seconds"),
        "last_receipt_fresh": bool(receipt_freshness.get("fresh")),
        "observed_at": observed_at,
        "source": "ea_live_ops.aggregate",
    }
    report["operator_text"] = _operator_text_for_google_workspace_oauth(report)
    return report


def probe_google_workspace_oauth_receipt(
    *,
    receipt_path: str = "",
    output_format: str = "json",
) -> dict[str, object]:
    path = Path(str(receipt_path or DEFAULT_GOOGLE_WORKSPACE_OAUTH_READINESS_PATH)).expanduser()
    receipt = _load_json_dict(path)
    observed_at = _utc_now()
    if not receipt:
        report = {
            "probe_ok": False,
            "ready": False,
            "status": "probe_failed",
            "reason": "google_workspace_oauth_receipt_missing_or_invalid",
            "scope_bundle": "",
            "expected_google_email_present": False,
            "expected_google_domain": "",
            "observed_google_email_present": False,
            "observed_google_domain": "",
            "observed_google_account_matches_expected": False,
            "missing_setup": [],
            "user_action_required": False,
            "next_action": "inspect_google_workspace_oauth_receipt",
            "next_action_href": "/integrations/google",
            "next_action_label": "Open Google setup",
            "next_action_method": "get",
            "console_deep_link": "",
            "auth_link_template": "",
            "oauth_project_id": "",
            "oauth_project_number": "",
            "gcloud_project": "",
            "gcloud_project_matches_oauth_project": False,
            "gcloud_account_present": False,
            "action_context": {},
            "gcloud_probe": {},
            "privacy": {
                "raw_expected_google_email_exposed": False,
                "raw_auth_link_exposed": False,
            },
            "telegram_delivery": {},
            "observed_at": observed_at,
            "source": f"published_receipt:{path}",
        }
        report["operator_text"] = _operator_text_for_google_workspace_oauth(report)
        return report

    operator_action = dict(receipt.get("operator_action") or {})
    gcloud_probe = dict(receipt.get("gcloud_probe") or {})
    oauth_client = dict(receipt.get("oauth_client") or {})
    expected_account = dict(receipt.get("expected_google_account") or {})
    observed_account = dict(receipt.get("observed_google_account") or {})
    missing_setup = [
        str(item).strip()
        for item in list(receipt.get("missing_setup") or [])
        if str(item).strip()
    ]
    status = str(receipt.get("status") or "unknown").strip() or "unknown"
    report = {
        "probe_ok": True,
        "ready": status in {"pass", "ready_manual_console_check"},
        "status": status,
        "reason": str(receipt.get("blocker_kind") or "").strip() or (missing_setup[0] if missing_setup else ""),
        "scope_bundle": str(receipt.get("scope_bundle") or "").strip(),
        "expected_google_email_present": bool(expected_account.get("present")),
        "expected_google_domain": str(expected_account.get("domain") or "").strip(),
        "observed_google_email_present": bool(observed_account.get("present")),
        "observed_google_domain": str(observed_account.get("domain") or "").strip(),
        "observed_google_account_matches_expected": bool(observed_account.get("matches_expected")),
        "missing_setup": missing_setup,
        "user_action_required": bool(operator_action.get("user_action_required")),
        "next_action": str(operator_action.get("next_action") or "").strip(),
        "next_action_href": str(operator_action.get("next_action_href") or "").strip(),
        "next_action_label": str(operator_action.get("next_action_label") or "").strip(),
        "next_action_method": str(operator_action.get("next_action_method") or "").strip(),
        "delivery_policy": str(operator_action.get("delivery_policy") or "").strip(),
        "console_deep_link": str(receipt.get("console_deep_link") or "").strip(),
        "auth_link_template": str(receipt.get("auth_link_template") or "").strip(),
        "oauth_project_id": str(oauth_client.get("client_project_id") or "").strip(),
        "oauth_project_number": str(oauth_client.get("client_project_number") or "").strip(),
        "gcloud_project": str(gcloud_probe.get("active_project") or "").strip(),
        "gcloud_project_matches_oauth_project": bool(gcloud_probe.get("active_project_matches_oauth_project")),
        "gcloud_account_present": bool(gcloud_probe.get("active_account_present")),
        "action_context": operator_action,
        "gcloud_probe": gcloud_probe,
        "privacy": {
            "raw_expected_google_email_exposed": False,
            "raw_auth_link_exposed": False,
        },
        "telegram_delivery": {},
        "observed_at": str(receipt.get("generated_at") or observed_at).strip() or observed_at,
        "source": f"published_receipt:{path}",
    }
    report["operator_text"] = _operator_text_for_google_workspace_oauth(report)
    return report


def _google_workspace_oauth_probe_context_from_receipt(receipt_path: str = "") -> dict[str, object]:
    path = Path(str(receipt_path or DEFAULT_GOOGLE_WORKSPACE_OAUTH_READINESS_PATH)).expanduser()
    receipt = _load_json_dict(path)
    if not receipt:
        return {}
    observed_account = dict(receipt.get("observed_google_account") or {})
    expected_account = dict(receipt.get("expected_google_account") or {})
    observed_google_email = ""
    if bool(observed_account.get("present")) and bool(observed_account.get("matches_expected")) and bool(expected_account.get("present")):
        observed_google_email = "__expected__"
    return {
        "scope_bundle": str(receipt.get("scope_bundle") or "").strip(),
        "observed_error": str(receipt.get("observed_error") or "").strip(),
        "observed_google_email": observed_google_email,
        "test_user_confirmed": bool(dict(receipt.get("test_user_confirmation") or {}).get("confirmed")),
    }


def _google_workspace_oauth_effective_cli_context(
    *,
    scope_bundle: str,
    observed_error: str,
    observed_google_email: str,
    test_user_confirmed: bool,
    receipt_path: str = "",
) -> dict[str, object]:
    receipt_context = _google_workspace_oauth_probe_context_from_receipt(receipt_path=receipt_path)
    effective_scope_bundle = str(scope_bundle or "").strip() or str(receipt_context.get("scope_bundle") or "").strip()
    effective_observed_error = str(observed_error or "").strip() or str(receipt_context.get("observed_error") or "").strip()
    effective_observed_google_email = str(observed_google_email or "").strip() or str(
        receipt_context.get("observed_google_email") or ""
    ).strip()
    effective_test_user_confirmed = bool(test_user_confirmed or bool(receipt_context.get("test_user_confirmed")))
    return {
        "scope_bundle": effective_scope_bundle,
        "observed_error": effective_observed_error,
        "observed_google_email": effective_observed_google_email,
        "test_user_confirmed": effective_test_user_confirmed,
    }


def probe_google_workspace_oauth(
    *,
    expected_google_email: str,
    scope_bundle: str = google_workspace_oauth_readiness.DEFAULT_SCOPE_BUNDLE,
    observed_error: str = "",
    error_description: str = "",
    observed_google_email: str = "",
    test_user_confirmed: bool = False,
    probe_gcloud: bool = True,
    send_telegram_to_principal: str = "",
    dry_run: bool = False,
    timeout_seconds: float = 30.0,
    output_format: str = "json",
    telegram_operator_streams: tuple[str, ...] | str | None = None,
) -> dict[str, object]:
    normalized_email = str(expected_google_email or "").strip().lower()
    normalized_observed_google_email = str(observed_google_email or "").strip().lower()
    normalized_scope = str(scope_bundle or google_workspace_oauth_readiness.DEFAULT_SCOPE_BUNDLE).strip()
    if not normalized_scope:
        normalized_scope = google_workspace_oauth_readiness.DEFAULT_SCOPE_BUNDLE
    observed_at = _utc_now()
    effective_timeout_seconds = max(float(timeout_seconds or 30.0), 1.0)
    if "@" not in normalized_email:
        report = {
            "probe_ok": False,
            "ready": False,
            "status": "probe_failed",
            "reason": "expected_google_email_missing",
            "operator_stream": OPERATOR_STREAM_OFFICE_SETUP,
            "allowed_operator_streams": list(_effective_telegram_operator_streams(telegram_operator_streams)),
            "scope_bundle": normalized_scope,
            "expected_google_email_present": False,
            "expected_google_domain": "",
            "observed_google_email_present": "@" in normalized_observed_google_email,
            "observed_google_domain": (
                normalized_observed_google_email.rsplit("@", 1)[-1]
                if "@" in normalized_observed_google_email
                else ""
            ),
            "observed_google_account_matches_expected": False,
            "missing_setup": ["expected_google_email_missing"],
            "user_action_required": True,
            "next_action": "add_google_oauth_test_user_and_retry_full_workspace_auth",
            "next_action_href": "/integrations/google",
            "next_action_label": "Open Google setup",
            "next_action_method": "get",
            "oauth_project_id": "",
            "oauth_project_number": "",
            "gcloud_project": "",
            "gcloud_project_matches_oauth_project": False,
            "gcloud_account_present": False,
            "delivery_policy": "action_required_only",
            "telegram_delivery": {},
            "privacy": {
                "raw_expected_google_email_exposed": False,
                "raw_auth_link_exposed": False,
            },
            "observed_at": observed_at,
            "source": "scripts.materialize_google_workspace_oauth_readiness.py",
        }
        report["operator_text"] = _operator_text_for_google_workspace_oauth(report)
        return report

    try:
        receipt = google_workspace_oauth_readiness.build_receipt(
            expected_google_email=normalized_email,
            scope_bundle=normalized_scope,
            observed_error=str(observed_error or "").strip(),
            error_description=str(error_description or "").strip(),
            observed_google_email=normalized_observed_google_email,
            test_user_confirmed=bool(test_user_confirmed),
            probe_gcloud=bool(probe_gcloud),
            include_env_file=ROOT / ".env",
            timeout_seconds=effective_timeout_seconds,
        )
    except Exception as exc:
        report = {
            "probe_ok": False,
            "ready": False,
            "status": "probe_failed",
            "reason": (str(exc).strip() or type(exc).__name__)[:160],
            "operator_stream": OPERATOR_STREAM_OFFICE_SETUP,
            "allowed_operator_streams": list(_effective_telegram_operator_streams(telegram_operator_streams)),
            "scope_bundle": normalized_scope,
            "expected_google_email_present": True,
            "expected_google_domain": normalized_email.rsplit("@", 1)[-1],
            "observed_google_email_present": "@" in normalized_observed_google_email,
            "observed_google_domain": (
                normalized_observed_google_email.rsplit("@", 1)[-1]
                if "@" in normalized_observed_google_email
                else ""
            ),
            "observed_google_account_matches_expected": False,
            "missing_setup": [],
            "user_action_required": False,
            "next_action": "",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
            "oauth_project_id": "",
            "oauth_project_number": "",
            "gcloud_project": "",
            "gcloud_project_matches_oauth_project": False,
            "gcloud_account_present": False,
            "delivery_policy": "queue_only",
            "telegram_delivery": {},
            "privacy": {
                "raw_expected_google_email_exposed": False,
                "raw_auth_link_exposed": False,
            },
            "observed_at": observed_at,
            "source": "scripts.materialize_google_workspace_oauth_readiness.py",
        }
        report["operator_text"] = _operator_text_for_google_workspace_oauth(report)
        return report

    operator_action = dict(receipt.get("operator_action") or {})
    gcloud_probe = dict(receipt.get("gcloud_probe") or {})
    oauth_client = dict(receipt.get("oauth_client") or {})
    expected_account = dict(receipt.get("expected_google_account") or {})
    observed_account = dict(receipt.get("observed_google_account") or {})
    missing_setup = [
        str(item).strip()
        for item in list(receipt.get("missing_setup") or [])
        if str(item).strip()
    ]
    user_action_required = bool(operator_action.get("user_action_required"))
    report = {
        "probe_ok": True,
        "ready": str(receipt.get("status") or "").strip() in {"pass", "ready_manual_console_check"},
        "status": str(receipt.get("status") or "").strip(),
        "reason": str(receipt.get("blocker_kind") or "").strip(),
        "operator_stream": OPERATOR_STREAM_OFFICE_SETUP,
        "allowed_operator_streams": list(_effective_telegram_operator_streams(telegram_operator_streams)),
        "scope_bundle": normalized_scope,
        "expected_google_email_present": bool(expected_account.get("present")),
        "expected_google_domain": str(expected_account.get("domain") or "").strip(),
        "observed_google_email_present": bool(observed_account.get("present")),
        "observed_google_domain": str(observed_account.get("domain") or "").strip(),
        "observed_google_account_matches_expected": bool(observed_account.get("matches_expected")),
        "missing_setup": missing_setup,
        "user_action_required": user_action_required,
        "next_action": str(operator_action.get("next_action") or "").strip(),
        "next_action_href": str(operator_action.get("next_action_href") or "").strip(),
        "next_action_label": str(operator_action.get("next_action_label") or "").strip(),
        "next_action_method": str(operator_action.get("next_action_method") or "").strip(),
        "delivery_policy": str(operator_action.get("delivery_policy") or "").strip(),
        "console_deep_link": str(receipt.get("console_deep_link") or "").strip(),
        "auth_link_template": str(receipt.get("auth_link_template") or "").strip(),
        "oauth_project_id": str(oauth_client.get("client_project_id") or "").strip(),
        "oauth_project_number": str(oauth_client.get("client_project_number") or "").strip(),
        "gcloud_project": str(gcloud_probe.get("active_project") or "").strip(),
        "gcloud_project_matches_oauth_project": bool(gcloud_probe.get("active_project_matches_oauth_project")),
        "gcloud_account_present": bool(gcloud_probe.get("active_account_present")),
        "action_context": operator_action,
        "gcloud_probe": gcloud_probe,
        "privacy": {
            "raw_expected_google_email_exposed": False,
            "raw_auth_link_exposed": False,
        },
        "telegram_delivery": {},
        "observed_at": observed_at,
        "source": "scripts.materialize_google_workspace_oauth_readiness.py",
    }
    if str(send_telegram_to_principal or "").strip():
        if user_action_required:
            direct_auth_link = _google_workspace_oauth_direct_link(
                expected_google_email=normalized_email,
                scope_bundle=normalized_scope,
            )
            allowed_operator_streams = _effective_telegram_operator_streams(telegram_operator_streams)
            if not _telegram_operator_stream_allowed(
                OPERATOR_STREAM_OFFICE_SETUP,
                allowed_operator_streams=allowed_operator_streams,
            ):
                telegram_delivery = _suppressed_telegram_delivery(
                    principal_id=str(send_telegram_to_principal or "").strip(),
                    operator_stream=OPERATOR_STREAM_OFFICE_SETUP,
                    allowed_operator_streams=allowed_operator_streams,
                    observed_at=observed_at,
                    source="scripts.materialize_google_workspace_oauth_readiness.py",
                )
            else:
                telegram_delivery = send_telegram(
                    principal_id=str(send_telegram_to_principal or "").strip(),
                    text=_google_workspace_oauth_telegram_text(
                        receipt=receipt,
                        expected_google_email=normalized_email,
                        direct_auth_link=direct_auth_link,
                    ),
                    dry_run=bool(dry_run),
                    timeout_seconds=effective_timeout_seconds,
                )
        else:
            telegram_delivery = {
                "sent": False,
                "reason": "no_operator_action_required",
                "principal_id": str(send_telegram_to_principal or "").strip(),
                "delivery_transport": "telegram_bot",
                "observed_at": observed_at,
                "source": "scripts.materialize_google_workspace_oauth_readiness.py",
            }
        report["telegram_delivery"] = telegram_delivery
    report["operator_text"] = _operator_text_for_google_workspace_oauth(report)
    if output_format == "operator":
        report["operator_text"] = _operator_text_for_google_workspace_oauth(report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generic EA live-ops provider probing and operator delivery.")
    parser.add_argument("--database-url", default=_env("DATABASE_URL"))
    parser.add_argument("--binding-json", default=_env("EA_WHATSAPP_WEB_READINESS_BINDING_JSON"))
    parser.add_argument("--binding-id", default=_env("EA_WHATSAPP_WEB_DEFAULT_BINDING_ID", "ea-whatsapp-web-session"))
    parser.add_argument("--principal-id", default=_default_whatsapp_principal_id())
    parser.add_argument("--session-api-base-url", default=_env("EA_WHATSAPP_WEB_SESSION_API_BASE_URL", DEFAULT_SESSION_API_BASE_URL))
    parser.add_argument("--session-ref", default=_env("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF"))
    parser.add_argument("--timeout-seconds", type=float, default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe-provider", help="Probe a live provider state.")
    probe.add_argument("--provider", required=True)
    probe.add_argument("--format", choices=("json", "operator"), default="json")
    _add_timeout_seconds_argument(probe)

    provider_cost_pressure = subparsers.add_parser(
        "probe-provider-cost-pressure",
        help="Probe Gemini token pressure and cost-aware background provider routing.",
    )
    provider_cost_pressure.add_argument("--window", choices=("1h", "24h", "7d"), default="24h")
    provider_cost_pressure.add_argument("--principal-id", default="")
    provider_cost_pressure.add_argument("--format", choices=("json", "operator"), default="json")
    _add_timeout_seconds_argument(provider_cost_pressure)

    onemin_direct_refresh_posture = subparsers.add_parser(
        "probe-onemin-direct-refresh",
        help="Summarize the latest bounded 1min.AI direct refresh receipt without exposing private account or chat data.",
    )
    onemin_direct_refresh_posture.add_argument("--receipt-path", default="")
    onemin_direct_refresh_posture.add_argument("--format", choices=("json", "operator"), default="json")

    onemin_direct_refresh = subparsers.add_parser(
        "refresh-onemin-direct-api",
        help="Refresh 1min.AI credits through the bounded direct API lane and optionally send an operator packet over Telegram.",
    )
    onemin_direct_refresh.add_argument("--format", choices=("json", "operator"), default="json")
    onemin_direct_refresh.add_argument("--account-label", action="append", dest="account_labels", default=[])
    onemin_direct_refresh.add_argument("--max-accounts", type=int, default=0)
    onemin_direct_refresh.add_argument("--owner-ledger-path", default="")
    onemin_direct_refresh.add_argument("--output-json", default="")
    onemin_direct_refresh.add_argument("--batch-size", type=int, default=DEFAULT_ONEMIN_DIRECT_REFRESH_BATCH_SIZE)
    onemin_direct_refresh.add_argument("--batch-backoff-seconds", type=float, default=DEFAULT_ONEMIN_DIRECT_REFRESH_BATCH_BACKOFF_SECONDS)
    onemin_direct_refresh.add_argument(
        "--max-rate-limit-sleep-seconds",
        type=float,
        default=DEFAULT_ONEMIN_DIRECT_REFRESH_MAX_RATE_LIMIT_SLEEP_SECONDS,
    )
    onemin_direct_refresh.add_argument(
        "--no-continue-on-rate-limit",
        dest="continue_on_rate_limit",
        action="store_false",
        default=True,
    )
    onemin_direct_refresh.add_argument("--telegram-principal-id", default=_default_proactive_principal_id())
    onemin_direct_refresh.add_argument("--send-telegram", action="store_true")
    onemin_direct_refresh.add_argument("--dry-run", action="store_true")
    _add_telegram_operator_streams_argument(onemin_direct_refresh)
    _add_timeout_seconds_argument(onemin_direct_refresh)

    whatsapp_readiness = subparsers.add_parser("probe-whatsapp-readiness", help="Probe WhatsApp Web action processor readiness.")
    whatsapp_readiness.add_argument("--format", choices=("json", "operator"), default="json")
    whatsapp_readiness.add_argument("--receipt-path", default="")
    whatsapp_readiness.add_argument("--no-refresh", dest="refresh", action="store_false", default=True)
    whatsapp_readiness.add_argument("--volatile", action="store_true", help="Refresh through a temporary receipt file instead of the published receipt.")

    whatsapp_repair = subparsers.add_parser(
        "repair-whatsapp-action-processor",
        help="Start or recreate only the WhatsApp Web action processor service, then re-probe readiness.",
    )
    whatsapp_repair.add_argument("--format", choices=("json", "operator"), default="json")
    whatsapp_repair.add_argument(
        "--compose-file",
        default=_env("EA_WHATSAPP_WEB_COMPOSE_FILE", str(DEFAULT_WHATSAPP_WEB_COMPOSE_FILE)),
    )
    whatsapp_repair.add_argument(
        "--service",
        default=_env("EA_WHATSAPP_WEB_ACTION_PROCESSOR_SERVICE", DEFAULT_WHATSAPP_WEB_ACTION_PROCESSOR_SERVICE),
    )
    whatsapp_repair.add_argument("--dry-run", action="store_true")

    whatsapp_pairing = subparsers.add_parser("probe-whatsapp-pairing", help="Probe and optionally send the live WhatsApp Web pairing QR recovery artifact.")
    whatsapp_pairing.add_argument("--format", choices=("json", "operator"), default="json")
    whatsapp_pairing.add_argument("--telegram-principal-id", default=_default_proactive_principal_id())
    whatsapp_pairing.add_argument("--send-telegram", action="store_true")
    whatsapp_pairing.add_argument("--dry-run", action="store_true")
    whatsapp_pairing.add_argument("--output-dir", default="")
    whatsapp_pairing.add_argument("--no-write-qr-svg", dest="write_qr_svg", action="store_false", default=True)
    _add_telegram_operator_streams_argument(whatsapp_pairing)

    telegram_readiness = subparsers.add_parser("probe-telegram-readiness", help="Probe Telegram operator delivery readiness without sending a message.")
    telegram_readiness.add_argument("--principal-id", dest="telegram_principal_id", default=_default_proactive_principal_id())
    telegram_readiness.add_argument("--format", choices=("json", "operator"), default="json")
    _add_timeout_seconds_argument(telegram_readiness)

    google_workspace_oauth = subparsers.add_parser(
        "probe-google-workspace-oauth",
        help="Probe Google Workspace OAuth readiness and optionally send the action packet over Telegram.",
    )
    google_workspace_oauth.add_argument("--expected-google-email", required=True)
    google_workspace_oauth.add_argument("--scope-bundle", default=google_workspace_oauth_readiness.DEFAULT_SCOPE_BUNDLE)
    google_workspace_oauth.add_argument("--observed-error", default="")
    google_workspace_oauth.add_argument("--error-description", default="")
    google_workspace_oauth.add_argument("--observed-google-email", default="")
    google_workspace_oauth.add_argument("--test-user-confirmed", action="store_true")
    google_workspace_oauth.add_argument("--no-probe-gcloud", dest="probe_gcloud", action="store_false", default=True)
    google_workspace_oauth.add_argument("--telegram-principal-id", default=_default_proactive_principal_id())
    google_workspace_oauth.add_argument("--send-telegram", action="store_true")
    google_workspace_oauth.add_argument("--dry-run", action="store_true")
    google_workspace_oauth.add_argument("--format", choices=("json", "operator"), default="json")
    _add_telegram_operator_streams_argument(google_workspace_oauth)
    _add_timeout_seconds_argument(google_workspace_oauth)

    teable_recovery = subparsers.add_parser("probe-teable-recovery", help="Probe Teable env backup/restore posture without exposing secret values.")
    teable_recovery.add_argument("--format", choices=("json", "operator"), default="json")

    mymedia_alexa = subparsers.add_parser(
        "probe-mymedia-alexa",
        help="Probe My Media for Alexa pairing, indexing, and console posture without exposing secret values.",
    )
    mymedia_alexa.add_argument("--format", choices=("json", "operator"), default="json")
    mymedia_alexa.add_argument("--container-name", default=_env("EA_MYMEDIA_ALEXA_CONTAINER", DEFAULT_MYMEDIA_ALEXA_CONTAINER))
    mymedia_alexa.add_argument("--web-base-url", default=_env("EA_MYMEDIA_ALEXA_WEB_BASE_URL", DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL))
    mymedia_alexa.add_argument("--public-web-base-url", default=_env("EA_MYMEDIA_ALEXA_PUBLIC_BASE_URL", DEFAULT_MYMEDIA_ALEXA_PUBLIC_BASE_URL))
    _add_timeout_seconds_argument(mymedia_alexa)

    mymedia_rescan = subparsers.add_parser(
        "rescan-mymedia-library",
        help="Request a My Media library rescan and return an operator-safe status receipt.",
    )
    mymedia_rescan.add_argument("--format", choices=("json", "operator"), default="json")
    mymedia_rescan.add_argument("--web-base-url", default=_env("EA_MYMEDIA_ALEXA_WEB_BASE_URL", DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL))
    mymedia_rescan.add_argument("--clear-history", action="store_true")
    _add_timeout_seconds_argument(mymedia_rescan)

    mymedia_console_api_repair = subparsers.add_parser(
        "repair-mymedia-console-api",
        help="Restart the My Media container when the local console API is wedged and return an operator-safe receipt.",
    )
    mymedia_console_api_repair.add_argument("--format", choices=("json", "operator"), default="json")
    mymedia_console_api_repair.add_argument(
        "--container-name",
        default=_env("EA_MYMEDIA_ALEXA_CONTAINER", DEFAULT_MYMEDIA_ALEXA_CONTAINER),
    )
    mymedia_console_api_repair.add_argument(
        "--web-base-url",
        default=_env("EA_MYMEDIA_ALEXA_WEB_BASE_URL", DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL),
    )
    _add_timeout_seconds_argument(mymedia_console_api_repair)

    mymedia_public_repair = subparsers.add_parser(
        "repair-mymedia-public-surface",
        help="Repair the Cloudflare-backed My Media public console surface and return an operator-safe receipt.",
    )
    mymedia_public_repair.add_argument("--format", choices=("json", "operator"), default="json")
    mymedia_public_repair.add_argument(
        "--web-base-url",
        default=_env("EA_MYMEDIA_ALEXA_WEB_BASE_URL", DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL),
    )
    mymedia_public_repair.add_argument(
        "--public-web-base-url",
        default=_env("EA_MYMEDIA_ALEXA_PUBLIC_BASE_URL", DEFAULT_MYMEDIA_ALEXA_PUBLIC_BASE_URL),
    )
    mymedia_public_repair.add_argument(
        "--public-tunnel-origin-url",
        default=_env("EA_MYMEDIA_ALEXA_PUBLIC_TUNNEL_ORIGIN_URL", DEFAULT_MYMEDIA_ALEXA_PUBLIC_TUNNEL_ORIGIN_URL),
    )
    _add_timeout_seconds_argument(mymedia_public_repair)

    mymedia_pairing = subparsers.add_parser(
        "trigger-mymedia-amazon-pairing",
        help="Drive the real My Media setup wizard into the Amazon MFA handoff and optionally notify Telegram.",
    )
    mymedia_pairing.add_argument("--format", choices=("json", "operator"), default="json")
    mymedia_pairing.add_argument("--web-base-url", default=_env("EA_MYMEDIA_ALEXA_WEB_BASE_URL", DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL))
    mymedia_pairing.add_argument("--setup-url", default="")
    mymedia_pairing.add_argument(
        "--otp-channel",
        choices=("whatsapp", "sms", "call"),
        default=_mymedia_runtime_default_value(
            env_names=("EA_MYMEDIA_ALEXA_AMAZON_OTP_CHANNEL", "AMAZON_OTP_CHANNEL"),
            payload_keys=("amazon_otp_channel",),
            default=DEFAULT_MYMEDIA_ALEXA_AMAZON_OTP_CHANNEL,
        ),
    )
    mymedia_pairing.add_argument(
        "--phone-suffix",
        default=_mymedia_runtime_default_value(
            env_names=("EA_MYMEDIA_ALEXA_AMAZON_PHONE_SUFFIX", "AMAZON_OTP_SUFFIX"),
            payload_keys=("amazon_phone_suffix",),
            default=DEFAULT_MYMEDIA_ALEXA_AMAZON_PHONE_SUFFIX,
        ),
    )
    mymedia_pairing.add_argument("--output-dir", default="")
    mymedia_pairing.add_argument("--telegram-principal-id", default=_default_proactive_principal_id())
    mymedia_pairing.add_argument("--send-telegram", action="store_true")
    mymedia_pairing.add_argument("--dry-run", action="store_true")
    _add_telegram_operator_streams_argument(mymedia_pairing)
    _add_timeout_seconds_argument(mymedia_pairing)

    mymedia_pairing_submit = subparsers.add_parser(
        "submit-mymedia-amazon-pairing-code",
        help="Resume the saved My Media pairing browser session and submit the Amazon MFA code.",
    )
    mymedia_pairing_submit.add_argument("--otp-code", required=True)
    mymedia_pairing_submit.add_argument("--format", choices=("json", "operator"), default="json")
    mymedia_pairing_submit.add_argument("--web-base-url", default=_env("EA_MYMEDIA_ALEXA_WEB_BASE_URL", DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL))
    mymedia_pairing_submit.add_argument("--output-dir", default="")
    _add_timeout_seconds_argument(mymedia_pairing_submit)

    mymedia_pairing_telegram = subparsers.add_parser(
        "send-mymedia-amazon-pairing-telegram",
        help="Send the My Media Amazon pairing handoff over Telegram, reusing a fresh saved session before retriggering.",
    )
    mymedia_pairing_telegram.add_argument("--format", choices=("json", "operator"), default="json")
    mymedia_pairing_telegram.add_argument("--web-base-url", default=_env("EA_MYMEDIA_ALEXA_WEB_BASE_URL", DEFAULT_MYMEDIA_ALEXA_WEB_BASE_URL))
    mymedia_pairing_telegram.add_argument("--otp-channel", choices=("whatsapp", "sms", "call"), default="")
    mymedia_pairing_telegram.add_argument("--phone-suffix", default="")
    mymedia_pairing_telegram.add_argument("--output-dir", default="")
    mymedia_pairing_telegram.add_argument("--telegram-principal-id", default=_default_proactive_principal_id())
    mymedia_pairing_telegram.add_argument("--dry-run", action="store_true")
    _add_telegram_operator_streams_argument(mymedia_pairing_telegram)
    _add_timeout_seconds_argument(mymedia_pairing_telegram)

    sonarr_tv_season_probe = subparsers.add_parser(
        "probe-sonarr-tv-season",
        help="Probe one Sonarr TV season for missing episodes, metadata-only queue rows, and staging-pack recovery candidates.",
    )
    sonarr_tv_season_probe.add_argument("--series-id", type=int, default=0)
    sonarr_tv_season_probe.add_argument("--series-title", default="")
    sonarr_tv_season_probe.add_argument("--season-number", type=int, required=True)
    sonarr_tv_season_probe.add_argument("--sonarr-base-url", default=_env("EA_SONARR_BASE_URL", DEFAULT_SONARR_BASE_URL))
    sonarr_tv_season_probe.add_argument("--sonarr-config-path", default=_env("EA_SONARR_CONFIG_PATH", str(DEFAULT_SONARR_CONFIG_PATH)))
    sonarr_tv_season_probe.add_argument("--staging-root", default=_env("EA_SONARR_STAGING_ROOT", str(DEFAULT_SONARR_STAGING_ROOT)))
    sonarr_tv_season_probe.add_argument("--format", choices=("json", "operator"), default="json")
    _add_timeout_seconds_argument(sonarr_tv_season_probe)

    sonarr_tv_season_repair = subparsers.add_parser(
        "repair-sonarr-tv-season",
        help="Repair one Sonarr TV season by importing staged files, rescanning the series, and clearing stale metadata-only queue rows.",
    )
    sonarr_tv_season_repair.add_argument("--series-id", type=int, default=0)
    sonarr_tv_season_repair.add_argument("--series-title", default="")
    sonarr_tv_season_repair.add_argument("--season-number", type=int, required=True)
    sonarr_tv_season_repair.add_argument("--sonarr-base-url", default=_env("EA_SONARR_BASE_URL", DEFAULT_SONARR_BASE_URL))
    sonarr_tv_season_repair.add_argument("--sonarr-config-path", default=_env("EA_SONARR_CONFIG_PATH", str(DEFAULT_SONARR_CONFIG_PATH)))
    sonarr_tv_season_repair.add_argument("--staging-root", default=_env("EA_SONARR_STAGING_ROOT", str(DEFAULT_SONARR_STAGING_ROOT)))
    sonarr_tv_season_repair.add_argument("--format", choices=("json", "operator"), default="json")
    _add_timeout_seconds_argument(sonarr_tv_season_repair)

    operator_readiness = subparsers.add_parser("probe-operator-readiness", help="Probe aggregate EA operator readiness without exposing secret values.")
    operator_readiness.add_argument("--format", choices=("json", "operator"), default="json")
    operator_readiness.add_argument("--telegram-principal-id", default=_default_proactive_principal_id())
    operator_readiness.add_argument("--proactive-principal-id", default=_default_proactive_principal_id())
    operator_readiness.add_argument("--compose-file", default=_env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE)))
    operator_readiness.add_argument("--runtime-service", default=_env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE))
    operator_readiness.add_argument("--receipt-path", default=_env("EA_PROACTIVE_OODA_LIVE_RECEIPT_PATH"))
    operator_readiness.add_argument("--no-proactive", dest="include_proactive", action="store_false", default=True)
    operator_readiness.add_argument("--no-pairing", dest="include_pairing", action="store_false", default=True)
    operator_readiness.add_argument(
        "--sonarr-series-id",
        type=int,
        default=_operator_readiness_int_value(_env("EA_OPERATOR_READINESS_SONARR_SERIES_ID", "0"), default=0),
    )
    operator_readiness.add_argument("--sonarr-series-title", default=_env("EA_OPERATOR_READINESS_SONARR_SERIES_TITLE", ""))
    operator_readiness.add_argument(
        "--sonarr-season-number",
        type=int,
        default=_operator_readiness_int_value(_env("EA_OPERATOR_READINESS_SONARR_SEASON_NUMBER", "0"), default=0),
    )
    _add_telegram_operator_streams_argument(operator_readiness)
    _add_timeout_seconds_argument(operator_readiness)

    proactive_route = subparsers.add_parser("probe-proactive-route", help="Probe the live proactive OODA delivery route.")
    proactive_route.add_argument("--principal-id", dest="proactive_principal_id", default=_default_proactive_principal_id())
    proactive_route.add_argument("--format", choices=("json", "operator"), default="json")
    proactive_route.add_argument("--compose-file", default=_env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE)))
    proactive_route.add_argument("--runtime-service", default=_env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE))
    proactive_route.add_argument("--receipt-path", default=_env("EA_PROACTIVE_OODA_LIVE_RECEIPT_PATH"))
    _add_timeout_seconds_argument(proactive_route)

    proactive_artifacts = subparsers.add_parser("probe-proactive-artifacts", help="Probe the live proactive OODA runtime artifacts.")
    proactive_artifacts.add_argument("--format", choices=("json", "operator"), default="json")
    proactive_artifacts.add_argument("--compose-file", default=_env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE)))
    proactive_artifacts.add_argument("--runtime-service", default=_env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE))
    _add_timeout_seconds_argument(proactive_artifacts)

    proactive_quiet = subparsers.add_parser(
        "probe-proactive-action-required-quiet",
        help="Create a live quiet receipt proving non-actionable proactive OODA packets do not notify Telegram.",
    )
    proactive_quiet.add_argument("--principal-id", dest="proactive_principal_id", default=_default_proactive_principal_id())
    proactive_quiet.add_argument("--format", choices=("json", "operator"), default="json")
    proactive_quiet.add_argument("--compose-file", default=_env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE)))
    proactive_quiet.add_argument("--runtime-service", default=_env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE))
    _add_timeout_seconds_argument(proactive_quiet)

    proactive_approval_capture = subparsers.add_parser(
        "probe-proactive-approval-capture",
        help="Probe whether the current Telegram approval callback can be accepted without exposing secret values.",
    )
    proactive_approval_capture.add_argument("--principal-id", dest="proactive_principal_id", default=_default_proactive_principal_id())
    proactive_approval_capture.add_argument("--format", choices=("json", "operator"), default="json")
    proactive_approval_capture.add_argument("--compose-file", default=_env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE)))
    proactive_approval_capture.add_argument("--runtime-service", default=_env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE))
    _add_timeout_seconds_argument(proactive_approval_capture)

    proactive_gmail_draft = subparsers.add_parser(
        "probe-proactive-gmail-draft",
        help="Probe the live Telegram to Gmail draft followthrough lane for the current staged proactive action.",
    )
    proactive_gmail_draft.add_argument("--principal-id", dest="proactive_principal_id", default=_default_proactive_principal_id())
    proactive_gmail_draft.add_argument("--format", choices=("json", "operator"), default="json")
    proactive_gmail_draft.add_argument("--compose-file", default=_env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE)))
    proactive_gmail_draft.add_argument("--runtime-service", default=_env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE))
    proactive_gmail_draft.add_argument("--state-path", default=_env("EA_PROACTIVE_OODA_STATE_PATH"))
    proactive_gmail_draft.add_argument("--receipt-path", default=_env("EA_PROACTIVE_OODA_RECEIPT_PATH"))
    proactive_gmail_draft.add_argument("--stage-packet-dir", default=_env("EA_PROACTIVE_OODA_STAGE_PACKET_DIR"))
    proactive_gmail_draft.add_argument("--safe-work-result-dir", default=_env("EA_PROACTIVE_OODA_SAFE_WORK_RESULT_DIR"))
    _add_timeout_seconds_argument(proactive_gmail_draft)

    proactive_source_coverage = subparsers.add_parser(
        "probe-proactive-source-coverage",
        help="Probe sanitized live source coverage for proactive OODA signal lanes.",
    )
    proactive_source_coverage.add_argument("--principal-id", dest="proactive_principal_id", default=_default_proactive_principal_id())
    proactive_source_coverage.add_argument("--format", choices=("json", "operator"), default="json")
    proactive_source_coverage.add_argument("--compose-file", default=_env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE)))
    proactive_source_coverage.add_argument("--runtime-service", default=_env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE))
    proactive_source_coverage.add_argument("--observation-limit", type=int, default=400)
    _add_timeout_seconds_argument(proactive_source_coverage)

    pocket_sync = subparsers.add_parser(
        "sync-pocket-transcripts",
        help="Run an operator-safe Pocket.ai transcript sync in the live EA runtime.",
    )
    pocket_sync.add_argument("--principal-id", dest="proactive_principal_id", default=_default_proactive_principal_id())
    pocket_sync.add_argument("--format", choices=("json", "operator"), default="json")
    pocket_sync.add_argument("--compose-file", default=_env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE)))
    pocket_sync.add_argument("--runtime-service", default=_env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE))
    pocket_sync.add_argument("--mode", choices=("incremental", "backfill", "archive-reindex"), default="incremental")
    pocket_sync.add_argument("--limit", type=int, default=10)
    _add_timeout_seconds_argument(pocket_sync)

    proactive_approval = subparsers.add_parser(
        "record-proactive-approval",
        help="Record the explicit approval outcome for the current live proactive OODA packet.",
    )
    proactive_approval.add_argument("--principal-id", dest="proactive_principal_id", default=_default_proactive_principal_id())
    proactive_approval.add_argument("--format", choices=("json", "operator"), default="json")
    proactive_approval.add_argument("--compose-file", default=_env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE)))
    proactive_approval.add_argument("--runtime-service", default=_env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE))
    proactive_approval.add_argument("--outcome", required=True)
    proactive_approval.add_argument("--evidence", required=True)
    proactive_approval.add_argument("--actor", default="operator-cli")
    proactive_approval.add_argument("--source-kind", default="operator")
    proactive_approval.add_argument("--packet-ref", default="")
    proactive_approval.add_argument("--staged-artifact-ref", default="")
    proactive_approval.add_argument("--dry-run", action="store_true")
    _add_timeout_seconds_argument(proactive_approval)

    proactive_reissue = subparsers.add_parser(
        "reissue-proactive-approval",
        help="Reissue Telegram approval buttons for the current staged proactive OODA packet.",
    )
    proactive_reissue.add_argument("--principal-id", dest="proactive_principal_id", default=_default_proactive_principal_id())
    proactive_reissue.add_argument("--format", choices=("json", "operator"), default="json")
    proactive_reissue.add_argument("--compose-file", default=_env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE)))
    proactive_reissue.add_argument("--runtime-service", default=_env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE))
    proactive_reissue.add_argument("--dry-run", action="store_true")
    proactive_reissue.add_argument("--force", action="store_true")
    proactive_reissue.add_argument("--reissue-after-seconds", type=int, default=0)
    _add_timeout_seconds_argument(proactive_reissue)

    proactive_callback_cleanup = subparsers.add_parser(
        "cleanup-proactive-approval-callbacks",
        help="Expire or supersede stale Telegram approval callbacks for the current proactive OODA packet.",
    )
    proactive_callback_cleanup.add_argument("--format", choices=("json", "operator"), default="json")
    proactive_callback_cleanup.add_argument("--compose-file", default=_env("EA_PROACTIVE_OODA_RUNTIME_COMPOSE_FILE", str(DEFAULT_PROACTIVE_OODA_COMPOSE_FILE)))
    proactive_callback_cleanup.add_argument("--runtime-service", default=_env("EA_PROACTIVE_OODA_RUNTIME_SERVICE", DEFAULT_PROACTIVE_OODA_RUNTIME_SERVICE))
    proactive_callback_cleanup.add_argument("--execute", action="store_true")
    proactive_callback_cleanup.add_argument("--keep-noncurrent", action="store_true")
    _add_timeout_seconds_argument(proactive_callback_cleanup)

    resolve = subparsers.add_parser("resolve-whatsapp", help="Resolve a WhatsApp recipient from a partial phone hint.")
    resolve.add_argument("--phone-hint", required=True)

    send = subparsers.add_parser("send-whatsapp", help="Send a factual operator update over WhatsApp Web.")
    send.add_argument("--phone-hint", required=True)
    send.add_argument("--text", required=True)
    send.add_argument("--dry-run", action="store_true")

    send_telegram_parser = subparsers.add_parser("send-telegram", help="Send a factual operator update over Telegram.")
    send_telegram_parser.add_argument("--principal-id", dest="telegram_principal_id", default=_default_proactive_principal_id())
    send_telegram_parser.add_argument("--text", required=True)
    send_telegram_parser.add_argument("--dry-run", action="store_true")
    _add_timeout_seconds_argument(send_telegram_parser)

    send_telegram_document_parser = subparsers.add_parser("send-telegram-document", help="Send a local document over Telegram.")
    send_telegram_document_parser.add_argument("--principal-id", dest="telegram_principal_id", default=_default_proactive_principal_id())
    send_telegram_document_parser.add_argument("--document-ref", required=True)
    send_telegram_document_parser.add_argument("--caption", default="")
    send_telegram_document_parser.add_argument("--dry-run", action="store_true")
    _add_timeout_seconds_argument(send_telegram_document_parser)

    send_telegram_video_parser = subparsers.add_parser("send-telegram-video", help="Send a local video over Telegram.")
    send_telegram_video_parser.add_argument("--principal-id", dest="telegram_principal_id", default=_default_proactive_principal_id())
    send_telegram_video_parser.add_argument("--video-ref", required=True)
    send_telegram_video_parser.add_argument("--caption", default="")
    send_telegram_video_parser.add_argument("--fallback-audio-text", default="")
    send_telegram_video_parser.add_argument("--fallback-audio-language", default="")
    send_telegram_video_parser.add_argument("--dry-run", action="store_true")
    _add_timeout_seconds_argument(send_telegram_video_parser)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "probe-provider":
        report = probe_provider(
            args.provider,
            output_format=args.format,
            timeout_seconds=float(getattr(args, "timeout_seconds", None) or 20.0),
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0
    if args.command == "probe-provider-cost-pressure":
        report = probe_provider_cost_pressure(
            window=str(getattr(args, "window", "") or "24h"),
            principal_id=str(getattr(args, "principal_id", "") or "").strip(),
            timeout_seconds=float(getattr(args, "timeout_seconds", None) or 30.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "probe-onemin-direct-refresh":
        report = probe_onemin_direct_refresh_posture(
            receipt_path=str(getattr(args, "receipt_path", "") or "").strip(),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "refresh-onemin-direct-api":
        report = refresh_onemin_direct_api(
            account_labels=list(getattr(args, "account_labels", []) or []),
            max_accounts=int(getattr(args, "max_accounts", 0) or 0),
            owner_ledger_path=str(getattr(args, "owner_ledger_path", "") or "").strip(),
            output_json=str(getattr(args, "output_json", "") or "").strip(),
            batch_size=int(getattr(args, "batch_size", DEFAULT_ONEMIN_DIRECT_REFRESH_BATCH_SIZE) or DEFAULT_ONEMIN_DIRECT_REFRESH_BATCH_SIZE),
            batch_backoff_seconds=float(
                getattr(args, "batch_backoff_seconds", DEFAULT_ONEMIN_DIRECT_REFRESH_BATCH_BACKOFF_SECONDS)
                or DEFAULT_ONEMIN_DIRECT_REFRESH_BATCH_BACKOFF_SECONDS
            ),
            max_rate_limit_sleep_seconds=float(
                getattr(args, "max_rate_limit_sleep_seconds", DEFAULT_ONEMIN_DIRECT_REFRESH_MAX_RATE_LIMIT_SLEEP_SECONDS)
                or DEFAULT_ONEMIN_DIRECT_REFRESH_MAX_RATE_LIMIT_SLEEP_SECONDS
            ),
            continue_on_rate_limit=bool(getattr(args, "continue_on_rate_limit", True)),
            send_telegram_to_principal=(
                str(getattr(args, "telegram_principal_id", "") or "").strip()
                if bool(getattr(args, "send_telegram", False))
                else ""
            ),
            dry_run=bool(getattr(args, "dry_run", False)),
            timeout_seconds=float(getattr(args, "timeout_seconds", None) or 180.0),
            output_format=args.format,
            telegram_operator_streams=str(getattr(args, "telegram_operator_streams", "") or ""),
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        successful_statuses = {"ready", "already_refreshed", "partial_rate_limited", "partial", "dry_run"}
        status = str(report.get("status") or "").strip()
        if not bool(report.get("probe_ok")):
            return 2
        if not bool(getattr(args, "send_telegram", False)):
            return 0 if status in successful_statuses else 2
        delivery = dict(report.get("telegram_delivery") or {})
        reason = str(delivery.get("reason") or "").strip()
        if bool(delivery.get("sent")):
            return 0 if status in successful_statuses else 2
        if reason == "dry_run" and bool(delivery.get("ready")):
            return 0 if status in successful_statuses else 2
        return 2
    if args.command == "probe-whatsapp-readiness":
        report = probe_whatsapp_readiness(
            refresh=bool(getattr(args, "refresh", True)),
            receipt_path=str(getattr(args, "receipt_path", "") or "").strip(),
            output_format=args.format,
            volatile=bool(getattr(args, "volatile", False)),
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "repair-whatsapp-action-processor":
        report = repair_whatsapp_action_processor(
            compose_file=str(getattr(args, "compose_file", "") or "").strip(),
            service=str(getattr(args, "service", "") or "").strip(),
            dry_run=bool(getattr(args, "dry_run", False)),
            timeout_seconds=float(args.timeout_seconds or 60.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "probe-whatsapp-pairing":
        report = probe_whatsapp_pairing(
            args=args,
            output_format=args.format,
            send_telegram_to_principal=(
                str(getattr(args, "telegram_principal_id", "") or "").strip()
                if bool(getattr(args, "send_telegram", False))
                else ""
            ),
            dry_run=bool(getattr(args, "dry_run", False)),
            write_qr_svg=bool(getattr(args, "write_qr_svg", True)),
            output_dir=str(getattr(args, "output_dir", "") or "").strip(),
            telegram_operator_streams=str(getattr(args, "telegram_operator_streams", "") or ""),
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "probe-telegram-readiness":
        report = probe_telegram_readiness(
            principal_id=str(getattr(args, "telegram_principal_id", "") or "").strip(),
            timeout_seconds=float(getattr(args, "timeout_seconds", None) or DEFAULT_TELEGRAM_READINESS_TIMEOUT_SECONDS),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "probe-google-workspace-oauth":
        context = _google_workspace_oauth_effective_cli_context(
            scope_bundle=str(getattr(args, "scope_bundle", "") or "").strip(),
            observed_error=str(getattr(args, "observed_error", "") or "").strip(),
            observed_google_email=str(getattr(args, "observed_google_email", "") or "").strip(),
            test_user_confirmed=bool(getattr(args, "test_user_confirmed", False)),
        )
        report = probe_google_workspace_oauth(
            expected_google_email=str(getattr(args, "expected_google_email", "") or "").strip(),
            scope_bundle=str(context.get("scope_bundle") or "").strip(),
            observed_error=str(context.get("observed_error") or "").strip(),
            error_description=str(getattr(args, "error_description", "") or "").strip(),
            observed_google_email=str(context.get("observed_google_email") or "").strip(),
            test_user_confirmed=bool(context.get("test_user_confirmed")),
            probe_gcloud=bool(getattr(args, "probe_gcloud", True)),
            send_telegram_to_principal=(
                str(getattr(args, "telegram_principal_id", "") or "").strip()
                if bool(getattr(args, "send_telegram", False))
                else ""
            ),
            dry_run=bool(getattr(args, "dry_run", False)),
            timeout_seconds=float(getattr(args, "timeout_seconds", None) or 30.0),
            output_format=args.format,
            telegram_operator_streams=str(getattr(args, "telegram_operator_streams", "") or ""),
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        if not bool(report.get("probe_ok")):
            return 2
        if not bool(getattr(args, "send_telegram", False)):
            return 0
        delivery = dict(report.get("telegram_delivery") or {})
        reason = str(delivery.get("reason") or "").strip()
        if bool(delivery.get("sent")):
            return 0
        if reason == "no_operator_action_required":
            return 0
        if reason == "dry_run" and bool(delivery.get("ready")):
            return 0
        return 2
    if args.command == "probe-teable-recovery":
        report = probe_teable_recovery(
            output_format=args.format,
            timeout_seconds=float(args.timeout_seconds or 30.0),
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("ready")) else 2
    if args.command == "probe-mymedia-alexa":
        report = probe_mymedia_alexa(
            container_name=str(getattr(args, "container_name", "") or "").strip(),
            web_base_url=str(getattr(args, "web_base_url", "") or "").strip(),
            public_web_base_url=str(getattr(args, "public_web_base_url", "") or "").strip(),
            timeout_seconds=float(getattr(args, "timeout_seconds", None) or 15.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "rescan-mymedia-library":
        report = rescan_mymedia_library(
            web_base_url=str(getattr(args, "web_base_url", "") or "").strip(),
            clear_history=bool(getattr(args, "clear_history", False)),
            timeout_seconds=float(getattr(args, "timeout_seconds", None) or 15.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "repair-mymedia-console-api":
        report = repair_mymedia_console_api(
            container_name=str(getattr(args, "container_name", "") or "").strip(),
            web_base_url=str(getattr(args, "web_base_url", "") or "").strip(),
            timeout_seconds=float(getattr(args, "timeout_seconds", None) or 45.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if str(report.get("status") or "").strip() in {"ready", "repaired"} else 2
    if args.command == "repair-mymedia-public-surface":
        report = repair_mymedia_public_surface(
            web_base_url=str(getattr(args, "web_base_url", "") or "").strip(),
            public_web_base_url=str(getattr(args, "public_web_base_url", "") or "").strip(),
            public_tunnel_origin_url=str(getattr(args, "public_tunnel_origin_url", "") or "").strip(),
            timeout_seconds=float(getattr(args, "timeout_seconds", None) or 30.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("ready")) else 2
    if args.command == "probe-sonarr-tv-season":
        report = probe_sonarr_tv_season(
            series_id=(None if int(getattr(args, "series_id", 0) or 0) <= 0 else int(getattr(args, "series_id", 0) or 0)),
            series_title=str(getattr(args, "series_title", "") or "").strip(),
            season_number=int(getattr(args, "season_number", 0) or 0),
            sonarr_base_url=str(getattr(args, "sonarr_base_url", "") or "").strip(),
            sonarr_config_path=str(getattr(args, "sonarr_config_path", "") or "").strip(),
            staging_root=str(getattr(args, "staging_root", "") or "").strip(),
            timeout_seconds=float(getattr(args, "timeout_seconds", None) or 20.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) and str(report.get("status") or "").strip() == "ready" else 2
    if args.command == "repair-sonarr-tv-season":
        report = repair_sonarr_tv_season(
            series_id=(None if int(getattr(args, "series_id", 0) or 0) <= 0 else int(getattr(args, "series_id", 0) or 0)),
            series_title=str(getattr(args, "series_title", "") or "").strip(),
            season_number=int(getattr(args, "season_number", 0) or 0),
            sonarr_base_url=str(getattr(args, "sonarr_base_url", "") or "").strip(),
            sonarr_config_path=str(getattr(args, "sonarr_config_path", "") or "").strip(),
            staging_root=str(getattr(args, "staging_root", "") or "").strip(),
            timeout_seconds=float(getattr(args, "timeout_seconds", None) or 45.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if str(report.get("status") or "").strip() in {"ready", "repaired"} else 2
    if args.command == "trigger-mymedia-amazon-pairing":
        report = trigger_mymedia_amazon_pairing(
            web_base_url=str(getattr(args, "web_base_url", "") or "").strip(),
            setup_url=str(getattr(args, "setup_url", "") or "").strip(),
            otp_channel=str(getattr(args, "otp_channel", "") or "").strip(),
            phone_suffix=str(getattr(args, "phone_suffix", "") or "").strip(),
            send_telegram_to_principal=(
                str(getattr(args, "telegram_principal_id", "") or "").strip()
                if bool(getattr(args, "send_telegram", False))
                else ""
            ),
            dry_run=bool(getattr(args, "dry_run", False)),
            timeout_seconds=float(getattr(args, "timeout_seconds", None) or 45.0),
            output_format=args.format,
            output_dir=str(getattr(args, "output_dir", "") or "").strip(),
            telegram_operator_streams=str(getattr(args, "telegram_operator_streams", "") or ""),
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "submit-mymedia-amazon-pairing-code":
        report = submit_mymedia_amazon_pairing_code(
            otp_code=str(getattr(args, "otp_code", "") or "").strip(),
            web_base_url=str(getattr(args, "web_base_url", "") or "").strip(),
            timeout_seconds=float(getattr(args, "timeout_seconds", None) or 45.0),
            output_format=args.format,
            output_dir=str(getattr(args, "output_dir", "") or "").strip(),
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "send-mymedia-amazon-pairing-telegram":
        report = send_mymedia_amazon_pairing_telegram(
            web_base_url=str(getattr(args, "web_base_url", "") or "").strip(),
            otp_channel=str(getattr(args, "otp_channel", "") or "").strip(),
            phone_suffix=str(getattr(args, "phone_suffix", "") or "").strip(),
            telegram_principal_id=str(getattr(args, "telegram_principal_id", "") or "").strip(),
            dry_run=bool(getattr(args, "dry_run", False)),
            timeout_seconds=float(getattr(args, "timeout_seconds", None) or 45.0),
            output_format=args.format,
            output_dir=str(getattr(args, "output_dir", "") or "").strip(),
            telegram_operator_streams=str(getattr(args, "telegram_operator_streams", "") or ""),
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        if bool(report.get("ready")) and str(report.get("status") or "").strip() == "already_paired":
            return 0
        if bool(report.get("telegram_sent")):
            return 0
        delivery = dict(report.get("telegram_delivery") or {})
        if bool(getattr(args, "dry_run", False)) and str(delivery.get("reason") or "").strip() == "dry_run" and bool(delivery.get("ready")):
            return 0
        return 2
    if args.command == "probe-operator-readiness":
        report = probe_operator_readiness(
            args=args,
            telegram_principal_id=str(getattr(args, "telegram_principal_id", "") or "").strip(),
            proactive_principal_id=str(getattr(args, "proactive_principal_id", "") or "").strip(),
            compose_file=str(getattr(args, "compose_file", "") or "").strip(),
            runtime_service=str(getattr(args, "runtime_service", "") or "").strip(),
            receipt_path=str(getattr(args, "receipt_path", "") or "").strip(),
            timeout_seconds=float(args.timeout_seconds or 30.0),
            include_proactive=bool(getattr(args, "include_proactive", True)),
            include_pairing=bool(getattr(args, "include_pairing", True)),
            sonarr_series_id=int(getattr(args, "sonarr_series_id", 0) or 0),
            sonarr_series_title=str(getattr(args, "sonarr_series_title", "") or "").strip(),
            sonarr_season_number=int(getattr(args, "sonarr_season_number", 0) or 0),
            output_format=args.format,
            telegram_operator_streams=str(getattr(args, "telegram_operator_streams", "") or ""),
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "probe-proactive-route":
        report = probe_proactive_route(
            principal_id=str(getattr(args, "proactive_principal_id", "") or "").strip(),
            compose_file=str(args.compose_file or "").strip(),
            runtime_service=str(args.runtime_service or "").strip(),
            receipt_path=str(args.receipt_path or "").strip(),
            timeout_seconds=float(args.timeout_seconds or 60.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "probe-proactive-artifacts":
        report = probe_proactive_artifacts(
            compose_file=str(args.compose_file or "").strip(),
            runtime_service=str(args.runtime_service or "").strip(),
            timeout_seconds=float(args.timeout_seconds or 60.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "probe-proactive-action-required-quiet":
        report = probe_proactive_action_required_quiet(
            principal_id=str(getattr(args, "proactive_principal_id", "") or "").strip(),
            compose_file=str(args.compose_file or "").strip(),
            runtime_service=str(args.runtime_service or "").strip(),
            timeout_seconds=float(args.timeout_seconds or 60.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "probe-proactive-approval-capture":
        report = probe_proactive_approval_capture(
            principal_id=str(getattr(args, "proactive_principal_id", "") or "").strip(),
            compose_file=str(args.compose_file or "").strip(),
            runtime_service=str(args.runtime_service or "").strip(),
            timeout_seconds=float(args.timeout_seconds or 60.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "probe-proactive-gmail-draft":
        report = probe_proactive_gmail_draft(
            principal_id=str(getattr(args, "proactive_principal_id", "") or "").strip(),
            compose_file=str(args.compose_file or "").strip(),
            runtime_service=str(args.runtime_service or "").strip(),
            state_path=str(args.state_path or "").strip(),
            receipt_path=str(args.receipt_path or "").strip(),
            stage_packet_dir=str(args.stage_packet_dir or "").strip(),
            safe_work_result_dir=str(args.safe_work_result_dir or "").strip(),
            timeout_seconds=float(args.timeout_seconds or 60.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "probe-proactive-source-coverage":
        report = probe_proactive_source_coverage(
            principal_id=str(getattr(args, "proactive_principal_id", "") or "").strip(),
            compose_file=str(args.compose_file or "").strip(),
            runtime_service=str(args.runtime_service or "").strip(),
            observation_limit=int(args.observation_limit or 400),
            timeout_seconds=float(args.timeout_seconds or 60.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) else 2
    if args.command == "sync-pocket-transcripts":
        report = sync_pocket_transcripts(
            principal_id=str(getattr(args, "proactive_principal_id", "") or "").strip(),
            mode=str(args.mode or "incremental").strip(),
            limit=int(args.limit or 10),
            compose_file=str(args.compose_file or "").strip(),
            runtime_service=str(args.runtime_service or "").strip(),
            timeout_seconds=float(args.timeout_seconds or 120.0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("probe_ok")) and str(report.get("status") or "") not in {"blocked", "probe_failed"} else 2
    if args.command == "record-proactive-approval":
        report = record_proactive_approval(
            principal_id=str(getattr(args, "proactive_principal_id", "") or "").strip(),
            outcome=str(args.outcome or "").strip(),
            evidence=str(args.evidence or "").strip(),
            actor=str(args.actor or "").strip(),
            source_kind=str(args.source_kind or "").strip(),
            packet_ref=str(args.packet_ref or "").strip(),
            staged_artifact_ref=str(args.staged_artifact_ref or "").strip(),
            compose_file=str(args.compose_file or "").strip(),
            runtime_service=str(args.runtime_service or "").strip(),
            timeout_seconds=float(args.timeout_seconds or 60.0),
            dry_run=bool(getattr(args, "dry_run", False)),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if bool(report.get("recorded")) or str(report.get("reason") or "") == "dry_run" else 2
    if args.command == "reissue-proactive-approval":
        report = reissue_proactive_approval(
            principal_id=str(getattr(args, "proactive_principal_id", "") or "").strip(),
            compose_file=str(args.compose_file or "").strip(),
            runtime_service=str(args.runtime_service or "").strip(),
            timeout_seconds=float(args.timeout_seconds or 60.0),
            dry_run=bool(getattr(args, "dry_run", False)),
            force=bool(getattr(args, "force", False)),
            reissue_after_seconds=max(int(getattr(args, "reissue_after_seconds", 0) or 0), 0),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if str(report.get("status") or "").strip() in {"sent", "already_live_pending", "already_decided", "dry_run"} else 2
    if args.command == "cleanup-proactive-approval-callbacks":
        report = cleanup_proactive_approval_callbacks(
            compose_file=str(args.compose_file or "").strip(),
            runtime_service=str(args.runtime_service or "").strip(),
            timeout_seconds=float(args.timeout_seconds or 60.0),
            execute=bool(getattr(args, "execute", False)),
            supersede_noncurrent=not bool(getattr(args, "keep_noncurrent", False)),
            output_format=args.format,
        )
        if args.format == "operator":
            print(str(report.get("operator_text") or ""))
        else:
            print(_json_dumps(report))
        return 0 if str(report.get("status") or "").strip() in {"dry_run", "clean", "cleaned"} else 2
    if args.command == "resolve-whatsapp":
        report = resolve_whatsapp(args.phone_hint, args=args)
        print(_json_dumps(report))
        return 0 if str(report.get("status") or "") == "resolved" else 2
    if args.command == "send-whatsapp":
        report = send_whatsapp(phone_hint=args.phone_hint, text=args.text, args=args)
        print(_json_dumps(report))
        return 0 if bool(report.get("sent")) or str(report.get("reason") or "") == "dry_run" else 2
    if args.command == "send-telegram":
        report = send_telegram(
            principal_id=str(getattr(args, "telegram_principal_id", "") or "").strip(),
            text=str(getattr(args, "text", "") or ""),
            dry_run=bool(getattr(args, "dry_run", False)),
            timeout_seconds=float(getattr(args, "timeout_seconds", None) or 30.0),
        )
        print(_json_dumps(report))
        return 0 if bool(report.get("sent")) or (
            str(report.get("reason") or "") == "dry_run" and bool(report.get("ready"))
        ) else 2
    if args.command == "send-telegram-document":
        report = send_telegram_document(
            principal_id=str(getattr(args, "telegram_principal_id", "") or "").strip(),
            document_ref=str(getattr(args, "document_ref", "") or "").strip(),
            caption=str(getattr(args, "caption", "") or ""),
            dry_run=bool(getattr(args, "dry_run", False)),
            timeout_seconds=float(getattr(args, "timeout_seconds", None) or 30.0),
        )
        print(_json_dumps(report))
        return 0 if bool(report.get("sent")) or (
            str(report.get("reason") or "") == "dry_run" and bool(report.get("ready"))
        ) else 2
    if args.command == "send-telegram-video":
        report = send_telegram_video(
            principal_id=str(getattr(args, "telegram_principal_id", "") or "").strip(),
            video_ref=str(getattr(args, "video_ref", "") or "").strip(),
            caption=str(getattr(args, "caption", "") or ""),
            fallback_audio_text=str(getattr(args, "fallback_audio_text", "") or ""),
            fallback_audio_language=str(getattr(args, "fallback_audio_language", "") or ""),
            dry_run=bool(getattr(args, "dry_run", False)),
            timeout_seconds=float(getattr(args, "timeout_seconds", None) or 30.0),
        )
        print(_json_dumps(report))
        return 0 if bool(report.get("sent")) or (
            str(report.get("reason") or "") == "dry_run" and bool(report.get("ready"))
        ) else 2
    raise RuntimeError(f"unsupported_command:{args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
