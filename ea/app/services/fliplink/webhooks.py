from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field


_EMAIL_RE = re.compile(r"^[^@\s]{1,160}@[^@\s]{1,180}\.[^@\s]{2,40}$")
_ALLOWED_CUSTOM_FIELD_KEYS = frozenset(
    {
        "viewer_role",
        "reaction",
        "question",
        "intent",
        "property_ref",
        "packet_kind",
        "privacy_mode",
    }
)


def _text(value: object, limit: int = 500) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _email(value: object) -> str:
    normalized = _text(value, 320).lower()
    return normalized if _EMAIL_RE.match(normalized) else ""


def _email_hash(value: str) -> str:
    normalized = _email(value)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _email_mask(value: str) -> str:
    normalized = _email(value)
    if not normalized:
        return ""
    local, domain = normalized.split("@", 1)
    if len(local) <= 2:
        masked_local = local[:1] + "*"
    else:
        masked_local = local[:2] + "*" * min(5, max(3, len(local) - 2))
    return f"{masked_local}@{domain}"


def _custom_key(value: object) -> str:
    raw = _text(value, 80).lower()
    raw = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw)
    raw = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return raw[:80]


def safe_custom_fields(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    custom: dict[str, object] = {}
    redacted_keys: list[str] = []
    for key, raw_value in value.items():
        normalized_key = _custom_key(key)
        if (
            not normalized_key
            or normalized_key not in _ALLOWED_CUSTOM_FIELD_KEYS
            or isinstance(raw_value, (dict, list, tuple, set))
        ):
            if normalized_key:
                redacted_keys.append(normalized_key)
            continue
        custom[normalized_key] = _text(raw_value, 500)
    if redacted_keys:
        custom["custom_fields_extra_redacted"] = True
        custom["custom_fields_extra_count"] = len(redacted_keys)
        custom["custom_fields_extra_keys"] = sorted(set(redacted_keys))[:20]
    return custom


@dataclass(frozen=True)
class FlipLinkLeadWebhook:
    publication_id: str = ""
    fliplink_url: str = ""
    name: str = ""
    email: str = ""
    phone: str = ""
    company: str = ""
    job_title: str = ""
    custom_fields: dict[str, object] = field(default_factory=dict)

    @property
    def email_hash(self) -> str:
        return _email_hash(self.email)

    @property
    def email_masked(self) -> str:
        return _email_mask(self.email)

    def safe_payload(self) -> dict[str, object]:
        custom = safe_custom_fields(self.custom_fields)
        return {
            "publication_id": self.publication_id,
            "fliplink_url": self.fliplink_url,
            "name": self.name,
            "email_hash": self.email_hash,
            "email_masked": self.email_masked,
            "phone_present": bool(self.phone),
            "company": self.company,
            "job_title": self.job_title,
            "custom_fields": custom,
            "trust": "untrusted_external",
            "status": "pending_owner_review",
        }


def normalize_lead_webhook(payload: dict[str, object]) -> FlipLinkLeadWebhook:
    custom = payload.get("custom_fields") or payload.get("customFields") or {}
    if not isinstance(custom, dict):
        custom = {}
    merged_custom = dict(custom)
    for key in _ALLOWED_CUSTOM_FIELD_KEYS:
        if key not in merged_custom and key in payload:
            merged_custom[key] = payload.get(key)
    return FlipLinkLeadWebhook(
        publication_id=_text(payload.get("publication_id") or payload.get("publicationId") or merged_custom.get("publication_id"), 160),
        fliplink_url=_text(payload.get("fliplink_url") or payload.get("url") or payload.get("document_url") or merged_custom.get("fliplink_url"), 500),
        name=_text(payload.get("name") or payload.get("full_name") or payload.get("fullName"), 160),
        email=_email(payload.get("email") or payload.get("email_address") or payload.get("emailAddress")),
        phone=_text(payload.get("phone") or payload.get("phone_number") or payload.get("phoneNumber"), 80),
        company=_text(payload.get("company"), 160),
        job_title=_text(payload.get("job_title") or payload.get("jobTitle"), 160),
        custom_fields=merged_custom,
    )
