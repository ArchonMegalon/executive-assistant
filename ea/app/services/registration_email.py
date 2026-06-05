from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import hashlib
import html
from dataclasses import dataclass
from datetime import datetime, timezone


EMAILIT_API_BASE = "https://api.emailit.com/v2/emails"
DEFAULT_SENDER_EMAIL = "property@propertyquarry.com"
DEFAULT_SENDER_NAME = "PropertyQuarry"


@dataclass(frozen=True)
class RegistrationEmailReceipt:
    provider: str
    message_id: str
    accepted_at: str


def email_delivery_enabled() -> bool:
    return bool(str(os.environ.get("EMAILIT_API_KEY") or "").strip())


def _force_fallback_sender() -> bool:
    return str(os.environ.get("EA_REGISTRATION_EMAIL_FORCE_FALLBACK") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _registration_sender_email() -> str:
    if _force_fallback_sender():
        forced = _fallback_sender_email()
        if forced:
            return forced
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
    if _force_fallback_sender():
        return _fallback_sender_name()
    configured = str(os.environ.get("EA_REGISTRATION_EMAIL_NAME") or "").strip()
    if configured:
        return configured
    fallback = str(os.environ.get("EA_EMAIL_DEFAULT_NAME") or "").strip()
    return fallback or DEFAULT_SENDER_NAME


def _fallback_sender_email() -> str:
    configured = str(os.environ.get("EA_REGISTRATION_EMAIL_FROM_FALLBACK") or "").strip()
    if configured:
        return configured
    fallback = str(os.environ.get("EA_EMAIL_DEFAULT_FROM") or "").strip()
    return fallback


def _fallback_sender_name() -> str:
    configured = str(os.environ.get("EA_REGISTRATION_EMAIL_NAME_FALLBACK") or "").strip()
    if configured:
        return configured
    fallback = str(os.environ.get("EA_EMAIL_DEFAULT_NAME") or "").strip()
    return fallback or _registration_sender_name()


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
    return "Verify your email for PropertyQuarry"


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
        "Use this verification code to create your PropertyQuarry workspace:\n\n"
        f"{verification_code}\n\n"
        "Or open this secure link:\n\n"
        f"{magic_link_url}\n\n"
        f"This link and code expire in about {minutes} minutes.\n\n"
        "Google is connected after sign-up as an identity and optional workspace data source for PropertyQuarry.\n\n"
        "If you did not request this email, you can ignore it.\n"
    )


