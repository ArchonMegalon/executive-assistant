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


def email_delivery_enabled() -> bool:
    return bool(str(os.environ.get("EMAILIT_API_KEY") or "").strip())


def _registration_sender_email() -> str:
    configured = str(os.environ.get("EA_REGISTRATION_EMAIL_FROM") or "").strip()
    if configured:
        return configured
    fallback = str(os.environ.get("EA_EMAIL_DEFAULT_FROM") or "").strip()
    return fallback or DEFAULT_SENDER_EMAIL


def delivery_sender_emails() -> tuple[str, ...]:
    values = {
        DEFAULT_SENDER_EMAIL.strip().lower(),
        str(os.environ.get("EA_EMAIL_DEFAULT_FROM") or "").strip().lower(),
        str(os.environ.get("EA_REGISTRATION_EMAIL_FROM") or "").strip().lower(),
        _registration_sender_email().strip().lower(),
    }
    return tuple(sorted(value for value in values if value))


def _registration_sender_name() -> str:
    configured = str(os.environ.get("EA_REGISTRATION_EMAIL_NAME") or "").strip()
    if configured:
        return configured
    fallback = str(os.environ.get("EA_EMAIL_DEFAULT_NAME") or "").strip()
    return fallback or DEFAULT_SENDER_NAME


def _resolved_sender_email(sender_email: str = "") -> str:
    configured = str(sender_email or "").strip()
    if configured:
        return configured
    return _registration_sender_email()


def _resolved_sender_name(sender_name: str = "") -> str:
    configured = str(sender_name or "").strip()
    if configured:
        return configured
    return _registration_sender_name()


def _registration_subject() -> str:
    return "Verify your email for Executive Assistant"


def _minutes_until(*, expires_at: int | None = None, expires_at_iso: str = "") -> int:
    if expires_at is not None:
        return max(1, int((int(expires_at) - int(time.time())) / 60))
    normalized = str(expires_at_iso or "").strip()
    if not normalized:
        return 60
    try:
        when = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return 60
    return max(1, int((when - datetime.now(timezone.utc)).total_seconds() / 60))


def _registration_text(*, verification_code: str, magic_link_url: str, expires_at: int) -> str:
    minutes = _minutes_until(expires_at=expires_at)
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


