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
DEFAULT_BUSINESS_PHONE_NUMBER = "+15555550100"
DEFAULT_BUSINESS_NAME = "Executive Assistant WhatsApp Business"
DEFAULT_BINDING_ID = "ea-whatsapp-business"


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def phone_digits(phone_number: str) -> str:
    return "".join(ch for ch in str(phone_number or "") if ch.isdigit())


def normalized_phone(phone_number: str) -> str:
    raw = str(phone_number or "").strip()
    digits = phone_digits(raw)
    if len(digits) < 7:
        raise ValueError("whatsapp_business_phone_number_invalid")
    return raw if raw.startswith("+") else f"+{digits}"


@dataclass(frozen=True)
class WhatsAppBusinessSeed:
    tenant_id: str
    tenant_name: str
    tenant_slug: str
    principal_id: str
    display_name: str
    email: str
    business_phone_number: str
    business_name: str
    binding_id: str
    access_token: str = ""
    phone_number_id: str = ""

    @property
    def business_phone_number_digits(self) -> str:
        return phone_digits(self.business_phone_number)

    @property
    def credential_status(self) -> str:
        return "meta_configured" if self.access_token and self.phone_number_id else "meta_credentials_missing"

    @property
    def connector_status(self) -> str:
        return "enabled"

    def identity_profile(self) -> dict[str, object]:
        return {
            "business_name": self.business_name,
            "business_phone_number": self.business_phone_number,
            "business_phone_number_digits": self.business_phone_number_digits,
            "source": "operator_seed",
            "tenant_id": self.tenant_id,
        }

    def channel_metadata(self) -> dict[str, object]:
        return {
            **self.identity_profile(),
            "requires": (
                "EA_WHATSAPP_DEFAULT_AUTH_TOKEN and EA_WHATSAPP_DEFAULT_PHONE_NUMBER_ID "
                "or connector auth_metadata access_token and phone_number_id"
            ),
            "send_config_status": self.credential_status,
        }

    def scope_json(self) -> dict[str, object]:
        return {
            "business_phone_number": self.business_phone_number,
            "channel_account_id": f"channel-{self.binding_id}",
            "scopes": ["whatsapp.send"],
            "source": "operator_seed",
            "tenant_id": self.tenant_id,
        }

    def auth_metadata_json(self) -> dict[str, object]:
        metadata: dict[str, object] = {
            "business_name": self.business_name,
            "business_phone_number": self.business_phone_number,
            "business_phone_number_digits": self.business_phone_number_digits,
            "credential_status": self.credential_status,
            "provider": "meta",
            "status": "business_number_stored",
        }
        if self.phone_number_id:
            metadata["phone_number_id"] = self.phone_number_id
        if self.access_token:
            metadata["access_token"] = self.access_token
        return metadata

    def sanitized_summary(self) -> dict[str, object]:
        return {
            "tenant_id": self.tenant_id,
            "principal_id": self.principal_id,
            "email": self.email,
            "channel": "whatsapp",
            "business_phone_number": self.business_phone_number,
            "binding_id": self.binding_id,
            "connector_status": self.connector_status,
            "credential_status": self.credential_status,
            "access_token_present": bool(self.access_token),
            "phone_number_id_present": bool(self.phone_number_id),
        }


def build_seed(args: argparse.Namespace) -> WhatsAppBusinessSeed:
    access_token = str(args.access_token or "").strip()
    phone_number_id = str(args.phone_number_id or "").strip()
    if access_token and not phone_number_id:
        raise ValueError("meta_phone_number_id_required_when_access_token_is_set")
    return WhatsAppBusinessSeed(
        tenant_id=str(args.tenant_id or DEFAULT_TENANT_ID).strip(),
        tenant_name=str(args.tenant_name or DEFAULT_TENANT_NAME).strip(),
        tenant_slug=str(args.tenant_slug or DEFAULT_TENANT_SLUG).strip(),
        principal_id=str(args.principal_id or DEFAULT_PRINCIPAL_ID).strip(),
        display_name=str(args.display_name or DEFAULT_DISPLAY_NAME).strip(),
        email=str(args.email or DEFAULT_EMAIL).strip(),
        business_phone_number=normalized_phone(str(args.business_phone_number or DEFAULT_BUSINESS_PHONE_NUMBER)),
        business_name=str(args.business_name or DEFAULT_BUSINESS_NAME).strip(),
        binding_id=str(args.binding_id or DEFAULT_BINDING_ID).strip(),
        access_token=access_token,
        phone_number_id=phone_number_id,
    )


