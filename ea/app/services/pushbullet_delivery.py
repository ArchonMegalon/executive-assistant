from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError

PUSHBULLET_API_BASE_URL = "https://api.pushbullet.com"
PUSHBULLET_ACCOUNT_SETTINGS_URL = "https://www.pushbullet.com/#settings/account"
PUSHBULLET_DOCS_URL = "https://docs.pushbullet.com/"

_CLIENT_KEY_RE = re.compile(r"[^a-z0-9_]+")


@dataclass(frozen=True)
class PushbulletClientConfig:
    client_key: str
    email_env: str
    email_sha256: str
    email_domain: str
    email_present: bool
    token_env: str
    token_present: bool
    source: str


@dataclass(frozen=True)
class PushbulletDeliveryReceipt:
    client_key: str
    status: str
    push_id_hash: str
    push_type: str
    recipient_ref_hash: str
    delivery_transport: str = "pushbullet"


UrlOpen = Callable[..., Any]


def _sha256(value: str) -> str:
    normalized = str(value or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def _email_identity(email: str) -> str:
    normalized = str(email or "").strip().lower()
    if "@" not in normalized:
        return normalized
    local, domain = normalized.split("@", 1)
    if domain in {"gmail.com", "googlemail.com"}:
        return f"{local.replace('.', '')}@gmail.com"
    return f"{local}@{domain}"


def _client_key(value: str) -> str:
    normalized = str(value or "").strip().lower()
    normalized = _CLIENT_KEY_RE.sub("_", normalized).strip("_")
    return normalized or "default"


def _email_domain(email: str) -> str:
    normalized = str(email or "").strip().lower()
    return normalized.rsplit("@", 1)[1] if "@" in normalized else ""


def _env_mapping(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return env if env is not None else os.environ


def _env_value(env: Mapping[str, str], key: str) -> str:
    return str(env.get(key) or "").strip().strip('"').strip("'")


def _client_from_env(
    *,
    env: Mapping[str, str],
    client_key: str,
    email_env: str,
    token_env: str,
    source: str,
) -> PushbulletClientConfig:
    email = _env_value(env, email_env)
    return PushbulletClientConfig(
        client_key=_client_key(client_key),
        email_env=email_env,
        email_sha256=_sha256(_email_identity(email)),
        email_domain=_email_domain(_email_identity(email)),
        email_present=bool(email),
        token_env=token_env,
        token_present=bool(_env_value(env, token_env)),
        source=source,
    )


def discover_pushbullet_clients(env: Mapping[str, str] | None = None) -> tuple[PushbulletClientConfig, ...]:
    values = _env_mapping(env)
    specs: dict[str, dict[str, str]] = {}

    def ensure(key: str) -> dict[str, str]:
        client_key = _client_key(key)
        return specs.setdefault(client_key, {"client_key": client_key, "email_env": "", "token_env": "", "source": ""})

    if _env_value(values, "PB_TOKEN") or _env_value(values, "PUSHBULLET_EMAIL"):
        spec = ensure("default")
        spec["email_env"] = spec["email_env"] or "PUSHBULLET_EMAIL"
        spec["token_env"] = spec["token_env"] or "PB_TOKEN"
        spec["source"] = "legacy_default_env"

    for raw_key in sorted(values):
        key = str(raw_key or "").strip()
        if key.startswith("PB_TOKEN_"):
            suffix = key.removeprefix("PB_TOKEN_")
            spec = ensure(suffix)
            spec["token_env"] = key
            spec["email_env"] = spec["email_env"] or f"PUSHBULLET_{suffix}_EMAIL"
            spec["source"] = spec["source"] or "named_env"
        elif key.startswith("PUSHBULLET_") and key.endswith("_EMAIL") and key != "PUSHBULLET_EMAIL":
            suffix = key.removeprefix("PUSHBULLET_").removesuffix("_EMAIL")
            spec = ensure(suffix)
            spec["email_env"] = key
            spec["token_env"] = spec["token_env"] or f"PB_TOKEN_{suffix}"
            spec["source"] = spec["source"] or "named_env"

    raw_json = _env_value(values, "EA_PUSHBULLET_CLIENTS_JSON")
    if raw_json:
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            parsed = {}
        items = parsed.items() if isinstance(parsed, dict) else enumerate(parsed if isinstance(parsed, list) else [])
        for raw_key, raw_spec in items:
            if not isinstance(raw_spec, dict):
                continue
            spec_key = _client_key(str(raw_spec.get("key") or raw_key or "default"))
            spec = ensure(spec_key)
            if str(raw_spec.get("email_env") or "").strip():
                spec["email_env"] = str(raw_spec.get("email_env") or "").strip()
            if str(raw_spec.get("token_env") or "").strip():
                spec["token_env"] = str(raw_spec.get("token_env") or "").strip()
            spec["source"] = "client_registry_json"

    clients: list[PushbulletClientConfig] = []
    for spec in specs.values():
        token_env = str(spec.get("token_env") or "").strip()
        email_env = str(spec.get("email_env") or "").strip()
        if not token_env and not email_env:
            continue
        clients.append(
            _client_from_env(
                env=values,
                client_key=str(spec.get("client_key") or ""),
                email_env=email_env or f"PUSHBULLET_{str(spec.get('client_key') or '').upper()}_EMAIL",
                token_env=token_env or f"PB_TOKEN_{str(spec.get('client_key') or '').upper()}",
                source=str(spec.get("source") or "env"),
            )
        )
    return tuple(sorted(clients, key=lambda item: item.client_key))


def pushbullet_client_by_key(client_key: str, env: Mapping[str, str] | None = None) -> PushbulletClientConfig | None:
    wanted = _client_key(client_key)
    for client in discover_pushbullet_clients(env):
        if client.client_key == wanted:
            return client
    return None


def _token_for_client(client: PushbulletClientConfig, env: Mapping[str, str]) -> str:
    return _env_value(env, client.token_env)


def _email_for_client(client: PushbulletClientConfig, env: Mapping[str, str]) -> str:
    return _email_identity(_env_value(env, client.email_env))


def _request_json(
    *,
    method: str,
    path: str,
    token: str,
    payload: dict[str, object] | None = None,
    timeout: float = 20.0,
    opener: UrlOpen | None = None,
) -> dict[str, object]:
    normalized_token = str(token or "").strip()
    if not normalized_token:
        raise RuntimeError("pushbullet_token_missing")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{PUSHBULLET_API_BASE_URL}{path}",
        data=body,
        headers={
            "Access-Token": normalized_token,
            "Content-Type": "application/json",
        },
        method=method,
    )
    opener = opener or urllib.request.urlopen
    try:
        with opener(request, timeout=max(float(timeout or 20.0), 1.0)) as response:
            raw = response.read()
    except HTTPError as exc:
        raise RuntimeError(_pushbullet_error_code(exc)) from exc
    except URLError as exc:
        raise RuntimeError("pushbullet_url_error") from exc
    except TimeoutError as exc:
        raise RuntimeError("pushbullet_timeout") from exc
    try:
        parsed = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw or "{}"))
    except Exception as exc:
        raise RuntimeError("pushbullet_response_invalid_json") from exc
    return dict(parsed) if isinstance(parsed, dict) else {}


