from __future__ import annotations

import copy
import hmac
import hashlib
import json
import os
import time
from typing import Any

from app.services import audiobook_epub_pipeline


DEFAULT_CALLBACK_SECRET_FILES = (
    "/run/secrets/whatsapp_audiobook_callback_secret",
    "/config/whatsapp_audiobook_callback_secret",
    "/app/config/whatsapp_audiobook_callback_secret",
)
DEFAULT_PLAYBACK_CALLBACK_TTL_SECONDS = 30 * 24 * 60 * 60


def _base36_decode(value: str) -> int:
    return int(str(value or "0").strip().lower(), 36)


def _callback_secret_from_file() -> str:
    paths = [
        str(os.getenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET_FILE") or "").strip(),
        *DEFAULT_CALLBACK_SECRET_FILES,
    ]
    for raw_path in paths:
        if not raw_path:
            continue
        try:
            with open(raw_path, encoding="utf-8") as handle:
                secret = handle.read().strip()
        except OSError:
            continue
        if secret:
            return secret
    return ""


def _callback_secret() -> str:
    return (
        str(os.getenv("EA_WHATSAPP_AUDIOBOOK_CALLBACK_SECRET") or "").strip()
        or str(os.getenv("EA_WHATSAPP_CALLBACK_SECRET") or "").strip()
        or str(os.getenv("EA_WHATSAPP_WEB_SESSION_API_TOKEN") or "").strip()
        or _callback_secret_from_file()
    )


def _playback_callback_ttl_seconds() -> int:
    raw = str(os.getenv("EA_WHATSAPP_AUDIOBOOK_PLAYBACK_CALLBACK_TTL_SECONDS") or "").strip()
    try:
        value = int(raw or DEFAULT_PLAYBACK_CALLBACK_TTL_SECONDS)
    except Exception:
        value = DEFAULT_PLAYBACK_CALLBACK_TTL_SECONDS
    return max(value, 300)


def _voice_signature(*, secret: str, action: str, token: str, sender_ref: str, expires_at: int) -> str:
    payload = "|".join(("ab", action.strip().lower(), token.strip(), sender_ref.strip(), str(int(expires_at))))
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:10]


def _playback_signature(
    *,
    secret: str,
    action: str,
    token: str,
    sender_ref: str,
    expires_at: int,
    callback_prefix: str = "ap2",
) -> str:
    normalized_prefix = str(callback_prefix or "").strip().lower()
    if normalized_prefix not in {"ap", "ap2"}:
        normalized_prefix = "ap2"
    payload = "|".join((normalized_prefix, action.strip().lower(), token.strip(), sender_ref.strip(), str(int(expires_at))))
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:10]


def _management_signature(*, secret: str, action: str, token: str, sender_ref: str, expires_at: int) -> str:
    payload = "|".join(("am", action.strip().lower(), token.strip(), sender_ref.strip(), str(int(expires_at))))
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:10]


def encode_whatsapp_audiobook_voice_callback(*, action: str, token: str, sender_ref: str, expires_at: int | None = None) -> str:
    normalized_action = str(action or "").strip().lower()[:1]
    normalized_token = str(token or "").strip()
    normalized_sender = str(sender_ref or "").strip()
    secret = _callback_secret()
    if normalized_action not in {"u", "d", "a"} or not normalized_token or not normalized_sender or not secret:
        return ""
    expiry = int(expires_at or (time.time() + 604800))
    signature = _voice_signature(
        secret=secret,
        action=normalized_action,
        token=normalized_token,
        sender_ref=normalized_sender,
        expires_at=expiry,
    )
    return f"ab|{normalized_action}|{normalized_token}|{_base36_encode(expiry)}|{signature}"


