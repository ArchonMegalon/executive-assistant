#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass


DEFAULT_TENANT_ID = "tenant-default"
DEFAULT_TENANT_NAME = "Default Tenant"
DEFAULT_TENANT_SLUG = "default"
DEFAULT_PRINCIPAL_ID = "principal-default"
DEFAULT_DISPLAY_NAME = "Executive Assistant Operator"
DEFAULT_EMAIL = "operator@example.test"
DEFAULT_PHONE_NUMBER = "+15555550100"
DEFAULT_SESSION_LABEL = "Executive Assistant WhatsApp Web Session"
DEFAULT_BINDING_ID = "ea-whatsapp-web-session"
DEFAULT_CONNECTOR_STATUS = "staged"

WHATSAPP_WEB_SESSION_CONNECTOR = "whatsapp_web_session"


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def phone_digits(phone_number: str) -> str:
    return "".join(ch for ch in str(phone_number or "") if ch.isdigit())


def normalized_phone(phone_number: str) -> str:
    raw = str(phone_number or "").strip()
    digits = phone_digits(raw)
    if len(digits) < 7:
        raise ValueError("whatsapp_web_phone_number_invalid")
    return raw if raw.startswith("+") else f"+{digits}"


@dataclass(frozen=True)
class WhatsAppWebSessionSeed:
    tenant_id: str
    tenant_name: str
    tenant_slug: str
    principal_id: str
    display_name: str
    email: str
    phone_number: str
    session_label: str
    binding_id: str
    session_ref: str = ""
    session_store_ref: str = ""
    browser_profile_ref: str = ""
    session_send_url_template: str = ""
    session_status_url_template: str = ""
    session_api_base_url: str = ""
    session_api_token: str = ""
    auth_header_name: str = ""
    auth_header_prefix: str = ""
    connector_status: str = DEFAULT_CONNECTOR_STATUS

    @property
    def phone_number_digits(self) -> str:
        return phone_digits(self.phone_number)

    @property
    def connector_name(self) -> str:
        return WHATSAPP_WEB_SESSION_CONNECTOR

    @property
    def delivery_channel(self) -> str:
        return "whatsapp"

    @property
    def delivery_transport(self) -> str:
        return WHATSAPP_WEB_SESSION_CONNECTOR

    @property
    def session_status(self) -> str:
        return "web_session_ready" if self.session_ref and (self.session_store_ref or self.browser_profile_ref) else "web_session_missing"

    def identity_profile(self) -> dict[str, object]:
        return {
            "phone_number": self.phone_number,
            "phone_number_digits": self.phone_number_digits,
            "session_label": self.session_label,
            "source": "operator_seed",
            "tenant_id": self.tenant_id,
            "transport": self.delivery_transport,
        }

    def service_routes_json(self) -> dict[str, object]:
        return {
            "applies_to": [
                "connector.dispatch",
                "delivery.send",
                "executive_assistant_channel_send",
                "operator_summary",
                "support_reply",
                "public_signal",
            ],
            "default_delivery_channel": self.delivery_channel,
            "default_transport": self.delivery_transport,
            "route_priority": "primary_when_enabled",
        }

    def channel_metadata(self) -> dict[str, object]:
        return {
            **self.identity_profile(),
            "send_config_status": self.session_status,
            "service_routes": self.service_routes_json(),
        }

    def scope_json(self) -> dict[str, object]:
        return {
            "channel_account_id": f"channel-{self.binding_id}",
            "preferred_delivery_channel": self.delivery_channel,
            "preferred_transport": self.delivery_transport,
            "scopes": ["whatsapp.send"],
            "service_routes": self.service_routes_json(),
            "source": "operator_seed",
            "tenant_id": self.tenant_id,
        }

    def auth_metadata_json(self) -> dict[str, object]:
        metadata: dict[str, object] = {
            "browser_profile_ref": self.browser_profile_ref,
            "auth_header_name": self.auth_header_name,
            "auth_header_prefix": self.auth_header_prefix,
            "credential_status": self.session_status,
            "delivery_channel": self.delivery_channel,
            "delivery_transport": self.delivery_transport,
            "phone_number": self.phone_number,
            "phone_number_digits": self.phone_number_digits,
            "provider": "whatsapp_web",
            "session_api_base_url": self.session_api_base_url,
            "session_api_token": self.session_api_token,
            "session_label": self.session_label,
            "session_ref": self.session_ref,
            "session_send_url_template": self.session_send_url_template,
            "session_status_url_template": self.session_status_url_template,
            "session_store_ref": self.session_store_ref,
            "status": self.session_status,
        }
        return {key: value for key, value in metadata.items() if value != ""}

    def sanitized_summary(self) -> dict[str, object]:
        return {
            "tenant_id": self.tenant_id,
            "principal_id": self.principal_id,
            "email": self.email,
            "channel": self.delivery_channel,
            "transport": self.delivery_transport,
            "phone_number": self.phone_number,
            "binding_id": self.binding_id,
            "connector_name": self.connector_name,
            "connector_status": self.connector_status,
            "session_status": self.session_status,
            "session_ref_present": bool(self.session_ref),
            "session_store_ref_present": bool(self.session_store_ref),
            "browser_profile_ref_present": bool(self.browser_profile_ref),
            "session_endpoint_present": bool(self.session_send_url_template or self.session_api_base_url),
            "session_status_endpoint_present": bool(self.session_status_url_template or self.session_api_base_url),
            "session_api_token_present": bool(self.session_api_token),
        }