def _pushbullet_error_code(exc: HTTPError) -> str:
    status = int(getattr(exc, "code", 0) or 0)
    detail = ""
    try:
        raw = exc.read()
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
        if isinstance(parsed, dict):
            error = parsed.get("error")
            if isinstance(error, dict):
                detail = str(error.get("type") or error.get("code") or "").strip().lower()
    except Exception:
        detail = ""
    return f"pushbullet_http_{status}" + (f":{detail}" if detail else "")


def probe_pushbullet_client(
    client_key: str,
    *,
    env: Mapping[str, str] | None = None,
    opener: UrlOpen | None = None,
    timeout: float = 20.0,
) -> dict[str, object]:
    values = _env_mapping(env)
    client = pushbullet_client_by_key(client_key, values)
    if client is None:
        return {"status": "blocked", "reason": "pushbullet_client_missing", "client_key": _client_key(client_key)}
    token = _token_for_client(client, values)
    if not token:
        return {"status": "blocked", "reason": "pushbullet_token_missing", "client_key": client.client_key}
    try:
        user = _request_json(method="GET", path="/v2/users/me", token=token, timeout=timeout, opener=opener)
    except RuntimeError as exc:
        return {"status": "blocked", "reason": str(exc), "client_key": client.client_key}
    email = _email_identity(str(user.get("email_normalized") or user.get("email") or ""))
    expected_hash = client.email_sha256
    actual_hash = _sha256(email)
    email_matches = bool(expected_hash and actual_hash and expected_hash == actual_hash)
    return {
        "status": "pass" if not expected_hash or email_matches else "blocked",
        "reason": "" if not expected_hash or email_matches else "pushbullet_account_email_mismatch",
        "client_key": client.client_key,
        "user_id_hash": _sha256(str(user.get("iden") or "")),
        "email_sha256": actual_hash,
        "email_domain": _email_domain(email),
        "expected_email_matches": email_matches if expected_hash else None,
        "raw_email_exposed": False,
        "raw_token_exposed": False,
    }