def _base36_encode(value: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    normalized = max(int(value), 0)
    if normalized == 0:
        return "0"
    chars: list[str] = []
    while normalized:
        normalized, remainder = divmod(normalized, 36)
        chars.append(alphabet[remainder])
    return "".join(reversed(chars))


def encode_whatsapp_audiobook_playback_callback(*, action: str, token: str, sender_ref: str, expires_at: int | None = None) -> str:
    normalized_action = str(action or "").strip().lower()[:1]
    normalized_token = str(token or "").strip()
    normalized_sender = str(sender_ref or "").strip()
    secret = _callback_secret()
    if normalized_action not in {"a", "r"} or not normalized_token or not normalized_sender or not secret:
        return ""
    expiry = int(expires_at or (time.time() + _playback_callback_ttl_seconds()))
    signature = _playback_signature(
        secret=secret,
        action=normalized_action,
        token=normalized_token,
        sender_ref=normalized_sender,
        expires_at=expiry,
    )
    return f"ap2|{normalized_action}|{normalized_token}|{expiry}|{signature}"


def encode_whatsapp_audiobook_management_callback(*, action: str, token: str, sender_ref: str, expires_at: int | None = None) -> str:
    normalized_action = str(action or "").strip().lower()[:1]
    normalized_token = str(token or "").strip()
    normalized_sender = str(sender_ref or "").strip()
    secret = _callback_secret()
    if normalized_action not in {"r", "n", "b"} or not normalized_token or not normalized_sender or not secret:
        return ""
    expiry = int(expires_at or (time.time() + 604800))
    signature = _management_signature(
        secret=secret,
        action=normalized_action,
        token=normalized_token,
        sender_ref=normalized_sender,
        expires_at=expiry,
    )
    return f"am|{normalized_action}|{normalized_token}|{_base36_encode(expiry)}|{signature}"


def _decode_voice_callback(*, callback_data: str, sender_ref: str) -> dict[str, object]:
    parts = str(callback_data or "").strip().split("|")
    if len(parts) != 5 or parts[0] != "ab":
        return {"ok": False, "reason": "invalid_format"}
    _prefix, action, token, expires_raw, signature = parts
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"u", "d", "a"}:
        return {"ok": False, "reason": "invalid_action"}
    try:
        expires_at = _base36_decode(expires_raw)
    except Exception:
        return {"ok": False, "reason": "invalid_expiry"}
    if expires_at < int(time.time()):
        return {"ok": False, "reason": "expired"}
    secret = _callback_secret()
    if not secret:
        return {"ok": False, "reason": "missing_secret"}
    expected = _voice_signature(
        secret=secret,
        action=normalized_action,
        token=str(token or "").strip(),
        sender_ref=str(sender_ref or "").strip(),
        expires_at=expires_at,
    )
    if not hmac.compare_digest(str(signature or "").strip(), expected):
        return {"ok": False, "reason": "invalid_signature"}
    return {
        "ok": True,
        "kind": "audiobook_voice",
        "action": {
            "u": "use",
            "d": "dismiss",
            "a": "use_automatic_cast",
        }[normalized_action],
        "token": str(token or "").strip(),
        "expires_at": expires_at,
    }


def _decode_playback_callback(*, callback_data: str, sender_ref: str) -> dict[str, object]:
    parts = str(callback_data or "").strip().split("|")
    if len(parts) != 5 or parts[0] not in {"ap", "ap2"}:
        return {"ok": False, "reason": "invalid_format"}
    callback_prefix, action, token, expires_raw, signature = parts
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"a", "r"}:
        return {"ok": False, "reason": "invalid_action"}
    try:
        expires_at = int(str(expires_raw or "").strip())
    except Exception:
        return {"ok": False, "reason": "invalid_expiry"}
    if expires_at < int(time.time()):
        return {
            "ok": False,
            "reason": "expired",
            "kind": "audiobook_playback",
            "action": "accepted" if normalized_action == "a" else "problem",
            "token": str(token or "").strip(),
            "expires_at": expires_at,
        }
    secret = _callback_secret()
    if not secret:
        return {"ok": False, "reason": "missing_secret"}
    expected = _playback_signature(
        secret=secret,
        action=normalized_action,
        token=str(token or "").strip(),
        sender_ref=str(sender_ref or "").strip(),
        expires_at=expires_at,
        callback_prefix=callback_prefix,
    )
    if not hmac.compare_digest(str(signature or "").strip(), expected):
        return {"ok": False, "reason": "invalid_signature"}
    return {
        "ok": True,
        "kind": "audiobook_playback",
        "action": "accepted" if normalized_action == "a" else "problem",
        "token": str(token or "").strip(),
        "expires_at": expires_at,
        "perceptual_attestation_version": (
            1 if callback_prefix == "ap2" else 0
        ),
    }