def build_seed(args: argparse.Namespace) -> WhatsAppWebSessionSeed:
    session_ref = str(args.session_ref or "").strip()
    session_store_ref = str(args.session_store_ref or "").strip()
    browser_profile_ref = str(args.browser_profile_ref or "").strip()
    session_send_url_template = str(args.session_send_url_template or "").strip()
    session_status_url_template = str(getattr(args, "session_status_url_template", "") or "").strip()
    session_api_base_url = str(args.session_api_base_url or "").strip()
    connector_status = str(args.connector_status or DEFAULT_CONNECTOR_STATUS).strip() or DEFAULT_CONNECTOR_STATUS
    if session_ref and not (session_store_ref or browser_profile_ref):
        raise ValueError("whatsapp_web_session_store_or_browser_profile_ref_required_when_session_ref_is_set")
    if connector_status.lower() == "enabled":
        if not session_ref:
            raise ValueError("whatsapp_web_session_ref_required_when_enabled")
        if not (session_store_ref or browser_profile_ref):
            raise ValueError("whatsapp_web_session_store_or_browser_profile_ref_required_when_enabled")
        if not (session_send_url_template or session_api_base_url):
            raise ValueError("whatsapp_web_session_send_endpoint_required_when_enabled")
    return WhatsAppWebSessionSeed(
        tenant_id=str(args.tenant_id or DEFAULT_TENANT_ID).strip(),
        tenant_name=str(args.tenant_name or DEFAULT_TENANT_NAME).strip(),
        tenant_slug=str(args.tenant_slug or DEFAULT_TENANT_SLUG).strip(),
        principal_id=str(args.principal_id or DEFAULT_PRINCIPAL_ID).strip(),
        display_name=str(args.display_name or DEFAULT_DISPLAY_NAME).strip(),
        email=str(args.email or DEFAULT_EMAIL).strip(),
        phone_number=normalized_phone(str(args.phone_number or DEFAULT_PHONE_NUMBER)),
        session_label=str(args.session_label or DEFAULT_SESSION_LABEL).strip(),
        binding_id=str(args.binding_id or DEFAULT_BINDING_ID).strip(),
        session_ref=session_ref,
        session_store_ref=session_store_ref,
        browser_profile_ref=browser_profile_ref,
        session_send_url_template=session_send_url_template,
        session_status_url_template=session_status_url_template,
        session_api_base_url=session_api_base_url,
        session_api_token=str(args.session_api_token or "").strip(),
        auth_header_name=str(args.auth_header_name or "").strip(),
        auth_header_prefix=str(args.auth_header_prefix or "").strip(),
        connector_status=connector_status,
    )


