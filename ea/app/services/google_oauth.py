from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any

from app.domain.models import ConnectorBinding, ProviderBindingRecord

if TYPE_CHECKING:
    from app.container import AppContainer

GOOGLE_PROVIDER_KEY = "google_gmail"
GOOGLE_CONNECTOR_NAME = "google_workspace"
GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"

GOOGLE_SCOPE_IDENTITY = (
    "openid",
    "email",
    "profile",
)
GOOGLE_SCOPE_SEND = "https://www.googleapis.com/auth/gmail.send"
GOOGLE_SCOPE_METADATA = "https://www.googleapis.com/auth/gmail.metadata"
GOOGLE_SCOPE_GMAIL_MODIFY = "https://www.googleapis.com/auth/gmail.modify"
GOOGLE_SCOPE_CALENDAR = "https://www.googleapis.com/auth/calendar"
GOOGLE_SCOPE_CALENDAR_READONLY = "https://www.googleapis.com/auth/calendar.readonly"
GOOGLE_SCOPE_CONTACTS_READONLY = "https://www.googleapis.com/auth/contacts.readonly"
GOOGLE_SCOPE_DRIVE_METADATA_READONLY = "https://www.googleapis.com/auth/drive.metadata.readonly"

GOOGLE_SCOPE_SEND_ONLY = GOOGLE_SCOPE_IDENTITY + (
    GOOGLE_SCOPE_SEND,
)

GOOGLE_SCOPE_VERIFY = GOOGLE_SCOPE_IDENTITY + (
    GOOGLE_SCOPE_SEND,
    GOOGLE_SCOPE_METADATA,
)

GOOGLE_SCOPE_CORE = GOOGLE_SCOPE_IDENTITY + (
    GOOGLE_SCOPE_SEND,
    GOOGLE_SCOPE_METADATA,
    GOOGLE_SCOPE_CALENDAR_READONLY,
    GOOGLE_SCOPE_CONTACTS_READONLY,
)

GOOGLE_SCOPE_FULL_WORKSPACE = GOOGLE_SCOPE_IDENTITY + (
    GOOGLE_SCOPE_SEND,
    GOOGLE_SCOPE_METADATA,
    GOOGLE_SCOPE_GMAIL_MODIFY,
    GOOGLE_SCOPE_CALENDAR,
    GOOGLE_SCOPE_CONTACTS_READONLY,
    GOOGLE_SCOPE_DRIVE_METADATA_READONLY,
)

SCOPE_BUNDLES: dict[str, tuple[str, ...]] = {
    "send": GOOGLE_SCOPE_SEND_ONLY,
    "verify": GOOGLE_SCOPE_VERIFY,
    "core": GOOGLE_SCOPE_CORE,
    "full_workspace": GOOGLE_SCOPE_FULL_WORKSPACE,
    "all": GOOGLE_SCOPE_FULL_WORKSPACE,
}

SCOPE_BUNDLE_METADATA: dict[str, dict[str, object]] = {
    "send": {
        "label": "Send only",
        "summary": "Sign in and send mail from the connected Gmail account.",
        "capabilities": (
            "Sign in with Google identity",
            "Send draft and operator-approved mail",
        ),
        "limitations": (
            "No mailbox verification",
            "No calendar context",
            "No contact enrichment",
        ),
    },
    "verify": {
        "label": "Advanced Gmail verify",
        "summary": "Add mailbox metadata verification without expanding into calendar or contacts.",
        "capabilities": (
            "Send mail",
            "Verify delivery using Gmail metadata",
        ),
        "limitations": (
            "No calendar context",
            "No contacts context",
            "No inbox modification",
        ),
    },
    "core": {
        "label": "Google Core",
        "summary": "The practical default: Gmail send/verify plus calendar and contacts read context.",
        "capabilities": (
            "Send mail",
            "Mailbox verification",
            "Calendar read context",
            "Contacts read context",
        ),
        "limitations": (
            "No inbox mutation",
            "No Drive file index context",
        ),
    },
    "full_workspace": {
        "label": "Google Full Workspace",
        "summary": "Broader assistant context: inbox actions plus richer calendar and Drive index context.",
        "capabilities": (
            "Inbox understanding and modification",
            "Richer calendar actions",
            "Drive file index context",
        ),
        "limitations": (
            "Still not a promise that every Google surface is integrated today",
        ),
    },
    "all": {
        "label": "Google Full Workspace",
        "summary": "Alias for the full workspace bundle.",
        "capabilities": (
            "Inbox understanding and modification",
            "Richer calendar actions",
            "Drive file index context",
        ),
        "limitations": (
            "Still not a promise that every Google surface is integrated today",
        ),
    },
}