def _decode_management_callback(*, callback_data: str, sender_ref: str) -> dict[str, object]:
    parts = str(callback_data or "").strip().split("|")
    if len(parts) != 5 or parts[0] != "am":
        return {"ok": False, "reason": "invalid_format"}
    _prefix, action, token, expires_raw, signature = parts
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"r", "n", "b"}:
        return {"ok": False, "reason": "invalid_action"}
    try:
        expires_at = _base36_decode(expires_raw)
    except Exception:
        return {"ok": False, "reason": "invalid_expiry"}
    if expires_at < int(time.time()):
        return {"ok": False, "reason": "expired"}
    secret = _callback_secret()
    if not secret:
        return {"ok": False, "reason": "missing_secret"}
    expected = _management_signature(
        secret=secret,
        action=normalized_action,
        token=str(token or "").strip(),
        sender_ref=str(sender_ref or "").strip(),
        expires_at=expires_at,
    )
    if not hmac.compare_digest(str(signature or "").strip(), expected):
        return {"ok": False, "reason": "invalid_signature"}
    action_name = {
        "r": "restore_language",
        "n": "next_batch",
        "b": "use_best_current",
    }[normalized_action]
    return {
        "ok": True,
        "kind": "audiobook_voice_management",
        "action": action_name,
        "token": str(token or "").strip(),
        "expires_at": expires_at,
    }


def decode_whatsapp_inbound_callback(*, callback_data: str, sender_ref: str) -> dict[str, object]:
    normalized = str(callback_data or "").strip()
    if normalized.startswith("ab|"):
        return _decode_voice_callback(callback_data=normalized, sender_ref=sender_ref)
    if normalized.startswith(("ap|", "ap2|")):
        return _decode_playback_callback(callback_data=normalized, sender_ref=sender_ref)
    if normalized.startswith("am|"):
        return _decode_management_callback(callback_data=normalized, sender_ref=sender_ref)
    return {"ok": False, "reason": "unsupported_callback"}


def _whatsapp_audiobook_reply_text(job: dict[str, object]) -> str:
    whatsapp_job = copy.deepcopy(job)
    whatsapp = dict(whatsapp_job.get("whatsapp") or {})
    delivery = dict(whatsapp.get("voice_sample_delivery") or {})
    if delivery:
        telegram = dict(whatsapp_job.get("telegram") or {})
        telegram["voice_sample_delivery"] = delivery
        whatsapp_job["telegram"] = telegram
    text = audiobook_epub_pipeline.telegram_epub_reply_text(whatsapp_job)
    return text.replace("Telegram", "WhatsApp").replace("telegram", "WhatsApp")