def seed_postgres(database_url: str, seed: WhatsAppWebSessionSeed) -> None:
    try:
        import psycopg
        from psycopg.types.json import Json
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError("psycopg is required to seed EA postgres") from exc

    if not str(database_url or "").strip():
        raise ValueError("database_url_required")

    identity_account_id = f"identity-{seed.binding_id}"
    channel_account_id = f"channel-{seed.binding_id}"
    now_sql = "now()"

    with psycopg.connect(database_url, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO tenants (tenant_id, tenant_name, tenant_slug, created_at, updated_at)
                VALUES (%s, %s, %s, {now_sql}, {now_sql})
                ON CONFLICT (tenant_id) DO UPDATE
                SET tenant_name = EXCLUDED.tenant_name,
                    tenant_slug = EXCLUDED.tenant_slug,
                    updated_at = {now_sql}
                """,
                (seed.tenant_id, seed.tenant_name, seed.tenant_slug),
            )
            cur.execute(
                f"""
                INSERT INTO principals (principal_id, tenant_id, display_name, email, principal_type, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 'operator', {now_sql}, {now_sql})
                ON CONFLICT (principal_id) DO UPDATE
                SET tenant_id = EXCLUDED.tenant_id,
                    display_name = EXCLUDED.display_name,
                    email = EXCLUDED.email,
                    principal_type = EXCLUDED.principal_type,
                    updated_at = {now_sql}
                """,
                (seed.principal_id, seed.tenant_id, seed.display_name, seed.email),
            )
            cur.execute(
                f"""
                INSERT INTO identity_accounts (
                    identity_account_id, principal_id, provider_key, external_subject,
                    external_username, profile_json, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, {now_sql}, {now_sql})
                ON CONFLICT (provider_key, external_subject) DO UPDATE
                SET principal_id = EXCLUDED.principal_id,
                    external_username = EXCLUDED.external_username,
                    profile_json = EXCLUDED.profile_json,
                    updated_at = {now_sql}
                """,
                (
                    identity_account_id,
                    seed.principal_id,
                    seed.connector_name,
                    seed.phone_number,
                    seed.phone_number,
                    Json(seed.identity_profile()),
                ),
            )
            cur.execute(
                f"""
                INSERT INTO channel_accounts (
                    channel_account_id, tenant_id, principal_id, channel, identity_account_id,
                    external_ref, status, metadata_json, created_at, updated_at
                )
                VALUES (%s, %s, %s, 'whatsapp', %s, %s, 'staged', %s, {now_sql}, {now_sql})
                ON CONFLICT (principal_id, channel, external_ref) DO UPDATE
                SET tenant_id = EXCLUDED.tenant_id,
                    identity_account_id = EXCLUDED.identity_account_id,
                    status = EXCLUDED.status,
                    metadata_json = EXCLUDED.metadata_json,
                    updated_at = {now_sql}
                """,
                (
                    channel_account_id,
                    seed.tenant_id,
                    seed.principal_id,
                    identity_account_id,
                    seed.phone_number,
                    Json(seed.channel_metadata()),
                ),
            )
            cur.execute(
                f"""
                INSERT INTO connector_bindings (
                    binding_id, principal_id, connector_name, external_account_ref,
                    scope_json, auth_metadata_json, status, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, {now_sql}, {now_sql})
                ON CONFLICT (binding_id) DO UPDATE
                SET principal_id = EXCLUDED.principal_id,
                    connector_name = EXCLUDED.connector_name,
                    external_account_ref = EXCLUDED.external_account_ref,
                    scope_json = EXCLUDED.scope_json,
                    auth_metadata_json = EXCLUDED.auth_metadata_json,
                    status = EXCLUDED.status,
                    updated_at = {now_sql}
                """,
                (
                    seed.binding_id,
                    seed.principal_id,
                    seed.connector_name,
                    seed.phone_number,
                    Json(seed.scope_json()),
                    Json(seed.auth_metadata_json()),
                    seed.connector_status,
                ),
            )
        conn.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed an EA-owned WhatsApp Web session binding.")
    parser.add_argument("--database-url", default=_env("DATABASE_URL"))
    parser.add_argument("--tenant-id", default=_env("EA_WHATSAPP_WEB_DEFAULT_TENANT_ID") or _env("EA_WHATSAPP_DEFAULT_TENANT_ID", DEFAULT_TENANT_ID))
    parser.add_argument("--tenant-name", default=_env("EA_WHATSAPP_WEB_DEFAULT_TENANT_NAME") or _env("EA_WHATSAPP_DEFAULT_TENANT_NAME", DEFAULT_TENANT_NAME))
    parser.add_argument("--tenant-slug", default=_env("EA_WHATSAPP_WEB_DEFAULT_TENANT_SLUG") or _env("EA_WHATSAPP_DEFAULT_TENANT_SLUG", DEFAULT_TENANT_SLUG))
    parser.add_argument("--principal-id", default=_env("EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID") or _env("EA_WHATSAPP_DEFAULT_PRINCIPAL_ID", DEFAULT_PRINCIPAL_ID))
    parser.add_argument("--display-name", default=_env("EA_WHATSAPP_WEB_DEFAULT_DISPLAY_NAME") or _env("EA_WHATSAPP_DEFAULT_DISPLAY_NAME", DEFAULT_DISPLAY_NAME))
    parser.add_argument("--email", default=_env("EA_WHATSAPP_WEB_DEFAULT_EMAIL") or _env("EA_WHATSAPP_DEFAULT_EMAIL", DEFAULT_EMAIL))
    parser.add_argument("--phone-number", default=_env("EA_WHATSAPP_WEB_DEFAULT_PHONE_NUMBER") or _env("EA_WHATSAPP_DEFAULT_BUSINESS_PHONE_NUMBER", DEFAULT_PHONE_NUMBER))
    parser.add_argument("--session-label", default=_env("EA_WHATSAPP_WEB_DEFAULT_SESSION_LABEL", DEFAULT_SESSION_LABEL))
    parser.add_argument("--binding-id", default=_env("EA_WHATSAPP_WEB_DEFAULT_BINDING_ID", DEFAULT_BINDING_ID))
    parser.add_argument("--session-ref", default=_env("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF"))
    parser.add_argument("--session-store-ref", default=_env("EA_WHATSAPP_WEB_DEFAULT_SESSION_STORE_REF"))
    parser.add_argument("--browser-profile-ref", default=_env("EA_WHATSAPP_WEB_DEFAULT_BROWSER_PROFILE_REF"))
    parser.add_argument("--session-send-url-template", default=_env("EA_WHATSAPP_WEB_SESSION_SEND_URL_TEMPLATE"))
    parser.add_argument("--session-status-url-template", default=_env("EA_WHATSAPP_WEB_SESSION_STATUS_URL_TEMPLATE"))
    parser.add_argument("--session-api-base-url", default=_env("EA_WHATSAPP_WEB_SESSION_API_BASE_URL"))
    parser.add_argument("--session-api-token", default=_env("EA_WHATSAPP_WEB_SESSION_API_TOKEN"))
    parser.add_argument("--auth-header-name", default=_env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_NAME"))
    parser.add_argument("--auth-header-prefix", default=_env("EA_WHATSAPP_WEB_SESSION_AUTH_HEADER_PREFIX"))
    parser.add_argument("--connector-status", default=_env("EA_WHATSAPP_WEB_DEFAULT_CONNECTOR_STATUS", DEFAULT_CONNECTOR_STATUS))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _safe_error_reason(exc: Exception) -> str:
    text = str(exc or "").strip()
    return (text.split(":", 1)[0] if text else type(exc).__name__).strip()


def _failure_summary(args: argparse.Namespace | None, exc: Exception) -> dict[str, object]:
    return {
        "binding_id": str(getattr(args, "binding_id", "") or "").strip(),
        "connector_name": WHATSAPP_WEB_SESSION_CONNECTOR,
        "connector_status": str(getattr(args, "connector_status", "") or "").strip(),
        "principal_id": str(getattr(args, "principal_id", "") or "").strip(),
        "reason": _safe_error_reason(exc),
        "seeded": False,
        "transport": WHATSAPP_WEB_SESSION_CONNECTOR,
    }


def main() -> int:
    args: argparse.Namespace | None = None
    try:
        args = parse_args()
        seed = build_seed(args)
        if not args.dry_run:
            seed_postgres(str(args.database_url or "").strip(), seed)
        print(json.dumps(seed.sanitized_summary(), sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps(_failure_summary(args, exc), sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