def _meta_ref(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def _emailit_meta_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    except TypeError:
        return str(value).strip()


def _emailit_meta_payload(*, kind: str, recipient_email: str, meta: dict[str, object] | None = None) -> dict[str, str]:
    raw = {
        "kind": kind,
        "recipient_email": str(recipient_email or "").strip(),
        **dict(meta or {}),
    }
    payload: dict[str, str] = {}
    for key, value in raw.items():
        normalized_key = str(key or "").strip()[:80]
        if not normalized_key:
            continue
        normalized_value = _emailit_meta_value(value)
        if not normalized_value:
            continue
        payload[normalized_key] = normalized_value[:500]
    return payload


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


_EMAIL_LINK_STYLE = "color:#0b57d0;text-decoration:underline;"


def _html_escape(value: object) -> str:
    return html.escape(str(value or "").strip(), quote=True)


def _html_link(*, href: object, label: object) -> str:
    url = str(href or "").strip()
    text = str(label or "").strip() or url
    if not url:
        return _html_escape(text)
    return f'<a href="{_html_escape(url)}" style="{_EMAIL_LINK_STYLE}">{_html_escape(text)}</a>'


def _html_email_shell(*, title: str, body_html: str) -> str:
    return (
        '<!doctype html><html><body style="margin:0;padding:0;background:#f6f3ee;'
        'font-family:Arial,Helvetica,sans-serif;color:#191714;">'
        '<div style="max-width:760px;margin:0 auto;padding:24px;">'
        '<div style="border:1px solid #ded6c8;border-radius:10px;background:#fffdf8;padding:20px;">'
        f'<h1 style="margin:0 0 14px;font-size:22px;line-height:1.2;">{_html_escape(title)}</h1>'
        f"{body_html}"
        "</div></div></body></html>"
    )


def _property_email_facts(row: dict[str, object]) -> list[tuple[str, str]]:
    fact_specs = (
        ("Fit", row.get("fit_summary")),
        ("Source", row.get("source_label")),
        ("Price", row.get("price_label")),
        ("Area", row.get("area_label")),
        ("Rooms", row.get("rooms_label")),
        ("Location", row.get("location_label")),
        ("360", str(row.get("tour_status") or "").strip().replace("_", " ")),
    )
    facts: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for label, value in fact_specs:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        key = (label, normalized)
        if key in seen:
            continue
        seen.add(key)
        facts.append((label, normalized))
    return facts


def _property_search_results_ready_html(
    *,
    results_url: str,
    result_total: int,
    hosted_tour_total: int,
    property_rows: list[dict[str, object]],
) -> str:
    metric_table = (
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        'style="border-collapse:collapse;margin:0 0 16px;">'
        "<tr>"
        '<td style="padding:10px;border:1px solid #ded6c8;background:#fdf9f1;">'
        '<div style="font-size:12px;color:#6c675f;text-transform:uppercase;">Ranked results</div>'
        f'<strong style="font-size:18px;">{max(int(result_total), 0)}</strong>'
        "</td>"
        '<td style="padding:10px;border:1px solid #ded6c8;background:#fdf9f1;">'
        '<div style="font-size:12px;color:#6c675f;text-transform:uppercase;">Hosted tours ready</div>'
        f'<strong style="font-size:18px;">{max(int(hosted_tour_total), 0)}</strong>'
        "</td>"
        "</tr></table>"
    )
    rows_html: list[str] = []
    for index, row in enumerate(property_rows[:5], start=1):
        title = str(row.get("title") or "Property match").strip() or "Property match"
        review_url = str(row.get("review_url") or "").strip()
        tour_url = str(row.get("tour_url") or "").strip()
        property_url = str(row.get("property_url") or "").strip()
        primary_url = review_url or tour_url or property_url
        facts_html = "".join(
            "<tr>"
            f'<td style="padding:4px 8px 4px 0;color:#6c675f;font-size:12px;white-space:nowrap;">{_html_escape(label)}</td>'
            f'<td style="padding:4px 0;color:#191714;font-size:13px;">{_html_escape(value)}</td>'
            "</tr>"
            for label, value in _property_email_facts(row)
        ) or '<tr><td style="padding:4px 0;color:#6c675f;font-size:13px;" colspan="2">No structured facts captured.</td></tr>'
        action_links = [
            _html_link(href=review_url, label="Review packet") if review_url else "",
            _html_link(href=tour_url, label="Open 360") if tour_url else "",
            _html_link(href=property_url, label="Source") if property_url else "",
        ]
        action_html = " &nbsp; ".join(link for link in action_links if link) or _html_link(href=primary_url, label="Open")
        rows_html.append(
            "<tr>"
            f'<td style="width:38px;vertical-align:top;padding:12px;border-top:1px solid #ded6c8;color:#6c675f;">#{index}</td>'
            '<td style="vertical-align:top;padding:12px;border-top:1px solid #ded6c8;">'
            f'<div style="font-weight:700;margin-bottom:8px;">{_html_link(href=primary_url, label=title)}</div>'
            '<table role="presentation" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">'
            f"{facts_html}</table>"
            f'<div style="margin-top:10px;font-size:13px;">{action_html}</div>'
            "</td></tr>"
        )
    properties_table = ""
    if rows_html:
        properties_table = (
            '<h2 style="font-size:16px;margin:18px 0 8px;">Best matches</h2>'
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
            'style="border-collapse:collapse;border:1px solid #ded6c8;background:#fffefa;">'
            + "".join(rows_html)
            + "</table>"
        )
    results_link = (
        f'<p style="margin:18px 0 0;">{_html_link(href=results_url, label="Open full results")}</p>'
        if str(results_url or "").strip()
        else ""
    )
    return _html_email_shell(
        title="PropertyQuarry results are ready",
        body_html=(
            '<p style="margin:0 0 14px;color:#383633;">Your ranked shortlist is ready.</p>'
            f"{metric_table}{properties_table}{results_link}"
        ),
    )


def _property_match_html(
    *,
    title: str,
    provider: str,
    primary_link: str,
    review_url: str,
    tour_url: str,
    property_url: str,
    fit_summary: str,
    decision_summary: dict[str, object],
) -> str:
    good_fit_reasons = [str(value or "").strip() for value in list(decision_summary.get("good_fit_reasons") or []) if str(value or "").strip()]
    bad_fit_reasons = [str(value or "").strip() for value in list(decision_summary.get("bad_fit_reasons") or []) if str(value or "").strip()]
    unknowns = [str(value or "").strip() for value in list(decision_summary.get("unknowns") or []) if str(value or "").strip()]
    facts = [
        ("Source", provider),
        ("Fit", fit_summary),
        ("360", "ready" if tour_url else "pending"),
    ]
    facts_html = "".join(
        "<tr>"
        f'<td style="padding:6px 10px;color:#6c675f;font-size:12px;white-space:nowrap;border-bottom:1px solid #ded6c8;">{_html_escape(label)}</td>'
        f'<td style="padding:6px 10px;color:#191714;font-size:13px;border-bottom:1px solid #ded6c8;">{_html_escape(value)}</td>'
        "</tr>"
        for label, value in facts
        if str(value or "").strip()
    )
    links = [
        _html_link(href=review_url or primary_link, label="Review packet") if (review_url or primary_link) else "",
        _html_link(href=tour_url, label="Open 360") if tour_url else "",
        _html_link(href=property_url, label="Source") if property_url else "",
    ]
    reason_sections: list[str] = []
    for heading, values in (
        ("Why it stands out", good_fit_reasons[:4]),
        ("What may be weak", bad_fit_reasons[:3]),
        ("What still needs checking", unknowns[:3]),
    ):
        if not values:
            continue
        reason_sections.append(
            f'<h2 style="font-size:15px;margin:16px 0 6px;">{_html_escape(heading)}</h2>'
            "<ul style=\"margin:0;padding-left:20px;\">"
            + "".join(f'<li style="margin:4px 0;">{_html_escape(value)}</li>' for value in values)
            + "</ul>"
        )
    return _html_email_shell(
        title=f"Property match: {title}",
        body_html=(
            f'<p style="margin:0 0 12px;">{_html_link(href=primary_link, label=title)}</p>'
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
            'style="border-collapse:collapse;border:1px solid #ded6c8;background:#fffefa;">'
            f"{facts_html}</table>"
            f'<p style="margin:14px 0 0;">{" &nbsp; ".join(link for link in links if link)}</p>'
            + "".join(reason_sections)
        ),
    )


def _send_emailit_email(
    *,
    recipient_email: str,
    subject: str,
    text: str,
    html_body: str = "",
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
        "html": str(html_body or "").strip(),
        "reply_to": resolved_sender_email,
        "tracking": False,
        "meta": _emailit_meta_payload(kind=kind, recipient_email=recipient_email, meta=meta),
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
    def _request_for_payload(active_payload: dict[str, object], active_idempotency_key: str):
        return urllib.request.Request(
            EMAILIT_API_BASE,
            data=json.dumps(active_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Idempotency-Key": active_idempotency_key,
            },
            method="POST",
        )

    request = _request_for_payload(payload, idempotency_key)
    last_error = ""
    used_fallback_sender = False
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
            if exc.code == 422 and "Domain not verified" in detail and not used_fallback_sender:
                fallback_email = _fallback_sender_email()
                if fallback_email and fallback_email.lower() != resolved_sender_email.lower():
                    fallback_name = _fallback_sender_name()
                    payload["from"] = f"{fallback_name} <{fallback_email}>"
                    payload["reply_to"] = fallback_email
                    payload["meta"] = _emailit_meta_payload(
                        kind=kind,
                        recipient_email=recipient_email,
                        meta={
                            **dict(payload.get("meta") or {}),
                            "sender_fallback_used": True,
                            "preferred_sender_email": resolved_sender_email,
                            "fallback_sender_email": fallback_email,
                        },
                    )
                    fallback_seed = json.dumps(
                        {
                            "kind": kind,
                            "recipient_email": str(recipient_email or "").strip().lower(),
                            "subject": str(subject or "").strip(),
                            "meta": dict(payload.get("meta") or {}),
                            "sender_email": fallback_email.lower(),
                            "sender_name": fallback_name,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    request = _request_for_payload(
                        payload,
                        f"ea-mail-{hashlib.sha256(fallback_seed.encode('utf-8')).hexdigest()[:24]}",
                    )
                    used_fallback_sender = True
                    continue
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
    inviter = str(invited_by or "PropertyQuarry").strip() or "PropertyQuarry"
    note_text = str(note or "").strip()
    body = [
        "Hello,",
        "",
        f"{inviter} invited you to join a PropertyQuarry workspace as {role_label}.",
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
        subject=f"{inviter} invited you to PropertyQuarry",
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
    workspace_label = str(workspace_name or "PropertyQuarry workspace").strip() or "PropertyQuarry workspace"
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
    workspace_label = str(workspace_name or "PropertyQuarry workspace").strip() or "PropertyQuarry workspace"
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
    decision_summary_json: dict[str, object] | None = None,
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
    decision_summary = decision_summary_json if isinstance(decision_summary_json, dict) else {}
    good_fit_reasons = [str(value or "").strip() for value in list(decision_summary.get("good_fit_reasons") or []) if str(value or "").strip()]
    bad_fit_reasons = [str(value or "").strip() for value in list(decision_summary.get("bad_fit_reasons") or []) if str(value or "").strip()]
    unknowns = [str(value or "").strip() for value in list(decision_summary.get("unknowns") or []) if str(value or "").strip()]
    recommendation = str(decision_summary.get("recommendation") or "").strip().replace("_", " ")
    if recommendation:
        body.extend(["", f"Recommendation: {recommendation}"])
    if good_fit_reasons:
        body.extend(["", "Why it could fit:", *[f"- {entry}" for entry in good_fit_reasons[:3]]])
    if bad_fit_reasons:
        body.extend(["", "Why it may not fit:", *[f"- {entry}" for entry in bad_fit_reasons[:3]]])
    if unknowns:
        body.extend(["", "What still needs checking:", *[f"- {entry}" for entry in unknowns[:3]]])
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


def send_property_match_email(
    *,
    recipient_email: str,
    property_title: str,
    property_url: str,
    review_url: str = "",
    tour_url: str = "",
    provider_label: str = "",
    fit_summary: str = "",
    decision_summary_json: dict[str, object] | None = None,
    sender_email: str = "",
    sender_name: str = "",
) -> RegistrationEmailReceipt:
    title = str(property_title or "Property match").strip() or "Property match"
    provider = str(provider_label or "").strip()
    subject = f"Property match: {title}"
    primary_link = str(tour_url or review_url or property_url).strip()
    body = [
        "Hello,",
        "",
        f"EA shortlisted a property match: {title}",
    ]
    if provider:
        body.append(f"Source: {provider}")
    if fit_summary:
        body.extend(["", fit_summary])
    if primary_link:
        body.extend(["", f"Open the hosted review: {primary_link}"])
    if review_url and review_url != primary_link:
        body.append(f"Research page: {review_url}")
    if tour_url and tour_url not in {primary_link, review_url}:
        body.append(f"Hosted tour: {tour_url}")
    if property_url and property_url not in {primary_link, review_url, tour_url}:
        body.append(f"Original listing: {property_url}")
    decision_summary = decision_summary_json if isinstance(decision_summary_json, dict) else {}
    good_fit_reasons = [str(value or "").strip() for value in list(decision_summary.get("good_fit_reasons") or []) if str(value or "").strip()]
    bad_fit_reasons = [str(value or "").strip() for value in list(decision_summary.get("bad_fit_reasons") or []) if str(value or "").strip()]
    unknowns = [str(value or "").strip() for value in list(decision_summary.get("unknowns") or []) if str(value or "").strip()]
    if good_fit_reasons:
        body.extend(["", "Why it stands out:", *[f"- {entry}" for entry in good_fit_reasons[:4]]])
    if bad_fit_reasons:
        body.extend(["", "What may be weak:", *[f"- {entry}" for entry in bad_fit_reasons[:3]]])
    if unknowns:
        body.extend(["", "What still needs checking:", *[f"- {entry}" for entry in unknowns[:3]]])
    return _send_emailit_email(
        recipient_email=recipient_email,
        subject=subject[:220],
        text="\n".join(body).strip() + "\n",
        html_body=_property_match_html(
            title=title,
            provider=provider,
            primary_link=primary_link,
            review_url=review_url,
            tour_url=tour_url,
            property_url=property_url,
            fit_summary=fit_summary,
            decision_summary=decision_summary,
        ),
        kind="ea_property_match_delivery",
        meta={
            "review_ref": _meta_ref(review_url or primary_link),
            "tour_ref": _meta_ref(tour_url),
            "listing_ref": _meta_ref(property_url),
        },
        sender_email=sender_email,
        sender_name=sender_name,
    )


def send_property_market_ready_email(
    *,
    recipient_email: str,
    country_label: str,
    workspace_url: str,
    sender_email: str = "",
    sender_name: str = "",
) -> RegistrationEmailReceipt:
    label = str(country_label or "Requested market").strip() or "Requested market"
    review_url = str(workspace_url or "").strip()
    body = [
        "Hello,",
        "",
        f"Initialization for {label} is complete.",
        "",
        "Your market is now ready in PropertyQuarry. You can start the search now.",
    ]
    if review_url:
        body.extend(["", f"Open PropertyQuarry: {review_url}"])
    return _send_emailit_email(
        recipient_email=recipient_email,
        subject=f"PropertyQuarry market ready: {label}"[:220],
        text="\n".join(body).strip() + "\n",
        kind="ea_property_market_ready_delivery",
        meta={"market_label": label, "workspace_ref": _meta_ref(review_url)},
        sender_email=sender_email,
        sender_name=sender_name,
    )


def send_property_search_results_ready_email(
    *,
    recipient_email: str,
    results_url: str,
    result_total: int,
    hosted_tour_total: int,
    top_properties: list[dict[str, object]] | None = None,
    sender_email: str = "",
    sender_name: str = "",
) -> RegistrationEmailReceipt:
    property_rows = [dict(item) for item in list(top_properties or []) if isinstance(item, dict)]
    body = [
        "Hello,",
        "",
        "Your PropertyQuarry results are ready.",
        "",
        f"Ranked results: {max(int(result_total), 0)}",
        f"Hosted tours ready: {max(int(hosted_tour_total), 0)}",
    ]
    if property_rows:
        body.extend(["", "Best matches:"])
        for index, row in enumerate(property_rows[:5], start=1):
            title = str(row.get("title") or "Property match").strip() or "Property match"
            source = str(row.get("source_label") or "").strip()
            fit_summary = str(row.get("fit_summary") or "").strip()
            review_url = str(row.get("review_url") or "").strip()
            tour_status = str(row.get("tour_status") or "").strip().replace("_", " ") or (
                "ready" if str(row.get("tour_url") or "").strip() else "pending"
            )
            body.append(f"{index}. {title}")
            details = [part for part in (fit_summary, source, f"360: {tour_status}") if part]
            if details:
                body.append(f"   {' | '.join(details)}")
            if review_url:
                body.append(f"   Review packet: {review_url}")
    if str(results_url or "").strip():
        body.extend(["", f"Open the results page: {results_url}"])
    html_body = _property_search_results_ready_html(
        results_url=str(results_url or "").strip(),
        result_total=result_total,
        hosted_tour_total=hosted_tour_total,
        property_rows=property_rows,
    )
    return _send_emailit_email(
        recipient_email=recipient_email,
        subject="PropertyQuarry results ready"[:220],
        text="\n".join(body).strip() + "\n",
        html_body=html_body,
        kind="ea_property_search_results_ready_delivery",
        meta={
            "results_ref": _meta_ref(results_url),
            "top_property_refs": [
                _meta_ref(row.get("review_url") or row.get("tour_url") or row.get("property_url"))
                for row in property_rows[:5]
            ],
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
    label = str(headline or "PropertyQuarry update").strip() or "PropertyQuarry update"
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
    label = str(headline or "PropertyQuarry update").strip() or "PropertyQuarry update"
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