def seed_postgres(database_url: str, seed: WhatsAppBusinessSeed) -> None:
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
                VALUES (%s, %s, 'whatsapp_business', %s, %s, %s, {now_sql}, {now_sql})
                ON CONFLICT (provider_key, external_subject) DO UPDATE
                SET principal_id = EXCLUDED.principal_id,
                    external_username = EXCLUDED.external_username,
                    profile_json = EXCLUDED.profile_json,
                    updated_at = {now_sql}
                """,
                (
                    identity_account_id,
                    seed.principal_id,
                    seed.business_phone_number,
                    seed.business_phone_number,
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
                    seed.business_phone_number,
                    Json(seed.channel_metadata()),
                ),
            )
            cur.execute(
                f"""
                INSERT INTO connector_bindings (
                    binding_id, principal_id, connector_name, external_account_ref,
                    scope_json, auth_metadata_json, status, created_at, updated_at
                )
                VALUES (%s, %s, 'whatsapp_business', %s, %s, %s, %s, {now_sql}, {now_sql})
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
                    seed.business_phone_number,
                    Json(seed.scope_json()),
                    Json(seed.auth_metadata_json()),
                    seed.connector_status,
                ),
            )
        conn.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed a WhatsApp Business account under an EA tenant/principal.")
    parser.add_argument("--database-url", default=_env("DATABASE_URL"))
    parser.add_argument("--tenant-id", default=_env("EA_WHATSAPP_DEFAULT_TENANT_ID", DEFAULT_TENANT_ID))
    parser.add_argument("--tenant-name", default=_env("EA_WHATSAPP_DEFAULT_TENANT_NAME", DEFAULT_TENANT_NAME))
    parser.add_argument("--tenant-slug", default=_env("EA_WHATSAPP_DEFAULT_TENANT_SLUG", DEFAULT_TENANT_SLUG))
    parser.add_argument("--principal-id", default=_env("EA_WHATSAPP_DEFAULT_PRINCIPAL_ID", DEFAULT_PRINCIPAL_ID))
    parser.add_argument("--display-name", default=_env("EA_WHATSAPP_DEFAULT_DISPLAY_NAME", DEFAULT_DISPLAY_NAME))
    parser.add_argument("--email", default=_env("EA_WHATSAPP_DEFAULT_EMAIL", DEFAULT_EMAIL))
    parser.add_argument(
        "--business-phone-number",
        default=_env("EA_WHATSAPP_DEFAULT_BUSINESS_PHONE_NUMBER", DEFAULT_BUSINESS_PHONE_NUMBER),
    )
    parser.add_argument("--business-name", default=_env("EA_WHATSAPP_DEFAULT_BUSINESS_NAME", DEFAULT_BUSINESS_NAME))
    parser.add_argument("--binding-id", default=_env("EA_WHATSAPP_DEFAULT_BINDING_ID", DEFAULT_BINDING_ID))
    parser.add_argument(
        "--access-token",
        default=_env("EA_WHATSAPP_DEFAULT_AUTH_TOKEN") or _env("EA_HEYY_AUTH_TOKEN") or _env("EA_WHATSAPP_API_TOKEN"),
    )
    parser.add_argument(
        "--phone-number-id",
        default=_env("EA_WHATSAPP_DEFAULT_PHONE_NUMBER_ID") or _env("EA_HEYY_PHONE_NUMBER_ID"),
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    seed = build_seed(args)
    if not args.dry_run:
        seed_postgres(str(args.database_url or "").strip(), seed)
    print(json.dumps(seed.sanitized_summary(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
