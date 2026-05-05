from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import yaml

from app.domain.models import ApprovalRequest, Commitment, DecisionWindow, DeadlineWindow, FollowUp, HumanTask, IntentSpecV3, Stakeholder, TaskExecutionRequest
from app.product.commercial import workspace_commercial_snapshot, workspace_plan_for_mode
from app.product.extractors import extract_commitment_candidates
from app.product.models import (
    BriefItem,
    CommitmentCandidate,
    CommitmentItem,
    DeadlineItem,
    DecisionItem,
    DecisionQueueItem,
    DraftCandidate,
    EvidenceItem,
    EvidenceRef,
    HandoffNote,
    HistoryEntry,
    PersonDetail,
    PersonProfile,
    ProductSnapshot,
    RuleItem,
    ThreadItem,
)
from app.product.projections import (
    commitment_item_from_commitment,
    commitment_item_from_follow_up,
    compact_text,
    contains_token,
    decision_item_from_window,
    due_bonus,
    evidence_items_from_objects,
    handoff_action_options,
    handoff_action_plan,
    handoff_from_human_task,
    priority_weight,
    rule_items_from_workspace,
    simulate_rule,
    status_open,
    thread_items_from_objects,
)
from app.services import google_oauth as google_oauth_service
from app.services.ltd_runtime_catalog import LtdRuntimeCatalogService
from app.services.ltd_runtime_skill_projection import projected_task_key
from app.services.registration_email import (
    delivery_sender_emails,
    email_delivery_enabled,
    send_channel_digest_email,
    send_google_connect_email,
    send_property_tour_email,
    send_workspace_access_email,
    send_workspace_invitation_email,
)
from app.settings import resolve_signing_secret

if TYPE_CHECKING:
    from app.container import AppContainer


_TEMPERATURE_BY_IMPORTANCE = {
    "critical": "hot",
    "high": "warm",
    "medium": "steady",
    "low": "cool",
}
_COMMITMENT_KEY_RE = re.compile(r"[^a-z0-9]+")
_READY_PROVIDER_STATES = {"ready", "healthy"}
_DEGRADED_PROVIDER_STATES = {"degraded", "cooldown", "rate_limited", "quarantined", "quota_low", "throttled"}
_FAILED_PROVIDER_STATES = {"error", "failed", "auth_failed", "revoked", "deleted", "expired", "unavailable", "missing"}
_SYSTEM_REPLY_SENDER_MARKERS = ("no-reply", "noreply", "donotreply", "do-not-reply", "mailer-daemon", "calendar-notification")
_REPLY_SIGNAL_CUES = ("reply", "respond", "send", "share", "confirm", "follow up", "follow-up", "let me know", "can you", "could you", "please", "need to", "must", "review")
_LOW_SIGNAL_GMAIL_LABELS = {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_FORUMS"}
_EA_DELIVERY_SUBJECT_MARKERS = (
    "morning memo digest",
    "executive assistant update",
    "verify your email for executive assistant",
    "invited you to executive assistant",
)
_EA_DELIVERY_TEXT_MARKERS = (
    "open this secure workspace view",
    "use this verification code to create your executive assistant workspace",
    "google is connected after sign-up as a workspace data source",
)
_WILLHABEN_HOST_MARKERS = ("willhaben.at",)
_PRODUCT_PULSE_FRESH_SECONDS = 48 * 3600
_PRODUCT_PULSE_STALE_SECONDS = 7 * 24 * 3600
_DEFAULT_DESIGN_PRODUCT_ROOT = Path("/docker/chummercomplete/chummer-design/products/chummer")
_POCKET_PUBLIC_API_BASE_URL = "https://public.heypocketai.com/api/v1"
_POCKET_API_MAX_ATTEMPTS = 4
_POCKET_API_RETRY_BACKOFF_SECONDS = 1.0
_POCKET_API_MAX_RETRY_BACKOFF_SECONDS = 5.0
_POCKET_SYNC_EVENT_LOOKBACK = 200
_POCKET_SIGNAL_DEDUPE_LOOKBACK = 2000
_POCKET_SYNC_MAX_SCAN_PAGES = 12
_POCKET_NON_ACTIONABLE_SUMMARY_MARKERS = (
    "no substantive discussion to summarize",
    "transcript contains no substantive discussion",
)
_POCKET_NON_ACTIONABLE_CONTEXT_MARKERS = (
    "adult and a child",
    "parent and a child",
    "father and his son",
    "mother and her son",
    "mother and her daughter",
    "playful",
    "role-playing",
    "role playing",
    "game rules",
    "mealtime",
    "meal preparation",
    "tooth brushing",
    "good night",
    "bedtime",
    "snack",
    "jam and yogurt",
    "make a cake",
    "leftover dough",
    "princess",
    "hedgehog",
    "grandmother",
    "noah",
    "family support",
    "parenting chat",
    "stroke recovery",
    "daily life discussion",
    "health update",
    "therapy session",
    "medical leave",
    "medical strategy",
    "recovering from a stroke",
    "chemo",
    "colonoscopy",
    "vocal performance",
    "rehearsal",
    "chant-like",
    "chanting",
    "phonetic patterns",
    "thank you for watching",
    "credits",
)
_POCKET_ACTIONABLE_MARKERS = (
    "send ",
    "share ",
    "reply ",
    "follow up",
    "follow-up",
    "confirm ",
    "review ",
    "approve ",
    "prepare ",
    "schedule ",
    "reschedule",
    "book ",
    "call ",
    "email ",
    "check in",
    "check ",
    "decide ",
    "decision",
    "deadline",
    "next step",
    "action item",
    "deliver ",
    "update ",
)
_EMAIL_APPROVAL_MARKERS = (
    "approval",
    "approve",
    "approved",
    "pending review",
    "review queue",
    "sign off",
    "sign-off",
    "signoff",
)
_EMAIL_DOCUMENTATION_MARKERS = (
    "documentation",
    "docs",
    "faq",
    "handbook",
    "help center",
    "knowledge base",
    "llms.txt",
    "manual",
    "playbook",
    "runbook",
)
_EMAIL_MARKUP_MARKERS = (
    "annotate",
    "board packet",
    "deck",
    "markup",
    "pdf",
    "proposal",
    "slide",
)
_EMAIL_IMAGE_BACKGROUND_MARKERS = (
    "background remove",
    "cut out",
    "remove the background",
    "transparent background",
)
_EMAIL_IMAGE_UPSCALE_MARKERS = (
    "higher resolution",
    "image upscale",
    "sharpen image",
    "upscale",
    "upscaled",
)
_EMAIL_IMAGE_GENERATION_MARKERS = (
    "banner",
    "hero image",
    "illustration",
    "mockup",
    "poster",
    "render",
    "thumbnail",
    "visual",
)
_EMAIL_PROPERTY_MARKERS = (
    "apartment",
    "floor plan",
    "floorplan",
    "immobilie",
    "listing",
    "property",
    "tour",
    "wohnung",
)
_EMAIL_DELIVERY_MARKERS = (
    "deliver",
    "delivery",
    "email link",
    "notify",
    "send the link",
    "share the link",
)
_EMAIL_DEADLINE_MARKERS = (
    "asap",
    "by eod",
    "deadline",
    "this afternoon",
    "this evening",
    "today",
    "tomorrow",
    "urgent",
)
_URL_TEXT_RE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_past_due(value: str | None) -> bool:
    when = _parse_iso(value)
    if when is None:
        return False
    return when <= datetime.now(timezone.utc)


def _hours_since(value: str | None) -> int:
    when = _parse_iso(value)
    if when is None:
        return 0
    return max(int((datetime.now(timezone.utc) - when).total_seconds() // 3600), 0)


def _memo_issue_reason(*, reason: str = "", error: str = "") -> str:
    normalized_error = str(error or "").strip()
    normalized_reason = str(reason or "").strip().lower()
    if normalized_error:
        if "domain not verified" in normalized_error.lower():
            return "Domain not verified"
        detail = normalized_error
        if normalized_error.startswith("registration_email_send_failed:"):
            detail = normalized_error.split(":", 2)[-1]
        if detail.startswith("{") and detail.endswith("}"):
            try:
                parsed = json.loads(detail)
            except Exception:
                parsed = {}
            extracted = str(parsed.get("error") or "").strip()
            if extracted:
                return extracted
        return compact_text(normalized_error, fallback="Memo delivery failed.", limit=160)
    if normalized_reason == "quiet_hours":
        return "Blocked by quiet hours"
    if normalized_reason == "recipient_missing":
        return "Recipient email missing"
    if normalized_reason == "email_delivery_not_configured":
        return "Email delivery is not configured"
    if normalized_reason == "unsupported_delivery_channel":
        return "Delivery channel is unsupported"
    if normalized_reason == "digest_not_available":
        return "Memo digest was not available"
    return compact_text(normalized_reason.replace("_", " "), fallback="", limit=160)


def _memo_issue_fix(*, reason: str = "", error: str = "") -> tuple[str, str]:
    normalized_reason = str(reason or "").strip().lower()
    normalized_error = str(error or "").strip().lower()
    if "google_" in normalized_reason or "google_" in normalized_error:
        return "/app/settings/google", "Open Google settings"
    if "domain not verified" in normalized_error or normalized_reason in {"email_delivery_not_configured", "unsupported_delivery_channel"}:
        return "/app/settings/support", "Open support"
    if normalized_reason in {"recipient_missing", "quiet_hours"}:
        return "/app/settings", "Open memo settings"
    return "/app/settings/outcomes", "Open outcomes"


def _memo_issue_fix_detail(*, reason: str = "", error: str = "") -> str:
    normalized_reason = str(reason or "").strip().lower()
    normalized_error = str(error or "").strip().lower()
    if "google_" in normalized_reason or "google_" in normalized_error:
        return "Reconnect Google before the next sync or approved send."
    if "domain not verified" in normalized_error:
        return "Verify the sending domain in the email provider before the next memo cycle."
    if normalized_reason == "email_delivery_not_configured":
        return "Configure outbound email delivery before the next memo cycle."
    if normalized_reason == "unsupported_delivery_channel":
        return "Use a supported delivery channel for memo email delivery."
    if normalized_reason == "recipient_missing":
        return "Set the memo recipient in morning memo settings."
    if normalized_reason == "quiet_hours":
        return "Adjust quiet hours or wait for the allowed delivery window."
    if normalized_reason == "digest_not_available":
        return "Regenerate the memo after the workspace loop refreshes."
    return ""


def _is_assistant_originated_delivery_email(*, title: str, summary: str, payload: dict[str, object] | None) -> bool:
    payload_json = dict(payload or {})
    from_email = str(payload_json.get("from_email") or "").strip().lower()
    if not from_email or from_email not in set(delivery_sender_emails()):
        return False
    normalized_title = str(title or "").strip().lower()
    normalized_summary = str(summary or "").strip().lower()
    snippet = str(payload_json.get("snippet") or "").strip().lower()
    if any(marker in normalized_title for marker in _EA_DELIVERY_SUBJECT_MARKERS):
        return True
    haystack = " ".join(part for part in (normalized_summary, snippet) if part).strip()
    return any(marker in haystack for marker in _EA_DELIVERY_TEXT_MARKERS)


def _is_willhaben_search_agent_email(
    *,
    title: str,
    summary: str,
    counterparty: str,
    payload: dict[str, object] | None,
) -> bool:
    payload_json = dict(payload or {})
    from_email = str(payload_json.get("from_email") or "").strip().lower()
    from_name = str(payload_json.get("from_name") or "").strip().lower()
    normalized_counterparty = str(counterparty or "").strip().lower()
    normalized_title = str(title or "").strip().lower()
    normalized_summary = str(summary or "").strip().lower()
    if "agent.willhaben.at" not in from_email:
        return False
    if "suchagent" not in " ".join(part for part in (from_name, normalized_counterparty, normalized_title) if part):
        return False
    if "neue anzeige" in normalized_title or "neue anzeigen" in normalized_title:
        return True
    return "neue anzeige" in normalized_summary or "neue anzeigen" in normalized_summary


def _env_flag(name: str, default: bool = False) -> bool:
    normalized = str(os.getenv(name) or "").strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on", "y"}:
        return True
    if normalized in {"0", "false", "no", "off", "n"}:
        return False
    return default


def _willhaben_search_agent_auto_create_enabled() -> bool:
    return _env_flag("EA_WILLHABEN_SEARCH_AGENT_AUTO_CREATE_PROPERTY_TOUR", default=False)


def _willhaben_property_tour_default_recipient_email() -> str:
    normalized = str(os.getenv("EA_WILLHABEN_PROPERTY_TOUR_DEFAULT_RECIPIENT_EMAIL") or "").strip().lower()
    return normalized if "@" in normalized else ""


def _willhaben_property_tour_recipient_map() -> dict[str, str]:
    raw = str(os.getenv("EA_WILLHABEN_PROPERTY_TOUR_RECIPIENT_MAP_JSON") or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    result: dict[str, str] = {}
    for key, value in payload.items():
        normalized_key = str(key or "").strip().lower()
        normalized_value = str(value or "").strip().lower()
        if normalized_key and "@" in normalized_value:
            result[normalized_key] = normalized_value
    return result


def _willhaben_property_tour_recipient_for_account_email(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return ""
    return str(_willhaben_property_tour_recipient_map().get(normalized) or "").strip().lower()


def _willhaben_property_url_from_signal(
    *,
    title: str,
    summary: str,
    text: str,
    source_ref: str,
    external_id: str,
    payload: dict[str, object],
) -> str:
    all_urls: list[str] = []
    seen: set[str] = set()
    for value in (
        *(
            _extract_urls_from_text(title)
            + _extract_urls_from_text(summary)
            + _extract_urls_from_text(text)
            + _extract_urls_from_text(source_ref)
            + _extract_urls_from_text(external_id)
            + _extract_urls_from_text(payload.get("snippet"))
            + _extract_urls_from_text(payload.get("body_text_excerpt"))
        ),
        str(payload.get("property_url") or "").strip(),
        str(payload.get("captured_url") or "").strip(),
        str(payload.get("url") or "").strip(),
        str(payload.get("href") or "").strip(),
    ):
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        all_urls.append(normalized)
    return next((value for value in all_urls if _is_willhaben_property_url(value)), "")


def _willhaben_search_agent_auto_create_spec(
    *,
    principal_id: str,
    title: str,
    summary: str,
    text: str,
    source_ref: str,
    external_id: str,
    counterparty: str,
    payload: dict[str, object],
) -> dict[str, str] | None:
    if not _willhaben_search_agent_auto_create_enabled():
        return None
    if not _is_willhaben_search_agent_email(
        title=title,
        summary=summary,
        counterparty=counterparty,
        payload=payload,
    ):
        return None
    property_url = _willhaben_property_url_from_signal(
        title=title,
        summary=summary,
        text=text,
        source_ref=source_ref,
        external_id=external_id,
        payload=payload,
    )
    if not property_url:
        return None
    recipient_email = _first_non_empty_text(
        payload.get("delivery_recipient_email"),
        payload.get("recipient_email"),
        payload.get("notify_email"),
        _willhaben_property_tour_recipient_for_account_email(payload.get("account_email")),
        _willhaben_property_tour_recipient_for_account_email(payload.get("google_account_email")),
        _willhaben_property_tour_default_recipient_email(),
        _principal_email_hint(principal_id),
    ).lower()
    return {
        "property_url": property_url,
        "recipient_email": recipient_email,
    }


def _property_alert_review_brief(title: str) -> str:
    normalized_title = compact_text(str(title or "").strip(), fallback="apartment alert", limit=88)
    return f"Review apartment alert: {normalized_title}"


def _memo_issue_channel_item(*, memo_loop: dict[str, object]) -> dict[str, str] | None:
    issue_reason = str(memo_loop.get("last_issue_reason") or "").strip()
    if not issue_reason:
        return None
    fix_href = str(memo_loop.get("last_issue_fix_href") or "/app/settings/outcomes").strip() or "/app/settings/outcomes"
    fix_label = str(memo_loop.get("last_issue_fix_label") or "Open outcomes").strip() or "Open outcomes"
    fix_detail = str(memo_loop.get("last_issue_fix_detail") or "").strip()
    detail = " ".join(
        part
        for part in (
            issue_reason.rstrip(".") + ".",
            fix_detail,
        )
        if str(part or "").strip()
    ).strip()
    return {
        "title": "Fix memo delivery blocker",
        "detail": detail or issue_reason,
        "tag": "Memo",
        "href": fix_href,
        "action_href": fix_href,
        "action_label": fix_label,
        "action_method": "get",
    }


def _action_label(action_json: dict[str, object]) -> str:
    raw = str(action_json.get("intent") or action_json.get("label") or action_json.get("action") or action_json.get("event_type") or "review").strip().replace("_", " ").replace(".", " ")
    return raw or "review"


def _gmail_resource_id(value: object, *, prefix: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if normalized.startswith(prefix):
        return normalized.split(":", 1)[1].strip()
    return normalized


def _search_tokens(value: str) -> tuple[str, ...]:
    normalized = _COMMITMENT_KEY_RE.sub(" ", str(value or "").strip().lower()).strip()
    if not normalized:
        return ()
    return tuple(part for part in normalized.split() if part)


def _person_key(value: str) -> str:
    return " ".join(_search_tokens(value))


def _search_score(*, tokens: tuple[str, ...], title: str = "", summary: str = "", extra: tuple[str, ...] = ()) -> float:
    if not tokens:
        return 0.0
    title_text = str(title or "").strip().lower()
    summary_text = str(summary or "").strip().lower()
    extra_text = " ".join(str(part or "").strip().lower() for part in extra if str(part or "").strip())
    score = 0.0
    full_query = " ".join(tokens)
    if full_query and title_text and full_query in title_text:
        score += 8.0
    if full_query and summary_text and full_query in summary_text:
        score += 4.0
    for token in tokens:
        if token in title_text:
            score += 5.0
        if token in summary_text:
            score += 3.0
        if extra_text and token in extra_text:
            score += 2.0
    return score


def _looks_like_url(value: object) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized.startswith("https://") or normalized.startswith("http://")


def _extract_urls_from_text(value: object) -> tuple[str, ...]:
    rows: list[str] = []
    seen: set[str] = set()
    for raw in _URL_TEXT_RE.findall(str(value or "")):
        normalized = str(raw or "").strip().rstrip(").,;]>")
        if normalized and normalized not in seen:
            seen.add(normalized)
            rows.append(normalized)
    return tuple(rows)


def _normalized_ltd_lookup(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _contains_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    normalized = str(text or "").strip().lower()
    return any(str(marker or "").strip().lower() in normalized for marker in markers if str(marker or "").strip())


def _saved_link_fallback_id(url_text: str) -> str:
    normalized = str(url_text or "").strip()
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _saved_link_tag_summary(value: object) -> str:
    if isinstance(value, str):
        return ", ".join(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, dict):
        names: list[str] = []
        for key, nested in value.items():
            nested_name = _first_non_empty_text(
                nested.get("tag") if isinstance(nested, dict) else "",
                nested.get("name") if isinstance(nested, dict) else "",
                key,
            )
            if nested_name:
                names.append(nested_name)
        return ", ".join(names)
    if isinstance(value, (list, tuple, set)):
        names: list[str] = []
        for nested in value:
            if isinstance(nested, dict):
                nested_name = _first_non_empty_text(nested.get("tag"), nested.get("name"), nested.get("label"))
                if nested_name:
                    names.append(nested_name)
            else:
                normalized = str(nested or "").strip()
                if normalized:
                    names.append(normalized)
        return ", ".join(names)
    return ""


def _saved_link_reference_at(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if normalized.isdigit():
        try:
            epoch = int(normalized)
            if epoch > 10_000_000_000:
                epoch //= 1000
            return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
        except Exception:
            return ""
    parsed = _parse_iso(normalized)
    return parsed.isoformat() if parsed is not None else ""


class _SavedLinkHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, object]] = []
        self._current_attrs: dict[str, str] | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        self._current_attrs = {str(key or "").strip().lower(): str(value or "").strip() for key, value in attrs}
        self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_attrs is not None and data:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._current_attrs is None:
            return
        item = dict(self._current_attrs)
        title = " ".join(part.strip() for part in self._current_text if part.strip()).strip()
        if title:
            item["title"] = title
        self.items.append(item)
        self._current_attrs = None
        self._current_text = []


def _saved_link_archive_entries_from_json(payload: object) -> tuple[dict[str, object], ...]:
    if isinstance(payload, dict):
        for key in ("items", "list", "bookmarks", "saved_links", "links"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return tuple(item for item in nested if isinstance(item, (dict, str)))
        if any(_looks_like_url(payload.get(key)) for key in ("url", "href", "resolved_url", "given_url")):
            return (payload,)
        dict_values = [item for item in payload.values() if isinstance(item, dict)]
        if dict_values:
            return tuple(dict_values)
        return ()
    if isinstance(payload, list):
        return tuple(item for item in payload if isinstance(item, (dict, str)))
    return ()


def _saved_link_archive_entries_from_csv(text: str) -> tuple[dict[str, object], ...]:
    reader = csv.DictReader(text.splitlines())
    rows: list[dict[str, object]] = []
    for row in reader:
        normalized = {str(key or "").strip(): value for key, value in dict(row).items()}
        if any(_looks_like_url(normalized.get(key)) for key in ("url", "href", "resolved_url", "given_url")):
            rows.append(normalized)
    return tuple(rows)


def _saved_link_archive_entries_from_html(text: str) -> tuple[dict[str, object], ...]:
    parser = _SavedLinkHTMLParser()
    parser.feed(text)
    return tuple(
        item
        for item in parser.items
        if any(_looks_like_url(item.get(key)) for key in ("href", "url"))
    )


def _decode_saved_link_archive_bytes(raw_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


def _saved_link_archive_format_name(suffix: str) -> str:
    normalized = str(suffix or "").strip().lower()
    if normalized == ".htm":
        return "html"
    return normalized.lstrip(".")


def _saved_link_archive_sources(path: Path) -> tuple[dict[str, object], ...]:
    suffix = path.suffix.lower()
    if suffix == ".zip":
        sources: list[dict[str, object]] = []
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                member_suffix = Path(info.filename).suffix.lower()
                if member_suffix not in {".json", ".csv", ".html", ".htm"}:
                    continue
                sources.append(
                    {
                        "name": info.filename,
                        "format": _saved_link_archive_format_name(member_suffix),
                        "text": _decode_saved_link_archive_bytes(archive.read(info.filename)),
                    }
                )
        return tuple(sources)
    if suffix not in {".json", ".csv", ".html", ".htm"}:
        return ()
    return (
        {
            "name": path.name,
            "format": _saved_link_archive_format_name(suffix),
            "text": _decode_saved_link_archive_bytes(path.read_bytes()),
        },
    )


def _saved_link_import_records_from_source(source: dict[str, object]) -> tuple[dict[str, object], ...]:
    format_name = str(source.get("format") or "").strip().lower()
    text = str(source.get("text") or "")
    if format_name == "json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return ()
        rows = _saved_link_archive_entries_from_json(payload)
    elif format_name == "csv":
        rows = _saved_link_archive_entries_from_csv(text)
    elif format_name == "html":
        rows = _saved_link_archive_entries_from_html(text)
    else:
        rows = ()
    records: list[dict[str, object]] = []
    for row in rows:
        if isinstance(row, str):
            row = {"url": row}
        if not isinstance(row, dict):
            continue
        url_text = _first_non_empty_text(row.get("url"), row.get("href"), row.get("resolved_url"), row.get("given_url"))
        if not _looks_like_url(url_text):
            continue
        title_text = _first_non_empty_text(
            row.get("title"),
            row.get("resolved_title"),
            row.get("given_title"),
            row.get("name"),
            url_text,
        )
        summary_text = _first_non_empty_text(
            row.get("excerpt"),
            row.get("summary"),
            row.get("description"),
            row.get("note"),
            row.get("preview"),
        )
        tags_text = _saved_link_tag_summary(row.get("tags"))
        item_id = _first_non_empty_text(row.get("item_id"), row.get("itemId"), row.get("resolved_id"), row.get("id"))
        reference_at = _first_non_empty_text(
            _saved_link_reference_at(row.get("time_added")),
            _saved_link_reference_at(row.get("time_updated")),
            _saved_link_reference_at(row.get("added_at")),
            _saved_link_reference_at(row.get("created_at")),
        )
        records.append(
            {
                "url": url_text,
                "title": title_text,
                "summary": summary_text,
                "tags": tags_text,
                "item_id": item_id,
                "reference_at": reference_at,
                "payload": dict(row),
            }
        )
    return tuple(records)


def _pocket_api_key() -> str:
    configured = str(os.environ.get("POCKET_API_KEY") or "").strip()
    if not configured:
        raise RuntimeError("pocket_api_key_missing")
    return configured


def _pocket_api_request(
    path: str,
    *,
    method: str = "GET",
    query: dict[str, object] | None = None,
    body: dict[str, object] | None = None,
) -> dict[str, object]:
    base_url = str(os.environ.get("POCKET_PUBLIC_API_BASE_URL") or _POCKET_PUBLIC_API_BASE_URL).strip().rstrip("/")
    normalized_path = "/" + str(path or "").strip().lstrip("/")
    url = f"{base_url}{normalized_path}"
    if query:
        encoded_query = urllib.parse.urlencode(
            {key: value for key, value in dict(query).items() if value is not None and str(value).strip() != ""}
        )
        if encoded_query:
            url = f"{url}?{encoded_query}"
    data: bytes | None = None
    headers = {
        "Authorization": f"Bearer {_pocket_api_key()}",
        "Accept": "application/json",
    }
    normalized_method = str(method or "GET").strip().upper() or "GET"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=normalized_method)
    payload: dict[str, object] | None = None
    for attempt in range(1, _POCKET_API_MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise RuntimeError("pocket_recording_not_found") from exc
            detail = exc.read().decode("utf-8", "replace")
            if exc.code == 429 and attempt < _POCKET_API_MAX_ATTEMPTS:
                retry_after = str(exc.headers.get("Retry-After") or "").strip()
                try:
                    delay = float(retry_after) if retry_after else 0.0
                except Exception:
                    delay = 0.0
                if delay <= 0.0:
                    delay = min(
                        _POCKET_API_RETRY_BACKOFF_SECONDS * float(attempt),
                        _POCKET_API_MAX_RETRY_BACKOFF_SECONDS,
                    )
                time.sleep(max(0.0, delay))
                continue
            raise RuntimeError(f"pocket_api_http_{exc.code}:{detail[:200]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"pocket_api_unreachable:{exc.reason}") from exc
    if payload is None:
        raise RuntimeError("pocket_api_empty_response")
    if not isinstance(payload, dict):
        raise RuntimeError("pocket_api_invalid_payload")
    if payload.get("success") is False:
        raise RuntimeError(str(payload.get("error") or "pocket_api_request_failed"))
    return payload


def _pocket_list_recordings(*, limit: int, page: int = 1) -> dict[str, object]:
    return _pocket_api_request("/public/recordings", query={"limit": max(int(limit), 1), "page": max(int(page), 1)})


def _pocket_get_recording_details(recording_id: str) -> dict[str, object]:
    return _pocket_api_request(
        f"/public/recordings/{urllib.parse.quote(str(recording_id or '').strip(), safe='')}",
        query={"include_transcript": "true", "include_summarizations": "true"},
    )


def _pocket_get_audio_download_url(recording_id: str) -> dict[str, object]:
    return _pocket_api_request(
        f"/public/recordings/{urllib.parse.quote(str(recording_id or '').strip(), safe='')}/audio-url"
    )


def _pocket_summary_payload(summary_payload: object) -> tuple[str, str]:
    if not isinstance(summary_payload, dict):
        return "", ""
    if "id" in summary_payload or "summarizationId" in summary_payload:
        summary_id = _first_non_empty_text(summary_payload.get("id"), summary_payload.get("summarizationId"))
        markdown = _first_non_empty_text(
            (((summary_payload.get("v2") or {}) if isinstance(summary_payload.get("v2"), dict) else {}).get("summary") or {}).get("markdown")
            if isinstance((((summary_payload.get("v2") or {}) if isinstance(summary_payload.get("v2"), dict) else {}).get("summary") or {}), dict)
            else "",
            summary_payload.get("summary"),
        )
        return summary_id, markdown
    for key, nested in summary_payload.items():
        nested_id, nested_markdown = _pocket_summary_payload(nested)
        if nested_markdown:
            return nested_id or str(key or "").strip(), nested_markdown
    return "", ""


def _pocket_tags(recording_payload: dict[str, object]) -> list[str]:
    tags = recording_payload.get("tags")
    if isinstance(tags, list):
        return [str(item or "").strip() for item in tags if str(item or "").strip()]
    if isinstance(tags, dict):
        values: list[str] = []
        for key, value in tags.items():
            normalized = _first_non_empty_text(value.get("name") if isinstance(value, dict) else "", key)
            if normalized:
                values.append(normalized)
        return values
    return []


def _pocket_recording_projection(
    detail_payload: dict[str, object],
    *,
    audio_payload: dict[str, object] | None = None,
) -> dict[str, object]:
    transcript = dict(detail_payload.get("transcript") or {}) if isinstance(detail_payload.get("transcript"), dict) else {}
    transcript_segments = list(transcript.get("segments") or []) if isinstance(transcript.get("segments"), list) else []
    summary_id, summary_markdown = _pocket_summary_payload(detail_payload.get("summarizations"))
    audio = dict(audio_payload or {})
    return {
        "recording_id": str(detail_payload.get("id") or "").strip(),
        "title": str(detail_payload.get("title") or "").strip(),
        "state": str(detail_payload.get("state") or "").strip(),
        "duration": detail_payload.get("duration"),
        "language": str(detail_payload.get("language") or "").strip(),
        "recording_at": str(detail_payload.get("recording_at") or "").strip(),
        "created_at": str(detail_payload.get("created_at") or "").strip(),
        "updated_at": str(detail_payload.get("updated_at") or "").strip(),
        "tags": _pocket_tags(detail_payload),
        "transcript_text": str(transcript.get("text") or "").strip(),
        "transcript_segment_count": len(transcript_segments),
        "transcript_metadata": dict(transcript.get("metadata") or {}) if isinstance(transcript.get("metadata"), dict) else {},
        "summary_markdown": str(summary_markdown or "").strip(),
        "summary_id": str(summary_id or "").strip(),
        "audio_download_url": str(audio.get("signed_url") or audio.get("url") or "").strip(),
        "audio_expires_at": str(audio.get("expires_at") or "").strip(),
        "audio_expires_in": int(audio.get("expires_in")) if str(audio.get("expires_in") or "").strip().isdigit() else None,
    }


def _pocket_recording_effective_updated_at(payload: dict[str, object]) -> str:
    return _first_non_empty_text(payload.get("updated_at"), payload.get("recording_at"), payload.get("created_at"))


def _pocket_recording_cursor_tuple(*, recording_id: str, updated_at: str) -> tuple[datetime, str]:
    parsed = _parse_iso(updated_at) or datetime.min.replace(tzinfo=timezone.utc)
    return parsed, str(recording_id or "").strip()


def _pocket_recording_is_newer_than_cursor(payload: dict[str, object], *, cursor_updated_at: str, cursor_recording_id: str) -> bool:
    if not str(cursor_updated_at or "").strip() and not str(cursor_recording_id or "").strip():
        return True
    row_tuple = _pocket_recording_cursor_tuple(
        recording_id=str(payload.get("id") or "").strip(),
        updated_at=_pocket_recording_effective_updated_at(payload),
    )
    cursor_tuple = _pocket_recording_cursor_tuple(
        recording_id=cursor_recording_id,
        updated_at=cursor_updated_at,
    )
    return row_tuple > cursor_tuple


def _pocket_signal_text(title: str, *, summary_markdown: str, transcript_text: str) -> str:
    transcript_excerpt = compact_text(transcript_text, fallback="", limit=1200)
    preferred = summary_markdown if not any(marker in summary_markdown.lower() for marker in _POCKET_NON_ACTIONABLE_SUMMARY_MARKERS) else ""
    return compact_text(
        " ".join(part for part in (str(title or "").strip(), preferred.strip(), transcript_excerpt) if part),
        fallback=str(title or "").strip() or preferred.strip() or transcript_excerpt,
        limit=2400,
    )


def _pocket_should_stage_commitments(
    *,
    title: str,
    summary_markdown: str,
    transcript_text: str,
    tags: Sequence[str] | None = None,
) -> tuple[bool, str]:
    normalized_title = " ".join(str(title or "").lower().split())
    normalized_summary = " ".join(str(summary_markdown or "").lower().split())
    normalized_tags = " ".join(" ".join(str(tag or "").lower().split()) for tag in tuple(tags or ()))
    if any(marker in normalized_summary for marker in _POCKET_NON_ACTIONABLE_SUMMARY_MARKERS):
        return False, "non_substantive_summary"
    candidate_source = " ".join(
        part
        for part in (
            str(title or "").strip(),
            str(summary_markdown or "").strip(),
            compact_text(transcript_text, fallback="", limit=600),
            normalized_tags,
        )
        if part
    )
    normalized_source = " ".join(candidate_source.lower().split())
    if len(normalized_source) < 48:
        return False, "too_short"
    if any(marker in normalized_source for marker in _POCKET_NON_ACTIONABLE_CONTEXT_MARKERS):
        return False, "non_actionable_context"
    if any(marker in normalized_title for marker in _POCKET_NON_ACTIONABLE_CONTEXT_MARKERS):
        return False, "non_actionable_context"
    if not any(marker in normalized_source for marker in _POCKET_ACTIONABLE_MARKERS):
        return False, "no_action_marker"
    return True, ""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_repo_path(raw: str, *, default: Path) -> Path:
    normalized = str(raw or "").strip()
    if not normalized:
        return default
    candidate = Path(normalized).expanduser()
    if candidate.is_absolute():
        return candidate
    return (_repo_root() / candidate).resolve()


def _weekly_product_pulse_path() -> Path:
    return _resolve_repo_path(
        str(os.getenv("EA_WEEKLY_PRODUCT_PULSE_PATH") or "").strip(),
        default=_repo_root() / ".codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json",
    )


def _default_journey_gates_path() -> Path:
    return _resolve_repo_path(
        str(os.getenv("EA_JOURNEY_GATES_PATH") or "").strip(),
        default=Path("/docker/fleet/.codex-studio/published/JOURNEY_GATES.generated.json"),
    )


def _default_public_guide_manifest_path() -> Path:
    return _resolve_repo_path(
        str(os.getenv("EA_PUBLIC_GUIDE_MANIFEST_PATH") or "").strip(),
        default=Path("/docker/chummercomplete/Chummer6/manifest.generated.json"),
    )


def _is_willhaben_property_url(value: object) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    parsed = urllib.parse.urlparse(normalized)
    host = str(parsed.netloc or "").strip().lower()
    return bool(host) and any(marker in host for marker in _WILLHABEN_HOST_MARKERS)


def _configured_public_tour_hosts() -> tuple[str, ...]:
    hosts: list[str] = []
    for raw in (
        str(os.getenv("EA_PUBLIC_TOUR_BASE_URL") or "").strip(),
        str(os.getenv("EA_PUBLIC_APP_BASE_URL") or "").strip(),
    ):
        if not raw:
            continue
        parsed = urllib.parse.urlparse(raw if "://" in raw else f"https://{raw}")
        host = str(parsed.netloc or parsed.path or "").strip().lower()
        if host and host not in hosts:
            hosts.append(host)
    return tuple(hosts)


def _is_crezlo_tour_host(value: object) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    parsed = urllib.parse.urlparse(normalized if "://" in normalized else f"https://{normalized}")
    host = str(parsed.netloc or parsed.path or "").strip().lower()
    return "crezlo" in host


def _is_branded_public_tour_url(value: object) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    parsed = urllib.parse.urlparse(normalized if "://" in normalized else f"https://{normalized}")
    host = str(parsed.netloc or parsed.path or "").strip().lower()
    if not host:
        return False
    configured_hosts = _configured_public_tour_hosts()
    if configured_hosts:
        return host in configured_hosts
    return "/tours/" in normalized and not _is_crezlo_tour_host(normalized)


def _resolve_property_tour_urls(structured_output: dict[str, object]) -> tuple[str, str]:
    hosted_url = _first_non_empty_text(structured_output.get("hosted_url"))
    public_url = _first_non_empty_text(structured_output.get("public_url"))
    share_url = _first_non_empty_text(structured_output.get("share_url"))
    crezlo_public_url = _first_non_empty_text(structured_output.get("crezlo_public_url"))

    branded_tour_url = _first_non_empty_text(
        hosted_url,
        public_url if _is_branded_public_tour_url(public_url) else "",
        crezlo_public_url if _is_branded_public_tour_url(crezlo_public_url) else "",
        share_url if _is_branded_public_tour_url(share_url) else "",
    )
    vendor_tour_url = _first_non_empty_text(
        crezlo_public_url if _is_crezlo_tour_host(crezlo_public_url) else "",
        public_url if _is_crezlo_tour_host(public_url) else "",
        share_url if _is_crezlo_tour_host(share_url) else "",
    )
    if not branded_tour_url:
        branded_tour_url = _first_non_empty_text(public_url, share_url, crezlo_public_url)
    if not vendor_tour_url:
        vendor_tour_url = _first_non_empty_text(
            public_url if public_url != branded_tour_url else "",
            share_url if share_url != branded_tour_url else "",
            crezlo_public_url if crezlo_public_url != branded_tour_url else "",
        )
    return branded_tour_url, vendor_tour_url


def _willhaben_property_packet_script_path() -> Path:
    explicit = str(os.getenv("EA_WILLHABEN_PROPERTY_PACKET_SCRIPT") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    resolved = Path(__file__).resolve()
    for parent in resolved.parents:
        candidate = parent / "scripts" / "willhaben_property_packet.py"
        if candidate.exists():
            return candidate
    return (_repo_root() / "scripts" / "willhaben_property_packet.py").resolve()


def _load_json_dict(path: Path) -> dict[str, object]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return dict(loaded) if isinstance(loaded, dict) else {}


def _crezlo_property_tour_state_root() -> Path:
    explicit = str(os.getenv("EA_CREZLO_PROPERTY_TOUR_STATE_ROOT") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return Path("/docker/fleet/state/browseract_bootstrap/runtime")


def _crezlo_property_tour_bootstrap_metadata() -> dict[str, object]:
    root = _crezlo_property_tour_state_root()
    metadata: dict[str, object] = {}

    publish_result = _load_json_dict(root / "crezlo_property_tour_operator_publish" / "result.json")
    workflow_id = _first_non_empty_text(
        publish_result.get("workflow_id"),
        publish_result.get("browseract_crezlo_property_tour_workflow_id"),
        publish_result.get("crezlo_property_tour_workflow_id"),
    )
    if workflow_id:
        metadata["crezlo_property_tour_workflow_id"] = workflow_id
        metadata["browseract_crezlo_property_tour_workflow_id"] = workflow_id

    try:
        worker_inputs = sorted(
            root.glob("crezlo_property_tour_runs_*/*.worker_input.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        worker_inputs = []
    for candidate in worker_inputs:
        loaded = _load_json_dict(candidate)
        if not loaded:
            continue
        login_email = _first_non_empty_text(loaded.get("login_email"), loaded.get("crezlo_login_email"))
        login_password = _first_non_empty_text(loaded.get("login_password"), loaded.get("crezlo_login_password"))
        workspace_id = _first_non_empty_text(loaded.get("workspace_id"))
        workspace_domain = _first_non_empty_text(loaded.get("workspace_domain"))
        workspace_base_url = _first_non_empty_text(loaded.get("workspace_base_url"))
        workspace_tours_url = _first_non_empty_text(loaded.get("workspace_tours_url"))
        if login_email:
            metadata["crezlo_login_email"] = login_email
        if login_password:
            metadata["crezlo_login_password"] = login_password
        if workspace_id:
            metadata["crezlo_workspace_id"] = workspace_id
            metadata["browseract_crezlo_workspace_id"] = workspace_id
        if workspace_domain:
            metadata["crezlo_workspace_domain"] = workspace_domain
            metadata["browseract_crezlo_workspace_domain"] = workspace_domain
        if workspace_base_url:
            metadata["crezlo_workspace_base_url"] = workspace_base_url
            metadata["browseract_crezlo_workspace_base_url"] = workspace_base_url
        if workspace_tours_url:
            metadata["crezlo_workspace_tours_url"] = workspace_tours_url
            metadata["browseract_crezlo_workspace_tours_url"] = workspace_tours_url
        break
    return metadata


def _load_willhaben_property_packet(property_url: str) -> dict[str, object]:
    normalized_url = urllib.parse.urldefrag(str(property_url or "").strip())[0]
    if not _is_willhaben_property_url(normalized_url):
        raise RuntimeError("willhaben_property_url_invalid")
    script_path = _willhaben_property_packet_script_path()
    if not script_path.exists():
        raise RuntimeError(f"willhaben_property_packet_script_missing:{script_path}")
    try:
        completed = subprocess.run(
            ["python3", str(script_path), normalized_url],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("python3_missing:willhaben_property_packet") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("willhaben_property_packet_timeout") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"willhaben_property_packet_failed:{detail[:400]}")
    try:
        payload = json.loads(str(completed.stdout or "").strip() or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError("willhaben_property_packet_invalid") from exc
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise RuntimeError("willhaben_property_packet_invalid")
    return dict(payload[0])


def _load_json_dict(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_yaml_dict(path: Path) -> dict[str, object] | None:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _design_product_root() -> Path:
    raw = str(os.getenv("CHUMMER6_DESIGN_PRODUCT_ROOT") or "").strip()
    if raw:
        return Path(raw)
    local_root = _repo_root() / ".codex-design/product"
    if local_root.exists():
        return local_root
    return _DEFAULT_DESIGN_PRODUCT_ROOT


def _design_source_path(key: str, fallback: str) -> Path:
    root = _design_product_root()
    manifest = _load_yaml_dict(root / "PUBLIC_GUIDE_EXPORT_MANIFEST.yaml") or {}
    sources = dict(manifest.get("sources") or {}) if isinstance(manifest.get("sources"), dict) else {}
    raw = str(sources.get(key) or "").strip()
    if raw.startswith("products/chummer/"):
        raw = raw[len("products/chummer/") :]
    relative = raw or fallback
    candidate = root / relative
    if candidate.exists():
        return candidate
    local_root = (_repo_root() / ".codex-design/product").resolve()
    try:
        root_resolved = root.resolve()
    except Exception:
        root_resolved = root
    if root_resolved == local_root and _DEFAULT_DESIGN_PRODUCT_ROOT.exists():
        fallback_candidate = _DEFAULT_DESIGN_PRODUCT_ROOT / relative
        if fallback_candidate.exists():
            return fallback_candidate
    return candidate


def _design_manifest_path(filename: str) -> Path:
    root = _design_product_root()
    candidate = root / filename
    if candidate.exists():
        return candidate
    local_root = (_repo_root() / ".codex-design/product").resolve()
    try:
        root_resolved = root.resolve()
    except Exception:
        root_resolved = root
    if root_resolved == local_root and _DEFAULT_DESIGN_PRODUCT_ROOT.exists():
        fallback_candidate = _DEFAULT_DESIGN_PRODUCT_ROOT / filename
        if fallback_candidate.exists():
            return fallback_candidate
    return candidate


def _design_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(entry).strip() for entry in value if str(entry).strip()]
    normalized = str(value or "").strip()
    return [normalized] if normalized else []


def _grounding_actions(rows: object) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    if not isinstance(rows, list):
        return actions
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip()
        href = str(row.get("href") or "").strip()
        if not label or not href:
            continue
        actions.append(
            {
                "label": label,
                "href": href,
                "method": str(row.get("method") or "get").strip().lower() or "get",
            }
        )
    return actions


def _grounding_source(*, label: str, path: Path | str, as_of: str = "") -> dict[str, str]:
    normalized_path = str(path or "").strip()
    payload = {"label": str(label or "").strip(), "path": normalized_path}
    if as_of:
        payload["as_of"] = str(as_of).strip()
    return payload


def _artifact_age_seconds(value: str | None) -> int | None:
    parsed = _parse_iso(value)
    if parsed is None:
        return None
    return max(int((_utcnow() - parsed).total_seconds()), 0)


def _path_mtime_iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return ""


def _freshness_state_from_age(age_seconds: int | None) -> str:
    if age_seconds is None:
        return "watch"
    if age_seconds <= _PRODUCT_PULSE_FRESH_SECONDS:
        return "fresh"
    if age_seconds <= _PRODUCT_PULSE_STALE_SECONDS:
        return "watch"
    return "stale"


def _freshness_label(state: str) -> str:
    return str(state or "watch").replace("_", " ")


def _journey_freshness_summary(payload: dict[str, object]) -> tuple[str, str]:
    freshness = dict(payload.get("artifact_freshness") or {})
    if not freshness:
        generated_at = str(payload.get("generated_at") or "").strip()
        state = _freshness_state_from_age(_artifact_age_seconds(generated_at))
        detail = (
            f"Published journey gates generated at {generated_at}."
            if generated_at
            else "Journey-gate freshness metadata is missing."
        )
        return state, detail
    severity = {"fresh": 0, "watch": 1, "stale": 2, "missing": 3}
    worst_state = "fresh"
    detail_parts: list[str] = []
    for key, value in freshness.items():
        item = dict(value or {}) if isinstance(value, dict) else {}
        available = bool(item.get("available"))
        raw_state = str(item.get("state") or "").strip().lower()
        state = "missing" if not available else raw_state or _freshness_state_from_age(int(item.get("age_seconds") or 0))
        if state not in severity:
            state = "watch"
        if severity[state] > severity[worst_state]:
            worst_state = state
        detail_parts.append(f"{str(key).replace('_', ' ')} {_freshness_label(state)}")
    return worst_state, "; ".join(detail_parts[:3])


def _public_guide_freshness_projection() -> dict[str, object]:
    severity = {"fresh": 0, "watch": 1, "stale": 2, "missing": 3}

    manifest_path = _default_public_guide_manifest_path()
    manifest_payload = _load_json_dict(manifest_path)
    if manifest_payload is not None:
        guide_root = manifest_path.parent
        required_files = ("README.md", "STATUS.md", "DOWNLOAD.md", "HELP.md", "FAQ.md", "CONTACT.md")
        required_dirs = ("PARTS", "HORIZONS", "TRUST", "assets")
        missing_items = [
            *[name for name in required_files if not (guide_root / name).is_file()],
            *[name for name in required_dirs if not (guide_root / name).is_dir()],
        ]
        generated_at = _path_mtime_iso(manifest_path)
        age_seconds = _artifact_age_seconds(generated_at)
        state = _freshness_state_from_age(age_seconds)
        manifest_status = str(manifest_payload.get("status") or "").strip().lower()
        if manifest_status and manifest_status != "ok":
            state = "watch" if severity.get(state, 1) < severity["watch"] else state
        if missing_items:
            state = "missing"
            missing_label = ", ".join(missing_items[:4])
            if len(missing_items) > 4:
                missing_label = f"{missing_label}, and {len(missing_items) - 4} more"
            detail = f"Public guide repo is incomplete on this host: missing {missing_label}."
        else:
            page_count = int(manifest_payload.get("page_count") or 0)
            active_wave = dict(manifest_payload.get("active_wave") or {})
            wave_title = str(active_wave.get("title") or "").strip()
            wave_status = str(active_wave.get("status") or "").strip().replace("_", " ")
            detail_parts = [
                f"Public guide mirror updated at {generated_at}." if generated_at else "Public guide mirror is available on this host.",
                f"{page_count} pages mirrored." if page_count else "",
                f"Wave {wave_title} is {wave_status}." if wave_title and wave_status else "",
                f"Manifest status: {manifest_status}." if manifest_status and manifest_status != "ok" else "",
            ]
            detail = " ".join(part for part in detail_parts if part)
        return {
            "origin": "downstream_public_guide",
            "state": state,
            "detail": compact_text(detail, fallback="Public-guide freshness is not available.", limit=220),
            "generated_at": generated_at,
            "path": str(manifest_path),
            "status": manifest_status or "ok",
        }

    export_manifest_path = _design_manifest_path("PUBLIC_GUIDE_EXPORT_MANIFEST.yaml")
    export_payload = _load_yaml_dict(export_manifest_path) or {}
    sources = dict(export_payload.get("sources") or {}) if isinstance(export_payload.get("sources"), dict) else {}
    mirrored_count = 0
    missing_sources: list[str] = []
    for key, raw_value in sources.items():
        normalized = str(raw_value or "").strip()
        fallback = normalized.removeprefix("products/chummer/") or normalized
        source_path = _design_source_path(str(key), fallback)
        if source_path.exists():
            mirrored_count += 1
        else:
            missing_sources.append(str(key))

    generated_at = _path_mtime_iso(export_manifest_path)
    age_seconds = _artifact_age_seconds(generated_at)
    state = _freshness_state_from_age(age_seconds)
    if severity.get(state, 1) < severity["watch"]:
        state = "watch"
    if not sources or mirrored_count == 0:
        state = "missing"

    missing_label = ", ".join(missing_sources[:3])
    if len(missing_sources) > 3:
        missing_label = f"{missing_label}, and {len(missing_sources) - 3} more"
    detail_parts = [
        "Downstream public guide manifest is not available on this host; using mirrored design export sources.",
        f"{mirrored_count}/{len(sources)} mapped public-guide sources are mirrored." if sources else "",
        f"Export manifest updated at {generated_at}." if generated_at else "",
        f"Missing source mappings: {missing_label}." if missing_label else "",
    ]
    return {
        "origin": "design_mirror_fallback",
        "state": state,
        "detail": compact_text(
            " ".join(part for part in detail_parts if part),
            fallback="Public-guide freshness is not available.",
            limit=220,
        ),
        "generated_at": generated_at,
        "path": str(export_manifest_path),
        "status": "fallback",
    }


def _journey_highlights(payload: dict[str, object]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for value in list(payload.get("journeys") or []):
        row = dict(value or {}) if isinstance(value, dict) else {}
        signals = dict(row.get("signals") or {})
        state = str(row.get("state") or "unknown").strip().lower()
        blocking_reasons = [str(item) for item in list(row.get("blocking_reasons") or []) if str(item).strip()]
        warning_reasons = [str(item) for item in list(row.get("warning_reasons") or []) if str(item).strip()]
        support_waiting = int(signals.get("support_closure_waiting_count") or 0)
        needs_human = int(signals.get("support_needs_human_response_count") or 0)
        candidates.append(
            {
                "id": str(row.get("id") or "").strip(),
                "title": str(row.get("title") or row.get("id") or "Journey").strip() or "Journey",
                "state": state or "unknown",
                "recommended_action": str(row.get("recommended_action") or "").strip(),
                "blocking_reasons": blocking_reasons[:2],
                "warning_reasons": warning_reasons[:2],
                "support_closure_waiting_count": support_waiting,
                "support_needs_human_response_count": needs_human,
            }
        )
    if not candidates:
        return []
    priority = {"blocked": 2, "warning": 1, "watch": 1, "ready": 0, "clear": 0}
    candidates.sort(
        key=lambda row: (
            -priority.get(str(row.get("state") or "").strip().lower(), 0),
            -int(row.get("support_closure_waiting_count") or 0),
            -int(row.get("support_needs_human_response_count") or 0),
            str(row.get("title") or ""),
        )
    )
    non_ready = [row for row in candidates if str(row.get("state") or "").strip().lower() not in {"ready", "clear"}]
    return non_ready[:3] if non_ready else candidates[:2]


def _support_fallout_projection(
    *,
    queue_health: dict[str, object],
    support_verification: dict[str, object],
    journey_highlights: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    highlight_rows = [dict(value) for value in list(journey_highlights or []) if isinstance(value, dict)]
    support_closures_waiting = sum(int(row.get("support_closure_waiting_count") or 0) for row in highlight_rows)
    support_human_responses = sum(int(row.get("support_needs_human_response_count") or 0) for row in highlight_rows)
    delivery_errors = int(queue_health.get("delivery_errors") or 0)
    retrying_delivery = int(queue_health.get("retrying_delivery") or 0)
    sla_breaches = int(queue_health.get("sla_breaches") or 0)
    verification_state = str(support_verification.get("state") or "not_requested").strip().lower() or "not_requested"
    verification_summary = compact_text(str(support_verification.get("summary") or "").strip(), fallback="", limit=180)
    verification_action = compact_text(str(support_verification.get("recommended_action") or "").strip(), fallback="", limit=180)

    if verification_state == "blocked" or delivery_errors or sla_breaches:
        state = "critical"
    elif (
        support_closures_waiting
        or support_human_responses
        or retrying_delivery
        or verification_state in {"sent", "opened", "waiting"}
    ):
        state = "watch"
    else:
        state = "clear"

    detail_parts = []
    if support_closures_waiting:
        detail_parts.append(f"{support_closures_waiting} support closures waiting")
    if support_human_responses:
        detail_parts.append(f"{support_human_responses} human responses needed")
    if delivery_errors:
        detail_parts.append(f"{delivery_errors} delivery errors in the queue")
    if retrying_delivery:
        detail_parts.append(f"{retrying_delivery} retrying deliveries")
    if verification_summary and verification_state in {"blocked", "sent", "opened", "waiting"}:
        detail_parts.append(verification_summary)

    detail = (
        " ".join(detail_parts)
        if detail_parts
        else "No active support fallout is blocking the release or public-guide posture."
    )

    recommended_action = verification_action
    if not recommended_action and state != "clear":
        recommended_action = (
            "Close support fallout before advancing the release and public-guide posture."
            if support_closures_waiting or support_human_responses
            else "Stabilize delivery and support confirmation before advancing the release and public-guide posture."
        )

    return {
        "state": state,
        "detail": compact_text(detail, fallback="Support fallout posture is not available.", limit=220),
        "recommended_action": compact_text(recommended_action, fallback="No support fallout action is recommended.", limit=220),
        "support_closures_waiting": support_closures_waiting,
        "support_human_responses": support_human_responses,
        "verification_state": verification_state,
    }


def _operator_id_from_email(value: str) -> str:
    normalized = str(value or "").strip().lower()
    local = normalized.split("@", 1)[0] if "@" in normalized else normalized
    slug = _COMMITMENT_KEY_RE.sub("-", local).strip("-")
    return f"operator-{slug or uuid4().hex[:6]}"


def _principal_email_hint(principal_id: str) -> str:
    normalized = str(principal_id or "").strip()
    if normalized.startswith("cf-email:"):
        candidate = normalized.partition(":")[2].strip().lower()
        if "@" in candidate:
            return candidate
    return ""


def _display_name_from_email(value: str) -> str:
    normalized = str(value or "").strip().lower()
    local = normalized.split("@", 1)[0] if "@" in normalized else normalized
    parts = [part for part in re.split(r"[._+-]+", local) if part]
    return " ".join(part[:1].upper() + part[1:] for part in parts)


def _counterparty_label(*, counterparty: str, email: str) -> str:
    normalized = str(counterparty or "").strip()
    return normalized or _display_name_from_email(email) or str(email or "").strip().lower()


def _first_name(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return normalized.split(" ", 1)[0].strip(" ,.:;")


def _trim_counterparty_suffix(value: str, *, counterparty: str) -> str:
    normalized = str(value or "").strip()
    target = str(counterparty or "").strip()
    if not normalized or not target:
        return normalized
    lowered = normalized.lower()
    variants = {target.lower()}
    if "@" in target:
        local = target.split("@", 1)[0].strip().lower()
        if local:
            variants.add(local)
            variants.add(" ".join(part for part in re.split(r"[._+-]+", local) if part))
    for variant in sorted((value for value in variants if value), key=len, reverse=True):
        for prefix in (f" to {variant}", f" for {variant}", f" with {variant}"):
            if lowered.endswith(prefix):
                return normalized[: -len(prefix)].strip(" .,:;")
    return normalized


def _reply_timing_phrase(value: str | None) -> str:
    when = _parse_iso(value)
    if when is None:
        return "shortly"
    target = when.astimezone(timezone.utc).date()
    today = _utcnow().date()
    if target == today:
        return "today"
    if target == today + timedelta(days=1):
        return "tomorrow"
    return f"by {target.isoformat()}"


def _sign_channel_payload(*, secret: str, payload: dict[str, object]) -> str:
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def _verify_channel_payload(*, secret: str, token: str) -> dict[str, object] | None:
    normalized = str(token or "").strip()
    if not normalized or "." not in normalized:
        return None
    payload_b64, signature = normalized.rsplit(".", 1)
    expected = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    padding = "=" * ((4 - len(payload_b64) % 4) % 4)
    try:
        payload_bytes = base64.urlsafe_b64decode(f"{payload_b64}{padding}".encode("ascii"))
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    expires_at = _parse_iso(str(payload.get("expires_at") or "").strip())
    if expires_at is not None and expires_at <= datetime.now(timezone.utc):
        return None
    return payload


def _first_non_empty_text(*values: object) -> str:
    for value in values:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""


def _tag_summary_text(value: object) -> str:
    if isinstance(value, dict):
        parts: list[str] = []
        for key, item in value.items():
            label = ""
            if isinstance(item, dict):
                label = _first_non_empty_text(item.get("tag"), item.get("label"), item.get("name"))
            if not label:
                label = str(key or "").strip()
            if label:
                parts.append(label)
        return ", ".join(parts)
    if isinstance(value, (list, tuple, set)):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(parts)
    return str(value or "").strip()


class ProductService:
    def __init__(self, container: AppContainer) -> None:
        self._container = container

    def _support_fix_verification_contact(
        self,
        *,
        principal_id: str,
    ) -> dict[str, str]:
        status = self._container.onboarding.status(principal_id=principal_id)
        workspace = dict(status.get("workspace") or {})
        delivery_preferences = dict(status.get("delivery_preferences") or {})
        morning_memo = dict(delivery_preferences.get("morning_memo") or {})
        google_accounts = google_oauth_service.list_google_accounts(container=self._container, principal_id=principal_id)
        primary_google_account = next(
            (
                account
                for account in google_accounts
                if str(account.binding.status or "").strip().lower() == "enabled"
                and str(account.token_status or "").strip().lower() != "revoked"
            ),
            google_accounts[0] if google_accounts else None,
        )
        recipient_email = str(
            morning_memo.get("resolved_recipient_email")
            or getattr(primary_google_account, "google_email", "")
            or ""
        ).strip().lower()
        display_name = str(workspace.get("name") or recipient_email or "Executive Workspace").strip()
        return {
            "recipient_email": recipient_email,
            "display_name": display_name,
            "role": "principal",
            "operator_id": "",
        }

    def _support_fix_verification_projection(
        self,
        *,
        principal_id: str,
        event_rows: tuple[object, ...] | None = None,
    ) -> dict[str, object]:
        rows = list(event_rows or ())
        if not rows:
            rows = [
                row
                for row in self._container.channel_runtime.list_recent_observations(limit=400, principal_id=principal_id)
                if str(row.channel or "").strip().lower() == "product"
            ]
        rows.sort(key=lambda row: (str(getattr(row, "created_at", "") or ""), str(getattr(row, "observation_id", "") or "")))
        contact = self._support_fix_verification_contact(principal_id=principal_id)
        recipient_email = str(contact.get("recipient_email") or "").strip().lower()
        request_row = next((row for row in reversed(rows) if str(getattr(row, "event_type", "") or "").strip() == "support_fix_verification_requested"), None)
        request_payload = dict(getattr(request_row, "payload", {}) or {}) if request_row is not None else {}
        request_id = str(request_payload.get("request_id") or getattr(request_row, "source_id", "") or "").strip()
        requested_at = str(getattr(request_row, "created_at", "") or request_payload.get("requested_at") or "").strip()
        if request_payload.get("recipient_email"):
            recipient_email = str(request_payload.get("recipient_email") or "").strip().lower()
        delivery_id = str(request_payload.get("delivery_id") or "").strip()
        access_session_id = str(request_payload.get("access_session_id") or "").strip()
        delivery_url = str(request_payload.get("delivery_url") or "").strip()
        access_url = str(request_payload.get("access_url") or "").strip()
        delivery_channel = str(request_payload.get("delivery_channel") or "").strip().lower()
        confirmed_row = next(
            (
                row
                for row in reversed(rows)
                if str(getattr(row, "event_type", "") or "").strip() == "support_fix_verification_confirmed"
                and str(dict(getattr(row, "payload", {}) or {}).get("request_id") or getattr(row, "source_id", "") or "").strip() == request_id
            ),
            None,
        )
        confirmed_at = str(getattr(confirmed_row, "created_at", "") or "").strip()
        delivery_opened = next(
            (
                row
                for row in reversed(rows)
                if str(getattr(row, "event_type", "") or "").strip() == "channel_digest_delivery_opened"
                and str(dict(getattr(row, "payload", {}) or {}).get("delivery_id") or getattr(row, "source_id", "") or "").strip() == delivery_id
            ),
            None,
        )
        delivery_sent = next(
            (
                row
                for row in reversed(rows)
                if str(getattr(row, "event_type", "") or "").strip() == "channel_digest_delivery_email_sent"
                and str(dict(getattr(row, "payload", {}) or {}).get("delivery_id") or getattr(row, "source_id", "") or "").strip() == delivery_id
            ),
            None,
        )
        delivery_failed = next(
            (
                row
                for row in reversed(rows)
                if str(getattr(row, "event_type", "") or "").strip() == "channel_digest_delivery_email_failed"
                and str(dict(getattr(row, "payload", {}) or {}).get("delivery_id") or getattr(row, "source_id", "") or "").strip() == delivery_id
            ),
            None,
        )
        access_opened = next(
            (
                row
                for row in reversed(rows)
                if str(getattr(row, "event_type", "") or "").strip() == "workspace_access_session_opened"
                and str(dict(getattr(row, "payload", {}) or {}).get("session_id") or getattr(row, "source_id", "") or "").strip() == access_session_id
            ),
            None,
        )
        channel_receipt_state = "not_requested"
        channel_receipt_detail = "No support verification link has been issued yet."
        if request_id:
            if delivery_opened is not None:
                channel_receipt_state = "received"
                channel_receipt_detail = "Recipient opened the support verification digest."
            elif delivery_failed is not None:
                failed_payload = dict(getattr(delivery_failed, "payload", {}) or {})
                channel_receipt_state = "failed"
                channel_receipt_detail = compact_text(
                    str(failed_payload.get("error") or "Support verification delivery failed.").strip(),
                    fallback="Support verification delivery failed.",
                    limit=180,
                )
            elif delivery_sent is not None or delivery_id:
                channel_receipt_state = "waiting"
                channel_receipt_detail = (
                    "Support verification email was sent and is waiting to be opened."
                    if delivery_channel == "email" and delivery_sent is not None
                    else "Support verification link was issued and is waiting to be opened."
                )
        install_receipt_state = "not_requested"
        install_receipt_detail = "No workspace install receipt has been requested yet."
        if request_id:
            if access_opened is not None:
                install_receipt_state = "opened"
                install_receipt_detail = "Recipient opened the workspace link attached to the verification request."
            elif access_session_id:
                install_receipt_state = "waiting"
                install_receipt_detail = "Workspace access link was issued and is waiting to be opened."
        confirmation_state = "not_requested"
        confirmation_detail = "No explicit confirmation has been requested yet."
        if request_id:
            if confirmed_at:
                confirmation_state = "confirmed"
                confirmation_detail = "Recipient explicitly confirmed the fix from the support verification link."
            else:
                confirmation_state = "waiting"
                confirmation_detail = "Waiting for the recipient to confirm the fix."
        state = "not_requested"
        summary = "No support verification request is active."
        if request_id and confirmed_at:
            state = "confirmed"
            summary = "Support verification is confirmed on the current channel."
        elif request_id and channel_receipt_state == "failed":
            state = "blocked"
            summary = "Support verification is blocked because the current channel delivery failed."
        elif request_id:
            state = "waiting"
            summary = "Support verification is waiting on receipt or explicit confirmation."
        elif not recipient_email:
            summary = "Support verification needs a recipient email before it can be requested."
        request_action_label = "Request confirmation" if recipient_email else "Recipient missing"
        if request_id and confirmation_state != "confirmed":
            request_action_label = "Reissue confirmation"
        recommended_action = (
            "Send a fresh support verification link and wait for channel receipt."
            if recipient_email and not request_id
            else "Set a memo recipient or connect Google before asking for support confirmation."
            if not recipient_email
            else "Open the current verification link or ask the recipient to confirm the fix."
            if state == "waiting"
            else "Use the support page to recover delivery before asking for confirmation again."
            if state == "blocked"
            else "Confirmation is already recorded."
        )
        confirm_action_href = (
            self.channel_action_href(
                principal_id=principal_id,
                object_kind="support_verification",
                object_ref=request_id,
                action="confirm",
                return_to="/app/channel-loop/memo",
                reason="Confirmed from support verification link.",
            )
            if request_id and confirmation_state != "confirmed"
            else ""
        )
        return {
            "state": state,
            "summary": summary,
            "recipient_email": recipient_email,
            "request_id": request_id,
            "requested_at": requested_at,
            "confirmed_at": confirmed_at,
            "delivery_channel": delivery_channel or ("email" if email_delivery_enabled() else "link_only"),
            "delivery_id": delivery_id,
            "delivery_url": delivery_url,
            "access_session_id": access_session_id,
            "access_url": access_url,
            "channel_receipt_state": channel_receipt_state,
            "channel_receipt_detail": channel_receipt_detail,
            "install_receipt_state": install_receipt_state,
            "install_receipt_detail": install_receipt_detail,
            "confirmation_state": confirmation_state,
            "confirmation_detail": confirmation_detail,
            "can_request": bool(recipient_email),
            "request_action_href": "/app/actions/support/fix-verification/request" if recipient_email else "",
            "request_action_method": "post",
            "request_action_label": request_action_label if recipient_email else "",
            "request_api_href": "/app/api/support/fix-verification/request" if recipient_email else "",
            "request_api_method": "post" if recipient_email else "",
            "recommended_action": recommended_action,
            "confirm_action_href": confirm_action_href,
            "display_name": str(contact.get("display_name") or "").strip(),
        }

    def request_support_fix_verification(
        self,
        *,
        principal_id: str,
        actor: str,
        base_url: str = "",
    ) -> dict[str, object]:
        contact = self._support_fix_verification_contact(principal_id=principal_id)
        recipient_email = str(contact.get("recipient_email") or "").strip().lower()
        if not recipient_email:
            raise ValueError("support_fix_verification_recipient_missing")
        delivery = self.issue_channel_digest_delivery(
            principal_id=principal_id,
            digest_key="memo",
            recipient_email=recipient_email,
            role=str(contact.get("role") or "principal").strip() or "principal",
            display_name=str(contact.get("display_name") or "").strip(),
            operator_id=str(contact.get("operator_id") or "").strip(),
            delivery_channel="email" if email_delivery_enabled() else "link_only",
            base_url=base_url,
        )
        if delivery is None:
            raise RuntimeError("support_fix_verification_delivery_not_available")
        request_id = f"support_verify_{uuid4().hex[:10]}"
        payload = {
            "request_id": request_id,
            "recipient_email": recipient_email,
            "delivery_channel": str(delivery.get("delivery_channel") or "").strip(),
            "delivery_id": str(delivery.get("delivery_id") or "").strip(),
            "delivery_url": str(delivery.get("delivery_url") or "").strip(),
            "access_session_id": str(delivery.get("access_session_id") or "").strip(),
            "access_url": str(delivery.get("access_url") or "").strip(),
            "requested_at": _now_iso(),
            "requested_by": str(actor or "").strip() or "support",
        }
        self._record_product_event(
            principal_id=principal_id,
            event_type="support_fix_verification_requested",
            payload=payload,
            source_id=request_id,
            dedupe_key=f"{principal_id}|{request_id}",
        )
        return payload

    def confirm_support_fix_verification(
        self,
        *,
        principal_id: str,
        request_id: str,
        actor: str,
    ) -> dict[str, object] | None:
        normalized_request_id = str(request_id or "").strip()
        if not normalized_request_id:
            return None
        payload = {
            "request_id": normalized_request_id,
            "confirmed_at": _now_iso(),
            "confirmed_by": str(actor or "").strip() or "support",
        }
        self._record_product_event(
            principal_id=principal_id,
            event_type="support_fix_verification_confirmed",
            payload=payload,
            source_id=normalized_request_id,
            dedupe_key=f"{principal_id}|{normalized_request_id}|confirmed",
        )
        return payload

    def _product_control_projection(self) -> dict[str, object]:
        pulse_path = _weekly_product_pulse_path()
        pulse_payload = _load_json_dict(pulse_path)
        pulse_generated_at = str((pulse_payload or {}).get("generated_at") or "").strip()
        pulse_age_seconds = _artifact_age_seconds(pulse_generated_at)
        pulse_freshness_state = "missing" if pulse_payload is None else _freshness_state_from_age(pulse_age_seconds)

        supporting_signals = dict((pulse_payload or {}).get("supporting_signals") or {})
        configured_journey_source = str(supporting_signals.get("journey_gate_source") or "").strip()
        journey_path = _resolve_repo_path(configured_journey_source, default=_default_journey_gates_path())
        journey_payload = _load_json_dict(journey_path)
        journey_generated_at = str((journey_payload or {}).get("generated_at") or "").strip()
        journey_summary = dict((journey_payload or {}).get("summary") or {})
        pulse_journey_health = dict((pulse_payload or {}).get("journey_gate_health") or {})
        journey_freshness_state = "missing"
        journey_freshness_detail = "Published journey gates are not available on this host."
        if journey_payload is not None:
            journey_freshness_state, journey_freshness_detail = _journey_freshness_summary(journey_payload)

        journey_state = (
            str(pulse_journey_health.get("state") or "").strip()
            or str(journey_summary.get("overall_state") or "").strip()
            or ("missing" if journey_payload is None else "watch")
        )
        journey_reason = (
            str(pulse_journey_health.get("reason") or "").strip()
            or str(journey_summary.get("recommended_action") or "").strip()
            or "Journey-gate posture is not available."
        )
        journey_highlights = _journey_highlights(journey_payload or {})
        governor_decision = next(
            (
                dict(value)
                for value in list((pulse_payload or {}).get("governor_decisions") or [])
                if isinstance(value, dict)
            ),
            {},
        )
        route_stewardship = dict(supporting_signals.get("provider_route_stewardship") or {})
        launch_readiness = str(supporting_signals.get("launch_readiness") or "").strip()
        public_guide_freshness = _public_guide_freshness_projection()
        summary = str((pulse_payload or {}).get("summary") or "").strip()
        if not summary:
            summary = str(journey_summary.get("recommended_action") or "").strip() or "Product-control pulse is not available."
        available = pulse_payload is not None or journey_payload is not None
        return {
            "available": available,
            "state": str(journey_state or "watch").strip().lower() or "watch",
            "summary": compact_text(summary, fallback="Product-control pulse is not available.", limit=220),
            "projection_note": "Mirrors weekly pulse, published journey gates, support fallout, and public-guide freshness; it does not replace design, Fleet, or Hub ownership.",
            "active_wave": str((pulse_payload or {}).get("active_wave") or "").strip(),
            "active_wave_status": str((pulse_payload or {}).get("active_wave_status") or "").strip(),
            "next_checkpoint_question": str((pulse_payload or {}).get("next_checkpoint_question") or "").strip(),
            "launch_readiness": launch_readiness,
            "provider_route_stewardship": {
                "default_status": str(route_stewardship.get("default_status") or "").strip(),
                "canary_status": str(route_stewardship.get("canary_status") or "").strip(),
                "review_due": str(route_stewardship.get("review_due") or "").strip(),
                "next_decision": str(route_stewardship.get("next_decision") or "").strip(),
            },
            "governor_decision": {
                "decision_id": str(governor_decision.get("decision_id") or "").strip(),
                "action": str(governor_decision.get("action") or "").strip(),
                "reason": compact_text(str(governor_decision.get("reason") or "").strip(), fallback="", limit=220),
            },
            "journey_gate_health": {
                "state": str(journey_state or "watch").strip().lower() or "watch",
                "reason": compact_text(journey_reason, fallback="Journey-gate posture is not available.", limit=220),
                "ready_count": int(journey_summary.get("ready_count") or 0),
                "warning_count": int(pulse_journey_health.get("warning_count") or journey_summary.get("warning_count") or 0),
                "blocked_count": int(pulse_journey_health.get("blocked_count") or journey_summary.get("blocked_count") or 0),
                "recommended_action": compact_text(
                    str(journey_summary.get("recommended_action") or journey_reason).strip(),
                    fallback="Journey-gate posture is not available.",
                    limit=220,
                ),
            },
            "journey_gate_freshness": {
                "state": journey_freshness_state,
                "detail": compact_text(journey_freshness_detail, fallback="Journey-gate freshness is not available.", limit=220),
                "generated_at": journey_generated_at,
            },
            "public_guide_freshness": public_guide_freshness,
            "pulse_freshness": {
                "state": pulse_freshness_state,
                "generated_at": pulse_generated_at,
                "age_seconds": pulse_age_seconds,
            },
            "journey_highlights": journey_highlights,
            "sources": {
                "pulse_path": str(pulse_path),
                "journey_gates_path": str(journey_path),
                "pulse_generated_at": pulse_generated_at,
                "journey_gates_generated_at": journey_generated_at,
                "public_guide_path": str(public_guide_freshness.get("path") or "").strip(),
                "public_guide_generated_at": str(public_guide_freshness.get("generated_at") or "").strip(),
            },
        }

    def _public_help_grounding_pack(self, *, product_control: dict[str, object] | None = None) -> dict[str, object]:
        trust_path = _design_source_path("public_trust_content", "PUBLIC_TRUST_CONTENT.yaml")
        release_path = _design_source_path("public_release_experience", "PUBLIC_RELEASE_EXPERIENCE.yaml")
        trust_payload = _load_yaml_dict(trust_path) or {}
        release_payload = _load_yaml_dict(release_path) or {}
        help_page = next(
            (
                dict(value)
                for value in list(trust_payload.get("trust_pages") or [])
                if isinstance(value, dict) and str(value.get("id") or "").strip() == "help"
            ),
            {},
        )
        launch_readiness = str(dict(product_control or {}).get("launch_readiness") or "").strip()
        summary_parts = [
            str(help_page.get("intro") or "").strip(),
            str(release_payload.get("release_notes_summary") or "").strip(),
        ]
        bullets = _design_string_list(help_page.get("summary_points"))[:3]
        update_posture = compact_text(str(release_payload.get("update_posture_summary") or "").strip(), fallback="", limit=180)
        if update_posture:
            bullets.append(update_posture)
        if launch_readiness:
            bullets.append(f"Current launch posture: {launch_readiness}")
        actions = _grounding_actions(help_page.get("actions"))
        install_help_label = str(release_payload.get("install_help_label") or "").strip()
        install_help_href = str(release_payload.get("install_help_href") or "").strip()
        if install_help_label and install_help_href and all(str(item.get("href") or "").strip() != install_help_href for item in actions):
            actions.append({"label": install_help_label, "href": install_help_href, "method": "get"})
        return {
            "id": "public_help",
            "title": str(help_page.get("heading") or "Get help without guessing").strip() or "Get help without guessing",
            "summary": compact_text(
                " ".join(part for part in summary_parts if part),
                fallback="Use the first-party help path before deeper technical material.",
                limit=220,
            ),
            "bullets": bullets[:5],
            "actions": actions[:4],
            "sources": [
                _grounding_source(
                    label="PUBLIC_TRUST_CONTENT.yaml",
                    path=trust_path,
                    as_of=str(help_page.get("updated_date") or trust_payload.get("version") or "").strip(),
                ),
                _grounding_source(
                    label="PUBLIC_RELEASE_EXPERIENCE.yaml",
                    path=release_path,
                    as_of=str(release_payload.get("version") or "").strip(),
                ),
            ],
        }

    def _support_assistant_grounding_pack(self, *, diagnostics: dict[str, object]) -> dict[str, object]:
        trust_path = _design_source_path("public_trust_content", "PUBLIC_TRUST_CONTENT.yaml")
        scorecard_path = _design_source_path("product_health_scorecard", "PRODUCT_HEALTH_SCORECARD.yaml")
        trust_payload = _load_yaml_dict(trust_path) or {}
        scorecard_payload = _load_yaml_dict(scorecard_path) or {}
        contact_page = next(
            (
                dict(value)
                for value in list(trust_payload.get("trust_pages") or [])
                if isinstance(value, dict) and str(value.get("id") or "").strip() == "contact"
            ),
            {},
        )
        support_scorecard = next(
            (
                dict(value)
                for value in list(scorecard_payload.get("scorecards") or [])
                if isinstance(value, dict) and str(value.get("id") or "").strip() == "support_and_feedback_closure"
            ),
            {},
        )
        support_verification = dict(diagnostics.get("support_verification") or {})
        product_control = dict(diagnostics.get("product_control") or {})
        readiness = dict(diagnostics.get("readiness") or {})
        providers = dict(diagnostics.get("providers") or {})
        queue_health = dict(diagnostics.get("queue_health") or {})
        metric_lines: list[str] = []
        for metric in list(support_scorecard.get("metrics") or [])[:2]:
            if not isinstance(metric, dict):
                continue
            name = str(metric.get("name") or "").strip()
            target = str(metric.get("target") or "").strip()
            if name and target:
                metric_lines.append(f"{name} target {target}.")
        bullets: list[str] = []
        recommended_action = compact_text(
            str(support_verification.get("recommended_action") or "").strip(),
            fallback="",
            limit=180,
        )
        if recommended_action:
            bullets.append(recommended_action)
        if str(support_verification.get("state") or "").strip() in {"waiting", "blocked"}:
            bullets.append(
                compact_text(
                    " ".join(
                        part
                        for part in (
                            str(support_verification.get("channel_receipt_detail") or "").strip(),
                            str(support_verification.get("install_receipt_detail") or "").strip(),
                            str(support_verification.get("confirmation_detail") or "").strip(),
                        )
                        if part
                    ),
                    fallback="Support verification is active.",
                    limit=180,
                )
            )
        if metric_lines:
            bullets.extend(metric_lines)
        provider_detail = compact_text(str(providers.get("risk_detail") or "").strip(), fallback="", limit=160)
        if provider_detail:
            bullets.append(f"Provider posture: {provider_detail}")
        elif int(queue_health.get("delivery_errors") or 0):
            bullets.append(f"Delivery backlog: {int(queue_health.get('delivery_errors') or 0)} active queue delivery errors.")
        readiness_detail = compact_text(str(readiness.get("detail") or "").strip(), fallback="", limit=160)
        if readiness_detail:
            bullets.append(f"Workspace readiness: {readiness_detail}")
        actions: list[dict[str, str]] = []
        request_api_href = str(support_verification.get("request_api_href") or "").strip()
        request_action_label = str(support_verification.get("request_action_label") or "Request confirmation").strip()
        request_api_method = str(support_verification.get("request_api_method") or "post").strip().lower() or "post"
        if request_api_href and request_action_label:
            actions.append({"label": request_action_label, "href": request_api_href, "method": request_api_method})
        actions.append({"label": "Open support diagnostics", "href": "/app/api/support", "method": "get"})
        access_url = str(support_verification.get("access_url") or "").strip()
        if access_url:
            actions.append({"label": "Open access link", "href": access_url, "method": "get"})
        for action in _grounding_actions(contact_page.get("actions")):
            if len(actions) >= 4:
                break
            if all(str(item.get("href") or "").strip() != str(action.get("href") or "").strip() for item in actions):
                actions.append(action)
        control_sources = dict(product_control.get("sources") or {})
        sources = [
            _grounding_source(
                label="PUBLIC_TRUST_CONTENT.yaml",
                path=trust_path,
                as_of=str(contact_page.get("updated_date") or trust_payload.get("version") or "").strip(),
            ),
            _grounding_source(
                label="PRODUCT_HEALTH_SCORECARD.yaml",
                path=scorecard_path,
                as_of=str(scorecard_payload.get("last_reviewed") or "").strip(),
            ),
        ]
        pulse_path = str(control_sources.get("pulse_path") or "").strip()
        if pulse_path:
            sources.append(
                _grounding_source(
                    label="WEEKLY_PRODUCT_PULSE.generated.json",
                    path=pulse_path,
                    as_of=str(control_sources.get("pulse_generated_at") or "").strip(),
                )
            )
        return {
            "id": "support_assistant",
            "title": "Support closure grounding",
            "summary": compact_text(
                " ".join(
                    part
                    for part in (
                        str(support_verification.get("summary") or "").strip(),
                        str(contact_page.get("intro") or "").strip(),
                        str(support_scorecard.get("question") or "").strip(),
                    )
                    if part
                ),
                fallback="Support guidance should stay grounded in mirrored trust and release signals.",
                limit=220,
            ),
            "bullets": bullets[:5],
            "actions": actions[:4],
            "sources": sources[:4],
        }

    def _operator_memo_grounding_pack(
        self,
        *,
        diagnostics: dict[str, object],
        lanes: list[dict[str, object]] | None = None,
        next_actions: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        scorecard_path = _design_source_path("product_health_scorecard", "PRODUCT_HEALTH_SCORECARD.yaml")
        journey_gates_path = _design_source_path("golden_journey_release_gates", "GOLDEN_JOURNEY_RELEASE_GATES.yaml")
        scorecard_payload = _load_yaml_dict(scorecard_path) or {}
        journey_gates_payload = _load_yaml_dict(journey_gates_path) or {}
        cadence = dict(scorecard_payload.get("cadence") or {})
        product_control = dict(diagnostics.get("product_control") or {})
        route_stewardship = dict(product_control.get("provider_route_stewardship") or {})
        journey_health = dict(product_control.get("journey_gate_health") or {})
        public_guide_freshness = dict(product_control.get("public_guide_freshness") or {})
        support_fallout = dict(product_control.get("support_fallout") or {})
        lane_rows = [dict(value) for value in list(lanes or []) if isinstance(value, dict)]
        severity = {"critical": 2, "watch": 1, "clear": 0}
        active_lane = next(
            (
                row
                for row in sorted(
                    lane_rows,
                    key=lambda row: (
                        severity.get(str(row.get("state") or "").strip(), 0),
                        int(row.get("count") or 0),
                    ),
                    reverse=True,
                )
                if severity.get(str(row.get("state") or "").strip(), 0) > 0
            ),
            {},
        )
        bullets: list[str] = []
        review = str(cadence.get("review") or "").strip()
        owner = str(cadence.get("snapshot_owner") or "").strip()
        if review or owner:
            bullets.append(f"Review cadence: {review or 'weekly'} by {owner or 'product_governor'}.")
        recommended_action = compact_text(
            str(journey_health.get("recommended_action") or journey_health.get("reason") or "").strip(),
            fallback="",
            limit=180,
        )
        if recommended_action:
            bullets.append(f"Journey gates: {recommended_action}")
        launch_readiness = str(product_control.get("launch_readiness") or "").strip()
        if launch_readiness:
            bullets.append(f"Launch readiness: {launch_readiness}")
        route_detail = " · ".join(
            part
            for part in (
                f"default {str(route_stewardship.get('default_status') or '').strip()}" if str(route_stewardship.get("default_status") or "").strip() else "",
                f"canary {str(route_stewardship.get('canary_status') or '').strip()}" if str(route_stewardship.get("canary_status") or "").strip() else "",
                f"next {str(route_stewardship.get('next_decision') or '').strip()}" if str(route_stewardship.get("next_decision") or "").strip() else "",
                f"review due {str(route_stewardship.get('review_due') or '').strip()}" if str(route_stewardship.get("review_due") or "").strip() else "",
            )
            if part
        )
        if route_detail:
            bullets.append(f"Provider-route stewardship: {route_detail}")
        support_fallout_action = compact_text(
            str(support_fallout.get("recommended_action") or support_fallout.get("detail") or "").strip(),
            fallback="",
            limit=180,
        )
        if support_fallout_action and str(support_fallout.get("state") or "clear").strip().lower() != "clear":
            bullets.append(f"Support fallout: {support_fallout_action}")
        guide_detail = compact_text(str(public_guide_freshness.get("detail") or "").strip(), fallback="", limit=180)
        if guide_detail:
            bullets.append(f"Public guide: {guide_detail}")
        if active_lane:
            bullets.append(
                compact_text(
                    f"Current lane pressure: {str(active_lane.get('label') or '').strip()}. {str(active_lane.get('detail') or '').strip()}",
                    fallback="",
                    limit=180,
                )
            )
        elif next_actions:
            first_action = dict(next_actions[0] or {})
            bullets.append(
                compact_text(
                    f"Next operator move: {str(first_action.get('label') or '').strip()}. {str(first_action.get('detail') or '').strip()}",
                    fallback="",
                    limit=180,
                )
            )
        actions: list[dict[str, str]] = []
        for item in list(next_actions or [])[:3]:
            row = dict(item or {})
            label = str(row.get("action_label") or row.get("label") or "").strip()
            href = str(row.get("action_href") or row.get("href") or "").strip()
            if not label or not href:
                continue
            actions.append(
                {
                    "label": label,
                    "href": href,
                    "method": str(row.get("action_method") or "get").strip().lower() or "get",
                }
            )
        if not actions and active_lane and str(active_lane.get("href") or "").strip():
            actions.append(
                {
                    "label": f"Open {str(active_lane.get('label') or 'operator lane').strip()}",
                    "href": str(active_lane.get("href") or "").strip(),
                    "method": "get",
                }
            )
        control_sources = dict(product_control.get("sources") or {})
        sources = [
            _grounding_source(
                label="PRODUCT_HEALTH_SCORECARD.yaml",
                path=scorecard_path,
                as_of=str(scorecard_payload.get("last_reviewed") or "").strip(),
            ),
            _grounding_source(
                label="GOLDEN_JOURNEY_RELEASE_GATES.yaml",
                path=journey_gates_path,
                as_of=str(journey_gates_payload.get("last_reviewed") or "").strip(),
            ),
        ]
        pulse_path = str(control_sources.get("pulse_path") or "").strip()
        if pulse_path:
            sources.append(
                _grounding_source(
                    label="WEEKLY_PRODUCT_PULSE.generated.json",
                    path=pulse_path,
                    as_of=str(control_sources.get("pulse_generated_at") or "").strip(),
                )
            )
        generated_journey_path = str(control_sources.get("journey_gates_path") or "").strip()
        if generated_journey_path:
            sources.append(
                _grounding_source(
                    label="JOURNEY_GATES.generated.json",
                    path=generated_journey_path,
                    as_of=str(control_sources.get("journey_gates_generated_at") or "").strip(),
                )
            )
        public_guide_path = str(control_sources.get("public_guide_path") or "").strip()
        if public_guide_path:
            sources.append(
                _grounding_source(
                    label="manifest.generated.json",
                    path=public_guide_path,
                    as_of=str(control_sources.get("public_guide_generated_at") or "").strip(),
                )
            )
        return {
            "id": "operator_memo",
            "title": "Operator memo grounding",
            "summary": compact_text(
                " ".join(
                    part
                    for part in (
                        str(product_control.get("summary") or "").strip(),
                        str(scorecard_payload.get("purpose") or "").strip(),
                    )
                    if part
                ),
                fallback="Operator memos should stay grounded in weekly product control and journey gate evidence.",
                limit=220,
            ),
            "bullets": [item for item in bullets[:5] if str(item or "").strip()],
            "actions": actions[:4],
            "sources": sources[:5],
        }

    def _gmail_signal_labels(
        self,
        *,
        signal: google_oauth_service.GoogleWorkspaceSignal,
    ) -> set[str]:
        payload = dict(signal.payload or {})
        return {
            str(value or "").strip().upper()
            for value in list(payload.get("labels") or [])
            if str(value or "").strip()
        }

    def _curate_google_workspace_signals(
        self,
        *,
        signals: tuple[google_oauth_service.GoogleWorkspaceSignal, ...],
    ) -> tuple[
        tuple[google_oauth_service.GoogleWorkspaceSignal, ...],
        tuple[google_oauth_service.GoogleWorkspaceSignal, ...],
    ]:
        curated: list[google_oauth_service.GoogleWorkspaceSignal] = []
        suppressed: list[google_oauth_service.GoogleWorkspaceSignal] = []
        seen_gmail_threads: set[str] = set()
        for signal in signals:
            normalized_channel = str(signal.channel or "").strip().lower()
            normalized_signal = str(signal.signal_type or "").strip().lower()
            normalized_source = str(signal.source_ref or "").strip()
            normalized_payload = dict(signal.payload or {})
            normalized_thread_ref = str(
                normalized_payload.get("thread_id")
                or normalized_payload.get("gmail_thread_id")
                or normalized_payload.get("thread_ref")
                or ""
            ).strip()
            if normalized_channel == "gmail" and normalized_signal == "email_thread":
                if self._gmail_signal_labels(signal=signal) & _LOW_SIGNAL_GMAIL_LABELS:
                    suppressed.append(signal)
                    continue
                thread_key = normalized_thread_ref or normalized_source
                if thread_key and thread_key in seen_gmail_threads:
                    suppressed.append(signal)
                    continue
                if thread_key:
                    seen_gmail_threads.add(thread_key)
            curated.append(signal)
        return tuple(curated), tuple(suppressed)

    def _channel_action_secret(self) -> str:
        return resolve_signing_secret(self._container.settings, purpose="channel-actions")

    def _workspace_access_secret(self) -> str:
        return resolve_signing_secret(self._container.settings, purpose="workspace-access")

    def _signal_ingest_secret(self) -> str:
        return resolve_signing_secret(self._container.settings, purpose="signal-ingest")

    def _record_product_event(
        self,
        *,
        principal_id: str,
        event_type: str,
        payload: dict[str, object] | None = None,
        source_id: str = "",
        dedupe_key: str = "",
    ) -> None:
        event = self._container.channel_runtime.ingest_observation(
            principal_id=principal_id,
            channel="product",
            event_type=event_type,
            payload=dict(payload or {}),
            source_id=source_id,
            dedupe_key=dedupe_key,
        )
        normalized_type = str(event_type or "").strip().lower()
        if normalized_type and not normalized_type.startswith("webhook_"):
            self._queue_webhook_deliveries(
                principal_id=principal_id,
                matched_event_type=normalized_type,
                payload=dict(payload or {}),
                source_id=str(source_id or event.observation_id or "").strip(),
            )

    def _stakeholder_lookup(self, principal_id: str) -> dict[str, Stakeholder]:
        rows = self._container.memory_runtime.list_stakeholders(principal_id=principal_id, limit=200)
        return {row.stakeholder_id: row for row in rows}

    def _resolve_stakeholder_ref(self, *, principal_id: str, stakeholder_id: str = "", counterparty: str = "") -> str:
        explicit = str(stakeholder_id or "").strip()
        if explicit:
            return explicit
        wanted = _person_key(counterparty)
        if not wanted:
            return ""
        for row in self._stakeholder_lookup(principal_id).values():
            if wanted == _person_key(str(row.display_name or "")):
                return str(row.stakeholder_id or "").strip()
            if wanted == _person_key(str(row.channel_ref or "")):
                return str(row.stakeholder_id or "").strip()
        return ""

    def _start_product_review_session(
        self,
        *,
        principal_id: str,
        goal: str,
        source_ref: str = "",
    ) -> str:
        session = self._container.orchestrator._ledger.start_session(
            IntentSpecV3(
                principal_id=principal_id,
                goal=str(goal or "Review office signal draft").strip() or "Review office signal draft",
                task_type="office_loop",
                deliverable_type="draft_review",
                risk_class="medium",
                approval_class="draft",
                budget_class="standard",
            )
        )
        self._container.orchestrator._ledger.append_event(
            session.session_id,
            "product_review_session_started",
            {
                "goal": str(goal or "").strip(),
                "source_ref": str(source_ref or "").strip(),
                "started_at": _now_iso(),
            },
        )
        return session.session_id

    def _find_pending_signal_draft_approval(
        self,
        *,
        principal_id: str,
        source_ref: str,
        recipient_email: str,
    ) -> ApprovalRequest | None:
        normalized_source = str(source_ref or "").strip()
        normalized_recipient = str(recipient_email or "").strip().lower()
        if not normalized_source and not normalized_recipient:
            return None
        for row in self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=200):
            action_json = dict(row.requested_action_json or {})
            if str(action_json.get("draft_origin") or "").strip() != "office_signal":
                continue
            current_source = str(action_json.get("source_ref") or action_json.get("thread_ref") or "").strip()
            current_recipient = str(action_json.get("recipient_email") or action_json.get("recipient") or "").strip().lower()
            if normalized_source and current_source == normalized_source:
                return row
            if normalized_recipient and current_recipient == normalized_recipient and normalized_source and current_source == normalized_source:
                return row
        return None

    def _compose_signal_reply_draft_text(
        self,
        *,
        counterparty: str,
        recipient_email: str,
        title: str,
        summary: str,
        action_title: str,
        due_at: str | None,
        tone: str,
    ) -> str:
        recipient_label = _counterparty_label(counterparty=counterparty, email=recipient_email)
        greeting_name = _first_name(recipient_label)
        greeting = f"Hi {greeting_name}," if greeting_name else "Hi,"
        normalized_subject = compact_text(title or summary, fallback="your note", limit=120)
        action_subject = _trim_counterparty_suffix(action_title, counterparty=recipient_label)
        if action_subject:
            action_subject = action_subject[:1].lower() + action_subject[1:]
        timing = _reply_timing_phrase(due_at)
        action_sentence = (
            f"I have the next step queued and will send {action_subject} {timing}."
            if action_subject
            else f"I have the next step queued and will follow up {timing}."
        )
        normalized_tone = str(tone or "").strip().lower()
        if normalized_tone == "warm":
            closer = "If there is anything you want emphasized, I can fold it in."
        elif normalized_tone == "direct":
            closer = "If there is anything specific you want highlighted, send it over."
        else:
            closer = "If there is anything specific you want emphasized, let me know."
        return "\n\n".join(
            (
                greeting,
                f"Thanks for the note about {normalized_subject}.",
                f"{action_sentence} {closer}",
                "Best,",
            )
        )

    def _stage_signal_reply_draft(
        self,
        *,
        principal_id: str,
        signal_type: str,
        channel: str,
        title: str,
        summary: str,
        text: str,
        source_ref: str,
        external_id: str,
        counterparty: str,
        stakeholder_id: str,
        due_at: str | None,
        payload: dict[str, object] | None,
        staged_candidates: tuple[CommitmentCandidate, ...],
    ) -> DraftCandidate | None:
        normalized_signal = str(signal_type or "").strip().lower()
        normalized_channel = str(channel or "").strip().lower()
        if normalized_signal != "email_thread" or normalized_channel != "gmail":
            return None
        recipient_email = str(dict(payload or {}).get("from_email") or "").strip().lower()
        if not recipient_email:
            resolved_stakeholder = self._resolve_stakeholder_ref(
                principal_id=principal_id,
                stakeholder_id=stakeholder_id,
                counterparty=counterparty,
            )
            stakeholder = self._stakeholder_lookup(principal_id).get(resolved_stakeholder)
            if stakeholder is not None and "@" in str(stakeholder.channel_ref or ""):
                recipient_email = str(stakeholder.channel_ref or "").strip().lower()
        if not recipient_email or any(marker in recipient_email for marker in _SYSTEM_REPLY_SENDER_MARKERS):
            return None
        combined_text = " ".join(part for part in (title, summary, text) if str(part or "").strip()).lower()
        if not any(token in combined_text for token in _REPLY_SIGNAL_CUES):
            return None
        existing = self._find_pending_signal_draft_approval(
            principal_id=principal_id,
            source_ref=source_ref,
            recipient_email=recipient_email,
        )
        if existing is not None:
            return self._draft_from_approval(existing)
        resolved_stakeholder_id = self._resolve_stakeholder_ref(
            principal_id=principal_id,
            stakeholder_id=stakeholder_id,
            counterparty=counterparty,
        )
        stakeholder = self._stakeholder_lookup(principal_id).get(resolved_stakeholder_id) if resolved_stakeholder_id else None
        recipient_label = _counterparty_label(
            counterparty=str(counterparty or dict(payload or {}).get("from_name") or (stakeholder.display_name if stakeholder is not None else "")).strip(),
            email=recipient_email,
        )
        preferred_tone = str((stakeholder.tone_pref if stakeholder is not None else "") or "direct").strip().lower() or "direct"
        primary_candidate = next(
            (
                row
                for row in staged_candidates
                if str(row.status or "").strip().lower() in {"pending", "duplicate"}
            ),
            staged_candidates[0] if staged_candidates else None,
        )
        requested_due_at = (
            str((primary_candidate.suggested_due_at if primary_candidate is not None else "") or "").strip()
            or str(due_at or "").strip()
            or None
        )
        draft_text = self._compose_signal_reply_draft_text(
            counterparty=recipient_label,
            recipient_email=recipient_email,
            title=title,
            summary=summary or text,
            action_title=str((primary_candidate.title if primary_candidate is not None else "") or title or "the update").strip(),
            due_at=requested_due_at,
            tone=preferred_tone,
        )
        subject = str(title or summary or "Follow-up").strip() or "Follow-up"
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        payload_json = dict(payload or {})
        google_account_email = str(payload_json.get("account_email") or "").strip().lower()
        google_binding_id = ""
        if google_account_email:
            for account in google_oauth_service.list_google_accounts(container=self._container, principal_id=principal_id):
                account_email = str(getattr(account, "google_email", "") or "").strip().lower()
                if account_email == google_account_email:
                    google_binding_id = str(account.binding.binding_id or "").strip()
                    break
        gmail_thread_id = str(payload_json.get("thread_id") or "").strip() or _gmail_resource_id(
            source_ref,
            prefix="gmail-thread:",
        )
        gmail_message_id = str(payload_json.get("message_id") or "").strip() or _gmail_resource_id(
            external_id,
            prefix="gmail-message:",
        )
        session_id = self._start_product_review_session(
            principal_id=principal_id,
            goal=f"Review reply draft for {recipient_label}",
            source_ref=source_ref,
        )
        approval = self._container.orchestrator._approvals.create_request(
            session_id,
            f"signal-draft:{uuid4().hex[:10]}",
            f"Approve reply to {recipient_label}",
            {
                "action": "delivery.send",
                "intent": "reply",
                "channel": "email",
                "recipient": recipient_email,
                "recipient_email": recipient_email,
                "recipient_label": recipient_label,
                "subject": subject,
                "content": draft_text,
                "draft_text": draft_text,
                "thread_ref": str(source_ref or external_id or session_id).strip(),
                "source_ref": str(source_ref or "").strip(),
                "external_id": str(external_id or "").strip(),
                "stakeholder_id": resolved_stakeholder_id,
                "gmail_thread_id": gmail_thread_id,
                "gmail_message_id": gmail_message_id,
                "gmail_rfc822_message_id": str(payload_json.get("rfc822_message_id") or "").strip(),
                "gmail_references": str(payload_json.get("references") or payload_json.get("message_id") or "").strip(),
                "google_account_email": google_account_email,
                "google_binding_id": google_binding_id,
                "signal_type": normalized_signal,
                "draft_origin": "office_signal",
                "tone": preferred_tone,
                "candidate_ids": [row.candidate_id for row in staged_candidates if str(row.candidate_id or "").strip()],
            },
        )
        self._record_product_event(
            principal_id=principal_id,
            event_type="approval_requested",
            payload={
                "draft_ref": f"approval:{approval.approval_id}",
                "source_ref": str(source_ref or "").strip(),
                "external_id": str(external_id or "").strip(),
                "signal_type": normalized_signal,
                "recipient": recipient_email,
                "recipient_label": recipient_label,
                "reason": approval.reason,
            },
            source_id=approval.approval_id,
        )
        self._record_product_event(
            principal_id=principal_id,
            event_type="signal_reply_draft_staged",
            payload={
                "draft_ref": f"approval:{approval.approval_id}",
                "source_ref": str(source_ref or "").strip(),
                "external_id": str(external_id or "").strip(),
                "recipient": recipient_email,
                "recipient_label": recipient_label,
            },
            source_id=approval.approval_id,
        )
        return self._draft_from_approval(approval)

    def _matching_staged_signal_candidates(
        self,
        *,
        principal_id: str,
        source_ref: str,
    ) -> tuple[CommitmentCandidate, ...]:
        normalized_source = str(source_ref or "").strip()
        if not normalized_source:
            return ()
        return tuple(
            row
            for row in self.list_commitment_candidates(principal_id=principal_id, limit=200, status=None)
            if str(row.source_ref or "").strip() == normalized_source
            and str(row.status or "").strip().lower() in {"pending", "duplicate"}
        )

    def _linked_signal_candidate_ids(
        self,
        *,
        principal_id: str,
        action_json: dict[str, object],
    ) -> tuple[str, ...]:
        rows: list[str] = []
        seen: set[str] = set()
        for value in list(action_json.get("candidate_ids") or []):
            normalized = str(value or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                rows.append(normalized)
        if rows:
            return tuple(rows)
        source_ref = str(action_json.get("source_ref") or action_json.get("thread_ref") or "").strip()
        for row in self._matching_staged_signal_candidates(principal_id=principal_id, source_ref=source_ref):
            normalized = str(row.candidate_id or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                rows.append(normalized)
        return tuple(rows)

    def _accept_linked_signal_candidates(
        self,
        *,
        principal_id: str,
        action_json: dict[str, object],
        reviewer: str,
    ) -> tuple[str, ...]:
        accepted: list[str] = []
        for candidate_id in self._linked_signal_candidate_ids(principal_id=principal_id, action_json=action_json):
            current = self.get_commitment_candidate(principal_id=principal_id, candidate_id=candidate_id)
            if current is None or str(current.status or "").strip().lower() not in {"pending", "duplicate"}:
                continue
            created = self.accept_commitment_candidate(
                principal_id=principal_id,
                candidate_id=candidate_id,
                reviewer=reviewer,
            )
            if created is not None:
                accepted.append(candidate_id)
        return tuple(accepted)

    def _resolve_google_binding_for_action(
        self,
        *,
        principal_id: str,
        action_json: dict[str, object],
    ) -> tuple[str, str]:
        explicit_binding_id = str(action_json.get("google_binding_id") or "").strip()
        explicit_account_email = str(
            action_json.get("google_account_email")
            or action_json.get("account_email")
            or ""
        ).strip().lower()
        if explicit_binding_id:
            return explicit_binding_id, explicit_account_email
        if not explicit_account_email:
            return "", ""
        for account in google_oauth_service.list_google_accounts(container=self._container, principal_id=principal_id):
            account_email = str(getattr(account, "google_email", "") or "").strip().lower()
            if account_email != explicit_account_email:
                continue
            return str(account.binding.binding_id or "").strip(), account_email
        return "", explicit_account_email

    def _maybe_send_approved_draft(
        self,
        *,
        principal_id: str,
        draft_ref: str,
        action_json: dict[str, object],
    ) -> dict[str, object]:
        channel = str(action_json.get("channel") or "").strip().lower()
        if channel not in {"email", "gmail"}:
            return {"status": "skipped", "reason": "unsupported_channel", "channel": channel}
        recipient_email = str(action_json.get("recipient_email") or action_json.get("recipient") or "").strip().lower()
        recipient_label = str(action_json.get("recipient_label") or "").strip()
        subject = str(action_json.get("subject") or "").strip()
        body_text = str(action_json.get("draft_text") or action_json.get("content") or "").strip()
        thread_ref = str(action_json.get("thread_ref") or "").strip()
        source_ref = str(action_json.get("source_ref") or "").strip()
        person_id = str(action_json.get("stakeholder_id") or "").strip()
        signal_type = str(action_json.get("signal_type") or "").strip()
        reply_to_message_id = str(action_json.get("gmail_rfc822_message_id") or action_json.get("in_reply_to") or "").strip()
        references = str(action_json.get("gmail_references") or action_json.get("references") or "").strip()
        google_binding_id, google_account_email = self._resolve_google_binding_for_action(
            principal_id=principal_id,
            action_json=action_json,
        )
        if not recipient_email or not body_text:
            return {
                "status": "skipped",
                "reason": "draft_send_missing_recipient_or_content",
                "channel": channel,
                "recipient_email": recipient_email,
                "recipient_label": recipient_label,
                "subject": subject,
                "thread_ref": thread_ref,
                "source_ref": source_ref,
                "person_id": person_id,
                "signal_type": signal_type,
                "reply_to_message_id": reply_to_message_id,
                "references": references,
                "google_binding_id": google_binding_id,
                "google_account_email": google_account_email,
            }
        if not subject:
            subject = compact_text(body_text, fallback="EA follow-up", limit=120)
        thread_id = str(action_json.get("gmail_thread_id") or "").strip() or _gmail_resource_id(
            action_json.get("source_ref"),
            prefix="gmail-thread:",
        )
        try:
            receipt = google_oauth_service.send_google_gmail_message(
                container=self._container,
                principal_id=principal_id,
                recipient_email=recipient_email,
                subject=subject,
                body_text=body_text,
                thread_id=thread_id or None,
                reply_to_message_id=reply_to_message_id or None,
                references=references or None,
                binding_id=google_binding_id,
            )
        except RuntimeError as exc:
            reason = str(exc or "draft_send_failed")
            skip_reasons = {
                "google_oauth_binding_not_found",
                "google_oauth_client_id_missing",
                "google_oauth_client_secret_missing",
                "google_oauth_redirect_uri_missing",
                "google_oauth_state_secret_missing",
                "google_oauth_provider_secret_key_missing",
                "google_gmail_send_scope_missing",
                "google_gmail_refresh_token_missing",
                "google_gmail_access_token_missing",
                "google_gmail_sender_missing",
                "google_gmail_recipient_missing",
                "google_gmail_body_missing",
            }
            status = "skipped" if reason in skip_reasons else "failed"
            return {
                "status": status,
                "reason": reason,
                "channel": channel,
                "recipient_email": recipient_email,
                "recipient_label": recipient_label,
                "subject": subject,
                "draft_ref": draft_ref,
                "thread_ref": thread_ref,
                "source_ref": source_ref,
                "person_id": person_id,
                "signal_type": signal_type,
                "reply_to_message_id": reply_to_message_id,
                "references": references,
                "google_binding_id": google_binding_id,
                "google_account_email": google_account_email,
            }
        return {
            "status": "sent",
            "channel": "gmail",
            "recipient_email": receipt.recipient_email,
            "recipient_label": recipient_label,
            "sender_email": receipt.sender_email,
            "subject": receipt.subject,
            "gmail_message_id": receipt.gmail_message_id,
            "rfc822_message_id": receipt.rfc822_message_id,
            "sent_at": receipt.sent_at,
            "draft_ref": draft_ref,
            "thread_ref": thread_ref,
            "source_ref": source_ref,
            "person_id": person_id,
            "signal_type": signal_type,
            "reply_to_message_id": reply_to_message_id,
            "references": references,
            "google_binding_id": google_binding_id,
            "google_account_email": google_account_email or receipt.sender_email,
        }

    def _ensure_draft_delivery_followup(
        self,
        *,
        principal_id: str,
        request: ApprovalRequest,
        action_json: dict[str, object],
        delivery: dict[str, object],
    ) -> HandoffNote | None:
        status = str(delivery.get("status") or "").strip().lower()
        if status not in {"skipped", "failed"}:
            return None
        return self._open_delivery_followup(
            principal_id=principal_id,
            session_id=request.session_id,
            source_id=request.approval_id,
            draft_ref=str(delivery.get("draft_ref") or f"approval:{request.approval_id}").strip(),
            action_json=action_json,
            reason=str(delivery.get("reason") or "draft_send_pending_manual_followup").strip(),
            event_type="draft_send_followup_created",
        )

    def _open_delivery_followup(
        self,
        *,
        principal_id: str,
        session_id: str,
        source_id: str,
        draft_ref: str,
        action_json: dict[str, object],
        reason: str,
        event_type: str,
        previous_resolution: str = "",
    ) -> HandoffNote | None:
        draft_ref = str(draft_ref or "").strip()
        if not draft_ref:
            return None
        for task in self._container.orchestrator.list_human_tasks(principal_id=principal_id, status="pending", limit=200):
            input_json = dict(task.input_json or {})
            if str(input_json.get("draft_ref") or "").strip() == draft_ref and str(task.task_type or "").strip() == "delivery_followup":
                return self._handoff_from_human_task(task)
        recipient_label = str(action_json.get("recipient_label") or action_json.get("recipient_email") or action_json.get("recipient") or "recipient").strip()
        subject = str(action_json.get("subject") or "").strip()
        brief = f"Send approved reply to {recipient_label}"
        if subject:
            brief = f"{brief}: {compact_text(subject, fallback=subject, limit=72)}"
        task = self._container.orchestrator.create_human_task(
            session_id=session_id,
            principal_id=principal_id,
            task_type="delivery_followup",
            role_required="operator",
            brief=brief,
            why_human=f"Automatic send did not complete ({reason}). Finish delivery manually.",
            priority="high" if str(action_json.get("draft_origin") or "").strip() == "office_signal" else "normal",
            sla_due_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            input_json={
                "draft_ref": draft_ref,
                "channel": str(action_json.get("channel") or "email").strip().lower(),
                "recipient_email": str(action_json.get("recipient_email") or action_json.get("recipient") or "").strip(),
                "recipient_label": str(action_json.get("recipient_label") or "").strip(),
                "subject": subject,
                "draft_text": str(action_json.get("draft_text") or action_json.get("content") or "").strip(),
                "reason": reason,
                "thread_ref": str(action_json.get("thread_ref") or "").strip(),
                "source_ref": str(action_json.get("source_ref") or "").strip(),
                "stakeholder_id": str(action_json.get("stakeholder_id") or "").strip(),
                "gmail_thread_id": str(action_json.get("gmail_thread_id") or "").strip(),
                "gmail_rfc822_message_id": str(action_json.get("gmail_rfc822_message_id") or "").strip(),
                "gmail_references": str(action_json.get("gmail_references") or "").strip(),
                "signal_type": str(action_json.get("signal_type") or "").strip(),
            },
            desired_output_json={
                "resolution": "sent",
                "proof": "Manual send completed and logged.",
            },
        )
        self._record_product_event(
            principal_id=principal_id,
            event_type=event_type,
            payload={
                "draft_ref": draft_ref,
                "handoff_ref": f"human_task:{task.human_task_id}",
                "reason": reason,
                "recipient_email": str(action_json.get("recipient_email") or action_json.get("recipient") or "").strip(),
                "recipient_label": str(action_json.get("recipient_label") or "").strip(),
                "subject": subject,
                "thread_ref": str(action_json.get("thread_ref") or "").strip(),
                "source_ref": str(action_json.get("source_ref") or "").strip(),
                "person_id": str(action_json.get("stakeholder_id") or "").strip(),
                "previous_resolution": previous_resolution,
            },
            source_id=source_id,
        )
        return self._handoff_from_human_task(task)

    def _draft_source_id(self, draft_ref: str) -> str:
        normalized = str(draft_ref or "").strip()
        if normalized.startswith("approval:"):
            return normalized.split(":", 1)[1].strip()
        return normalized

    def _delivery_thread_ref_from_payload(self, payload: dict[str, object]) -> str:
        return str(payload.get("thread_ref") or payload.get("source_ref") or payload.get("draft_ref") or "").strip()

    def _latest_delivery_followup_observation_for_thread(
        self,
        *,
        principal_id: str,
        thread_ref: str,
    ) -> tuple[dict[str, object], str, str]:
        normalized = str(thread_ref or "").strip()
        if not normalized:
            return {}, "", ""
        wanted = {normalized}
        if normalized.startswith("thread:"):
            wanted.add(normalized.split(":", 1)[1])
        rows = []
        for row in self._container.channel_runtime.list_recent_observations(limit=400, principal_id=principal_id):
            if str(row.channel or "").strip() != "product":
                continue
            event_type = str(row.event_type or "").strip().lower()
            if event_type not in {
                "draft_send_followup_created",
                "draft_send_followup_reopened",
                "draft_send_followup_resolved",
                "draft_send_reauth_needed",
                "draft_send_waiting_on_principal",
                "draft_send_failed",
            }:
                continue
            payload = dict(row.payload or {})
            if self._delivery_thread_ref_from_payload(payload) not in wanted:
                continue
            rows.append((str(row.created_at or ""), str(row.source_id or "").strip(), event_type, payload))
        rows.sort(key=lambda item: item[0], reverse=True)
        if not rows:
            return {}, "", ""
        _created_at, source_id, event_type, payload = rows[0]
        return payload, source_id, event_type

    def resume_thread_delivery_followup(
        self,
        *,
        principal_id: str,
        thread_ref: str,
        actor: str,
        operator_id: str = "",
    ) -> HandoffNote | None:
        payload, source_id, event_type = self._latest_delivery_followup_observation_for_thread(
            principal_id=principal_id,
            thread_ref=thread_ref,
        )
        if not payload:
            raise RuntimeError("thread_delivery_followup_not_resumable")
        draft_ref = str(payload.get("draft_ref") or self._delivery_thread_ref_from_payload(payload) or "").strip()
        if not draft_ref.startswith("approval:"):
            raise RuntimeError("thread_delivery_followup_request_not_found")
        approval_id = draft_ref.split(":", 1)[1].strip()
        request = self._container.orchestrator.fetch_approval_request_for_principal(approval_id, principal_id=principal_id)
        if request is None:
            raise RuntimeError("thread_delivery_followup_request_not_found")
        reopened = self._open_delivery_followup(
            principal_id=principal_id,
            session_id=request.session_id,
            source_id=source_id or approval_id,
            draft_ref=draft_ref,
            action_json=dict(request.requested_action_json or {}),
            reason=str(payload.get("reason") or "draft_send_pending_manual_followup").strip(),
            event_type="draft_send_followup_reopened",
            previous_resolution=(
                str(payload.get("resolution") or "").strip()
                or (
                    "reauth_needed"
                    if event_type == "draft_send_reauth_needed"
                    else "waiting_on_principal"
                    if event_type == "draft_send_waiting_on_principal"
                    else "failed"
                    if event_type == "draft_send_failed"
                    else ""
                )
            ),
        )
        if reopened is None:
            raise RuntimeError("thread_delivery_followup_not_resumable")
        if operator_id:
            task_id = reopened.id.split(":", 1)[1] if reopened.id.startswith("human_task:") else reopened.id
            current_task = self._container.orchestrator.fetch_human_task(task_id, principal_id=principal_id)
            if current_task is not None:
                current_owner = str(current_task.assigned_operator_id or "").strip()
                if current_owner and current_owner != operator_id:
                    raise RuntimeError("delivery_followup_owned_by_other_operator")
            assigned = self.assign_handoff(
                principal_id=principal_id,
                handoff_ref=reopened.id,
                operator_id=operator_id,
                actor=actor,
            )
            if assigned is not None:
                return assigned
        return reopened

    def _normalize_delivery_followup_resolution(self, resolution: str) -> str:
        normalized = str(resolution or "").strip().lower()
        if normalized in {"", "completed", "complete", "done"}:
            return "sent"
        if normalized in {"sent", "delivered", "manual_sent"}:
            return "sent"
        if normalized in {"reauth", "needs_reauth", "reauth_needed"}:
            return "reauth_needed"
        if normalized in {"failed", "unable_to_send", "delivery_failed"}:
            return "failed"
        if normalized in {"waiting", "waiting_on_principal", "principal"}:
            return "waiting_on_principal"
        return normalized or "sent"

    def _record_delivery_followup_resolution(
        self,
        *,
        principal_id: str,
        handoff_ref: str,
        task: HumanTask,
        operator_id: str,
        actor: str,
        resolution: str,
        delivery_mode: str = "manual_followup",
        delivery: dict[str, object] | None = None,
    ) -> None:
        input_json = dict(task.input_json or {})
        delivery = dict(delivery or {})
        draft_ref = str(input_json.get("draft_ref") or "").strip()
        source_id = self._draft_source_id(draft_ref) or task.human_task_id
        payload = {
            "draft_ref": draft_ref,
            "handoff_ref": handoff_ref,
            "operator_id": operator_id,
            "actor": actor,
            "resolution": resolution,
            "channel": str(delivery.get("channel") or input_json.get("channel") or "manual_followup").strip(),
            "delivery_mode": delivery_mode,
            "recipient_email": str(delivery.get("recipient_email") or input_json.get("recipient_email") or "").strip(),
            "recipient_label": str(input_json.get("recipient_label") or "").strip(),
            "subject": str(delivery.get("subject") or input_json.get("subject") or "").strip(),
            "reason": str(delivery.get("reason") or input_json.get("reason") or "").strip(),
            "thread_ref": str(delivery.get("thread_ref") or input_json.get("thread_ref") or "").strip(),
            "source_ref": str(delivery.get("source_ref") or input_json.get("source_ref") or "").strip(),
            "person_id": str(delivery.get("person_id") or input_json.get("stakeholder_id") or "").strip(),
            "sender_email": str(delivery.get("sender_email") or "").strip(),
            "gmail_message_id": str(delivery.get("gmail_message_id") or "").strip(),
            "rfc822_message_id": str(delivery.get("rfc822_message_id") or "").strip(),
            "sent_at": str(delivery.get("sent_at") or "").strip(),
        }
        self._record_product_event(
            principal_id=principal_id,
            event_type="draft_send_followup_resolved",
            payload=payload,
            source_id=source_id,
        )
        if resolution == "sent":
            self._record_product_event(
                principal_id=principal_id,
                event_type="draft_sent",
                payload={**payload, "status": "sent"},
                source_id=source_id,
            )
            return
        if resolution == "reauth_needed":
            self._record_product_event(
                principal_id=principal_id,
                event_type="draft_send_reauth_needed",
                payload=payload,
                source_id=source_id,
            )
            return
        if resolution == "waiting_on_principal":
            self._record_product_event(
                principal_id=principal_id,
                event_type="draft_send_waiting_on_principal",
                payload=payload,
                source_id=source_id,
            )
            return
        if resolution == "failed":
            self._record_product_event(
                principal_id=principal_id,
                event_type="draft_send_failed",
                payload={**payload, "status": "failed"},
                source_id=source_id,
            )

    def retry_delivery_followup_send(
        self,
        *,
        principal_id: str,
        handoff_ref: str,
        operator_id: str,
        actor: str,
    ) -> HandoffNote | None:
        if not handoff_ref.startswith("human_task:"):
            return None
        task_id = handoff_ref.split(":", 1)[1]
        current = self._container.orchestrator.fetch_human_task(task_id, principal_id=principal_id)
        if current is None:
            return None
        if str(current.task_type or "").strip() != "delivery_followup":
            raise RuntimeError("handoff_not_retryable")
        if str(current.assigned_operator_id or "").strip() and str(current.assigned_operator_id or "").strip() != str(operator_id or "").strip():
            raise RuntimeError("delivery_followup_owned_by_other_operator")
        if str(current.assigned_operator_id or "").strip() != str(operator_id or "").strip():
            assigned = self.assign_handoff(
                principal_id=principal_id,
                handoff_ref=handoff_ref,
                operator_id=operator_id,
                actor=actor,
            )
            if assigned is None:
                raise RuntimeError("handoff_not_assignable")
            current = self._container.orchestrator.fetch_human_task(task_id, principal_id=principal_id)
            if current is None:
                raise RuntimeError("handoff_not_found")
        input_json = dict(current.input_json or {})
        draft_ref = str(input_json.get("draft_ref") or "").strip()
        delivery = self._maybe_send_approved_draft(
            principal_id=principal_id,
            draft_ref=draft_ref,
            action_json={
                "channel": str(input_json.get("channel") or "email").strip().lower(),
                "recipient_email": str(input_json.get("recipient_email") or "").strip(),
                "recipient_label": str(input_json.get("recipient_label") or "").strip(),
                "subject": str(input_json.get("subject") or "").strip(),
                "draft_text": str(input_json.get("draft_text") or "").strip(),
                "thread_ref": str(input_json.get("thread_ref") or "").strip(),
                "source_ref": str(input_json.get("source_ref") or "").strip(),
                "stakeholder_id": str(input_json.get("stakeholder_id") or "").strip(),
                "gmail_thread_id": str(input_json.get("gmail_thread_id") or "").strip(),
                "gmail_rfc822_message_id": str(input_json.get("gmail_rfc822_message_id") or "").strip(),
                "gmail_references": str(input_json.get("gmail_references") or "").strip(),
                "signal_type": str(input_json.get("signal_type") or "").strip(),
            },
        )
        source_id = self._draft_source_id(draft_ref) or current.human_task_id
        self._record_product_event(
            principal_id=principal_id,
            event_type="draft_send_retry_attempted",
            payload={
                "draft_ref": draft_ref,
                "handoff_ref": handoff_ref,
                "operator_id": operator_id,
                "actor": actor,
                "status": str(delivery.get("status") or "").strip(),
                "reason": str(delivery.get("reason") or "").strip(),
                "recipient_email": str(delivery.get("recipient_email") or input_json.get("recipient_email") or "").strip(),
                "subject": str(delivery.get("subject") or input_json.get("subject") or "").strip(),
                "thread_ref": str(delivery.get("thread_ref") or input_json.get("thread_ref") or "").strip(),
                "source_ref": str(delivery.get("source_ref") or input_json.get("source_ref") or "").strip(),
            },
            source_id=source_id,
        )
        if str(delivery.get("status") or "").strip() != "sent":
            raise RuntimeError(str(delivery.get("reason") or delivery.get("status") or "draft_send_retry_failed"))
        updated = self._container.orchestrator.return_human_task(
            task_id,
            principal_id=principal_id,
            operator_id=operator_id,
            resolution="sent",
            returned_payload_json={
                "source": "product_handoffs",
                "actor": actor,
                "task_type": "delivery_followup",
                "draft_ref": draft_ref,
                "recipient_email": str(delivery.get("recipient_email") or input_json.get("recipient_email") or "").strip(),
                "subject": str(delivery.get("subject") or input_json.get("subject") or "").strip(),
                "reason": str(delivery.get("reason") or input_json.get("reason") or "").strip(),
                "resolution": "sent",
                "delivery_mode": "retry_send",
            },
            provenance_json={"source": "product_handoffs"},
        )
        if updated is None:
            raise RuntimeError("handoff_not_returnable")
        self._record_delivery_followup_resolution(
            principal_id=principal_id,
            handoff_ref=handoff_ref,
            task=current,
            operator_id=operator_id,
            actor=actor,
            resolution="sent",
            delivery_mode="retry_send",
            delivery=delivery,
        )
        self._record_product_event(
            principal_id=principal_id,
            event_type="handoff_completed",
            payload={"handoff_ref": handoff_ref, "operator_id": operator_id, "actor": actor, "resolution": "sent"},
            source_id=updated.human_task_id,
        )
        return self._handoff_from_human_task(updated)

    def _pending_signal_draft_candidate_ids(self, *, principal_id: str) -> set[str]:
        hidden: set[str] = set()
        for row in self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=200):
            action_json = dict(row.requested_action_json or {})
            if str(action_json.get("draft_origin") or "").strip() != "office_signal":
                continue
            hidden.update(self._linked_signal_candidate_ids(principal_id=principal_id, action_json=action_json))
        return hidden

    def _commitment_candidate_payload(self, row: CommitmentCandidate) -> dict[str, object]:
        return {
            "candidate_id": row.candidate_id,
            "title": row.title,
            "details": row.details,
            "source_text": row.source_text,
            "confidence": row.confidence,
            "suggested_due_at": row.suggested_due_at,
            "counterparty": row.counterparty,
            "channel_hint": row.channel_hint,
            "source_ref": row.source_ref,
            "signal_type": row.signal_type,
            "status": row.status,
            "kind": row.kind,
            "stakeholder_id": row.stakeholder_id,
            "duplicate_of_ref": row.duplicate_of_ref,
            "merge_strategy": row.merge_strategy,
        }

    def _draft_payload(self, row: DraftCandidate) -> dict[str, object]:
        return {
            "id": row.id,
            "thread_ref": row.thread_ref,
            "recipient_summary": row.recipient_summary,
            "intent": row.intent,
            "draft_text": row.draft_text,
            "tone": row.tone,
            "requires_approval": row.requires_approval,
            "approval_status": row.approval_status,
            "provenance_refs": [
                {
                    "ref_id": ref.ref_id,
                    "label": ref.label,
                    "href": ref.href,
                    "source_type": ref.source_type,
                    "note": ref.note,
                }
                for ref in row.provenance_refs
            ],
            "send_channel": row.send_channel,
        }

    def _commitment_item_from_commitment(self, row: Commitment) -> CommitmentItem:
        return commitment_item_from_commitment(row)

    def _commitment_item_from_follow_up(self, row: FollowUp, stakeholders: dict[str, Stakeholder]) -> CommitmentItem:
        return commitment_item_from_follow_up(row, stakeholders)

    def _commitment_identity_key(self, *, title: str, counterparty: str = "") -> str:
        normalized_title = _COMMITMENT_KEY_RE.sub(" ", str(title or "").strip().lower()).strip()
        normalized_counterparty = _COMMITMENT_KEY_RE.sub(" ", str(counterparty or "").strip().lower()).strip()
        if normalized_counterparty:
            counterparty_parts = tuple(part for part in normalized_counterparty.split() if part)
            stripped = False
            suffixes: list[str] = [normalized_counterparty]
            for index in range(len(counterparty_parts), 0, -1):
                suffixes.append(" ".join(counterparty_parts[:index]))
            for suffix in suffixes:
                for prefix in (f" to {suffix}", f" for {suffix}", f" with {suffix}"):
                    if normalized_title.endswith(prefix):
                        normalized_title = normalized_title[: -len(prefix)].strip()
                        stripped = True
                        break
                if stripped:
                    break
            if not stripped:
                for suffix in suffixes:
                    if normalized_title.endswith(suffix):
                        normalized_title = normalized_title[: -len(suffix)].strip()
                        break
        return f"{normalized_title}|{normalized_counterparty}"

    def _append_unique_refs(self, current: object, *values: str) -> tuple[str, ...]:
        seen: set[str] = set()
        rows: list[str] = []
        if isinstance(current, (list, tuple)):
            for item in current:
                normalized = str(item or "").strip()
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    rows.append(normalized)
        for value in values:
            normalized = str(value or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                rows.append(normalized)
        return tuple(rows)

    def _find_duplicate_commitment_ref(self, *, principal_id: str, title: str, counterparty: str = "") -> str:
        wanted = self._commitment_identity_key(title=title, counterparty=counterparty)
        if not wanted or wanted == "|":
            return ""
        stakeholders = self._stakeholder_lookup(principal_id)
        for row in self._container.memory_runtime.list_commitments(principal_id=principal_id, limit=200, status=None):
            candidate = self._commitment_item_from_commitment(row)
            if self._commitment_identity_key(title=candidate.statement, counterparty=candidate.counterparty) == wanted:
                return candidate.id
        for row in self._container.memory_runtime.list_follow_ups(principal_id=principal_id, limit=200, status=None):
            candidate = self._commitment_item_from_follow_up(row, stakeholders)
            if self._commitment_identity_key(title=candidate.statement, counterparty=candidate.counterparty) == wanted:
                return candidate.id
        return ""

    def _merge_candidate_into_existing(
        self,
        *,
        principal_id: str,
        duplicate_ref: str,
        candidate_id: str,
        title: str,
        details: str,
        due_at: str | None,
        counterparty: str,
        confidence: float,
        channel_hint: str = "",
        source_ref: str = "",
        signal_type: str = "",
        source_type: str = "manual",
    ) -> CommitmentItem | None:
        if duplicate_ref.startswith("commitment:"):
            current = self._container.memory_runtime.get_commitment(duplicate_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            source = dict(current.source_json or {})
            merged_from_refs = self._append_unique_refs(source.get("merged_from_refs"), candidate_id)
            effective_channel_hint = str(source.get("channel_hint") or "").strip() or channel_hint.strip() or "email"
            effective_source_ref = str(source.get("source_ref") or "").strip()
            effective_source_type = str(source.get("source_type") or "manual").strip() or "manual"
            effective_signal_type = str(source.get("signal_type") or "").strip()
            if source_ref.strip() and (not effective_source_ref or effective_source_type == "manual"):
                effective_source_ref = source_ref.strip()
                effective_source_type = source_type.strip() or "office_signal"
                effective_signal_type = signal_type.strip() or effective_signal_type
            updated = self._container.memory_runtime.upsert_commitment(
                principal_id=principal_id,
                commitment_id=current.commitment_id,
                title=current.title,
                details=current.details if details.strip() in {"", current.details.strip()} else f"{current.details}\n\nMerged candidate: {details.strip()}".strip(),
                status="open" if not status_open(current.status) else current.status,
                priority=current.priority,
                due_at=due_at or current.due_at,
                source_json={
                    **source,
                    "counterparty": counterparty.strip() or str(source.get("counterparty") or ""),
                    "confidence": max(float(source.get("confidence") or 0.0), confidence),
                    "channel_hint": effective_channel_hint,
                    "source_type": effective_source_type,
                    "source_ref": effective_source_ref,
                    "signal_type": effective_signal_type,
                    "merged_from_refs": list(merged_from_refs),
                    "resolution_code": "" if not status_open(current.status) else str(source.get("resolution_code") or ""),
                    "resolution_reason": "" if not status_open(current.status) else str(source.get("resolution_reason") or ""),
                    "reopened_at": _now_iso() if not status_open(current.status) else str(source.get("reopened_at") or ""),
                },
            )
            self._record_product_event(
                principal_id=principal_id,
                event_type="commitment_merged" if status_open(current.status) else "commitment_reopened",
                payload={"candidate_id": candidate_id, "duplicate_of_ref": duplicate_ref, "title": title},
                source_id=current.commitment_id,
            )
            return self._commitment_item_from_commitment(updated)
        if duplicate_ref.startswith("follow_up:"):
            current = self._container.memory_runtime.get_follow_up(duplicate_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            source = dict(current.source_json or {})
            merged_from_refs = self._append_unique_refs(source.get("merged_from_refs"), candidate_id)
            effective_channel_hint = str(source.get("channel_hint") or current.channel_hint or "").strip() or channel_hint.strip() or "email"
            effective_source_ref = str(source.get("source_ref") or "").strip()
            effective_source_type = str(source.get("source_type") or "follow_up").strip() or "follow_up"
            effective_signal_type = str(source.get("signal_type") or "").strip()
            if source_ref.strip() and (not effective_source_ref or effective_source_type in {"manual", "follow_up"}):
                effective_source_ref = source_ref.strip()
                effective_source_type = source_type.strip() or "office_signal"
                effective_signal_type = signal_type.strip() or effective_signal_type
            updated = self._container.memory_runtime.upsert_follow_up(
                principal_id=principal_id,
                follow_up_id=current.follow_up_id,
                stakeholder_ref=current.stakeholder_ref,
                topic=current.topic,
                status="open" if not status_open(current.status) else current.status,
                due_at=due_at or current.due_at,
                channel_hint=effective_channel_hint,
                notes=current.notes if details.strip() in {"", current.notes.strip()} else f"{current.notes}\n\nMerged candidate: {details.strip()}".strip(),
                source_json={
                    **source,
                    "counterparty": counterparty.strip() or str(source.get("counterparty") or ""),
                    "confidence": max(float(source.get("confidence") or 0.0), confidence),
                    "channel_hint": effective_channel_hint,
                    "source_type": effective_source_type,
                    "source_ref": effective_source_ref,
                    "signal_type": effective_signal_type,
                    "merged_from_refs": list(merged_from_refs),
                    "resolution_code": "" if not status_open(current.status) else str(source.get("resolution_code") or ""),
                    "resolution_reason": "" if not status_open(current.status) else str(source.get("resolution_reason") or ""),
                    "reopened_at": _now_iso() if not status_open(current.status) else str(source.get("reopened_at") or ""),
                },
            )
            self._record_product_event(
                principal_id=principal_id,
                event_type="commitment_merged" if status_open(current.status) else "commitment_reopened",
                payload={"candidate_id": candidate_id, "duplicate_of_ref": duplicate_ref, "title": title},
                source_id=current.follow_up_id,
            )
            return self._commitment_item_from_follow_up(updated, self._stakeholder_lookup(principal_id))
        return None

    def _handoff_from_human_task(self, task: HumanTask) -> HandoffNote:
        return handoff_from_human_task(task)

    def _provider_summary(self, registry: dict[str, object]) -> dict[str, object]:
        provider_rows = [dict(row) for row in (registry.get("providers") or []) if isinstance(row, dict)]
        lane_rows = [dict(row) for row in (registry.get("lanes") or []) if isinstance(row, dict)]
        provider_state_by_key: dict[str, str] = {}
        ready_keys: list[str] = []
        degraded_keys: list[str] = []
        failed_keys: list[str] = []
        unknown_keys: list[str] = []
        for row in provider_rows:
            provider_key = str(row.get("provider_key") or "").strip()
            state = str(row.get("state") or row.get("health_state") or "unknown").strip().lower() or "unknown"
            if provider_key:
                provider_state_by_key[provider_key] = state
            if state in _READY_PROVIDER_STATES:
                ready_keys.append(provider_key or state)
            elif state in _DEGRADED_PROVIDER_STATES:
                degraded_keys.append(provider_key or state)
            elif state in _FAILED_PROVIDER_STATES:
                failed_keys.append(provider_key or state)
            else:
                unknown_keys.append(provider_key or state)
        lanes_with_fallback = 0
        degraded_primary_lanes = 0
        failover_ready_lanes = 0
        for row in lane_rows:
            hint_order = [str(value).strip() for value in (row.get("provider_hint_order") or []) if str(value).strip()]
            if len(hint_order) > 1:
                lanes_with_fallback += 1
            primary_state = str(row.get("primary_state") or "unknown").strip().lower() or "unknown"
            if primary_state in (_DEGRADED_PROVIDER_STATES | _FAILED_PROVIDER_STATES):
                degraded_primary_lanes += 1
                secondary_states = [provider_state_by_key.get(key, "unknown") for key in hint_order[1:]]
                if any(state in (_READY_PROVIDER_STATES | _DEGRADED_PROVIDER_STATES) for state in secondary_states):
                    failover_ready_lanes += 1
        if failed_keys or (provider_rows and not ready_keys and not degraded_keys):
            risk_state = "critical"
            risk_detail = "At least one provider lane is failed or no ready provider remains bound for this workspace."
        elif degraded_keys or degraded_primary_lanes:
            risk_state = "watch"
            risk_detail = "At least one provider or primary routing lane is degraded and needs operator attention."
        elif not provider_rows:
            risk_state = "attention"
            risk_detail = "No providers are currently bound for this workspace."
        else:
            risk_state = "healthy"
            risk_detail = "Provider routing and failover posture are stable for the current workspace."
        return {
            "ready_count": len(ready_keys),
            "degraded_count": len(degraded_keys),
            "failed_count": len(failed_keys),
            "unknown_count": len(unknown_keys),
            "ready_provider_keys": ready_keys[:8],
            "degraded_provider_keys": degraded_keys[:8],
            "failed_provider_keys": failed_keys[:8],
            "lanes_with_fallback": lanes_with_fallback,
            "degraded_primary_lanes": degraded_primary_lanes,
            "failover_ready_lanes": failover_ready_lanes,
            "risk_state": risk_state,
            "risk_detail": risk_detail,
        }

    def _all_commitment_items(self, *, principal_id: str, limit: int) -> list[CommitmentItem]:
        stakeholders = self._stakeholder_lookup(principal_id)
        rows: list[CommitmentItem] = []
        for commitment in self._container.memory_runtime.list_commitments(principal_id=principal_id, limit=limit, status=None):
            rows.append(self._commitment_item_from_commitment(commitment))
        for follow_up in self._container.memory_runtime.list_follow_ups(principal_id=principal_id, limit=limit, status=None):
            rows.append(self._commitment_item_from_follow_up(follow_up, stakeholders))
        return rows

    def list_commitments(self, *, principal_id: str, limit: int = 50, include_closed: bool = False) -> tuple[CommitmentItem, ...]:
        rows = self._all_commitment_items(principal_id=principal_id, limit=limit)
        rows = rows if include_closed else [row for row in rows if status_open(row.status)]
        rows.sort(key=lambda row: (priority_weight(row.risk_level), due_bonus(row.due_at), row.statement.lower()), reverse=True)
        return tuple(rows[:limit])

    def list_recently_closed_commitments(self, *, principal_id: str, limit: int = 20) -> tuple[CommitmentItem, ...]:
        rows = [row for row in self._all_commitment_items(principal_id=principal_id, limit=max(limit * 3, 24)) if not status_open(row.status)]
        rows.sort(key=lambda row: (str(row.last_activity_at or ""), row.statement.lower()), reverse=True)
        return tuple(rows[:limit])

    def get_commitment(self, *, principal_id: str, commitment_ref: str) -> CommitmentItem | None:
        if commitment_ref.startswith("commitment:"):
            found = self._container.memory_runtime.get_commitment(commitment_ref.split(":", 1)[1], principal_id=principal_id)
            return None if found is None else self._commitment_item_from_commitment(found)
        if commitment_ref.startswith("follow_up:"):
            found = self._container.memory_runtime.get_follow_up(commitment_ref.split(":", 1)[1], principal_id=principal_id)
            if found is None:
                return None
            return self._commitment_item_from_follow_up(found, self._stakeholder_lookup(principal_id))
        return None

    def _event_matches_source_ids(self, *, wanted: set[str], source_id: str, payload: dict[str, object]) -> bool:
        if not wanted:
            return True
        refs = [
            source_id,
            str(payload.get("person_id") or "").strip(),
            str(payload.get("thread_ref") or "").strip(),
            str(payload.get("source_ref") or "").strip(),
            str(payload.get("draft_ref") or "").strip(),
            str(payload.get("handoff_ref") or "").strip(),
        ]
        return any(ref in wanted for ref in refs if ref)

    def _history_entries(self, *, principal_id: str, source_ids: tuple[str, ...] = (), limit: int = 20) -> tuple[HistoryEntry, ...]:
        wanted = {str(value).strip() for value in source_ids if str(value).strip()}
        rows: list[HistoryEntry] = []
        for row in self._container.channel_runtime.list_recent_observations(limit=200, principal_id=principal_id):
            if str(row.channel or "").strip() != "product":
                continue
            source_id = str(row.source_id or "").strip()
            payload = dict(row.payload or {})
            if not self._event_matches_source_ids(wanted=wanted, source_id=source_id, payload=payload):
                continue
            rows.append(
                HistoryEntry(
                    event_type=str(row.event_type or ""),
                    created_at=str(row.created_at or ""),
                    source_id=source_id,
                    actor=str(payload.get("actor") or payload.get("reviewer") or payload.get("decided_by") or ""),
                    detail=str(
                        payload.get("reason")
                        or payload.get("subject")
                        or payload.get("recipient_email")
                        or payload.get("resolution")
                        or payload.get("surface")
                        or payload.get("candidate_id")
                        or ""
                    ),
                )
            )
        rows.sort(key=lambda item: (str(item.created_at or ""), str(item.event_type or "")), reverse=True)
        return tuple(rows[:limit])

    def get_commitment_history(self, *, principal_id: str, commitment_ref: str, limit: int = 20) -> tuple[HistoryEntry, ...]:
        if ":" in commitment_ref:
            source_id = commitment_ref.split(":", 1)[1]
        else:
            source_id = commitment_ref
        return self._history_entries(principal_id=principal_id, source_ids=(source_id,), limit=limit)

    def _thread_item_from_event(
        self,
        *,
        event_type: str,
        created_at: str,
        payload: dict[str, object],
        commitments: tuple[CommitmentItem, ...],
        decisions: tuple[DecisionItem, ...],
    ) -> ThreadItem | None:
        thread_ref = str(payload.get("thread_ref") or payload.get("source_ref") or payload.get("draft_ref") or "").strip()
        if not thread_ref:
            return None
        thread_id = thread_ref if thread_ref.startswith("thread:") else f"thread:{thread_ref}"
        recipient_label = str(payload.get("recipient_label") or payload.get("recipient_email") or "").strip()
        recipient_email = str(payload.get("recipient_email") or "").strip()
        subject = str(payload.get("subject") or "").strip()
        resolution = str(payload.get("resolution") or "").strip()
        reason = str(payload.get("reason") or "").strip()
        draft_ref = str(payload.get("draft_ref") or "").strip()
        handoff_ref = str(payload.get("handoff_ref") or "").strip()
        source_ref = str(payload.get("source_ref") or "").strip()
        counterparties = self._append_unique_refs((), recipient_label, recipient_email)
        related_commitments = tuple(
            item.id
            for item in commitments
            if contains_token(item.counterparty, recipient_label)
            or contains_token(item.counterparty, recipient_email)
            or contains_token(item.statement, recipient_label)
            or contains_token(item.statement, thread_ref)
            or contains_token(item.source_ref, thread_ref)
        )
        related_decisions = tuple(
            item.id
            for item in decisions
            if contains_token(item.title, recipient_label)
            or contains_token(item.summary, recipient_label)
            or contains_token(item.summary, thread_ref)
        )
        status = {
            "draft_sent": "sent",
            "draft_send_followup_created": "delivery_followup",
            "draft_send_followup_reopened": "delivery_followup",
            "draft_send_followup_resolved": "sent" if resolution == "sent" else resolution or "delivery_followup",
            "draft_send_reauth_needed": "reauth_needed",
            "draft_send_failed": "delivery_failed",
        }.get(event_type, "active")
        summary = {
            "draft_sent": compact_text(subject, fallback="Reply was sent.", limit=160),
            "draft_send_followup_created": compact_text(reason, fallback="Manual send follow-up was created.", limit=160),
            "draft_send_followup_reopened": compact_text(reason, fallback="Manual send follow-up was reopened.", limit=160),
            "draft_send_followup_resolved": compact_text(
                reason or resolution,
                fallback="Manual send follow-up was resolved.",
                limit=160,
            ),
            "draft_send_reauth_needed": compact_text(reason, fallback="Google reauth is required before send.", limit=160),
            "draft_send_failed": compact_text(reason, fallback="Reply send failed.", limit=160),
        }.get(event_type, compact_text(subject or reason, fallback="Thread activity was recorded.", limit=160))
        evidence_refs: list[EvidenceRef] = []
        for ref_id, label, source_type, note in (
            (draft_ref, "Draft", "approval", event_type.replace("_", " ")),
            (source_ref, "Source", "signal", subject or reason),
            (handoff_ref, "Delivery handoff", "human_task", reason or resolution),
        ):
            if ref_id and all(existing.ref_id != ref_id for existing in evidence_refs):
                evidence_refs.append(EvidenceRef(ref_id=ref_id, label=label, source_type=source_type, note=note))
        return ThreadItem(
            id=thread_id,
            title=recipient_label or recipient_email or subject or thread_ref,
            channel=str(payload.get("channel") or "email"),
            status=status,
            last_activity_at=created_at or None,
            summary=summary,
            counterparties=counterparties,
            draft_ids=(draft_ref,) if draft_ref else (),
            related_commitment_ids=related_commitments,
            related_decision_ids=related_decisions,
            evidence_refs=tuple(evidence_refs),
        )

    def _thread_items_from_events(
        self,
        *,
        principal_id: str,
        commitments: tuple[CommitmentItem, ...],
        decisions: tuple[DecisionItem, ...],
        limit: int,
    ) -> tuple[ThreadItem, ...]:
        rows: dict[str, ThreadItem] = {}
        for row in self._container.channel_runtime.list_recent_observations(limit=max(limit * 10, 200), principal_id=principal_id):
            if str(row.channel or "").strip() != "product":
                continue
            event_type = str(row.event_type or "").strip().lower()
            if event_type not in {"draft_sent", "draft_send_followup_created", "draft_send_followup_reopened", "draft_send_followup_resolved", "draft_send_reauth_needed", "draft_send_failed"}:
                continue
            projected = self._thread_item_from_event(
                event_type=event_type,
                created_at=str(row.created_at or ""),
                payload=dict(row.payload or {}),
                commitments=commitments,
                decisions=decisions,
            )
            if projected is None:
                continue
            current = rows.get(projected.id)
            if current is None or str(projected.last_activity_at or "") > str(current.last_activity_at or ""):
                rows[projected.id] = projected
        ordered = sorted(rows.values(), key=lambda item: (str(item.last_activity_at or ""), item.title.lower()), reverse=True)
        return tuple(ordered[:limit])

    def _event_object_refs(self, *, source_id: str, payload: dict[str, object]) -> tuple[str, ...]:
        refs: list[str] = []
        for key in (
            "commitment_ref",
            "decision_ref",
            "thread_ref",
            "evidence_ref",
            "rule_ref",
            "handoff_ref",
            "draft_ref",
        ):
            value = str(payload.get(key) or "").strip()
            if value:
                refs.append(value)
        for key in ("commitment_refs", "decision_refs", "thread_refs", "evidence_refs", "rule_refs"):
            for value in (payload.get(key) or []):
                normalized = str(value or "").strip()
                if normalized:
                    refs.append(normalized)
        normalized_source = str(source_id or "").strip()
        if normalized_source:
            refs.append(normalized_source)
        return self._append_unique_refs(refs)

    def list_office_events(
        self,
        *,
        principal_id: str,
        limit: int = 50,
        event_type: str = "",
        channel: str = "",
    ) -> tuple[dict[str, object], ...]:
        wanted_type = str(event_type or "").strip().lower()
        wanted_channel = str(channel or "").strip().lower()
        rows: list[dict[str, object]] = []
        for row in self._container.channel_runtime.list_recent_observations(limit=max(limit * 4, 200), principal_id=principal_id):
            normalized_channel = str(row.channel or "").strip().lower()
            normalized_type = str(row.event_type or "").strip().lower()
            if wanted_channel and normalized_channel != wanted_channel:
                continue
            if wanted_type and normalized_type != wanted_type:
                continue
            payload = dict(row.payload or {})
            summary = (
                str(payload.get("summary") or "").strip()
                or str(payload.get("title") or "").strip()
                or str(payload.get("reason") or "").strip()
                or str(payload.get("text") or "").strip()
                or str(payload.get("surface") or "").strip()
                or normalized_type.replace("_", " ")
            )
            rows.append(
                {
                    "observation_id": str(row.observation_id or ""),
                    "channel": str(row.channel or ""),
                    "event_type": str(row.event_type or ""),
                    "created_at": str(row.created_at or ""),
                    "source_id": str(row.source_id or ""),
                    "external_id": str(row.external_id or ""),
                    "summary": summary[:220],
                    "object_refs": list(self._event_object_refs(source_id=str(row.source_id or ""), payload=payload)),
                    "payload": payload,
                }
            )
        rows.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("observation_id") or "")), reverse=True)
        return tuple(rows[:limit])

    def ingest_office_signal(
        self,
        *,
        principal_id: str,
        signal_type: str,
        channel: str = "office_api",
        title: str = "",
        summary: str = "",
        text: str = "",
        source_ref: str = "",
        external_id: str = "",
        counterparty: str = "",
        stakeholder_id: str = "",
        due_at: str | None = None,
        payload: dict[str, object] | None = None,
        actor: str = "",
    ) -> dict[str, object]:
        normalized_signal = str(signal_type or "").strip().lower()
        normalized_channel = str(channel or "office_api").strip().lower() or "office_api"
        summary_text = str(summary or "").strip()
        title_text = str(title or "").strip()
        source_text = str(text or "").strip() or " ".join(part for part in (title_text, summary_text) if part).strip()
        payload_json = dict(payload or {})
        is_willhaben_search_agent = (
            normalized_channel == "gmail"
            and normalized_signal == "email_thread"
            and _is_willhaben_search_agent_email(
                title=title_text,
                summary=summary_text,
                counterparty=counterparty,
                payload=payload_json,
            )
        )
        stable_external_identity = bool(str(external_id or "").strip() or str(source_ref or "").strip())
        source_text_fragment = source_text[:80]
        if normalized_channel == "pocket" and stable_external_identity:
            source_text_fragment = ""
        suppress_candidate_staging = (
            normalized_channel == "gmail"
            and normalized_signal == "email_thread"
            and _is_assistant_originated_delivery_email(
                title=title_text,
                summary=summary_text,
                payload=payload_json,
            )
        )
        suppress_candidate_staging = suppress_candidate_staging or is_willhaben_search_agent or bool(payload_json.get("suppress_candidate_staging"))
        property_alert_review_result = self._maybe_open_property_alert_review_from_signal(
            principal_id=principal_id,
            signal_type=normalized_signal,
            channel=normalized_channel,
            title=title_text,
            summary=summary_text,
            text=source_text,
            source_ref=str(source_ref or "").strip(),
            external_id=str(external_id or "").strip(),
            counterparty=str(counterparty or "").strip(),
            payload=payload_json,
            actor=str(actor or "").strip() or "office_api",
        )
        dedupe_parts = [
            "office-signal",
            principal_id,
            normalized_signal,
            str(external_id or "").strip(),
            str(source_ref or "").strip(),
            source_text_fragment,
        ]
        dedupe_key = "|".join(part for part in dedupe_parts if part)
        existing_event = self._existing_office_signal_event(
            principal_id=principal_id,
            dedupe_key=dedupe_key,
            channel=normalized_channel,
            signal_type=normalized_signal,
            source_ref=str(source_ref or "").strip(),
            external_id=str(external_id or "").strip(),
            stable_external_identity=stable_external_identity,
        )
        if existing_event is not None:
            existing_candidates = self._matching_staged_signal_candidates(
                principal_id=principal_id,
                source_ref=str(source_ref or "").strip(),
            )
            if suppress_candidate_staging and existing_candidates:
                for row in existing_candidates:
                    self.reject_commitment_candidate(
                        principal_id=principal_id,
                        candidate_id=str(row.candidate_id or "").strip(),
                        reviewer="signal_sync",
                    )
                existing_candidates = ()
            existing_draft_approval = self._find_pending_signal_draft_approval(
                principal_id=principal_id,
                source_ref=str(source_ref or "").strip(),
                recipient_email=str(payload_json.get("from_email") or "").strip().lower(),
            )
            existing_drafts = (self._draft_from_approval(existing_draft_approval),) if existing_draft_approval is not None else ()
            existing_payload = dict(getattr(existing_event, "payload", {}) or {})
            existing_ooda_loop = self._attach_property_alert_review_to_ooda_loop(
                ooda_loop=existing_payload.get("ooda_loop"),
                review_result=property_alert_review_result,
            )
            return {
                "observation_id": str(existing_event.observation_id or ""),
                "channel": str(existing_event.channel or normalized_channel),
                "event_type": str(existing_event.event_type or f"office_signal_{normalized_signal}"),
                "source_id": str(existing_event.source_id or source_ref or "").strip(),
                "external_id": str(existing_event.external_id or external_id or "").strip(),
                "created_at": str(existing_event.created_at or ""),
                "staged_candidates": [self._commitment_candidate_payload(row) for row in existing_candidates],
                "staged_drafts": [self._draft_payload(row) for row in existing_drafts],
                "staged_count": len(existing_candidates),
                "draft_count": len(existing_drafts),
                "deduplicated": True,
                "ooda_loop": existing_ooda_loop,
            }
        allow_generic_fallback = False
        if not suppress_candidate_staging:
            allow_generic_fallback = self._allow_generic_signal_candidate_fallback(
                signal_type=normalized_signal,
                channel=normalized_channel,
                title=title_text,
                summary=summary_text,
                counterparty=counterparty,
                stakeholder_id=stakeholder_id,
                payload=payload_json,
            )
        staged = self.stage_extracted_commitments(
            principal_id=principal_id,
            text=source_text,
            counterparty=counterparty,
            due_at=due_at,
            kind=(
                "follow_up"
                if "follow" in normalized_signal or "meeting" in normalized_signal or (normalized_channel == "calendar" and (counterparty.strip() or stakeholder_id.strip()))
                else "commitment"
            ),
            stakeholder_id=self._resolve_stakeholder_ref(
                principal_id=principal_id,
                stakeholder_id=stakeholder_id,
                counterparty=counterparty,
            ),
            channel_hint=normalized_channel,
            source_ref=str(source_ref or "").strip(),
            signal_type=normalized_signal,
            reference_at=str(payload_json.get("received_at") or payload_json.get("start_at") or _now_iso()).strip(),
            allow_generic_fallback=allow_generic_fallback,
        ) if source_text and not suppress_candidate_staging else ()
        staged_draft = self._stage_signal_reply_draft(
            principal_id=principal_id,
            signal_type=normalized_signal,
            channel=normalized_channel,
            title=title_text,
            summary=summary_text,
            text=source_text,
            source_ref=str(source_ref or "").strip(),
            external_id=str(external_id or "").strip(),
            counterparty=str(counterparty or "").strip(),
            stakeholder_id=str(stakeholder_id or "").strip(),
            due_at=due_at,
            payload=payload_json,
            staged_candidates=staged,
        )
        resolved_signal_source_id = str(source_ref or external_id or dedupe_key).strip()
        base_payload_json = {
            "signal_type": normalized_signal,
            "title": title_text,
            "summary": summary_text,
            "text": source_text,
            "counterparty": str(counterparty or "").strip(),
            "stakeholder_id": str(stakeholder_id or "").strip(),
            "due_at": str(due_at or "").strip(),
            "actor": str(actor or "").strip() or "office_api",
            "staged_candidate_ids": [row.candidate_id for row in staged if str(row.candidate_id or "").strip()],
            "staged_draft_ids": [staged_draft.id] if staged_draft is not None else [],
            **dict(payload or {}),
        }
        automated_signal_result: dict[str, object] | None = None
        ooda_loop: dict[str, object] = {}
        automated_signal_result = self._maybe_create_willhaben_property_tour_from_signal(
            principal_id=principal_id,
            title=title_text,
            summary=summary_text,
            text=source_text,
            source_ref=resolved_signal_source_id,
            external_id=str(external_id or "").strip(),
            counterparty=str(counterparty or "").strip(),
            payload=base_payload_json,
            actor=str(actor or "").strip() or "office_api",
        )
        try:
            ooda_loop = self._build_email_signal_ooda_loop(
                signal_type=normalized_signal,
                channel=normalized_channel,
                title=title_text,
                summary=summary_text,
                text=source_text,
                source_ref=str(source_ref or "").strip(),
                external_id=str(external_id or "").strip(),
                counterparty=str(counterparty or "").strip(),
                due_at=due_at,
                payload=base_payload_json,
                actor=str(actor or "").strip() or "office_api",
                staged_candidates=staged,
                staged_draft=staged_draft,
                automated_result=automated_signal_result,
            )
        except Exception as exc:
            ooda_loop = {
                "reviewed": False,
                "reviewed_at": _now_iso(),
                "summary": "Signal OODA loop failed.",
                "error": compact_text(str(exc or ""), fallback="signal_ooda_failed", limit=220),
            }
        ooda_loop = self._attach_property_alert_review_to_ooda_loop(
            ooda_loop=ooda_loop,
            review_result=property_alert_review_result,
        )
        payload_json = {
            **base_payload_json,
            "ooda_loop": dict(ooda_loop or {}),
        }
        event = self._container.channel_runtime.ingest_observation(
            principal_id=principal_id,
            channel=normalized_channel,
            event_type=f"office_signal_{normalized_signal}",
            payload=payload_json,
            source_id=str(source_ref or "").strip(),
            external_id=str(external_id or "").strip(),
            dedupe_key=dedupe_key,
        )
        self._queue_webhook_deliveries(
            principal_id=principal_id,
            matched_event_type=str(event.event_type or ""),
            payload=payload_json,
            source_id=str(source_ref or event.observation_id or "").strip(),
            external_id=str(external_id or "").strip(),
        )
        self._record_product_event(
            principal_id=principal_id,
            event_type="office_signal_ingested",
            payload={
                "signal_type": normalized_signal,
                "channel": normalized_channel,
                "source_ref": str(source_ref or "").strip(),
                "external_id": str(external_id or "").strip(),
                "staged_count": len(staged),
                "draft_count": 1 if staged_draft is not None else 0,
                "ooda_recommended_ltd_count": len(list((ooda_loop or {}).get("ltd_review", {}).get("recommended_actions") or [])),
            },
            source_id=str(resolved_signal_source_id or event.observation_id or "").strip(),
        )
        if ooda_loop:
            self._record_product_event(
                principal_id=principal_id,
                event_type="office_signal_ooda_evaluated",
                payload={
                    "channel": normalized_channel,
                    "signal_type": normalized_signal,
                    "source_ref": str(source_ref or "").strip(),
                    "external_id": str(external_id or "").strip(),
                    "counterparty": str(counterparty or "").strip(),
                    "summary": str(ooda_loop.get("summary") or "").strip(),
                    "ooda_loop": dict(ooda_loop or {}),
                },
                source_id=str(resolved_signal_source_id or event.observation_id or "").strip(),
                dedupe_key=f"{principal_id}|{dedupe_key}|office-signal-ooda",
            )
        return {
            "observation_id": str(event.observation_id or ""),
            "channel": str(event.channel or ""),
            "event_type": str(event.event_type or ""),
            "source_id": str(event.source_id or ""),
            "external_id": str(event.external_id or ""),
            "created_at": str(event.created_at or ""),
            "staged_candidates": [self._commitment_candidate_payload(row) for row in staged],
            "staged_drafts": [self._draft_payload(row) for row in (staged_draft,) if staged_draft is not None],
            "staged_count": len(staged),
            "draft_count": 1 if staged_draft is not None else 0,
            "deduplicated": False,
            "ooda_loop": dict(ooda_loop or {}),
        }

    def _existing_property_alert_review_task(
        self,
        *,
        principal_id: str,
        source_ref: str,
        external_id: str,
    ) -> HumanTask | None:
        normalized_source = str(source_ref or "").strip()
        normalized_external = str(external_id or "").strip()
        if not normalized_source and not normalized_external:
            return None
        for row in self._container.orchestrator.list_human_tasks(principal_id=principal_id, status="pending", limit=200):
            if str(getattr(row, "task_type", "") or "").strip() != "property_alert_review":
                continue
            input_json = dict(getattr(row, "input_json", {}) or {})
            if normalized_source and str(input_json.get("source_ref") or "").strip() == normalized_source:
                return row
            if normalized_external and str(input_json.get("external_id") or "").strip() == normalized_external:
                return row
        return None

    def _open_property_alert_review(
        self,
        *,
        principal_id: str,
        title: str,
        summary: str,
        source_ref: str,
        external_id: str,
        counterparty: str,
        account_email: str,
        property_url: str,
        actor: str,
    ) -> dict[str, object]:
        existing = self._existing_property_alert_review_task(
            principal_id=principal_id,
            source_ref=source_ref,
            external_id=external_id,
        )
        if existing is not None:
            return {
                "status": "existing",
                "human_task_id": f"human_task:{existing.human_task_id}",
                "queue_item_ref": f"human_task:{existing.human_task_id}",
                "task_type": "property_alert_review",
                "property_url": property_url,
                "source_ref": source_ref,
                "external_id": external_id,
                "recommended_task_key": projected_task_key("Crezlo Tours", "create_property_tour"),
            }
        session_id = self._start_product_review_session(
            principal_id=principal_id,
            goal=f"Review apartment alert for {title or counterparty or 'Willhaben'}",
            source_ref=source_ref or external_id,
        )
        task = self._container.orchestrator.create_human_task(
            session_id=session_id,
            principal_id=principal_id,
            task_type="property_alert_review",
            role_required="operator",
            brief=_property_alert_review_brief(title),
            why_human="Apartment-search mail should stay visible as a review item, not a fake commitment. Decide whether to open the listing, generate a tour, or ignore the alert.",
            priority="normal",
            input_json={
                "title": str(title or "").strip(),
                "summary": str(summary or "").strip(),
                "counterparty": str(counterparty or "").strip(),
                "account_email": str(account_email or "").strip().lower(),
                "property_url": str(property_url or "").strip(),
                "source_ref": str(source_ref or "").strip(),
                "external_id": str(external_id or "").strip(),
                "recommended_task_key": projected_task_key("Crezlo Tours", "create_property_tour"),
            },
            desired_output_json={
                "resolution": "reviewed",
                "selected_action": "",
                "property_url": str(property_url or "").strip(),
                "notes": "",
            },
        )
        payload = {
            "status": "opened",
            "human_task_id": f"human_task:{task.human_task_id}",
            "queue_item_ref": f"human_task:{task.human_task_id}",
            "task_type": "property_alert_review",
            "property_url": str(property_url or "").strip(),
            "source_ref": str(source_ref or "").strip(),
            "external_id": str(external_id or "").strip(),
            "recommended_task_key": projected_task_key("Crezlo Tours", "create_property_tour"),
        }
        self._record_product_event(
            principal_id=principal_id,
            event_type="property_alert_review_created",
            payload={
                **payload,
                "title": str(title or "").strip(),
                "summary": str(summary or "").strip(),
                "counterparty": str(counterparty or "").strip(),
                "account_email": str(account_email or "").strip().lower(),
                "actor": str(actor or "").strip() or "office_api",
            },
            source_id=str(source_ref or external_id or task.human_task_id).strip(),
            dedupe_key=f"{principal_id}|{source_ref or external_id or task.human_task_id}|property-alert-review-created",
        )
        return payload

    def _maybe_open_property_alert_review_from_signal(
        self,
        *,
        principal_id: str,
        signal_type: str,
        channel: str,
        title: str,
        summary: str,
        text: str,
        source_ref: str,
        external_id: str,
        counterparty: str,
        payload: dict[str, object],
        actor: str,
    ) -> dict[str, object] | None:
        if str(signal_type or "").strip().lower() != "email_thread":
            return None
        if str(channel or "").strip().lower() != "gmail":
            return None
        if not _is_willhaben_search_agent_email(
            title=title,
            summary=summary,
            counterparty=counterparty,
            payload=payload,
        ):
            return None
        auto_create_spec = _willhaben_search_agent_auto_create_spec(
            principal_id=principal_id,
            title=title,
            summary=summary,
            text=text,
            source_ref=source_ref,
            external_id=external_id,
            counterparty=counterparty,
            payload=payload,
        )
        if auto_create_spec is not None:
            return None
        property_url = _willhaben_property_url_from_signal(
            title=title,
            summary=summary,
            text=text,
            source_ref=source_ref,
            external_id=external_id,
            payload=payload,
        )
        return self._open_property_alert_review(
            principal_id=principal_id,
            title=title,
            summary=summary,
            source_ref=source_ref,
            external_id=external_id,
            counterparty=counterparty,
            account_email=str(payload.get("account_email") or "").strip().lower(),
            property_url=property_url,
            actor=actor,
        )

    def _attach_property_alert_review_to_ooda_loop(
        self,
        *,
        ooda_loop: object,
        review_result: dict[str, object] | None,
    ) -> dict[str, object]:
        updated = dict(ooda_loop or {}) if isinstance(ooda_loop, dict) else {}
        if review_result is None:
            return updated
        decide = dict(updated.get("decide") or {})
        recommended_actions = [str(value or "").strip() for value in list(decide.get("recommended_actions") or []) if str(value or "").strip()]
        if "open_property_alert_review" not in recommended_actions:
            recommended_actions.append("open_property_alert_review")
        decide["recommended_actions"] = recommended_actions
        decide_summary = str(decide.get("summary") or "").strip()
        review_note = "Keep the apartment alert as a review item instead of staging a fake commitment."
        if review_note not in decide_summary:
            decide["summary"] = compact_text(" ".join(part for part in (decide_summary, review_note) if part), fallback=review_note, limit=220)
        updated["decide"] = decide

        act = dict(updated.get("act") or {})
        executed_actions = [str(value or "").strip() for value in list(act.get("executed_actions") or []) if str(value or "").strip()]
        if "property_alert_review_queued" not in executed_actions:
            executed_actions.append("property_alert_review_queued")
        act["executed_actions"] = executed_actions
        automated_actions = [dict(item) for item in list(act.get("automated_actions") or []) if isinstance(item, dict)]
        human_task_id = str(review_result.get("human_task_id") or "").strip()
        if not any(
            str(item.get("action_key") or "").strip() == "review_property_alert"
            and str(item.get("human_task_id") or "").strip() == human_task_id
            for item in automated_actions
        ):
            automated_actions.append(
                {
                    "action_key": "review_property_alert",
                    "service_name": "Executive Assistant",
                    "status": str(review_result.get("status") or "").strip() or "opened",
                    "human_task_id": human_task_id,
                    "queue_item_ref": str(review_result.get("queue_item_ref") or human_task_id).strip(),
                    "task_type": str(review_result.get("task_type") or "property_alert_review").strip(),
                    "property_url": str(review_result.get("property_url") or "").strip(),
                    "recommended_task_key": str(review_result.get("recommended_task_key") or "").strip(),
                }
            )
        act["automated_actions"] = automated_actions
        act_summary = str(act.get("summary") or "").strip()
        act_note = "Opened an apartment-alert review item so the alert stays visible in the queue without becoming a fake commitment."
        if act_note not in act_summary:
            act["summary"] = compact_text(" ".join(part for part in (act_summary, act_note) if part), fallback=act_note, limit=220)
        updated["act"] = act

        summary_text = str(updated.get("summary") or "").strip()
        if act_note not in summary_text:
            updated["summary"] = compact_text(" ".join(part for part in (summary_text, act_note) if part), fallback=act_note, limit=240)
        return updated

    def _existing_office_signal_event(
        self,
        *,
        principal_id: str,
        dedupe_key: str,
        channel: str,
        signal_type: str,
        source_ref: str,
        external_id: str,
        stable_external_identity: bool,
    ):
        existing = self._container.channel_runtime.find_observation_by_dedupe(
            dedupe_key,
            principal_id=principal_id,
        )
        if existing is not None:
            return existing
        if str(channel or "").strip().lower() != "pocket" or not stable_external_identity:
            return None
        expected_event_type = f"office_signal_{str(signal_type or '').strip().lower()}"
        wanted_source_ref = str(source_ref or "").strip()
        wanted_external_id = str(external_id or "").strip()
        if not wanted_source_ref and not wanted_external_id:
            return None
        for row in self._container.channel_runtime.list_recent_observations(
            limit=_POCKET_SIGNAL_DEDUPE_LOOKBACK,
            principal_id=principal_id,
        ):
            if str(getattr(row, "channel", "") or "").strip().lower() != "pocket":
                continue
            if str(getattr(row, "event_type", "") or "").strip().lower() != expected_event_type:
                continue
            row_source_id = str(getattr(row, "source_id", "") or "").strip()
            row_external_id = str(getattr(row, "external_id", "") or "").strip()
            if wanted_source_ref and row_source_id == wanted_source_ref:
                return row
            if wanted_external_id and row_external_id == wanted_external_id:
                return row
        return None

    def _signal_ltd_review(
        self,
        *,
        title: str,
        summary: str,
        text: str,
        source_ref: str,
        external_id: str,
        counterparty: str,
        payload: dict[str, object],
        source_label: str = "signal",
    ) -> dict[str, object]:
        try:
            catalog = LtdRuntimeCatalogService(provider_registry=self._container.provider_registry)
            profiles = catalog.list_profiles()
        except Exception as exc:
            return {
                "reviewed": False,
                "profiles_considered": 0,
                "reviewed_action_count": 0,
                "recommended_actions": [],
                "summary": compact_text(
                    f"LTD review was not available for this {source_label}.",
                    fallback="LTD review unavailable for this signal.",
                    limit=220,
                ),
                "error": compact_text(str(exc or ""), fallback="ltd_runtime_catalog_unavailable", limit=180),
            }

        action_index: dict[tuple[str, str], tuple[object, object]] = {}
        reviewed_action_count = 0
        for profile in profiles:
            normalized_service = _normalized_ltd_lookup(getattr(profile, "service_name", ""))
            for action in getattr(profile, "actions", ()) or ():
                normalized_action = _normalized_ltd_lookup(getattr(action, "action_key", ""))
                if not normalized_action or normalized_action == "discover_account":
                    continue
                reviewed_action_count += 1
                action_index.setdefault((normalized_service, normalized_action), (profile, action))

        combined_text = " ".join(
            part
            for part in (
                str(title or "").strip(),
                str(summary or "").strip(),
                str(text or "").strip(),
                str(counterparty or "").strip(),
                str(source_ref or "").strip(),
                str(external_id or "").strip(),
                str(payload.get("snippet") or "").strip(),
                str(payload.get("body_text_excerpt") or "").strip(),
            )
            if part
        ).lower()
        all_urls = self._append_unique_refs(
            (),
            *(
                _extract_urls_from_text(title)
                + _extract_urls_from_text(summary)
                + _extract_urls_from_text(text)
                + _extract_urls_from_text(source_ref)
                + _extract_urls_from_text(external_id)
            ),
            str(payload.get("property_url") or "").strip(),
            str(payload.get("captured_url") or "").strip(),
            str(payload.get("url") or "").strip(),
            str(payload.get("href") or "").strip(),
        )
        property_url = next((value for value in all_urls if _is_willhaben_property_url(value)), "")
        wants_property_tour = bool(property_url) or _contains_any_marker(combined_text, _EMAIL_PROPERTY_MARKERS)
        wants_approval_review = _contains_any_marker(combined_text, _EMAIL_APPROVAL_MARKERS)
        wants_documentation = _contains_any_marker(combined_text, _EMAIL_DOCUMENTATION_MARKERS)
        wants_markup_review = _contains_any_marker(combined_text, _EMAIL_MARKUP_MARKERS)
        wants_background_remove = _contains_any_marker(combined_text, _EMAIL_IMAGE_BACKGROUND_MARKERS)
        wants_image_upscale = _contains_any_marker(combined_text, _EMAIL_IMAGE_UPSCALE_MARKERS)
        wants_image_generate = _contains_any_marker(combined_text, _EMAIL_IMAGE_GENERATION_MARKERS)
        wants_delivery = _contains_any_marker(combined_text, _EMAIL_DELIVERY_MARKERS)
        delivery_email = _first_non_empty_text(
            payload.get("delivery_recipient_email"),
            payload.get("notify_email"),
            payload.get("recipient_email"),
        ).lower()

        recommendations: list[dict[str, object]] = []

        def _add_recommendation(
            *,
            service_key: str,
            action_key: str,
            reason: str,
            score: int,
            context_json: dict[str, object] | None = None,
        ) -> None:
            matched = action_index.get((_normalized_ltd_lookup(service_key), _normalized_ltd_lookup(action_key)))
            if matched is None:
                return
            profile, action = matched
            recommendations.append(
                {
                    "service_name": str(getattr(profile, "service_name", "") or ""),
                    "runtime_state": str(getattr(profile, "runtime_state", "") or ""),
                    "action_key": str(getattr(action, "action_key", "") or ""),
                    "label": str(getattr(action, "label", "") or ""),
                    "description": str(getattr(action, "description", "") or ""),
                    "execution_mode": str(getattr(action, "execution_mode", "") or ""),
                    "executable": bool(getattr(action, "executable", False)),
                    "provider_key": str(getattr(action, "provider_key", "") or ""),
                    "route_path": str(getattr(action, "route_path", "") or ""),
                    "task_key": projected_task_key(
                        str(getattr(profile, "service_name", "") or ""),
                        str(getattr(action, "action_key", "") or ""),
                    ),
                    "reason": compact_text(reason, fallback="Relevant LTD action.", limit=220),
                    "score": score,
                    "context": dict(context_json or {}),
                    "notes": str(getattr(action, "notes", "") or ""),
                }
            )

        if wants_property_tour:
            _add_recommendation(
                service_key="Crezlo Tours",
                action_key="create_property_tour",
                reason="Signal references a property listing or apartment-tour workflow that fits the Crezlo tour lane.",
                score=100 if property_url else 82,
                context_json={"property_url": property_url},
            )
        if wants_approval_review:
            _add_recommendation(
                service_key="ApproveThis",
                action_key="read_queue",
                reason="Signal reads like an approval or sign-off request that should check the external approval queue.",
                score=70,
            )
        if wants_documentation:
            _add_recommendation(
                service_key="Documentation.AI",
                action_key="inspect_workspace",
                reason="Signal asks for docs, handbooks, or knowledge-base work that fits the Documentation.AI workspace lane.",
                score=66,
            )
        if wants_markup_review:
            _add_recommendation(
                service_key="MarkupGo",
                action_key="inspect_workspace",
                reason="Signal mentions a deck, PDF, packet, or markup-style review that fits the MarkupGo workspace lane.",
                score=64,
            )
        if wants_background_remove:
            _add_recommendation(
                service_key="1min.AI",
                action_key="background_remove",
                reason="Signal asks for image cleanup or background removal that fits the 1min.AI media lane.",
                score=72,
            )
        if wants_image_upscale:
            _add_recommendation(
                service_key="1min.AI",
                action_key="image_upscale",
                reason="Signal asks for higher-resolution image output that fits the 1min.AI upscaling lane.",
                score=71,
            )
        if wants_image_generate:
            _add_recommendation(
                service_key="1min.AI",
                action_key="image_generate",
                reason="Signal asks for a render, mockup, illustration, or other generated visual.",
                score=63,
            )
        if delivery_email or wants_delivery:
            _add_recommendation(
                service_key="Emailit",
                action_key="delivery_outbox",
                reason="Signal implies a link or outcome that may need external delivery through the managed email outbox.",
                score=55 if delivery_email else 48,
                context_json={"delivery_email": delivery_email},
            )

        recommendations.sort(
            key=lambda item: (
                -int(item.get("score") or 0),
                not bool(item.get("executable")),
                str(item.get("service_name") or "").lower(),
                str(item.get("action_key") or "").lower(),
            )
        )
        trimmed = recommendations[:4]
        if trimmed:
            summary_text = f"Reviewed {reviewed_action_count} LTD actions and recommended {len(trimmed)}."
        else:
            summary_text = f"Reviewed {reviewed_action_count} LTD actions and found no additional lane worth invoking."
        for row in trimmed:
            row.pop("score", None)
        return {
            "reviewed": True,
            "profiles_considered": len(profiles),
            "reviewed_action_count": reviewed_action_count,
            "recommended_actions": trimmed,
            "summary": summary_text,
        }

    def _email_signal_ltd_review(
        self,
        *,
        title: str,
        summary: str,
        text: str,
        source_ref: str,
        external_id: str,
        counterparty: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        return self._signal_ltd_review(
            title=title,
            summary=summary,
            text=text,
            source_ref=source_ref,
            external_id=external_id,
            counterparty=counterparty,
            payload=payload,
            source_label="email",
        )

    def _build_email_signal_ooda_loop(
        self,
        *,
        signal_type: str,
        channel: str,
        title: str,
        summary: str,
        text: str,
        source_ref: str,
        external_id: str,
        counterparty: str,
        due_at: str | None,
        payload: dict[str, object],
        actor: str,
        staged_candidates: tuple[CommitmentCandidate, ...],
        staged_draft: DraftCandidate | None,
        automated_result: dict[str, object] | None = None,
    ) -> dict[str, object]:
        normalized_signal_type = str(signal_type or "email_thread").strip().lower() or "email_thread"
        ltd_review = self._signal_ltd_review(
            title=title,
            summary=summary,
            text=text,
            source_ref=source_ref,
            external_id=external_id,
            counterparty=counterparty,
            payload=payload,
            source_label="email" if normalized_signal_type == "email_thread" else "signal",
        )
        combined_text = " ".join(
            part
            for part in (
                str(title or "").strip(),
                str(summary or "").strip(),
                str(text or "").strip(),
                str(counterparty or "").strip(),
                str(payload.get("snippet") or "").strip(),
                str(payload.get("body_text_excerpt") or "").strip(),
            )
            if part
        ).lower()
        all_urls = self._append_unique_refs(
            (),
            *(
                _extract_urls_from_text(title)
                + _extract_urls_from_text(summary)
                + _extract_urls_from_text(text)
                + _extract_urls_from_text(source_ref)
                + _extract_urls_from_text(external_id)
            ),
            str(payload.get("property_url") or "").strip(),
            str(payload.get("captured_url") or "").strip(),
            str(payload.get("url") or "").strip(),
            str(payload.get("href") or "").strip(),
        )
        property_url = next((value for value in all_urls if _is_willhaben_property_url(value)), "")

        orientation_tags: list[str] = []
        orientation_notes: list[str] = []
        if _contains_any_marker(combined_text, _REPLY_SIGNAL_CUES):
            orientation_tags.append("reply_or_follow_up")
            orientation_notes.append("Signal reads like a reply or follow-up request.")
        if str(due_at or "").strip() or _contains_any_marker(combined_text, _EMAIL_DEADLINE_MARKERS):
            orientation_tags.append("deadline_or_urgency")
            orientation_notes.append("Signal includes urgency or a timing cue.")
        if property_url or _contains_any_marker(combined_text, _EMAIL_PROPERTY_MARKERS):
            orientation_tags.append("property_workflow")
            orientation_notes.append("Signal references property-search or tour work.")
        if _contains_any_marker(combined_text, _EMAIL_APPROVAL_MARKERS):
            orientation_tags.append("approval_context")
            orientation_notes.append("Signal looks like an approval or sign-off surface.")
        if _contains_any_marker(combined_text, _EMAIL_DOCUMENTATION_MARKERS):
            orientation_tags.append("documentation_request")
            orientation_notes.append("Signal asks for docs or knowledge-base work.")
        if _contains_any_marker(combined_text, _EMAIL_MARKUP_MARKERS):
            orientation_tags.append("asset_review")
            orientation_notes.append("Signal mentions a packet, deck, PDF, or markup review.")
        if _contains_any_marker(combined_text, _EMAIL_IMAGE_BACKGROUND_MARKERS + _EMAIL_IMAGE_UPSCALE_MARKERS + _EMAIL_IMAGE_GENERATION_MARKERS):
            orientation_tags.append("visual_asset_request")
            orientation_notes.append("Signal asks for visual or media work.")
        if not orientation_notes:
            orientation_notes.append("Signal was reviewed for commitments, delivery intent, and automation opportunities.")

        recommended_ltd_actions = list(ltd_review.get("recommended_actions") or [])
        decide_actions: list[str] = []
        decide_notes: list[str] = []
        if staged_candidates:
            decide_actions.append("stage_commitment_candidates")
            decide_notes.append(f"Stage {len(staged_candidates)} commitment candidate{'s' if len(staged_candidates) != 1 else ''}.")
        else:
            decide_notes.append("No commitment candidate was strong enough to stage from this signal.")
        if staged_draft is not None:
            decide_actions.append("stage_reply_draft")
            decide_notes.append("Prepare a reply draft for approval before send.")
        if recommended_ltd_actions:
            decide_actions.append("review_ltd_actions")
            decide_notes.append(f"Review {len(recommended_ltd_actions)} LTD action recommendation{'s' if len(recommended_ltd_actions) != 1 else ''}.")
        else:
            decide_notes.append("No additional LTD lane is recommended from the current signal context.")

        executed_actions: list[str] = []
        automated_actions: list[dict[str, object]] = []
        if staged_candidates:
            executed_actions.append("commitment_candidates_staged")
        if staged_draft is not None:
            executed_actions.append("reply_draft_staged")
        if automated_result is not None:
            automated_actions.append(
                {
                    "action_key": "create_property_tour",
                    "service_name": "Crezlo Tours",
                    "status": str(automated_result.get("status") or "").strip(),
                    "delivery_status": str(automated_result.get("delivery_status") or "").strip(),
                    "blocked_reason": str(automated_result.get("blocked_reason") or "").strip(),
                    "tour_url": str(automated_result.get("tour_url") or "").strip(),
                    "human_task_id": str(automated_result.get("human_task_id") or "").strip(),
                }
            )
            executed_actions.append("create_property_tour")

        draft_count = 1 if staged_draft is not None else 0
        act_notes = [
            f"Staged {len(staged_candidates)} candidate{'s' if len(staged_candidates) != 1 else ''} and {draft_count} reply draft{'s' if draft_count != 1 else ''}."
        ]
        if automated_actions:
            automated_status = automated_actions[0]
            if str(automated_status.get("status") or "").strip() == "created":
                act_notes.append("Ran the property-tour automation for the referenced listing.")
            elif str(automated_status.get("status") or "").strip() == "blocked":
                act_notes.append("Property-tour automation was reviewed but handed off because the lane is not fully configured.")

        observe_summary = compact_text(
            " ".join(
                part
                for part in (
                    f"Signal from {counterparty}." if counterparty else "",
                    title,
                    summary,
                )
                if str(part or "").strip()
            ),
            fallback="Inbound signal received.",
            limit=220,
        )
        orient_summary = compact_text(" ".join(orientation_notes), fallback="Signal intent was reviewed.", limit=220)
        decide_summary = compact_text(" ".join(decide_notes), fallback="Signal decisions were recorded.", limit=220)
        act_summary = compact_text(" ".join(act_notes), fallback="Signal actions were recorded.", limit=220)
        return {
            "reviewed": True,
            "reviewed_at": _now_iso(),
            "actor": str(actor or "").strip() or "office_api",
            "observe": {
                "summary": observe_summary,
                "channel": str(channel or "").strip().lower() or "gmail",
                "signal_type": normalized_signal_type,
                "counterparty": str(counterparty or "").strip(),
                "source_ref": str(source_ref or "").strip(),
                "external_id": str(external_id or "").strip(),
                "due_at": str(due_at or "").strip(),
                "property_url": property_url,
                "account_email": str(payload.get("account_email") or "").strip().lower(),
            },
            "orient": {
                "summary": orient_summary,
                "tags": orientation_tags,
            },
            "ltd_review": {
                **dict(ltd_review),
                "recommended_count": len(recommended_ltd_actions),
            },
            "decide": {
                "summary": decide_summary,
                "recommended_actions": decide_actions,
            },
            "act": {
                "summary": act_summary,
                "executed_actions": executed_actions,
                "staged_candidate_count": len(staged_candidates),
                "staged_draft_count": draft_count,
                "automated_actions": automated_actions,
            },
            "summary": compact_text(
                " ".join(part for part in (observe_summary, decide_summary, str(ltd_review.get("summary") or "").strip()) if part),
                fallback="Signal OODA loop evaluated.",
                limit=240,
            ),
        }

    def _selected_willhaben_tour_variant(
        self,
        *,
        packet: dict[str, object],
        variant_key: str,
    ) -> dict[str, object]:
        requested = str(variant_key or "").strip().lower()
        variants = [dict(entry) for entry in list(packet.get("tour_variants_json") or []) if isinstance(entry, dict)]
        if not variants:
            raise RuntimeError("willhaben_tour_variants_missing")
        if requested:
            for row in variants:
                if str(row.get("variant_key") or "").strip().lower() == requested:
                    return row
        return variants[0]

    def _resolve_browseract_property_tour_binding_id(
        self,
        *,
        principal_id: str,
        binding_id: str = "",
    ) -> str:
        bootstrap_metadata = _crezlo_property_tour_bootstrap_metadata()
        explicit = str(binding_id or "").strip()
        if explicit:
            return explicit
        bindings = self._container.tool_runtime.list_connector_bindings(principal_id, limit=100)
        for row in bindings:
            if str(getattr(row, "connector_name", "") or "").strip().lower() != "browseract":
                continue
            if str(getattr(row, "status", "") or "").strip().lower() != "enabled":
                continue
            current_metadata = dict(getattr(row, "auth_metadata_json", {}) or {})
            merged_metadata = dict(current_metadata)
            for key, value in bootstrap_metadata.items():
                if not str(merged_metadata.get(key) or "").strip() and value not in {None, ""}:
                    merged_metadata[key] = value
            if merged_metadata != current_metadata:
                updated = self._container.tool_runtime.upsert_connector_binding(
                    principal_id=principal_id,
                    connector_name="browseract",
                    external_account_ref=str(getattr(row, "external_account_ref", "") or "").strip() or "crezlo-auto",
                    scope_json=dict(getattr(row, "scope_json", {}) or {}),
                    auth_metadata_json=merged_metadata,
                    status=str(getattr(row, "status", "") or "enabled"),
                )
                return str(updated.binding_id or "").strip()
            return str(getattr(row, "binding_id", "") or "").strip()
        if not str(os.getenv("BROWSERACT_API_KEY") or "").strip():
            return ""
        auth_metadata = {
            "service_name": "Crezlo Tours",
            "service_accounts_json": {"Crezlo Tours": {"status": "configured"}},
            **bootstrap_metadata,
        }
        created = self._container.tool_runtime.upsert_connector_binding(
            principal_id=principal_id,
            connector_name="browseract",
            external_account_ref="crezlo-auto",
            scope_json={"services": ["Crezlo Tours", "Crezlo"], "scopes": ["browseract", "crezlo"]},
            auth_metadata_json=auth_metadata,
            status="enabled",
        )
        return str(created.binding_id or "").strip()

    def _property_tour_execution_error_reason(self, exc: Exception) -> str:
        detail = str(exc or "").strip().lower()
        if any(
            marker in detail
            for marker in (
                "connector_binding_required:browseract.crezlo_property_tour",
                "connector_binding_not_found",
                "connector_binding_disabled",
            )
        ):
            return "browseract_connector_unconfigured"
        if any(
            marker in detail
            for marker in (
                "crezlo_login_required_for_direct_create",
                "crezlo_login_email_missing",
                "crezlo_login_password_missing",
                "crezlo_login_required",
                "crezlo_worker_missing",
            )
        ):
            return "crezlo_property_tour_not_configured"
        if "crezlo_media_missing" in detail:
            return "listing_media_missing"
        return "property_tour_execution_failed"

    def _existing_property_tour_followup(
        self,
        *,
        principal_id: str,
        property_url: str,
        variant_key: str,
    ) -> HumanTask | None:
        normalized_url = str(property_url or "").strip()
        normalized_variant = str(variant_key or "").strip().lower()
        if not normalized_url:
            return None
        for row in self._container.orchestrator.list_human_tasks(principal_id=principal_id, status="pending", limit=200):
            if str(getattr(row, "task_type", "") or "").strip() != "property_tour_followup":
                continue
            input_json = dict(getattr(row, "input_json", {}) or {})
            if str(input_json.get("property_url") or "").strip() != normalized_url:
                continue
            if str(input_json.get("variant_key") or "").strip().lower() != normalized_variant:
                continue
            return row
        return None

    def _open_property_tour_followup(
        self,
        *,
        principal_id: str,
        property_url: str,
        title: str,
        variant_key: str,
        blocked_reason: str,
        recipient_email: str,
        source_ref: str,
        external_id: str,
        connector_binding_id: str,
    ) -> HumanTask:
        existing = self._existing_property_tour_followup(
            principal_id=principal_id,
            property_url=property_url,
            variant_key=variant_key,
        )
        if existing is not None:
            return existing
        session_id = self._start_product_review_session(
            principal_id=principal_id,
            goal=f"Finish apartment-tour automation for {title or property_url}",
            source_ref=source_ref or property_url,
        )
        return self._container.orchestrator.create_human_task(
            session_id=session_id,
            principal_id=principal_id,
            task_type="property_tour_followup",
            role_required="operator",
            brief=f"Finish apartment tour delivery for {title or property_url}",
            why_human=f"Automatic apartment-tour handling stopped at {blocked_reason}. Finish the tour or delivery path.",
            priority="high",
            input_json={
                "property_url": str(property_url or "").strip(),
                "title": str(title or "").strip(),
                "variant_key": str(variant_key or "").strip(),
                "blocked_reason": str(blocked_reason or "").strip(),
                "recipient_email": str(recipient_email or "").strip().lower(),
                "connector_binding_id": str(connector_binding_id or "").strip(),
                "source_ref": str(source_ref or "").strip(),
                "external_id": str(external_id or "").strip(),
            },
            desired_output_json={
                "status": "completed",
                "tour_url": "",
                "delivery_email": str(recipient_email or "").strip().lower(),
            },
        )

    def _maybe_create_willhaben_property_tour_from_signal(
        self,
        *,
        principal_id: str,
        title: str,
        summary: str,
        text: str,
        source_ref: str,
        external_id: str,
        counterparty: str,
        payload: dict[str, object],
        actor: str,
    ) -> dict[str, object] | None:
        wants_tour = bool(payload.get("auto_create_property_tour"))
        if not wants_tour:
            actions = payload.get("ooda_actions")
            if isinstance(actions, (list, tuple, set)):
                wants_tour = any(str(value or "").strip().lower() == "create_property_tour" for value in actions)
        auto_create_spec = _willhaben_search_agent_auto_create_spec(
            principal_id=principal_id,
            title=title,
            summary=summary,
            text=text,
            source_ref=source_ref,
            external_id=external_id,
            counterparty=counterparty,
            payload=payload,
        )
        if not wants_tour and auto_create_spec is not None:
            wants_tour = True
        if not wants_tour:
            return None
        property_url = _first_non_empty_text(
            auto_create_spec.get("property_url") if auto_create_spec is not None else "",
            _willhaben_property_url_from_signal(
                title=title,
                summary=summary,
                text=text,
                source_ref=source_ref,
                external_id=external_id,
                payload=payload,
            ),
        )
        try:
            return self.create_willhaben_property_tour(
                principal_id=principal_id,
                property_url=property_url,
                recipient_email=_first_non_empty_text(
                    payload.get("delivery_recipient_email"),
                    payload.get("recipient_email"),
                    payload.get("notify_email"),
                    auto_create_spec.get("recipient_email") if auto_create_spec is not None else "",
                    _principal_email_hint(principal_id),
                ),
                variant_key=_first_non_empty_text(payload.get("variant_key"), payload.get("tour_variant_key"), "layout_first"),
                binding_id=_first_non_empty_text(payload.get("binding_id")),
                source_ref=source_ref,
                external_id=external_id,
                auto_deliver=bool(payload.get("auto_deliver", True)),
                actor=actor,
            )
        except Exception as exc:
            self._record_product_event(
                principal_id=principal_id,
                event_type="willhaben_property_tour_auto_failed",
                payload={
                    "property_url": property_url,
                    "source_ref": str(source_ref or "").strip(),
                    "external_id": str(external_id or "").strip(),
                    "title": str(title or "").strip(),
                    "summary": str(summary or "").strip(),
                    "error": str(exc or "").strip(),
                },
                source_id=str(source_ref or external_id or property_url).strip(),
                dedupe_key=f"{principal_id}|{source_ref or external_id or property_url}|property-tour-auto-failed",
            )
            return None

    def create_willhaben_property_tour(
        self,
        *,
        principal_id: str,
        property_url: str,
        recipient_email: str = "",
        variant_key: str = "layout_first",
        binding_id: str = "",
        source_ref: str = "",
        external_id: str = "",
        auto_deliver: bool = True,
        actor: str = "",
    ) -> dict[str, object]:
        normalized_url = urllib.parse.urldefrag(str(property_url or "").strip())[0]
        if not _is_willhaben_property_url(normalized_url):
            raise ValueError("willhaben_property_url_invalid")
        packet = _load_willhaben_property_packet(normalized_url)
        variant = self._selected_willhaben_tour_variant(packet=packet, variant_key=variant_key)
        resolved_variant_key = str(variant.get("variant_key") or variant_key or "layout_first").strip() or "layout_first"
        title = str(packet.get("title") or normalized_url).strip() or normalized_url
        listing_id = str(packet.get("listing_id") or "").strip()
        resolved_source_ref = str(source_ref or f"willhaben:{listing_id or _saved_link_fallback_id(normalized_url)}").strip()
        resolved_external_id = str(external_id or listing_id or normalized_url).strip()
        resolved_binding_id = self._resolve_browseract_property_tour_binding_id(
            principal_id=principal_id,
            binding_id=binding_id,
        )
        resolved_recipient_email = str(recipient_email or _principal_email_hint(principal_id)).strip().lower()
        generated_at = _now_iso()
        if not resolved_binding_id:
            followup = self._open_property_tour_followup(
                principal_id=principal_id,
                property_url=normalized_url,
                title=title,
                variant_key=resolved_variant_key,
                blocked_reason="browseract_connector_unconfigured",
                recipient_email=resolved_recipient_email,
                source_ref=resolved_source_ref,
                external_id=resolved_external_id,
                connector_binding_id="",
            )
            payload = {
                "generated_at": generated_at,
                "status": "blocked",
                "property_url": normalized_url,
                "title": title,
                "listing_id": listing_id,
                "variant_key": resolved_variant_key,
                "artifact_id": "",
                "execution_session_id": "",
                "connector_binding_id": "",
                "tour_url": "",
                "vendor_tour_url": "",
                "editor_url": "",
                "delivery_email": resolved_recipient_email,
                "delivery_status": "blocked",
                "blocked_reason": "browseract_connector_unconfigured",
                "human_task_id": f"human_task:{followup.human_task_id}",
                "source_ref": resolved_source_ref,
                "external_id": resolved_external_id,
            }
            self._record_product_event(
                principal_id=principal_id,
                event_type="willhaben_property_tour_blocked",
                payload=payload,
                source_id=resolved_source_ref,
                dedupe_key=f"{principal_id}|{resolved_source_ref}|{resolved_variant_key}|tour-blocked:browseract_connector_unconfigured",
            )
            return payload

        request_payload = {
            "binding_id": resolved_binding_id,
            "force_ui_worker": True,
            "tour_title": " - ".join(part for part in (title, resolved_variant_key.replace("_", " ")) if part)[:180],
            "display_title": title[:220],
            "property_url": normalized_url,
            "media_urls_json": list(packet.get("media_urls_json") or []),
            "floorplan_urls_json": list(packet.get("floorplan_urls_json") or []),
            "scene_strategy": str(variant.get("scene_strategy") or "layout_first").strip(),
            "scene_selection_json": dict(variant.get("scene_selection_json") or {}),
            "property_facts_json": dict(packet.get("property_facts_json") or {}),
            "creative_brief": str(variant.get("creative_brief") or "").strip(),
            "variant_key": resolved_variant_key,
            "language": "de",
            "theme_name": str(variant.get("theme_name") or "").strip(),
            "tour_style": str(variant.get("tour_style") or "").strip(),
            "audience": str(variant.get("audience") or "").strip(),
            "call_to_action": str(variant.get("call_to_action") or "").strip(),
            "tour_visibility": "public",
            "tour_settings_json": dict(variant.get("tour_settings_json") or {}),
            "is_private": False,
            "runtime_inputs_json": {
                "listing_id": listing_id,
                "listing_uuid": str(packet.get("listing_uuid") or "").strip(),
                "variant_key": resolved_variant_key,
                "source": "willhaben",
            },
        }
        resolved_task_key = "create_property_tour"
        if self._container.task_contracts.get_contract(resolved_task_key) is None:
            projected_crezlo_task_key = projected_task_key("Crezlo Tours", "create_property_tour")
            if self._container.task_contracts.get_contract(projected_crezlo_task_key) is not None:
                resolved_task_key = projected_crezlo_task_key

        artifact = None
        blocked_reason = ""
        try:
            artifact = self._container.orchestrator.execute_task_artifact(
                TaskExecutionRequest(
                    task_key=resolved_task_key,
                    principal_id=principal_id,
                    goal=f"create a steerable apartment tour for {title}",
                    input_json=request_payload,
                )
            )
        except Exception as exc:
            blocked_reason = self._property_tour_execution_error_reason(exc)

        if blocked_reason:
            followup = self._open_property_tour_followup(
                principal_id=principal_id,
                property_url=normalized_url,
                title=title,
                variant_key=resolved_variant_key,
                blocked_reason=blocked_reason,
                recipient_email=resolved_recipient_email,
                source_ref=resolved_source_ref,
                external_id=resolved_external_id,
                connector_binding_id=resolved_binding_id,
            )
            payload = {
                "generated_at": generated_at,
                "status": "blocked",
                "property_url": normalized_url,
                "title": title,
                "listing_id": listing_id,
                "variant_key": resolved_variant_key,
                "artifact_id": "",
                "execution_session_id": "",
                "connector_binding_id": resolved_binding_id,
                "tour_url": "",
                "vendor_tour_url": "",
                "editor_url": "",
                "delivery_email": resolved_recipient_email,
                "delivery_status": "blocked",
                "blocked_reason": blocked_reason,
                "human_task_id": f"human_task:{followup.human_task_id}",
                "source_ref": resolved_source_ref,
                "external_id": resolved_external_id,
            }
            self._record_product_event(
                principal_id=principal_id,
                event_type="willhaben_property_tour_blocked",
                payload=payload,
                source_id=resolved_source_ref,
                dedupe_key=f"{principal_id}|{resolved_source_ref}|{resolved_variant_key}|tour-blocked:{blocked_reason}",
            )
            return payload

        structured_output = dict(artifact.structured_output_json or {}) if artifact is not None else {}
        tour_url, vendor_tour_url = _resolve_property_tour_urls(structured_output)
        editor_url = _first_non_empty_text(structured_output.get("editor_url"))
        payload = {
            "generated_at": generated_at,
            "status": "created",
            "property_url": normalized_url,
            "title": title,
            "listing_id": listing_id,
            "variant_key": resolved_variant_key,
            "artifact_id": str(artifact.artifact_id or "").strip(),
            "execution_session_id": str(artifact.execution_session_id or "").strip(),
            "connector_binding_id": resolved_binding_id,
            "tour_url": tour_url,
            "vendor_tour_url": vendor_tour_url,
            "editor_url": editor_url,
            "delivery_email": resolved_recipient_email,
            "delivery_status": "skipped" if not auto_deliver else "",
            "blocked_reason": "",
            "human_task_id": "",
            "source_ref": resolved_source_ref,
            "external_id": resolved_external_id,
        }
        self._record_product_event(
            principal_id=principal_id,
            event_type="willhaben_property_tour_created",
            payload={
                **payload,
                "tour_id": str(structured_output.get("tour_id") or "").strip(),
            },
            source_id=resolved_source_ref,
            dedupe_key=f"{principal_id}|{resolved_source_ref}|{resolved_variant_key}|tour-created",
        )
        if not auto_deliver:
            return payload

        if not tour_url:
            blocked_reason = "property_tour_url_missing"
        elif not resolved_recipient_email:
            blocked_reason = "delivery_recipient_missing"
        elif not email_delivery_enabled():
            blocked_reason = "email_delivery_not_configured"
        else:
            blocked_reason = ""

        if blocked_reason:
            followup = self._open_property_tour_followup(
                principal_id=principal_id,
                property_url=normalized_url,
                title=title,
                variant_key=resolved_variant_key,
                blocked_reason=blocked_reason,
                recipient_email=resolved_recipient_email,
                source_ref=resolved_source_ref,
                external_id=resolved_external_id,
                connector_binding_id=resolved_binding_id,
            )
            payload.update(
                {
                    "status": "blocked",
                    "delivery_status": "blocked",
                    "blocked_reason": blocked_reason,
                    "human_task_id": f"human_task:{followup.human_task_id}",
                }
            )
            self._record_product_event(
                principal_id=principal_id,
                event_type="willhaben_property_tour_blocked",
                payload=payload,
                source_id=resolved_source_ref,
                dedupe_key=f"{principal_id}|{resolved_source_ref}|{resolved_variant_key}|tour-blocked:{blocked_reason}",
            )
            return payload

        facts = dict(packet.get("property_facts_json") or {})
        price_value = facts.get("total_rent_eur")
        price_label = f"EUR {price_value:g}" if isinstance(price_value, (int, float)) else ""
        try:
            receipt = send_property_tour_email(
                recipient_email=resolved_recipient_email,
                property_title=title,
                property_url=normalized_url,
                tour_url=tour_url,
                variant_key=resolved_variant_key,
                listing_id=listing_id,
                area_label=str(facts.get("area_label") or "").strip(),
                rooms_label=str(facts.get("rooms_label") or "").strip(),
                price_label=price_label,
            )
            payload.update({"status": "sent", "delivery_status": "sent"})
            self._record_product_event(
                principal_id=principal_id,
                event_type="willhaben_property_tour_email_sent",
                payload={
                    **payload,
                    "provider": str(receipt.provider or "").strip(),
                    "message_id": str(receipt.message_id or "").strip(),
                },
                source_id=resolved_source_ref,
                dedupe_key=f"{principal_id}|{resolved_source_ref}|{resolved_variant_key}|tour-email-sent",
            )
            return payload
        except Exception as exc:
            followup = self._open_property_tour_followup(
                principal_id=principal_id,
                property_url=normalized_url,
                title=title,
                variant_key=resolved_variant_key,
                blocked_reason="property_tour_delivery_failed",
                recipient_email=resolved_recipient_email,
                source_ref=resolved_source_ref,
                external_id=resolved_external_id,
                connector_binding_id=resolved_binding_id,
            )
            payload.update(
                {
                    "status": "blocked",
                    "delivery_status": "failed",
                    "blocked_reason": "property_tour_delivery_failed",
                    "human_task_id": f"human_task:{followup.human_task_id}",
                }
            )
            self._record_product_event(
                principal_id=principal_id,
                event_type="willhaben_property_tour_delivery_failed",
                payload={**payload, "error": str(exc or "").strip()},
                source_id=resolved_source_ref,
                dedupe_key=f"{principal_id}|{resolved_source_ref}|{resolved_variant_key}|tour-email-failed",
            )
            return payload

    def recreate_property_tour_followup(
        self,
        *,
        principal_id: str,
        handoff_ref: str,
        operator_id: str,
        actor: str,
    ) -> HandoffNote | None:
        if not str(handoff_ref or "").strip().startswith("human_task:"):
            return None
        task_id = handoff_ref.split(":", 1)[1]
        current = self._container.orchestrator.fetch_human_task(task_id, principal_id=principal_id)
        if current is None:
            return None
        if str(current.task_type or "").strip() != "property_tour_followup":
            return None
        current_status = str(current.status or "").strip()
        if current_status not in {"open", "pending", "claimed"}:
            raise RuntimeError("handoff_not_recreatable")
        current_operator = str(current.assigned_operator_id or "").strip()
        if current_operator and current_operator != str(operator_id or "").strip():
            raise RuntimeError("handoff_owned_by_other_operator")
        if str(operator_id or "").strip() and current_operator != str(operator_id or "").strip():
            assigned = self.assign_handoff(
                principal_id=principal_id,
                handoff_ref=handoff_ref,
                operator_id=operator_id,
                actor=actor,
            )
            if assigned is None:
                raise RuntimeError("handoff_not_assignable")
            current = self._container.orchestrator.fetch_human_task(task_id, principal_id=principal_id) or current
        input_json = dict(current.input_json or {})
        result = self.create_willhaben_property_tour(
            principal_id=principal_id,
            property_url=str(input_json.get("property_url") or "").strip(),
            recipient_email=str(input_json.get("recipient_email") or "").strip(),
            variant_key=str(input_json.get("variant_key") or "layout_first").strip(),
            binding_id=str(input_json.get("connector_binding_id") or "").strip(),
            source_ref=str(input_json.get("source_ref") or "").strip(),
            external_id=str(input_json.get("external_id") or "").strip(),
            auto_deliver=True,
            actor=actor,
        )
        if str(result.get("status") or "").strip() == "sent":
            completed = self.complete_handoff(
                principal_id=principal_id,
                handoff_ref=handoff_ref,
                operator_id=operator_id,
                actor=actor,
                resolution="sent",
            )
            if completed is not None:
                return completed
        return self.get_handoff(principal_id=principal_id, handoff_ref=handoff_ref)

    def sync_google_workspace_signals(
        self,
        *,
        principal_id: str,
        actor: str,
        email_limit: int = 5,
        calendar_limit: int = 5,
    ) -> dict[str, object]:
        seen_source_refs: set[str] = set()
        seen_external_ids: set[str] = set()
        for row in self._container.channel_runtime.list_recent_observations(limit=4000, principal_id=principal_id):
            if str(getattr(row, "channel", "") or "").strip().lower() != "gmail":
                continue
            if str(getattr(row, "event_type", "") or "").strip().lower() != "office_signal_email_thread":
                continue
            source_id = str(getattr(row, "source_id", "") or "").strip()
            external_id = str(getattr(row, "external_id", "") or "").strip()
            if source_id:
                seen_source_refs.add(source_id)
            if external_id:
                seen_external_ids.add(external_id)
        packet = google_oauth_service.list_recent_workspace_signals(
            container=self._container,
            principal_id=principal_id,
            email_limit=email_limit,
            calendar_limit=calendar_limit,
            seen_source_refs=seen_source_refs,
            seen_external_ids=seen_external_ids,
        )
        curated_signals, suppressed_signals = self._curate_google_workspace_signals(signals=packet.signals)
        items = [
            self.ingest_office_signal(
                principal_id=principal_id,
                signal_type=row.signal_type,
                channel=row.channel,
                title=row.title,
                summary=row.summary,
                text=row.text,
                source_ref=row.source_ref,
                external_id=row.external_id,
                counterparty=row.counterparty,
                due_at=row.due_at,
                payload=row.payload,
                actor=actor,
            )
            for row in curated_signals
        ]
        suppressed_total = len(suppressed_signals)
        deduplicated_total = sum(1 for item in items if bool(item.get("deduplicated")))
        synced_total = len(items) - deduplicated_total
        account_rollups: dict[str, dict[str, object]] = {}
        account_order: list[str] = []

        def _signal_account_email(signal: google_oauth_service.GoogleWorkspaceSignal) -> str:
            return str(dict(signal.payload or {}).get("account_email") or "").strip().lower()

        def _ensure_account_rollup(account_email: str) -> dict[str, object]:
            normalized_email = str(account_email or "").strip().lower()
            key = normalized_email or "unattributed"
            if key not in account_rollups:
                account_rollups[key] = {
                    "account_email": normalized_email,
                    "gmail_total": 0,
                    "calendar_total": 0,
                    "processed_total": 0,
                    "synced_total": 0,
                    "deduplicated_total": 0,
                    "suppressed_total": 0,
                }
                account_order.append(key)
            return account_rollups[key]

        for account_email in packet.account_emails:
            _ensure_account_rollup(str(account_email or "").strip().lower())
        for signal in packet.signals:
            row = _ensure_account_rollup(_signal_account_email(signal))
            if str(signal.channel or "").strip().lower() == "gmail":
                row["gmail_total"] = int(row["gmail_total"] or 0) + 1
            elif str(signal.channel or "").strip().lower() == "calendar":
                row["calendar_total"] = int(row["calendar_total"] or 0) + 1
        for signal, item in zip(curated_signals, items):
            row = _ensure_account_rollup(_signal_account_email(signal))
            row["processed_total"] = int(row["processed_total"] or 0) + 1
            if bool(item.get("deduplicated")):
                row["deduplicated_total"] = int(row["deduplicated_total"] or 0) + 1
            else:
                row["synced_total"] = int(row["synced_total"] or 0) + 1
        for signal in suppressed_signals:
            row = _ensure_account_rollup(_signal_account_email(signal))
            row["suppressed_total"] = int(row["suppressed_total"] or 0) + 1
        account_sync_accounts = [dict(account_rollups[key]) for key in account_order]
        self._record_product_event(
            principal_id=principal_id,
            event_type="google_workspace_signal_sync_completed",
            payload={
                "account_email": packet.account_email,
                "account_emails": list(packet.account_emails),
                "accounts": account_sync_accounts,
                "email_limit": max(int(email_limit), 0),
                "calendar_limit": max(int(calendar_limit), 0),
                "processed_total": len(items),
                "synced_total": synced_total,
                "deduplicated_total": deduplicated_total,
                "suppressed_total": suppressed_total,
                "gmail_total": sum(1 for row in packet.signals if row.channel == "gmail"),
                "calendar_total": sum(1 for row in packet.signals if row.channel == "calendar"),
            },
            source_id=packet.account_email,
            dedupe_key=(
                f"{principal_id}|google-signal-sync|{max(int(email_limit), 0)}|{max(int(calendar_limit), 0)}"
                f"|{_now_iso()}"
            ),
        )
        return {
            "generated_at": _now_iso(),
            "account_email": packet.account_email,
            "account_emails": list(packet.account_emails),
            "granted_scopes": list(packet.granted_scopes),
            "items": items,
            "total": len(items),
            "synced_total": synced_total,
            "deduplicated_total": deduplicated_total,
            "suppressed_total": suppressed_total,
        }

    def google_signal_sync_status(self, *, principal_id: str) -> dict[str, object]:
        diagnostics = self.workspace_diagnostics(principal_id=principal_id)
        sync = dict(dict(diagnostics.get("analytics") or {}).get("sync") or {})
        google_accounts = google_oauth_service.list_google_accounts(container=self._container, principal_id=principal_id)
        account_emails = [
            str(account.google_email or "").strip().lower()
            for account in google_accounts
            if str(account.google_email or "").strip()
        ]
        return {
            "generated_at": _now_iso(),
            "connected": bool(sync.get("google_connected")),
            "account_email": str(sync.get("google_account_email") or "").strip(),
            "account_emails": account_emails,
            "token_status": str(sync.get("google_token_status") or "missing").strip() or "missing",
            "last_refresh_at": str(sync.get("google_last_refresh_at") or "").strip(),
            "reauth_required_reason": str(sync.get("google_reauth_required_reason") or "").strip(),
            "sync_completed": int(sync.get("google_sync_completed") or 0),
            "office_signal_ingested": int(sync.get("office_signal_ingested") or 0),
            "last_completed_at": str(sync.get("google_sync_last_completed_at") or "").strip(),
            "last_synced_total": int(sync.get("google_sync_last_synced_total") or 0),
            "last_deduplicated_total": int(sync.get("google_sync_last_deduplicated_total") or 0),
            "last_suppressed_total": int(sync.get("google_sync_last_suppressed_total") or 0),
            "last_gmail_total": int(sync.get("google_sync_last_gmail_total") or 0),
            "last_calendar_total": int(sync.get("google_sync_last_calendar_total") or 0),
            "age_seconds": sync.get("google_sync_age_seconds"),
            "freshness_state": str(sync.get("google_sync_freshness_state") or "watch").strip() or "watch",
            "account_sync_accounts": [
                dict(value)
                for value in list(sync.get("google_sync_accounts") or [])
                if isinstance(value, dict)
            ],
            "last_send_verification_at": str(sync.get("google_send_verification_last_at") or "").strip(),
            "last_send_verification_state": str(sync.get("google_send_verification_last_state") or "").strip(),
            "last_send_verification_sender_email": str(sync.get("google_send_verification_last_sender_email") or "").strip(),
            "last_send_verification_recipient_email": str(sync.get("google_send_verification_last_recipient_email") or "").strip(),
            "last_send_verification_binding_id": str(sync.get("google_send_verification_last_binding_id") or "").strip(),
            "last_send_verification_error": str(sync.get("google_send_verification_last_error") or "").strip(),
            "send_verification_accounts": [
                dict(value)
                for value in list(sync.get("google_send_verification_accounts") or [])
                if isinstance(value, dict)
            ],
            "last_account_change_at": str(sync.get("google_account_change_last_at") or "").strip(),
            "last_account_change_state": str(sync.get("google_account_change_last_state") or "").strip(),
            "last_account_change_binding_id": str(sync.get("google_account_change_last_binding_id") or "").strip(),
            "last_account_change_email": str(sync.get("google_account_change_last_email") or "").strip(),
            "account_change_accounts": [
                dict(value)
                for value in list(sync.get("google_account_change_accounts") or [])
                if isinstance(value, dict)
            ],
            "pending_commitment_candidates": int(sync.get("pending_commitment_candidates") or 0),
            "covered_signal_candidates": int(sync.get("covered_signal_candidates") or 0),
        }

    def workspace_outcomes(self, *, principal_id: str) -> dict[str, object]:
        diagnostics = self.workspace_diagnostics(principal_id=principal_id)
        analytics = dict(diagnostics.get("analytics") or {})
        queue_health = dict(diagnostics.get("queue_health") or {})
        counts = dict(analytics.get("counts") or {})
        memo_loop = dict(analytics.get("memo_loop") or {})
        selected_counts = {
            "memo_opened": int(counts.get("memo_opened") or 0),
            "approval_requested": int(counts.get("approval_requested") or 0),
            "draft_approved": int(counts.get("draft_approved") or 0),
            "draft_sent": int(counts.get("draft_sent") or 0),
            "draft_send_followup_created": int(counts.get("draft_send_followup_created") or 0),
            "draft_send_followup_resolved": int(counts.get("draft_send_followup_resolved") or 0),
            "draft_send_reauth_needed": int(counts.get("draft_send_reauth_needed") or 0),
            "draft_send_waiting_on_principal": int(counts.get("draft_send_waiting_on_principal") or 0),
            "commitment_created": int(counts.get("commitment_created") or 0),
            "commitment_closed": int(counts.get("commitment_closed") or 0),
            "handoff_completed": int(counts.get("handoff_completed") or 0),
            "memory_corrected": int(counts.get("memory_corrected") or 0),
            "support_bundle_opened": int(counts.get("support_bundle_opened") or 0),
        }
        memo_open_rate = float(analytics.get("memo_open_rate") or 0.0)
        approval_coverage_rate = float(analytics.get("approval_coverage_rate") or 0.0)
        approval_action_rate = float(analytics.get("approval_action_rate") or 0.0)
        delivery_followup_closeout_count = int(analytics.get("delivery_followup_closeout_count") or 0)
        delivery_followup_blocked_count = int(analytics.get("delivery_followup_blocked_count") or 0)
        delivery_followup_resolution_rate = analytics.get("delivery_followup_resolution_rate")
        delivery_followup_blocked_rate = analytics.get("delivery_followup_blocked_rate")
        commitment_close_rate = float(analytics.get("commitment_close_rate") or 0.0)
        useful_loop_days = int(memo_loop.get("days_with_useful_loop") or 0)
        memo_issue_reason = str(memo_loop.get("last_issue_reason") or "").strip()
        memo_issue_fix_detail = str(memo_loop.get("last_issue_fix_detail") or "").strip()
        oldest_handoff_age_hours = int(queue_health.get("oldest_handoff_age_hours") or 0)
        office_loop_checks = [
            {
                "key": "memo_open_rate",
                "label": "Memo open rate",
                "actual": memo_open_rate,
                "target": 0.7,
                "state": "clear" if memo_open_rate >= 0.7 else "watch" if memo_open_rate >= 0.4 else "critical",
            },
            {
                "key": "approval_action_rate",
                "label": "Approval send rate",
                "actual": approval_action_rate,
                "target": 0.6,
                "state": "clear" if approval_action_rate >= 0.6 else "watch" if approval_action_rate >= 0.3 else "critical",
            },
            {
                "key": "commitment_close_rate",
                "label": "Commitment close rate",
                "actual": commitment_close_rate,
                "target": 0.35,
                "state": "clear" if commitment_close_rate >= 0.35 else "watch" if commitment_close_rate >= 0.15 else "critical",
            },
            {
                "key": "useful_loop_days",
                "label": "Useful loop days",
                "actual": useful_loop_days,
                "target": 3,
                "state": "clear" if useful_loop_days >= 3 else "watch" if useful_loop_days >= 1 else "critical",
            },
            {
                "key": "memo_delivery_blocker",
                "label": "Memo delivery blocker",
                "actual": memo_issue_reason or "clear",
                "target": "no blocker",
                "state": "critical" if memo_issue_reason else "clear",
                "detail": memo_issue_fix_detail,
            },
            {
                "key": "oldest_handoff_age_hours",
                "label": "Oldest handoff age",
                "actual": oldest_handoff_age_hours,
                "target_max": 48,
                "state": "clear" if oldest_handoff_age_hours <= 48 else "watch" if oldest_handoff_age_hours <= 72 else "critical",
            },
        ]
        passed_checks = sum(1 for row in office_loop_checks if str(row.get("state") or "") == "clear")
        critical_checks = sum(1 for row in office_loop_checks if str(row.get("state") or "") == "critical")
        office_loop_state = (
            "clear"
            if passed_checks == len(office_loop_checks)
            else "critical"
            if critical_checks >= 2 or not bool(memo_loop.get("enabled")) or bool(memo_issue_reason)
            else "watch"
        )
        office_loop_summary = (
            "Office-loop proof is strong enough to hold the wedge."
            if office_loop_state == "clear"
            else "Office-loop proof is blocked by a current memo delivery issue."
            if memo_issue_reason
            else "Office-loop proof is incomplete and needs another clean cycle."
            if office_loop_state == "critical"
            else "Office-loop proof is forming, but one or two gates still need work."
        )
        return {
            "generated_at": _now_iso(),
            "time_to_first_value_seconds": analytics.get("time_to_first_value_seconds"),
            "first_value_event": str(analytics.get("first_value_event") or "").strip(),
            "memo_open_rate": memo_open_rate,
            "approval_coverage_rate": approval_coverage_rate,
            "approval_action_rate": approval_action_rate,
            "delivery_followup_closeout_count": delivery_followup_closeout_count,
            "delivery_followup_blocked_count": delivery_followup_blocked_count,
            "delivery_followup_resolution_rate": (
                float(delivery_followup_resolution_rate)
                if delivery_followup_resolution_rate is not None
                else None
            ),
            "delivery_followup_blocked_rate": (
                float(delivery_followup_blocked_rate)
                if delivery_followup_blocked_rate is not None
                else None
            ),
            "commitment_close_rate": commitment_close_rate,
            "correction_rate": float(analytics.get("correction_rate") or 0.0),
            "churn_risk": str(analytics.get("churn_risk") or "watch").strip() or "watch",
            "success_summary": str(analytics.get("success_summary") or "").strip(),
            "memo_loop": memo_loop,
            "office_loop_proof": {
                "state": office_loop_state,
                "summary": office_loop_summary,
                "passed_checks": passed_checks,
                "check_total": len(office_loop_checks),
                "checks": office_loop_checks,
            },
            "counts": selected_counts,
        }

    def workspace_trust_summary(self, *, principal_id: str) -> dict[str, object]:
        diagnostics = self.workspace_diagnostics(principal_id=principal_id)
        analytics = dict(diagnostics.get("analytics") or {})
        reliability = dict(analytics.get("reliability") or {})
        providers = dict(diagnostics.get("providers") or {})
        readiness = dict(diagnostics.get("readiness") or {})
        evidence_items = self.list_evidence(principal_id=principal_id, limit=50)
        rules = self.list_rules(principal_id=principal_id)
        recent_events = [
            item
            for item in self.list_office_events(principal_id=principal_id, limit=12)
            if str(item.get("channel") or "").strip() == "product"
        ]
        trust_summary = (
            "Workspace trust posture is clear."
            if str(readiness.get("status") or "") == "ready"
            and str(providers.get("risk_state") or "healthy") in {"healthy", "ready", "clear"}
            and str(reliability.get("delivery_reliability_state") or "clear") == "clear"
            and str(reliability.get("sync_reliability_state") or "watch") in {"clear", "watch"}
            else "Review support diagnostics before the next office loop."
        )
        return {
            "generated_at": _now_iso(),
            "health_score": int(readiness.get("health_score") or 0),
            "workspace_summary": trust_summary,
            "readiness": {
                "status": str(readiness.get("status") or "unknown"),
                "detail": str(readiness.get("detail") or ""),
            },
            "provider_posture": {
                "risk_state": str(providers.get("risk_state") or "unknown"),
                "risk_detail": str(providers.get("risk_detail") or ""),
                "lanes_with_fallback": int(providers.get("lanes_with_fallback") or 0),
            },
            "reliability": {
                "delivery": str(reliability.get("delivery_reliability_state") or "watch"),
                "access": str(reliability.get("access_reliability_state") or "watch"),
                "sync": str(reliability.get("sync_reliability_state") or "watch"),
            },
            "audit_retention": str(dict(diagnostics.get("entitlements") or {}).get("audit_retention") or "standard"),
            "evidence_count": len(evidence_items),
            "rule_count": len(rules),
            "recent_events": recent_events[:8],
            "public_help_grounding": self._public_help_grounding_pack(
                product_control=dict(diagnostics.get("product_control") or {}),
            ),
        }

    def search_workspace(
        self,
        *,
        principal_id: str,
        query: str,
        limit: int = 20,
        operator_id: str = "",
    ) -> tuple[dict[str, object], ...]:
        tokens = _search_tokens(query)
        if not tokens:
            return ()
        rows: list[dict[str, object]] = []

        def add_result(
            *,
            id: str,
            kind: str,
            title: str,
            summary: str = "",
            href: str = "",
            secondary_label: str = "",
            related_object_refs: tuple[str, ...] = (),
            extra: tuple[str, ...] = (),
            action_href: str = "",
            action_label: str = "",
            action_method: str = "",
            action_value: str = "",
        ) -> None:
            score = _search_score(tokens=tokens, title=title, summary=summary, extra=extra)
            if score <= 0:
                return
            rows.append(
                {
                    "id": id,
                    "kind": kind,
                    "title": str(title or "").strip(),
                    "summary": str(summary or "").strip()[:220],
                    "href": href,
                    "score": score,
                    "secondary_label": secondary_label,
                    "related_object_refs": list(related_object_refs),
                    "action_href": action_href,
                    "action_label": action_label,
                    "action_method": action_method,
                    "action_value": action_value,
                }
            )

        for person in self.list_people(principal_id=principal_id, limit=max(limit * 2, 25)):
            add_result(
                id=person.id,
                kind="person",
                title=person.display_name,
                summary=f"{person.role_or_company} · {person.relationship_temperature} · {person.open_loops_count} open loops",
                href=f"/app/people/{urllib.parse.quote(person.id, safe='')}",
                secondary_label=person.relationship_temperature,
                related_object_refs=(person.id,),
                extra=tuple(person.themes) + tuple(person.risks) + (person.preferred_tone, person.role_or_company),
            )

        for thread in self.list_threads(principal_id=principal_id, limit=max(limit * 2, 25)):
            add_result(
                id=thread.id,
                kind="thread",
                title=thread.title,
                summary=thread.summary,
                href=f"/app/threads/{urllib.parse.quote(thread.id, safe='')}",
                secondary_label=thread.channel,
                related_object_refs=tuple(thread.related_commitment_ids) + tuple(thread.related_decision_ids),
                extra=tuple(thread.counterparties) + tuple(thread.draft_ids),
            )

        for draft in self.list_drafts(principal_id=principal_id, limit=max(limit * 2, 25)):
            thread_ref = str(draft.thread_ref or "").strip()
            thread_id = thread_ref if thread_ref.startswith("thread:") else (f"thread:{thread_ref}" if thread_ref else "")
            add_result(
                id=draft.id,
                kind="draft",
                title=draft.recipient_summary or draft.intent,
                summary=f"{draft.intent} · {draft.send_channel} · {draft.approval_status}",
                href=f"/app/threads/{urllib.parse.quote(thread_id, safe='')}" if thread_id else "/app/queue",
                secondary_label=draft.approval_status,
                related_object_refs=(draft.id, draft.thread_ref) if draft.thread_ref else (draft.id,),
                extra=(draft.thread_ref, draft.intent, draft.send_channel, draft.draft_text, draft.recipient_summary, draft.tone),
                action_href=f"/app/actions/drafts/{urllib.parse.quote(draft.id, safe='')}/approve",
                action_label="Approve",
                action_method="post",
            )

        for commitment in self.list_commitments(principal_id=principal_id, limit=max(limit * 3, 40), include_closed=True):
            normalized_status = str(commitment.status or "").strip().lower()
            actionable_open = status_open(normalized_status)
            add_result(
                id=commitment.id,
                kind="commitment",
                title=commitment.statement,
                summary=f"{commitment.counterparty} · {commitment.status} · {commitment.risk_level}",
                href=f"/app/commitment-items/{urllib.parse.quote(commitment.id, safe='')}",
                secondary_label=commitment.status,
                related_object_refs=(commitment.id,),
                extra=(commitment.counterparty, commitment.owner, commitment.channel_hint, commitment.source_ref),
                action_href=f"/app/actions/queue/{urllib.parse.quote(commitment.id, safe='')}/resolve",
                action_label="Close" if actionable_open else "Reopen",
                action_method="post",
                action_value="close" if actionable_open else "reopen",
            )

        for decision in self.list_decisions(principal_id=principal_id, limit=max(limit * 2, 25), include_closed=True):
            actionable_open = status_open(decision.status)
            add_result(
                id=decision.id,
                kind="decision",
                title=decision.title,
                summary=decision.summary,
                href=f"/app/decisions/{urllib.parse.quote(decision.id, safe='')}",
                secondary_label=decision.status,
                related_object_refs=tuple(decision.related_commitment_ids) + tuple(decision.linked_thread_ids),
                extra=tuple(decision.options) + tuple(decision.related_people) + (decision.recommendation, decision.next_action, decision.rationale),
                action_href=f"/app/actions/queue/{urllib.parse.quote(decision.id, safe='')}/resolve",
                action_label="Resolve" if actionable_open else "Reopen",
                action_method="post",
                action_value="resolve" if actionable_open else "reopen",
            )

        for deadline in self.list_deadlines(principal_id=principal_id, limit=max(limit * 2, 25), include_closed=True):
            actionable_open = status_open(deadline.status)
            add_result(
                id=deadline.id,
                kind="deadline",
                title=deadline.title,
                summary=f"{deadline.status} · {deadline.priority} · {(deadline.end_at or deadline.start_at or '')[:10]}",
                href=f"/app/deadlines/{urllib.parse.quote(deadline.id, safe='')}",
                secondary_label=deadline.status,
                related_object_refs=(deadline.id,),
                extra=(deadline.summary, deadline.priority, deadline.start_at, deadline.end_at),
                action_href=f"/app/actions/queue/{urllib.parse.quote(deadline.id, safe='')}/resolve",
                action_label="Resolve" if actionable_open else "Reopen",
                action_method="post",
                action_value="resolve" if actionable_open else "reopen",
            )

        for handoff in self.list_handoffs(principal_id=principal_id, limit=max(limit * 2, 25), operator_id=operator_id, status=None):
            action_plan = handoff_action_plan(handoff, operator_id=operator_id)
            action_kind = str(action_plan.get("kind") or "assign").strip()
            add_result(
                id=handoff.id,
                kind="handoff",
                title=handoff.summary,
                summary=f"{handoff.owner or 'unassigned'} · {handoff.escalation_status} · {handoff.status}",
                href=f"/app/handoffs/{urllib.parse.quote(handoff.id, safe='')}",
                secondary_label=handoff.escalation_status,
                related_object_refs=(handoff.id,),
                extra=(handoff.owner, handoff.status, handoff.escalation_status, handoff.due_time or ""),
                action_href=f"/app/actions/handoffs/{urllib.parse.quote(handoff.id, safe='')}/{'complete' if action_kind == 'complete' else 'assign'}",
                action_label=str(action_plan.get("label") or "Claim"),
                action_method="post",
                action_value=str(action_plan.get("value") or "assign"),
            )

        for evidence in self.list_evidence(principal_id=principal_id, limit=max(limit * 2, 25), operator_id=operator_id):
            add_result(
                id=evidence.id,
                kind="evidence",
                title=evidence.label,
                summary=evidence.summary,
                href=f"/app/evidence/{urllib.parse.quote(evidence.id, safe='')}",
                secondary_label=evidence.source_type,
                related_object_refs=(evidence.id,),
                extra=(evidence.source_type,),
            )

        for rule in self.list_rules(principal_id=principal_id):
            add_result(
                id=rule.id,
                kind="rule",
                title=rule.label,
                summary=rule.summary,
                href=f"/app/rules/{urllib.parse.quote(rule.id, safe='')}",
                secondary_label=rule.scope,
                related_object_refs=(rule.id,),
                extra=(rule.scope, rule.current_value, rule.impact, rule.status, rule.simulated_effect),
            )

        rows.sort(key=lambda item: (float(item.get("score") or 0.0), str(item.get("title") or "").lower(), str(item.get("id") or "")), reverse=True)
        return tuple(rows[:limit])

    def list_webhooks(self, *, principal_id: str, limit: int = 50) -> tuple[dict[str, object], ...]:
        configs: dict[str, dict[str, object]] = {}
        delivery_meta: dict[str, dict[str, object]] = {}
        for row in self._container.channel_runtime.list_recent_observations(limit=1000, principal_id=principal_id):
            event_type = str(row.event_type or "").strip().lower()
            payload = dict(row.payload or {})
            if event_type == "webhook_registered":
                webhook_id = str(payload.get("webhook_id") or row.source_id or "").strip()
                if webhook_id and webhook_id not in configs:
                    configs[webhook_id] = {
                        "webhook_id": webhook_id,
                        "label": str(payload.get("label") or webhook_id).strip(),
                        "target_url": str(payload.get("target_url") or "").strip(),
                        "status": str(payload.get("status") or "active").strip() or "active",
                        "event_types": [str(item).strip().lower() for item in payload.get("event_types") or [] if str(item).strip()],
                        "created_at": str(payload.get("created_at") or row.created_at or ""),
                        "last_delivery_at": "",
                        "delivery_count": 0,
                    }
            elif event_type == "webhook_delivery_queued":
                webhook_id = str(payload.get("webhook_id") or "").strip()
                if not webhook_id:
                    continue
                slot = delivery_meta.setdefault(webhook_id, {"delivery_count": 0, "last_delivery_at": ""})
                slot["delivery_count"] = int(slot.get("delivery_count") or 0) + 1
                created_at = str(row.created_at or "")
                if created_at and created_at > str(slot.get("last_delivery_at") or ""):
                    slot["last_delivery_at"] = created_at
        rows: list[dict[str, object]] = []
        for webhook_id, config in configs.items():
            meta = delivery_meta.get(webhook_id, {})
            rows.append(
                {
                    **config,
                    "last_delivery_at": str(meta.get("last_delivery_at") or ""),
                    "delivery_count": int(meta.get("delivery_count") or 0),
                }
            )
        rows.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("webhook_id") or "")), reverse=True)
        return tuple(rows[:limit])

    def get_webhook(self, *, principal_id: str, webhook_id: str) -> dict[str, object] | None:
        normalized = str(webhook_id or "").strip()
        if not normalized:
            return None
        for row in self.list_webhooks(principal_id=principal_id, limit=200):
            if str(row.get("webhook_id") or "").strip() == normalized:
                return row
        return None

    def register_webhook(
        self,
        *,
        principal_id: str,
        label: str,
        target_url: str,
        event_types: tuple[str, ...] = (),
        status: str = "active",
    ) -> dict[str, object]:
        webhook_id = f"webhook_{uuid4().hex[:10]}"
        payload = {
            "webhook_id": webhook_id,
            "label": str(label or "").strip(),
            "target_url": str(target_url or "").strip(),
            "event_types": [str(item).strip().lower() for item in event_types if str(item).strip()],
            "status": str(status or "active").strip().lower() or "active",
            "created_at": _now_iso(),
        }
        self._container.channel_runtime.ingest_observation(
            principal_id=principal_id,
            channel="product",
            event_type="webhook_registered",
            payload=payload,
            source_id=webhook_id,
            external_id=str(target_url or "").strip(),
            dedupe_key=f"{principal_id}|{webhook_id}",
        )
        found = self.get_webhook(principal_id=principal_id, webhook_id=webhook_id)
        return dict(found or payload)

    def _queue_single_webhook_delivery(
        self,
        *,
        principal_id: str,
        webhook: dict[str, object],
        matched_event_type: str,
        payload: dict[str, object],
        source_id: str = "",
        external_id: str = "",
        delivery_kind: str = "event",
    ) -> dict[str, object]:
        webhook_id = str(webhook.get("webhook_id") or "").strip()
        delivery_id = f"{webhook_id}:{matched_event_type}:{str(external_id or source_id or uuid4().hex[:8]).strip()}"
        event_payload = {
            "webhook_id": webhook_id,
            "label": str(webhook.get("label") or webhook_id).strip(),
            "target_url": str(webhook.get("target_url") or "").strip(),
            "matched_event_type": str(matched_event_type or "").strip().lower(),
            "delivery_kind": str(delivery_kind or "event").strip().lower() or "event",
            "status": "queued",
            "summary": str(payload.get("summary") or payload.get("title") or matched_event_type).strip(),
            "event_payload": dict(payload or {}),
        }
        event = self._container.channel_runtime.ingest_observation(
            principal_id=principal_id,
            channel="product",
            event_type="webhook_delivery_queued",
            payload=event_payload,
            source_id=str(source_id or webhook_id).strip(),
            external_id=delivery_id,
            dedupe_key=delivery_id,
        )
        return {
            "delivery_id": delivery_id,
            "webhook_id": webhook_id,
            "label": str(event_payload.get("label") or "").strip(),
            "target_url": str(event_payload.get("target_url") or "").strip(),
            "matched_event_type": str(event_payload.get("matched_event_type") or "").strip(),
            "delivery_kind": str(event_payload.get("delivery_kind") or "event").strip(),
            "status": "queued",
            "created_at": str(event.created_at or ""),
            "source_id": str(source_id or webhook_id).strip(),
            "summary": str(event_payload.get("summary") or "").strip(),
            "payload": dict(payload or {}),
        }

    def _queue_webhook_deliveries(
        self,
        *,
        principal_id: str,
        matched_event_type: str,
        payload: dict[str, object],
        source_id: str = "",
        external_id: str = "",
        delivery_kind: str = "event",
    ) -> tuple[dict[str, object], ...]:
        normalized_type = str(matched_event_type or "").strip().lower()
        if not normalized_type:
            return ()
        rows: list[dict[str, object]] = []
        for webhook in self.list_webhooks(principal_id=principal_id, limit=100):
            if str(webhook.get("status") or "active").strip().lower() != "active":
                continue
            filters = tuple(str(item).strip().lower() for item in webhook.get("event_types") or [] if str(item).strip())
            if filters and normalized_type not in filters:
                continue
            rows.append(
                self._queue_single_webhook_delivery(
                    principal_id=principal_id,
                    webhook=webhook,
                    matched_event_type=normalized_type,
                    payload=payload,
                    source_id=source_id,
                    external_id=external_id,
                    delivery_kind=delivery_kind,
                )
            )
        return tuple(rows)

    def list_webhook_deliveries(
        self,
        *,
        principal_id: str,
        webhook_id: str = "",
        limit: int = 100,
    ) -> tuple[dict[str, object], ...]:
        wanted_webhook = str(webhook_id or "").strip()
        rows: list[dict[str, object]] = []
        for row in self._container.channel_runtime.list_recent_observations(limit=1000, principal_id=principal_id):
            if str(row.event_type or "").strip().lower() != "webhook_delivery_queued":
                continue
            payload = dict(row.payload or {})
            current_webhook = str(payload.get("webhook_id") or "").strip()
            if wanted_webhook and current_webhook != wanted_webhook:
                continue
            rows.append(
                {
                    "delivery_id": str(row.external_id or ""),
                    "webhook_id": current_webhook,
                    "label": str(payload.get("label") or "").strip(),
                    "target_url": str(payload.get("target_url") or "").strip(),
                    "matched_event_type": str(payload.get("matched_event_type") or "").strip(),
                    "delivery_kind": str(payload.get("delivery_kind") or "event").strip(),
                    "status": str(payload.get("status") or "queued").strip(),
                    "created_at": str(row.created_at or ""),
                    "source_id": str(row.source_id or "").strip(),
                    "summary": str(payload.get("summary") or "").strip(),
                    "payload": dict(payload.get("event_payload") or {}),
                }
            )
        rows.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("delivery_id") or "")), reverse=True)
        return tuple(rows[:limit])

    def test_webhook(self, *, principal_id: str, webhook_id: str) -> dict[str, object] | None:
        webhook = self.get_webhook(principal_id=principal_id, webhook_id=webhook_id)
        if webhook is None:
            return None
        delivery = self._queue_single_webhook_delivery(
            principal_id=principal_id,
            webhook=webhook,
            matched_event_type="webhook_test_ping",
            payload={"summary": "Webhook test ping", "webhook_id": webhook_id},
            source_id=webhook_id,
            delivery_kind="test",
        )
        return {"webhook": webhook, "delivery": delivery}

    def issue_signal_ingest_endpoint(
        self,
        *,
        principal_id: str,
        channel: str,
        signal_type: str,
        label: str = "",
        counterparty: str = "",
        base_url: str = "",
        actor: str = "",
    ) -> dict[str, object]:
        normalized_channel = str(channel or "").strip().lower() or "office_api"
        normalized_signal = str(signal_type or "").strip().lower() or "saved_link"
        endpoint_id = f"signal_ingest_{uuid4().hex[:10]}"
        created_at = _now_iso()
        resolved_label = str(label or "").strip() or f"{normalized_channel.title()} signal ingest"
        token_payload = {
            "token_kind": "signal_ingest_endpoint",
            "endpoint_id": endpoint_id,
            "principal_id": str(principal_id or "").strip(),
            "channel": normalized_channel,
            "signal_type": normalized_signal,
            "label": resolved_label,
            "counterparty": str(counterparty or "").strip(),
            "created_at": created_at,
        }
        ingest_token = _sign_channel_payload(secret=self._signal_ingest_secret(), payload=token_payload)
        upload_path = f"/signals/{urllib.parse.quote(normalized_channel, safe='')}/{ingest_token}"
        upload_url = urllib.parse.urljoin(f"{str(base_url or '').strip().rstrip('/')}/", upload_path.lstrip("/")) if str(base_url or "").strip() else upload_path
        payload = {
            "endpoint_id": endpoint_id,
            "label": resolved_label,
            "channel": normalized_channel,
            "signal_type": normalized_signal,
            "counterparty": str(counterparty or "").strip(),
            "created_at": created_at,
            "upload_url": upload_url,
            "ingest_token": ingest_token,
            "issued_by": str(actor or "").strip() or "workspace",
        }
        self._container.channel_runtime.ingest_observation(
            principal_id=principal_id,
            channel="product",
            event_type="signal_ingest_endpoint_issued",
            payload=payload,
            source_id=endpoint_id,
            external_id=upload_url,
            dedupe_key=f"{principal_id}|{endpoint_id}",
        )
        return payload

    def preview_signal_ingest_endpoint(
        self,
        *,
        token: str,
        base_url: str = "",
    ) -> dict[str, object] | None:
        payload = _verify_channel_payload(secret=self._signal_ingest_secret(), token=token)
        if payload is None or str(payload.get("token_kind") or "").strip() != "signal_ingest_endpoint":
            return None
        normalized_channel = str(payload.get("channel") or "").strip().lower()
        if not normalized_channel:
            return None
        upload_path = f"/signals/{urllib.parse.quote(normalized_channel, safe='')}/{token}"
        upload_url = urllib.parse.urljoin(f"{str(base_url or '').strip().rstrip('/')}/", upload_path.lstrip("/")) if str(base_url or "").strip() else upload_path
        return {
            "endpoint_id": str(payload.get("endpoint_id") or "").strip(),
            "label": str(payload.get("label") or "").strip() or f"{normalized_channel.title()} signal ingest",
            "channel": normalized_channel,
            "signal_type": str(payload.get("signal_type") or "").strip().lower() or "saved_link",
            "counterparty": str(payload.get("counterparty") or "").strip(),
            "created_at": str(payload.get("created_at") or "").strip(),
            "upload_url": upload_url,
            "ingest_token": str(token or "").strip(),
        }

    def ingest_signal_upload(
        self,
        *,
        token: str,
        payload: dict[str, object] | None = None,
        actor: str = "",
    ) -> dict[str, object] | None:
        token_payload = _verify_channel_payload(secret=self._signal_ingest_secret(), token=token)
        if token_payload is None or str(token_payload.get("token_kind") or "").strip() != "signal_ingest_endpoint":
            return None
        principal_id = str(token_payload.get("principal_id") or "").strip()
        if not principal_id:
            return None
        endpoint = self.preview_signal_ingest_endpoint(token=token)
        if endpoint is None:
            return None
        normalized_channel = str(endpoint.get("channel") or "").strip().lower() or "office_api"
        normalized_signal = str(endpoint.get("signal_type") or "").strip().lower() or "saved_link"
        payload_json = dict(payload or {})
        nested_item = payload_json.get("item")
        item_payload = nested_item if isinstance(nested_item, dict) else {}
        url_text = _first_non_empty_text(
            payload_json.get("url"),
            payload_json.get("href"),
            payload_json.get("resolved_url"),
            payload_json.get("given_url"),
            item_payload.get("url"),
            item_payload.get("resolved_url"),
            item_payload.get("given_url"),
        )
        title_text = _first_non_empty_text(
            payload_json.get("title"),
            payload_json.get("given_title"),
            payload_json.get("resolved_title"),
            item_payload.get("title"),
            item_payload.get("given_title"),
            item_payload.get("resolved_title"),
            url_text,
        )
        summary_text = _first_non_empty_text(
            payload_json.get("summary"),
            payload_json.get("excerpt"),
            payload_json.get("description"),
            payload_json.get("note"),
            item_payload.get("summary"),
            item_payload.get("excerpt"),
            item_payload.get("description"),
            item_payload.get("note"),
        )
        tags_text = _tag_summary_text(payload_json.get("tags") or item_payload.get("tags"))
        raw_text = _first_non_empty_text(
            payload_json.get("text"),
            payload_json.get("raw_body"),
            item_payload.get("text"),
        )
        text_parts = [part for part in (title_text, summary_text, url_text, f"Tags: {tags_text}" if tags_text else "", raw_text) if str(part or "").strip()]
        source_text = " ".join(text_parts).strip()
        item_id = _first_non_empty_text(
            payload_json.get("item_id"),
            payload_json.get("resolved_id"),
            payload_json.get("external_id"),
            payload_json.get("id"),
            item_payload.get("item_id"),
            item_payload.get("resolved_id"),
            item_payload.get("external_id"),
            item_payload.get("id"),
        )
        source_ref = _first_non_empty_text(
            payload_json.get("source_ref"),
            f"{normalized_channel}:{item_id}" if item_id else "",
            url_text,
        )
        external_id = _first_non_empty_text(payload_json.get("external_id"), item_id, url_text)
        counterparty = _first_non_empty_text(payload_json.get("counterparty"), endpoint.get("counterparty"), normalized_channel.title())
        enriched_payload = {
            **payload_json,
            "endpoint_id": str(endpoint.get("endpoint_id") or "").strip(),
            "endpoint_label": str(endpoint.get("label") or "").strip(),
            "upload_channel": normalized_channel,
            "upload_signal_type": normalized_signal,
            "captured_url": url_text,
            "captured_tags": tags_text,
        }
        result = self.ingest_office_signal(
            principal_id=principal_id,
            signal_type=normalized_signal,
            channel=normalized_channel,
            title=title_text,
            summary=summary_text or url_text,
            text=source_text,
            source_ref=source_ref,
            external_id=external_id,
            counterparty=counterparty,
            payload=enriched_payload,
            actor=str(actor or "").strip() or f"{normalized_channel}_webhook",
        )
        self._record_product_event(
            principal_id=principal_id,
            event_type="signal_ingest_endpoint_used",
            payload={
                "endpoint_id": str(endpoint.get("endpoint_id") or "").strip(),
                "channel": normalized_channel,
                "signal_type": normalized_signal,
                "source_ref": source_ref,
                "external_id": external_id,
            },
            source_id=str(endpoint.get("endpoint_id") or source_ref or "").strip(),
            dedupe_key=(
                f"{str(endpoint.get('endpoint_id') or '').strip()}|"
                f"{external_id or source_ref or result.get('observation_id') or uuid4().hex[:8]}"
            ),
        )
        return result

    def import_pocket_saved_links_from_local_path(
        self,
        *,
        principal_id: str,
        path: str,
        counterparty: str = "Pocket",
        actor: str = "",
    ) -> dict[str, object]:
        candidate_path = Path(str(path or "").strip()).expanduser()
        if not candidate_path.is_absolute():
            candidate_path = (_repo_root() / candidate_path).resolve()
        if not candidate_path.exists() or not candidate_path.is_file():
            raise RuntimeError("pocket_import_path_not_found")
        sources = _saved_link_archive_sources(candidate_path)
        if not sources:
            raise RuntimeError("pocket_import_format_unsupported")
        records: list[dict[str, object]] = []
        source_formats: list[str] = []
        for source in sources:
            format_name = str(source.get("format") or "").strip().lower()
            if format_name and format_name not in source_formats:
                source_formats.append(format_name)
            records.extend(_saved_link_import_records_from_source(source))
        if not records:
            raise RuntimeError("pocket_import_entries_not_found")
        items: list[dict[str, object]] = []
        for record in records:
            url_text = str(record.get("url") or "").strip()
            title_text = str(record.get("title") or "").strip() or url_text
            summary_text = str(record.get("summary") or "").strip()
            tags_text = str(record.get("tags") or "").strip()
            item_id = str(record.get("item_id") or "").strip() or _saved_link_fallback_id(url_text)
            source_ref = f"pocket:{item_id}" if item_id else url_text
            external_id = item_id or url_text
            source_text = " ".join(
                part
                for part in (
                    title_text,
                    summary_text,
                    url_text,
                    f"Tags: {tags_text}" if tags_text else "",
                )
                if str(part or "").strip()
            ).strip()
            payload_json = {
                **dict(record.get("payload") or {}),
                "import_source_path": str(candidate_path),
                "import_channel": "pocket_export",
                "captured_url": url_text,
                "captured_tags": tags_text,
                "received_at": str(record.get("reference_at") or "").strip(),
            }
            items.append(
                self.ingest_office_signal(
                    principal_id=principal_id,
                    signal_type="saved_link",
                    channel="pocket",
                    title=title_text,
                    summary=summary_text or url_text,
                    text=source_text,
                    source_ref=source_ref,
                    external_id=external_id,
                    counterparty=str(counterparty or "").strip() or "Pocket",
                    payload=payload_json,
                    actor=str(actor or "").strip() or "pocket_import",
                )
            )
        deduplicated_total = sum(1 for item in items if bool(item.get("deduplicated")))
        synced_total = len(items) - deduplicated_total
        self._record_product_event(
            principal_id=principal_id,
            event_type="pocket_saved_link_import_completed",
            payload={
                "source_path": str(candidate_path),
                "source_formats": list(source_formats),
                "processed_total": len(items),
                "parsed_entry_total": len(records),
                "synced_total": synced_total,
                "deduplicated_total": deduplicated_total,
            },
            source_id=str(candidate_path),
            dedupe_key=f"{principal_id}|pocket-import|{candidate_path}|{len(records)}|{_now_iso()}",
        )
        return {
            "generated_at": _now_iso(),
            "source_path": str(candidate_path),
            "source_formats": list(source_formats),
            "items": items,
            "total": len(items),
            "synced_total": synced_total,
            "deduplicated_total": deduplicated_total,
            "suppressed_total": 0,
            "parsed_entry_total": len(records),
        }

    def _latest_product_event(self, *, principal_id: str, event_type: str):  # type: ignore[no-untyped-def]
        for row in self._container.channel_runtime.list_recent_observations(
            limit=_POCKET_SYNC_EVENT_LOOKBACK,
            principal_id=principal_id,
        ):
            if str(getattr(row, "channel", "") or "").strip() != "product":
                continue
            if str(getattr(row, "event_type", "") or "").strip() != str(event_type or "").strip():
                continue
            return row
        return None

    def _pocket_sync_cursor(self, *, principal_id: str) -> dict[str, str]:
        last_sync_event = self._latest_product_event(
            principal_id=principal_id,
            event_type="pocket_recording_sync_completed",
        )
        last_reset_event = self._latest_product_event(
            principal_id=principal_id,
            event_type="pocket_recording_sync_cursor_reset",
        )
        last_sync_created_at = str(getattr(last_sync_event, "created_at", "") or "").strip()
        last_reset_created_at = str(getattr(last_reset_event, "created_at", "") or "").strip()
        if last_reset_created_at and (not last_sync_created_at or last_reset_created_at >= last_sync_created_at):
            return {
                "updated_at": "",
                "recording_id": "",
                "completed_at": "",
                "reset_at": last_reset_created_at,
                "reset_reason": str(dict(getattr(last_reset_event, "payload", {}) or {}).get("reason") or "").strip(),
            }
        payload = dict(getattr(last_sync_event, "payload", {}) or {}) if last_sync_event is not None else {}
        return {
            "updated_at": str(payload.get("cursor_updated_at") or "").strip(),
            "recording_id": str(payload.get("cursor_recording_id") or "").strip(),
            "completed_at": last_sync_created_at,
            "reset_at": last_reset_created_at,
            "reset_reason": str(dict(getattr(last_reset_event, "payload", {}) or {}).get("reason") or "").strip(),
        }

    def get_pocket_recording_detail(self, *, recording_id: str, include_audio: bool = True) -> dict[str, object]:
        detail_response = _pocket_get_recording_details(recording_id)
        detail_payload = dict(detail_response.get("data") or {}) if isinstance(detail_response.get("data"), dict) else {}
        if not detail_payload:
            raise RuntimeError("pocket_recording_not_found")
        audio_payload: dict[str, object] | None = None
        if include_audio and str(detail_payload.get("state") or "").strip().lower() == "completed":
            try:
                audio_response = _pocket_get_audio_download_url(recording_id)
            except RuntimeError:
                audio_payload = None
            else:
                audio_payload = dict(audio_response.get("data") or {}) if isinstance(audio_response.get("data"), dict) else {}
        return _pocket_recording_projection(detail_payload, audio_payload=audio_payload)

    def reset_pocket_recording_sync_cursor(
        self,
        *,
        principal_id: str,
        actor: str,
        reason: str = "",
    ) -> dict[str, object]:
        reset_at = _now_iso()
        self._record_product_event(
            principal_id=principal_id,
            event_type="pocket_recording_sync_cursor_reset",
            payload={
                "reason": str(reason or "").strip(),
                "actor": str(actor or "").strip() or "office_api",
            },
            source_id="pocket",
            dedupe_key=f"{principal_id}|pocket-sync-cursor-reset|{reset_at}",
        )
        return {
            "generated_at": _now_iso(),
            "reset_at": reset_at,
            "reason": str(reason or "").strip(),
            "cursor_updated_at": "",
            "cursor_recording_id": "",
            "cursor_cleared": True,
        }

    def _run_pocket_recording_sync(
        self,
        *,
        principal_id: str,
        actor: str,
        limit: int,
        use_cursor: bool,
        persist_cursor: bool,
        mode: str,
        completion_event_type: str,
    ) -> dict[str, object]:
        max_limit = 250 if not use_cursor else 100
        bounded_limit = max(1, min(int(limit or 5), max_limit))
        previous_cursor = self._pocket_sync_cursor(principal_id=principal_id)
        previous_cursor_updated_at = str(previous_cursor.get("updated_at") or "").strip()
        previous_cursor_recording_id = str(previous_cursor.get("recording_id") or "").strip()
        scan_cursor_updated_at = previous_cursor_updated_at if use_cursor else ""
        scan_cursor_recording_id = previous_cursor_recording_id if use_cursor else ""
        cursor_configured = use_cursor and bool(scan_cursor_updated_at or scan_cursor_recording_id)
        page = 1
        rows: list[dict[str, object]] = []
        pages_scanned = 0
        cursor_reached = False
        scan_truncated = False
        while pages_scanned < _POCKET_SYNC_MAX_SCAN_PAGES:
            page_size = min(25, bounded_limit - len(rows)) if not cursor_configured else 25
            if page_size <= 0:
                break
            response = _pocket_list_recordings(limit=page_size, page=page)
            page_rows = list(response.get("data") or []) if isinstance(response.get("data"), list) else []
            for row in page_rows:
                if not isinstance(row, dict):
                    continue
                if cursor_configured and not _pocket_recording_is_newer_than_cursor(
                    row,
                    cursor_updated_at=scan_cursor_updated_at,
                    cursor_recording_id=scan_cursor_recording_id,
                ):
                    cursor_reached = True
                    break
                rows.append(row)
                if not cursor_configured and len(rows) >= bounded_limit:
                    break
            pagination = dict(response.get("pagination") or {}) if isinstance(response.get("pagination"), dict) else {}
            has_more = bool(pagination.get("has_more"))
            pages_scanned += 1
            if cursor_reached or (not cursor_configured and len(rows) >= bounded_limit):
                break
            if not has_more or not page_rows:
                break
            page += 1
        else:
            scan_truncated = True
        items: list[dict[str, object]] = []
        suppressed_total = 0
        failed_total = 0
        failed_recording_ids: list[str] = []
        staging_suppressed_total = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            recording_id = str(row.get("id") or "").strip()
            state = str(row.get("state") or "").strip().lower()
            if not recording_id:
                continue
            if state != "completed":
                suppressed_total += 1
                continue
            try:
                detail = self.get_pocket_recording_detail(recording_id=recording_id, include_audio=False)
            except RuntimeError as exc:
                failed_total += 1
                failed_recording_ids.append(recording_id)
                self._record_product_event(
                    principal_id=principal_id,
                    event_type="pocket_recording_sync_failed",
                    payload={"recording_id": recording_id, "error": str(exc or "unknown_error")},
                    source_id=f"pocket-recording:{recording_id}",
                )
                continue
            transcript_text = str(detail.get("transcript_text") or "").strip()
            summary_markdown = str(detail.get("summary_markdown") or "").strip()
            title = str(detail.get("title") or "").strip() or f"Pocket recording {recording_id}"
            tags = [str(value).strip() for value in list(detail.get("tags") or []) if str(value).strip()]
            summary = compact_text(summary_markdown or transcript_text or title, fallback=title, limit=280)
            text = _pocket_signal_text(title, summary_markdown=summary_markdown, transcript_text=transcript_text)
            should_stage_commitments, staging_suppression_reason = _pocket_should_stage_commitments(
                title=title,
                summary_markdown=summary_markdown,
                transcript_text=transcript_text,
                tags=tags,
            )
            suppress_candidate_staging = not should_stage_commitments
            if suppress_candidate_staging:
                staging_suppressed_total += 1
            items.append(
                self.ingest_office_signal(
                    principal_id=principal_id,
                    signal_type="audio_recording",
                    channel="pocket",
                    title=title,
                    summary=summary,
                    text=text,
                    source_ref=f"pocket-recording:{recording_id}",
                    external_id=recording_id,
                    counterparty="Pocket",
                    payload={
                        "recording_id": recording_id,
                        "recording_state": str(detail.get("state") or "").strip(),
                        "recording_at": str(detail.get("recording_at") or "").strip(),
                        "recording_created_at": str(detail.get("created_at") or "").strip(),
                        "recording_updated_at": str(detail.get("updated_at") or _pocket_recording_effective_updated_at(row)).strip(),
                        "duration": detail.get("duration"),
                        "language": str(detail.get("language") or "").strip(),
                        "tags": tags,
                        "summary_id": str(detail.get("summary_id") or "").strip(),
                        "summary_markdown": summary_markdown,
                        "transcript_excerpt": compact_text(transcript_text, fallback="", limit=4000),
                        "transcript_segment_count": int(detail.get("transcript_segment_count") or 0),
                        "suppress_candidate_staging": suppress_candidate_staging,
                        "staging_suppression_reason": staging_suppression_reason if suppress_candidate_staging else "",
                    },
                    actor=actor,
                )
            )
        deduplicated_total = sum(1 for item in items if bool(item.get("deduplicated")))
        synced_total = len(items) - deduplicated_total
        cursor_updated_at = previous_cursor_updated_at
        cursor_recording_id = previous_cursor_recording_id
        cursor_advanced = False
        if persist_cursor and rows and failed_total == 0 and not scan_truncated:
            newest_fresh_row = rows[0]
            cursor_updated_at = _pocket_recording_effective_updated_at(newest_fresh_row)
            cursor_recording_id = str(newest_fresh_row.get("id") or "").strip()
            cursor_advanced = bool(cursor_updated_at or cursor_recording_id)
        self._record_product_event(
            principal_id=principal_id,
            event_type=completion_event_type,
            payload={
                "mode": mode,
                "processed_total": len(items),
                "recording_total": len(rows),
                "synced_total": synced_total,
                "deduplicated_total": deduplicated_total,
                "suppressed_total": suppressed_total,
                "failed_total": failed_total,
                "failed_recording_ids": failed_recording_ids[:10],
                "staging_suppressed_total": staging_suppressed_total,
                "cursor_used": use_cursor,
                "cursor_persisted": persist_cursor,
                "cursor_updated_at": cursor_updated_at,
                "cursor_recording_id": cursor_recording_id,
                "cursor_advanced": cursor_advanced,
                "previous_cursor_updated_at": previous_cursor_updated_at,
                "previous_cursor_recording_id": previous_cursor_recording_id,
                "scan_truncated": scan_truncated,
                "pages_scanned": pages_scanned,
            },
            source_id="pocket",
            dedupe_key=f"{principal_id}|pocket-sync|{int(limit or 5)}|{_now_iso()}",
        )
        return {
            "generated_at": _now_iso(),
            "mode": mode,
            "items": items,
            "total": len(items),
            "synced_total": synced_total,
            "deduplicated_total": deduplicated_total,
            "suppressed_total": suppressed_total,
            "failed_total": failed_total,
            "recording_total": len(rows),
            "staging_suppressed_total": staging_suppressed_total,
            "cursor_used": use_cursor,
            "cursor_persisted": persist_cursor,
            "cursor_updated_at": cursor_updated_at,
            "cursor_recording_id": cursor_recording_id,
            "cursor_advanced": cursor_advanced,
            "scan_truncated": scan_truncated,
        }

    def sync_pocket_recordings(
        self,
        *,
        principal_id: str,
        actor: str,
        limit: int = 5,
    ) -> dict[str, object]:
        return self._run_pocket_recording_sync(
            principal_id=principal_id,
            actor=actor,
            limit=limit,
            use_cursor=True,
            persist_cursor=True,
            mode="incremental",
            completion_event_type="pocket_recording_sync_completed",
        )

    def backfill_pocket_recordings(
        self,
        *,
        principal_id: str,
        actor: str,
        limit: int = 25,
    ) -> dict[str, object]:
        return self._run_pocket_recording_sync(
            principal_id=principal_id,
            actor=actor,
            limit=limit,
            use_cursor=False,
            persist_cursor=False,
            mode="backfill",
            completion_event_type="pocket_recording_backfill_completed",
        )

    def list_workspace_invitations(
        self,
        *,
        principal_id: str,
        status: str = "",
        limit: int = 100,
    ) -> tuple[dict[str, object], ...]:
        wanted_status = str(status or "").strip().lower()
        invitations: dict[str, dict[str, object]] = {}
        rows = list(self._container.channel_runtime.list_recent_observations(limit=1000, principal_id=principal_id))
        rows.sort(key=lambda row: (str(row.created_at or ""), str(row.observation_id or "")))
        for row in rows:
            event_type = str(row.event_type or "").strip().lower()
            payload = dict(row.payload or {})
            invitation_id = str(payload.get("invitation_id") or row.source_id or "").strip()
            if not invitation_id:
                continue
            if event_type == "workspace_invitation_created":
                invitations[invitation_id] = {
                    "invitation_id": invitation_id,
                    "email": str(payload.get("email") or "").strip().lower(),
                    "role": str(payload.get("role") or "operator").strip().lower() or "operator",
                    "display_name": str(payload.get("display_name") or "").strip(),
                    "note": str(payload.get("note") or "").strip(),
                    "status": "pending",
                    "invited_by": str(payload.get("invited_by") or "").strip(),
                    "invited_at": str(payload.get("invited_at") or row.created_at or ""),
                    "expires_at": str(payload.get("expires_at") or "").strip(),
                    "accepted_at": "",
                    "accepted_by": "",
                    "revoked_at": "",
                    "invite_url": str(payload.get("invite_url") or "").strip(),
                    "invite_token": str(payload.get("invite_token") or "").strip(),
                    "operator_id": str(payload.get("operator_id") or "").strip(),
                }
            elif event_type == "workspace_invitation_accepted" and invitation_id in invitations:
                invitations[invitation_id].update(
                    {
                        "status": "accepted",
                        "accepted_at": str(payload.get("accepted_at") or row.created_at or ""),
                        "accepted_by": str(payload.get("accepted_by") or "").strip(),
                        "operator_id": str(payload.get("operator_id") or invitations[invitation_id].get("operator_id") or "").strip(),
                    }
                )
            elif event_type == "workspace_invitation_revoked" and invitation_id in invitations:
                invitations[invitation_id].update(
                    {
                        "status": "revoked",
                        "revoked_at": str(payload.get("revoked_at") or row.created_at or ""),
                    }
                )
        items = list(invitations.values())
        if wanted_status:
            items = [item for item in items if str(item.get("status") or "").strip().lower() == wanted_status]
        items.sort(key=lambda item: (str(item.get("invited_at") or ""), str(item.get("invitation_id") or "")), reverse=True)
        return tuple(items[:limit])

    def get_workspace_invitation(self, *, principal_id: str, invitation_id: str) -> dict[str, object] | None:
        normalized = str(invitation_id or "").strip()
        if not normalized:
            return None
        for row in self.list_workspace_invitations(principal_id=principal_id, limit=200):
            if str(row.get("invitation_id") or "").strip() == normalized:
                return row
        return None

    def create_workspace_invitation(
        self,
        *,
        principal_id: str,
        email: str,
        role: str,
        invited_by: str,
        display_name: str = "",
        note: str = "",
        expires_in_days: int = 14,
        base_url: str = "",
    ) -> dict[str, object]:
        normalized_email = str(email or "").strip().lower()
        normalized_role = str(role or "operator").strip().lower() or "operator"
        invitation_id = f"invite_{uuid4().hex[:10]}"
        expires_at = datetime.now(timezone.utc).timestamp() + max(int(expires_in_days), 1) * 86400
        token_payload = {
            "token_kind": "workspace_invitation",
            "principal_id": principal_id,
            "invitation_id": invitation_id,
            "email": normalized_email,
            "role": normalized_role,
            "display_name": str(display_name or "").strip(),
            "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        }
        invite_token = _sign_channel_payload(secret=self._channel_action_secret(), payload=token_payload)
        invite_path = f"/workspace-invites/{invite_token}"
        absolute_invite_url = urllib.parse.urljoin(str(base_url or "").strip(), invite_path) if str(base_url or "").strip() else invite_path
        payload = {
            "invitation_id": invitation_id,
            "email": normalized_email,
            "role": normalized_role,
            "display_name": str(display_name or "").strip(),
            "note": str(note or "").strip(),
            "invited_by": str(invited_by or "").strip() or "workspace",
            "invited_at": _now_iso(),
            "expires_at": str(token_payload["expires_at"]),
            "invite_token": invite_token,
            "invite_url": invite_path,
            "operator_id": _operator_id_from_email(normalized_email) if normalized_role == "operator" else "",
            "email_delivery_status": "not_configured" if normalized_email and not email_delivery_enabled() else "",
            "email_delivery_error": "",
            "email_message_id": "",
            "email_provider": "",
        }
        if normalized_email and email_delivery_enabled():
            try:
                receipt = send_workspace_invitation_email(
                    recipient_email=normalized_email,
                    invite_url=absolute_invite_url,
                    role=normalized_role,
                    invited_by=payload["invited_by"],
                    note=payload["note"],
                    expires_at=payload["expires_at"],
                )
                payload["email_delivery_status"] = "sent"
                payload["email_message_id"] = receipt.message_id
                payload["email_provider"] = receipt.provider
                self._record_product_event(
                    principal_id=principal_id,
                    event_type="workspace_invitation_email_sent",
                    payload={"invitation_id": invitation_id, "recipient_email": normalized_email, "provider": receipt.provider},
                    source_id=invitation_id,
                    dedupe_key=f"{principal_id}|{invitation_id}|invite-email-sent",
                )
            except RuntimeError as exc:
                payload["email_delivery_status"] = "failed"
                payload["email_delivery_error"] = str(exc)
                self._record_product_event(
                    principal_id=principal_id,
                    event_type="workspace_invitation_email_failed",
                    payload={"invitation_id": invitation_id, "recipient_email": normalized_email, "error": str(exc)},
                    source_id=invitation_id,
                    dedupe_key=f"{principal_id}|{invitation_id}|invite-email-failed",
                )
        self._record_product_event(
            principal_id=principal_id,
            event_type="workspace_invitation_created",
            payload=payload,
            source_id=invitation_id,
            dedupe_key=f"{principal_id}|{invitation_id}",
        )
        found = self.get_workspace_invitation(principal_id=principal_id, invitation_id=invitation_id)
        return dict(found or payload)

    def preview_workspace_invitation(self, *, token: str) -> dict[str, object] | None:
        payload = _verify_channel_payload(secret=self._channel_action_secret(), token=token)
        if payload is None or str(payload.get("token_kind") or "").strip() != "workspace_invitation":
            return None
        principal_id = str(payload.get("principal_id") or "").strip()
        invitation_id = str(payload.get("invitation_id") or "").strip()
        if not principal_id or not invitation_id:
            return None
        current = self.get_workspace_invitation(principal_id=principal_id, invitation_id=invitation_id)
        if current is not None:
            return current
        return {
            "invitation_id": invitation_id,
            "email": str(payload.get("email") or "").strip().lower(),
            "role": str(payload.get("role") or "operator").strip().lower() or "operator",
            "display_name": str(payload.get("display_name") or "").strip(),
            "note": "",
            "status": "pending",
            "invited_by": "",
            "invited_at": "",
            "expires_at": str(payload.get("expires_at") or "").strip(),
            "accepted_at": "",
            "accepted_by": "",
            "revoked_at": "",
            "invite_url": f"/workspace-invites/{token}",
            "invite_token": str(token or "").strip(),
            "operator_id": _operator_id_from_email(str(payload.get("email") or "").strip().lower()),
        }

    def issue_workspace_access_session(
        self,
        *,
        principal_id: str,
        email: str,
        role: str,
        display_name: str = "",
        operator_id: str = "",
        source_kind: str = "workspace_access",
        expires_in_hours: int = 72,
    ) -> dict[str, object]:
        normalized_email = str(email or "").strip().lower()
        normalized_role = str(role or "principal").strip().lower() or "principal"
        resolved_operator_id = str(operator_id or "").strip()
        if normalized_role == "operator" and not resolved_operator_id:
            resolved_operator_id = _operator_id_from_email(normalized_email)
        expires_at = datetime.now(timezone.utc).timestamp() + max(int(expires_in_hours), 1) * 3600
        session_id = f"access_{uuid4().hex[:10]}"
        token_payload = {
            "token_kind": "workspace_access_session",
            "session_id": session_id,
            "principal_id": str(principal_id or "").strip(),
            "email": normalized_email,
            "role": normalized_role,
            "display_name": str(display_name or "").strip(),
            "operator_id": resolved_operator_id,
            "source_kind": str(source_kind or "workspace_access").strip() or "workspace_access",
            "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        }
        access_token = _sign_channel_payload(secret=self._workspace_access_secret(), payload=token_payload)
        default_target = "/admin/office" if normalized_role == "operator" else "/app/today"
        payload = {
            "session_id": session_id,
            "principal_id": str(principal_id or "").strip(),
            "email": normalized_email,
            "role": normalized_role,
            "display_name": str(display_name or "").strip(),
            "operator_id": resolved_operator_id,
            "source_kind": str(token_payload["source_kind"]),
            "issued_at": _now_iso(),
            "status": "active",
            "revoked_at": "",
            "revoked_by": "",
            "expires_at": str(token_payload["expires_at"]),
            "access_token": access_token,
            "access_url": f"/workspace-access/{access_token}",
            "default_target": default_target,
        }
        self._record_product_event(
            principal_id=principal_id,
            event_type="workspace_access_session_issued",
            payload=payload,
            source_id=session_id,
            dedupe_key=f"{principal_id}|{session_id}",
        )
        return payload

    def list_workspace_access_sessions(
        self,
        *,
        principal_id: str,
        status: str = "",
        limit: int = 100,
    ) -> tuple[dict[str, object], ...]:
        wanted_status = str(status or "").strip().lower()
        sessions: dict[str, dict[str, object]] = {}
        rows = list(self._container.channel_runtime.list_recent_observations(limit=1000, principal_id=principal_id))
        rows.sort(key=lambda row: (str(row.created_at or ""), str(row.observation_id or "")))
        for row in rows:
            event_type = str(row.event_type or "").strip().lower()
            payload = dict(row.payload or {})
            session_id = str(payload.get("session_id") or row.source_id or "").strip()
            if not session_id:
                continue
            if event_type == "workspace_access_session_issued":
                normalized_role = str(payload.get("role") or "principal").strip().lower() or "principal"
                sessions[session_id] = {
                    "session_id": session_id,
                    "principal_id": str(payload.get("principal_id") or principal_id).strip(),
                    "email": str(payload.get("email") or "").strip().lower(),
                    "role": normalized_role,
                    "display_name": str(payload.get("display_name") or "").strip(),
                    "operator_id": str(payload.get("operator_id") or "").strip() if normalized_role == "operator" else "",
                    "source_kind": str(payload.get("source_kind") or "").strip(),
                    "issued_at": str(payload.get("issued_at") or row.created_at or ""),
                    "status": "active",
                    "revoked_at": "",
                    "revoked_by": "",
                    "expires_at": str(payload.get("expires_at") or "").strip(),
                    "access_token": str(payload.get("access_token") or "").strip(),
                    "access_url": str(payload.get("access_url") or "").strip(),
                    "default_target": str(payload.get("default_target") or ("/admin/office" if normalized_role == "operator" else "/app/today")).strip(),
                }
            elif event_type == "workspace_access_session_revoked" and session_id in sessions:
                sessions[session_id].update(
                    {
                        "status": "revoked",
                        "revoked_at": str(payload.get("revoked_at") or row.created_at or ""),
                        "revoked_by": str(payload.get("revoked_by") or "").strip(),
                    }
                )
        items = list(sessions.values())
        if wanted_status:
            items = [item for item in items if str(item.get("status") or "").strip().lower() == wanted_status]
        items.sort(key=lambda item: (str(item.get("issued_at") or ""), str(item.get("session_id") or "")), reverse=True)
        return tuple(items[:limit])

    def get_workspace_access_session(self, *, principal_id: str, session_id: str) -> dict[str, object] | None:
        normalized = str(session_id or "").strip()
        if not normalized:
            return None
        for row in self.list_workspace_access_sessions(principal_id=principal_id, limit=200):
            if str(row.get("session_id") or "").strip() == normalized:
                return row
        return None

    def preview_workspace_access_session(self, *, token: str) -> dict[str, object] | None:
        payload = _verify_channel_payload(secret=self._workspace_access_secret(), token=token)
        if payload is None or str(payload.get("token_kind") or "").strip() != "workspace_access_session":
            return None
        principal_id = str(payload.get("principal_id") or "").strip()
        session_id = str(payload.get("session_id") or "").strip()
        if not principal_id or not session_id:
            return None
        current = self.get_workspace_access_session(principal_id=principal_id, session_id=session_id)
        if current is not None:
            if str(current.get("status") or "").strip().lower() == "revoked":
                return None
            return current
        normalized_role = str(payload.get("role") or "principal").strip().lower() or "principal"
        return {
            "session_id": session_id,
            "principal_id": principal_id,
            "email": str(payload.get("email") or "").strip().lower(),
            "role": normalized_role,
            "display_name": str(payload.get("display_name") or "").strip(),
            "operator_id": str(payload.get("operator_id") or "").strip() if normalized_role == "operator" else "",
            "source_kind": str(payload.get("source_kind") or "").strip(),
            "issued_at": "",
            "status": "active",
            "revoked_at": "",
            "revoked_by": "",
            "expires_at": str(payload.get("expires_at") or "").strip(),
            "access_token": str(token or "").strip(),
            "access_url": f"/workspace-access/{token}",
            "default_target": "/admin/office" if normalized_role == "operator" else "/app/today",
        }

    def open_workspace_access_session(self, *, token: str, actor: str = "") -> dict[str, object] | None:
        session = self.preview_workspace_access_session(token=token)
        if session is None:
            return None
        principal_id = str(session.get("principal_id") or "").strip()
        session_id = str(session.get("session_id") or "").strip()
        if principal_id and session_id:
            self._record_product_event(
                principal_id=principal_id,
                event_type="workspace_access_session_opened",
                payload={
                    "session_id": session_id,
                    "email": str(session.get("email") or "").strip().lower(),
                    "role": str(session.get("role") or "principal").strip().lower() or "principal",
                    "operator_id": str(session.get("operator_id") or "").strip(),
                    "source_kind": str(session.get("source_kind") or "").strip(),
                    "opened_at": _now_iso(),
                    "opened_by": str(actor or session.get("email") or principal_id or "workspace_access").strip(),
                },
                source_id=session_id,
            )
        return session

    def revoke_workspace_access_session(
        self,
        *,
        principal_id: str,
        session_id: str,
        actor: str,
    ) -> dict[str, object] | None:
        current = self.get_workspace_access_session(principal_id=principal_id, session_id=session_id)
        if current is None:
            return None
        if str(current.get("status") or "").strip().lower() == "revoked":
            return current
        self._record_product_event(
            principal_id=principal_id,
            event_type="workspace_access_session_revoked",
            payload={
                "session_id": str(session_id or "").strip(),
                "revoked_at": _now_iso(),
                "revoked_by": str(actor or "").strip() or "workspace",
            },
            source_id=str(session_id or "").strip(),
            dedupe_key=f"{principal_id}|{session_id}|revoked",
        )
        return self.get_workspace_access_session(principal_id=principal_id, session_id=session_id)

    def accept_workspace_invitation(
        self,
        *,
        token: str,
        accepted_by: str,
        display_name: str = "",
        operator_id: str = "",
    ) -> dict[str, object] | None:
        raw_payload = _verify_channel_payload(secret=self._channel_action_secret(), token=token)
        if raw_payload is None or str(raw_payload.get("token_kind") or "").strip() != "workspace_invitation":
            return None
        preview = self.preview_workspace_invitation(token=token)
        if preview is None:
            return None
        current_status = str(preview.get("status") or "").strip().lower()
        if current_status == "revoked":
            return preview
        principal_id = str(raw_payload.get("principal_id") or "").strip()
        invitation_id = str(preview.get("invitation_id") or "").strip()
        role = str(preview.get("role") or "operator").strip().lower() or "operator"
        email = str(preview.get("email") or "").strip().lower()
        resolved_operator_id = str(operator_id or preview.get("operator_id") or "").strip()
        resolved_display_name = str(display_name or preview.get("display_name") or email or "Workspace Operator").strip()
        if current_status == "pending" and role == "operator":
            if not resolved_operator_id:
                resolved_operator_id = _operator_id_from_email(email)
            existing = self._container.orchestrator.fetch_operator_profile(resolved_operator_id, principal_id=principal_id)
            if existing is None:
                status = self._container.onboarding.status(principal_id=principal_id)
                workspace = dict(status.get("workspace") or {})
                plan = workspace_plan_for_mode(str(workspace.get("mode") or "personal"))
                active = self._container.orchestrator.list_operator_profiles(principal_id=principal_id, status="active", limit=500)
                if len(active) >= plan.entitlements.operator_seats:
                    raise ValueError("operator_seat_limit_reached")
            self._container.orchestrator.upsert_operator_profile(
                principal_id=principal_id,
                operator_id=resolved_operator_id,
                display_name=resolved_display_name,
                roles=(role,),
                trust_tier="standard",
                status="active",
                notes=f"Accepted workspace invite for {email}.",
            )
        if current_status == "pending":
            self._record_product_event(
                principal_id=principal_id,
                event_type="workspace_invitation_accepted",
                payload={
                    "invitation_id": invitation_id,
                    "accepted_by": str(accepted_by or email or "workspace").strip() or "workspace",
                    "accepted_at": _now_iso(),
                    "operator_id": resolved_operator_id,
                },
                source_id=invitation_id,
                dedupe_key=f"{principal_id}|{invitation_id}|accepted",
            )
        access_session = self.issue_workspace_access_session(
            principal_id=principal_id,
            email=email,
            role=role,
            display_name=resolved_display_name,
            operator_id=resolved_operator_id,
            source_kind="workspace_invite",
        )
        current = self.get_workspace_invitation(principal_id=principal_id, invitation_id=invitation_id)
        return {
            **dict(current or preview),
            "access_token": str(access_session.get("access_token") or "").strip(),
            "access_url": str(access_session.get("access_url") or "").strip(),
            "access_expires_at": str(access_session.get("expires_at") or "").strip(),
        }

    def revoke_workspace_invitation(
        self,
        *,
        principal_id: str,
        invitation_id: str,
        actor: str,
    ) -> dict[str, object] | None:
        current = self.get_workspace_invitation(principal_id=principal_id, invitation_id=invitation_id)
        if current is None:
            return None
        if str(current.get("status") or "").strip().lower() == "revoked":
            return current
        self._record_product_event(
            principal_id=principal_id,
            event_type="workspace_invitation_revoked",
            payload={
                "invitation_id": str(invitation_id or "").strip(),
                "revoked_at": _now_iso(),
                "revoked_by": str(actor or "").strip() or "workspace",
            },
            source_id=str(invitation_id or "").strip(),
            dedupe_key=f"{principal_id}|{invitation_id}|revoked",
        )
        return self.get_workspace_invitation(principal_id=principal_id, invitation_id=invitation_id)

    def _workspace_sign_in_candidates(
        self,
        *,
        email: str,
        observation_limit: int = 5000,
        per_principal_limit: int = 200,
    ) -> tuple[dict[str, object], ...]:
        normalized_email = str(email or "").strip().lower()
        if not normalized_email:
            return ()
        principal_last_seen: dict[str, str] = {}
        for row in self._container.channel_runtime.list_recent_observations(limit=max(int(observation_limit), 100)):
            payload = dict(row.payload or {})
            email_values = (
                str(payload.get("email") or "").strip().lower(),
                str(payload.get("recipient_email") or "").strip().lower(),
            )
            if normalized_email not in email_values:
                continue
            principal_id = str(row.principal_id or "").strip()
            if not principal_id:
                continue
            created_at = str(row.created_at or "").strip()
            previous = str(principal_last_seen.get(principal_id) or "").strip()
            if not previous or created_at > previous:
                principal_last_seen[principal_id] = created_at
        candidates: list[dict[str, object]] = []
        for principal_id, last_seen_at in sorted(principal_last_seen.items(), key=lambda item: item[1], reverse=True):
            status = self._container.onboarding.status(principal_id=principal_id)
            workspace = dict(status.get("workspace") or {})
            workspace_name = str(workspace.get("name") or "Executive Workspace").strip() or "Executive Workspace"
            access_matches = [
                dict(row)
                for row in self.list_workspace_access_sessions(
                    principal_id=principal_id,
                    status="active",
                    limit=max(int(per_principal_limit), 50),
                )
                if str(row.get("email") or "").strip().lower() == normalized_email
            ]
            access_matches.sort(
                key=lambda row: (
                    str(row.get("issued_at") or ""),
                    str(row.get("session_id") or ""),
                ),
                reverse=True,
            )
            if access_matches:
                selected = access_matches[0]
                candidates.append(
                    {
                        "kind": "access",
                        "principal_id": principal_id,
                        "workspace_name": workspace_name,
                        "email": normalized_email,
                        "role": str(selected.get("role") or "principal").strip().lower() or "principal",
                        "display_name": str(selected.get("display_name") or workspace_name).strip() or workspace_name,
                        "operator_id": str(selected.get("operator_id") or "").strip(),
                    }
                )
                continue
            accepted_invites = [
                dict(row)
                for row in self.list_workspace_invitations(
                    principal_id=principal_id,
                    status="accepted",
                    limit=max(int(per_principal_limit), 50),
                )
                if str(row.get("email") or "").strip().lower() == normalized_email
            ]
            accepted_invites.sort(
                key=lambda row: (
                    str(row.get("accepted_at") or row.get("invited_at") or ""),
                    str(row.get("invitation_id") or ""),
                ),
                reverse=True,
            )
            if accepted_invites:
                selected = accepted_invites[0]
                candidates.append(
                    {
                        "kind": "access",
                        "principal_id": principal_id,
                        "workspace_name": workspace_name,
                        "email": normalized_email,
                        "role": str(selected.get("role") or "operator").strip().lower() or "operator",
                        "display_name": str(selected.get("display_name") or workspace_name).strip() or workspace_name,
                        "operator_id": str(selected.get("operator_id") or "").strip(),
                    }
                )
                continue
            pending_invites = [
                dict(row)
                for row in self.list_workspace_invitations(
                    principal_id=principal_id,
                    status="pending",
                    limit=max(int(per_principal_limit), 50),
                )
                if str(row.get("email") or "").strip().lower() == normalized_email
            ]
            pending_invites.sort(
                key=lambda row: (
                    str(row.get("invited_at") or ""),
                    str(row.get("invitation_id") or ""),
                ),
                reverse=True,
            )
            if pending_invites:
                selected = pending_invites[0]
                candidates.append(
                    {
                        "kind": "invite",
                        "principal_id": principal_id,
                        "workspace_name": workspace_name,
                        "email": normalized_email,
                        "role": str(selected.get("role") or "operator").strip().lower() or "operator",
                        "display_name": str(selected.get("display_name") or "").strip(),
                        "invited_by": str(selected.get("invited_by") or "").strip(),
                        "note": str(selected.get("note") or "").strip(),
                        "invite_url": str(selected.get("invite_url") or "").strip(),
                        "expires_at": str(selected.get("expires_at") or "").strip(),
                    }
                )
        return tuple(candidates)

    def request_workspace_sign_in_email_links(
        self,
        *,
        email: str,
        base_url: str = "",
        expires_in_hours: int = 72,
    ) -> dict[str, object]:
        normalized_email = str(email or "").strip().lower()
        if "@" not in normalized_email or "." not in normalized_email.rsplit("@", 1)[-1]:
            raise ValueError("workspace_sign_in_email_invalid")
        if not email_delivery_enabled():
            raise RuntimeError("workspace_sign_in_email_delivery_not_configured")
        candidates = self._workspace_sign_in_candidates(email=normalized_email)
        if not candidates:
            return {
                "status": "not_found",
                "email": normalized_email,
                "workspace_total": 0,
                "sent_total": 0,
                "failed_total": 0,
                "items": [],
            }
        sent_total = 0
        failed_total = 0
        items: list[dict[str, object]] = []
        for candidate in candidates:
            principal_id = str(candidate.get("principal_id") or "").strip()
            workspace_name = str(candidate.get("workspace_name") or "Executive Workspace").strip() or "Executive Workspace"
            kind = str(candidate.get("kind") or "access").strip().lower() or "access"
            role = str(candidate.get("role") or "principal").strip().lower() or "principal"
            display_name = str(candidate.get("display_name") or workspace_name).strip() or workspace_name
            try:
                if kind == "invite":
                    invite_url = str(candidate.get("invite_url") or "").strip()
                    if not invite_url:
                        raise RuntimeError("workspace_invite_url_missing")
                    absolute_invite_url = urllib.parse.urljoin(str(base_url or "").strip(), invite_url) if str(base_url or "").strip() else invite_url
                    receipt = send_workspace_invitation_email(
                        recipient_email=normalized_email,
                        invite_url=absolute_invite_url,
                        role=role,
                        invited_by=str(candidate.get("invited_by") or workspace_name).strip() or workspace_name,
                        note=str(candidate.get("note") or "").strip(),
                        expires_at=str(candidate.get("expires_at") or "").strip(),
                    )
                    self._record_product_event(
                        principal_id=principal_id,
                        event_type="workspace_sign_in_invite_email_sent",
                        payload={
                            "recipient_email": normalized_email,
                            "workspace_name": workspace_name,
                            "role": role,
                            "provider": receipt.provider,
                        },
                        source_id=f"signin-invite:{normalized_email}:{principal_id}",
                    )
                    sent_total += 1
                    items.append(
                        {
                            "kind": kind,
                            "workspace_name": workspace_name,
                            "principal_id": principal_id,
                            "status": "sent",
                            "role": role,
                        }
                    )
                    continue
                access_session = self.issue_workspace_access_session(
                    principal_id=principal_id,
                    email=normalized_email,
                    role=role,
                    display_name=display_name,
                    operator_id=str(candidate.get("operator_id") or "").strip(),
                    source_kind="sign_in_email",
                    expires_in_hours=expires_in_hours,
                )
                access_url = str(access_session.get("access_url") or "").strip()
                absolute_access_url = urllib.parse.urljoin(str(base_url or "").strip(), access_url) if str(base_url or "").strip() else access_url
                receipt = send_workspace_access_email(
                    recipient_email=normalized_email,
                    workspace_name=workspace_name,
                    access_url=absolute_access_url,
                    role=role,
                    display_name=display_name,
                    expires_at=str(access_session.get("expires_at") or "").strip(),
                )
                self._record_product_event(
                    principal_id=principal_id,
                    event_type="workspace_sign_in_access_email_sent",
                    payload={
                        "recipient_email": normalized_email,
                        "workspace_name": workspace_name,
                        "role": role,
                        "provider": receipt.provider,
                        "access_session_id": str(access_session.get("session_id") or "").strip(),
                    },
                    source_id=f"signin-access:{normalized_email}:{principal_id}",
                )
                sent_total += 1
                items.append(
                    {
                        "kind": kind,
                        "workspace_name": workspace_name,
                        "principal_id": principal_id,
                        "status": "sent",
                        "role": role,
                    }
                )
            except RuntimeError as exc:
                failed_total += 1
                error_text = str(exc or "workspace_sign_in_email_send_failed")
                self._record_product_event(
                    principal_id=principal_id,
                    event_type="workspace_sign_in_email_failed",
                    payload={
                        "recipient_email": normalized_email,
                        "workspace_name": workspace_name,
                        "role": role,
                        "error": error_text,
                        "kind": kind,
                    },
                    source_id=f"signin-failed:{normalized_email}:{principal_id}:{kind}",
                )
                items.append(
                    {
                        "kind": kind,
                        "workspace_name": workspace_name,
                        "principal_id": principal_id,
                        "status": "failed",
                        "role": role,
                        "error": error_text,
                    }
                )
        status = "sent" if sent_total and not failed_total else "partial" if sent_total else "failed"
        return {
            "status": status,
            "email": normalized_email,
            "workspace_total": len(candidates),
            "sent_total": sent_total,
            "failed_total": failed_total,
            "items": items,
        }

    def send_google_connect_email_link(
        self,
        *,
        principal_id: str,
        recipient_email: str,
        scope_bundle: str = "full_workspace",
        base_url: str = "",
        expires_in_hours: int = 72,
    ) -> dict[str, object]:
        normalized_email = str(recipient_email or "").strip().lower()
        if "@" not in normalized_email or "." not in normalized_email.rsplit("@", 1)[-1]:
            raise ValueError("google_connect_email_invalid")
        if not email_delivery_enabled():
            raise RuntimeError("google_connect_email_delivery_not_configured")
        normalized_bundle = google_oauth_service.normalize_scope_bundle(scope_bundle)
        if normalized_bundle == "all":
            normalized_bundle = "full_workspace"
        workspace = dict(self._container.onboarding.status(principal_id=principal_id).get("workspace") or {})
        workspace_name = str(workspace.get("name") or "Executive Workspace").strip() or "Executive Workspace"
        accounts = sorted(
            google_oauth_service.list_google_accounts(container=self._container, principal_id=principal_id),
            key=lambda account: (
                account.binding.binding_id != f"{account.binding.principal_id}:{google_oauth_service.GOOGLE_PROVIDER_KEY}",
                str(account.google_email or "").strip().lower(),
            ),
        )
        primary_account = next(
            (
                account
                for account in accounts
                if str(account.binding.binding_id or "").strip()
                == f"{account.binding.principal_id}:{google_oauth_service.GOOGLE_PROVIDER_KEY}"
            ),
            accounts[0] if accounts else None,
        )
        access_session = self.issue_workspace_access_session(
            principal_id=principal_id,
            email=normalized_email,
            role="principal",
            display_name=workspace_name,
            source_kind="google_connect_email",
            expires_in_hours=expires_in_hours,
        )
        connect_path = "/app/actions/google/connect?" + urllib.parse.urlencode(
            {
                "return_to": "/app/settings/google",
                "scope_bundle": normalized_bundle,
            }
        )
        access_path = (
            f"{str(access_session.get('access_url') or '').strip()}?"
            f"return_to={urllib.parse.quote(connect_path, safe='/')}"
        )
        absolute_connect_url = urllib.parse.urljoin(str(base_url or "").strip(), access_path) if str(base_url or "").strip() else access_path
        bundle_details = google_oauth_service.google_scope_bundle_details(normalized_bundle)
        try:
            receipt = send_google_connect_email(
                recipient_email=normalized_email,
                workspace_name=workspace_name,
                connect_url=absolute_connect_url,
                scope_label=str(bundle_details.get("label") or normalized_bundle).strip() or normalized_bundle,
                scope_summary=str(bundle_details.get("summary") or "").strip(),
                primary_google_email=str(getattr(primary_account, "google_email", "") or "").strip(),
                connected_account_total=len(accounts),
                expires_at=str(access_session.get("expires_at") or "").strip(),
            )
        except RuntimeError as exc:
            error_text = str(exc or "google_connect_email_send_failed")
            self._record_product_event(
                principal_id=principal_id,
                event_type="google_connect_email_failed",
                payload={
                    "recipient_email": normalized_email,
                    "workspace_name": workspace_name,
                    "scope_bundle": normalized_bundle,
                    "error": error_text,
                },
                source_id=f"google-connect-email:{normalized_email}:{normalized_bundle}",
            )
            raise
        self._record_product_event(
            principal_id=principal_id,
            event_type="google_connect_email_sent",
            payload={
                "recipient_email": normalized_email,
                "workspace_name": workspace_name,
                "scope_bundle": normalized_bundle,
                "provider": receipt.provider,
                "access_session_id": str(access_session.get("session_id") or "").strip(),
                "connected_account_total": len(accounts),
                "primary_google_email": str(getattr(primary_account, "google_email", "") or "").strip(),
            },
            source_id=f"google-connect-email:{normalized_email}:{normalized_bundle}",
        )
        return {
            "status": "sent",
            "recipient_email": normalized_email,
            "workspace_name": workspace_name,
            "scope_bundle": normalized_bundle,
            "scope_label": str(bundle_details.get("label") or normalized_bundle).strip() or normalized_bundle,
            "connected_account_total": len(accounts),
            "primary_google_email": str(getattr(primary_account, "google_email", "") or "").strip(),
            "connect_url": access_path,
            "access_session_id": str(access_session.get("session_id") or "").strip(),
            "email_provider": receipt.provider,
            "email_message_id": receipt.message_id,
        }

    def create_commitment(
        self,
        *,
        principal_id: str,
        title: str,
        details: str = "",
        due_at: str | None = None,
        priority: str = "medium",
        counterparty: str = "",
        owner: str = "office",
        kind: str = "commitment",
        stakeholder_id: str = "",
        channel_hint: str = "email",
        source_type: str = "manual",
        source_ref: str = "",
        confidence: float = 1.0,
        signal_type: str = "",
    ) -> CommitmentItem:
        normalized_kind = str(kind or "commitment").strip().lower()
        normalized_channel_hint = str(channel_hint or "email").strip() or "email"
        normalized_source_type = str(source_type or "manual").strip() or "manual"
        normalized_source_ref = str(source_ref or "").strip()
        normalized_signal_type = str(signal_type or "").strip()
        resolved_stakeholder_id = self._resolve_stakeholder_ref(
            principal_id=principal_id,
            stakeholder_id=stakeholder_id,
            counterparty=counterparty,
        )
        source_json = {
            "source_type": normalized_source_type,
            "counterparty": counterparty,
            "owner": owner,
            "channel_hint": normalized_channel_hint,
            "confidence": confidence,
            "source_ref": normalized_source_ref,
            "signal_type": normalized_signal_type,
        }
        if normalized_kind == "follow_up" and resolved_stakeholder_id:
            row = self._container.memory_runtime.upsert_follow_up(
                principal_id=principal_id,
                stakeholder_ref=resolved_stakeholder_id,
                topic=title,
                status="open",
                due_at=due_at,
                channel_hint=normalized_channel_hint,
                notes=details,
                source_json=source_json,
            )
            self._record_product_event(
                principal_id=principal_id,
                event_type="commitment_created",
                payload={"kind": "follow_up", "title": title, "counterparty": counterparty, "due_at": due_at or ""},
                source_id=row.follow_up_id,
            )
            return self._commitment_item_from_follow_up(row, self._stakeholder_lookup(principal_id))
        row = self._container.memory_runtime.upsert_commitment(
            principal_id=principal_id,
            title=title,
            details=details,
            status="open",
            priority=priority,
            due_at=due_at,
            source_json=source_json,
        )
        self._record_product_event(
            principal_id=principal_id,
            event_type="commitment_created",
            payload={"kind": "commitment", "title": title, "counterparty": counterparty, "due_at": due_at or ""},
            source_id=row.commitment_id,
        )
        return self._commitment_item_from_commitment(row)

    def extract_commitments(
        self,
        *,
        text: str,
        counterparty: str = "",
        due_at: str | None = None,
        reference_at: str | None = None,
        allow_generic_fallback: bool = True,
    ) -> tuple[CommitmentCandidate, ...]:
        return extract_commitment_candidates(
            text,
            counterparty=counterparty,
            due_at=due_at,
            reference_at=reference_at,
            allow_generic_fallback=allow_generic_fallback,
        )

    def _candidate_from_memory_row(self, row) -> CommitmentCandidate:  # type: ignore[no-untyped-def]
        fact = dict(getattr(row, "fact_json", {}) or {})
        duplicate_of_ref = str(fact.get("duplicate_of_ref") or "").strip()
        status = str(getattr(row, "status", "pending") or "pending")
        if duplicate_of_ref and status == "pending":
            status = "duplicate"
        return CommitmentCandidate(
            candidate_id=str(getattr(row, "candidate_id", "") or ""),
            title=str(fact.get("title") or getattr(row, "summary", "") or "Commitment candidate"),
            details=str(fact.get("details") or getattr(row, "summary", "") or ""),
            source_text=str(fact.get("source_text") or ""),
            confidence=float(getattr(row, "confidence", 0.5) or 0.5),
            suggested_due_at=str(fact.get("suggested_due_at") or "") or None,
            counterparty=str(fact.get("counterparty") or ""),
            channel_hint=str(fact.get("channel_hint") or ""),
            source_ref=str(fact.get("source_ref") or ""),
            signal_type=str(fact.get("signal_type") or ""),
            status=status,
            kind=str(fact.get("kind") or "commitment"),
            stakeholder_id=str(fact.get("stakeholder_id") or ""),
            duplicate_of_ref=duplicate_of_ref,
            merge_strategy="merge" if duplicate_of_ref else "create",
        )

    def list_commitment_candidates(self, *, principal_id: str, limit: int = 20, status: str | None = None) -> tuple[CommitmentCandidate, ...]:
        rows = self._container.memory_runtime.list_candidates(limit=max(limit * 4, 50), status=None, principal_id=principal_id)
        filtered = [row for row in rows if str(getattr(row, "category", "") or "") == "product_commitment_candidate"]
        projected = tuple(self._candidate_from_memory_row(row) for row in filtered)
        if status is not None:
            wanted = str(status or "").strip().lower()
            projected = tuple(row for row in projected if str(row.status or "").strip().lower() == wanted)
        return tuple(projected[:limit])

    def list_reviewable_commitment_candidates(self, *, principal_id: str, limit: int = 20) -> tuple[CommitmentCandidate, ...]:
        return tuple(
            row
            for row in self.list_commitment_candidates(principal_id=principal_id, limit=max(limit * 4, 50), status=None)
            if str(row.status or "").strip().lower() in {"pending", "duplicate"}
        )[:limit]

    def get_commitment_candidate(self, *, principal_id: str, candidate_id: str) -> CommitmentCandidate | None:
        row = self._container.memory_runtime.get_candidate(candidate_id, principal_id=principal_id)
        if row is None or str(getattr(row, "category", "") or "") != "product_commitment_candidate":
            return None
        return self._candidate_from_memory_row(row)

    def stage_extracted_commitments(
        self,
        *,
        principal_id: str,
        text: str,
        counterparty: str = "",
        due_at: str | None = None,
        kind: str = "commitment",
        stakeholder_id: str = "",
        channel_hint: str = "",
        source_ref: str = "",
        signal_type: str = "",
        reference_at: str | None = None,
        allow_generic_fallback: bool = True,
    ) -> tuple[CommitmentCandidate, ...]:
        extracted = self.extract_commitments(
            text=text,
            counterparty=counterparty,
            due_at=due_at,
            reference_at=reference_at,
            allow_generic_fallback=allow_generic_fallback,
        )
        staged: list[CommitmentCandidate] = []
        normalized_kind = str(kind or "commitment").strip().lower() or "commitment"
        for candidate in extracted:
            resolved_stakeholder_id = self._resolve_stakeholder_ref(
                principal_id=principal_id,
                stakeholder_id=stakeholder_id,
                counterparty=candidate.counterparty or counterparty,
            ) if normalized_kind == "follow_up" else ""
            duplicate_of_ref = self._find_duplicate_commitment_ref(
                principal_id=principal_id,
                title=candidate.title,
                counterparty=candidate.counterparty or counterparty,
            )
            row = self._container.memory_runtime.stage_candidate(
                principal_id=principal_id,
                category="product_commitment_candidate",
                summary=candidate.title,
                fact_json={
                    "title": candidate.title,
                    "details": candidate.details,
                    "source_text": candidate.source_text,
                    "suggested_due_at": candidate.suggested_due_at or "",
                    "counterparty": candidate.counterparty,
                    "kind": normalized_kind,
                    "stakeholder_id": resolved_stakeholder_id,
                    "channel_hint": channel_hint,
                    "source_ref": source_ref,
                    "signal_type": signal_type,
                    "duplicate_of_ref": duplicate_of_ref,
                },
                confidence=candidate.confidence,
                sensitivity="internal",
            )
            staged.append(self._candidate_from_memory_row(row))
            self._record_product_event(
                principal_id=principal_id,
                event_type="commitment_candidate_duplicate_detected" if duplicate_of_ref else "commitment_candidate_staged",
                payload={"title": candidate.title, "kind": normalized_kind, "counterparty": candidate.counterparty, "duplicate_of_ref": duplicate_of_ref},
                source_id=row.candidate_id,
            )
        return tuple(staged)

    def _allow_generic_signal_candidate_fallback(
        self,
        *,
        signal_type: str,
        channel: str,
        title: str,
        summary: str,
        counterparty: str,
        stakeholder_id: str,
        payload: dict[str, object] | None,
    ) -> bool:
        normalized_signal = str(signal_type or "").strip().lower()
        normalized_channel = str(channel or "").strip().lower()
        payload_json = dict(payload or {})
        if normalized_channel == "calendar" and normalized_signal == "calendar_note":
            return bool(str(payload_json.get("description") or "").strip())
        if normalized_channel == "gmail" and normalized_signal == "email_thread":
            if _is_assistant_originated_delivery_email(
                title=title,
                summary=summary,
                payload=payload_json,
            ):
                return False
            labels = {
                str(value or "").strip().upper()
                for value in (payload_json.get("labels") or [])
                if str(value or "").strip()
            }
            if labels & _LOW_SIGNAL_GMAIL_LABELS:
                return False
            auto_submitted = str(payload_json.get("auto_submitted") or "").strip().lower()
            if auto_submitted and auto_submitted != "no":
                return False
            if str(payload_json.get("precedence") or "").strip().lower() in {"bulk", "list", "junk"}:
                return False
        return True

    def accept_commitment_candidate(
        self,
        *,
        principal_id: str,
        candidate_id: str,
        reviewer: str,
        title: str = "",
        details: str = "",
        due_at: str | None = None,
        counterparty: str = "",
        kind: str = "",
        stakeholder_id: str = "",
    ) -> CommitmentItem | None:
        promoted = self._container.memory_runtime.promote_candidate(
            candidate_id,
            principal_id=principal_id,
            reviewer=reviewer,
            sharing_policy="private",
        )
        if promoted is None:
            return None
        candidate, _item = promoted
        fact = dict(candidate.fact_json or {})
        duplicate_of_ref = str(fact.get("duplicate_of_ref") or "").strip()
        if duplicate_of_ref:
            merged = self._merge_candidate_into_existing(
                principal_id=principal_id,
                duplicate_ref=duplicate_of_ref,
                candidate_id=candidate_id,
                title=title.strip() or str(fact.get("title") or candidate.summary or "Commitment"),
                details=details if details.strip() else str(fact.get("details") or ""),
                due_at=due_at if str(due_at or "").strip() else (str(fact.get("suggested_due_at") or "") or None),
                counterparty=counterparty.strip() or str(fact.get("counterparty") or ""),
                confidence=float(getattr(candidate, "confidence", 0.5) or 0.5),
                channel_hint=str(fact.get("channel_hint") or ""),
                source_ref=str(fact.get("source_ref") or ""),
                signal_type=str(fact.get("signal_type") or ""),
                source_type="office_signal" if str(fact.get("source_ref") or "").strip() or str(fact.get("signal_type") or "").strip() else "manual",
            )
            if merged is not None:
                self._record_product_event(
                    principal_id=principal_id,
                    event_type="commitment_candidate_accepted",
                    payload={
                        "candidate_id": candidate_id,
                        "reviewer": reviewer,
                        "title_override": title.strip(),
                        "due_at_override": str(due_at or "").strip(),
                        "counterparty_override": counterparty.strip(),
                        "kind_override": kind.strip(),
                        "merged_into_ref": duplicate_of_ref,
                    },
                    source_id=candidate_id,
                )
                return merged
        created = self.create_commitment(
            principal_id=principal_id,
            title=title.strip() or str(fact.get("title") or candidate.summary or "Commitment"),
            details=details if details.strip() else str(fact.get("details") or ""),
            due_at=due_at if str(due_at or "").strip() else (str(fact.get("suggested_due_at") or "") or None),
            counterparty=counterparty.strip() or str(fact.get("counterparty") or ""),
            owner="office",
            kind=kind.strip() or str(fact.get("kind") or "commitment"),
            stakeholder_id=stakeholder_id.strip() or str(fact.get("stakeholder_id") or ""),
            channel_hint=str(fact.get("channel_hint") or "email"),
            source_type="office_signal" if str(fact.get("source_ref") or "").strip() or str(fact.get("signal_type") or "").strip() else "manual",
            source_ref=str(fact.get("source_ref") or ""),
            confidence=float(getattr(candidate, "confidence", 0.5) or 0.5),
            signal_type=str(fact.get("signal_type") or ""),
        )
        self._record_product_event(
            principal_id=principal_id,
            event_type="commitment_candidate_accepted",
            payload={
                "candidate_id": candidate_id,
                "reviewer": reviewer,
                "title_override": title.strip(),
                "due_at_override": str(due_at or "").strip(),
                "counterparty_override": counterparty.strip(),
                "kind_override": kind.strip(),
            },
            source_id=candidate_id,
        )
        return created

    def resolve_commitment(
        self,
        *,
        principal_id: str,
        commitment_ref: str,
        action: str,
        actor: str,
        reason: str = "",
        reason_code: str = "",
        due_at: str | None = None,
    ) -> CommitmentItem | None:
        normalized = str(action or "").strip().lower()
        code = str(reason_code or "").strip().lower()
        if commitment_ref.startswith("commitment:"):
            current = self._container.memory_runtime.get_commitment(commitment_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            source = dict(current.source_json or {})
            next_status = current.status
            event_type = "commitment_updated"
            if normalized in {"close", "done", "complete"}:
                next_status = "completed"
                event_type = "commitment_closed"
                code = code or "completed"
            elif normalized in {"drop", "dismiss", "cancel"}:
                next_status = "cancelled"
                event_type = "commitment_dropped"
                code = code or "no_longer_needed"
            elif normalized in {"defer", "snooze"}:
                next_status = "open"
                event_type = "commitment_deferred"
                code = code or "deferred"
            elif normalized in {"wait", "waiting", "waiting_on_external", "await_external"}:
                next_status = "waiting_on_external"
                event_type = "commitment_waiting_on_external"
                code = code or "waiting_on_external"
            elif normalized in {"schedule", "scheduled", "reschedule"}:
                next_status = "scheduled"
                event_type = "commitment_scheduled"
                code = code or "scheduled"
            elif normalized in {"reopen"}:
                next_status = "open"
                event_type = "commitment_reopened"
            updated_source = {
                **source,
                "resolution_code": "" if normalized == "reopen" else code,
                "resolution_reason": "" if normalized == "reopen" else (reason or str(source.get("resolution_reason") or "")),
                "channel_hint": str(source.get("channel_hint") or "email"),
            }
            if normalized == "reopen":
                updated_source["reopened_at"] = _now_iso()
            updated = self._container.memory_runtime.upsert_commitment(
                principal_id=principal_id,
                commitment_id=current.commitment_id,
                title=current.title,
                details=current.details,
                status=next_status,
                priority=current.priority,
                due_at=due_at or current.due_at,
                source_json=updated_source,
            )
            self._record_product_event(
                principal_id=principal_id,
                event_type=event_type,
                payload={"item_ref": commitment_ref, "action": normalized or "update", "actor": actor, "reason": reason or "", "reason_code": code},
                source_id=current.commitment_id,
            )
            return self._commitment_item_from_commitment(updated)
        if commitment_ref.startswith("follow_up:"):
            current = self._container.memory_runtime.get_follow_up(commitment_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            source = dict(current.source_json or {})
            next_status = current.status
            event_type = "commitment_updated"
            if normalized in {"close", "done", "complete"}:
                next_status = "completed"
                event_type = "commitment_closed"
                code = code or "completed"
            elif normalized in {"drop", "dismiss", "cancel"}:
                next_status = "cancelled"
                event_type = "commitment_dropped"
                code = code or "no_longer_needed"
            elif normalized in {"defer", "snooze"}:
                next_status = "open"
                event_type = "commitment_deferred"
                code = code or "deferred"
            elif normalized in {"wait", "waiting", "waiting_on_external", "await_external"}:
                next_status = "waiting_on_external"
                event_type = "commitment_waiting_on_external"
                code = code or "waiting_on_external"
            elif normalized in {"schedule", "scheduled", "reschedule"}:
                next_status = "scheduled"
                event_type = "commitment_scheduled"
                code = code or "scheduled"
            elif normalized in {"reopen"}:
                next_status = "open"
                event_type = "commitment_reopened"
            updated_source = {
                **source,
                "resolution_code": "" if normalized == "reopen" else code,
                "resolution_reason": "" if normalized == "reopen" else (reason or str(source.get("resolution_reason") or "")),
                "channel_hint": str(source.get("channel_hint") or current.channel_hint or "email"),
            }
            if normalized == "reopen":
                updated_source["reopened_at"] = _now_iso()
            updated = self._container.memory_runtime.upsert_follow_up(
                principal_id=principal_id,
                follow_up_id=current.follow_up_id,
                stakeholder_ref=current.stakeholder_ref,
                topic=current.topic,
                status=next_status,
                due_at=due_at or current.due_at,
                channel_hint=current.channel_hint,
                notes=current.notes if not reason else reason,
                source_json=updated_source,
            )
            self._record_product_event(
                principal_id=principal_id,
                event_type=event_type,
                payload={"item_ref": commitment_ref, "action": normalized or "update", "actor": actor, "reason": reason or "", "reason_code": code},
                source_id=current.follow_up_id,
            )
            return self._commitment_item_from_follow_up(updated, self._stakeholder_lookup(principal_id))
        return None

    def reject_commitment_candidate(
        self,
        *,
        principal_id: str,
        candidate_id: str,
        reviewer: str,
    ) -> CommitmentCandidate | None:
        row = self._container.memory_runtime.reject_candidate(candidate_id, principal_id=principal_id, reviewer=reviewer)
        if row is None:
            return None
        self._record_product_event(
            principal_id=principal_id,
            event_type="commitment_candidate_rejected",
            payload={"candidate_id": candidate_id, "reviewer": reviewer},
            source_id=candidate_id,
        )
        return self._candidate_from_memory_row(row)

    def _queue_item_from_approval(self, row: ApprovalRequest) -> DecisionQueueItem:
        action_json = dict(row.requested_action_json or {})
        action_label = _action_label(action_json)
        summary = compact_text(
            action_json.get("content") or action_json.get("draft_text") or row.reason,
            fallback="Approval is waiting for a decision.",
        )
        return DecisionQueueItem(
            id=f"approval:{row.approval_id}",
            queue_kind="approve_draft",
            title=row.reason or f"Approve {action_label}",
            summary=summary,
            priority="high",
            deadline=row.expires_at,
            owner_role="principal",
            requires_principal=True,
            evidence_refs=(
                EvidenceRef(ref_id=f"approval:{row.approval_id}", label="Approval", source_type="approval", note=action_label),
                EvidenceRef(ref_id=f"session:{row.session_id}", label="Session", source_type="session", note=row.step_id),
            ),
            resolution_state=row.status,
        )

    def _draft_from_approval(self, row: ApprovalRequest) -> DraftCandidate:
        action_json = dict(row.requested_action_json or {})
        return DraftCandidate(
            id=f"approval:{row.approval_id}",
            thread_ref=str(action_json.get("thread_ref") or action_json.get("source_ref") or row.session_id),
            recipient_summary=str(
                action_json.get("recipient_label")
                or action_json.get("recipient_name")
                or action_json.get("recipient")
                or action_json.get("recipient_email")
                or action_json.get("to")
                or "Review required"
            ),
            intent=_action_label(action_json),
            draft_text=compact_text(
                action_json.get("content") or action_json.get("draft_text") or row.reason,
                fallback="Approval-backed draft ready for review.",
                limit=500,
            ),
            tone=str(action_json.get("tone") or "review"),
            requires_approval=True,
            approval_status=row.status,
            provenance_refs=(
                EvidenceRef(ref_id=f"approval:{row.approval_id}", label="Approval request", source_type="approval", note=row.reason),
                EvidenceRef(ref_id=f"session:{row.session_id}", label="Session", source_type="session", note=row.step_id),
            ),
            send_channel=str(action_json.get("channel") or "email"),
        )

    def list_drafts(self, *, principal_id: str, limit: int = 20) -> tuple[DraftCandidate, ...]:
        rows = self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=limit)
        return tuple(self._draft_from_approval(row) for row in rows[:limit])

    def approve_draft(self, *, principal_id: str, draft_ref: str, decided_by: str, reason: str) -> DraftCandidate | None:
        if not draft_ref.startswith("approval:"):
            return None
        approval_id = draft_ref.split(":", 1)[1]
        allowed = {row.approval_id for row in self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=500)}
        if approval_id not in allowed:
            return None
        decided = self._container.orchestrator.decide_approval(
            approval_id,
            decision="approved",
            decided_by=decided_by,
            reason=reason or "Approved from product draft queue.",
        )
        if decided is None:
            return None
        request, _ = decided
        action_json = dict(request.requested_action_json or {})
        accepted_candidate_ids: tuple[str, ...] = ()
        if str(action_json.get("draft_origin") or "").strip() == "office_signal":
            accepted_candidate_ids = self._accept_linked_signal_candidates(
                principal_id=principal_id,
                action_json=action_json,
                reviewer=decided_by,
            )
        delivery = self._maybe_send_approved_draft(
            principal_id=principal_id,
            draft_ref=draft_ref,
            action_json=action_json,
        )
        if str(delivery.get("status") or "").strip() == "sent":
            self._record_product_event(
                principal_id=principal_id,
                event_type="draft_sent",
                payload=dict(delivery),
                source_id=request.approval_id,
            )
        elif str(delivery.get("status") or "").strip() == "failed":
            self._record_product_event(
                principal_id=principal_id,
                event_type="draft_send_failed",
                payload=dict(delivery),
                source_id=request.approval_id,
            )
        followup = self._ensure_draft_delivery_followup(
            principal_id=principal_id,
            request=request,
            action_json=action_json,
            delivery=delivery,
        )
        self._record_product_event(
            principal_id=principal_id,
            event_type="draft_approved",
            payload={
                "draft_ref": draft_ref,
                "decided_by": decided_by,
                "reason": reason or "",
                "accepted_candidate_ids": list(accepted_candidate_ids),
                "person_id": str(delivery.get("person_id") or action_json.get("stakeholder_id") or "").strip(),
                "thread_ref": str(delivery.get("thread_ref") or action_json.get("thread_ref") or "").strip(),
                "source_ref": str(delivery.get("source_ref") or action_json.get("source_ref") or "").strip(),
                "delivery": dict(delivery),
                "followup_ref": followup.id if followup is not None else "",
            },
            source_id=request.approval_id,
        )
        return DraftCandidate(
            id=f"approval:{request.approval_id}",
            thread_ref=request.session_id,
            recipient_summary="Approved draft",
            intent="approved",
            draft_text=compact_text(request.reason, fallback="Approved from product draft queue."),
            tone="approved",
            requires_approval=True,
            approval_status="approved",
            provenance_refs=(EvidenceRef(ref_id=f"approval:{request.approval_id}", label="Approval request", source_type="approval", note=request.reason),),
            send_channel=str(action_json.get("channel") or "email"),
        )

    def reject_draft(self, *, principal_id: str, draft_ref: str, decided_by: str, reason: str) -> DraftCandidate | None:
        if not draft_ref.startswith("approval:"):
            return None
        approval_id = draft_ref.split(":", 1)[1]
        allowed = {row.approval_id for row in self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=500)}
        if approval_id not in allowed:
            return None
        decided = self._container.orchestrator.decide_approval(
            approval_id,
            decision="rejected",
            decided_by=decided_by,
            reason=reason or "Rejected from product draft queue.",
        )
        if decided is None:
            return None
        request, _ = decided
        self._record_product_event(
            principal_id=principal_id,
            event_type="draft_rejected",
            payload={"draft_ref": draft_ref, "decided_by": decided_by, "reason": reason or ""},
            source_id=request.approval_id,
        )
        return DraftCandidate(
            id=f"approval:{request.approval_id}",
            thread_ref=request.session_id,
            recipient_summary="Rejected draft",
            intent="rejected",
            draft_text=compact_text(request.reason, fallback="Rejected from product draft queue."),
            tone="rejected",
            requires_approval=True,
            approval_status="rejected",
            provenance_refs=(EvidenceRef(ref_id=f"approval:{request.approval_id}", label="Approval request", source_type="approval", note=request.reason),),
            send_channel=str(dict(request.requested_action_json or {}).get("channel") or "email"),
        )

    def _queue_item_from_human_task(self, row: HumanTask) -> DecisionQueueItem:
        summary = " · ".join(
            part
            for part in (
                compact_text(row.why_human, fallback="Human judgment is still required."),
                f"Role {row.role_required}" if row.role_required else "",
                f"Due {row.sla_due_at[:10]}" if row.sla_due_at else "",
            )
            if part
        )
        return DecisionQueueItem(
            id=f"human_task:{row.human_task_id}",
            queue_kind="assign_owner",
            title=row.brief,
            summary=summary,
            priority=row.priority,
            deadline=row.sla_due_at,
            owner_role=row.role_required,
            requires_principal=False,
            evidence_refs=(
                EvidenceRef(ref_id=f"human_task:{row.human_task_id}", label="Human task", source_type="human_task", note=row.task_type),
                EvidenceRef(ref_id=f"session:{row.session_id}", label="Session", source_type="session", note=row.step_id or ""),
            ),
            resolution_state=row.status,
        )

    def _queue_item_from_commitment(self, row: CommitmentItem) -> DecisionQueueItem:
        return DecisionQueueItem(
            id=row.id,
            queue_kind="close_commitment",
            title=row.statement,
            summary=compact_text(
                row.proof_refs[0].note if row.proof_refs else "",
                fallback="Commitment is still open and needs a visible next action.",
            ),
            priority=row.risk_level,
            deadline=row.due_at,
            owner_role=row.owner,
            requires_principal=False,
            evidence_refs=row.proof_refs,
            resolution_state=row.status,
        )

    def _queue_item_from_decision(self, row: DecisionWindow) -> DecisionQueueItem:
        return DecisionQueueItem(
            id=f"decision:{row.decision_window_id}",
            queue_kind="choose_option",
            title=row.title,
            summary=compact_text(row.context or row.notes, fallback="Decision window is open."),
            priority=row.urgency,
            deadline=row.closes_at or row.opens_at,
            owner_role=row.authority_required,
            requires_principal=str(row.authority_required or "").strip().lower() in {"principal", "exec", "executive"},
            evidence_refs=(EvidenceRef(ref_id=f"decision:{row.decision_window_id}", label="Decision", source_type="decision", note=row.status),),
            resolution_state=row.status,
        )

    def _queue_item_from_deadline(self, row: DeadlineWindow) -> DecisionQueueItem:
        return DecisionQueueItem(
            id=f"deadline:{row.window_id}",
            queue_kind="defer",
            title=row.title,
            summary=compact_text(row.notes, fallback="Deadline window is active."),
            priority=row.priority,
            deadline=row.end_at or row.start_at,
            owner_role="office",
            requires_principal=False,
            evidence_refs=(EvidenceRef(ref_id=f"deadline:{row.window_id}", label="Deadline", source_type="deadline", note=row.status),),
            resolution_state=row.status,
        )

    def list_queue(self, *, principal_id: str, limit: int = 30, operator_id: str = "") -> tuple[DecisionQueueItem, ...]:
        operator_key = str(operator_id or "").strip()
        items: list[DecisionQueueItem] = []
        items.extend(self._queue_item_from_approval(row) for row in self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=limit))
        for row in self._container.orchestrator.list_human_tasks(principal_id=principal_id, status="pending", limit=limit):
            assigned = str(row.assigned_operator_id or "").strip()
            if operator_key and assigned and assigned != operator_key:
                continue
            items.append(self._queue_item_from_human_task(row))
        items.extend(self._queue_item_from_commitment(row) for row in self.list_commitments(principal_id=principal_id, limit=limit))
        for row in self._container.memory_runtime.list_decision_windows(principal_id=principal_id, limit=limit, status=None):
            if status_open(row.status):
                items.append(self._queue_item_from_decision(row))
        for row in self._container.memory_runtime.list_deadline_windows(principal_id=principal_id, limit=limit, status=None):
            if status_open(row.status):
                items.append(self._queue_item_from_deadline(row))
        items = [item for item in items if status_open(item.resolution_state)]
        items.sort(key=lambda item: (priority_weight(item.priority), due_bonus(item.deadline), item.title.lower()), reverse=True)
        return tuple(items[:limit])

    def resolve_queue_item(
        self,
        *,
        principal_id: str,
        item_ref: str,
        action: str,
        actor: str,
        reason: str = "",
        reason_code: str = "",
        due_at: str | None = None,
    ) -> DecisionQueueItem | None:
        normalized = str(action or "").strip().lower()
        if item_ref.startswith("approval:"):
            decision = "approved" if normalized in {"approve", "approved", "close"} else "rejected"
            approval_id = item_ref.split(":", 1)[1]
            decision_reason = reason or f"{decision.capitalize()} from decision queue."
            decided = (
                self.approve_draft(
                    principal_id=principal_id,
                    draft_ref=item_ref,
                    decided_by=actor,
                    reason=decision_reason,
                )
                if decision == "approved"
                else self.reject_draft(
                    principal_id=principal_id,
                    draft_ref=item_ref,
                    decided_by=actor,
                    reason=decision_reason,
                )
            )
            if decided is None:
                return None
            request = self._container.orchestrator.fetch_approval_request_for_principal(approval_id, principal_id=principal_id)
            self._record_product_event(
                principal_id=principal_id,
                event_type="queue_resolved",
                payload={"item_ref": item_ref, "action": decision, "actor": actor, "reason": reason or ""},
                source_id=approval_id,
            )
            if request is None:
                return DecisionQueueItem(
                    id=item_ref,
                    queue_kind="approve_draft",
                    title=f"{decision.capitalize()} draft",
                    summary=decided.draft_text,
                    priority="high",
                    owner_role="principal",
                    requires_principal=True,
                    evidence_refs=decided.provenance_refs,
                    resolution_state=decision,
                )
            updated = self._queue_item_from_approval(request)
            return DecisionQueueItem(
                id=updated.id,
                queue_kind=updated.queue_kind,
                title=updated.title,
                summary=updated.summary,
                priority=updated.priority,
                deadline=updated.deadline,
                owner_role=updated.owner_role,
                requires_principal=updated.requires_principal,
                evidence_refs=updated.evidence_refs,
                resolution_state=decision,
            )
        if item_ref.startswith("commitment:"):
            updated = self.resolve_commitment(
                principal_id=principal_id,
                commitment_ref=item_ref,
                action=normalized,
                actor=actor,
                reason=reason,
                reason_code=reason_code,
                due_at=due_at,
            )
            return None if updated is None else self._queue_item_from_commitment(updated)
        if item_ref.startswith("follow_up:"):
            updated = self.resolve_commitment(
                principal_id=principal_id,
                commitment_ref=item_ref,
                action=normalized,
                actor=actor,
                reason=reason,
                reason_code=reason_code,
                due_at=due_at,
            )
            return None if updated is None else self._queue_item_from_commitment(updated)
        if item_ref.startswith("human_task:"):
            current = self._container.orchestrator.fetch_human_task(item_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            operator_id = str(current.assigned_operator_id or actor or "").strip()
            if normalized in {"assign", "claim"}:
                result = self.assign_handoff(
                    principal_id=principal_id,
                    handoff_ref=item_ref,
                    operator_id=operator_id,
                    actor=actor,
                )
            else:
                result = self.complete_handoff(
                    principal_id=principal_id,
                    handoff_ref=item_ref,
                    operator_id=operator_id,
                    actor=actor,
                    resolution=normalized or "completed",
                )
            if result is None:
                return None
            self._record_product_event(
                principal_id=principal_id,
                event_type="queue_resolved",
                payload={"item_ref": item_ref, "action": normalized or "complete", "actor": actor, "operator_id": operator_id},
                source_id=current.human_task_id,
            )
            refreshed = self._container.orchestrator.fetch_human_task(current.human_task_id, principal_id=principal_id)
            return None if refreshed is None else self._queue_item_from_human_task(refreshed)
        if item_ref.startswith("decision:"):
            current = self._container.memory_runtime.get_decision_window(item_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            source = dict(current.source_json or {})
            next_status = "decided" if normalized in {"resolve", "close", "done", "complete"} else "open"
            if normalized in {"defer", "snooze", "reopen", "escalate"}:
                next_status = "open"
            next_authority = current.authority_required
            if normalized == "escalate":
                next_authority = "principal"
            updated = self._container.memory_runtime.upsert_decision_window(
                principal_id=principal_id,
                decision_window_id=current.decision_window_id,
                title=current.title,
                context=current.context,
                opens_at=current.opens_at,
                closes_at=due_at or current.closes_at,
                urgency=current.urgency,
                authority_required=next_authority,
                status=next_status,
                notes=reason or current.notes,
                source_json={
                    **source,
                    "resolution_reason": reason if normalized in {"resolve", "close", "done", "complete"} else "",
                    "resolved_by": actor if normalized in {"resolve", "close", "done", "complete"} else "",
                    "resolved_at": _now_iso() if normalized in {"resolve", "close", "done", "complete"} else "",
                    "reopened_by": actor if normalized == "reopen" else str(source.get("reopened_by") or ""),
                    "reopened_at": _now_iso() if normalized == "reopen" else str(source.get("reopened_at") or ""),
                    "escalation_reason": reason if normalized == "escalate" else "",
                    "escalated_by": actor if normalized == "escalate" else str(source.get("escalated_by") or ""),
                    "escalated_at": _now_iso() if normalized == "escalate" else str(source.get("escalated_at") or ""),
                },
            )
            self._record_product_event(
                principal_id=principal_id,
                event_type="decision_resolved" if normalized in {"resolve", "close", "done", "complete"} else ("decision_escalated" if normalized == "escalate" else ("decision_reopened" if normalized == "reopen" else "queue_resolved")),
                payload={"item_ref": item_ref, "action": normalized or "resolve", "actor": actor, "reason": reason or ""},
                source_id=current.decision_window_id,
            )
            return self._queue_item_from_decision(updated)
        if item_ref.startswith("deadline:"):
            current = self._container.memory_runtime.get_deadline_window(item_ref.split(":", 1)[1], principal_id=principal_id)
            if current is None:
                return None
            next_status = "elapsed" if normalized in {"resolve", "close", "done", "complete"} else "open"
            updated = self._container.memory_runtime.upsert_deadline_window(
                principal_id=principal_id,
                window_id=current.window_id,
                title=current.title,
                start_at=current.start_at,
                end_at=due_at or current.end_at,
                status=next_status,
                priority=current.priority,
                notes=reason or current.notes,
                source_json=dict(current.source_json or {}),
            )
            self._record_product_event(
                principal_id=principal_id,
                event_type="queue_resolved",
                payload={"item_ref": item_ref, "action": normalized or "resolve", "actor": actor, "reason": reason or ""},
                source_id=current.window_id,
            )
            return self._queue_item_from_deadline(updated)
        return None

    def _decision_item_from_window(self, row: DecisionWindow) -> DecisionItem:
        return decision_item_from_window(row)

    def list_decisions(
        self,
        *,
        principal_id: str,
        limit: int = 20,
        include_closed: bool = False,
    ) -> tuple[DecisionItem, ...]:
        rows = [
            self._decision_item_from_window(row)
            for row in self._container.memory_runtime.list_decision_windows(principal_id=principal_id, limit=limit, status=None)
            if include_closed or status_open(row.status)
        ]
        rows.sort(key=lambda row: (priority_weight(row.priority), due_bonus(row.due_at), row.title.lower()), reverse=True)
        return tuple(rows[:limit])

    def get_decision(self, *, principal_id: str, decision_ref: str) -> DecisionItem | None:
        normalized = decision_ref.split(":", 1)[1] if decision_ref.startswith("decision:") else decision_ref
        found = self._container.memory_runtime.get_decision_window(normalized, principal_id=principal_id)
        if found is None:
            return None
        return self._decision_item_from_window(found)

    def get_decision_history(self, *, principal_id: str, decision_ref: str, limit: int = 20) -> tuple[HistoryEntry, ...]:
        source_id = decision_ref.split(":", 1)[1] if ":" in decision_ref else decision_ref
        return self._history_entries(principal_id=principal_id, source_ids=(source_id,), limit=limit)

    def _deadline_item_from_window(self, row: DeadlineWindow) -> DeadlineItem:
        return DeadlineItem(
            id=f"deadline:{row.window_id}",
            title=row.title,
            summary=compact_text(row.notes, fallback="Deadline window is active."),
            priority=row.priority,
            start_at=row.start_at,
            end_at=row.end_at,
            status=row.status,
        )

    def list_deadlines(
        self,
        *,
        principal_id: str,
        limit: int = 20,
        include_closed: bool = False,
    ) -> tuple[DeadlineItem, ...]:
        rows = [
            self._deadline_item_from_window(row)
            for row in self._container.memory_runtime.list_deadline_windows(principal_id=principal_id, limit=limit, status=None)
            if include_closed or status_open(row.status)
        ]
        rows.sort(key=lambda row: (priority_weight(row.priority), due_bonus(row.end_at or row.start_at), row.title.lower()), reverse=True)
        return tuple(rows[:limit])

    def get_deadline(self, *, principal_id: str, deadline_ref: str) -> DeadlineItem | None:
        normalized = deadline_ref.split(":", 1)[1] if deadline_ref.startswith("deadline:") else deadline_ref
        found = self._container.memory_runtime.get_deadline_window(normalized, principal_id=principal_id)
        if found is None:
            return None
        return self._deadline_item_from_window(found)

    def get_deadline_history(self, *, principal_id: str, deadline_ref: str, limit: int = 20) -> tuple[HistoryEntry, ...]:
        source_id = deadline_ref.split(":", 1)[1] if ":" in deadline_ref else deadline_ref
        return self._history_entries(principal_id=principal_id, source_ids=(source_id,), limit=limit)

    def resolve_decision(
        self,
        *,
        principal_id: str,
        decision_ref: str,
        actor: str,
        action: str,
        reason: str = "",
        due_at: str | None = None,
    ) -> DecisionItem | None:
        item_ref = decision_ref if decision_ref.startswith("decision:") else f"decision:{decision_ref}"
        updated = self.resolve_queue_item(
            principal_id=principal_id,
            item_ref=item_ref,
            action=action,
            actor=actor,
            reason=reason,
            due_at=due_at,
        )
        if updated is None:
            return None
        return self.get_decision(principal_id=principal_id, decision_ref=item_ref)

    def resolve_deadline(
        self,
        *,
        principal_id: str,
        deadline_ref: str,
        actor: str,
        action: str,
        reason: str = "",
        due_at: str | None = None,
    ) -> DeadlineItem | None:
        item_ref = deadline_ref if deadline_ref.startswith("deadline:") else f"deadline:{deadline_ref}"
        updated = self.resolve_queue_item(
            principal_id=principal_id,
            item_ref=item_ref,
            action=action,
            actor=actor,
            reason=reason,
            due_at=due_at,
        )
        if updated is None:
            return None
        return self.get_deadline(principal_id=principal_id, deadline_ref=item_ref)

    def list_threads(self, *, principal_id: str, limit: int = 20) -> tuple[ThreadItem, ...]:
        drafts = self.list_drafts(principal_id=principal_id, limit=max(limit, 20))
        commitments = self.list_commitments(principal_id=principal_id, limit=max(limit, 20))
        decisions = self.list_decisions(principal_id=principal_id, limit=max(limit, 20), include_closed=True)
        active_threads = thread_items_from_objects(drafts, commitments, decisions, limit=max(limit, 20))
        event_threads = self._thread_items_from_events(
            principal_id=principal_id,
            commitments=commitments,
            decisions=decisions,
            limit=max(limit, 20),
        )
        rows: list[ThreadItem] = list(active_threads)
        seen = {item.id for item in active_threads}
        for item in event_threads:
            if item.id in seen:
                continue
            seen.add(item.id)
            rows.append(item)
        rows.sort(
            key=lambda item: (
                1 if item.draft_ids else 0,
                str(item.last_activity_at or ""),
                item.title.lower(),
            ),
            reverse=True,
        )
        return tuple(rows[:limit])

    def get_thread(self, *, principal_id: str, thread_ref: str) -> ThreadItem | None:
        normalized = thread_ref if thread_ref.startswith("thread:") else f"thread:{thread_ref}"
        for row in self.list_threads(principal_id=principal_id, limit=200):
            if row.id == normalized:
                return row
        return None

    def get_thread_history(self, *, principal_id: str, thread_ref: str, limit: int = 20) -> tuple[HistoryEntry, ...]:
        normalized = str(thread_ref or "").strip()
        if not normalized:
            return ()
        source_ids = (normalized, normalized.split(":", 1)[1] if normalized.startswith("thread:") else f"thread:{normalized}")
        return self._history_entries(principal_id=principal_id, source_ids=source_ids, limit=limit)

    def list_evidence(
        self,
        *,
        principal_id: str,
        limit: int = 40,
        operator_id: str = "",
    ) -> tuple[EvidenceItem, ...]:
        brief_items = self.list_brief_items(principal_id=principal_id, limit=max(limit, 12), operator_id=operator_id)
        queue_items = self.list_queue(principal_id=principal_id, limit=max(limit, 12), operator_id=operator_id)
        commitments = self.list_commitments(principal_id=principal_id, limit=max(limit, 12))
        drafts = self.list_drafts(principal_id=principal_id, limit=max(limit, 12))
        decisions = self.list_decisions(principal_id=principal_id, limit=max(limit, 12), include_closed=True)
        handoffs = self.list_handoffs(principal_id=principal_id, limit=max(limit, 12), operator_id=operator_id, status=None)
        threads = thread_items_from_objects(drafts, commitments, decisions, limit=max(limit, 12))
        return evidence_items_from_objects(
            brief_items=brief_items,
            queue_items=queue_items,
            commitments=commitments,
            drafts=drafts,
            decisions=decisions,
            handoffs=handoffs,
            threads=threads,
            limit=limit,
        )

    def get_evidence(self, *, principal_id: str, evidence_ref: str, operator_id: str = "") -> EvidenceItem | None:
        for row in self.list_evidence(principal_id=principal_id, limit=200, operator_id=operator_id):
            if row.id == evidence_ref:
                return row
        return None

    def _rules_diagnostics(self, *, principal_id: str) -> tuple[dict[str, object], dict[str, object]]:
        status = self._container.onboarding.status(principal_id=principal_id)
        workspace = dict(status.get("workspace") or {})
        selected_channels = tuple(str(value) for value in (status.get("selected_channels") or []) if str(value).strip())
        plan = workspace_plan_for_mode(str(workspace.get("mode") or "personal"))
        operators = self._container.orchestrator.list_operator_profiles(principal_id=principal_id, status="active", limit=25)
        seats_used = len(operators)
        seat_limit = int(plan.entitlements.operator_seats or 0)
        seat_overage = max(seats_used - seat_limit, 0)
        commercial_snapshot = workspace_commercial_snapshot(plan, seats_used=seats_used, selected_channels=selected_channels)
        return status, {
            "billing": dict(commercial_snapshot.get("billing") or {}),
            "entitlements": {
                "principal_seats": plan.entitlements.principal_seats,
                "operator_seats": plan.entitlements.operator_seats,
                "messaging_channels_enabled": plan.entitlements.messaging_channels_enabled,
                "audit_retention": plan.entitlements.audit_retention,
                "feature_flags": list(plan.entitlements.feature_flags),
            },
            "operators": {
                "active_count": seats_used,
                "seats_used": seats_used,
                "seats_remaining": max(seat_limit - seats_used, 0),
                "seat_overage": seat_overage,
            },
            "commercial": dict(commercial_snapshot.get("commercial") or {}),
        }

    def list_rules(self, *, principal_id: str) -> tuple[RuleItem, ...]:
        status, diagnostics = self._rules_diagnostics(principal_id=principal_id)
        return rule_items_from_workspace(status, diagnostics)

    def get_rule(self, *, principal_id: str, rule_id: str) -> RuleItem | None:
        for row in self.list_rules(principal_id=principal_id):
            if row.id == rule_id:
                return row
        return None

    def simulate_rule(self, *, principal_id: str, rule_id: str, proposed_value: str) -> RuleItem | None:
        current = self.get_rule(principal_id=principal_id, rule_id=rule_id)
        if current is None:
            return None
        _, diagnostics = self._rules_diagnostics(principal_id=principal_id)
        return simulate_rule(current, proposed_value=proposed_value, diagnostics=diagnostics)

    def _brief_item_from_queue(self, row: DecisionQueueItem, *, workspace_id: str) -> BriefItem:
        confidence = 0.7
        if row.id.startswith("approval:"):
            confidence = 0.95
        elif row.id.startswith("decision:"):
            confidence = 0.88
        elif row.id.startswith(("commitment:", "follow_up:")):
            confidence = 0.84
        return BriefItem(
            id=row.id,
            workspace_id=workspace_id,
            kind=row.queue_kind,
            title=row.title,
            summary=row.summary,
            score=float(priority_weight(row.priority) + due_bonus(row.deadline)),
            why_now=row.summary,
            evidence_refs=row.evidence_refs,
            related_people=(),
            related_commitment_ids=(row.id,) if row.queue_kind == "close_commitment" else (),
            recommended_action=row.queue_kind.replace("_", " "),
            status=row.resolution_state,
            confidence=confidence,
            object_ref=row.id,
            evidence_count=len(row.evidence_refs),
        )

    def _brief_item_from_decision(self, row: DecisionItem, *, workspace_id: str) -> BriefItem:
        why_now_parts = [
            str(row.sla_status or "").replace("_", " ").title(),
            row.impact_summary or row.summary,
        ]
        return BriefItem(
            id=f"brief:{row.id}",
            workspace_id=workspace_id,
            kind="decision",
            title=row.title,
            summary=row.summary,
            score=float(priority_weight(row.priority) + due_bonus(row.due_at) + 1),
            why_now=" · ".join(part for part in why_now_parts if part),
            evidence_refs=row.evidence_refs,
            related_people=row.related_people,
            related_commitment_ids=row.related_commitment_ids,
            recommended_action="resolve decision",
            status=row.status,
            confidence=0.9 if row.evidence_refs else 0.75,
            object_ref=row.id,
            evidence_count=len(row.evidence_refs),
        )

    def _brief_item_from_commitment(self, row: CommitmentItem, *, workspace_id: str) -> BriefItem:
        why_now_parts = [
            row.status.replace("_", " ").title() if str(row.status or "").strip().lower() not in {"open", "completed", "dropped"} else "",
            row.risk_level.replace("_", " ").title(),
            f"Due {row.due_at[:10]}" if row.due_at else "",
            row.counterparty,
        ]
        recommended_action = "close commitment"
        if str(row.status or "").strip().lower() == "waiting_on_external":
            recommended_action = "check external dependency"
        elif str(row.status or "").strip().lower() == "scheduled":
            recommended_action = "confirm scheduled follow-up"
        return BriefItem(
            id=f"brief:{row.id}",
            workspace_id=workspace_id,
            kind="commitment",
            title=row.statement,
            summary=row.proof_refs[0].note if row.proof_refs else row.statement,
            score=float(priority_weight(row.risk_level) + due_bonus(row.due_at)),
            why_now=" · ".join(part for part in why_now_parts if part),
            evidence_refs=row.proof_refs,
            related_people=(row.counterparty,) if row.counterparty else (),
            related_commitment_ids=(row.id,),
            recommended_action=recommended_action,
            status=row.status,
            confidence=row.confidence,
            object_ref=row.id,
            evidence_count=len(row.proof_refs),
        )

    def _brief_item_from_handoff(self, row: HandoffNote, *, workspace_id: str) -> BriefItem:
        why_now_parts = [
            row.escalation_status.replace("_", " ").title(),
            f"Due {row.due_time[:10]}" if row.due_time else "",
            row.owner,
        ]
        return BriefItem(
            id=f"brief:{row.id}",
            workspace_id=workspace_id,
            kind="handoff",
            title=row.summary,
            summary=row.evidence_refs[0].note if row.evidence_refs else row.summary,
            score=float(priority_weight(row.escalation_status) + due_bonus(row.due_time)),
            why_now=" · ".join(part for part in why_now_parts if part),
            evidence_refs=row.evidence_refs,
            related_people=(row.owner,) if row.owner else (),
            related_commitment_ids=(),
            recommended_action="claim handoff" if row.status == "pending" else "review handoff",
            status=row.status,
            confidence=0.8 if row.evidence_refs else 0.65,
            object_ref=row.id,
            evidence_count=len(row.evidence_refs),
        )

    def _brief_event_context(self, *, principal_id: str) -> dict[str, object]:
        deferred_counts: dict[str, int] = {}
        rows = list(self._container.channel_runtime.list_recent_observations(limit=500, principal_id=principal_id))
        rows.sort(key=lambda row: (str(row.created_at or ""), str(row.observation_id or "")))
        for row in rows:
            if str(row.channel or "").strip() != "product":
                continue
            event_type = str(row.event_type or "").strip().lower()
            payload = dict(row.payload or {})
            item_ref = str(payload.get("item_ref") or "").strip()
            action = str(payload.get("action") or "").strip().lower()
            if not item_ref:
                continue
            if event_type == "commitment_deferred" or (event_type == "queue_resolved" and action in {"defer", "snooze"}):
                deferred_counts[item_ref] = int(deferred_counts.get(item_ref) or 0) + 1
        return {"deferred_counts": deferred_counts}

    def list_brief_items(self, *, principal_id: str, limit: int = 20, operator_id: str = "") -> tuple[BriefItem, ...]:
        event_context = self._brief_event_context(principal_id=principal_id)
        deferred_counts = {str(key): int(value or 0) for key, value in dict(event_context.get("deferred_counts") or {}).items()}
        queue = self.list_queue(principal_id=principal_id, limit=max(limit, 8), operator_id=operator_id)
        decisions = self.list_decisions(principal_id=principal_id, limit=max(limit, 6))
        commitments = self.list_commitments(principal_id=principal_id, limit=max(limit, 6))
        handoffs = self.list_handoffs(principal_id=principal_id, limit=max(limit, 4), operator_id=operator_id, status=None)
        items: list[BriefItem] = []
        items.extend(self._brief_item_from_decision(row, workspace_id=principal_id) for row in decisions)
        items.extend(self._brief_item_from_commitment(row, workspace_id=principal_id) for row in commitments)
        items.extend(self._brief_item_from_handoff(row, workspace_id=principal_id) for row in handoffs)
        for row in queue:
            if row.id.startswith(("decision:", "commitment:", "follow_up:", "human_task:")):
                continue
            items.append(self._brief_item_from_queue(row, workspace_id=principal_id))
        contextualized: list[BriefItem] = []
        for row in items:
            deferred_count = int(deferred_counts.get(str(row.object_ref or row.id).strip()) or 0)
            if deferred_count <= 0:
                contextualized.append(row)
                continue
            deferred_label = f"Deferred {deferred_count} time" if deferred_count == 1 else f"Deferred {deferred_count} times"
            contextualized.append(
                BriefItem(
                    id=row.id,
                    workspace_id=row.workspace_id,
                    kind=row.kind,
                    title=row.title,
                    summary=row.summary,
                    score=float(row.score + min(0.6 * deferred_count, 1.8)),
                    why_now=" · ".join(part for part in (row.why_now, deferred_label) if part),
                    evidence_refs=row.evidence_refs,
                    related_people=row.related_people,
                    related_commitment_ids=row.related_commitment_ids,
                    recommended_action=row.recommended_action,
                    status=row.status,
                    confidence=row.confidence,
                    object_ref=row.object_ref,
                    evidence_count=row.evidence_count,
                )
            )
        deduped: dict[str, BriefItem] = {}
        for row in contextualized:
            key = row.object_ref or row.id
            current = deduped.get(key)
            if current is None or (row.score, row.evidence_count, row.confidence) > (current.score, current.evidence_count, current.confidence):
                deduped[key] = row
        ordered = sorted(
            deduped.values(),
            key=lambda row: (row.score, row.evidence_count, row.confidence, row.title.lower()),
            reverse=True,
        )
        return tuple(ordered[:limit])

    def _person_profile(self, row: Stakeholder, *, open_loops_count: int) -> PersonProfile:
        themes = tuple(str(key).replace("_", " ") for key in dict(row.open_loops_json or {}).keys())
        risks = tuple(str(key).replace("_", " ") for key in dict(row.friction_points_json or {}).keys())
        importance_key = str(row.importance or "medium").strip().lower() or "medium"
        return PersonProfile(
            id=row.stakeholder_id,
            display_name=row.display_name,
            role_or_company=row.channel_ref or row.authority_level,
            importance_score=priority_weight(importance_key),
            relationship_temperature=_TEMPERATURE_BY_IMPORTANCE.get(importance_key, "steady"),
            open_loops_count=open_loops_count,
            latest_touchpoint_at=row.last_interaction_at,
            preferred_tone=row.tone_pref,
            themes=themes,
            risks=risks or (("open loops",) if open_loops_count else ()),
        )

    def list_people(self, *, principal_id: str, limit: int = 25) -> tuple[PersonProfile, ...]:
        stakeholders = list(self._container.memory_runtime.list_stakeholders(principal_id=principal_id, limit=limit))
        follow_ups = list(self._container.memory_runtime.list_follow_ups(principal_id=principal_id, limit=200, status=None))
        commitments = list(self._container.memory_runtime.list_commitments(principal_id=principal_id, limit=200, status=None))
        rows: list[PersonProfile] = []
        for row in stakeholders:
            open_loops = len(dict(row.open_loops_json or {}))
            open_loops += sum(1 for follow_up in follow_ups if status_open(follow_up.status) and str(follow_up.stakeholder_ref or "") == row.stakeholder_id)
            open_loops += sum(1 for commitment in commitments if status_open(commitment.status) and row.display_name.lower() in str(commitment.details or "").lower())
            rows.append(self._person_profile(row, open_loops_count=open_loops))
        rows.sort(key=lambda row: (row.importance_score, row.open_loops_count, row.display_name.lower()), reverse=True)
        return tuple(rows[:limit])

    def get_person(self, *, principal_id: str, person_id: str) -> PersonProfile | None:
        found = self._container.memory_runtime.get_stakeholder(person_id, principal_id=principal_id)
        if found is None:
            return None
        people = {row.id: row for row in self.list_people(principal_id=principal_id, limit=200)}
        return people.get(found.stakeholder_id, self._person_profile(found, open_loops_count=len(dict(found.open_loops_json or {}))))

    def get_person_detail(self, *, principal_id: str, person_id: str, operator_id: str = "") -> PersonDetail | None:
        profile = self.get_person(principal_id=principal_id, person_id=person_id)
        if profile is None:
            return None
        person_tokens = tuple(
            token
            for token in {
                profile.display_name,
                profile.role_or_company,
                profile.display_name.split(" ", 1)[0] if profile.display_name else "",
            }
            if str(token or "").strip()
        )

        def _matches(*values: str | None) -> bool:
            return any(contains_token(value, token) for token in person_tokens for value in values)

        commitments = tuple(
            row
            for row in self.list_commitments(principal_id=principal_id, limit=100)
            if _matches(row.statement, row.counterparty, row.owner, row.proof_refs[0].note if row.proof_refs else "")
        )
        drafts = tuple(
            row
            for row in self.list_drafts(principal_id=principal_id, limit=100)
            if _matches(row.recipient_summary, row.draft_text, row.intent)
        )
        threads = tuple(
            row
            for row in self.list_threads(principal_id=principal_id, limit=100)
            if _matches(
                row.title,
                row.summary,
                *row.counterparties,
                *(ref.note for ref in row.evidence_refs),
            )
        )
        queue_items = tuple(
            row
            for row in self.list_queue(principal_id=principal_id, limit=100, operator_id=operator_id)
            if _matches(
                row.title,
                row.summary,
                row.evidence_refs[0].note if row.evidence_refs else "",
            )
        )
        handoffs = tuple(
            row
            for row in self.list_handoffs(principal_id=principal_id, limit=100, operator_id=operator_id)
            if _matches(
                row.summary,
                row.owner,
                row.evidence_refs[0].note if row.evidence_refs else "",
            )
        )
        evidence: list[EvidenceRef] = []
        seen: set[str] = set()
        for refs in [
            *(row.proof_refs for row in commitments),
            *(row.provenance_refs for row in drafts),
            *(row.evidence_refs for row in threads),
            *(row.evidence_refs for row in queue_items),
            *(row.evidence_refs for row in handoffs),
        ]:
            for ref in refs:
                if ref.ref_id in seen:
                    continue
                seen.add(ref.ref_id)
                evidence.append(ref)
        history_source_ids: list[str] = [person_id]
        for values in (
            *(row.id for row in commitments),
            *(row.id for row in drafts),
            *(row.id for row in handoffs),
            *(row.id for row in threads),
            *(draft_id for row in threads for draft_id in row.draft_ids),
        ):
            normalized = str(values or "").strip()
            if not normalized:
                continue
            history_source_ids.append(normalized)
            if ":" in normalized:
                history_source_ids.append(normalized.split(":", 1)[1])
        return PersonDetail(
            profile=profile,
            commitments=commitments,
            drafts=drafts,
            threads=threads,
            queue_items=queue_items,
            handoffs=handoffs,
            evidence_refs=tuple(evidence[:12]),
            history=self._history_entries(principal_id=principal_id, source_ids=tuple(history_source_ids), limit=12),
        )

    def get_person_history(self, *, principal_id: str, person_id: str, limit: int = 20) -> tuple[HistoryEntry, ...]:
        detail = self.get_person_detail(principal_id=principal_id, person_id=person_id)
        if detail is None:
            return ()
        source_ids: list[str] = [person_id]
        for values in (
            *(row.id for row in detail.commitments),
            *(row.id for row in detail.drafts),
            *(row.id for row in detail.handoffs),
            *(row.id for row in detail.threads),
            *(draft_id for row in detail.threads for draft_id in row.draft_ids),
        ):
            normalized = str(values or "").strip()
            if not normalized:
                continue
            source_ids.append(normalized)
            if ":" in normalized:
                source_ids.append(normalized.split(":", 1)[1])
        return self._history_entries(principal_id=principal_id, source_ids=tuple(source_ids), limit=limit)

    def correct_person_profile(
        self,
        *,
        principal_id: str,
        person_id: str,
        preferred_tone: str = "",
        add_theme: str = "",
        remove_theme: str = "",
        add_risk: str = "",
        remove_risk: str = "",
    ) -> PersonDetail | None:
        current = self._container.memory_runtime.get_stakeholder(person_id, principal_id=principal_id)
        if current is None:
            return None
        open_loops = dict(current.open_loops_json or {})
        risks = dict(current.friction_points_json or {})
        if add_theme.strip():
            open_loops[add_theme.strip().replace(" ", "_")] = True
        if remove_theme.strip():
            open_loops.pop(remove_theme.strip().replace(" ", "_"), None)
        if add_risk.strip():
            risks[add_risk.strip().replace(" ", "_")] = "user_corrected"
        if remove_risk.strip():
            risks.pop(remove_risk.strip().replace(" ", "_"), None)
        self._container.memory_runtime.upsert_stakeholder(
            principal_id=principal_id,
            stakeholder_id=current.stakeholder_id,
            display_name=current.display_name,
            channel_ref=current.channel_ref,
            authority_level=current.authority_level,
            importance=current.importance,
            response_cadence=current.response_cadence,
            tone_pref=preferred_tone.strip() or current.tone_pref,
            sensitivity=current.sensitivity,
            escalation_policy=current.escalation_policy,
            open_loops_json=open_loops,
            friction_points_json=risks,
            last_interaction_at=current.last_interaction_at,
            status=current.status,
            notes=current.notes,
        )
        self._record_product_event(
            principal_id=principal_id,
            event_type="memory_corrected",
            payload={
                "person_id": person_id,
                "preferred_tone": preferred_tone.strip(),
                "add_theme": add_theme.strip(),
                "remove_theme": remove_theme.strip(),
                "add_risk": add_risk.strip(),
                "remove_risk": remove_risk.strip(),
            },
            source_id=current.stakeholder_id,
        )
        return self.get_person_detail(principal_id=principal_id, person_id=person_id)

    def list_handoffs(
        self,
        *,
        principal_id: str,
        limit: int = 20,
        operator_id: str = "",
        status: str | None = "pending",
    ) -> tuple[HandoffNote, ...]:
        operator_key = str(operator_id or "").strip()
        rows: list[HandoffNote] = []
        for task in self._container.orchestrator.list_human_tasks(principal_id=principal_id, status=status, limit=limit):
            assigned = str(task.assigned_operator_id or "").strip()
            if operator_key and assigned and assigned != operator_key:
                continue
            rows.append(self._handoff_from_human_task(task))
        rows.sort(key=lambda row: (priority_weight(row.escalation_status), due_bonus(row.due_time), row.summary.lower()), reverse=True)
        return tuple(rows[:limit])

    def get_handoff(self, *, principal_id: str, handoff_ref: str) -> HandoffNote | None:
        if not str(handoff_ref or "").startswith("human_task:"):
            return None
        found = self._container.orchestrator.fetch_human_task(handoff_ref.split(":", 1)[1], principal_id=principal_id)
        if found is None:
            return None
        return self._handoff_from_human_task(found)

    def assign_handoff(self, *, principal_id: str, handoff_ref: str, operator_id: str, actor: str) -> HandoffNote | None:
        if not handoff_ref.startswith("human_task:"):
            return None
        updated = self._container.orchestrator.assign_human_task(
            handoff_ref.split(":", 1)[1],
            principal_id=principal_id,
            operator_id=operator_id,
            assignment_source="manual",
            assigned_by_actor_id=actor,
        )
        if updated is None:
            return None
        self._record_product_event(
            principal_id=principal_id,
            event_type="handoff_assigned",
            payload={"handoff_ref": handoff_ref, "operator_id": operator_id, "actor": actor},
            source_id=updated.human_task_id,
        )
        return self._handoff_from_human_task(updated)

    def complete_handoff(
        self,
        *,
        principal_id: str,
        handoff_ref: str,
        operator_id: str,
        actor: str,
        resolution: str,
    ) -> HandoffNote | None:
        if not handoff_ref.startswith("human_task:"):
            return None
        task_id = handoff_ref.split(":", 1)[1]
        current = self._container.orchestrator.fetch_human_task(task_id, principal_id=principal_id)
        if current is None:
            return None
        normalized_resolution = (
            self._normalize_delivery_followup_resolution(resolution)
            if str(current.task_type or "").strip() == "delivery_followup"
            else str(resolution or "").strip() or "completed"
        )
        updated = self._container.orchestrator.return_human_task(
            task_id,
            principal_id=principal_id,
            operator_id=operator_id,
            resolution=normalized_resolution,
            returned_payload_json={
                "source": "product_handoffs",
                "actor": actor,
                "task_type": str(current.task_type or "").strip(),
                "draft_ref": str(dict(current.input_json or {}).get("draft_ref") or "").strip(),
                "recipient_email": str(dict(current.input_json or {}).get("recipient_email") or "").strip(),
                "subject": str(dict(current.input_json or {}).get("subject") or "").strip(),
                "reason": str(dict(current.input_json or {}).get("reason") or "").strip(),
                "resolution": normalized_resolution,
            },
            provenance_json={"source": "product_handoffs"},
        )
        if updated is None:
            return None
        if str(current.task_type or "").strip() == "delivery_followup":
            self._record_delivery_followup_resolution(
                principal_id=principal_id,
                handoff_ref=handoff_ref,
                task=current,
                operator_id=operator_id,
                actor=actor,
                resolution=normalized_resolution,
            )
        self._record_product_event(
            principal_id=principal_id,
            event_type="handoff_completed",
            payload={"handoff_ref": handoff_ref, "operator_id": operator_id, "actor": actor, "resolution": normalized_resolution},
            source_id=updated.human_task_id,
        )
        return self._handoff_from_human_task(updated)

    def _queue_health(
        self,
        *,
        principal_id: str,
        operator_id: str = "",
    ) -> tuple[dict[str, object], tuple[HandoffNote, ...]]:
        operator_key = str(operator_id or "").strip()
        pending_tasks = list(self._container.orchestrator.list_human_tasks(principal_id=principal_id, status="pending", limit=200))
        visible_tasks: list[HumanTask] = []
        for task in pending_tasks:
            assigned = str(task.assigned_operator_id or "").strip()
            if operator_key and assigned and assigned != operator_key:
                continue
            visible_tasks.append(task)
        unclaimed_tasks = [task for task in visible_tasks if not str(task.assigned_operator_id or "").strip()]
        assigned_tasks = [task for task in visible_tasks if str(task.assigned_operator_id or "").strip()]
        sla_breaches = [task for task in visible_tasks if _is_past_due(task.sla_due_at)]
        approvals = list(self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=200))
        pending_delivery = list(self._container.channel_runtime.list_pending_delivery(limit=200, principal_id=principal_id))
        retrying_delivery = [row for row in pending_delivery if str(getattr(row, "status", "") or "").strip() == "retry"]
        delivery_errors = [row for row in pending_delivery if str(getattr(row, "last_error", "") or "").strip()]
        oldest_pending_delivery_hours = max((_hours_since(str(getattr(row, "created_at", "") or "")) for row in pending_delivery), default=0)
        highest_delivery_attempt_count = max((int(getattr(row, "attempt_count", 0) or 0) for row in pending_delivery), default=0)
        queue_items = self.list_queue(principal_id=principal_id, limit=100, operator_id=operator_id)
        waiting_on_principal = sum(1 for row in queue_items if row.requires_principal)
        at_risk_commitments = sum(1 for row in self.list_commitments(principal_id=principal_id, limit=100) if row.risk_level == "high")
        oldest_handoff_hours = max(
            (
                _hours_since(
                    str(
                        getattr(task, "created_at", None)
                        or getattr(task, "updated_at", None)
                        or getattr(task, "last_transition_at", None)
                        or ""
                    )
                )
                for task in visible_tasks
            ),
            default=0,
        )
        suggested_tasks = sorted(
            unclaimed_tasks,
            key=lambda row: (priority_weight(row.priority), due_bonus(row.sla_due_at), str(row.brief or "").lower()),
            reverse=True,
        )
        suggestion_rows = tuple(self._handoff_from_human_task(row) for row in suggested_tasks[:3])
        load_score = (
            (len(sla_breaches) * 5)
            + (len(unclaimed_tasks) * 2)
            + (len(approvals) * 2)
            + waiting_on_principal
            + at_risk_commitments
            + (len(retrying_delivery) * 3)
            + len(delivery_errors)
        )
        if sla_breaches or len(approvals) >= 3 or waiting_on_principal >= 4 or retrying_delivery:
            state = "critical"
            detail = "SLA breaches, approval backlog, or principal-gated work need active clearing."
        elif unclaimed_tasks or at_risk_commitments >= 2 or pending_delivery or delivery_errors:
            state = "watch"
            detail = "The queue is stable, but there is visible backlog that should be cleared before the next memo cycle."
        else:
            state = "healthy"
            detail = "The operator lane is clear enough to trust the current office loop."
        return (
            {
                "state": state,
                "detail": detail,
                "pending_handoffs": len(visible_tasks),
                "assigned_handoffs": len(assigned_tasks),
                "unclaimed_handoffs": len(unclaimed_tasks),
                "sla_breaches": len(sla_breaches),
                "pending_approvals": len(approvals),
                "waiting_on_principal": waiting_on_principal,
                "at_risk_commitments": at_risk_commitments,
                "pending_delivery": len(pending_delivery),
                "retrying_delivery": len(retrying_delivery),
                "delivery_errors": len(delivery_errors),
                "highest_delivery_attempt_count": highest_delivery_attempt_count,
                "oldest_handoff_age_hours": oldest_handoff_hours,
                "oldest_pending_delivery_age_hours": oldest_pending_delivery_hours,
                "load_score": load_score,
                "suggested_claims": len(suggestion_rows),
            },
            suggestion_rows,
        )

    def workspace_snapshot(self, *, principal_id: str, operator_id: str = "") -> ProductSnapshot:
        brief_items = self.list_brief_items(principal_id=principal_id, limit=8, operator_id=operator_id)
        queue_items = self.list_queue(principal_id=principal_id, limit=10, operator_id=operator_id)
        commitments = self.list_commitments(principal_id=principal_id, limit=10)
        recently_closed_commitments = self.list_recently_closed_commitments(principal_id=principal_id, limit=6)
        commitment_candidates = self.list_reviewable_commitment_candidates(principal_id=principal_id, limit=8)
        drafts = self.list_drafts(principal_id=principal_id, limit=8)
        decisions = self.list_decisions(principal_id=principal_id, limit=8)
        threads = self.list_threads(principal_id=principal_id, limit=8)
        people = self.list_people(principal_id=principal_id, limit=8)
        handoffs = self.list_handoffs(principal_id=principal_id, limit=8, operator_id=operator_id)
        completed_handoffs = self.list_handoffs(
            principal_id=principal_id,
            limit=6,
            operator_id=operator_id,
            status="returned",
        )
        queue_health, _suggestions = self._queue_health(principal_id=principal_id, operator_id=operator_id)
        evidence = self.list_evidence(principal_id=principal_id, limit=8, operator_id=operator_id)
        rules = self.list_rules(principal_id=principal_id)
        return ProductSnapshot(
            brief_items=brief_items,
            queue_items=queue_items,
            commitments=commitments,
            recently_closed_commitments=recently_closed_commitments,
            commitment_candidates=commitment_candidates,
            drafts=drafts,
            decisions=decisions,
            threads=threads,
            people=people,
            handoffs=handoffs,
            completed_handoffs=completed_handoffs,
            evidence=evidence,
            rules=rules,
            stats_json={
                "brief_items": len(brief_items),
                "queue_items": len(queue_items),
                "commitments": len(commitments),
                "recently_closed_commitments": len(recently_closed_commitments),
                "commitment_candidates": len(commitment_candidates),
                "drafts": len(drafts),
                "decisions": len(decisions),
                "threads": len(threads),
                "people": len(people),
                "handoffs": len(handoffs),
                "completed_handoffs": len(completed_handoffs),
                "sla_breaches": int(queue_health.get("sla_breaches") or 0),
                "unclaimed_handoffs": int(queue_health.get("unclaimed_handoffs") or 0),
                "pending_approvals": int(queue_health.get("pending_approvals") or 0),
                "pending_delivery": int(queue_health.get("pending_delivery") or 0),
                "waiting_on_principal": int(queue_health.get("waiting_on_principal") or 0),
                "evidence": len(evidence),
                "rules": len(rules),
            },
        )

    def workspace_diagnostics(self, *, principal_id: str) -> dict[str, object]:
        status = self._container.onboarding.status(principal_id=principal_id)
        workspace = dict(status.get("workspace") or {})
        delivery_preferences = dict(status.get("delivery_preferences") or {})
        morning_memo = dict(delivery_preferences.get("morning_memo") or {})
        selected_channels = tuple(str(value) for value in (status.get("selected_channels") or []) if str(value).strip())
        plan = workspace_plan_for_mode(str(workspace.get("mode") or "personal"))
        snapshot = self.workspace_snapshot(principal_id=principal_id)
        queue_health, assignment_suggestions = self._queue_health(principal_id=principal_id)
        readiness_ok, readiness_label = self._container.readiness.check()
        registry = self._container.provider_registry.registry_read_model(principal_id=principal_id)
        provider_summary = self._provider_summary(registry)
        operators = self._container.orchestrator.list_operator_profiles(principal_id=principal_id, status="active", limit=25)
        product_events = [
            row
            for row in self._container.channel_runtime.list_recent_observations(limit=200, principal_id=principal_id)
            if str(row.channel or "").strip() == "product"
        ]
        event_rows = sorted(product_events, key=lambda row: str(row.created_at or ""))
        analytics_counts: dict[str, int] = {}
        activation_started_at = ""
        first_value_at = ""
        first_value_event = ""
        first_scheduled_memo_sent_at = ""
        last_scheduled_memo_sent_at = ""
        last_memo_delivery_sent_at = ""
        useful_loop_days: set[str] = set()
        latest_memo_issue_at = ""
        latest_memo_issue_kind = ""
        latest_memo_issue_reason = ""
        latest_memo_issue_fix_href = ""
        latest_memo_issue_fix_label = ""
        latest_memo_issue_fix_detail = ""
        first_value_types = {
            "draft_sent",
            "draft_send_followup_created",
            "commitment_created",
            "commitment_closed",
            "handoff_completed",
            "memory_corrected",
            "memo_opened",
        }
        for row in event_rows:
            analytics_counts[row.event_type] = int(analytics_counts.get(row.event_type, 0) or 0) + 1
            created_at = str(row.created_at or "").strip()
            payload = dict(getattr(row, "payload", {}) or {})
            if row.event_type == "activation_opened" and created_at and not activation_started_at:
                activation_started_at = created_at
            if row.event_type in first_value_types and created_at and not first_value_at:
                first_value_at = created_at
                first_value_event = row.event_type
            if row.event_type == "scheduled_morning_memo_delivery_sent":
                local_day = str(payload.get("local_day") or "").strip()
                if local_day:
                    useful_loop_days.add(local_day)
                if created_at and not first_scheduled_memo_sent_at:
                    first_scheduled_memo_sent_at = created_at
                if created_at:
                    last_scheduled_memo_sent_at = created_at
                    last_memo_delivery_sent_at = created_at
            if (
                row.event_type == "channel_digest_delivery_email_sent"
                and str(payload.get("digest_key") or "").strip().lower() == "memo"
                and created_at
            ):
                sent_at = _parse_iso(created_at)
                latest_sent_at = _parse_iso(last_memo_delivery_sent_at)
                if latest_sent_at is None or (sent_at is not None and sent_at >= latest_sent_at):
                    last_memo_delivery_sent_at = created_at
            if row.event_type in {"scheduled_morning_memo_delivery_failed", "scheduled_morning_memo_delivery_blocked"} and created_at:
                issue_at = _parse_iso(created_at)
                latest_issue_at = _parse_iso(latest_memo_issue_at)
                if latest_issue_at is None or (issue_at is not None and issue_at >= latest_issue_at):
                    issue_reason = _memo_issue_reason(
                        reason=str(payload.get("reason") or "").strip(),
                        error=str(payload.get("email_delivery_error") or "").strip(),
                    )
                    fix_href, fix_label = _memo_issue_fix(
                        reason=str(payload.get("reason") or "").strip(),
                        error=str(payload.get("email_delivery_error") or "").strip(),
                    )
                    fix_detail = _memo_issue_fix_detail(
                        reason=str(payload.get("reason") or "").strip(),
                        error=str(payload.get("email_delivery_error") or "").strip(),
                    )
                    latest_memo_issue_at = created_at
                    latest_memo_issue_kind = "failed" if row.event_type == "scheduled_morning_memo_delivery_failed" else "blocked"
                    latest_memo_issue_reason = issue_reason
                    latest_memo_issue_fix_href = fix_href if issue_reason else ""
                    latest_memo_issue_fix_label = fix_label if issue_reason else ""
                    latest_memo_issue_fix_detail = fix_detail if issue_reason else ""
            if (
                row.event_type == "channel_digest_delivery_email_failed"
                and str(payload.get("digest_key") or "").strip().lower() == "memo"
                and created_at
            ):
                issue_at = _parse_iso(created_at)
                latest_issue_at = _parse_iso(latest_memo_issue_at)
                if latest_issue_at is None or (issue_at is not None and issue_at >= latest_issue_at):
                    issue_reason = _memo_issue_reason(error=str(payload.get("error") or "").strip())
                    fix_href, fix_label = _memo_issue_fix(error=str(payload.get("error") or "").strip())
                    fix_detail = _memo_issue_fix_detail(error=str(payload.get("error") or "").strip())
                    latest_memo_issue_at = created_at
                    latest_memo_issue_kind = "failed"
                    latest_memo_issue_reason = issue_reason
                    latest_memo_issue_fix_href = fix_href if issue_reason else ""
                    latest_memo_issue_fix_label = fix_label if issue_reason else ""
                    latest_memo_issue_fix_detail = fix_detail if issue_reason else ""
        first_value_seconds: int | None = None
        if activation_started_at and first_value_at:
            try:
                started = datetime.fromisoformat(activation_started_at.replace("Z", "+00:00"))
                reached = datetime.fromisoformat(first_value_at.replace("Z", "+00:00"))
                first_value_seconds = max(int((reached - started).total_seconds()), 0)
            except Exception:
                first_value_seconds = None
        google_sync_last_event = next((row for row in reversed(event_rows) if row.event_type == "google_workspace_signal_sync_completed"), None)
        google_sync_last_payload = dict(getattr(google_sync_last_event, "payload", {}) or {}) if google_sync_last_event is not None else {}
        google_sync_last_completed_at = str(getattr(google_sync_last_event, "created_at", "") or "").strip()
        google_send_verification_last_event = next(
            (
                row
                for row in reversed(event_rows)
                if row.event_type in {"google_send_verification_completed", "google_send_verification_failed"}
            ),
            None,
        )
        google_send_verification_last_payload = (
            dict(getattr(google_send_verification_last_event, "payload", {}) or {})
            if google_send_verification_last_event is not None
            else {}
        )
        google_send_verification_last_at = str(getattr(google_send_verification_last_event, "created_at", "") or "").strip()
        google_send_verification_last_state = (
            "completed"
            if str(getattr(google_send_verification_last_event, "event_type", "") or "").strip() == "google_send_verification_completed"
            else "failed"
            if google_send_verification_last_event is not None
            else ""
        )
        google_account_change_last_event = next(
            (
                row
                for row in reversed(event_rows)
                if row.event_type in {
                    "google_account_connected",
                    "google_account_primary_updated",
                    "google_account_disconnected",
                }
            ),
            None,
        )
        google_account_change_last_payload = (
            dict(getattr(google_account_change_last_event, "payload", {}) or {})
            if google_account_change_last_event is not None
            else {}
        )
        google_account_change_last_at = str(getattr(google_account_change_last_event, "created_at", "") or "").strip()
        google_account_change_last_state = (
            str(getattr(google_account_change_last_event, "event_type", "") or "").strip().replace("google_", "")
            if google_account_change_last_event is not None
            else ""
        )
        pocket_sync_last_event = next((row for row in reversed(event_rows) if row.event_type == "pocket_recording_sync_completed"), None)
        pocket_sync_last_payload = dict(getattr(pocket_sync_last_event, "payload", {}) or {}) if pocket_sync_last_event is not None else {}
        pocket_sync_last_completed_at = str(getattr(pocket_sync_last_event, "created_at", "") or "").strip()
        google_accounts = google_oauth_service.list_google_accounts(container=self._container, principal_id=principal_id)
        primary_google_account = next(
            (
                account
                for account in google_accounts
                if str(account.binding.status or "").strip().lower() == "enabled"
                and str(account.token_status or "").strip().lower() != "revoked"
            ),
            google_accounts[0] if google_accounts else None,
        )
        google_connected = primary_google_account is not None or bool(str(google_sync_last_payload.get("account_email") or "").strip())
        google_account_email = str(
            getattr(primary_google_account, "google_email", "") or google_sync_last_payload.get("account_email") or ""
        ).strip()
        google_token_status = str(getattr(primary_google_account, "token_status", "") or "").strip() or ("active" if google_sync_last_completed_at else ("missing" if not google_connected else "unknown"))
        google_last_refresh_at = str(getattr(primary_google_account, "last_refresh_at", "") or google_sync_last_completed_at or "").strip()
        google_reauth_required_reason = str(getattr(primary_google_account, "reauth_required_reason", "") or "").strip()
        google_send_verification_by_identity: dict[str, dict[str, object]] = {}
        for row in reversed(event_rows):
            if row.event_type not in {"google_send_verification_completed", "google_send_verification_failed"}:
                continue
            payload = dict(getattr(row, "payload", {}) or {})
            identity = (
                str(payload.get("google_subject") or "").strip().lower()
                or str(payload.get("google_email") or "").strip().lower()
                or str(payload.get("sender_email") or "").strip().lower()
                or str(payload.get("binding_id") or "").strip().lower()
            )
            if not identity or identity in google_send_verification_by_identity:
                continue
            google_send_verification_by_identity[identity] = {
                "state": "completed" if row.event_type == "google_send_verification_completed" else "failed",
                "verified_at": str(getattr(row, "created_at", "") or "").strip(),
                "sender_email": str(payload.get("sender_email") or "").strip(),
                "recipient_email": str(payload.get("recipient_email") or "").strip(),
                "error": str(payload.get("error") or "").strip(),
            }
        google_send_verification_accounts: list[dict[str, object]] = []
        for account in google_accounts:
            identity_keys = (
                str(account.google_subject or "").strip().lower(),
                str(account.google_email or "").strip().lower(),
                str(account.binding.binding_id or "").strip().lower(),
            )
            matched: dict[str, object] = {}
            for identity_key in identity_keys:
                if identity_key and identity_key in google_send_verification_by_identity:
                    matched = dict(google_send_verification_by_identity[identity_key])
                    break
            google_send_verification_accounts.append(
                {
                    "binding_id": str(account.binding.binding_id or "").strip(),
                    "google_email": str(account.google_email or "").strip(),
                    "google_subject": str(account.google_subject or "").strip(),
                    "is_primary": str(account.binding.binding_id or "").strip()
                    == f"{account.binding.principal_id}:{google_oauth_service.GOOGLE_PROVIDER_KEY}",
                    "state": str(matched.get("state") or "").strip(),
                    "verified_at": str(matched.get("verified_at") or "").strip(),
                    "sender_email": str(matched.get("sender_email") or "").strip(),
                    "recipient_email": str(matched.get("recipient_email") or "").strip(),
                    "error": str(matched.get("error") or "").strip(),
                }
            )
        google_account_change_by_identity: dict[str, dict[str, object]] = {}
        for row in reversed(event_rows):
            if row.event_type not in {
                "google_account_connected",
                "google_account_primary_updated",
                "google_account_disconnected",
            }:
                continue
            payload = dict(getattr(row, "payload", {}) or {})
            identity = (
                str(payload.get("google_subject") or "").strip().lower()
                or str(payload.get("google_email") or "").strip().lower()
                or str(payload.get("binding_id") or "").strip().lower()
            )
            if not identity or identity in google_account_change_by_identity:
                continue
            google_account_change_by_identity[identity] = {
                "state": str(row.event_type or "").strip().replace("google_", ""),
                "changed_at": str(getattr(row, "created_at", "") or "").strip(),
                "google_email": str(payload.get("google_email") or "").strip(),
                "error": str(payload.get("error") or "").strip(),
            }
        google_account_change_accounts: list[dict[str, object]] = []
        for account in google_accounts:
            identity_keys = (
                str(account.google_subject or "").strip().lower(),
                str(account.google_email or "").strip().lower(),
                str(account.binding.binding_id or "").strip().lower(),
            )
            matched_change: dict[str, object] = {}
            for identity_key in identity_keys:
                if identity_key and identity_key in google_account_change_by_identity:
                    matched_change = dict(google_account_change_by_identity[identity_key])
                    break
            google_account_change_accounts.append(
                {
                    "binding_id": str(account.binding.binding_id or "").strip(),
                    "google_email": str(account.google_email or "").strip(),
                    "google_subject": str(account.google_subject or "").strip(),
                    "is_primary": str(account.binding.binding_id or "").strip()
                    == f"{account.binding.principal_id}:{google_oauth_service.GOOGLE_PROVIDER_KEY}",
                    "state": str(matched_change.get("state") or "").strip(),
                    "changed_at": str(matched_change.get("changed_at") or "").strip(),
                    "error": str(matched_change.get("error") or "").strip(),
                }
            )
        google_sync_age_seconds: int | None = None
        if google_sync_last_completed_at:
            try:
                google_sync_age_seconds = max(
                    int((_utcnow() - datetime.fromisoformat(google_sync_last_completed_at.replace("Z", "+00:00"))).total_seconds()),
                    0,
                )
            except Exception:
                google_sync_age_seconds = None
        pocket_sync_age_seconds: int | None = None
        if pocket_sync_last_completed_at:
            try:
                pocket_sync_age_seconds = max(
                    int((_utcnow() - datetime.fromisoformat(pocket_sync_last_completed_at.replace("Z", "+00:00"))).total_seconds()),
                    0,
                )
            except Exception:
                pocket_sync_age_seconds = None
        pending_candidate_rows = list(self.list_reviewable_commitment_candidates(principal_id=principal_id, limit=200))
        hidden_candidate_ids = self._pending_signal_draft_candidate_ids(principal_id=principal_id)
        covered_signal_candidates = sum(
            1 for row in pending_candidate_rows if str(row.candidate_id or "").strip() in hidden_candidate_ids
        )
        pending_commitment_candidates = max(len(pending_candidate_rows) - covered_signal_candidates, 0)
        usage_stats = dict(snapshot.stats_json or {})
        seats_used = len(operators)
        seat_limit = int(plan.entitlements.operator_seats or 0)
        seats_remaining = max(seat_limit - seats_used, 0)
        seat_overage = max(seats_used - seat_limit, 0)
        commercial_snapshot = workspace_commercial_snapshot(plan, seats_used=seats_used, selected_channels=selected_channels)
        selected_messaging = [str(value) for value in (commercial_snapshot.get("commercial", {}).get("selected_messaging_channels") or []) if str(value).strip()]
        warnings = [str(value) for value in (commercial_snapshot.get("commercial", {}).get("warnings") or []) if str(value).strip()]
        blocked_actions = [str(value) for value in (commercial_snapshot.get("commercial", {}).get("blocked_actions") or []) if str(value).strip()]
        if not readiness_ok:
            warnings.append(str(readiness_label or "Runtime readiness needs attention."))
            blocked_actions.append("runtime_readiness")
        if str(provider_summary.get("risk_state") or "") in {"attention", "watch", "critical"}:
            warnings.append(str(provider_summary.get("risk_detail") or "Provider posture needs attention."))
        recommended_plan = plan
        if seat_overage or (selected_messaging and not plan.entitlements.messaging_channels_enabled):
            recommended_plan = workspace_plan_for_mode("team" if plan.plan_key == "pilot" else "executive_ops")
        health_score = 100
        if not readiness_ok:
            health_score -= 30
        provider_risk = str(provider_summary.get("risk_state") or "healthy")
        if provider_risk == "watch":
            health_score -= 15
        elif provider_risk in {"attention", "critical"}:
            health_score -= 30
        queue_state = str(queue_health.get("state") or "healthy")
        if queue_state == "watch":
            health_score -= 15
        elif queue_state == "critical":
            health_score -= 30
        health_score = max(health_score - min(int(queue_health.get("delivery_errors") or 0) * 3, 15), 0)
        memo_opened_count = int(analytics_counts.get("memo_opened") or 0)
        approval_requested_count = int(analytics_counts.get("approval_requested") or 0)
        draft_approved_count = int(analytics_counts.get("draft_approved") or 0)
        draft_sent_count = int(analytics_counts.get("draft_sent") or 0)
        draft_send_followup_created_count = int(analytics_counts.get("draft_send_followup_created") or 0)
        draft_send_followup_resolved_count = int(analytics_counts.get("draft_send_followup_resolved") or 0)
        draft_send_reauth_needed_count = int(analytics_counts.get("draft_send_reauth_needed") or 0)
        draft_send_waiting_on_principal_count = int(analytics_counts.get("draft_send_waiting_on_principal") or 0)
        commitment_closed_count = int(analytics_counts.get("commitment_closed") or 0)
        memory_corrected_count = int(analytics_counts.get("memory_corrected") or 0)
        scheduled_memo_sent_count = int(analytics_counts.get("scheduled_morning_memo_delivery_sent") or 0)
        scheduled_memo_failed_count = int(analytics_counts.get("scheduled_morning_memo_delivery_failed") or 0)
        scheduled_memo_blocked_count = int(analytics_counts.get("scheduled_morning_memo_delivery_blocked") or 0)
        support_bundle_opened_count = int(analytics_counts.get("support_bundle_opened") or 0)
        registration_email_sent_count = int(analytics_counts.get("registration_email_sent") or 0)
        registration_email_failed_count = int(analytics_counts.get("registration_email_failed") or 0)
        invite_email_sent_count = int(analytics_counts.get("workspace_invitation_email_sent") or 0)
        invite_email_failed_count = int(analytics_counts.get("workspace_invitation_email_failed") or 0)
        digest_email_sent_count = int(analytics_counts.get("channel_digest_delivery_email_sent") or 0)
        digest_email_failed_count = int(analytics_counts.get("channel_digest_delivery_email_failed") or 0)
        access_session_issued_count = int(analytics_counts.get("workspace_access_session_issued") or 0)
        access_session_opened_count = int(analytics_counts.get("workspace_access_session_opened") or 0)
        access_session_revoked_count = int(analytics_counts.get("workspace_access_session_revoked") or 0)
        google_sync_completed_count = int(analytics_counts.get("google_workspace_signal_sync_completed") or 0)
        pocket_sync_completed_count = int(analytics_counts.get("pocket_recording_sync_completed") or 0)
        office_signal_ingested_count = int(analytics_counts.get("office_signal_ingested") or 0)
        active_access_sessions = len(self.list_workspace_access_sessions(principal_id=principal_id, status="active", limit=500))
        registration_delivery_success_rate = (
            round(
                registration_email_sent_count
                / max(registration_email_sent_count + registration_email_failed_count, 1),
                2,
            )
            if (registration_email_sent_count + registration_email_failed_count)
            else None
        )
        invite_delivery_success_rate = (
            round(invite_email_sent_count / max(invite_email_sent_count + invite_email_failed_count, 1), 2)
            if (invite_email_sent_count + invite_email_failed_count)
            else None
        )
        digest_delivery_success_rate = (
            round(digest_email_sent_count / max(digest_email_sent_count + digest_email_failed_count, 1), 2)
            if (digest_email_sent_count + digest_email_failed_count)
            else None
        )
        delivery_success_total = registration_email_sent_count + invite_email_sent_count + digest_email_sent_count
        delivery_failure_total = registration_email_failed_count + invite_email_failed_count + digest_email_failed_count
        delivery_success_rate = (
            round(delivery_success_total / max(delivery_success_total + delivery_failure_total, 1), 2)
            if (delivery_success_total + delivery_failure_total)
            else None
        )
        pending_invitations = len(self.list_workspace_invitations(principal_id=principal_id, status="pending", limit=500))
        accepted_invitations = len(self.list_workspace_invitations(principal_id=principal_id, status="accepted", limit=500))
        revoked_invitations = len(self.list_workspace_invitations(principal_id=principal_id, status="revoked", limit=500))
        workspace_access_open_rate = (
            round(access_session_opened_count / max(access_session_issued_count, 1), 2)
            if access_session_issued_count
            else None
        )
        access_reliability_state = (
            "watch"
            if access_session_issued_count and access_session_opened_count == 0
            else "clear"
            if access_session_issued_count or active_access_sessions
            else "watch"
        )
        google_sync_freshness_state = (
            "watch"
            if not google_connected
            else "critical"
            if google_token_status not in {"active", "unknown"}
            else "watch"
            if not google_sync_last_completed_at
            else "clear"
            if google_sync_age_seconds is None
            else "critical"
            if google_sync_age_seconds >= 86400
            else "watch"
            if google_sync_age_seconds >= 21600
            else "clear"
        )
        sync_reliability_state = google_sync_freshness_state
        current_commitments = int(usage_stats.get("commitments") or 0)
        current_queue_items = int(usage_stats.get("queue_items") or 0)
        memo_open_rate = 1.0 if memo_opened_count else 0.0
        approval_coverage_count = draft_sent_count + draft_send_followup_created_count
        approval_coverage_rate = (
            round(approval_coverage_count / approval_requested_count, 2)
            if approval_requested_count
            else (1.0 if approval_coverage_count else 0.0)
        )
        approval_action_rate = (
            round(draft_sent_count / approval_requested_count, 2)
            if approval_requested_count
            else (1.0 if draft_sent_count else 0.0)
        )
        delivery_followup_blocked_count = draft_send_reauth_needed_count + draft_send_waiting_on_principal_count
        delivery_followup_terminal_resolution_count = max(
            draft_send_followup_resolved_count - delivery_followup_blocked_count,
            0,
        )
        delivery_followup_resolution_rate = (
            round(delivery_followup_terminal_resolution_count / draft_send_followup_created_count, 2)
            if draft_send_followup_created_count
            else None
        )
        delivery_followup_blocked_rate = (
            round(delivery_followup_blocked_count / draft_send_followup_created_count, 2)
            if draft_send_followup_created_count
            else None
        )
        commitment_close_rate = round(commitment_closed_count / max(commitment_closed_count + current_commitments, 1), 2)
        correction_rate = round(memory_corrected_count / max(memo_opened_count, 1), 2)
        churn_risk = "low"
        if (first_value_seconds is None and current_queue_items >= 3) or memo_opened_count == 0:
            churn_risk = "watch"
        if (first_value_seconds is None and current_queue_items >= 5) or support_bundle_opened_count > memo_opened_count:
            churn_risk = "high"
        success_summary = (
            "Office loop is active."
            if churn_risk == "low"
            else "Activation needs help."
            if churn_risk == "high"
            else "Adoption needs attention."
        )
        memo_loop_state = (
            "watch"
            if not bool(morning_memo.get("enabled"))
            else "critical"
            if scheduled_memo_failed_count or scheduled_memo_blocked_count
            else "watch"
            if scheduled_memo_sent_count == 0
            else "clear"
        )
        if latest_memo_issue_at and last_memo_delivery_sent_at:
            latest_issue_at = _parse_iso(latest_memo_issue_at)
            last_sent_at = _parse_iso(last_memo_delivery_sent_at)
            if latest_issue_at is not None and last_sent_at is not None and latest_issue_at <= last_sent_at:
                latest_memo_issue_at = ""
                latest_memo_issue_kind = ""
                latest_memo_issue_reason = ""
                latest_memo_issue_fix_href = ""
                latest_memo_issue_fix_label = ""
                latest_memo_issue_fix_detail = ""
        active_memo_delivery_blocker = 1 if latest_memo_issue_reason else 0
        active_delivery_issue_total = int(queue_health.get("delivery_errors") or 0) + active_memo_delivery_blocker
        delivery_reliability_state = (
            "critical"
            if active_delivery_issue_total
            else "watch"
            if int(queue_health.get("retrying_delivery") or 0)
            else "clear"
        )
        product_control = self._product_control_projection()
        support_verification = self._support_fix_verification_projection(
            principal_id=principal_id,
            event_rows=tuple(event_rows),
        )
        product_control["support_fallout"] = _support_fallout_projection(
            queue_health=queue_health,
            support_verification=support_verification,
            journey_highlights=[dict(value) for value in list(product_control.get("journey_highlights") or []) if isinstance(value, dict)],
        )
        return {
            "workspace": {
                "name": str(workspace.get("name") or "Executive Workspace"),
                "mode": str(workspace.get("mode") or "personal"),
                "region": str(workspace.get("region") or ""),
                "language": str(workspace.get("language") or ""),
                "timezone": str(workspace.get("timezone") or ""),
            },
            "selected_channels": list(selected_channels),
            "plan": {
                "plan_key": plan.plan_key,
                "display_name": plan.display_name,
                "unit_of_sale": plan.unit_of_sale,
            },
            "billing": dict(commercial_snapshot.get("billing") or {}),
            "entitlements": {
                "principal_seats": plan.entitlements.principal_seats,
                "operator_seats": plan.entitlements.operator_seats,
                "messaging_channels_enabled": plan.entitlements.messaging_channels_enabled,
                "audit_retention": plan.entitlements.audit_retention,
                "feature_flags": list(plan.entitlements.feature_flags),
            },
            "readiness": {
                "ready": readiness_ok,
                "detail": readiness_label,
                "health_score": health_score,
                "risk_state": "healthy" if health_score >= 85 else "watch" if health_score >= 60 else "critical",
            },
            "operators": {
                "active_count": seats_used,
                "seats_used": seats_used,
                "seats_remaining": seats_remaining,
                "seat_overage": seat_overage,
                "active_operator_ids": [str(row.operator_id or "") for row in operators if str(row.operator_id or "").strip()],
                "active_operator_names": [str(row.display_name or row.operator_id or "") for row in operators if str(row.display_name or row.operator_id or "").strip()],
            },
            "commercial": {
                **dict(commercial_snapshot.get("commercial") or {}),
                "warnings": warnings,
                "blocked_actions": blocked_actions,
                "recommended_plan_key": recommended_plan.plan_key,
                "recommended_plan_label": recommended_plan.display_name,
            },
            "providers": {
                "provider_count": int(registry.get("provider_count") or 0),
                "lane_count": int(registry.get("lane_count") or 0),
                **provider_summary,
            },
            "queue_health": {
                **queue_health,
                "assignment_suggestions": [
                    {
                        "id": row.id,
                        "summary": row.summary,
                        "owner": row.owner,
                        "due_time": row.due_time,
                        "escalation_status": row.escalation_status,
                    }
                    for row in assignment_suggestions
                ],
            },
            "product_control": product_control,
            "support_verification": support_verification,
            "usage": usage_stats,
            "analytics": {
                "counts": analytics_counts,
                "activation_started_at": activation_started_at,
                "first_value_at": first_value_at,
                "first_value_event": first_value_event,
                "time_to_first_value_seconds": first_value_seconds,
                "memo_open_rate": memo_open_rate,
                "approval_coverage_rate": approval_coverage_rate,
                "approval_action_rate": approval_action_rate,
                "delivery_followup_closeout_count": delivery_followup_terminal_resolution_count,
                "delivery_followup_blocked_count": delivery_followup_blocked_count,
                "delivery_followup_resolution_rate": delivery_followup_resolution_rate,
                "delivery_followup_blocked_rate": delivery_followup_blocked_rate,
                "commitment_close_rate": commitment_close_rate,
                "correction_rate": correction_rate,
                "churn_risk": churn_risk,
                "success_summary": success_summary,
                "memo_loop": {
                    "enabled": bool(morning_memo.get("enabled")),
                    "cadence": str(morning_memo.get("cadence") or "daily_morning"),
                    "delivery_time_local": str(morning_memo.get("delivery_time_local") or "08:00"),
                    "timezone": str(morning_memo.get("timezone") or workspace.get("timezone") or "UTC"),
                    "recipient_email": str(morning_memo.get("resolved_recipient_email") or ""),
                    "scheduled_sent": scheduled_memo_sent_count,
                    "scheduled_failed": scheduled_memo_failed_count,
                    "scheduled_blocked": scheduled_memo_blocked_count,
                    "days_with_useful_loop": len(useful_loop_days),
                    "first_scheduled_sent_at": first_scheduled_memo_sent_at,
                    "last_scheduled_sent_at": last_scheduled_memo_sent_at,
                    "last_issue_at": latest_memo_issue_at,
                    "last_issue_kind": latest_memo_issue_kind,
                    "last_issue_reason": latest_memo_issue_reason,
                    "last_issue_fix_href": latest_memo_issue_fix_href,
                    "last_issue_fix_label": latest_memo_issue_fix_label,
                    "last_issue_fix_detail": latest_memo_issue_fix_detail,
                    "state": memo_loop_state,
                },
                "delivery": {
                    "registration_sent": registration_email_sent_count,
                    "registration_failed": registration_email_failed_count,
                    "invite_sent": invite_email_sent_count,
                    "invite_failed": invite_email_failed_count,
                    "digest_sent": digest_email_sent_count,
                    "digest_failed": digest_email_failed_count,
                },
                "access": {
                    "issued": access_session_issued_count,
                    "opened": access_session_opened_count,
                    "revoked": access_session_revoked_count,
                    "active": active_access_sessions,
                },
                "invitations": {
                    "pending": pending_invitations,
                    "accepted": accepted_invitations,
                    "revoked": revoked_invitations,
                },
                "sync": {
                    "google_sync_completed": google_sync_completed_count,
                    "pocket_sync_completed": pocket_sync_completed_count,
                    "office_signal_ingested": office_signal_ingested_count,
                    "google_connected": google_connected,
                    "google_account_email": google_account_email,
                    "google_token_status": google_token_status,
                    "google_last_refresh_at": google_last_refresh_at,
                    "google_reauth_required_reason": google_reauth_required_reason,
                    "google_sync_last_completed_at": google_sync_last_completed_at,
                    "google_sync_last_synced_total": int(google_sync_last_payload.get("synced_total") or 0),
                    "google_sync_last_deduplicated_total": int(google_sync_last_payload.get("deduplicated_total") or 0),
                    "google_sync_last_suppressed_total": int(google_sync_last_payload.get("suppressed_total") or 0),
                    "google_sync_last_gmail_total": int(google_sync_last_payload.get("gmail_total") or 0),
                    "google_sync_last_calendar_total": int(google_sync_last_payload.get("calendar_total") or 0),
                    "google_sync_age_seconds": google_sync_age_seconds,
                    "google_sync_freshness_state": google_sync_freshness_state,
                    "google_sync_accounts": [
                        dict(value)
                        for value in list(google_sync_last_payload.get("accounts") or [])
                        if isinstance(value, dict)
                    ],
                    "google_send_verification_last_at": google_send_verification_last_at,
                    "google_send_verification_last_state": google_send_verification_last_state,
                    "google_send_verification_last_sender_email": str(
                        google_send_verification_last_payload.get("sender_email") or ""
                    ).strip(),
                    "google_send_verification_last_recipient_email": str(
                        google_send_verification_last_payload.get("recipient_email") or ""
                    ).strip(),
                    "google_send_verification_last_binding_id": str(
                        google_send_verification_last_payload.get("binding_id") or ""
                    ).strip(),
                    "google_send_verification_last_error": str(
                        google_send_verification_last_payload.get("error") or ""
                    ).strip(),
                    "google_send_verification_accounts": [dict(value) for value in google_send_verification_accounts],
                    "google_account_change_last_at": google_account_change_last_at,
                    "google_account_change_last_state": google_account_change_last_state,
                    "google_account_change_last_binding_id": str(
                        google_account_change_last_payload.get("binding_id") or ""
                    ).strip(),
                    "google_account_change_last_email": str(
                        google_account_change_last_payload.get("google_email") or ""
                    ).strip(),
                    "google_account_change_accounts": [dict(value) for value in google_account_change_accounts],
                    "pocket_sync_last_completed_at": pocket_sync_last_completed_at,
                    "pocket_sync_last_synced_total": int(pocket_sync_last_payload.get("synced_total") or 0),
                    "pocket_sync_last_deduplicated_total": int(pocket_sync_last_payload.get("deduplicated_total") or 0),
                    "pocket_sync_last_suppressed_total": int(pocket_sync_last_payload.get("suppressed_total") or 0),
                    "pocket_sync_last_failed_total": int(pocket_sync_last_payload.get("failed_total") or 0),
                    "pocket_sync_last_staging_suppressed_total": int(pocket_sync_last_payload.get("staging_suppressed_total") or 0),
                    "pocket_sync_cursor_updated_at": str(pocket_sync_last_payload.get("cursor_updated_at") or "").strip(),
                    "pocket_sync_cursor_recording_id": str(pocket_sync_last_payload.get("cursor_recording_id") or "").strip(),
                    "pocket_sync_age_seconds": pocket_sync_age_seconds,
                    "pending_commitment_candidates": pending_commitment_candidates,
                    "covered_signal_candidates": covered_signal_candidates,
                },
                "reliability": {
                    "delivery_success_total": delivery_success_total,
                    "delivery_failure_total": delivery_failure_total,
                    "active_delivery_issue_total": active_delivery_issue_total,
                    "delivery_success_rate": delivery_success_rate,
                    "registration_delivery_success_rate": registration_delivery_success_rate,
                    "invite_delivery_success_rate": invite_delivery_success_rate,
                    "digest_delivery_success_rate": digest_delivery_success_rate,
                    "workspace_access_open_rate": workspace_access_open_rate,
                    "delivery_reliability_state": delivery_reliability_state,
                    "access_reliability_state": access_reliability_state,
                    "sync_reliability_state": sync_reliability_state,
                },
                "recent_events": [
                    {
                        "event_type": row.event_type,
                        "created_at": row.created_at,
                        "source_id": row.source_id,
                        "payload": dict(row.payload or {}),
                    }
                    for row in product_events[:12]
                ],
            },
        }

    def operator_center(self, *, principal_id: str, operator_id: str = "") -> dict[str, object]:
        snapshot = self.workspace_snapshot(principal_id=principal_id, operator_id=operator_id)
        diagnostics = self.workspace_diagnostics(principal_id=principal_id)
        queue_health = dict(diagnostics.get("queue_health") or {})
        providers = dict(diagnostics.get("providers") or {})
        commercial = dict(diagnostics.get("commercial") or {})
        readiness = dict(diagnostics.get("readiness") or {})
        analytics = dict(diagnostics.get("analytics") or {})
        usage = {str(key): int(value or 0) for key, value in dict(diagnostics.get("usage") or {}).items()}
        delivery = dict(analytics.get("delivery") or {})
        access = dict(analytics.get("access") or {})
        sync = dict(analytics.get("sync") or {})
        memo_loop = dict(analytics.get("memo_loop") or {})
        counts = {str(key): int(value or 0) for key, value in dict(analytics.get("counts") or {}).items()}
        blocked_actions = [str(value).replace("_", " ") for value in list(commercial.get("blocked_actions") or []) if str(value).strip()]
        warning_messages = [str(value) for value in list(commercial.get("warnings") or []) if str(value).strip()]
        active_memo_delivery_blocker = 1 if str(memo_loop.get("last_issue_reason") or "").strip() else 0
        active_delivery_issue_total = int(queue_health.get("delivery_errors") or 0) + active_memo_delivery_blocker
        clearable_queue_items = [row for row in snapshot.queue_items if not bool(row.requires_principal)]
        exception_total = (
            int(queue_health.get("sla_breaches") or 0)
            + active_delivery_issue_total
            + len(blocked_actions)
        )
        recent_events = [
            dict(row)
            for row in list(analytics.get("recent_events") or [])
            if str((row or {}).get("event_type") or "").strip()
            in {
                "registration_email_sent",
                "registration_email_failed",
                "workspace_invitation_email_sent",
                "workspace_invitation_email_failed",
                "workspace_access_session_issued",
                "workspace_access_session_opened",
                "workspace_access_session_revoked",
                "channel_digest_delivery_email_sent",
                "channel_digest_delivery_email_failed",
                "channel_digest_delivery_opened",
                "google_workspace_signal_sync_completed",
                "office_signal_ingested",
                "support_bundle_opened",
            }
        ][:12]
        assignment_suggestions = [dict(value) for value in list(queue_health.get("assignment_suggestions") or [])[:3]]
        lanes = [
            {
                "key": "sla",
                "label": "SLA risk",
                "state": "critical" if int(queue_health.get("sla_breaches") or 0) else "clear",
                "count": int(queue_health.get("sla_breaches") or 0),
                "detail": f"{int(queue_health.get('sla_breaches') or 0)} breaches · {int(queue_health.get('oldest_handoff_age_hours') or 0)}h oldest handoff",
                "href": "/admin/office",
            },
            {
                "key": "claims",
                "label": "Claimable work",
                "state": "watch" if int(queue_health.get("unclaimed_handoffs") or 0) else "clear",
                "count": int(queue_health.get("unclaimed_handoffs") or 0),
                "detail": f"{int(queue_health.get('suggested_claims') or 0)} suggested claims ready now",
                "href": "/admin/office",
            },
            {
                "key": "preclear",
                "label": "Clear before principal",
                "state": "watch" if clearable_queue_items else "clear",
                "count": len(clearable_queue_items),
                "detail": f"{len(clearable_queue_items)} queue items can be cleared inside the operator lane",
                "href": "/admin/office",
            },
            {
                "key": "principal",
                "label": "Waiting on principal",
                "state": "watch" if int(queue_health.get("waiting_on_principal") or 0) else "clear",
                "count": int(queue_health.get("waiting_on_principal") or 0),
                "detail": f"{int(queue_health.get('pending_approvals') or 0)} approvals · {int(counts.get('queue_opened') or 0)} queue opens",
                "href": "/app/queue",
            },
            {
                "key": "delivery",
                "label": "Delivery health",
                "state": "critical"
                if active_delivery_issue_total
                else "watch"
                if int(queue_health.get("retrying_delivery") or 0)
                else "clear",
                "count": int(queue_health.get("pending_delivery") or 0) + active_memo_delivery_blocker,
                "detail": (
                    f"{int(queue_health.get('retrying_delivery') or 0)} retrying · "
                    f"{int(queue_health.get('delivery_errors') or 0)} queue errors · "
                    f"{active_memo_delivery_blocker} active memo blockers"
                ),
                "href": "/app/settings/support",
            },
            {
                "key": "access",
                "label": "Workspace access",
                "state": "watch" if int(access.get("revoked") or 0) else ("clear" if int(access.get("active") or 0) else "watch"),
                "count": int(access.get("active") or 0),
                "detail": f"{int(access.get('active') or 0)} active sessions · {int(access.get('opened') or 0)} opens · {int(access.get('revoked') or 0)} revoked",
                "href": "/app/settings/support",
            },
            {
                "key": "exceptions",
                "label": "Exception queue",
                "state": "critical" if exception_total else "clear",
                "count": exception_total,
                "detail": (
                    f"{int(queue_health.get('sla_breaches') or 0)} SLA breaches · "
                    f"{active_delivery_issue_total} delivery issues · "
                    f"{len(blocked_actions)} blocked actions"
                ),
                "href": "/app/settings/support",
            },
            {
                "key": "sync",
                "label": "Google sync",
                "state": str(sync.get("google_sync_freshness_state") or ("watch" if int(sync.get("google_sync_completed") or 0) == 0 else "clear")),
                "count": int(sync.get("pending_commitment_candidates") or 0),
                "detail": (
                    f"{int(sync.get('google_sync_completed') or 0)} sync runs · "
                    f"{int(sync.get('office_signal_ingested') or 0)} ingested office signals · "
                    f"{int(sync.get('pending_commitment_candidates') or 0)} pending candidates"
                    f"{' · ' + str(int(sync.get('covered_signal_candidates') or 0)) + ' covered by drafts' if int(sync.get('covered_signal_candidates') or 0) else ''}"
                ),
                "href": "/app/settings/usage",
            },
        ]
        next_actions: list[dict[str, object]] = []
        operator_key = str(operator_id or "").strip()
        delivery_followup = next(
            (
                row
                for row in snapshot.handoffs
                if str(row.task_type or "").strip() == "delivery_followup"
                and str(row.resolution or "").strip() != "sent"
                and (operator_key and str(row.owner or "").strip() == operator_key)
            ),
            None,
        )
        if delivery_followup is None:
            delivery_followup = next(
                (
                    row
                    for row in snapshot.handoffs
                    if str(row.task_type or "").strip() == "delivery_followup"
                    and str(row.resolution or "").strip() != "sent"
                    and not str(row.owner or "").strip()
                ),
                None,
            )
        if delivery_followup is not None:
            delivery_actions = self._handoff_browser_actions(
                handoff=delivery_followup,
                operator_id=operator_key,
                return_to="/admin/office",
            )
            next_actions.append(
                {
                    "label": str(delivery_followup.summary or "Unblock approved send"),
                    "detail": " · ".join(
                        part
                        for part in (
                            delivery_followup.recipient_email,
                            str(delivery_followup.delivery_reason or "").replace("_", " "),
                            "Use the office lane to retry, reconnect Google, or record the manual send outcome.",
                        )
                        if str(part or "").strip()
                    ),
                    "href": f"/app/handoffs/{delivery_followup.id}",
                    "action_href": str(delivery_actions[0].get("href") or "") if delivery_actions else "",
                    "action_label": str(delivery_actions[0].get("label") or "") if delivery_actions else "",
                    "action_value": str(delivery_actions[0].get("value") or "") if delivery_actions else "",
                    "action_method": str(delivery_actions[0].get("method") or "") if delivery_actions else "",
                    "return_to": "/admin/office" if delivery_actions else "",
                    "secondary_action_href": str(delivery_actions[1].get("href") or "") if len(delivery_actions) > 1 else "",
                    "secondary_action_label": str(delivery_actions[1].get("label") or "") if len(delivery_actions) > 1 else "",
                    "secondary_action_value": str(delivery_actions[1].get("value") or "") if len(delivery_actions) > 1 else "",
                    "secondary_action_method": str(delivery_actions[1].get("method") or "") if len(delivery_actions) > 1 else "",
                    "secondary_return_to": "/admin/office" if len(delivery_actions) > 1 else "",
                    "tertiary_action_href": str(delivery_actions[2].get("href") or "") if len(delivery_actions) > 2 else "",
                    "tertiary_action_label": str(delivery_actions[2].get("label") or "") if len(delivery_actions) > 2 else "",
                    "tertiary_action_value": str(delivery_actions[2].get("value") or "") if len(delivery_actions) > 2 else "",
                    "tertiary_action_method": str(delivery_actions[2].get("method") or "") if len(delivery_actions) > 2 else "",
                    "tertiary_return_to": "/admin/office" if len(delivery_actions) > 2 else "",
                    "quaternary_action_href": str(delivery_actions[3].get("href") or "") if len(delivery_actions) > 3 else "",
                    "quaternary_action_label": str(delivery_actions[3].get("label") or "") if len(delivery_actions) > 3 else "",
                    "quaternary_action_value": str(delivery_actions[3].get("value") or "") if len(delivery_actions) > 3 else "",
                    "quaternary_action_method": str(delivery_actions[3].get("method") or "") if len(delivery_actions) > 3 else "",
                    "quaternary_return_to": "/admin/office" if len(delivery_actions) > 3 else "",
                }
            )
        if str(memo_loop.get("last_issue_reason") or "").strip():
            next_actions.append(
                {
                    "label": "Fix memo delivery blocker",
                    "detail": " ".join(
                        part
                        for part in (
                            str(memo_loop.get("last_issue_reason") or "").strip().rstrip(".") + ".",
                            str(memo_loop.get("last_issue_fix_detail") or "").strip(),
                        )
                        if str(part or "").strip()
                    ).strip(),
                    "href": str(memo_loop.get("last_issue_fix_href") or "/app/settings/outcomes"),
                    "action_href": str(memo_loop.get("last_issue_fix_href") or ""),
                    "action_label": str(memo_loop.get("last_issue_fix_label") or ""),
                    "action_method": "get" if str(memo_loop.get("last_issue_fix_href") or "").strip() else "",
                    "return_to": str(memo_loop.get("last_issue_fix_href") or "") if str(memo_loop.get("last_issue_fix_href") or "").strip() else "",
                }
            )
        for item in assignment_suggestions:
            handoff_id = str(item.get("id") or "").strip()
            next_actions.append(
                {
                    "label": str(item.get("summary") or handoff_id or "Claim handoff"),
                    "detail": "Claim the most urgent unassigned handoff before it ages into a miss.",
                    "href": f"/app/handoffs/{handoff_id}" if handoff_id else "/admin/office",
                    "action_href": f"/app/actions/handoffs/{handoff_id}/assign" if handoff_id else "",
                    "action_label": "Claim" if handoff_id else "",
                    "action_value": "assign" if handoff_id else "",
                    "action_method": "post" if handoff_id else "",
                    "return_to": "/admin/office" if handoff_id else "",
                }
            )
        if int(queue_health.get("retrying_delivery") or 0) or active_delivery_issue_total:
            next_actions.append(
                {
                    "label": "Open support diagnostics",
                    "detail": "Delivery backlog or failures need support posture before the next memo cycle.",
                    "href": "/app/settings/support",
                    "action_href": "/app/api/diagnostics/export",
                    "action_label": "Open bundle",
                    "action_method": "get",
                    "return_to": "/app/settings/support",
                }
            )
        if exception_total:
            next_actions.append(
                {
                    "label": "Clear exception queue",
                    "detail": (
                        "; ".join(
                            part
                            for part in (
                                f"{int(queue_health.get('sla_breaches') or 0)} SLA breaches" if int(queue_health.get("sla_breaches") or 0) else "",
                                f"{active_delivery_issue_total} delivery issues"
                                if active_delivery_issue_total
                                else "",
                                blocked_actions[0] if blocked_actions else "",
                                warning_messages[0] if warning_messages else "",
                            )
                            if part
                        )
                        or "The operator lane has active exceptions."
                    ),
                    "href": "/app/settings/support",
                }
            )
        if clearable_queue_items:
            clearable = clearable_queue_items[0]
            clearable_href = ""
            clearable_action_href = ""
            clearable_action_label = ""
            clearable_action_value = ""
            clearable_action_method = ""
            if clearable.id.startswith("approval:"):
                clearable_href = "/app/queue"
                clearable_action_href = f"/app/actions/drafts/{clearable.id}/approve"
                clearable_action_label = "Approve"
                clearable_action_method = "post"
            elif clearable.id.startswith(("commitment:", "follow_up:")):
                clearable_href = "/app/commitments"
                clearable_action_href = f"/app/actions/queue/{clearable.id}/resolve"
                clearable_action_label = "Close"
                clearable_action_value = "close"
                clearable_action_method = "post"
            elif clearable.id.startswith(("decision:", "deadline:")):
                clearable_href = "/app/queue"
                clearable_action_href = f"/app/actions/queue/{clearable.id}/resolve"
                clearable_action_label = "Resolve"
                clearable_action_value = "resolve"
                clearable_action_method = "post"
            next_actions.append(
                {
                    "label": str(clearable.title or "Clear queue item"),
                    "detail": "Resolve this inside the operator lane before it becomes principal noise.",
                    "href": clearable_href or "/admin/office",
                    "action_href": clearable_action_href,
                    "action_label": clearable_action_label,
                    "action_value": clearable_action_value,
                    "action_method": clearable_action_method,
                    "return_to": "/admin/office" if clearable_action_href else "",
                }
            )
        if not bool(sync.get("google_connected")):
            next_actions.append(
                {
                    "label": "Connect Google",
                    "detail": "Workspace sync cannot run until a Google workspace account is connected.",
                    "href": "/app/settings/google",
                    "action_href": "/app/actions/google/connect?return_to=/app/settings/google",
                    "action_label": "Connect now",
                    "action_method": "get",
                    "return_to": "/app/settings/google",
                }
            )
        elif str(sync.get("google_token_status") or "") not in {"active", "unknown"}:
            next_actions.append(
                {
                    "label": "Reconnect Google",
                    "detail": str(sync.get("google_reauth_required_reason") or "Google access needs attention before the next sync."),
                    "href": "/app/settings/google",
                    "action_href": "/app/actions/google/connect?return_to=/app/settings/google",
                    "action_label": "Reconnect now",
                    "action_method": "get",
                    "return_to": "/app/settings/google",
                }
            )
        elif str(sync.get("google_sync_freshness_state") or "") != "clear":
            next_actions.append(
                {
                    "label": "Run Google sync",
                    "detail": (
                        f"Last sync at {str(sync.get('google_sync_last_completed_at') or 'not yet completed')}."
                        if str(sync.get("google_sync_last_completed_at") or "").strip()
                        else "This workspace has not completed a Google signal sync yet."
                    ),
                    "href": "/app/settings/google",
                    "action_href": "/app/api/signals/google/sync",
                    "action_label": "Sync now",
                    "action_method": "post",
                    "return_to": "/app/settings/google",
                }
            )
        if int(sync.get("pending_commitment_candidates") or 0):
            next_actions.append(
                {
                    "label": "Review staged commitments",
                    "detail": f"{int(sync.get('pending_commitment_candidates') or 0)} pending commitment candidates need review after sync.",
                    "href": "/app/queue",
                }
            )
        if int(queue_health.get("waiting_on_principal") or 0):
            next_actions.append(
                {
                    "label": "Clear principal approvals",
                    "detail": "Executive-gated work is still blocking the operator lane.",
                    "href": "/app/queue",
                }
            )
        trimmed_next_actions = next_actions[:6]
        return {
            "generated_at": _now_iso(),
            "workspace": dict(diagnostics.get("workspace") or {}),
            "operators": dict(diagnostics.get("operators") or {}),
            "queue_health": queue_health,
            "providers": providers,
            "readiness": readiness,
            "delivery": delivery,
            "access": access,
            "sync": sync,
            "usage": usage,
            "lanes": lanes,
            "next_actions": trimmed_next_actions,
            "recent_runtime": recent_events,
            "snapshot": {
                "assigned_handoffs": len([row for row in snapshot.handoffs if str(row.owner or "").strip() == str(operator_id or "").strip()]) if str(operator_id or "").strip() else 0,
                "completed_handoffs": len(snapshot.completed_handoffs),
                "clearable_queue_items": len(clearable_queue_items),
                "exception_count": exception_total,
                "open_commitments": len(snapshot.commitments),
                "pending_drafts": len(snapshot.drafts),
                "open_decisions": len(snapshot.decisions),
                "people_in_play": len(snapshot.people),
            },
            "operator_memo_grounding": self._operator_memo_grounding_pack(
                diagnostics=diagnostics,
                lanes=lanes,
                next_actions=trimmed_next_actions,
            ),
        }

    def workspace_support_bundle(self, *, principal_id: str) -> dict[str, object]:
        diagnostics = self.workspace_diagnostics(principal_id=principal_id)
        queue_health = dict(diagnostics.get("queue_health") or {})
        approvals = self._container.orchestrator.list_pending_approvals_for_principal(principal_id=principal_id, limit=25)
        approval_history = self._container.orchestrator.list_approval_history_for_principal(principal_id=principal_id, limit=25)
        human_tasks = self._container.orchestrator.list_human_tasks(principal_id=principal_id, status=None, limit=25)
        provider_registry = self._container.provider_registry.registry_read_model(principal_id=principal_id)
        pending_delivery = self._container.channel_runtime.list_pending_delivery(limit=25, principal_id=principal_id)
        return {
            "workspace": diagnostics["workspace"],
            "selected_channels": diagnostics["selected_channels"],
            "plan": diagnostics["plan"],
            "billing": diagnostics["billing"],
            "entitlements": diagnostics["entitlements"],
            "commercial": diagnostics["commercial"],
            "readiness": diagnostics["readiness"],
            "product_control": diagnostics["product_control"],
            "support_verification": diagnostics["support_verification"],
            "usage": diagnostics["usage"],
            "analytics": diagnostics["analytics"],
            "approvals": {
                "pending": [
                    {
                        "approval_id": row.approval_id,
                        "reason": row.reason,
                        "status": row.status,
                        "expires_at": row.expires_at,
                        "session_id": row.session_id,
                    }
                    for row in approvals
                ],
                "recent_decisions": [
                    {
                        "decision_id": row.decision_id,
                        "approval_id": row.approval_id,
                        "decision": row.decision,
                        "reason": row.reason,
                        "created_at": row.created_at,
                    }
                    for row in approval_history
                ],
            },
            "human_tasks": [
                {
                    "human_task_id": row.human_task_id,
                    "brief": row.brief,
                    "status": row.status,
                    "assignment_state": row.assignment_state,
                    "assigned_operator_id": row.assigned_operator_id,
                    "priority": row.priority,
                    "sla_due_at": row.sla_due_at,
                }
                for row in human_tasks
            ],
            "providers": {**provider_registry, **dict(diagnostics.get("providers") or {})},
            "queue_health": queue_health,
            "assignment_suggestions": list(queue_health.get("assignment_suggestions") or []),
            "pending_delivery": [
                {
                    "delivery_id": row.delivery_id,
                    "channel": row.channel,
                    "recipient": row.recipient,
                    "status": row.status,
                    "attempt_count": row.attempt_count,
                    "last_error": row.last_error,
                }
                for row in pending_delivery
            ],
            "recent_events": list(self.list_office_events(principal_id=principal_id, limit=20)),
            "support_assistant_grounding": self._support_assistant_grounding_pack(diagnostics=diagnostics),
        }

    def _handoff_browser_actions(
        self,
        *,
        handoff: HandoffNote,
        operator_id: str,
        return_to: str,
    ) -> tuple[dict[str, str], ...]:
        actions: list[dict[str, str]] = []
        for option in handoff_action_options(handoff, operator_id=operator_id, return_to=return_to)[:4]:
            route = str(option.get("route") or "").strip()
            href = str(option.get("href") or "").strip()
            action_href = href or (f"/app/actions/handoffs/{handoff.id}/{route}" if route else "")
            if not action_href:
                continue
            actions.append(
                {
                    "href": action_href,
                    "label": str(option.get("label") or "").strip(),
                    "value": str(option.get("value") or "").strip(),
                    "method": str(option.get("method") or ("get" if href else "post")).strip().lower() or "post",
                }
            )
        return tuple(actions)

    def _handoff_channel_action_reason(self, *, action: str) -> str:
        normalized = str(action or "").strip().lower()
        if normalized in {"assign", "claim"}:
            return "Claimed from operator digest."
        if normalized == "retry_send":
            return "Retried from operator digest."
        if normalized == "recreate":
            return "Recreated from operator digest."
        if normalized == "sent":
            return "Marked sent from operator digest."
        if normalized == "failed":
            return "Marked unable to send from operator digest."
        if normalized == "reauth_needed":
            return "Marked reauth required from operator digest."
        if normalized == "waiting_on_principal":
            return "Marked waiting on principal from operator digest."
        return "Resolved from operator digest."

    def _handoff_channel_actions(
        self,
        *,
        principal_id: str,
        handoff: HandoffNote,
        operator_id: str,
        return_to: str,
    ) -> tuple[dict[str, str], ...]:
        resolved_operator_id = str(operator_id or handoff.owner).strip()
        actions: list[dict[str, str]] = []
        for option in handoff_action_options(handoff, operator_id=operator_id, return_to=return_to)[:4]:
            direct_href = str(option.get("href") or "").strip()
            channel_action = str(option.get("channel_action") or "").strip()
            if direct_href:
                action_href = direct_href
            elif channel_action:
                action_href = self.channel_action_href(
                    principal_id=principal_id,
                    object_kind="handoff",
                    object_ref=handoff.id,
                    action=channel_action,
                    return_to=return_to,
                    operator_id=resolved_operator_id,
                    reason=self._handoff_channel_action_reason(action=channel_action),
                )
            else:
                continue
            actions.append(
                {
                    "href": action_href,
                    "label": str(option.get("label") or "").strip(),
                    "method": "get",
                }
            )
        return tuple(actions)

    def channel_loop_pack(self, *, principal_id: str, operator_id: str = "") -> dict[str, object]:
        snapshot = self.workspace_snapshot(principal_id=principal_id, operator_id=operator_id)
        operator_key = str(operator_id or "").strip()
        diagnostics = self.workspace_diagnostics(principal_id=principal_id)
        memo_loop = dict(dict(diagnostics.get("analytics") or {}).get("memo_loop") or {})
        items: list[dict[str, str]] = []
        memo_blocker_item = _memo_issue_channel_item(memo_loop=memo_loop)
        if memo_blocker_item is not None:
            items.append(dict(memo_blocker_item))
        if snapshot.brief_items:
            memo = snapshot.brief_items[0]
            items.append(
                {
                    "title": "Morning memo",
                    "detail": memo.why_now or memo.summary or "Open the memo before the day fragments.",
                    "tag": "Memo",
                    "href": "/app/today",
                    "action_href": "/app/today",
                    "action_label": "Open memo",
                    "action_method": "get",
                }
            )
        if snapshot.drafts:
            draft = snapshot.drafts[0]
            items.append(
                {
                    "title": f"Approve draft for {draft.recipient_summary or 'next reply'}",
                    "detail": " · ".join(
                        part
                        for part in (
                            draft.intent.title(),
                            draft.send_channel,
                            draft.approval_status,
                        )
                        if part
                    )
                    or "Draft is waiting for approval.",
                    "tag": "Draft",
                    "href": "/app/queue",
                    "action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="draft",
                        object_ref=draft.id,
                        action="approve",
                        return_to="/app/channel-loop",
                        operator_id=operator_key,
                        reason="Approved from inline loop.",
                    ),
                    "action_label": "Approve now",
                    "action_method": "get",
                    "secondary_action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="draft",
                        object_ref=draft.id,
                        action="reject",
                        return_to="/app/channel-loop",
                        operator_id=operator_key,
                        reason="Rejected from inline loop.",
                    ),
                    "secondary_action_label": "Reject",
                    "secondary_action_method": "get",
                }
            )
        if snapshot.commitments:
            commitment = snapshot.commitments[0]
            items.append(
                {
                    "title": commitment.statement,
                    "detail": " · ".join(
                        part
                        for part in (
                            commitment.counterparty,
                            f"Due {commitment.due_at[:10]}" if commitment.due_at else "",
                            commitment.risk_level.replace("_", " ").title(),
                        )
                        if part
                    )
                    or "Commitment still needs a visible next action.",
                    "tag": "Commitment",
                    "href": f"/app/commitment-items/{commitment.id}",
                    "action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="queue",
                        object_ref=commitment.id,
                        action="close",
                        return_to="/app/channel-loop",
                        operator_id=operator_key,
                        reason="Closed from inline loop.",
                    ),
                    "action_label": "Close",
                    "action_method": "get",
                    "secondary_action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="queue",
                        object_ref=commitment.id,
                        action="defer",
                        return_to="/app/channel-loop",
                        operator_id=operator_key,
                        reason="Deferred from inline loop.",
                    ),
                    "secondary_action_label": "Defer",
                    "secondary_action_method": "get",
                }
            )
        if snapshot.handoffs:
            preferred_handoff = next((row for row in snapshot.handoffs if operator_key and row.owner == operator_key), snapshot.handoffs[0])
            actions = self._handoff_channel_actions(
                principal_id=principal_id,
                handoff=preferred_handoff,
                operator_id=operator_key,
                return_to="/app/channel-loop",
            )
            items.append(
                {
                    "title": preferred_handoff.summary,
                    "detail": " · ".join(
                        part
                        for part in (
                            preferred_handoff.owner,
                            f"Due {preferred_handoff.due_time[:10]}" if preferred_handoff.due_time else "",
                            preferred_handoff.escalation_status.replace("_", " ").title(),
                        )
                        if part
                    )
                    or "Handoff is waiting in the operator lane.",
                    "tag": "Handoff",
                    "href": f"/app/handoffs/{preferred_handoff.id}",
                    "action_href": str(actions[0].get("href") or "") if actions else "",
                    "action_label": str(actions[0].get("label") or "Claim") if actions else "Claim",
                    "action_method": str(actions[0].get("method") or "get") if actions else "get",
                    "secondary_action_href": str(actions[1].get("href") or "") if len(actions) > 1 else "",
                    "secondary_action_label": str(actions[1].get("label") or "") if len(actions) > 1 else "",
                    "secondary_action_method": str(actions[1].get("method") or "get") if len(actions) > 1 else "",
                    "tertiary_action_href": str(actions[2].get("href") or "") if len(actions) > 2 else "",
                    "tertiary_action_label": str(actions[2].get("label") or "") if len(actions) > 2 else "",
                    "tertiary_action_method": str(actions[2].get("method") or "get") if len(actions) > 2 else "",
                    "quaternary_action_href": str(actions[3].get("href") or "") if len(actions) > 3 else "",
                    "quaternary_action_label": str(actions[3].get("label") or "") if len(actions) > 3 else "",
                    "quaternary_action_method": str(actions[3].get("method") or "get") if len(actions) > 3 else "",
                }
            )
        if snapshot.decisions:
            decision = snapshot.decisions[0]
            items.append(
                {
                    "title": decision.title,
                    "detail": " · ".join(
                        part
                        for part in (
                            decision.sla_status.replace("_", " ").title(),
                            decision.impact_summary or decision.summary,
                        )
                        if part
                    )
                    or "Decision remains open.",
                    "tag": "Decision",
                    "href": f"/app/decisions/{decision.id}",
                    "action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="decision",
                        object_ref=decision.id,
                        action="resolve",
                        return_to="/app/channel-loop",
                        operator_id=operator_key,
                        reason="Resolved from inline loop.",
                    ),
                    "action_label": "Resolve now",
                    "action_method": "get",
                    "secondary_action_href": f"/app/decisions/{decision.id}",
                    "secondary_action_label": "Review",
                    "secondary_action_method": "get",
                }
            )
        digests = self._channel_digests(
            snapshot=snapshot,
            operator_key=operator_key,
            principal_id=principal_id,
            diagnostics=diagnostics,
            memo_loop=memo_loop,
        )
        return {
            "headline": "Inline loop",
            "summary": "Use a compact, mobile-safe surface for the memo, approvals, commitments, handoffs, and the next decision that still matters.",
            "items": items,
            "stats": {
                "memo_items": int(snapshot.stats_json.get("brief_items", 0) or 0),
                "pending_drafts": len(snapshot.drafts),
                "open_commitments": len(snapshot.commitments),
                "open_handoffs": len(snapshot.handoffs),
                "open_decisions": len(snapshot.decisions),
            },
            "digests": digests,
        }

    def channel_digest_pack(self, *, principal_id: str, digest_key: str, operator_id: str = "") -> dict[str, object] | None:
        pack = self.channel_loop_pack(principal_id=principal_id, operator_id=operator_id)
        wanted = str(digest_key or "").strip().lower()
        for row in list(pack.get("digests") or []):
            if str(row.get("key") or "").strip().lower() == wanted:
                return dict(row)
        return None

    def channel_digest_text(
        self,
        *,
        principal_id: str,
        digest_key: str,
        operator_id: str = "",
        base_url: str = "",
    ) -> str:
        digest = self.channel_digest_pack(principal_id=principal_id, digest_key=digest_key, operator_id=operator_id)
        if digest is None:
            return ""
        normalized_base = str(base_url or "").strip()

        def absolute(href: str) -> str:
            value = str(href or "").strip()
            if not value:
                return ""
            if "://" in value:
                return value
            if normalized_base:
                return urllib.parse.urljoin(normalized_base, value)
            return value

        lines: list[str] = [
            str(digest.get("headline") or "Channel digest").strip(),
            str(digest.get("summary") or "").strip(),
            str(digest.get("preview_text") or "").strip(),
            "",
        ]
        for index, item in enumerate(list(digest.get("items") or []), start=1):
            title = str(item.get("title") or f"Item {index}").strip()
            tag = str(item.get("tag") or "").strip()
            detail = str(item.get("detail") or "").strip()
            action_label = str(item.get("action_label") or "").strip()
            action_href = absolute(str(item.get("action_href") or "").strip())
            secondary_label = str(item.get("secondary_action_label") or "").strip()
            secondary_href = absolute(str(item.get("secondary_action_href") or "").strip())
            tertiary_label = str(item.get("tertiary_action_label") or "").strip()
            tertiary_href = absolute(str(item.get("tertiary_action_href") or "").strip())
            quaternary_label = str(item.get("quaternary_action_label") or "").strip()
            quaternary_href = absolute(str(item.get("quaternary_action_href") or "").strip())
            href = absolute(str(item.get("href") or "").strip())
            wrote_action = False
            header = f"{index}. [{tag}] {title}" if tag else f"{index}. {title}"
            lines.append(header)
            if detail:
                lines.append(f"   {detail}")
            if action_label and action_href:
                lines.append(f"   {action_label}: {action_href}")
                wrote_action = True
            if secondary_label and secondary_href:
                lines.append(f"   {secondary_label}: {secondary_href}")
                wrote_action = True
            if tertiary_label and tertiary_href:
                lines.append(f"   {tertiary_label}: {tertiary_href}")
                wrote_action = True
            if quaternary_label and quaternary_href:
                lines.append(f"   {quaternary_label}: {quaternary_href}")
                wrote_action = True
            if not wrote_action and href:
                lines.append(f"   Open: {href}")
            lines.append("")
        return "\n".join(line for line in lines if line or (lines and line == ""))

    def issue_channel_digest_delivery(
        self,
        *,
        principal_id: str,
        digest_key: str,
        recipient_email: str,
        role: str,
        display_name: str = "",
        operator_id: str = "",
        delivery_channel: str = "email",
        expires_in_hours: int = 72,
        base_url: str = "",
    ) -> dict[str, object] | None:
        normalized_digest = str(digest_key or "").strip().lower()
        normalized_email = str(recipient_email or "").strip().lower()
        normalized_role = str(role or "principal").strip().lower() or "principal"
        resolved_operator_id = str(operator_id or "").strip() if normalized_role == "operator" else ""
        if normalized_digest == "memo":
            sync_status = self.google_signal_sync_status(principal_id=principal_id)
            if bool(sync_status.get("connected")) and str(sync_status.get("freshness_state") or "").strip().lower() != "clear":
                try:
                    self.sync_google_workspace_signals(
                        principal_id=principal_id,
                        actor="channel_digest:memo",
                        email_limit=5,
                        calendar_limit=5,
                    )
                    self._record_product_event(
                        principal_id=principal_id,
                        event_type="channel_digest_signal_refresh_completed",
                        payload={
                            "digest_key": normalized_digest,
                            "freshness_before": str(sync_status.get("freshness_state") or "watch"),
                        },
                        source_id=normalized_digest,
                    )
                except RuntimeError as exc:
                    self._record_product_event(
                        principal_id=principal_id,
                        event_type="channel_digest_signal_refresh_failed",
                        payload={
                            "digest_key": normalized_digest,
                            "freshness_before": str(sync_status.get("freshness_state") or "watch"),
                            "error": str(exc),
                        },
                        source_id=normalized_digest,
                    )
        digest = self.channel_digest_pack(
            principal_id=principal_id,
            digest_key=normalized_digest,
            operator_id=resolved_operator_id,
        )
        if digest is None:
            return None
        access_session = self.issue_workspace_access_session(
            principal_id=principal_id,
            email=normalized_email,
            role=normalized_role,
            display_name=str(display_name or "").strip(),
            operator_id=resolved_operator_id,
            source_kind="channel_digest_delivery",
            expires_in_hours=expires_in_hours,
        )
        delivery_id = f"digest_{uuid4().hex[:10]}"
        token_payload = {
            "token_kind": "channel_digest_delivery",
            "delivery_id": delivery_id,
            "principal_id": principal_id,
            "digest_key": normalized_digest,
            "recipient_email": normalized_email,
            "role": normalized_role,
            "display_name": str(display_name or "").strip(),
            "operator_id": str(access_session.get("operator_id") or "").strip(),
            "delivery_channel": str(delivery_channel or "email").strip().lower() or "email",
            "access_token": str(access_session.get("access_token") or "").strip(),
            "expires_at": str(access_session.get("expires_at") or "").strip(),
        }
        delivery_token = _sign_channel_payload(secret=self._workspace_access_secret(), payload=token_payload)
        delivery_url = f"/channel-loop/deliveries/{delivery_token}"
        absolute_delivery_url = urllib.parse.urljoin(str(base_url or "").strip(), delivery_url) if str(base_url or "").strip() else delivery_url
        plain_text = "\n".join(
            part
            for part in (
                f"Open digest: {absolute_delivery_url}",
                self.channel_digest_text(
                    principal_id=principal_id,
                    digest_key=normalized_digest,
                    operator_id=str(access_session.get("operator_id") or "").strip(),
                    base_url=base_url,
                ),
            )
            if part
        )
        payload = {
            "delivery_id": delivery_id,
            "digest_key": normalized_digest,
            "principal_id": principal_id,
            "recipient_email": normalized_email,
            "role": normalized_role,
            "display_name": str(display_name or "").strip(),
            "operator_id": str(access_session.get("operator_id") or "").strip(),
            "delivery_channel": str(token_payload["delivery_channel"]),
            "expires_at": str(token_payload["expires_at"]),
            "delivery_token": delivery_token,
            "delivery_url": delivery_url,
            "open_url": f"/app/channel-loop/{normalized_digest}",
            "access_session_id": str(access_session.get("session_id") or "").strip(),
            "access_token": str(access_session.get("access_token") or "").strip(),
            "access_url": str(access_session.get("access_url") or "").strip(),
            "default_target": str(access_session.get("default_target") or "/app/today"),
            "headline": str(digest.get("headline") or "Channel digest"),
            "preview_text": str(digest.get("preview_text") or ""),
            "plain_text": plain_text,
            "email_delivery_status": "not_requested" if str(token_payload["delivery_channel"]) != "email" else ("not_configured" if not email_delivery_enabled() else ""),
            "email_delivery_error": "",
            "email_message_id": "",
            "email_provider": "",
        }
        if str(token_payload["delivery_channel"]) == "email" and email_delivery_enabled():
            try:
                receipt = send_channel_digest_email(
                    recipient_email=normalized_email,
                    digest_key=normalized_digest,
                    headline=str(payload.get("headline") or "Channel digest"),
                    preview_text=str(payload.get("preview_text") or ""),
                    delivery_url=absolute_delivery_url,
                    plain_text=plain_text,
                    expires_at=str(payload.get("expires_at") or ""),
                )
                payload["email_delivery_status"] = "sent"
                payload["email_message_id"] = receipt.message_id
                payload["email_provider"] = receipt.provider
                self._record_product_event(
                    principal_id=principal_id,
                    event_type="channel_digest_delivery_email_sent",
                    payload={
                        "delivery_id": delivery_id,
                        "digest_key": normalized_digest,
                        "recipient_email": normalized_email,
                        "provider": receipt.provider,
                    },
                    source_id=delivery_id,
                    dedupe_key=f"{principal_id}|{delivery_id}|delivery-email-sent",
                )
            except RuntimeError as exc:
                payload["email_delivery_status"] = "failed"
                payload["email_delivery_error"] = str(exc)
                self._record_product_event(
                    principal_id=principal_id,
                    event_type="channel_digest_delivery_email_failed",
                    payload={
                        "delivery_id": delivery_id,
                        "digest_key": normalized_digest,
                        "recipient_email": normalized_email,
                        "error": str(exc),
                    },
                    source_id=delivery_id,
                    dedupe_key=f"{principal_id}|{delivery_id}|delivery-email-failed",
                )
        self._record_product_event(
            principal_id=principal_id,
            event_type="channel_digest_delivery_issued",
            payload={
                "delivery_id": delivery_id,
                "digest_key": normalized_digest,
                "recipient_email": normalized_email,
                "role": normalized_role,
                "operator_id": str(payload.get("operator_id") or ""),
                "delivery_channel": str(payload.get("delivery_channel") or ""),
                "delivery_url": delivery_url,
                "open_url": str(payload.get("open_url") or ""),
                "access_session_id": str(payload.get("access_session_id") or ""),
                "expires_at": str(payload.get("expires_at") or ""),
                "email_delivery_status": str(payload.get("email_delivery_status") or ""),
                "email_message_id": str(payload.get("email_message_id") or ""),
                "email_provider": str(payload.get("email_provider") or ""),
            },
            source_id=delivery_id,
            dedupe_key=f"{principal_id}|{delivery_id}",
        )
        return payload

    def preview_channel_digest_delivery(self, *, token: str, base_url: str = "") -> dict[str, object] | None:
        payload = _verify_channel_payload(secret=self._workspace_access_secret(), token=token)
        if payload is None or str(payload.get("token_kind") or "").strip() != "channel_digest_delivery":
            return None
        principal_id = str(payload.get("principal_id") or "").strip()
        digest_key = str(payload.get("digest_key") or "").strip().lower()
        access_token = str(payload.get("access_token") or "").strip()
        access_session = self.preview_workspace_access_session(token=access_token)
        if not principal_id or not digest_key or access_session is None:
            return None
        digest = self.channel_digest_pack(
            principal_id=principal_id,
            digest_key=digest_key,
            operator_id=str(access_session.get("operator_id") or "").strip(),
        )
        if digest is None:
            return None
        delivery_id = str(payload.get("delivery_id") or "").strip()
        self._record_product_event(
            principal_id=principal_id,
            event_type="channel_digest_delivery_opened",
            payload={
                "delivery_id": delivery_id,
                "digest_key": digest_key,
                "recipient_email": str(payload.get("recipient_email") or "").strip().lower(),
                "role": str(payload.get("role") or "principal").strip().lower() or "principal",
                "open_url": f"/app/channel-loop/{digest_key}",
            },
            source_id=delivery_id,
            dedupe_key=f"{principal_id}|{delivery_id}|opened",
        )
        if digest_key == "memo":
            self.record_surface_event(
                principal_id=principal_id,
                event_type="memo_opened",
                surface="channel_digest_delivery",
                actor=str(payload.get("recipient_email") or payload.get("role") or "delivery").strip(),
            )
        return {
            "delivery_id": delivery_id,
            "digest_key": digest_key,
            "principal_id": principal_id,
            "recipient_email": str(payload.get("recipient_email") or "").strip().lower(),
            "role": str(payload.get("role") or "principal").strip().lower() or "principal",
            "display_name": str(payload.get("display_name") or "").strip(),
            "operator_id": str(access_session.get("operator_id") or "").strip(),
            "delivery_channel": str(payload.get("delivery_channel") or "email").strip().lower() or "email",
            "expires_at": str(payload.get("expires_at") or "").strip(),
            "delivery_token": str(token or "").strip(),
            "delivery_url": f"/channel-loop/deliveries/{token}",
            "open_url": f"/app/channel-loop/{digest_key}",
            "access_token": access_token,
            "access_url": str(access_session.get("access_url") or "").strip(),
            "default_target": str(access_session.get("default_target") or "/app/today"),
            "headline": str(digest.get("headline") or "Channel digest"),
            "preview_text": str(digest.get("preview_text") or ""),
            "plain_text": self.channel_digest_text(
                principal_id=principal_id,
                digest_key=digest_key,
                operator_id=str(access_session.get("operator_id") or "").strip(),
                base_url=base_url,
            ),
        }

    def _channel_digests(
        self,
        *,
        snapshot: ProductSnapshot,
        operator_key: str,
        principal_id: str,
        diagnostics: dict[str, object] | None = None,
        memo_loop: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        diagnostics_payload = dict(diagnostics or {})
        at_risk_commitments = [
            item
            for item in snapshot.commitments
            if _is_past_due(item.due_at) or item.risk_level in {"high", "critical", "due_now"}
        ]
        support_verification = self._support_fix_verification_projection(principal_id=principal_id)
        support_grounding = self._support_assistant_grounding_pack(diagnostics=diagnostics_payload) if diagnostics_payload else {}
        operator_grounding = self._operator_memo_grounding_pack(diagnostics=diagnostics_payload) if diagnostics_payload else {}
        resolved_memo_loop = dict(memo_loop or {})
        memo_blocker_item = _memo_issue_channel_item(memo_loop=resolved_memo_loop)
        open_decisions = [item for item in snapshot.decisions if item.status != "decided"]
        principal_queue = [item for item in snapshot.queue_items if item.requires_principal]
        review_candidates = [
            item
            for item in snapshot.commitment_candidates
            if str(item.status or "").strip().lower() in {"pending", "duplicate"}
        ]
        hidden_candidate_ids = self._pending_signal_draft_candidate_ids(principal_id=principal_id)
        visible_review_candidates = [
            item for item in review_candidates if str(item.candidate_id or "").strip() not in hidden_candidate_ids
        ]
        assigned_handoffs = [item for item in snapshot.handoffs if operator_key and item.owner == operator_key]
        unclaimed_handoffs = [item for item in snapshot.handoffs if not str(item.owner or "").strip()]
        visible_handoffs = assigned_handoffs[:1] + unclaimed_handoffs[:2]
        if not visible_handoffs:
            visible_handoffs = list(snapshot.handoffs[:2])

        def first_get_action(pack: dict[str, object], *, fallback_label: str, fallback_href: str) -> tuple[str, str, str]:
            for action in list(pack.get("actions") or []):
                if not isinstance(action, dict):
                    continue
                href = str(action.get("href") or "").strip()
                method = str(action.get("method") or "get").strip().lower() or "get"
                label = str(action.get("label") or "").strip()
                if href and method == "get" and label:
                    return label, href, method
            return fallback_label, fallback_href, "get"

        memo_items: list[dict[str, str]] = []
        if str(support_verification.get("request_id") or "").strip() and str(support_verification.get("confirmation_state") or "").strip() != "confirmed":
            memo_items.append(
                {
                    "title": "Confirm the fix reached you",
                    "detail": " · ".join(
                        part
                        for part in (
                            str(support_verification.get("channel_receipt_detail") or "").strip(),
                            str(support_verification.get("install_receipt_detail") or "").strip(),
                        )
                        if str(part or "").strip()
                    ),
                    "tag": "Support",
                    "href": "/app/settings/support",
                    "action_href": str(support_verification.get("confirm_action_href") or "").strip(),
                    "action_label": "Confirm",
                    "action_method": "get",
                    "secondary_action_href": str(support_verification.get("access_url") or "").strip(),
                    "secondary_action_label": "Open access link" if str(support_verification.get("access_url") or "").strip() else "",
                    "secondary_action_method": "get",
                }
            )
        if memo_blocker_item is not None:
            memo_items.append(dict(memo_blocker_item))
        if support_grounding:
            support_action_label, support_action_href, support_action_method = first_get_action(
                support_grounding,
                fallback_label="Open support",
                fallback_href="/app/settings/support",
            )
            memo_items.append(
                {
                    "title": str(support_grounding.get("title") or "Support closure grounding"),
                    "detail": str(support_grounding.get("summary") or "Support posture should stay grounded in mirrored trust and scorecard truth."),
                    "tag": "Grounding",
                    "href": "/app/settings/support",
                    "action_href": support_action_href,
                    "action_label": support_action_label,
                    "action_method": support_action_method,
                }
            )
        for item in snapshot.brief_items[:2]:
            memo_items.append(
                {
                    "title": item.title,
                    "detail": item.why_now or item.summary or "Open the memo before the day fragments.",
                    "tag": item.kind.replace("_", " ").title() or "Memo",
                    "href": "/app/today",
                    "action_href": "/app/today",
                    "action_label": "Open memo",
                    "action_method": "get",
                }
            )
        if at_risk_commitments:
            commitment = at_risk_commitments[0]
            memo_items.append(
                {
                    "title": commitment.statement,
                    "detail": " · ".join(
                        part
                        for part in (
                            commitment.counterparty,
                            f"Due {commitment.due_at[:10]}" if commitment.due_at else "",
                            commitment.risk_level.replace("_", " ").title(),
                        )
                        if part
                    )
                    or "Commitment pressure needs a visible next action.",
                    "tag": "Commitment",
                    "href": f"/app/commitment-items/{commitment.id}",
                    "action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="queue",
                        object_ref=commitment.id,
                        action="close",
                        return_to="/app/channel-loop/memo",
                        operator_id=operator_key,
                        reason="Closed from morning memo digest.",
                    ),
                    "action_label": "Close",
                    "action_method": "get",
                    "secondary_action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="queue",
                        object_ref=commitment.id,
                        action="defer",
                        return_to="/app/channel-loop/memo",
                        operator_id=operator_key,
                        reason="Deferred from morning memo digest.",
                    ),
                    "secondary_action_label": "Defer",
                    "secondary_action_method": "get",
                }
            )
        approval_items: list[dict[str, str]] = []
        for draft in snapshot.drafts[:2]:
            approval_items.append(
                {
                    "title": f"Approve draft for {draft.recipient_summary or 'next reply'}",
                    "detail": " · ".join(
                        part for part in (draft.intent.title(), draft.send_channel, draft.approval_status) if part
                    )
                    or "Draft is waiting for approval.",
                    "tag": "Draft",
                    "href": "/app/queue",
                    "action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="draft",
                        object_ref=draft.id,
                        action="approve",
                        return_to="/app/channel-loop/approvals",
                        operator_id=operator_key,
                        reason="Approved from inline approvals digest.",
                    ),
                    "action_label": "Approve now",
                    "action_method": "get",
                    "secondary_action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="draft",
                        object_ref=draft.id,
                        action="reject",
                        return_to="/app/channel-loop/approvals",
                        operator_id=operator_key,
                        reason="Rejected from inline approvals digest.",
                    ),
                    "secondary_action_label": "Reject",
                    "secondary_action_method": "get",
                }
            )
        for candidate in visible_review_candidates[:2]:
            candidate_detail = " · ".join(
                part
                for part in (
                    candidate.kind.replace("_", " ").title(),
                    candidate.counterparty,
                    f"Due {candidate.suggested_due_at[:10]}" if candidate.suggested_due_at else "",
                    candidate.signal_type.replace("_", " ").title() if candidate.signal_type else "",
                    f"Merges into {candidate.duplicate_of_ref}" if candidate.duplicate_of_ref else "",
                )
                if part
            ) or "Signal-backed commitment candidate is waiting for review."
            approval_items.append(
                {
                    "title": candidate.title,
                    "detail": candidate_detail,
                    "tag": "Candidate",
                    "href": f"/app/commitments/candidates/{candidate.candidate_id}",
                    "action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="candidate",
                        object_ref=candidate.candidate_id,
                        action="accept",
                        return_to="/app/channel-loop/approvals",
                        operator_id=operator_key,
                        reason="Accepted from inline approvals digest.",
                    ),
                    "action_label": "Merge" if candidate.duplicate_of_ref else "Accept",
                    "action_method": "get",
                    "secondary_action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="candidate",
                        object_ref=candidate.candidate_id,
                        action="reject",
                        return_to="/app/channel-loop/approvals",
                        operator_id=operator_key,
                        reason="Rejected from inline approvals digest.",
                    ),
                    "secondary_action_label": "Reject",
                    "secondary_action_method": "get",
                }
            )
        for decision in open_decisions[:2]:
            approval_items.append(
                {
                    "title": decision.title,
                    "detail": " · ".join(
                        part
                        for part in (
                            decision.owner_role,
                            decision.sla_status.replace("_", " ").title(),
                            decision.impact_summary or decision.summary,
                        )
                        if part
                    )
                    or "Decision still needs a visible resolution.",
                    "tag": "Decision",
                    "href": f"/app/decisions/{decision.id}",
                    "action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="decision",
                        object_ref=decision.id,
                        action="resolve",
                        return_to="/app/channel-loop/approvals",
                        operator_id=operator_key,
                        reason="Resolved from inline approvals digest.",
                    ),
                    "action_label": "Resolve now",
                    "action_method": "get",
                    "secondary_action_href": f"/app/decisions/{decision.id}",
                    "secondary_action_label": "Review",
                    "secondary_action_method": "get",
                }
            )
        operator_items: list[dict[str, str]] = []
        if memo_blocker_item is not None:
            operator_items.append(dict(memo_blocker_item))
        if operator_grounding:
            operator_action_label, operator_action_href, operator_action_method = first_get_action(
                operator_grounding,
                fallback_label="Open office",
                fallback_href="/admin/office",
            )
            operator_items.append(
                {
                    "title": str(operator_grounding.get("title") or "Operator memo grounding"),
                    "detail": str(operator_grounding.get("summary") or "Operator memos should stay grounded in weekly product-control evidence."),
                    "tag": "Grounding",
                    "href": "/admin/office",
                    "action_href": operator_action_href,
                    "action_label": operator_action_label,
                    "action_method": operator_action_method,
                }
            )
        for handoff in visible_handoffs:
            actions = self._handoff_channel_actions(
                principal_id=principal_id,
                handoff=handoff,
                operator_id=operator_key,
                return_to="/app/channel-loop/operator",
            )
            operator_items.append(
                {
                    "title": handoff.summary,
                    "detail": " · ".join(
                        part
                        for part in (
                            handoff.owner or "Unclaimed",
                            f"Due {handoff.due_time[:10]}" if handoff.due_time else "",
                            handoff.escalation_status.replace("_", " ").title(),
                        )
                        if part
                    )
                    or "Handoff is waiting in the operator lane.",
                    "tag": "Handoff",
                    "href": f"/app/handoffs/{handoff.id}",
                    "action_href": str(actions[0].get("href") or "") if actions else "",
                    "action_label": str(actions[0].get("label") or "Claim") if actions else "Claim",
                    "action_method": str(actions[0].get("method") or "get") if actions else "get",
                    "secondary_action_href": str(actions[1].get("href") or "") if len(actions) > 1 else "",
                    "secondary_action_label": str(actions[1].get("label") or "") if len(actions) > 1 else "",
                    "secondary_action_method": str(actions[1].get("method") or "get") if len(actions) > 1 else "",
                    "tertiary_action_href": str(actions[2].get("href") or "") if len(actions) > 2 else "",
                    "tertiary_action_label": str(actions[2].get("label") or "") if len(actions) > 2 else "",
                    "tertiary_action_method": str(actions[2].get("method") or "get") if len(actions) > 2 else "",
                    "quaternary_action_href": str(actions[3].get("href") or "") if len(actions) > 3 else "",
                    "quaternary_action_label": str(actions[3].get("label") or "") if len(actions) > 3 else "",
                    "quaternary_action_method": str(actions[3].get("method") or "get") if len(actions) > 3 else "",
                }
            )
        if snapshot.commitments:
            commitment = at_risk_commitments[0] if at_risk_commitments else snapshot.commitments[0]
            operator_items.append(
                {
                    "title": commitment.statement,
                    "detail": " · ".join(
                        part
                        for part in (
                            commitment.counterparty,
                            f"Due {commitment.due_at[:10]}" if commitment.due_at else "",
                            commitment.risk_level.replace("_", " ").title(),
                        )
                        if part
                    )
                    or "Commitment still needs an explicit owner and next step.",
                    "tag": "Commitment",
                    "href": f"/app/commitment-items/{commitment.id}",
                    "action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="queue",
                        object_ref=commitment.id,
                        action="close",
                        return_to="/app/channel-loop/operator",
                        operator_id=operator_key,
                        reason="Closed from operator digest.",
                    ),
                    "action_label": "Close",
                    "action_method": "get",
                    "secondary_action_href": self.channel_action_href(
                        principal_id=principal_id,
                        object_kind="queue",
                        object_ref=commitment.id,
                        action="defer",
                        return_to="/app/channel-loop/operator",
                        operator_id=operator_key,
                        reason="Deferred from operator digest.",
                    ),
                    "secondary_action_label": "Defer",
                    "secondary_action_method": "get",
                }
            )
        return [
            {
                "key": "memo",
                "headline": "Morning memo digest",
                "summary": "Forward or open the ranked day brief from a mobile-safe surface.",
                "preview_text": (
                    f"{len(snapshot.brief_items)} memo items, {len(at_risk_commitments)} commitments at risk, {len(open_decisions)} open decisions."
                    + (" 1 memo blocker needs a fix action." if memo_blocker_item is not None else "")
                ),
                "items": memo_items,
                "stats": {
                    "memo_items": len(snapshot.brief_items),
                    "at_risk_commitments": len(at_risk_commitments),
                    "open_decisions": len(open_decisions),
                    "memo_blockers": 1 if memo_blocker_item is not None else 0,
                },
            },
            {
                "key": "approvals",
                "headline": "Inline approvals",
                "summary": "Clear draft approvals, staged commitment review, and decision pressure without dropping into the full workspace.",
                "preview_text": (
                    f"{len(snapshot.drafts)} pending drafts, "
                    f"{len(visible_review_candidates)} staged commitment candidates, "
                    f"and {len(principal_queue)} principal-backed queue items are waiting."
                ),
                "items": approval_items,
                "stats": {
                    "pending_drafts": len(snapshot.drafts),
                    "pending_commitment_candidates": len(visible_review_candidates),
                    "principal_queue_items": len(principal_queue),
                    "open_decisions": len(open_decisions),
                },
            },
            {
                "key": "operator",
                "headline": "Operator handoff digest",
                "summary": "Claim, complete, and close the next office item from a compact operator surface.",
                "preview_text": (
                    f"{len(assigned_handoffs)} assigned handoffs, {len(unclaimed_handoffs)} unclaimed handoffs, {len(snapshot.commitments)} open commitments."
                    + (" Active memo blocker needs an operator-visible fix path." if memo_blocker_item is not None else "")
                ),
                "items": operator_items,
                "stats": {
                    "assigned_handoffs": len(assigned_handoffs),
                    "unclaimed_handoffs": len(unclaimed_handoffs),
                    "open_commitments": len(snapshot.commitments),
                    "memo_blockers": 1 if memo_blocker_item is not None else 0,
                },
            },
        ]

    def channel_action_href(
        self,
        *,
        principal_id: str,
        object_kind: str,
        object_ref: str,
        action: str,
        return_to: str,
        operator_id: str = "",
        reason: str = "",
        expires_in_seconds: int = 60 * 60 * 24 * 7,
    ) -> str:
        expires_at = datetime.now(timezone.utc).timestamp() + max(int(expires_in_seconds), 300)
        payload = {
            "principal_id": str(principal_id or "").strip(),
            "object_kind": str(object_kind or "").strip(),
            "object_ref": str(object_ref or "").strip(),
            "action": str(action or "").strip(),
            "return_to": str(return_to or "/app/channel-loop").strip() or "/app/channel-loop",
            "operator_id": str(operator_id or "").strip(),
            "reason": str(reason or "").strip(),
            "issued_at": _now_iso(),
            "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        }
        token = _sign_channel_payload(secret=self._channel_action_secret(), payload=payload)
        return f"/app/channel-actions/{token}"

    def redeem_channel_action_token(
        self,
        *,
        token: str,
        actor: str = "",
        preferred_operator_id: str = "",
    ) -> dict[str, object] | None:
        preview = self.preview_channel_action_token(token=token)
        if preview is None:
            return None
        principal_id = str(preview.get("principal_id") or "").strip()
        object_kind = str(preview.get("object_kind") or "").strip().lower()
        object_ref = str(preview.get("object_ref") or "").strip()
        action = str(preview.get("action") or "").strip().lower()
        return_to = str(preview.get("return_to") or "/sign-in").strip() or "/sign-in"
        reason = str(preview.get("reason") or "Resolved from channel action link.").strip() or "Resolved from channel action link."
        operator_id = str(preferred_operator_id or preview.get("operator_id") or "").strip()
        resolved_actor = str(actor or operator_id or principal_id or "channel_link").strip() or "channel_link"
        if not principal_id or not object_kind or not object_ref or not action:
            return None
        result: object | None = None
        if object_kind == "draft":
            if action == "reject":
                result = self.reject_draft(
                    principal_id=principal_id,
                    draft_ref=object_ref,
                    decided_by=resolved_actor,
                    reason=reason,
                )
            else:
                result = self.approve_draft(
                    principal_id=principal_id,
                    draft_ref=object_ref,
                    decided_by=resolved_actor,
                    reason=reason,
                )
        elif object_kind in {"candidate", "commitment_candidate"}:
            if action == "reject":
                result = self.reject_commitment_candidate(
                    principal_id=principal_id,
                    candidate_id=object_ref,
                    reviewer=resolved_actor,
                )
            else:
                result = self.accept_commitment_candidate(
                    principal_id=principal_id,
                    candidate_id=object_ref,
                    reviewer=resolved_actor,
                )
        elif object_kind == "queue":
            result = self.resolve_queue_item(
                principal_id=principal_id,
                item_ref=object_ref,
                action=action,
                actor=resolved_actor,
                reason=reason,
            )
        elif object_kind == "decision":
            result = self.resolve_decision(
                principal_id=principal_id,
                decision_ref=object_ref,
                actor=resolved_actor,
                action=action,
                reason=reason,
            )
        elif object_kind == "handoff":
            if not operator_id:
                active = self._container.orchestrator.list_operator_profiles(principal_id=principal_id, status="active", limit=1)
                operator_id = str(active[0].operator_id or "").strip() if active else ""
            if not operator_id:
                return None
            if action in {"assign", "claim"}:
                result = self.assign_handoff(
                    principal_id=principal_id,
                    handoff_ref=object_ref,
                    operator_id=operator_id,
                    actor=resolved_actor,
                )
            elif action in {"retry_send", "retry-send", "retry"}:
                result = self.retry_delivery_followup_send(
                    principal_id=principal_id,
                    handoff_ref=object_ref,
                    operator_id=operator_id,
                    actor=resolved_actor,
                )
            elif action == "recreate":
                result = self.recreate_property_tour_followup(
                    principal_id=principal_id,
                    handoff_ref=object_ref,
                    operator_id=operator_id,
                    actor=resolved_actor,
                )
            else:
                result = self.complete_handoff(
                    principal_id=principal_id,
                    handoff_ref=object_ref,
                    operator_id=operator_id,
                    actor=resolved_actor,
                    resolution=action,
                )
        elif object_kind in {"support_verification", "support_fix_verification"}:
            if action != "confirm":
                return None
            result = self.confirm_support_fix_verification(
                principal_id=principal_id,
                request_id=object_ref,
                actor=resolved_actor,
            )
        if result is None:
            return None
        self._record_product_event(
            principal_id=principal_id,
            event_type="channel_action_redeemed",
            payload={
                "object_kind": object_kind,
                "object_ref": object_ref,
                "action": action,
                "actor": resolved_actor,
                "return_to": return_to,
            },
            source_id=object_ref,
            dedupe_key=f"{principal_id}|{object_kind}|{object_ref}|{action}|{token}",
        )
        return {
            "principal_id": principal_id,
            "object_kind": object_kind,
            "object_ref": object_ref,
            "action": action,
            "return_to": return_to,
            "actor": resolved_actor,
        }

    def preview_channel_action_token(
        self,
        *,
        token: str,
    ) -> dict[str, object] | None:
        payload = _verify_channel_payload(secret=self._channel_action_secret(), token=token)
        if payload is None:
            return None
        principal_id = str(payload.get("principal_id") or "").strip()
        object_kind = str(payload.get("object_kind") or "").strip().lower()
        object_ref = str(payload.get("object_ref") or "").strip()
        action = str(payload.get("action") or "").strip().lower()
        if not principal_id or not object_kind or not object_ref or not action:
            return None
        return {
            "principal_id": principal_id,
            "object_kind": object_kind,
            "object_ref": object_ref,
            "action": action,
            "return_to": str(payload.get("return_to") or "/sign-in").strip() or "/sign-in",
            "reason": str(payload.get("reason") or "Resolved from channel action link.").strip()
            or "Resolved from channel action link.",
            "operator_id": str(payload.get("operator_id") or "").strip(),
            "issued_at": str(payload.get("issued_at") or "").strip(),
            "expires_at": str(payload.get("expires_at") or "").strip(),
        }

    def record_surface_event(
        self,
        *,
        principal_id: str,
        event_type: str,
        surface: str,
        actor: str = "",
        metadata: dict[str, object] | None = None,
    ) -> None:
        normalized_type = str(event_type or "").strip().lower()
        normalized_surface = str(surface or "").strip().lower()
        if not normalized_type or not normalized_surface:
            return
        payload = {
            "surface": normalized_surface,
            "actor": str(actor or "").strip() or "browser",
        }
        if metadata:
            payload.update(dict(metadata))
        self._record_product_event(
            principal_id=principal_id,
            event_type=normalized_type,
            payload=payload,
            source_id=normalized_surface,
        )


def build_product_service(container: AppContainer) -> ProductService:
    return ProductService(container)
