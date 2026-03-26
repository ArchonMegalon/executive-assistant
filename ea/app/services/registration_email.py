from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone


EMAILIT_API_BASE = "https://api.emailit.com/v2/emails"
DEFAULT_SENDER_EMAIL = "kleinhirn@myexternalbrain.com"
DEFAULT_SENDER_NAME = "Kleinhirn"


@dataclass(frozen=True)
class RegistrationEmailReceipt:
    provider: str
    message_id: str
    accepted_at: str


def _registration_sender_email() -> str:
    configured = str(os.environ.get("EA_REGISTRATION_EMAIL_FROM") or "").strip()
    if configured:
        return configured
    fallback = str(os.environ.get("EA_EMAIL_DEFAULT_FROM") or "").strip()
    return fallback or DEFAULT_SENDER_EMAIL


def _registration_sender_name() -> str:
    configured = str(os.environ.get("EA_REGISTRATION_EMAIL_NAME") or "").strip()
    if configured:
        return configured
    fallback = str(os.environ.get("EA_EMAIL_DEFAULT_NAME") or "").strip()
    return fallback or DEFAULT_SENDER_NAME


def _registration_subject() -> str:
    return "Verify your email for Executive Assistant"


def _registration_text(*, verification_code: str, magic_link_url: str, expires_at: int) -> str:
    minutes = max(1, int((int(expires_at) - int(time.time())) / 60))
    return (
        "Hello,\n\n"
        "Use this verification code to create your Executive Assistant workspace:\n\n"
        f"{verification_code}\n\n"
        "Or open this secure link:\n\n"
        f"{magic_link_url}\n\n"
        f"This link and code expire in about {minutes} minutes.\n\n"
        "Google is connected after sign-up as a workspace data source. It is not your app login.\n\n"
        "If you did not request this email, you can ignore it.\n"
    )


def send_registration_email(*, recipient_email: str, verification_code: str, magic_link_url: str, expires_at: int) -> RegistrationEmailReceipt:
    api_key = str(os.environ.get("EMAILIT_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("registration_email_api_key_missing")
    payload = {
        "from": f"{_registration_sender_name()} <{_registration_sender_email()}>",
        "to": str(recipient_email or "").strip(),
        "subject": _registration_subject(),
        "text": _registration_text(
            verification_code=verification_code,
            magic_link_url=magic_link_url,
            expires_at=expires_at,
        ),
        "html": "",
        "reply_to": _registration_sender_email(),
        "tracking": False,
        "meta": {
            "kind": "ea_registration_verification",
            "recipient_email": str(recipient_email or "").strip(),
        },
    }
    idempotency_seed = f"{str(recipient_email or '').strip().lower()}|{verification_code}|registration"
    idempotency_key = f"ea-register-{hashlib.sha256(idempotency_seed.encode('utf-8')).hexdigest()[:24]}"
    request = urllib.request.Request(
        EMAILIT_API_BASE,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        },
        method="POST",
    )
    last_error = ""
    for _ in range(7):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(body or "{}")
            return RegistrationEmailReceipt(
                provider="emailit",
                message_id=str(parsed.get("id") or ""),
                accepted_at=datetime.now(timezone.utc).isoformat(),
            )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = f"registration_email_send_failed:{exc.code}:{detail[:600]}"
            if exc.code == 429:
                retry_after = 1
                try:
                    retry_after = int(json.loads(detail).get("retry_after") or 1)
                except Exception:
                    retry_after = 1
                time.sleep(max(1, retry_after))
                continue
            break
    raise RuntimeError(last_error or "registration_email_send_failed")
