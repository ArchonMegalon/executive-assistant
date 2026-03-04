from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.connectors.registry import test_connector_endpoint
from app.db import get_db

ONBOARDING_STATES = (
    "invited",
    "channel_bound",
    "principal_ready",
    "oauth_partial",
    "oauth_ready",
    "sources_partial",
    "syncing",
    "dry_run_ready",
    "ready",
)

_ALLOWED_TRANSITIONS = {
    "invited": {"channel_bound", "principal_ready"},
    "channel_bound": {"principal_ready"},
    "principal_ready": {"oauth_partial", "oauth_ready", "sources_partial"},
    "oauth_partial": {"oauth_ready", "sources_partial"},
    "oauth_ready": {"sources_partial", "syncing"},
    "sources_partial": {"syncing", "dry_run_ready"},
    "syncing": {"dry_run_ready"},
    "dry_run_ready": {"ready"},
    "ready": set(),
}


@dataclass(frozen=True)
class InviteCreated:
    invite_id: int
    token: str
    expires_at: datetime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class OnboardingService:
    def __init__(self) -> None:
        self.db = get_db()

    def _audit(
        self,
        *,
        tenant_key: str,
        session_id: int | None,
        principal_id: int | None,
        event_type: str,
        event_status: str,
        correlation_id: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO onboarding_audit_events
                (tenant_key, session_id, principal_id, event_type, event_status, correlation_id, redacted_payload_json)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                tenant_key,
                session_id,
                principal_id,
                event_type,
                event_status,
                correlation_id,
                __import__("json").dumps(payload or {}, ensure_ascii=False),
            ),
        )

    def create_invite(self, *, tenant_key: str, created_by: str, ttl_hours: int = 24) -> InviteCreated:
        token = secrets.token_urlsafe(24)
        expires_at = _utcnow() + timedelta(hours=max(1, ttl_hours))
        row = self.db.fetchone(
            """
            INSERT INTO tenant_invites (tenant_key, invite_token_hash, invite_status, expires_at, created_by)
            VALUES (%s, %s, 'invited', %s, %s)
            RETURNING invite_id
            """,
            (tenant_key, _token_hash(token), expires_at, created_by),
        )
        invite_id = int(row["invite_id"])
        self._audit(
            tenant_key=tenant_key,
            session_id=None,
            principal_id=None,
            event_type="invite_created",
            event_status="ok",
            correlation_id=f"onb-invite-{invite_id}",
            payload={"created_by": created_by},
        )
        return InviteCreated(invite_id=invite_id, token=token, expires_at=expires_at)

    def start_session_from_invite(self, *, invite_token: str) -> int:
        invite = self.db.fetchone(
            """
            SELECT invite_id, tenant_key, invite_status, expires_at
            FROM tenant_invites
            WHERE invite_token_hash = %s
            """,
            (_token_hash(invite_token),),
        )
        if not invite:
            raise ValueError("invite_not_found")
        if str(invite["invite_status"]) != "invited":
            raise ValueError("invite_not_available")
        if invite["expires_at"] and invite["expires_at"] < _utcnow():
            raise ValueError("invite_expired")
        row = self.db.fetchone(
            """
            INSERT INTO onboarding_sessions (tenant_key, invite_id, status, current_step, metadata_json)
            VALUES (%s, %s, 'invited', 'start', '{}'::jsonb)
            RETURNING session_id
            """,
            (invite["tenant_key"], invite["invite_id"]),
        )
        session_id = int(row["session_id"])
        self._audit(
            tenant_key=str(invite["tenant_key"]),
            session_id=session_id,
            principal_id=None,
            event_type="session_started",
            event_status="ok",
            correlation_id=f"onb-session-{session_id}",
        )
        return session_id

    def _transition(self, *, session_id: int, next_state: str) -> dict[str, Any]:
        if next_state not in ONBOARDING_STATES:
            raise ValueError(f"invalid_state:{next_state}")
        row = self.db.fetchone(
            "SELECT session_id, tenant_key, status, principal_id FROM onboarding_sessions WHERE session_id = %s",
            (session_id,),
        )
        if not row:
            raise ValueError("session_not_found")
        current = str(row["status"])
        if next_state not in _ALLOWED_TRANSITIONS.get(current, set()) and next_state != current:
            raise ValueError(f"invalid_transition:{current}->{next_state}")
        self.db.execute(
            "UPDATE onboarding_sessions SET status = %s, updated_at = NOW() WHERE session_id = %s",
            (next_state, session_id),
        )
        self._audit(
            tenant_key=str(row["tenant_key"]),
            session_id=session_id,
            principal_id=row.get("principal_id"),
            event_type="state_transition",
            event_status="ok",
            correlation_id=f"onb-session-{session_id}",
            payload={"from": current, "to": next_state},
        )
        row["status"] = next_state
        return row

    def _upsert_channel_binding(
        self,
        *,
        tenant_key: str,
        principal_id: int,
        channel_type: str,
        channel_user_id: str,
        chat_id: str,
    ) -> int:
        quiet_hours_json = '{"start":"22:00","end":"07:00"}'
        for _ in range(3):
            binding = self.db.fetchone(
                """
                SELECT binding_id
                FROM channel_bindings
                WHERE channel_type = %s
                  AND (channel_user_id = %s OR chat_id = %s)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (channel_type, channel_user_id, chat_id),
            )
            if binding and binding.get("binding_id"):
                binding_id = int(binding["binding_id"])
                self.db.execute(
                    """
                    DELETE FROM channel_bindings
                    WHERE channel_type = %s
                      AND (channel_user_id = %s OR chat_id = %s)
                      AND binding_id <> %s
                    """,
                    (channel_type, channel_user_id, chat_id, binding_id),
                )
                try:
                    self.db.execute(
                        """
                        UPDATE channel_bindings
                        SET tenant_key = %s,
                            principal_id = %s,
                            channel_user_id = %s,
                            chat_id = %s,
                            quiet_hours_json = %s::jsonb,
                            is_primary = TRUE
                        WHERE binding_id = %s
                        """,
                        (
                            tenant_key,
                            principal_id,
                            channel_user_id,
                            chat_id,
                            quiet_hours_json,
                            binding_id,
                        ),
                    )
                    return binding_id
                except Exception:
                    continue

            inserted = self.db.fetchone(
                """
                INSERT INTO channel_bindings (tenant_key, principal_id, channel_type, channel_user_id, chat_id, quiet_hours_json, is_primary)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, TRUE)
                ON CONFLICT DO NOTHING
                RETURNING binding_id
                """,
                (tenant_key, principal_id, channel_type, channel_user_id, chat_id, quiet_hours_json),
            )
            if inserted and inserted.get("binding_id"):
                return int(inserted["binding_id"])

        fallback = self.db.fetchone(
            """
            SELECT binding_id
            FROM channel_bindings
            WHERE channel_type = %s
              AND (channel_user_id = %s OR chat_id = %s)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (channel_type, channel_user_id, chat_id),
        )
        if fallback and fallback.get("binding_id"):
            binding_id = int(fallback["binding_id"])
            self.db.execute(
                """
                UPDATE channel_bindings
                SET tenant_key = %s,
                    principal_id = %s,
                    channel_user_id = %s,
                    chat_id = %s,
                    quiet_hours_json = %s::jsonb,
                    is_primary = TRUE
                WHERE binding_id = %s
                """,
                (
                    tenant_key,
                    principal_id,
                    channel_user_id,
                    chat_id,
                    quiet_hours_json,
                    binding_id,
                ),
            )
            return binding_id
        raise RuntimeError("channel_binding_upsert_failed")

    def bind_channel(
        self,
        *,
        session_id: int,
        channel_type: str,
        channel_user_id: str,
        chat_id: str,
        display_name: str,
        locale: str,
        timezone_name: str,
    ) -> dict[str, Any]:
        row = self.db.fetchone(
            "SELECT tenant_key FROM onboarding_sessions WHERE session_id = %s",
            (session_id,),
        )
        if not row:
            raise ValueError("session_not_found")
        tenant_key = str(row["tenant_key"])
        principal = self.db.fetchone(
            """
            INSERT INTO principals (tenant_key, external_user_id, display_name, locale, timezone)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_key, external_user_id)
            DO UPDATE SET display_name = EXCLUDED.display_name, locale = EXCLUDED.locale, timezone = EXCLUDED.timezone, updated_at = NOW()
            RETURNING principal_id
            """,
            (tenant_key, channel_user_id, display_name, locale, timezone_name),
        )
        principal_id = int(principal["principal_id"])
        binding_id = self._upsert_channel_binding(
            tenant_key=tenant_key,
            principal_id=principal_id,
            channel_type=channel_type,
            channel_user_id=channel_user_id,
            chat_id=chat_id,
        )
        self.db.execute(
            """
            UPDATE onboarding_sessions
            SET principal_id = %s, channel_binding_id = %s, locale = %s, timezone = %s, updated_at = NOW()
            WHERE session_id = %s
            """,
            (principal_id, binding_id, locale, timezone_name, session_id),
        )
        self._transition(session_id=session_id, next_state="channel_bound")
        return self._transition(session_id=session_id, next_state="principal_ready")

    def set_google_oauth_scopes(
        self,
        *,
        session_id: int,
        provider: str,
        scopes: list[str],
        oauth_status: str,
        secret_ref: str,
    ) -> dict[str, Any]:
        row = self.db.fetchone(
            "SELECT tenant_key, principal_id FROM onboarding_sessions WHERE session_id = %s",
            (session_id,),
        )
        if not row:
            raise ValueError("session_not_found")
        principal_id = row.get("principal_id")
        if not principal_id:
            raise ValueError("principal_not_ready")
        self.db.execute(
            """
            INSERT INTO oauth_connections (tenant_key, principal_id, provider, scope_inventory, oauth_status, secret_ref)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_key, principal_id, provider)
            DO UPDATE SET scope_inventory = EXCLUDED.scope_inventory, oauth_status = EXCLUDED.oauth_status, secret_ref = EXCLUDED.secret_ref, updated_at = NOW()
            """,
            (row["tenant_key"], principal_id, provider, scopes, oauth_status, secret_ref),
        )
        target = "oauth_ready" if oauth_status == "oauth_ready" else "oauth_partial"
        return self._transition(session_id=session_id, next_state=target)

    def add_source_connection(
        self,
        *,
        session_id: int,
        connector_type: str,
        connector_name: str,
        endpoint_url: str,
        network_mode: str,
        allow_private_targets: bool = False,
    ) -> dict[str, Any]:
        row = self.db.fetchone(
            "SELECT tenant_key, principal_id FROM onboarding_sessions WHERE session_id = %s",
            (session_id,),
        )
        if not row:
            raise ValueError("session_not_found")
        principal_id = row.get("principal_id")
        if not principal_id:
            raise ValueError("principal_not_ready")

        decision = test_connector_endpoint(
            connector_type=connector_type,
            endpoint_url=endpoint_url,
            network_mode=network_mode,
            allow_private_targets=allow_private_targets,
            allow_metadata_targets=False,
        )
        src = self.db.fetchone(
            """
            INSERT INTO source_connections
                (tenant_key, principal_id, connector_type, connector_name, connector_status, network_mode, endpoint_url, capability_flags)
            VALUES
                (%s, %s, %s, %s, 'sources_partial', %s, %s, %s::jsonb)
            RETURNING source_connection_id
            """,
            (
                row["tenant_key"],
                principal_id,
                connector_type,
                connector_name,
                network_mode,
                endpoint_url,
                __import__("json").dumps({"decision": decision["reason"]}),
            ),
        )
        self.db.execute(
            """
            INSERT INTO source_test_runs (source_connection_id, tenant_key, result_status, failure_code, redacted_details)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            """,
            (
                src["source_connection_id"],
                row["tenant_key"],
                "ok" if decision["ok"] else "blocked",
                None if decision["ok"] else decision["reason"],
                __import__("json").dumps({"resolved_ips": decision["resolved_ips"]}),
            ),
        )
        if decision["ok"]:
            self._transition(session_id=session_id, next_state="sources_partial")
        return decision

    def mark_syncing(self, *, session_id: int) -> dict[str, Any]:
        return self._transition(session_id=session_id, next_state="syncing")

    def mark_dry_run_ready(self, *, session_id: int) -> dict[str, Any]:
        return self._transition(session_id=session_id, next_state="dry_run_ready")

    def mark_ready(self, *, session_id: int) -> dict[str, Any]:
        row = self._transition(session_id=session_id, next_state="ready")
        self.db.execute(
            "UPDATE onboarding_sessions SET completed_at = NOW() WHERE session_id = %s",
            (session_id,),
        )
        self.db.execute(
            "UPDATE tenant_invites SET invite_status = 'consumed', consumed_at = NOW(), consumed_by_principal_id = %s WHERE invite_id = (SELECT invite_id FROM onboarding_sessions WHERE session_id = %s)",
            (row.get("principal_id"), session_id),
        )
        return row
