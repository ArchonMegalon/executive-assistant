from __future__ import annotations

import os
from typing import Any

import requests


SUPPORTED_PROVIDERS = ("tavus", "did")


def provider_label(provider_key: str) -> str:
    normalized = str(provider_key or "").strip().lower()
    if normalized == "tavus":
        return "Tavus"
    if normalized == "did":
        return "D-ID"
    return ""


def configured_provider() -> tuple[str, bool]:
    provider_key = str(os.getenv("EA_MEMORIAL_VIDEO_MEETING_PROVIDER") or "").strip().lower()
    if provider_key not in SUPPORTED_PROVIDERS:
        return "", False
    enabled = str(os.getenv("EA_MEMORIAL_VIDEO_MEETING_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}
    required_env = {
        "tavus": "TAVUS_API_KEY",
        "did": "D_ID_API_KEY",
    }.get(provider_key, "")
    if not enabled or not required_env:
        return provider_key, False
    return provider_key, bool(str(os.getenv(required_env) or "").strip())


def _tavus_ready_for_live_session() -> bool:
    return all(
        str(os.getenv(name) or "").strip()
        for name in (
            "TAVUS_API_KEY",
            "TAVUS_PERSONA_ID",
            "TAVUS_REPLICA_ID",
        )
    ) and str(os.getenv("EA_MEMORIAL_VIDEO_MEETING_ALLOW_PROVIDER_SESSION") or "").strip().lower() in {"1", "true", "yes", "on"}


def public_video_meeting_payload(*, slug: str, person_name: str) -> dict[str, object]:
    provider_key, provider_configured = configured_provider()
    provider_name = provider_label(provider_key)
    if provider_key == "tavus" and provider_configured and _tavus_ready_for_live_session():
        integration_state = "provider_live_session_ready"
        detail = "Tavus ist für echte serverseitige Session-Erzeugung vorbereitet."
        next_action = "create_provider_session"
    elif provider_key == "did" and provider_configured:
        integration_state = "provider_configured_contract_only"
        detail = (
            "D-ID ist als Agent-SDK-/Client-Key-Lane vorgesehen. "
            "Die öffentliche Seite bleibt bis zur echten SDK-Integration weiter auf Portrait und Stimme fail-closed."
        )
        next_action = "provider_client_sdk_not_implemented"
    elif provider_configured and provider_key:
        integration_state = "provider_configured_contract_only"
        detail = (
            f"{provider_name} ist fuer den serverseitigen Session-Bootstrap konfiguriert. "
            "Die öffentliche Seite bleibt bis zur echten Live-Integration weiter auf Portrait und Stimme fail-closed."
        )
        next_action = "provider_session_runtime_not_implemented"
    else:
        integration_state = "fallback_only"
        detail = "Live-Avatar noch nicht freigegeben. Der Video Call läuft weiter über Portrait und Stimme."
        next_action = "fallback_to_portrait_voice"
    return {
        "enabled": False,
        "integration_state": integration_state,
        "provider_key": provider_key if provider_configured else "",
        "provider_label": provider_name if provider_configured else "",
        "title": f"Video Call mit {person_name}",
        "detail": detail,
        "camera_optional": True,
        "microphone_required": True,
        "fallback_mode": "portrait_voice",
        "session_endpoint": f"/memorials/{slug}/video-meeting/session",
        "status_endpoint": f"/memorials/{slug}/video-meeting/status",
        "recommended_provider": "tavus",
        "secondary_provider": "did",
        "next_action": next_action,
    }


def _tavus_callback_url(request_host: str, slug: str) -> str:
    base = str(os.getenv("EA_MEMORIAL_VIDEO_MEETING_CALLBACK_URL") or "").strip().rstrip("/")
    if base:
        return f"{base}/memorials/{slug}/video-meeting/provider-callback"
    host = str(request_host or "").strip().rstrip("/")
    if host.startswith("http://") or host.startswith("https://"):
        return f"{host}/memorials/{slug}/video-meeting/provider-callback"
    return ""


def create_video_meeting_session(
    *,
    slug: str,
    person_name: str,
    camera_requested: bool,
    personal_memory_enabled: bool,
    request_host: str,
) -> dict[str, object]:
    payload = public_video_meeting_payload(slug=slug, person_name=person_name)
    integration_state = str(payload.get("integration_state") or "fallback_only").strip()
    provider_key = str(payload.get("provider_key") or "").strip()
    response_payload: dict[str, Any] = {
        "slug": slug,
        "title": str(payload.get("title") or f"Video Call mit {person_name}"),
        "integration_state": integration_state,
        "provider_key": provider_key,
        "provider_label": str(payload.get("provider_label") or ""),
        "camera_optional": bool(payload.get("camera_optional") is True),
        "microphone_required": bool(payload.get("microphone_required") is True),
        "fallback_mode": str(payload.get("fallback_mode") or "portrait_voice"),
        "detail": str(payload.get("detail") or ""),
        "next_action": str(payload.get("next_action") or "fallback_to_portrait_voice"),
        "client": {
            "camera_requested": bool(camera_requested),
            "personal_memory_enabled": bool(personal_memory_enabled),
        },
    }
    if integration_state != "provider_live_session_ready" or provider_key != "tavus":
        return response_payload

    tavus_api_key = str(os.getenv("TAVUS_API_KEY") or "").strip()
    tavus_persona_id = str(os.getenv("TAVUS_PERSONA_ID") or "").strip()
    tavus_replica_id = str(os.getenv("TAVUS_REPLICA_ID") or "").strip()
    callback_url = _tavus_callback_url(request_host, slug)
    request_payload: dict[str, Any] = {
        "persona_id": tavus_persona_id,
        "replica_id": tavus_replica_id,
        "conversation_name": f"Manfred Memorial Live Call ({slug})",
        "custom_greeting": f"Schön, dass du da bist. Ich bin Manfred.",
        "conversational_context": (
            "This is a careful memorial conversation surface for Manfred Hoza. "
            "Keep the tone calm, direct, and source-bound."
        ),
        "require_auth": True,
        "max_participants": 2,
        "audio_only": False,
    }
    if callback_url:
        request_payload["callback_url"] = callback_url
    try:
        provider_response = requests.post(
            "https://tavusapi.com/v2/conversations",
            headers={
                "Content-Type": "application/json",
                "x-api-key": tavus_api_key,
            },
            json=request_payload,
            timeout=(10, 45),
        )
        provider_response.raise_for_status()
        provider_payload = provider_response.json()
    except Exception as exc:
        response_payload["integration_state"] = "fallback_only"
        response_payload["provider_key"] = ""
        response_payload["provider_label"] = ""
        response_payload["detail"] = f"Tavus-Session konnte gerade nicht erstellt werden. Der Video Call läuft weiter über Portrait und Stimme. ({str(exc)[:180]})"
        response_payload["next_action"] = "fallback_to_portrait_voice"
        return response_payload

    response_payload["provider_key"] = "tavus"
    response_payload["provider_label"] = "Tavus"
    response_payload["integration_state"] = "provider_live_session_created"
    response_payload["next_action"] = "join_provider_session"
    response_payload["provider_session"] = {
        "conversation_id": str(provider_payload.get("conversation_id") or "").strip(),
        "conversation_url": str(provider_payload.get("conversation_url") or "").strip(),
        "meeting_token": str(provider_payload.get("meeting_token") or "").strip(),
        "status": str(provider_payload.get("status") or "").strip(),
        "created_at": str(provider_payload.get("created_at") or "").strip(),
        "callback_url": str(provider_payload.get("callback_url") or callback_url).strip(),
    }
    response_payload["detail"] = "Tavus-Session erstellt. Der Client kann jetzt der Avatar-Session beitreten."
    return response_payload
