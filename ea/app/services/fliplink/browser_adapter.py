from __future__ import annotations

from app.services.fliplink.models import fliplink_settings_from_env


def browseract_fliplink_publish_requested(request: dict[str, object]) -> dict[str, object]:
    settings = fliplink_settings_from_env()
    if not settings.browseract_enabled:
        raise RuntimeError("fliplink_browseract_disabled")
    if not str(request.get("pdf_artifact_ref") or "").strip():
        raise ValueError("pdf_artifact_ref_required")
    if not bool(request.get("redaction_receipt_present")):
        raise ValueError("redaction_receipt_required")
    if str(request.get("privacy_mode") or "").strip() == "owner_private" and not bool(request.get("password_required")):
        raise ValueError("owner_private_requires_password")
    return {
        "status": "queued_operator_assist",
        "task_name": "browseract.fliplink_publish_property_packet",
        "provider": "fliplink",
    }