def google_scope_bundle_details(bundle: str | None) -> dict[str, object]:
    normalized = normalize_scope_bundle(bundle)
    metadata = dict(SCOPE_BUNDLE_METADATA.get(normalized) or {})
    metadata["bundle"] = normalized
    metadata["scopes"] = list(SCOPE_BUNDLES[normalized])
    return metadata


@dataclass(frozen=True)
class GoogleOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    state_secret: str
    provider_secret_key: str


@dataclass(frozen=True)
class GoogleOAuthStartPacket:
    principal_id: str
    scope_bundle: str
    requested_scopes: tuple[str, ...]
    state: str
    auth_url: str
    redirect_uri: str


@dataclass(frozen=True)
class GoogleOAuthAccount:
    binding: ProviderBindingRecord
    connector_binding: ConnectorBinding | None
    google_email: str
    google_subject: str
    google_hosted_domain: str
    granted_scopes: tuple[str, ...]
    consent_stage: str
    workspace_mode: str
    token_status: str
    last_refresh_at: str
    reauth_required_reason: str


@dataclass(frozen=True)
class GoogleGmailSmokeResult:
    binding: ProviderBindingRecord
    sender_email: str
    recipient_email: str
    rfc822_message_id: str
    gmail_message_id: str
    sent_at: str


def load_google_oauth_config() -> GoogleOAuthConfig:
    client_id = str(os.environ.get("EA_GOOGLE_OAUTH_CLIENT_ID") or "").strip()
    client_secret = str(os.environ.get("EA_GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()
    redirect_uri = str(os.environ.get("EA_GOOGLE_OAUTH_REDIRECT_URI") or "").strip()
    state_secret = str(os.environ.get("EA_GOOGLE_OAUTH_STATE_SECRET") or "").strip()
    provider_secret_key = str(os.environ.get("EA_PROVIDER_SECRET_KEY") or "").strip()
    if not client_id:
        raise RuntimeError("google_oauth_client_id_missing")
    if not client_secret:
        raise RuntimeError("google_oauth_client_secret_missing")
    if not redirect_uri:
        raise RuntimeError("google_oauth_redirect_uri_missing")
    if not state_secret:
        raise RuntimeError("google_oauth_state_secret_missing")
    if not provider_secret_key:
        raise RuntimeError("google_oauth_provider_secret_key_missing")
    return GoogleOAuthConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        state_secret=state_secret,
        provider_secret_key=provider_secret_key,
    )


def normalize_scope_bundle(raw: str | None) -> str:
    bundle = str(raw or "send").strip().lower() or "send"
    if bundle not in SCOPE_BUNDLES:
        raise RuntimeError("google_oauth_scope_bundle_invalid")
    return bundle


def build_google_oauth_start(
    *,
    principal_id: str,
    scope_bundle: str,
    redirect_uri_override: str | None = None,
) -> GoogleOAuthStartPacket:
    config = load_google_oauth_config()
    normalized_bundle = normalize_scope_bundle(scope_bundle)
    requested_scopes = SCOPE_BUNDLES[normalized_bundle]
    redirect_uri = str(redirect_uri_override or config.redirect_uri).strip() or config.redirect_uri
    state = _encode_signed_state(
        {
            "principal_id": principal_id,
            "scope_bundle": normalized_bundle,
            "redirect_uri": redirect_uri,
            "nonce": secrets.token_urlsafe(12),
            "issued_at": int(time.time()),
        },
        secret=config.state_secret,
    )
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(requested_scopes),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
    )
    return GoogleOAuthStartPacket(
        principal_id=principal_id,
        scope_bundle=normalized_bundle,
        requested_scopes=requested_scopes,
        state=state,
        auth_url=f"{GOOGLE_AUTH_ENDPOINT}?{query}",
        redirect_uri=redirect_uri,
    )


