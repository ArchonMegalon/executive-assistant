from __future__ import annotations

import logging
from typing import Any

from app.domain.models import ConnectorBinding, OnboardingState
from app.repositories.onboarding_state import InMemoryOnboardingStateRepository, OnboardingStateRepository
from app.repositories.onboarding_state_postgres import PostgresOnboardingStateRepository
from app.services.google_oauth import GOOGLE_PROVIDER_KEY, build_google_oauth_start
from app.services.provider_registry import ProviderRegistryService
from app.services.tool_runtime import ToolRuntimeService
from app.settings import Settings, ensure_storage_fallback_allowed, get_settings

TELEGRAM_IDENTITY_CONNECTOR = "telegram_identity"
TELEGRAM_OFFICIAL_BOT_CONNECTOR = "telegram_official_bot"
WHATSAPP_BUSINESS_CONNECTOR = "whatsapp_business"
WHATSAPP_EXPORT_CONNECTOR = "whatsapp_export"

GOOGLE_ONBOARDING_BUNDLE_ALIASES = {
    "send": "send",
    "verify": "verify",
    "core": "verify",
    "full_workspace": "full_workspace",
}


class OnboardingService:
    def __init__(
        self,
        *,
        onboarding_repo: OnboardingStateRepository,
        provider_registry: ProviderRegistryService,
        tool_runtime: ToolRuntimeService,
        settings: Settings,
    ) -> None:
        self._repo = onboarding_repo
        self._provider_registry = provider_registry
        self._tool_runtime = tool_runtime
        self._settings = settings

    def start_workspace(
        self,
        *,
        principal_id: str,
        workspace_name: str,
        workspace_mode: str,
        region: str,
        language: str,
        timezone: str,
        selected_channels: tuple[str, ...],
    ) -> dict[str, object]:
        normalized_channels = self._normalize_channels(selected_channels)
        state = self._repo.get_for_principal(principal_id)
        channel_preferences = dict(state.channel_preferences_json if state is not None else {})
        for channel in normalized_channels:
            channel_preferences.setdefault(channel, {})
        saved = self._repo.upsert_state(
            principal_id=principal_id,
            onboarding_id=state.onboarding_id if state is not None else None,
            workspace_name=workspace_name,
            workspace_mode=workspace_mode or "personal",
            region=region,
            language=language,
            timezone=timezone,
            selected_channels=normalized_channels,
            channel_preferences_json=channel_preferences,
            privacy_preferences_json=dict(state.privacy_preferences_json if state is not None else {}),
            brief_preview_json={},
            status="started",
        )
        return self.status(principal_id=principal_id, state_override=saved)

    def start_google(
        self,
        *,
        principal_id: str,
        scope_bundle: str,
        redirect_uri_override: str | None = None,
    ) -> dict[str, object]:
        requested_bundle = str(scope_bundle or "core").strip().lower() or "core"
        if requested_bundle not in GOOGLE_ONBOARDING_BUNDLE_ALIASES:
            raise RuntimeError("onboarding_google_scope_bundle_invalid")
        state = self._ensure_state(principal_id)
        google_pref = dict((state.channel_preferences_json or {}).get("google") or {})
        google_pref["requested_bundle"] = requested_bundle
        if requested_bundle == "full_workspace":
            google_pref["status"] = "planned_not_available"
            google_pref["next_step"] = "Use Google Core for the current EA slice; full workspace remains planned."
            updated = self._replace_channel_pref(state, "google", google_pref, status="in_progress")
            payload = self.status(principal_id=principal_id, state_override=updated)
            payload["google_start"] = {
                "ready": False,
                "requested_bundle": requested_bundle,
                "fallback_bundle": "core",
                "auth_url": "",
                "requested_scopes": [],
                "detail": google_pref["next_step"],
            }
            return payload
        oauth_bundle = GOOGLE_ONBOARDING_BUNDLE_ALIASES[requested_bundle]
        google_pref["oauth_bundle"] = oauth_bundle
        try:
            packet = build_google_oauth_start(
                principal_id=principal_id,
                scope_bundle=oauth_bundle,
                redirect_uri_override=redirect_uri_override,
            )
            google_pref["status"] = "ready_to_connect"
            google_pref["requested_scopes"] = list(packet.requested_scopes)
            google_pref["auth_url"] = packet.auth_url
            google_pref["next_step"] = "Complete Google consent to link Gmail and core workspace context."
            updated = self._replace_channel_pref(state, "google", google_pref, status="in_progress")
            payload = self.status(principal_id=principal_id, state_override=updated)
            payload["google_start"] = {
                "ready": True,
                "requested_bundle": requested_bundle,
                "oauth_bundle": oauth_bundle,
                "auth_url": packet.auth_url,
                "requested_scopes": list(packet.requested_scopes),
            }
            return payload
        except RuntimeError as exc:
            google_pref["status"] = "credentials_missing"
            google_pref["next_step"] = str(exc)
            updated = self._replace_channel_pref(state, "google", google_pref, status="in_progress")
            payload = self.status(principal_id=principal_id, state_override=updated)
            payload["google_start"] = {
                "ready": False,
                "requested_bundle": requested_bundle,
                "auth_url": "",
                "requested_scopes": [],
                "detail": str(exc),
            }
            return payload

    def start_telegram(
        self,
        *,
        principal_id: str,
        telegram_ref: str,
        identity_mode: str,
        history_mode: str,
        assistant_surfaces: tuple[str, ...],
    ) -> dict[str, object]:
        external_ref = str(telegram_ref or "").strip() or principal_id
        surfaces = tuple(sorted({str(v).strip().lower() for v in assistant_surfaces if str(v).strip()}))
        binding = self._tool_runtime.upsert_connector_binding(
            principal_id=principal_id,
            connector_name=TELEGRAM_IDENTITY_CONNECTOR,
            external_account_ref=external_ref,
            scope_json={"assistant_surfaces": list(surfaces)},
            auth_metadata_json={
                "identity_mode": str(identity_mode or "login_widget").strip() or "login_widget",
                "history_mode": str(history_mode or "future_only").strip() or "future_only",
                "status": "guided_manual",
            },
            status="guided",
        )
        state = self._ensure_state(principal_id)
        telegram_pref = dict((state.channel_preferences_json or {}).get("telegram") or {})
        telegram_pref.update(
            {
                "telegram_ref": external_ref,
                "identity_mode": str(identity_mode or "login_widget").strip() or "login_widget",
                "history_mode": str(history_mode or "future_only").strip() or "future_only",
                "assistant_surfaces": list(surfaces),
                "binding_id": binding.binding_id,
                "status": "guided_manual",
                "next_step": "Link the official bot or stay future-only until a Telegram auth/import adapter lands.",
            }
        )
        updated = self._replace_channel_pref(state, "telegram", telegram_pref, status="in_progress")
        payload = self.status(principal_id=principal_id, state_override=updated)
        payload["telegram_start"] = {
            "binding_id": binding.binding_id,
            "status": "guided_manual",
            "detail": telegram_pref["next_step"],
        }
        return payload

    def link_telegram_bot(
        self,
        *,
        principal_id: str,
        bot_handle: str,
        install_surfaces: tuple[str, ...],
        default_chat_ref: str,
    ) -> dict[str, object]:
        external_ref = str(bot_handle or "").strip() or principal_id
        surfaces = tuple(sorted({str(v).strip().lower() for v in install_surfaces if str(v).strip()}))
        binding = self._tool_runtime.upsert_connector_binding(
            principal_id=principal_id,
            connector_name=TELEGRAM_OFFICIAL_BOT_CONNECTOR,
            external_account_ref=external_ref,
            scope_json={"install_surfaces": list(surfaces)},
            auth_metadata_json={
                "default_chat_ref": str(default_chat_ref or "").strip(),
                "status": "bot_link_requested",
            },
            status="planned",
        )
        state = self._ensure_state(principal_id)
        telegram_pref = dict((state.channel_preferences_json or {}).get("telegram") or {})
        telegram_pref.update(
            {
                "bot_handle": external_ref,
                "bot_binding_id": binding.binding_id,
                "install_surfaces": list(surfaces),
                "default_chat_ref": str(default_chat_ref or "").strip(),
                "status": "bot_link_requested",
                "next_step": "Complete official bot installation; history import remains a separate explicit future step.",
            }
        )
        updated = self._replace_channel_pref(state, "telegram", telegram_pref, status="in_progress")
        payload = self.status(principal_id=principal_id, state_override=updated)
        payload["telegram_bot"] = {
            "binding_id": binding.binding_id,
            "status": "bot_link_requested",
        }
        return payload

    def start_whatsapp_business(
        self,
        *,
        principal_id: str,
        phone_number: str,
        business_name: str,
        import_history_now: bool,
    ) -> dict[str, object]:
        external_ref = str(phone_number or "").strip() or principal_id
        binding = self._tool_runtime.upsert_connector_binding(
            principal_id=principal_id,
            connector_name=WHATSAPP_BUSINESS_CONNECTOR,
            external_account_ref=external_ref,
            scope_json={"import_history_now": bool(import_history_now)},
            auth_metadata_json={
                "business_name": str(business_name or "").strip(),
                "status": "planned_business",
            },
            status="planned",
        )
        state = self._ensure_state(principal_id)
        whatsapp_pref = dict((state.channel_preferences_json or {}).get("whatsapp") or {})
        whatsapp_pref.update(
            {
                "mode": "business",
                "phone_number": external_ref,
                "business_name": str(business_name or "").strip(),
                "import_history_now": bool(import_history_now),
                "binding_id": binding.binding_id,
                "status": "planned_business",
                "next_step": "Use Business onboarding when the adapter lands, and trigger history sync inside the allowed onboarding window.",
            }
        )
        updated = self._replace_channel_pref(state, "whatsapp", whatsapp_pref, status="in_progress")
        payload = self.status(principal_id=principal_id, state_override=updated)
        payload["whatsapp_business"] = {
            "binding_id": binding.binding_id,
            "status": "planned_business",
        }
        return payload

    def import_whatsapp_export(
        self,
        *,
        principal_id: str,
        export_label: str,
        selected_chat_labels: tuple[str, ...],
        include_media: bool,
    ) -> dict[str, object]:
        external_ref = str(export_label or "").strip() or principal_id
        chats = tuple(str(v).strip() for v in selected_chat_labels if str(v).strip())
        binding = self._tool_runtime.upsert_connector_binding(
            principal_id=principal_id,
            connector_name=WHATSAPP_EXPORT_CONNECTOR,
            external_account_ref=external_ref,
            scope_json={"selected_chat_labels": list(chats), "include_media": bool(include_media)},
            auth_metadata_json={"status": "export_planned"},
            status="planned",
        )
        state = self._ensure_state(principal_id)
        whatsapp_pref = dict((state.channel_preferences_json or {}).get("whatsapp") or {})
        whatsapp_pref.update(
            {
                "mode": "export",
                "export_label": external_ref,
                "selected_chat_labels": list(chats),
                "include_media": bool(include_media),
                "binding_id": binding.binding_id,
                "status": "export_planned",
                "next_step": "Upload the exported chats explicitly; generic automatic WhatsApp history import is not promised here.",
            }
        )
        updated = self._replace_channel_pref(state, "whatsapp", whatsapp_pref, status="in_progress")
        payload = self.status(principal_id=principal_id, state_override=updated)
        payload["whatsapp_export"] = {
            "binding_id": binding.binding_id,
            "status": "export_planned",
        }
        return payload

    def finalize(
        self,
        *,
        principal_id: str,
        retention_mode: str,
        metadata_only_channels: tuple[str, ...],
        allow_drafts: bool,
        allow_action_suggestions: bool,
        allow_auto_briefs: bool,
    ) -> dict[str, object]:
        state = self._ensure_state(principal_id)
        privacy = {
            "retention_mode": str(retention_mode or "full_bodies").strip() or "full_bodies",
            "metadata_only_channels": list(self._normalize_channels(metadata_only_channels)),
            "allow_drafts": bool(allow_drafts),
            "allow_action_suggestions": bool(allow_action_suggestions),
            "allow_auto_briefs": bool(allow_auto_briefs),
        }
        preview = self._build_brief_preview(state=state, privacy=privacy)
        saved = self._repo.upsert_state(
            principal_id=principal_id,
            onboarding_id=state.onboarding_id,
            workspace_name=state.workspace_name,
            workspace_mode=state.workspace_mode,
            region=state.region,
            language=state.language,
            timezone=state.timezone,
            selected_channels=state.selected_channels,
            privacy_preferences_json=privacy,
            channel_preferences_json=dict(state.channel_preferences_json),
            brief_preview_json=preview,
            status="ready_for_brief",
        )
        return self.status(principal_id=principal_id, state_override=saved)

    def status(self, *, principal_id: str, state_override: OnboardingState | None = None) -> dict[str, object]:
        state = state_override or self._repo.get_for_principal(principal_id)
        google_binding = self._provider_registry.get_persisted_binding_record(
            binding_id=f"{principal_id}:{GOOGLE_PROVIDER_KEY}",
            principal_id=principal_id,
        )
        google_state = self._provider_registry.binding_state(GOOGLE_PROVIDER_KEY, principal_id=principal_id)
        connectors = self._tool_runtime.list_connector_bindings(principal_id=principal_id, limit=100)
        channel_statuses = self._channel_statuses(
            principal_id=principal_id,
            state=state,
            google_binding=google_binding,
            google_state=google_state,
            connectors=connectors,
        )
        preview = dict(state.brief_preview_json) if state is not None and state.brief_preview_json else self._build_brief_preview(
            state=state,
            privacy=dict(state.privacy_preferences_json) if state is not None else {},
        )
        next_step = self._next_step(state=state, channel_statuses=channel_statuses)
        return {
            "principal_id": principal_id,
            "status": state.status if state is not None else "draft",
            "workspace": {
                "name": state.workspace_name if state is not None else "",
                "mode": state.workspace_mode if state is not None else "personal",
                "region": state.region if state is not None else "",
                "language": state.language if state is not None else "",
                "timezone": state.timezone if state is not None else "",
            },
            "selected_channels": list(state.selected_channels if state is not None else ()),
            "privacy": dict(state.privacy_preferences_json) if state is not None else {},
            "channels": channel_statuses,
            "brief_preview": preview,
            "next_step": next_step,
            "onboarding_id": state.onboarding_id if state is not None else "",
        }

    def _ensure_state(self, principal_id: str) -> OnboardingState:
        existing = self._repo.get_for_principal(principal_id)
        if existing is not None:
            return existing
        return self._repo.upsert_state(principal_id=principal_id, status="draft")

    def _replace_channel_pref(
        self,
        state: OnboardingState,
        channel: str,
        value: dict[str, object],
        *,
        status: str,
    ) -> OnboardingState:
        prefs = dict(state.channel_preferences_json or {})
        prefs[str(channel or "").strip().lower()] = dict(value or {})
        selected = set(state.selected_channels)
        selected.add(str(channel or "").strip().lower())
        return self._repo.upsert_state(
            principal_id=state.principal_id,
            onboarding_id=state.onboarding_id,
            workspace_name=state.workspace_name,
            workspace_mode=state.workspace_mode,
            region=state.region,
            language=state.language,
            timezone=state.timezone,
            selected_channels=tuple(sorted(selected)),
            privacy_preferences_json=dict(state.privacy_preferences_json),
            channel_preferences_json=prefs,
            brief_preview_json=dict(state.brief_preview_json),
            status=status,
        )

    def _channel_statuses(
        self,
        *,
        principal_id: str,
        state: OnboardingState | None,
        google_binding,
        google_state,
        connectors: list[ConnectorBinding],
    ) -> dict[str, dict[str, object]]:
        channel_prefs = dict(state.channel_preferences_json) if state is not None else {}
        by_name: dict[str, list[ConnectorBinding]] = {}
        for binding in connectors:
            by_name.setdefault(binding.connector_name, []).append(binding)
        google_pref = dict(channel_prefs.get("google") or {})
        google_requested_bundle = str(google_pref.get("requested_bundle") or "").strip().lower() or "core"
        google_status = "not_selected"
        google_detail = "Select Google during onboarding to request assistant email and workspace context."
        granted_scopes = []
        if google_binding is not None:
            google_status = "connected"
            granted_scopes = list(dict(google_binding.auth_metadata_json or {}).get("granted_scopes") or [])
            google_detail = "Google is linked for this principal."
        elif google_requested_bundle == "full_workspace":
            google_status = "planned_not_available"
            google_detail = "Full Workspace stays planned in EA; the current supported fallback is Google Core."
        elif google_state is not None and bool(google_state.secret_configured):
            if google_pref:
                google_status = "ready_to_connect"
                google_detail = "Google Core can be connected through the existing OAuth flow."
            else:
                google_status = "available"
                google_detail = "Google Core is available but not started for this onboarding record yet."
        elif google_state is not None:
            google_status = "credentials_missing"
            google_detail = "Google OAuth credentials are not configured for this EA host yet."
        telegram_pref = dict(channel_prefs.get("telegram") or {})
        telegram_status = str(telegram_pref.get("status") or "").strip() or "not_selected"
        telegram_detail = str(telegram_pref.get("next_step") or "").strip() or (
            "Telegram is a guided manual lane: identity linking and official bot setup are separate from history import."
        )
        if by_name.get(TELEGRAM_OFFICIAL_BOT_CONNECTOR):
            telegram_status = "bot_link_requested"
        elif by_name.get(TELEGRAM_IDENTITY_CONNECTOR):
            telegram_status = telegram_status or "guided_manual"
        whatsapp_pref = dict(channel_prefs.get("whatsapp") or {})
        whatsapp_status = str(whatsapp_pref.get("status") or "").strip() or "not_selected"
        whatsapp_detail = str(whatsapp_pref.get("next_step") or "").strip() or (
            "WhatsApp stays split between supported business onboarding and explicit export import."
        )
        if by_name.get(WHATSAPP_BUSINESS_CONNECTOR):
            whatsapp_status = "planned_business"
        elif by_name.get(WHATSAPP_EXPORT_CONNECTOR):
            whatsapp_status = "export_planned"
        return {
            "google": {
                "status": google_status,
                "requested_bundle": google_requested_bundle,
                "granted_scopes": granted_scopes,
                "detail": google_detail,
            },
            "telegram": {
                "status": telegram_status,
                "detail": telegram_detail,
                "bindings": [binding.binding_id for binding in by_name.get(TELEGRAM_IDENTITY_CONNECTOR, []) + by_name.get(TELEGRAM_OFFICIAL_BOT_CONNECTOR, [])],
            },
            "whatsapp": {
                "status": whatsapp_status,
                "detail": whatsapp_detail,
                "bindings": [binding.binding_id for binding in by_name.get(WHATSAPP_BUSINESS_CONNECTOR, []) + by_name.get(WHATSAPP_EXPORT_CONNECTOR, [])],
            },
        }

    def _build_brief_preview(
        self,
        *,
        state: OnboardingState | None,
        privacy: dict[str, object],
    ) -> dict[str, object]:
        workspace_name = state.workspace_name if state is not None and state.workspace_name else "Assistant"
        selected_channels = list(state.selected_channels if state is not None else ())
        metadata_only_channels = list(privacy.get("metadata_only_channels") or [])
        connected = []
        pending = []
        for channel in selected_channels:
            prefs = dict((state.channel_preferences_json if state is not None else {}).get(channel) or {})
            status = str(prefs.get("status") or "").strip()
            if channel == "google" and status == "ready_to_connect":
                pending.append("Google consent is ready but not completed yet.")
            elif status:
                pending.append(f"{channel.capitalize()} is staged as {status.replace('_', ' ')}.")
            else:
                pending.append(f"{channel.capitalize()} is selected but not configured yet.")
        if not selected_channels:
            pending.append("No channels are selected yet, so the first brief can only describe setup state.")
        return {
            "headline": f"{workspace_name} will wake up with one cross-channel brief instead of three disconnected inboxes.",
            "workspace_mode": state.workspace_mode if state is not None else "personal",
            "who_you_are": [
                f"Workspace: {workspace_name}",
                f"Mode: {(state.workspace_mode if state is not None else 'personal').replace('_', ' ')}",
                f"Timezone: {state.timezone if state is not None and state.timezone else 'unspecified'}",
            ],
            "connected_channels": connected,
            "selected_channels": selected_channels,
            "history_import_state": pending,
            "privacy_posture": {
                "retention_mode": str(privacy.get('retention_mode') or 'full_bodies'),
                "metadata_only_channels": metadata_only_channels,
                "allow_drafts": bool(privacy.get("allow_drafts", False)),
                "allow_action_suggestions": bool(privacy.get("allow_action_suggestions", False)),
                "allow_auto_briefs": bool(privacy.get("allow_auto_briefs", False)),
            },
            "sample_brief": [
                "Who needs a reply first.",
                "What changed since the last brief.",
                "Which threads are waiting on you.",
                "Why the assistant suggested each follow-up.",
            ],
        }

    def _next_step(self, *, state: OnboardingState | None, channel_statuses: dict[str, dict[str, object]]) -> str:
        if state is None or not state.workspace_name:
            return "Start onboarding with a workspace name, mode, and channel selection."
        google_status = str(dict(channel_statuses.get("google") or {}).get("status") or "")
        if "google" in state.selected_channels and google_status in {"available", "ready_to_connect"}:
            return "Complete Google Core consent to unlock the first real connected account."
        if "telegram" in state.selected_channels and str(dict(channel_statuses.get("telegram") or {}).get("status") or "") == "guided_manual":
            return "Decide whether Telegram starts as identity-only, official bot, or future-only memory."
        if "whatsapp" in state.selected_channels and str(dict(channel_statuses.get("whatsapp") or {}).get("status") or "") in {"planned_business", "export_planned", "not_selected"}:
            return "Choose the WhatsApp path: supported business onboarding or explicit export import."
        if not dict(state.privacy_preferences_json):
            return "Finalize privacy and brief preferences so EA can build the first trustworthy brief."
        return "Review the sample brief and start connecting real channels."

    @staticmethod
    def _normalize_channels(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        allowed = {"google", "telegram", "whatsapp"}
        normalized = sorted({str(value or "").strip().lower() for value in values if str(value or "").strip().lower() in allowed})
        return tuple(normalized)


def _backend_mode(settings: Settings) -> str:
    return str(settings.storage.backend or "auto").strip().lower()


def build_onboarding_repo(settings: Settings) -> OnboardingStateRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.onboarding")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "onboarding configured for memory")
        return InMemoryOnboardingStateRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresOnboardingStateRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresOnboardingStateRepository(settings.database_url)
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "onboarding auto fallback", exc)
            log.warning("postgres onboarding backend unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "onboarding auto backend without DATABASE_URL")
    return InMemoryOnboardingStateRepository()


def build_onboarding_service(
    *,
    settings: Settings | None = None,
    provider_registry: ProviderRegistryService,
    tool_runtime: ToolRuntimeService,
) -> OnboardingService:
    resolved = settings or get_settings()
    return OnboardingService(
        onboarding_repo=build_onboarding_repo(resolved),
        provider_registry=provider_registry,
        tool_runtime=tool_runtime,
        settings=resolved,
    )
