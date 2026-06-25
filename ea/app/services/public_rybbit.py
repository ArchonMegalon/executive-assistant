from __future__ import annotations

import html
import ipaddress
import json
import os
from typing import Any
from urllib.parse import urlparse

from app.services.public_request import request_hostname as _public_request_hostname


_RYBBIT_HOST_CONFIG = {
    "myexternalbrain.com": ("RYBBIT_MYEXTERNALBRAIN_SITE_ID", ""),
    "www.myexternalbrain.com": ("RYBBIT_MYEXTERNALBRAIN_SITE_ID", ""),
}


def _normalize_hostname(hostname: str | None) -> str:
    return str(hostname or "").strip().lower().rstrip(".")


def _rybbit_enabled() -> bool:
    for env_name in ("EA_ENABLE_RYBBIT", "EA_PUBLIC_RYBBIT_ENABLED"):
        if str(os.getenv(env_name) or "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def _configured_public_base_hostname() -> str:
    return _normalize_hostname(urlparse(str(os.getenv("EA_PUBLIC_APP_BASE_URL") or "")).hostname or "")


def _hostname_can_fallback_to_public_base_url(hostname: str) -> bool:
    normalized = _normalize_hostname(hostname)
    if not normalized:
        return True
    if normalized == "localhost":
        return False
    if normalized.endswith((".internal", ".local", ".localhost")):
        return True
    if "." not in normalized:
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return address.is_private and not address.is_loopback


def rybbit_site_id_for_hostname(hostname: str | None) -> str:
    if not _rybbit_enabled():
        return ""
    normalized = _normalize_hostname(hostname)
    config = _RYBBIT_HOST_CONFIG.get(normalized)
    if config is None and _hostname_can_fallback_to_public_base_url(normalized):
        configured_base_host = _configured_public_base_hostname()
        config = _RYBBIT_HOST_CONFIG.get(configured_base_host)
    if not config:
        return ""
    env_name, fallback = config
    return str(os.getenv(env_name) or fallback).strip()


def request_hostname(request: Any) -> str:
    return _public_request_hostname(request)


def _script_attr(name: str, value: str) -> str:
    return f' {name}="{html.escape(value, quote=True)}"'


def rybbit_head_snippet(hostname: str | None) -> str:
    site_id = rybbit_site_id_for_hostname(hostname)
    if not site_id:
        return ""
    script_src = str(os.getenv("EA_PUBLIC_RYBBIT_SCRIPT_SRC") or "https://app.rybbit.io/api/script.js").strip()
    attributes = [
        f'src="{html.escape(script_src, quote=True)}"',
        "async",
        f'data-site-id="{html.escape(site_id, quote=True)}"',
    ]
    optional_map = {
        "EA_PUBLIC_RYBBIT_TAG": "data-tag",
        "EA_PUBLIC_RYBBIT_DEBOUNCE": "data-debounce",
        "EA_PUBLIC_RYBBIT_SKIP_PATTERNS": "data-skip-patterns",
        "EA_PUBLIC_RYBBIT_MASK_PATTERNS": "data-mask-patterns",
    }
    for env_name, attr_name in optional_map.items():
        raw_value = str(os.getenv(env_name) or "").strip()
        if not raw_value:
            continue
        if attr_name in {"data-skip-patterns", "data-mask-patterns"}:
            try:
                parsed = json.loads(raw_value)
                if isinstance(parsed, list):
                    raw_value = json.dumps([str(item) for item in parsed], ensure_ascii=True, separators=(",", ":"))
            except json.JSONDecodeError:
                pass
        attributes.append(f'{attr_name}="{html.escape(raw_value, quote=True)}"')
    return "<script " + " ".join(attributes) + "></script>"