def complete_google_oauth_callback(
    *,
    container: AppContainer,
    code: str,
    state: str,
) -> GoogleOAuthAccount:
    config = load_google_oauth_config()
    state_payload = _decode_signed_state(state, secret=config.state_secret)
    principal_id = str(state_payload.get("principal_id") or "").strip()
    if not principal_id:
        raise RuntimeError("google_oauth_principal_missing")
    scope_bundle = normalize_scope_bundle(str(state_payload.get("scope_bundle") or "send"))
    redirect_uri = str(state_payload.get("redirect_uri") or config.redirect_uri).strip() or config.redirect_uri
    token_payload = _exchange_google_code_for_tokens(
        code=code,
        client_id=config.client_id,
        client_secret=config.client_secret,
        redirect_uri=redirect_uri,
    )
    userinfo = _fetch_google_userinfo(str(token_payload.get("access_token") or "").strip())
    google_subject = str(userinfo.get("sub") or "").strip()
    google_email = str(userinfo.get("email") or "").strip().lower()
    if not google_subject or not google_email:
        raise RuntimeError("google_oauth_userinfo_incomplete")

    granted_scopes = tuple(
        sorted(
            {
                scope.strip()
                for scope in str(token_payload.get("scope") or "").split(" ")
                if scope.strip()
            }
        )
    ) or SCOPE_BUNDLES[scope_bundle]
    consent_stage = "verify" if GOOGLE_SCOPE_METADATA in granted_scopes else "send"
    encrypted_refresh = ""
    refresh_token = str(token_payload.get("refresh_token") or "").strip()
    existing = container.provider_registry.get_persisted_binding_record(
        binding_id=f"{principal_id}:{GOOGLE_PROVIDER_KEY}",
        principal_id=principal_id,
    )
    existing_metadata = dict(existing.auth_metadata_json or {}) if existing is not None else {}
    if refresh_token:
        encrypted_refresh = _encrypt_secret(refresh_token, key=config.provider_secret_key)
    else:
        encrypted_refresh = str(existing_metadata.get("refresh_token_ref") or "").strip()
    expires_in = _safe_int(token_payload.get("expires_in"), default=0)
    access_token_expires_at = ""
    if expires_in > 0:
        access_token_expires_at = _utc_iso_after_seconds(expires_in)
    auth_metadata_json = {
        "google_subject": google_subject,
        "google_email": google_email,
        "google_hosted_domain": str(userinfo.get("hd") or "").strip(),
        "granted_scopes": list(granted_scopes),
        "refresh_token_ref": encrypted_refresh,
        "access_token_expires_at": access_token_expires_at,
        "token_status": "active",
        "consent_stage": consent_stage,
        "workspace_mode": "user_oauth",
        "last_successful_api_call_at": _utc_iso_now(),
        "last_refresh_at": _utc_iso_now(),
        "reauth_required_reason": "",
    }
    scope_json = {
        "bundle": scope_bundle,
        "scopes": list(granted_scopes),
    }
    probe_details_json = {
        "google_email": google_email,
        "google_subject": google_subject,
        "consent_stage": consent_stage,
        "workspace_mode": "user_oauth",
    }
    binding = container.provider_registry.upsert_binding_record(
        principal_id=principal_id,
        provider_key=GOOGLE_PROVIDER_KEY,
        status="enabled",
        priority=80,
        scope_json=scope_json,
        auth_metadata_json=auth_metadata_json,
        probe_state="ready",
        probe_details_json=probe_details_json,
    )
    connector_binding = container.tool_runtime.upsert_connector_binding(
        principal_id=principal_id,
        connector_name=GOOGLE_CONNECTOR_NAME,
        external_account_ref=str(userinfo.get("hd") or google_email),
        scope_json={"scopes": list(granted_scopes), "bundle": scope_bundle},
        auth_metadata_json={
            "google_email": google_email,
            "google_subject": google_subject,
            "google_hosted_domain": str(userinfo.get("hd") or "").strip(),
            "workspace_mode": "user_oauth",
        },
        status="enabled",
    )
    return GoogleOAuthAccount(
        binding=binding,
        connector_binding=connector_binding,
        google_email=google_email,
        google_subject=google_subject,
        google_hosted_domain=str(userinfo.get("hd") or "").strip(),
        granted_scopes=granted_scopes,
        consent_stage=consent_stage,
        workspace_mode="user_oauth",
        token_status="active",
        last_refresh_at=auth_metadata_json["last_refresh_at"],
        reauth_required_reason="",
    )


def upgrade_google_oauth_scope(
    *,
    principal_id: str,
    scope_bundle: str,
) -> GoogleOAuthStartPacket:
    return build_google_oauth_start(principal_id=principal_id, scope_bundle=scope_bundle)


def disconnect_google_account(
    *,
    container: AppContainer,
    principal_id: str,
) -> ProviderBindingRecord:
    binding = container.provider_registry.get_persisted_binding_record(
        binding_id=f"{principal_id}:{GOOGLE_PROVIDER_KEY}",
        principal_id=principal_id,
    )
    if binding is None:
        raise RuntimeError("google_oauth_binding_not_found")
    auth_metadata_json = dict(binding.auth_metadata_json or {})
    auth_metadata_json["token_status"] = "revoked"
    auth_metadata_json["reauth_required_reason"] = "disconnected_by_operator"
    auth_metadata_json["refresh_token_ref"] = ""
    updated = container.provider_registry.upsert_binding_record(
        principal_id=principal_id,
        provider_key=GOOGLE_PROVIDER_KEY,
        status="disabled",
        priority=binding.priority,
        probe_state="revoked",
        probe_details_json=dict(binding.probe_details_json or {}),
        scope_json=dict(binding.scope_json or {}),
        auth_metadata_json=auth_metadata_json,
    )
    return updated