def _meta_ref(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def _digest_preview_excerpt(plain_text: str, *, max_lines: int = 8, max_chars: int = 800) -> str:
    lines: list[str] = []
    for raw_line in str(plain_text or "").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith("open digest:"):
            continue
        if len(stripped) > 240 and "http" in stripped:
            continue
        lines.append(stripped)
        if len(lines) >= max_lines:
            break
    excerpt = "\n".join(lines).strip()
    if len(excerpt) > max_chars:
        excerpt = excerpt[: max_chars - 3].rstrip() + "..."
    return excerpt


def _send_emailit_email(
    *,
    recipient_email: str,
    subject: str,
    text: str,
    kind: str,
    meta: dict[str, object] | None = None,
    sender_email: str = "",
    sender_name: str = "",
) -> RegistrationEmailReceipt:
    api_key = str(os.environ.get("EMAILIT_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("registration_email_api_key_missing")
    resolved_sender_email = _resolved_sender_email(sender_email)
    resolved_sender_name = _resolved_sender_name(sender_name)
    payload = {
        "from": f"{resolved_sender_name} <{resolved_sender_email}>",
        "to": str(recipient_email or "").strip(),
        "subject": str(subject or "").strip(),
        "text": str(text or "").strip(),
        "html": "",
        "reply_to": resolved_sender_email,
        "tracking": False,
        "meta": {
            "kind": kind,
            "recipient_email": str(recipient_email or "").strip(),
            **dict(meta or {}),
        },
    }
    idempotency_seed = json.dumps(
        {
            "kind": kind,
            "recipient_email": str(recipient_email or "").strip().lower(),
            "subject": str(subject or "").strip(),
            "meta": dict(meta or {}),
            "sender_email": resolved_sender_email.lower(),
            "sender_name": resolved_sender_name,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    idempotency_key = f"ea-mail-{hashlib.sha256(idempotency_seed.encode('utf-8')).hexdigest()[:24]}"
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


def send_registration_email(*, recipient_email: str, verification_code: str, magic_link_url: str, expires_at: int) -> RegistrationEmailReceipt:
    return _send_emailit_email(
        recipient_email=recipient_email,
        subject=_registration_subject(),
        text=_registration_text(
            verification_code=verification_code,
            magic_link_url=magic_link_url,
            expires_at=expires_at,
        ),
        kind="ea_registration_verification",
        meta={"verification_code": verification_code},
    )


def send_workspace_invitation_email(
    *,
    recipient_email: str,
    invite_url: str,
    role: str,
    invited_by: str,
    note: str = "",
    expires_at: str = "",
) -> RegistrationEmailReceipt:
    minutes = _minutes_until(expires_at_iso=expires_at)
    role_label = str(role or "operator").strip().replace("_", " ").title() or "Operator"
    inviter = str(invited_by or "Executive Assistant").strip() or "Executive Assistant"
    note_text = str(note or "").strip()
    body = [
        "Hello,",
        "",
        f"{inviter} invited you to join an Executive Assistant workspace as {role_label}.",
        "",
        "Open this secure link to accept the invite:",
        "",
        invite_url,
        "",
        f"This link expires in about {minutes} minutes.",
    ]
    if note_text:
        body.extend(["", "Message from the workspace:", note_text])
    body.extend(
        [
            "",
            "You will get workspace access after accepting the invite.",
            "Google is connected later as a workspace data source. It is not your app login.",
        ]
    )
    return _send_emailit_email(
        recipient_email=recipient_email,
        subject=f"{inviter} invited you to Executive Assistant",
        text="\n".join(body).strip() + "\n",
        kind="ea_workspace_invitation",
        meta={"invite_ref": _meta_ref(invite_url), "role": str(role or "").strip().lower()},
    )


def send_workspace_access_email(
    *,
    recipient_email: str,
    workspace_name: str,
    access_url: str,
    role: str,
    display_name: str = "",
    expires_at: str = "",
) -> RegistrationEmailReceipt:
    minutes = _minutes_until(expires_at_iso=expires_at)
    role_label = str(role or "principal").strip().replace("_", " ").title() or "Principal"
    workspace_label = str(workspace_name or "Executive Assistant workspace").strip() or "Executive Assistant workspace"
    display = str(display_name or "").strip()
    body = [
        "Hello,",
        "",
        f"Open this secure link to return to {workspace_label}:",
        "",
        access_url,
        "",
        f"This link expires in about {minutes} minutes.",
    ]
    if display:
        body.extend(["", f"This link opens your {role_label.lower()} access as {display}."])
    else:
        body.extend(["", f"This link opens your {role_label.lower()} access to the workspace."])
    body.extend(
        [
            "",
            "Google is connected later as a workspace data source. It is not your app login.",
        ]
    )
    return _send_emailit_email(
        recipient_email=recipient_email,
        subject=f"Your access link for {workspace_label}",
        text="\n".join(body).strip() + "\n",
        kind="ea_workspace_access_session",
        meta={
            "access_ref": _meta_ref(access_url),
            "workspace_name": workspace_label,
            "role": str(role or "").strip().lower(),
        },
    )


def send_google_connect_email(
    *,
    recipient_email: str,
    workspace_name: str,
    connect_url: str,
    scope_label: str,
    scope_summary: str,
    primary_google_email: str = "",
    connected_account_total: int = 0,
    expires_at: str = "",
) -> RegistrationEmailReceipt:
    minutes = _minutes_until(expires_at_iso=expires_at)
    workspace_label = str(workspace_name or "Executive Assistant workspace").strip() or "Executive Assistant workspace"
    label = str(scope_label or "Google Full Workspace").strip() or "Google Full Workspace"
    summary = str(scope_summary or "").strip()
    primary_email = str(primary_google_email or "").strip().lower()
    body = [
        "Hello,",
        "",
        f"Open this secure link to connect a Google inbox to {workspace_label}:",
        "",
        connect_url,
        "",
        f"This link expires in about {minutes} minutes.",
        "",
        "The link signs you into the workspace first, then starts Google consent.",
        f"Requested bundle: {label}.",
    ]
    if summary:
        body.extend(["", summary])
    if connected_account_total <= 0:
        body.extend(["", "No Google inbox is connected in this workspace yet, so this link will attach the first one."])
    elif primary_email:
        body.extend(["", f"The current primary inbox stays {primary_email}. This link adds another inbox to the same workspace."])
    else:
        body.extend(["", "This link adds another Google inbox to the same workspace."])
    body.extend(
        [
            "",
            "Google is used here as workspace data and action consent. It is not your app login.",
        ]
    )
    return _send_emailit_email(
        recipient_email=recipient_email,
        subject=f"Connect Google to {workspace_label}",
        text="\n".join(body).strip() + "\n",
        kind="ea_google_connect_link",
        sender_email=str(os.environ.get("EA_EMAIL_DEFAULT_FROM") or "").strip(),
        sender_name=str(os.environ.get("EA_EMAIL_DEFAULT_NAME") or "").strip(),
        meta={
            "connect_ref": _meta_ref(connect_url),
            "workspace_name": workspace_label,
            "scope_label": label,
        },
    )


def send_property_tour_email(
    *,
    recipient_email: str,
    property_title: str,
    property_url: str,
    tour_url: str,
    variant_key: str = "",
    listing_id: str = "",
    area_label: str = "",
    rooms_label: str = "",
    price_label: str = "",
    sender_email: str = "",
    sender_name: str = "",
) -> RegistrationEmailReceipt:
    title = str(property_title or "Apartment tour").strip() or "Apartment tour"
    variant_label = str(variant_key or "").strip().replace("_", " ")
    subject = f"Apartment tour ready: {title}"
    if variant_label:
        subject = f"{subject} · {variant_label}"
    body = [
        "Hello,",
        "",
        f"EA prepared a tour for {title}:",
        "",
        tour_url,
        "",
        f"Listing: {property_url}",
    ]
    if listing_id:
        body.append(f"Listing ID: {listing_id}")
    facts = [value for value in (area_label, rooms_label, price_label) if str(value or "").strip()]
    if facts:
        body.extend(["", "Quick facts:", *facts])
    body.extend(
        [
            "",
            "Open the tour link to review the space directly.",
        ]
    )
    return _send_emailit_email(
        recipient_email=recipient_email,
        subject=subject[:220],
        text="\n".join(body).strip() + "\n",
        kind="ea_property_tour_delivery",
        meta={
            "tour_ref": _meta_ref(tour_url),
            "listing_ref": _meta_ref(property_url),
            "variant_key": str(variant_key or "").strip(),
        },
        sender_email=sender_email,
        sender_name=sender_name,
    )


def send_channel_digest_email(
    *,
    recipient_email: str,
    digest_key: str,
    headline: str,
    preview_text: str,
    delivery_url: str,
    plain_text: str,
    expires_at: str = "",
) -> RegistrationEmailReceipt:
    minutes = _minutes_until(expires_at_iso=expires_at)
    label = str(headline or "Executive Assistant update").strip() or "Executive Assistant update"
    preview = str(preview_text or "").strip()
    digest_excerpt = _digest_preview_excerpt(plain_text)
    body = [
        label,
        "",
    ]
    if preview:
        body.extend([preview, ""])
    body.extend(
        [
            "Open this secure workspace view:",
            "",
            delivery_url,
            "",
            f"This link expires in about {minutes} minutes.",
        ]
    )
    if digest_excerpt:
        body.extend(["", "Digest preview", "", digest_excerpt])
    return _send_emailit_email(
        recipient_email=recipient_email,
        subject=label,
        text="\n".join(body).strip() + "\n",
        kind="ea_channel_digest_delivery",
        meta={"digest_key": str(digest_key or "").strip().lower(), "delivery_ref": _meta_ref(delivery_url)},
    )


def send_plaintext_digest_email(
    *,
    recipient_email: str,
    digest_key: str,
    headline: str,
    preview_text: str,
    plain_text: str,
    sender_email: str = "",
    sender_name: str = "",
) -> RegistrationEmailReceipt:
    label = str(headline or "Executive Assistant update").strip() or "Executive Assistant update"
    preview = str(preview_text or "").strip()
    body = [label, ""]
    if preview:
        body.extend([preview, ""])
    body.extend([str(plain_text or "").strip()])
    return _send_emailit_email(
        recipient_email=recipient_email,
        subject=label,
        text="\n".join(body).strip() + "\n",
        kind="ea_plaintext_digest_delivery",
        meta={"digest_key": str(digest_key or "").strip().lower()},
        sender_email=sender_email,
        sender_name=sender_name,
    )