def pushbullet_client_email(client_key: str, env: Mapping[str, str] | None = None) -> str:
    values = _env_mapping(env)
    client = pushbullet_client_by_key(client_key, values)
    if client is None:
        return ""
    return _email_for_client(client, values)


def list_pushbullet_pushes(
    client_key: str,
    *,
    modified_after: float = 0.0,
    active_only: bool = True,
    env: Mapping[str, str] | None = None,
    opener: UrlOpen | None = None,
    timeout: float = 20.0,
) -> tuple[dict[str, object], ...]:
    values = _env_mapping(env)
    client = pushbullet_client_by_key(client_key, values)
    if client is None:
        raise RuntimeError("pushbullet_client_missing")
    token = _token_for_client(client, values)
    if not token:
        raise RuntimeError("pushbullet_token_missing")

    pushes: list[dict[str, object]] = []
    cursor = ""
    while True:
        query: dict[str, str] = {
            "modified_after": str(max(float(modified_after or 0.0), 0.0)),
            "active": "true" if active_only else "false",
        }
        if cursor:
            query["cursor"] = cursor
        response = _request_json(
            method="GET",
            path=f"/v2/pushes?{urllib.parse.urlencode(query)}",
            token=token,
            timeout=timeout,
            opener=opener,
        )
        items = response.get("pushes")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    pushes.append(dict(item))
        cursor = str(response.get("cursor") or "").strip()
        if not cursor:
            break
    pushes.sort(key=lambda item: (float(item.get("modified") or 0.0), str(item.get("iden") or "")))
    return tuple(pushes)


def send_pushbullet_note(
    *,
    client_key: str,
    title: str,
    body: str,
    url: str = "",
    target_email: str = "",
    env: Mapping[str, str] | None = None,
    opener: UrlOpen | None = None,
    timeout: float = 20.0,
) -> PushbulletDeliveryReceipt:
    values = _env_mapping(env)
    client = pushbullet_client_by_key(client_key, values)
    if client is None:
        raise RuntimeError("pushbullet_client_missing")
    token = _token_for_client(client, values)
    if not token:
        raise RuntimeError("pushbullet_token_missing")
    push_type = "link" if str(url or "").strip() else "note"
    payload: dict[str, object] = {
        "type": push_type,
        "title": str(title or "").strip(),
        "body": str(body or "").strip(),
    }
    normalized_target_email = str(target_email or "").strip().lower()
    if normalized_target_email:
        payload["email"] = normalized_target_email
    if push_type == "link":
        payload["url"] = str(url or "").strip()
    response = _request_json(
        method="POST",
        path="/v2/pushes",
        token=token,
        payload=payload,
        timeout=timeout,
        opener=opener,
    )
    push_id = str(response.get("iden") or response.get("id") or "").strip()
    return PushbulletDeliveryReceipt(
        client_key=client.client_key,
        status="sent",
        push_id_hash=_sha256(push_id),
        push_type=push_type,
        recipient_ref_hash=client.email_sha256,
    )