def run_google_gmail_smoke_test(
    *,
    container: AppContainer,
    principal_id: str,
    recipient_email: str | None = None,
) -> GoogleGmailSmokeResult:
    config = load_google_oauth_config()
    binding = container.provider_registry.get_persisted_binding_record(
        binding_id=f"{principal_id}:{GOOGLE_PROVIDER_KEY}",
        principal_id=principal_id,
    )
    if binding is None:
        raise RuntimeError("google_oauth_binding_not_found")
    metadata = dict(binding.auth_metadata_json or {})
    granted_scopes = {
        str(scope or "").strip()
        for scope in (metadata.get("granted_scopes") or [])
        if str(scope or "").strip()
    }
    if GOOGLE_SCOPE_SEND not in granted_scopes:
        raise RuntimeError("google_gmail_send_scope_missing")
    refresh_token_ref = str(metadata.get("refresh_token_ref") or "").strip()
    if not refresh_token_ref:
        raise RuntimeError("google_gmail_refresh_token_missing")
    refresh_token = _decrypt_secret(refresh_token_ref, key=config.provider_secret_key)
    token_payload = _refresh_google_access_token(
        refresh_token=refresh_token,
        client_id=config.client_id,
        client_secret=config.client_secret,
    )
    access_token = str(token_payload.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("google_gmail_access_token_missing")
    sender_email = str(metadata.get("google_email") or "").strip().lower()
    if not sender_email:
        raise RuntimeError("google_gmail_sender_missing")
    to_email = str(recipient_email or sender_email).strip().lower() or sender_email
    rfc822_message_id = f"<ea-smoke-{secrets.token_hex(8)}@ea.local>"
    raw_message = _build_gmail_smoke_message(
        sender_email=sender_email,
        recipient_email=to_email,
        message_id=rfc822_message_id,
    )
    gmail_message_id = _gmail_send_message(access_token=access_token, raw_message=raw_message)
    updated_metadata = dict(metadata)
    updated_metadata["access_token_expires_at"] = _utc_iso_after_seconds(_safe_int(token_payload.get("expires_in"), default=0))
    updated_metadata["last_refresh_at"] = _utc_iso_now()
    updated_metadata["last_successful_api_call_at"] = _utc_iso_now()
    updated_metadata["token_status"] = "active"
    updated = container.provider_registry.upsert_binding_record(
        principal_id=principal_id,
        provider_key=GOOGLE_PROVIDER_KEY,
        status=binding.status,
        priority=binding.priority,
        probe_state="ready",
        probe_details_json=dict(binding.probe_details_json or {}),
        scope_json=dict(binding.scope_json or {}),
        auth_metadata_json=updated_metadata,
    )
    return GoogleGmailSmokeResult(
        binding=updated,
        sender_email=sender_email,
        recipient_email=to_email,
        rfc822_message_id=rfc822_message_id,
        gmail_message_id=gmail_message_id,
        sent_at=updated_metadata["last_successful_api_call_at"],
    )


def list_google_accounts(*, container: AppContainer, principal_id: str) -> list[GoogleOAuthAccount]:
    connector_by_ref: dict[str, ConnectorBinding] = {}
    for connector in container.tool_runtime.list_connector_bindings(principal_id=principal_id, limit=100):
        if connector.connector_name == GOOGLE_CONNECTOR_NAME:
            connector_by_ref[connector.external_account_ref] = connector
    accounts: list[GoogleOAuthAccount] = []
    for binding in container.provider_registry.list_persisted_binding_records(principal_id=principal_id, limit=100):
        if binding.provider_key != GOOGLE_PROVIDER_KEY:
            continue
        metadata = dict(binding.auth_metadata_json or {})
        google_email = str(metadata.get("google_email") or "").strip().lower()
        google_hosted_domain = str(metadata.get("google_hosted_domain") or "").strip()
        connector = connector_by_ref.get(google_hosted_domain or google_email)
        accounts.append(
            GoogleOAuthAccount(
                binding=binding,
                connector_binding=connector,
                google_email=google_email,
                google_subject=str(metadata.get("google_subject") or "").strip(),
                google_hosted_domain=google_hosted_domain,
                granted_scopes=tuple(
                    sorted(str(scope or "").strip() for scope in (metadata.get("granted_scopes") or []) if str(scope or "").strip())
                ),
                consent_stage=str(metadata.get("consent_stage") or "").strip() or "send",
                workspace_mode=str(metadata.get("workspace_mode") or "").strip() or "user_oauth",
                token_status=str(metadata.get("token_status") or "").strip() or "unknown",
                last_refresh_at=str(metadata.get("last_refresh_at") or "").strip(),
                reauth_required_reason=str(metadata.get("reauth_required_reason") or "").strip(),
            )
        )
    return accounts


def _exchange_google_code_for_tokens(*, code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict[str, Any]:
    payload = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        GOOGLE_TOKEN_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _refresh_google_access_token(*, refresh_token: str, client_id: str, client_secret: str) -> dict[str, Any]:
    payload = urllib.parse.urlencode(
        {
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        GOOGLE_TOKEN_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _gmail_send_message(*, access_token: str, raw_message: str) -> str:
    body = json.dumps({"raw": raw_message}).encode("utf-8")
    request = urllib.request.Request(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        data=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    message_id = str(payload.get("id") or "").strip()
    if not message_id:
        raise RuntimeError("google_gmail_send_missing_message_id")
    return message_id


def _fetch_google_userinfo(access_token: str) -> dict[str, Any]:
    if not access_token:
        raise RuntimeError("google_oauth_access_token_missing")
    request = urllib.request.Request(
        GOOGLE_USERINFO_ENDPOINT,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _encode_signed_state(payload: dict[str, Any], *, secret: str) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body_b64 = _b64url_encode(body)
    signature = hmac.new(secret.encode("utf-8"), body_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{body_b64}.{_b64url_encode(signature)}"


def _decode_signed_state(state: str, *, secret: str) -> dict[str, Any]:
    raw = str(state or "").strip()
    if "." not in raw:
        raise RuntimeError("google_oauth_state_invalid")
    body_b64, signature_b64 = raw.split(".", 1)
    expected = hmac.new(secret.encode("utf-8"), body_b64.encode("ascii"), hashlib.sha256).digest()
    provided = _b64url_decode(signature_b64)
    if not hmac.compare_digest(expected, provided):
        raise RuntimeError("google_oauth_state_signature_invalid")
    payload = json.loads(_b64url_decode(body_b64).decode("utf-8"))
    issued_at = _safe_int(payload.get("issued_at"), default=0)
    if issued_at <= 0 or time.time() - issued_at > 900:
        raise RuntimeError("google_oauth_state_expired")
    return payload


def _encrypt_secret(value: str, *, key: str) -> str:
    if not value:
        return ""
    env = dict(os.environ)
    env["EA_GOOGLE_OAUTH_ENCRYPTION_KEY"] = key
    proc = subprocess.run(
        [
            "openssl",
            "enc",
            "-aes-256-cbc",
            "-pbkdf2",
            "-a",
            "-A",
            "-salt",
            "-pass",
            "env:EA_GOOGLE_OAUTH_ENCRYPTION_KEY",
        ],
        input=value.encode("utf-8"),
        capture_output=True,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"google_oauth_encrypt_failed:{proc.stderr.decode('utf-8', errors='ignore').strip()}")
    return proc.stdout.decode("utf-8").strip()


def _decrypt_secret(value: str, *, key: str) -> str:
    env = dict(os.environ)
    env["EA_GOOGLE_OAUTH_ENCRYPTION_KEY"] = key
    proc = subprocess.run(
        [
            "openssl",
            "enc",
            "-aes-256-cbc",
            "-pbkdf2",
            "-a",
            "-A",
            "-d",
            "-salt",
            "-pass",
            "env:EA_GOOGLE_OAUTH_ENCRYPTION_KEY",
        ],
        input=value.encode("utf-8"),
        capture_output=True,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"google_oauth_decrypt_failed:{proc.stderr.decode('utf-8', errors='ignore').strip()}")
    return proc.stdout.decode("utf-8").strip()


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _utc_iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _utc_iso_after_seconds(seconds: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + max(0, int(seconds))))


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def _build_gmail_smoke_message(*, sender_email: str, recipient_email: str, message_id: str) -> str:
    message = EmailMessage()
    message["From"] = sender_email
    message["To"] = recipient_email
    message["Subject"] = "EA Gmail smoke test"
    message["Message-ID"] = message_id
    message["X-EA-Smoke-Test"] = "google-gmail-send"
    message.set_content(
        "This is an EA Gmail smoke test. If you received it, the send-only OAuth path is working."
    )
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
