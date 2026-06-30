from __future__ import annotations

import urllib.parse

from app.services.public_urls import ea_public_app_base_url


DEFAULT_GOOGLE_REAUTH_RETURN_TO = "/app/settings/google"
DEFAULT_GOOGLE_REAUTH_SCOPE_BUNDLE = "full_workspace"
DEFAULT_WHATSAPP_RECOVERY_PATH = "/integrations/whatsapp"
DEFAULT_APPROVAL_CAPTURE_PATH = "/admin/proactive-ooda/approval"
DEFAULT_QUEUE_REVIEW_PATH = "/app/queue"
DEFAULT_POCKET_SYNC_PATH = "/app/api/signals/pocket/reindex-archive"


def _absolute_public_href(path: str, *, public_base_url: str = "") -> str:
    normalized_path = str(path or "").strip()
    if not normalized_path:
        return ""
    if normalized_path.startswith(("http://", "https://")):
        return normalized_path
    base_url = str(public_base_url or ea_public_app_base_url()).strip().rstrip("/")
    if not base_url:
        return normalized_path
    return urllib.parse.urljoin(f"{base_url}/", normalized_path.lstrip("/"))


def proactive_next_action_surface(action: str, *, public_base_url: str = "") -> dict[str, str]:
    normalized = str(action or "").strip()
    if normalized == "reauthorize_google_workspace_binding":
        path = "/app/actions/google/connect?" + urllib.parse.urlencode(
            {
                "return_to": DEFAULT_GOOGLE_REAUTH_RETURN_TO,
                "scope_bundle": DEFAULT_GOOGLE_REAUTH_SCOPE_BUNDLE,
            }
        )
        return {
            "href": _absolute_public_href(path, public_base_url=public_base_url),
            "label": "Reconnect Google workspace",
            "method": "get",
        }
    if normalized in {"scan_whatsapp_web_qr", "restore_whatsapp_web_session"}:
        return {
            "href": _absolute_public_href(DEFAULT_WHATSAPP_RECOVERY_PATH, public_base_url=public_base_url),
            "label": "Open WhatsApp pairing",
            "method": "get",
        }
    if normalized in {
        "tap_proactive_telegram_approval_button_or_record_proactive_ooda_approval_outcome",
        "record_proactive_ooda_approval_outcome",
    }:
        return {
            "href": _absolute_public_href(DEFAULT_APPROVAL_CAPTURE_PATH, public_base_url=public_base_url),
            "label": "Open approval capture",
            "method": "get",
        }
    if normalized == "review_proactive_draft_queue":
        return {
            "href": _absolute_public_href(DEFAULT_QUEUE_REVIEW_PATH, public_base_url=public_base_url),
            "label": "Open queue",
            "method": "get",
        }
    if normalized == "sync_pocket_ai_audio_transcripts":
        return {
            "href": _absolute_public_href(DEFAULT_POCKET_SYNC_PATH, public_base_url=public_base_url),
            "label": "Sync Pocket transcripts",
            "method": "post",
        }
    return {"href": "", "label": "", "method": ""}