def handle_whatsapp_inbound_callback(
    *,
    callback_data: str,
    sender_ref: str,
    message_id: str = "",
) -> dict[str, object]:
    decoded = decode_whatsapp_inbound_callback(callback_data=callback_data, sender_ref=sender_ref)
    playback_callback = str(callback_data or "").strip().startswith(("ap|", "ap2|"))
    if not bool(decoded.get("ok")):
        if str(decoded.get("kind") or "").strip() == "audiobook_playback" and str(decoded.get("reason") or "").strip() == "expired":
            return {
                "status": "stale",
                "kind": "audiobook_playback",
                "reason": "expired",
                "reply_text": "That audiobook playback button expired. Send 'audiobook playback' and I will send fresh buttons for the latest audiobook.",
            }
        if playback_callback:
            return {
                "status": "stale",
                "kind": "audiobook_playback",
                "reason": str(decoded.get("reason") or "invalid_callback"),
                "reply_text": "That audiobook playback button is stale. Send 'audiobook playback' and I will send fresh buttons for the latest audiobook.",
            }
        return {
            "status": "ignored",
            "reason": str(decoded.get("reason") or "invalid_callback"),
            "reply_text": "That WhatsApp action is no longer valid. Send the request again if needed.",
        }
    if str(decoded.get("kind") or "") == "audiobook_voice":
        try:
            job = audiobook_epub_pipeline.apply_audiobook_voice_audition_action(
                callback_token=str(decoded.get("token") or "").strip(),
                action=str(decoded.get("action") or "").strip(),
            )
        except Exception as exc:
            reason = str(exc).strip()
            if reason in {"voice_audition_token_not_found", "voice_audition_token_missing"}:
                return {
                    "status": "stale",
                    "kind": "audiobook_voice",
                    "reason": reason,
                    "reply_text": "That audiobook voice button is stale, so I ignored it. Use the latest voice sample buttons, or reply with the voice name or 'dismiss all'.",
                }
            return {
                "status": "failed",
                "kind": "audiobook_voice",
                "reason": "audiobook_voice_choice_failed",
                "reply_text": "I could not apply that audiobook voice choice yet.",
            }
        return {
            "status": "applied",
            "kind": "audiobook_voice",
            "action": str(decoded.get("action") or "").strip(),
            "job": job,
            "reply_text": _whatsapp_audiobook_reply_text(job),
        }
    if str(decoded.get("kind") or "") == "audiobook_voice_management":
        return {
            "status": "applied",
            "kind": "audiobook_voice_management",
            "action": str(decoded.get("action") or "").strip(),
            "token": str(decoded.get("token") or "").strip(),
            "reply_text": "",
        }
    accepted = str(decoded.get("action") or "").strip() == "accepted"
    perceptual_attestation_version = int(
        decoded.get("perceptual_attestation_version") or 0
    )
    structured_attestation = (
        audiobook_epub_pipeline.build_audiobook_perceptual_attestation(
            channel="whatsapp"
        )
        if accepted and perceptual_attestation_version == 1
        else None
    )
    feedback = (
        audiobook_epub_pipeline.audiobook_perceptual_attestation_feedback(
            "whatsapp"
        )
        if structured_attestation
        else "whatsapp_button_playback_accepted"
        if accepted
        else "whatsapp_button_playback_problem"
    )
    try:
        updated_job = audiobook_epub_pipeline.record_audiobook_playback_acceptance_by_callback_token(
            callback_token=str(decoded.get("token") or "").strip(),
            accepted=accepted,
            source="whatsapp_button",
            message_id=message_id,
            feedback=feedback,
            perceptual_attestation=structured_attestation,
        )
    except Exception as exc:
        reason = str(exc).strip()
        if reason in {
            "audiobook_playback_acceptance_token_missing",
            "audiobook_playback_acceptance_token_not_found",
        }:
            return {
                "status": "stale",
                "kind": "audiobook_playback",
                "reason": "audiobook_playback_acceptance_stale",
                "reply_text": "That audiobook playback button is stale. Send 'audiobook playback' and I will send fresh buttons for the latest audiobook.",
            }
        return {
            "status": "failed",
            "kind": "audiobook_playback",
            "reason": "audiobook_playback_acceptance_failed",
            "reply_text": "I could not record that audiobook playback result. Please try again with the latest playback buttons.",
        }
    return {
        "status": "applied",
        "kind": "audiobook_playback",
        "action": str(decoded.get("action") or "").strip(),
        "reply_text": (
            (
                "Recorded your all-7 perceptual playback attestation."
                if dict(
                    dict(updated_job or {}).get("playback_acceptance") or {}
                ).get(
                    "listened"
                )
                is True
                else (
                    "Recorded the seven-check response, but the listened-canary "
                    "proof is still incomplete. Send 'audiobook playback' to "
                    "retry after the release evidence is ready."
                )
            )
            if structured_attestation
            else (
                "Recorded the legacy playback acknowledgement. It does "
                "not complete the listened-canary checklist."
            )
            if accepted
            else "Noted. I marked this audiobook for playback review."
        ),
    }
