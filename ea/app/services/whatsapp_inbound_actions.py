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


def _playback_signature(*, secret: str, action: str, token: str, sender_ref: str, expires_at: int) -> str:
    payload = "|".join(("ap", action.strip().lower(), token.strip(), sender_ref.strip(), str(int(expires_at))))
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:10]


def _management_signature(*, secret: str, action: str, token: str, sender_ref: str, expires_at: int) -> str:
    payload = "|".join(("am", action.strip().lower(), token.strip(), sender_ref.strip(), str(int(expires_at))))
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:10]


def encode_whatsapp_audiobook_voice_callback(*, action: str, token: str, sender_ref: str, expires_at: int | None = None) -> str:
    normalized_action = str(action or "").strip().lower()[:1]
    normalized_token = str(token or "").strip()
    normalized_sender = str(sender_ref or "").strip()
    secret = _callback_secret()
    if normalized_action not in {"u", "d"} or not normalized_token or not normalized_sender or not secret:
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
    return f"ap|{normalized_action}|{normalized_token}|{expiry}|{signature}"


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
    if normalized_action not in {"u", "d"}:
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
        "action": "use" if normalized_action == "u" else "dismiss",
        "token": str(token or "").strip(),
        "expires_at": expires_at,
    }


def _decode_playback_callback(*, callback_data: str, sender_ref: str) -> dict[str, object]:
    parts = str(callback_data or "").strip().split("|")
    if len(parts) != 5 or parts[0] != "ap":
        return {"ok": False, "reason": "invalid_format"}
    _prefix, action, token, expires_raw, signature = parts
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
    )
    if not hmac.compare_digest(str(signature or "").strip(), expected):
        return {"ok": False, "reason": "invalid_signature"}
    return {
        "ok": True,
        "kind": "audiobook_playback",
        "action": "accepted" if normalized_action == "a" else "problem",
        "token": str(token or "").strip(),
        "expires_at": expires_at,
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
    if normalized.startswith("ap|"):
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


def _sender_digits(value: object) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _job_public_share(job: dict[str, object]) -> dict[str, object]:
    import_result = dict(job.get("audiobookshelf_import") or {})
    return dict(import_result.get("public_share") or {})


def _job_whatsapp_public_share_delivery(job: dict[str, object]) -> dict[str, object]:
    public_share = _job_public_share(job)
    delivery = dict(public_share.get("whatsapp_delivery") or {})
    if delivery:
        return delivery
    whatsapp = dict(job.get("whatsapp") or {})
    return dict(whatsapp.get("public_share_delivery") or {})


def _whatsapp_public_share_delivery_recoverable(delivery: dict[str, object]) -> bool:
    status = str(delivery.get("status") or "").strip().lower()
    return status in {"sent", "delivered", "read", "ok", "success"}


def _best_effort_playback_action(callback_data: str) -> str:
    parts = str(callback_data or "").strip().split("|")
    if len(parts) < 2 or parts[0] != "ap":
        return ""
    action = str(parts[1] or "").strip().lower()[:1]
    if action == "a":
        return "accepted"
    if action == "r":
        return "rejected"
    return ""


def _recover_whatsapp_playback_acceptance_for_sender(
    *,
    sender_ref: str,
    accepted: bool,
    message_id: str,
    feedback: str,
) -> dict[str, object]:
    normalized_sender = _sender_digits(sender_ref)
    if not normalized_sender:
        raise RuntimeError("audiobook_playback_acceptance_sender_missing")

    candidates: list[tuple[float, object]] = []
    root = audiobook_epub_pipeline.audiobook_jobs_root()
    for manifest_path in sorted(root.glob("*/job.json")):
        try:
            job = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(job, dict):
            continue
        if _sender_digits(dict(job.get("whatsapp") or {}).get("sender_ref")) != normalized_sender:
            continue
        public_share = _job_public_share(job)
        whatsapp_delivery = _job_whatsapp_public_share_delivery(job)
        playback = dict(job.get("playback_acceptance") or {})
        if not _whatsapp_public_share_delivery_recoverable(whatsapp_delivery):
            continue
        if (
            str(public_share.get("status") or "").strip() != "public_share_ready"
            and not str(public_share.get("absolute_url") or "").strip()
        ):
            continue
        if str(playback.get("status") or "").strip() in {"accepted", "rejected"}:
            continue
        candidates.append((manifest_path.stat().st_mtime, manifest_path.parent))

    if not candidates:
        raise RuntimeError("audiobook_playback_acceptance_recovery_job_not_found")

    _, job_dir = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
    return audiobook_epub_pipeline.record_audiobook_playback_acceptance(
        job_dir=job_dir,
        accepted=accepted,
        source="whatsapp_button_recovered",
        message_id=message_id,
        feedback=feedback,
    )


def handle_whatsapp_inbound_callback(
    *,
    callback_data: str,
    sender_ref: str,
    message_id: str = "",
) -> dict[str, object]:
    decoded = decode_whatsapp_inbound_callback(callback_data=callback_data, sender_ref=sender_ref)
    playback_callback = str(callback_data or "").strip().startswith("ap|")
    if not bool(decoded.get("ok")):
        fallback_action = _best_effort_playback_action(callback_data)
        if fallback_action:
            accepted = fallback_action == "accepted"
            feedback = "whatsapp_button_playback_accepted" if accepted else "whatsapp_button_playback_problem"
            try:
                _recover_whatsapp_playback_acceptance_for_sender(
                    sender_ref=sender_ref,
                    accepted=accepted,
                    message_id=message_id,
                    feedback=feedback,
                )
            except Exception:
                pass
            else:
                return {
                    "status": "applied",
                    "kind": "audiobook_playback",
                    "action": fallback_action,
                    "recovered": True,
                    "reply_text": "Marked the audiobook playback as working." if accepted else "Noted. I marked this audiobook for playback review.",
                }
        if str(decoded.get("kind") or "").strip() == "audiobook_playback" and str(decoded.get("reason") or "").strip() == "expired":
            accepted = str(decoded.get("action") or "").strip() == "accepted"
            feedback = "whatsapp_button_playback_accepted" if accepted else "whatsapp_button_playback_problem"
            try:
                _recover_whatsapp_playback_acceptance_for_sender(
                    sender_ref=sender_ref,
                    accepted=accepted,
                    message_id=message_id,
                    feedback=feedback,
                )
            except Exception:
                return {
                    "status": "stale",
                    "kind": "audiobook_playback",
                    "reason": "expired",
                    "reply_text": "That audiobook playback button expired. Send 'audiobook playback' and I will send fresh buttons for the latest audiobook.",
                }
            return {
                "status": "applied",
                "kind": "audiobook_playback",
                "action": str(decoded.get("action") or "").strip(),
                "recovered": True,
                "reply_text": "Marked the audiobook playback as working." if accepted else "Noted. I marked this audiobook for playback review.",
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
                "reason": reason or type(exc).__name__,
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
    try:
        audiobook_epub_pipeline.record_audiobook_playback_acceptance_by_callback_token(
            callback_token=str(decoded.get("token") or "").strip(),
            accepted=accepted,
            source="whatsapp_button",
            message_id=message_id,
            feedback="whatsapp_button_playback_accepted" if accepted else "whatsapp_button_playback_problem",
        )
    except Exception as exc:
        reason = str(exc).strip() or type(exc).__name__
        feedback = "whatsapp_button_playback_accepted" if accepted else "whatsapp_button_playback_problem"
        try:
            _recover_whatsapp_playback_acceptance_for_sender(
                sender_ref=sender_ref,
                accepted=accepted,
                message_id=message_id,
                feedback=feedback,
            )
        except Exception as recovery_exc:
            if reason == "audiobook_playback_acceptance_token_not_found":
                return {
                    "status": "stale",
                    "kind": "audiobook_playback",
                    "reason": str(recovery_exc).strip() or type(recovery_exc).__name__,
                    "reply_text": "That audiobook playback button is stale. Send 'audiobook playback' and I will send fresh buttons for the latest audiobook.",
                }
            return {
                "status": "failed",
                "kind": "audiobook_playback",
                "reason": reason,
                "reply_text": f"I could not record that audiobook playback result. Current blocker: {reason}.",
            }
        else:
            return {
                "status": "applied",
                "kind": "audiobook_playback",
                "action": str(decoded.get("action") or "").strip(),
                "recovered": True,
                "reply_text": "Marked the audiobook playback as working." if accepted else "Noted. I marked this audiobook for playback review.",
            }
    return {
        "status": "applied",
        "kind": "audiobook_playback",
        "action": str(decoded.get("action") or "").strip(),
        "reply_text": "Marked the audiobook playback as working." if accepted else "Noted. I marked this audiobook for playback review.",
    }
