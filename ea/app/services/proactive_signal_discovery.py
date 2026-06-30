from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from xml.etree import ElementTree

from app.services.proactive_ooda_service import JsonOodaStateStore, ProactiveSignal

_TRANSCRIPT_REQUEST_MARKERS = (
    "book",
    "buy",
    "can you",
    "compare",
    "could you",
    "finde",
    "find",
    "formuliere",
    "brauch",
    "brauche",
    "ich brauche",
    "kannst du",
    "koenntest du",
    "need to",
    "order",
    "please",
    "remember to",
    "renew",
    "reply",
    "reserve",
    "respond",
    "review",
    "schedule",
    "schick",
    "schicke",
    "schreib",
    "schreibe",
    "shop",
    "should",
    "such",
    "suche",
    "wenn du",
    "write",
)
_TRANSCRIPT_DRAFT_TERMS = (
    "draft",
    "e-mail",
    "email",
    "entwurf",
    "formuliere",
    "inbox",
    "mail",
    "message",
    "reply",
    "respond",
    "schicke",
    "schreibe",
    "text back",
    "write back",
)
_TRANSCRIPT_DRAFT_SAVE_TERMS = (
    "als draft in meiner inbox",
    "als entwurf in meiner inbox",
    "draft in meiner inbox",
    "draft in my inbox",
    "save it as a draft",
    "save it as draft",
    "save the draft in my inbox",
    "save this as a draft",
    "save this as draft",
    "save to my inbox",
    "speicher den entwurf in meiner inbox",
    "speicher es als draft",
    "speicher es als entwurf",
    "speicher es in meiner inbox",
    "speicher ihn als draft",
    "speicher ihn als entwurf",
    "speicher sie als draft",
    "speicher sie als entwurf",
    "speichere den entwurf in meiner inbox",
    "speichere es als draft",
    "speichere es als entwurf",
    "speichere es in meiner inbox",
    "speichere ihn als draft",
    "speichere ihn als entwurf",
    "speichere sie als draft",
    "speichere sie als entwurf",
)
_TRANSCRIPT_BOOKING_TERMS = (
    "appointment",
    "book",
    "booking",
    "buch",
    "buche",
    "flight",
    "hotel",
    "reservation",
    "reserve",
    "restaurant",
    "schedule",
    "termin",
    "table",
    "viewing",
    "visit",
)
_TRANSCRIPT_COMPARE_TERMS = (
    "buy",
    "candidate",
    "compare",
    "finde",
    "find",
    "florist",
    "gift",
    "kandidat",
    "kandidaten",
    "option",
    "order",
    "provider",
    "renew",
    "renewal",
    "search",
    "such",
    "suche",
    "shop",
    "shopping",
    "shortlist",
    "supplier",
    "vendor",
)
_TRANSCRIPT_SERVICE_PROVIDER_MARKERS = (
    "befund",
    "befundung",
    "chimney sweep",
    "contractor",
    "estimate",
    "expert",
    "gutachten",
    "inspection",
    "provider",
    "quote",
    "rauchfangkehrer",
    "repair",
    "schornsteinfeger",
    "specialist",
    "technician",
    "vendor",
)
_TRANSCRIPT_SHOPPING_MARKERS = (
    "buy",
    "flowers",
    "gift",
    "hotel",
    "order",
    "restaurant",
    "shop",
    "shopping",
)
_TRANSCRIPT_SEARCH_QUERY_STOPWORDS = {
    "a",
    "als",
    "an",
    "approval",
    "ask",
    "bitte",
    "brauch",
    "brauche",
    "can",
    "could",
    "draft",
    "du",
    "eines",
    "einen",
    "eine",
    "einem",
    "einer",
    "email",
    "emailanfrage",
    "find",
    "finde",
    "finden",
    "found",
    "formuliere",
    "gefunden",
    "hast",
    "here",
    "ich",
    "ihnen",
    "in",
    "inbox",
    "inquiry",
    "it",
    "ihr",
    "ihre",
    "ihren",
    "kannst",
    "koenntest",
    "link",
    "me",
    "mein",
    "meine",
    "meinen",
    "meinem",
    "meiner",
    "mir",
    "my",
    "ob",
    "of",
    "one",
    "please",
    "reply",
    "save",
    "schicke",
    "schreibe",
    "send",
    "sie",
    "speicher",
    "suche",
    "such",
    "the",
    "to",
    "use",
    "verwenden",
    "want",
    "we",
    "wenn",
    "you",
}
_TRANSCRIPT_HIGH_RISK_TERMS = (
    "beauftrage",
    "book",
    "buy",
    "cancel",
    "commit",
    "kaufe",
    "order",
    "pay",
    "sende",
    "purchase",
    "reply",
    "reserve",
    "respond",
    "schick",
    "schicke",
    "send",
    "sign",
    "write back",
)
_TRANSCRIPT_SUPPRESSION_PATTERNS = (
    re.compile(r"\b(?:stop|no more|quit)\b(?:\s+(?:with|about|regarding|on))?\s+(?P<topic>.+)", re.IGNORECASE),
    re.compile(r"\b(?:do not|don't)\b(?:\s+(?:send|research|compare|shop|buy|book|look for|talk about))?(?:\s+(?:with|about|regarding|on))?\s+(?P<topic>.+)", re.IGNORECASE),
    re.compile(r"\b(?:hor auf|hoer auf|hore auf)\b(?:\s+mit)?\s+(?P<topic>.+)", re.IGNORECASE),
)
_TRANSCRIPT_SUPPRESSION_STOPWORDS = {
    "about",
    "bitte",
    "das",
    "dem",
    "den",
    "der",
    "die",
    "diesem",
    "dieser",
    "do",
    "dont",
    "for",
    "it",
    "jetzt",
    "mit",
    "more",
    "on",
    "please",
    "regarding",
    "the",
    "this",
    "topic",
    "uber",
    "ueber",
    "und",
    "with",
}
_TRANSCRIPT_SUPPRESSION_TOKEN_MAP = {
    "mic": "microphone",
    "mics": "microphone",
    "microfon": "microphone",
    "microfone": "microphone",
    "microfonen": "microphone",
    "microphones": "microphone",
    "mikrofon": "microphone",
    "mikrofone": "microphone",
    "mikrofonen": "microphone",
    "unter": "under",
    "unterwand": "underwall",
    "wallbox": "wallbox",
    "wande": "wall",
    "wand": "wall",
    "waende": "wall",
}


@dataclass(frozen=True)
class SignalSource:
    source_type: str
    ref: str
    channel: str = "discovery"
    signal_type: str = "external_signal"
    counterparty: str = ""
    limit: int = 20
    field_map: Mapping[str, str] | None = None
    config: Mapping[str, Any] | None = None

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "SignalSource":
        source_type = str(row.get("type") or row.get("source_type") or "").strip().lower()
        ref = str(row.get("url") or row.get("path") or row.get("ref") or "").strip()
        if not source_type:
            source_type = _infer_source_type(ref)
        return cls(
            source_type=source_type,
            ref=ref,
            channel=str(row.get("channel") or "discovery").strip(),
            signal_type=str(row.get("signal_type") or row.get("type_label") or "external_signal").strip(),
            counterparty=str(row.get("counterparty") or row.get("source_name") or row.get("name") or "").strip(),
            limit=max(int(row.get("limit") or 20), 1),
            field_map=row.get("field_map") if isinstance(row.get("field_map"), Mapping) else None,
            config=row,
        )


@dataclass(frozen=True)
class SignalDiscoveryResult:
    signals: tuple[ProactiveSignal, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class OpportunityTriggerEvaluation:
    kind: str
    matched: bool
    weather_context: Mapping[str, float] | None = None


@dataclass(frozen=True)
class OpportunityTriggerRuntime:
    signal_key: str
    occurrence: int
    state: Mapping[str, Any]


def load_signal_sources_config(raw: str) -> tuple[SignalSource, ...]:
    normalized = str(raw or "").strip()
    if not normalized:
        return ()
    payload = json.loads(normalized)
    if isinstance(payload, dict):
        rows = payload.get("sources") or []
    else:
        rows = payload
    if not isinstance(rows, list):
        raise ValueError("discovery_sources_must_be_a_list")
    return tuple(SignalSource.from_mapping(row) for row in rows if isinstance(row, Mapping))


def discover_signals(
    *,
    sources: Iterable[SignalSource],
    base_dir: Path,
    timeout_seconds: int = 20,
    principal_id: str = "",
    opportunity_state_store: JsonOodaStateStore | None = None,
    persist_opportunity_state: bool = True,
) -> list[ProactiveSignal]:
    signals: list[ProactiveSignal] = []
    for source in sources:
        signals.extend(
            _discover_source(
                source,
                base_dir=base_dir,
                timeout_seconds=timeout_seconds,
                principal_id=principal_id,
                opportunity_state_store=opportunity_state_store,
                persist_opportunity_state=persist_opportunity_state,
            )
        )
    return signals


def discover_signals_resilient(
    *,
    sources: Iterable[SignalSource],
    base_dir: Path,
    timeout_seconds: int = 20,
    principal_id: str = "",
    opportunity_state_store: JsonOodaStateStore | None = None,
    persist_opportunity_state: bool = True,
) -> SignalDiscoveryResult:
    signals: list[ProactiveSignal] = []
    errors: list[str] = []
    for source in sources:
        try:
            signals.extend(
                _discover_source(
                    source,
                    base_dir=base_dir,
                    timeout_seconds=timeout_seconds,
                    principal_id=principal_id,
                    opportunity_state_store=opportunity_state_store,
                    persist_opportunity_state=persist_opportunity_state,
                )
            )
        except Exception as exc:
            errors.append(_source_error_label(source, exc))
    return SignalDiscoveryResult(signals=tuple(signals), errors=tuple(errors))


def _discover_source(
    source: SignalSource,
    *,
    base_dir: Path,
    timeout_seconds: int,
    principal_id: str = "",
    opportunity_state_store: JsonOodaStateStore | None = None,
    persist_opportunity_state: bool = True,
) -> list[ProactiveSignal]:
    if source.source_type in {"opportunity_rules", "opportunity_rule", "personal_rules", "personal_rule"}:
        return _load_opportunity_rules_source(
            source,
            base_dir=base_dir,
            timeout_seconds=timeout_seconds,
            principal_id=principal_id,
            opportunity_state_store=opportunity_state_store,
            persist_opportunity_state=persist_opportunity_state,
        )
    if not source.ref:
        return []
    if source.source_type == "json":
        return _load_json_source(source, base_dir=base_dir, timeout_seconds=timeout_seconds)
    if source.source_type == "jsonl":
        return _load_jsonl_source(source, base_dir=base_dir, timeout_seconds=timeout_seconds)
    if source.source_type == "rss":
        return _load_rss_source(source, base_dir=base_dir, timeout_seconds=timeout_seconds)
    if source.source_type == "teable":
        return _load_teable_source(source, timeout_seconds=timeout_seconds)
    raise ValueError(f"unsupported_signal_source_type:{source.source_type}")


def discover_opportunity_rule_signals(
    *,
    raw_config: str,
    base_dir: Path,
    timeout_seconds: int = 20,
    principal_id: str = "",
    opportunity_state_store: JsonOodaStateStore | None = None,
    persist_opportunity_state: bool = True,
) -> SignalDiscoveryResult:
    normalized = str(raw_config or "").strip()
    if not normalized:
        return SignalDiscoveryResult(signals=(), errors=())
    try:
        source = SignalSource(
            source_type="opportunity_rules",
            ref=normalized if not normalized.startswith(("{", "[")) else "",
            channel="assistant_opportunity",
            signal_type="opportunity",
            counterparty="EA",
            config=json.loads(normalized) if normalized.startswith(("{", "[")) else None,
        )
        return SignalDiscoveryResult(
            signals=tuple(
                _load_opportunity_rules_source(
                    source,
                    base_dir=base_dir,
                    timeout_seconds=timeout_seconds,
                    principal_id=principal_id,
                    opportunity_state_store=opportunity_state_store,
                    persist_opportunity_state=persist_opportunity_state,
                )
            ),
            errors=(),
        )
    except Exception as exc:
        return SignalDiscoveryResult(signals=(), errors=(f"assistant_opportunity:opportunity_rules:{exc.__class__.__name__}:config",))


def discover_personal_rule_signals(
    *,
    raw_config: str,
    base_dir: Path,
    timeout_seconds: int = 20,
    principal_id: str = "",
    opportunity_state_store: JsonOodaStateStore | None = None,
    persist_opportunity_state: bool = True,
) -> SignalDiscoveryResult:
    return discover_opportunity_rule_signals(
        raw_config=raw_config,
        base_dir=base_dir,
        timeout_seconds=timeout_seconds,
        principal_id=principal_id,
        opportunity_state_store=opportunity_state_store,
        persist_opportunity_state=persist_opportunity_state,
    )


def discover_postgres_observation_signals(
    *,
    principal_id: str,
    database_url: str | None = None,
    limit: int = 50,
    lookback_hours: int = 24,
) -> list[ProactiveSignal]:
    url = str(database_url or os.getenv("DATABASE_URL") or "").strip()
    if not url:
        return []
    try:
        import psycopg
    except Exception:
        return []
    event_types = (
        "office_signal_ooda_evaluated",
        "commitment_candidate_staged",
        "property_scout_sync_completed",
        "telegram.message",
        "telegram_business.signal_candidate",
        "alexa_history_indexed",
        "pocket_recording_archive_indexed",
    )
    principals = _candidate_principals(principal_id)
    try:
        with psycopg.connect(url, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                query = """
                    select observation_id, principal_id, channel, event_type, payload_json, created_at, source_id, external_id, dedupe_key
                    from observation_events
                    where principal_id = any(%s)
                      and event_type = any(%s)
                """
                query_params: list[Any] = [principals, list(event_types)]
                if int(lookback_hours) > 0:
                    query += " and created_at >= now() - (%s || ' hours')::interval"
                    query_params.append(int(lookback_hours))
                query += """
                    order by created_at desc
                    limit %s
                    """
                query_params.append(int(limit))
                cursor.execute(
                    query,
                    tuple(query_params),
                )
                rows = cursor.fetchall()
    except Exception:
        return []
    signals: list[ProactiveSignal] = []
    coalesced_keys: set[str] = set()
    for row in rows:
        event_type = str(row[3] or "")
        payload = row[4] if isinstance(row[4], Mapping) else {}
        signal = observation_row_to_signal(
            observation_id=str(row[0] or ""),
            principal_id=str(row[1] or ""),
            channel=str(row[2] or ""),
            event_type=event_type,
            payload=payload,
            created_at=str(row[5] or ""),
            source_id=str(row[6] or ""),
            external_id=str(row[7] or ""),
            dedupe_key=str(row[8] or ""),
        )
        if not signal:
            continue
        coalescing_key = _observation_coalescing_key(event_type=event_type, payload=payload)
        if coalescing_key:
            if coalescing_key in coalesced_keys:
                continue
            coalesced_keys.add(coalescing_key)
        signals.append(signal)
    return signals


def _pocket_recording_payload_fields(payload: Mapping[str, Any] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    if not isinstance(payload, Mapping):
        return normalized
    for key in (
        "recording_id",
        "title",
        "recording_at",
        "archive_status",
        "archive_path",
        "archive_sha256",
        "summary_markdown",
        "transcript_excerpt",
        "transcript_text",
        "topic_keywords_csv",
        "tags_csv",
        "location_name",
        "location_address",
        "location_confidence",
        "location_match_status",
        "location_match_reason",
    ):
        value = _clean_text(str(payload.get(key) or "")).strip()
        if value:
            normalized[key] = value
    return normalized


def _pocket_recording_source_context(
    *,
    payload: Mapping[str, Any] | None,
    fields: Mapping[str, str],
    source_id: str,
    created_at: str,
) -> dict[str, Any]:
    transcript_text = _clean_text(str((payload or {}).get("transcript_text") or "")).strip() if isinstance(payload, Mapping) else ""
    transcript_excerpt = _clean_text(str((payload or {}).get("transcript_excerpt") or "")).strip() if isinstance(payload, Mapping) else ""
    summary_markdown = _clean_text(str((payload or {}).get("summary_markdown") or "")).strip() if isinstance(payload, Mapping) else ""
    archive_path = str(fields.get("archive_path") or "").strip()
    freshness_context = _pocket_recording_freshness_context(
        recording_at=str(fields.get("recording_at") or "").strip(),
        indexed_at=str(created_at or "").strip(),
    )
    retention_status = str(fields.get("archive_status") or "").strip() or "unknown"
    context: dict[str, Any] = {
        "provider": "pocket.ai",
        "source_id": str(source_id or "").strip(),
        "indexed_at": str(created_at or "").strip(),
        "recording_id": str(fields.get("recording_id") or "").strip(),
        "recording_at": str(fields.get("recording_at") or "").strip(),
        "archive_status": str(fields.get("archive_status") or "").strip(),
        "archive_sha256": str(fields.get("archive_sha256") or "").strip(),
        "archive_path_sha256": _sha256_text(archive_path),
        "retention_class": "pocket_audio_archive_index",
        "retention_status": retention_status,
        "retention_payload": "redacted_source_metadata",
        "topic_keywords_csv": str(fields.get("topic_keywords_csv") or "").strip(),
        "tags_csv": str(fields.get("tags_csv") or "").strip(),
        "location_name": str(fields.get("location_name") or "").strip(),
        "location_address": str(fields.get("location_address") or "").strip(),
        "location_confidence": str(fields.get("location_confidence") or "").strip(),
        "location_match_status": str(fields.get("location_match_status") or "").strip(),
        "location_match_reason": str(fields.get("location_match_reason") or "").strip(),
        "summary_markdown_sha256": _sha256_text(summary_markdown),
        "transcript_excerpt_sha256": _sha256_text(transcript_excerpt),
        "transcript_text_sha256": _sha256_text(transcript_text),
        "summary_markdown_char_count": len(summary_markdown),
        "transcript_excerpt_char_count": len(transcript_excerpt),
        "transcript_text_char_count": len(transcript_text),
        "privacy": {
            "raw_archive_path_stored": False,
            "raw_summary_markdown_stored": False,
            "raw_transcript_excerpt_stored": False,
            "raw_transcript_text_stored": False,
        },
    }
    context.update(freshness_context)
    return {
        key: value
        for key, value in context.items()
        if value != "" and not (value == 0 and key not in {"source_lag_hours"})
    }


def _pocket_recording_freshness_context(*, recording_at: str, indexed_at: str) -> dict[str, Any]:
    recording_time = _parse_iso_datetime(recording_at)
    indexed_time = _parse_iso_datetime(indexed_at)
    context: dict[str, Any] = {
        "source_freshness_basis": "recording_at_to_indexed_at",
        "source_stale_after_hours": 168.0,
    }
    if not recording_time or not indexed_time:
        context["source_current_status"] = "unknown"
        return context
    lag_hours = round((indexed_time - recording_time).total_seconds() / 3600.0, 2)
    context["source_lag_hours"] = lag_hours
    if lag_hours < -1.0:
        context["source_current_status"] = "clock_skew"
    elif lag_hours <= 168.0:
        context["source_current_status"] = "current"
    else:
        context["source_current_status"] = "stale"
    return context


def _pocket_transcript_text(payload: Mapping[str, Any] | None) -> str:
    fields = _pocket_recording_payload_fields(payload)
    for key in ("summary_markdown", "transcript_excerpt", "transcript_text"):
        value = fields.get(key, "")
        if value:
            return value
    return fields.get("title", "")


def _alexa_history_payload_fields(payload: Mapping[str, Any] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    if not isinstance(payload, Mapping):
        return normalized
    for key in (
        "history_entry_id",
        "source_ref",
        "title",
        "occurred_at",
        "summary_markdown",
        "utterance_text",
        "response_text",
        "transcript_text",
        "transcript_excerpt",
        "device_name",
        "skill_name",
        "locale",
        "activity_status",
        "import_source_path",
        "import_archive_member",
    ):
        value = _clean_text(str(payload.get(key) or "")).strip()
        if value:
            normalized[key] = value
    return normalized


def _alexa_transcript_text(payload: Mapping[str, Any] | None) -> str:
    fields = _alexa_history_payload_fields(payload)
    for key in ("utterance_text", "summary_markdown", "transcript_excerpt", "transcript_text", "response_text"):
        value = fields.get(key, "")
        if value:
            return value
    return fields.get("title", "")


def _transcript_request_text(*values: Any) -> str:
    parts: list[str] = []
    lowered_parts: list[str] = []
    for value in values:
        normalized = _clean_text(str(value or "")).strip()
        lowered = normalized.lower()
        if not normalized:
            continue
        if any(lowered == existing or lowered in existing for existing in lowered_parts):
            continue
        contained_indexes = [index for index, existing in enumerate(lowered_parts) if existing in lowered]
        for index in reversed(contained_indexes):
            parts.pop(index)
            lowered_parts.pop(index)
        parts.append(normalized)
        lowered_parts.append(lowered)
    return " ".join(parts).strip()


def _transcript_delivery_window_days(text: str) -> float | None:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return None
    if any(marker in lowered for marker in ("today", "tonight")):
        return 1.0
    if "tomorrow" in lowered:
        return 1.0
    if "weekend" in lowered:
        return 3.0
    if "next week" in lowered:
        return 7.0
    return None


def _draft_text_from_request(request_text: str) -> str:
    normalized = _clean_text(request_text).strip()
    if not normalized:
        return ""
    return f"Draft to review:\n\n{normalized}"


def _research_query_from_request(request_text: str) -> str:
    normalized = _clean_text(request_text).strip()
    if not normalized:
        return ""
    lowered = normalized.lower()
    split_markers = (
        " draft ",
        " email inquiry",
        " emailanfrage",
        " formuliere ",
        " schreibe ",
        " schicke ",
        " save it ",
        " save the draft",
        " save as draft",
        " speicher ",
        " als draft",
        " in meiner inbox",
        " in my inbox",
        " for approval",
        " zur freigabe",
    )
    cut = len(normalized)
    for marker in split_markers:
        index = lowered.find(marker)
        if index > 0:
            cut = min(cut, index)
    trimmed = normalized[:cut].strip(" ,")
    sentence_match = re.search(r"\A(.+?[.!?])(?:\s|$)", trimmed)
    if sentence_match:
        candidate = sentence_match.group(1).strip(" ,")
    else:
        segments = [segment.strip(" ,") for segment in re.split(r"[;]+", trimmed) if segment.strip(" ,")]
        candidate = segments[0] if segments else trimmed
    candidate = re.sub(r"^(when you|if you|please|can you|could you|would you)\s+", "", candidate, flags=re.IGNORECASE).strip()
    candidate = re.sub(r"^(wenn du|falls du|bitte|kannst du|koenntest du)\s+", "", candidate, flags=re.IGNORECASE).strip()
    candidate = re.sub(r"\b(gefunden hast|found one|found)\b", "", candidate, flags=re.IGNORECASE).strip(" ,")
    compacted_candidate = re.sub(
        r"^(find me|find|look for|search for|suche mir|suche|such|finde)\s+",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    compacted = compacted_candidate != candidate
    candidate = compacted_candidate.strip()
    candidate = re.sub(r"^(a|an|the|einen|eine|einer|einem|den|die|das)\s+", "", candidate, flags=re.IGNORECASE).strip()
    if compacted:
        candidate = candidate.strip(" ,.-")
    lowered_candidate = candidate.lower()
    explanatory_markers = (
        " - ich brauche",
        " - ich benoetige",
        " - i need",
        ", ich brauche",
        ", ich benoetige",
        ", i need",
        " ich brauche ",
        " ich benoetige ",
        " i need ",
        " ob ich ",
        " whether i ",
    )
    cut = len(candidate)
    for marker in explanatory_markers:
        index = lowered_candidate.find(marker)
        if index > 0:
            cut = min(cut, index)
    candidate = candidate[:cut].strip(" ,")
    candidate = re.sub(r"\s+", " ", candidate).strip(" ,")
    return candidate or trimmed or normalized


def _search_queries_from_request(*, research_query: str, request_text: str) -> list[str]:
    base = str(research_query or "").strip()
    if not base:
        return []
    queries = [base]
    base_terms = {
        _ascii_fold_text(token).lower()
        for token in re.findall(r"[A-Za-z0-9]+", base)
        if _ascii_fold_text(token).strip()
    }
    context_terms: list[str] = []
    seen_context: set[str] = set()
    for token in re.findall(r"[A-Za-z0-9]+", _clean_text(request_text)):
        normalized = _ascii_fold_text(token).lower()
        if (
            not normalized
            or len(normalized) < 5
            or normalized in base_terms
            or normalized in _TRANSCRIPT_SEARCH_QUERY_STOPWORDS
            or normalized in seen_context
        ):
            continue
        seen_context.add(normalized)
        context_terms.append(str(token).strip())
    if context_terms:
        longest = " ".join([base, *context_terms[:4]]).strip()
        if longest:
            queries.insert(0, longest)
        shorter = " ".join([base, *context_terms[:3]]).strip()
        if shorter:
            queries.insert(1, shorter if longest else shorter)
    return list(dict.fromkeys(query for query in queries if query))


def _transcript_request_locale(request_text: str) -> str:
    lowered = _ascii_fold_text(_clean_text(request_text).strip().lower())
    if any(
        marker in lowered
        for marker in (
            "wenn du",
            "brauch",
            "brauche",
            "kannst du",
            "koenntest du",
            "rauchfangkehrer",
            "formuliere",
            "schreibe",
            "schicke",
            "suche",
            "finde",
        )
    ):
        return "de"
    return "en"


def _transcript_save_gmail_draft_requested(lowered_request: str) -> bool:
    normalized = f" {str(lowered_request or '').strip()} "
    return any(marker in normalized for marker in _TRANSCRIPT_DRAFT_SAVE_TERMS)


def _transcript_service_provider_request(lowered_request: str) -> bool:
    normalized = f" {str(lowered_request or '').strip()} "
    if any(marker in normalized for marker in _TRANSCRIPT_SERVICE_PROVIDER_MARKERS):
        return True
    if (
        any(marker in normalized for marker in (" suche mir ", " suche ", " find me ", " find ", " search for "))
        and any(marker in normalized for marker in (" ich brauche ", " i need ", " brauche ", " need "))
        and not any(marker in normalized for marker in _TRANSCRIPT_SHOPPING_MARKERS)
    ):
        return True
    return False


def _transcript_has_action_intent(lowered_request: str) -> bool:
    normalized = _ascii_fold_text(_clean_text(lowered_request).strip().lower())
    if not normalized:
        return False
    padded = f" {normalized} "
    if _transcript_save_gmail_draft_requested(normalized) or _transcript_service_provider_request(normalized):
        return True
    direct_patterns = (
        r"\b(?:can you|could you|please|remember to)\b",
        r"\b(?:kannst du|koenntest du|wenn du|bitte|suche mir|such mir)\b",
        r"\bshould\s+(?:book|buy|compare|draft|find|order|reply|research|schedule|send|shop|write)\b",
    )
    if any(re.search(pattern, padded) for pattern in direct_patterns):
        return True
    action_patterns = (
        r"\b(?:book|buy|compare|draft|find|order|renew|reply|reserve|respond|review|schedule|search|send|shop|write)\b",
        r"\b(?:buche|finde|formuliere|rauchfangkehrer|schicke|schick|schreibe|schreib|suche|termin)\b",
        r"\b(?:brauch|brauche|brauchst|brauchen)\b",
    )
    return any(re.search(pattern, padded) for pattern in action_patterns)


def _transcript_stage_notes(*values: Any) -> list[str]:
    notes: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _clean_text(str(value or "")).strip()
        lowered = normalized.lower()
        if not normalized or lowered in seen:
            continue
        seen.add(lowered)
        notes.append(normalized)
    return notes[:4]


def _ascii_fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return normalized.encode("ascii", "ignore").decode("ascii")


def _sha256_text(value: str) -> str:
    normalized = str(value or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def _parse_iso_datetime(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_topic_token(token: str) -> str:
    normalized = _ascii_fold_text(_clean_text(token).strip().lower())
    if not normalized:
        return ""
    return _TRANSCRIPT_SUPPRESSION_TOKEN_MAP.get(normalized, normalized)


def _topic_terms_from_fragment(fragment: str) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", _ascii_fold_text(fragment).lower()):
        normalized = _normalize_topic_token(token)
        if not normalized or normalized in _TRANSCRIPT_SUPPRESSION_STOPWORDS or len(normalized) < 3:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized)
    return tuple(terms[:6])


def _transcript_suppression_terms(text: str) -> tuple[str, ...]:
    normalized = _ascii_fold_text(_clean_text(text).strip().lower())
    if not normalized:
        return ()
    for pattern in _TRANSCRIPT_SUPPRESSION_PATTERNS:
        match = pattern.search(normalized)
        if match is None:
            continue
        topic = _clean_text(str(match.groupdict().get("topic") or "")).strip()
        terms = _topic_terms_from_fragment(topic)
        if terms:
            return terms
    return ()


def _transcript_topic_suppression(
    *,
    request_text: str,
    title: str = "",
    channel: str,
    signal_type: str,
    counterparty: str,
    observed_at: str,
) -> dict[str, Any] | None:
    terms = _transcript_suppression_terms(request_text)
    if not terms:
        return None
    return {
        "schema": "ea.proactive_topic_suppression.v1",
        "scope": "topic",
        "topic_hint": " ".join(terms),
        "terms": list(terms),
        "source_channel": channel,
        "source_signal_type": signal_type,
        "counterparty": counterparty,
        "observed_at": str(observed_at or "").strip(),
    }


def extract_proactive_suppression_directive(row: Mapping[str, Any]) -> dict[str, Any] | None:
    payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
    directive = payload.get("proactive_suppression") if isinstance(payload, Mapping) else None
    if not isinstance(directive, Mapping):
        return None
    terms = [
        _normalize_topic_token(str(item or ""))
        for item in list(directive.get("terms") or [])
        if _normalize_topic_token(str(item or ""))
    ]
    if not terms:
        return None
    return {
        "source_ref": str(row.get("source_ref") or "").strip(),
        "topic_hint": str(directive.get("topic_hint") or "").strip(),
        "terms": tuple(dict.fromkeys(terms)),
        "observed_at": str(directive.get("observed_at") or "").strip(),
    }


def signal_matches_proactive_suppression(row: Mapping[str, Any], suppression: Mapping[str, Any]) -> bool:
    search_text = _signal_search_text(row)
    if not search_text:
        return False
    normalized_text = _ascii_fold_text(_clean_text(search_text).lower())
    collapsed_text = re.sub(r"\s+", "", normalized_text)
    search_terms = {
        normalized
        for normalized in (
            _normalize_topic_token(token) for token in re.findall(r"[a-z0-9]+", normalized_text)
        )
        if normalized
    }
    suppression_terms = [
        _normalize_topic_token(str(item or ""))
        for item in list(suppression.get("terms") or [])
        if _normalize_topic_token(str(item or ""))
    ]
    if not suppression_terms:
        return False
    matched_terms: set[str] = set()
    for term in suppression_terms:
        if term in search_terms or term in normalized_text or term in collapsed_text:
            matched_terms.add(term)
    for index in range(len(suppression_terms) - 1):
        pair = f"{suppression_terms[index]}{suppression_terms[index + 1]}"
        if pair and pair in collapsed_text:
            matched_terms.add(suppression_terms[index])
            matched_terms.add(suppression_terms[index + 1])
    minimum_matches = 1 if len(suppression_terms) == 1 else 2
    return len(matched_terms) >= minimum_matches


def _signal_search_text(row: Mapping[str, Any]) -> str:
    payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
    ooda_loop = payload.get("ooda_loop") if isinstance(payload.get("ooda_loop"), Mapping) else {}
    act = ooda_loop.get("act") if isinstance(ooda_loop.get("act"), Mapping) else {}
    stage = act.get("stage") if isinstance(act.get("stage"), Mapping) else {}
    candidate_items = []
    for candidate in list(stage.get("candidate_items") or []) + list(stage.get("candidates") or []):
        if isinstance(candidate, Mapping):
            candidate_items.append(_first_text(candidate.get("label"), candidate.get("url")))
    parts = [
        row.get("title"),
        row.get("summary"),
        row.get("counterparty"),
        payload.get("event_type"),
        ooda_loop.get("summary"),
        act.get("summary"),
        stage.get("summary"),
        stage.get("research_query"),
        stage.get("requested_outcome"),
        " ".join(candidate_items),
        " ".join(str(item or "") for item in list(stage.get("selection_criteria") or [])),
    ]
    return " ".join(_clean_text(str(part or "")).strip() for part in parts if _clean_text(str(part or "")).strip())


def _transcript_assistant_ooda(
    *,
    request_text: str,
    title: str,
    channel: str,
    signal_type: str,
    counterparty: str,
    notes: Iterable[str] = (),
) -> dict[str, Any]:
    normalized_request = _clean_text(request_text).strip()
    lowered = normalized_request.lower()
    if not normalized_request or not _transcript_has_action_intent(lowered):
        return {}
    note_list = [str(item).strip() for item in notes if str(item).strip()][:4]
    delivery_window = _transcript_delivery_window_days(lowered)
    base_policy = "Research, compare, or draft only; require explicit approval before purchase, booking, cancellation, sending, posting, or commitment."
    draft_like = any(marker in lowered for marker in _TRANSCRIPT_DRAFT_TERMS)
    save_gmail_draft = _transcript_save_gmail_draft_requested(lowered)
    booking_like = any(marker in lowered for marker in _TRANSCRIPT_BOOKING_TERMS)
    compare_like = booking_like or any(marker in lowered for marker in _TRANSCRIPT_COMPARE_TERMS)
    discovery_like = any(marker in lowered for marker in _TRANSCRIPT_COMPARE_TERMS) or "gefunden" in lowered or " found " in f" {lowered} "
    if draft_like and discovery_like:
        research_query = _research_query_from_request(normalized_request)
        search_queries = _search_queries_from_request(research_query=research_query, request_text=normalized_request)
        locale = _transcript_request_locale(normalized_request)
        subject_prefix = "Anfrage" if locale == "de" else "Inquiry"
        selection_criteria = ["reversible before approval", "contact details visible", "reachability"]
        if booking_like:
            selection_criteria.extend(["availability", "timing"])
        else:
            selection_criteria.extend(["availability", "timing", "fit to request"])
        stage_summary = (
            "One researched inquiry draft saved to Gmail for review."
            if save_gmail_draft
            else "One researched inquiry draft ready for review before any send."
        )
        return {
            "reviewed": True,
            "observe": {
                "summary": _first_sentence(title or normalized_request),
                "channel": channel or "product",
                "signal_type": signal_type,
                "counterparty": counterparty,
            },
            "orient": {
                "summary": "This transcript sounds like a research task that should end in one reviewable draft once EA finds a plausible contact.",
                "tags": ["transcript", "research", "draft", "reversible"],
            },
            "decide": {
                "summary": (
                    "Decide whether EA should research candidates, draft one inquiry, and save it as a Gmail draft."
                    if save_gmail_draft
                    else "Decide whether EA should research candidates, draft one inquiry, and hold it for approval."
                ),
                "recommended_actions": [
                    "Research a shortlist, prepare one inquiry draft, and save it as a Gmail draft."
                    if save_gmail_draft
                    else "Research a shortlist, prepare one inquiry draft, and hold it for approval."
                ],
                "approval_required": not save_gmail_draft,
                "ignored_consequence": (
                    "A useful outreach draft may stay unsaved until the request becomes urgent."
                    if save_gmail_draft
                    else "A useful outreach draft may stay unstaged until the request becomes urgent."
                ),
            },
            "act": {
                "summary": (
                    "Research candidates, prepare one inquiry draft, and save it as a Gmail draft."
                    if save_gmail_draft
                    else "Research candidates, prepare one inquiry draft, and stage it for approval."
                ),
                "action_plan": [
                    "Clarify the candidate search from the transcript",
                    "Research a small reversible option set",
                    "Prepare one inquiry draft using the best reachable contact found",
                    "Save the draft to Gmail without sending it"
                    if save_gmail_draft
                    else "Hold the draft for explicit approval before any send",
                ],
                "external_action_policy": "Do not send the draft externally without explicit approval.",
                "stage": {
                    "kind": "research_packet" if save_gmail_draft else "approval_packet",
                    "summary": stage_summary,
                    "artifacts": ["shortlist", "comparison_table", "draft_text", "approval_prompt"],
                    "work_type": "draft",
                    "draft_mode": "research_backed_inquiry",
                    "draft_request_text": normalized_request,
                    "post_approval_action": "save_gmail_draft",
                    "auto_execute_action": "save_gmail_draft" if save_gmail_draft else "",
                    "subject_hint": f"{subject_prefix}: {_first_sentence(research_query or normalized_request)[:96]}",
                    "research_query": research_query or normalized_request,
                    "search_queries": search_queries or [research_query or normalized_request],
                    "selection_criteria": selection_criteria,
                    "comparison_dimensions": ["reachability", "contact details", "timing"],
                    "delivery_window": delivery_window if delivery_window is not None else "",
                    "locale": locale,
                    "notes": note_list,
                    "worker_hint": "browser_research",
                    "adapter_hint": "transcript_signal",
                },
            },
        }
    if draft_like:
        return {
            "reviewed": True,
            "observe": {
                "summary": _first_sentence(title or normalized_request),
                "channel": channel or "product",
                "signal_type": signal_type,
                "counterparty": counterparty,
            },
            "orient": {
                "summary": "This transcript sounds like a reply or message task that EA can draft safely before any send.",
                "tags": ["transcript", "draft", "reversible"],
            },
            "decide": {
                "summary": (
                    "Decide whether EA should prepare a concise draft and save it as a Gmail draft."
                    if save_gmail_draft
                    else "Decide whether EA should prepare a concise draft for review."
                ),
                "recommended_actions": [
                    "Draft a concise reply and save it as a Gmail draft."
                    if save_gmail_draft
                    else "Draft a concise reply for approval."
                ],
                "approval_required": not save_gmail_draft,
                "ignored_consequence": (
                    "A useful draft may stay unsaved until the thread becomes urgent."
                    if save_gmail_draft
                    else "A useful reply may stay unsent until the thread becomes urgent."
                ),
            },
            "act": {
                "summary": (
                    "Draft a concise reply and save it as a Gmail draft."
                    if save_gmail_draft
                    else "Draft a concise reply and stage it for approval."
                ),
                "action_plan": [
                    "Capture the requested reply from the transcript",
                    "Prepare one concise draft",
                    "Save the draft to Gmail without sending it"
                    if save_gmail_draft
                    else "Hold the draft for explicit approval before any send",
                ],
                "external_action_policy": "Do not send the draft externally without explicit approval.",
                "stage": {
                    "kind": "research_packet" if save_gmail_draft else "approval_packet",
                    "summary": (
                        "One draft reply saved to Gmail for review."
                        if save_gmail_draft
                        else "One draft reply ready for review before any send."
                    ),
                    "artifacts": ["draft_text", "approval_prompt"],
                    "work_type": "draft",
                    "post_approval_action": "save_gmail_draft",
                    "auto_execute_action": "save_gmail_draft" if save_gmail_draft else "",
                    "subject_hint": _first_sentence(title or normalized_request)[:120],
                    "draft_text": _draft_text_from_request(normalized_request),
                    "selection_criteria": ["match transcript intent", "keep it concise"],
                    "notes": note_list,
                },
            },
        }
    approval_required = any(marker in lowered for marker in _TRANSCRIPT_HIGH_RISK_TERMS)
    service_provider_like = _transcript_service_provider_request(lowered)
    review_or_approval = "approval" if approval_required else "review"
    stage_summary = (
        f"Research booking candidates and stage one reversible option for {review_or_approval}."
        if booking_like
        else f"Research a shortlist and stage one reversible option for {review_or_approval}."
        if compare_like
        else "Research the request and stage the smallest reversible next step."
    )
    stage_research_query = normalized_request
    stage_search_queries = [normalized_request]
    if booking_like or compare_like:
        compact_query = _research_query_from_request(normalized_request)
        if compact_query:
            stage_research_query = compact_query
            stage_search_queries = _search_queries_from_request(
                research_query=compact_query,
                request_text=normalized_request,
            ) or [compact_query]
    selection_criteria = ["reversible before approval"]
    comparison_dimensions: list[str] = []
    if booking_like:
        selection_criteria.extend(["availability", "cancellation flexibility"])
        comparison_dimensions.extend(["availability", "timing", "cancellation flexibility"])
    elif service_provider_like:
        selection_criteria.extend(["contact details visible", "reachability", "fit to request"])
        comparison_dimensions.extend(["reachability", "contact details", "timing"])
    elif compare_like:
        selection_criteria.extend(["price", "availability"])
        comparison_dimensions.extend(["price", "availability", "timing"])
    if delivery_window is not None:
        selection_criteria.append("fit the timing window stated in the transcript")
    return {
        "reviewed": True,
        "observe": {
            "summary": _first_sentence(title or normalized_request),
            "channel": channel or "product",
            "signal_type": signal_type,
            "counterparty": counterparty,
        },
        "orient": {
            "summary": "This transcript sounds like a task EA can research safely before any irreversible external action.",
            "tags": ["transcript", "assistant_task", "reversible"],
        },
        "decide": {
            "summary": "Decide whether EA should research options and stage one reversible next step.",
            "recommended_actions": [stage_summary],
            "approval_required": approval_required,
            "ignored_consequence": "A useful assistant task may slip until it turns into an urgent manual chore.",
        },
        "act": {
            "summary": stage_summary,
            "action_plan": [
                "Clarify the request from the transcript",
                "Research a small reversible option set",
                "Stage one recommended next step for review",
            ],
            "external_action_policy": base_policy,
            "stage": {
                "kind": "research_packet",
                "summary": stage_summary,
                "artifacts": (
                    ["booking_candidate", "comparison_table", "approval_prompt"]
                    if booking_like
                    else ["shortlist", "comparison_table", "approval_prompt"]
                    if compare_like
                    else ["research_summary", "approval_prompt"]
                ),
                "work_type": "compare_options" if compare_like else "research",
                "research_query": stage_research_query,
                "search_queries": stage_search_queries,
                "selection_criteria": selection_criteria,
                "comparison_dimensions": comparison_dimensions,
                "delivery_window": delivery_window if delivery_window is not None else "",
                "notes": note_list,
                "worker_hint": "browser_research",
                "adapter_hint": "transcript_signal",
            },
        },
    }


def observation_row_to_signal(
    *,
    observation_id: str,
    principal_id: str,
    channel: str,
    event_type: str,
    payload: Mapping[str, Any],
    created_at: str,
    source_id: str = "",
    external_id: str = "",
    dedupe_key: str = "",
) -> ProactiveSignal | None:
    ooda_loop = _normalize_ooda_loop(payload.get("ooda_loop")) if isinstance(payload.get("ooda_loop"), Mapping) else {}
    extra_payload: dict[str, Any] = {}
    extra_payload_key = ""
    proactive_suppression: dict[str, Any] | None = None
    if event_type == "office_signal_ooda_evaluated":
        observe = ooda_loop.get("observe") if isinstance(ooda_loop.get("observe"), Mapping) else {}
        decide = ooda_loop.get("decide") if isinstance(ooda_loop.get("decide"), Mapping) else {}
        title = _first_sentence(
            _first_text(
                decide.get("summary") if isinstance(decide, Mapping) else "",
                observe.get("summary") if isinstance(observe, Mapping) else "",
                payload.get("summary"),
                "Office signal needs review",
            )
        )
        summary = _first_text(
            ooda_loop.get("summary"),
            observe.get("summary") if isinstance(observe, Mapping) else "",
            payload.get("summary"),
        )
        counterparty = _first_text(
            observe.get("counterparty") if isinstance(observe, Mapping) else "",
            payload.get("counterparty"),
            payload.get("channel"),
            channel,
            "EA",
        )
        signal_type = _first_text(
            observe.get("signal_type") if isinstance(observe, Mapping) else "",
            payload.get("signal_type"),
            "office_signal",
        )
        due_at = _first_text(observe.get("due_at") if isinstance(observe, Mapping) else "")
    elif event_type == "commitment_candidate_staged":
        title = str(payload.get("title") or "Commitment candidate staged").strip()
        summary = f"EA staged a {payload.get('kind') or 'commitment'} candidate for review."
        counterparty = str(payload.get("counterparty") or "EA").strip()
        signal_type = "commitment_candidate"
        due_at = ""
    elif event_type == "property_scout_sync_completed":
        status = str(payload.get("status") or "processed").strip()
        scout_totals = _property_scout_sync_totals(payload)
        high_fit_total = scout_totals["high_fit_total"]
        review_total = scout_totals["review_total"]
        notified_total = scout_totals["notified_total"]
        failed_total = scout_totals["failed_total"]
        scanned_total = scout_totals["scanned_total"]
        filtered_low_fit_total = scout_totals["filtered_low_fit_total"]
        if high_fit_total or review_total or notified_total or failed_total:
            title = "Property scout needs attention" if failed_total else "Property scout found items to review"
            summary = (
                f"Property scout {status}: {high_fit_total} high-fit, {review_total} review, "
                f"{notified_total} notified, {failed_total} failed."
            )
        elif scanned_total > 0 or filtered_low_fit_total > 0:
            title = "Property scout found no viable matches"
            summary = (
                f"Property scout {status}: {scanned_total} scanned, {filtered_low_fit_total} filtered low-fit, "
                "0 review, 0 notified."
            )
            ooda_loop = _property_scout_zero_match_ooda(
                payload,
                scanned_total=scanned_total,
                filtered_low_fit_total=filtered_low_fit_total,
            )
            external_id = external_id or _property_scout_zero_match_external_id(payload, created_at=created_at)
        else:
            return None
        counterparty = "Property Scout"
        signal_type = "property_scout"
        due_at = ""
    elif event_type == "telegram.message":
        title = _first_sentence(str(payload.get("analysis_summary") or payload.get("text") or "Telegram message"))
        summary = str(payload.get("analysis_summary") or payload.get("text") or "").strip()
        counterparty = "Telegram"
        signal_type = "telegram_message"
        due_at = ""
        transcript_request = _transcript_request_text(
            payload.get("text"),
            payload.get("analysis_summary"),
            title,
        )
        if not ooda_loop:
            ooda_loop = _transcript_assistant_ooda(
                request_text=transcript_request,
                title=title,
                channel=channel,
                signal_type=signal_type,
                counterparty=counterparty,
            )
        proactive_suppression = _transcript_topic_suppression(
            request_text=transcript_request,
            title=title,
            channel=channel,
            signal_type=signal_type,
            counterparty=counterparty,
            observed_at=created_at,
        )
    elif event_type == "telegram_business.signal_candidate":
        if str(payload.get("signal_type") or "").strip() != "candidate":
            return None
        if payload.get("human_review_required") is not True:
            return None
        title = _first_sentence(str(payload.get("text_preview") or "Telegram Business signal candidate"))
        summary = str(payload.get("text_preview") or "").strip()
        counterparty = "Telegram Business"
        signal_type = "telegram_business_signal_candidate"
        due_at = ""
        external_id = external_id or str(payload.get("message_id") or payload.get("update_id") or "").strip()
        transcript_request = _transcript_request_text(
            payload.get("text_preview"),
            title,
        )
        if not ooda_loop:
            ooda_loop = _transcript_assistant_ooda(
                request_text=transcript_request,
                title=title,
                channel=channel,
                signal_type=signal_type,
                counterparty=counterparty,
                notes=_transcript_stage_notes(
                    "Telegram Business/Secretary candidate from an allowlisted chat.",
                    "Read-only ingest: do not reply or write memory before review.",
                ),
            )
        proactive_suppression = _transcript_topic_suppression(
            request_text=transcript_request,
            title=title,
            channel=channel,
            signal_type=signal_type,
            counterparty=counterparty,
            observed_at=created_at,
        )
    elif event_type == "alexa_history_indexed":
        alexa_fields = _alexa_history_payload_fields(payload)
        title = _first_text(alexa_fields.get("title"), _first_sentence(_alexa_transcript_text(payload), limit=140), "Alexa history")
        summary = _first_text(_alexa_transcript_text(payload), title)
        if not summary:
            summary = title
        counterparty = "Alexa"
        signal_type = "alexa_transcript"
        due_at = ""
        external_id = external_id or alexa_fields.get("history_entry_id", "") or source_id.removeprefix("alexa-history:")
        extra_payload_key = "alexa_history"
        if source_id:
            extra_payload["source_id"] = source_id
        if alexa_fields.get("history_entry_id"):
            extra_payload["history_entry_id"] = alexa_fields.get("history_entry_id", "")
        if alexa_fields.get("device_name"):
            extra_payload["device_name"] = alexa_fields.get("device_name", "")
        if alexa_fields.get("skill_name"):
            extra_payload["skill_name"] = alexa_fields.get("skill_name", "")
        transcript_request = _transcript_request_text(
            alexa_fields.get("utterance_text"),
            alexa_fields.get("transcript_excerpt"),
            alexa_fields.get("transcript_text"),
            title,
        )
        if not ooda_loop:
            ooda_loop = _transcript_assistant_ooda(
                request_text=transcript_request,
                title=title,
                channel=channel,
                signal_type=signal_type,
                counterparty=counterparty,
                notes=_transcript_stage_notes(
                    f"Device: {alexa_fields.get('device_name', '')}" if alexa_fields.get("device_name") else "",
                    f"Skill: {alexa_fields.get('skill_name', '')}" if alexa_fields.get("skill_name") else "",
                    f"Locale: {alexa_fields.get('locale', '')}" if alexa_fields.get("locale") else "",
                ),
            )
        proactive_suppression = _transcript_topic_suppression(
            request_text=transcript_request,
            title=title,
            channel=channel,
            signal_type=signal_type,
            counterparty=counterparty,
            observed_at=created_at,
        )
    elif event_type == "pocket_recording_archive_indexed":
        pocket_fields = _pocket_recording_payload_fields(payload)
        title = _first_text(pocket_fields.get("title"), "Pocket recording")
        summary = _first_text(_pocket_transcript_text(payload), title)
        if not summary:
            summary = title
        counterparty = "Pocket"
        signal_type = "pocket_transcript"
        due_at = ""
        external_id = external_id or pocket_fields.get("recording_id", "") or source_id.removeprefix("pocket-recording:")
        extra_payload_key = "pocket_recording"
        extra_payload.update(
            _pocket_recording_source_context(
                payload=payload,
                fields=pocket_fields,
                source_id=source_id,
                created_at=created_at,
            )
        )
        transcript_request = _transcript_request_text(
            pocket_fields.get("transcript_excerpt"),
            pocket_fields.get("transcript_text"),
            pocket_fields.get("summary_markdown"),
            title,
        )
        if not ooda_loop:
            ooda_loop = _transcript_assistant_ooda(
                request_text=transcript_request,
                title=title,
                channel=channel,
                signal_type=signal_type,
                counterparty=counterparty,
                notes=_transcript_stage_notes(
                    f"Topic keywords: {pocket_fields.get('topic_keywords_csv', '')}" if pocket_fields.get("topic_keywords_csv") else "",
                    f"Tags: {pocket_fields.get('tags_csv', '')}" if pocket_fields.get("tags_csv") else "",
                    f"Location: {pocket_fields.get('location_name', '')}" if pocket_fields.get("location_name") else "",
                ),
            )
        proactive_suppression = _transcript_topic_suppression(
            request_text=transcript_request,
            title=title,
            channel=channel,
            signal_type=signal_type,
            counterparty=counterparty,
            observed_at=created_at,
        )
    else:
        return None
    if not title and not summary:
        return None
    source_ref = dedupe_key or external_id or source_id or observation_id
    signal_payload = {
        "observation_id": observation_id,
        "principal_id": principal_id,
        "event_type": event_type,
        "created_at": created_at,
        "ooda_loop": ooda_loop,
        **({extra_payload_key: extra_payload} if extra_payload and extra_payload_key else {}),
    }
    if proactive_suppression is not None:
        signal_payload["proactive_suppression"] = proactive_suppression
    return ProactiveSignal(
        source_ref=f"observation:{source_ref}",
        signal_type=signal_type,
        channel=channel or "observation",
        title=_clean_text(title),
        summary=_clean_text(summary),
        counterparty=counterparty,
        due_at=due_at or None,
        external_id=external_id or observation_id,
        payload=signal_payload,
    )


def _property_scout_zero_match_ooda(
    payload: Mapping[str, Any],
    *,
    scanned_total: int,
    filtered_low_fit_total: int,
) -> dict[str, Any]:
    candidate_items = _property_scout_review_candidate_items(payload)
    source_urls = [str(item.get("url") or "").strip() for item in candidate_items if str(item.get("url") or "").strip()]
    summary = (
        f"Property scout scanned {scanned_total} listings and filtered out {filtered_low_fit_total} as low-fit, "
        "so the current search may need a deliberate filter review before the market shifts again."
    )
    action = "Review the strongest live source first and stage a reversible filter-adjustment recommendation."
    policy = "Do not change search criteria, contact brokers, schedule viewings, or commit without explicit approval."
    return {
        "reviewed": True,
        "observe": {
            "summary": summary,
            "channel": "product",
            "signal_type": "property_scout_gap",
            "counterparty": "Property Scout",
        },
        "orient": {
            "summary": "A paid assistant should surface when real inventory exists but current preferences produce no viable matches.",
            "tags": ["property_scout", "zero_match", "review_filters"],
        },
        "decide": {
            "summary": "Approve whether EA should stage one filter-review packet from the strongest live source.",
            "recommended_actions": [action],
            "approval_required": True,
            "ignored_consequence": "Good inventory may slip by while outdated filters or preferences stay unchallenged.",
        },
        "act": {
            "summary": action,
            "action_plan": [
                "Inspect the live source pages that still show active supply",
                "Compare whether the current fit threshold looks too strict",
                "Stage one reversible recommendation before any preference or outreach change",
            ],
            "stage": {
                "kind": "research_packet",
                "summary": "One filter-review packet with the best source to inspect first.",
                "status": "planned",
                "approval_gate": policy,
                "artifacts": ["shortlist", "candidate_link", "approval_prompt"],
                "candidate_items": candidate_items,
                "target_sites": source_urls,
                "selection_criteria": ["active_supply", "reversibility", "signal_freshness"],
                "work_type": "compare_options",
                "research_query": "Review why the current property scout filters produced zero viable matches and which live source should be inspected first.",
            },
            "external_action_policy": policy,
        },
    }


def _property_scout_review_candidate_items(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in payload.get("sources") or []:
        if not isinstance(source, Mapping):
            continue
        url = str(source.get("source_url") or "").strip()
        label = str(source.get("source_label") or source.get("platform") or "Property source").strip()
        scanned = max(_safe_int(source.get("listing_total")), _safe_int(source.get("scanned_listing_total")), _safe_int(source.get("raw_listing_total")))
        filtered = _safe_int(source.get("filtered_low_fit_total"))
        if not url:
            continue
        rows.append(
            {
                "label": label,
                "url": url,
                "scanned_listing_total": scanned,
                "filtered_low_fit_total": filtered,
                "reason": f"{scanned} scanned, {filtered} low-fit",
            }
        )
    rows.sort(
        key=lambda item: (
            int(item.get("scanned_listing_total") or 0),
            -int(item.get("filtered_low_fit_total") or 0),
            str(item.get("label") or ""),
        ),
        reverse=True,
    )
    return rows[:5]


def _property_scout_sync_totals(payload: Mapping[str, Any]) -> dict[str, int]:
    return {
        "high_fit_total": _safe_int(payload.get("high_fit_total")),
        "review_total": _safe_int(payload.get("review_created_total")) + _safe_int(payload.get("review_existing_total")),
        "notified_total": _safe_int(payload.get("notified_total")) + _safe_int(payload.get("watch_notified_total")),
        "failed_total": _safe_int(payload.get("failed_total")),
        "scanned_total": max(
            _safe_int(payload.get("listing_total")),
            _safe_int(payload.get("scanned_listing_total")),
            _safe_int(payload.get("raw_listing_total")),
        ),
        "filtered_low_fit_total": _safe_int(payload.get("filtered_low_fit_total")),
    }


def _property_scout_zero_match_external_id(payload: Mapping[str, Any], *, created_at: str = "") -> str:
    urls = [str(item.get("url") or "") for item in _property_scout_review_candidate_items(payload)]
    material_parts = [url for url in urls if url]
    generated_day = _day_bucket(_first_text(payload.get("generated_at"), created_at))
    if generated_day:
        material_parts.append(f"day:{generated_day}")
    scanned_total = max(
        _safe_int(payload.get("listing_total")),
        _safe_int(payload.get("scanned_listing_total")),
        _safe_int(payload.get("raw_listing_total")),
    )
    filtered_low_fit_total = _safe_int(payload.get("filtered_low_fit_total"))
    material_parts.append(f"scanned:{scanned_total}")
    material_parts.append(f"low_fit:{filtered_low_fit_total}")
    material = "|".join(part for part in material_parts if part)
    if not material:
        material = "property_scout_zero_match"
    return f"property_scout_zero_match:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _observation_coalescing_key(*, event_type: str, payload: Mapping[str, Any]) -> str:
    if str(event_type or "").strip() != "property_scout_sync_completed":
        return ""
    scout_totals = _property_scout_sync_totals(payload)
    has_attention_items = any(
        scout_totals[key] > 0
        for key in ("high_fit_total", "review_total", "notified_total", "failed_total")
    )
    if has_attention_items or (
        scout_totals["scanned_total"] <= 0 and scout_totals["filtered_low_fit_total"] <= 0
    ):
        return ""
    return _property_scout_zero_match_family_key(payload)


def _property_scout_zero_match_family_key(payload: Mapping[str, Any]) -> str:
    candidate_items = _property_scout_review_candidate_items(payload)
    material_parts = [
        str(item.get("url") or "").strip()
        for item in candidate_items
        if str(item.get("url") or "").strip()
    ]
    if not material_parts:
        material_parts.extend(
            sorted(
                {
                    str(source.get("platform") or source.get("source_label") or "").strip()
                    for source in payload.get("sources") or []
                    if isinstance(source, Mapping) and str(source.get("platform") or source.get("source_label") or "").strip()
                }
            )
        )
    location_query = _clean_text(str(payload.get("location_query") or "")).strip().lower()
    if location_query:
        material_parts.append(f"location:{location_query}")
    country_code = _clean_text(str(payload.get("country_code") or "")).strip().lower()
    if country_code:
        material_parts.append(f"country:{country_code}")
    selected_platforms = [
        _clean_text(str(item or "")).strip().lower()
        for item in list(payload.get("selected_platforms") or [])
        if _clean_text(str(item or "")).strip()
    ]
    material_parts.extend(f"platform:{item}" for item in sorted(set(selected_platforms)))
    material = "|".join(part for part in material_parts if part)
    if not material:
        material = "property_scout_zero_match"
    return f"property_scout_zero_match_family:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _day_bucket(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return ""


def _load_json_source(source: SignalSource, *, base_dir: Path, timeout_seconds: int) -> list[ProactiveSignal]:
    payload = json.loads(_read_ref(source.ref, base_dir=base_dir, timeout_seconds=timeout_seconds))
    if isinstance(payload, dict):
        rows = payload.get("signals") or payload.get("items") or payload.get("entries") or []
    else:
        rows = payload
    if not isinstance(rows, list):
        return []
    return [
        _signal_from_row(row, source=source, index=index)
        for index, row in enumerate(rows)
        if isinstance(row, Mapping)
    ]


def _load_jsonl_source(source: SignalSource, *, base_dir: Path, timeout_seconds: int) -> list[ProactiveSignal]:
    rows: list[ProactiveSignal] = []
    for index, line in enumerate(_read_ref(source.ref, base_dir=base_dir, timeout_seconds=timeout_seconds).splitlines()):
        normalized = line.strip()
        if not normalized:
            continue
        payload = json.loads(normalized)
        if isinstance(payload, Mapping):
            rows.append(_signal_from_row(payload, source=source, index=index))
    return rows


def _load_rss_source(source: SignalSource, *, base_dir: Path, timeout_seconds: int) -> list[ProactiveSignal]:
    raw = _read_ref(source.ref, base_dir=base_dir, timeout_seconds=timeout_seconds)
    root = ElementTree.fromstring(raw)
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    signals: list[ProactiveSignal] = []
    for index, item in enumerate(items[: source.limit]):
        title = _xml_text(item, "title")
        summary = _xml_text(item, "description") or _xml_text(item, "summary") or _xml_text(item, "content")
        link = _xml_text(item, "link") or _atom_link(item)
        published = _xml_text(item, "pubDate") or _xml_text(item, "published") or _xml_text(item, "updated")
        source_ref = f"{source.channel}:{link or title or index}"
        signals.append(
            ProactiveSignal(
                source_ref=source_ref,
                signal_type=source.signal_type,
                channel=source.channel,
                title=_clean_text(title),
                summary=_clean_text(summary),
                counterparty=source.counterparty,
                external_id=link,
                payload={"published": published, "source": source.ref},
            )
        )
    return signals


def _load_teable_source(source: SignalSource, *, timeout_seconds: int) -> list[ProactiveSignal]:
    table_id = _teable_table_id(source.ref)
    if not table_id:
        return []
    api_key = str(os.getenv("TEABLE_API_KEY") or "").strip()
    if not api_key:
        raise ValueError("teable_api_key_missing")
    base_url = str(os.getenv("TEABLE_BASE_URL") or "https://app.teable.ai").strip().rstrip("/")
    query = urllib.parse.urlencode({"fieldKeyType": "name", "cellFormat": "json", "take": source.limit, "skip": 0})
    request = urllib.request.Request(
        f"{base_url}/api/table/{urllib.parse.quote(table_id)}/record?{query}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "EA-Proactive-OODA/1.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    records = [dict(item) for item in payload.get("records") or [] if isinstance(item, Mapping)]
    signals: list[ProactiveSignal] = []
    for index, record in enumerate(records):
        fields = dict(record.get("fields") or {})
        record_id = str(record.get("id") or index).strip()
        signals.append(_signal_from_teable_record(fields, record_id=record_id, source=source))
    return signals


def _load_opportunity_rules_source(
    source: SignalSource,
    *,
    base_dir: Path,
    timeout_seconds: int,
    principal_id: str = "",
    opportunity_state_store: JsonOodaStateStore | None = None,
    persist_opportunity_state: bool = True,
) -> list[ProactiveSignal]:
    payload: Any
    if source.ref:
        payload = json.loads(_read_ref(source.ref, base_dir=base_dir, timeout_seconds=timeout_seconds))
    else:
        payload = source.config or {}
    if isinstance(payload, list):
        rules = payload
    elif isinstance(payload, Mapping):
        rules = payload.get("rules") or payload.get("items") or []
    else:
        rules = []
    if not isinstance(rules, list):
        return []
    now_epoch = int(time.time())
    signals: list[ProactiveSignal] = []
    for index, raw_rule in enumerate(rules[: source.limit]):
        if not isinstance(raw_rule, Mapping) or not _truthy_default(raw_rule.get("enabled"), default=True):
            continue
        signal = _opportunity_rule_to_signal(
            raw_rule,
            source=source,
            index=index,
            now_epoch=now_epoch,
            timeout_seconds=timeout_seconds,
            principal_id=principal_id,
            opportunity_state_store=opportunity_state_store,
            persist_opportunity_state=persist_opportunity_state,
        )
        if signal is not None:
            signals.append(signal)
    return signals


def _opportunity_rule_to_signal(
    rule: Mapping[str, Any],
    *,
    source: SignalSource,
    index: int,
    now_epoch: int,
    timeout_seconds: int,
    principal_id: str = "",
    opportunity_state_store: JsonOodaStateStore | None = None,
    persist_opportunity_state: bool = True,
) -> ProactiveSignal | None:
    trigger = rule.get("trigger") if isinstance(rule.get("trigger"), Mapping) else {}
    rule_id = _rule_id(rule, fallback=f"rule-{index}")
    cadence_days = _safe_int(rule.get("cadence_days") or rule.get("cooldown_days") or 14)
    cadence_seconds = max(cadence_days, 1) * 86400
    evaluation = _evaluate_opportunity_rule_trigger(trigger, timeout_seconds=timeout_seconds)
    trigger_kind = evaluation.kind or "always"
    weather_context = evaluation.weather_context
    runtime = _opportunity_trigger_runtime(
        rule,
        trigger=trigger,
        rule_id=rule_id,
        trigger_kind=trigger_kind,
        matched=evaluation.matched,
        now_epoch=now_epoch,
        cadence_seconds=cadence_seconds,
        principal_id=principal_id,
        opportunity_state_store=opportunity_state_store,
        persist_opportunity_state=persist_opportunity_state,
    )
    if runtime is None:
        return None
    location = _clean_text(str(trigger.get("location") or trigger.get("location_name") or "local weather"))
    title = _clean_text(str(rule.get("title") or "Assistant opportunity"))
    base_summary = _clean_text(str(rule.get("summary") or rule.get("brief") or "A potentially useful opportunity is worth attention."))
    summary = base_summary
    if weather_context:
        summary = f"{base_summary} {_weather_sentence(weather_context, location=location)}"
    action_text = _clean_text(str(rule.get("action") or rule.get("recommended_action") or "Ask the user whether to take the next step."))
    ignored = _clean_text(str(rule.get("ignored_consequence") or "A useful low-effort opportunity may slip again."))
    counterparty = _clean_text(str(rule.get("counterparty") or source.counterparty or "EA"))
    approval_required = _truthy_default(rule.get("approval_required"), default=True)
    source_ref = f"opportunity:{rule_id}:{runtime.signal_key}"
    action_plan = _string_list(rule.get("action_plan") or rule.get("plan"))
    external_action_policy = _clean_text(
        str(
            rule.get("external_action_policy")
            or rule.get("guardrail")
            or "Research, prepare, or stage external actions only; ask the user before purchase, booking, posting, or sending."
        )
    )
    stage = _opportunity_rule_stage(
        rule,
        action_text=action_text,
        external_action_policy=external_action_policy,
    )
    return ProactiveSignal(
        source_ref=source_ref,
        signal_type=_clean_text(str(rule.get("signal_type") or source.signal_type or "opportunity")),
        channel=_clean_text(str(rule.get("channel") or source.channel or "assistant_opportunity")),
        title=title,
        summary=summary,
        counterparty=counterparty,
        due_at=_clean_text(str(rule.get("due_at") or "")) or None,
        external_id=_short_hash(f"{rule_id}:{runtime.signal_key}:{title}"),
        payload={
            "source": "opportunity_rules",
            "rule_id_hash": _short_hash(rule_id),
            "trigger_kind": trigger_kind,
            "ooda_loop": {
                "reviewed": True,
                "observe": {
                    "summary": title,
                    "channel": source.channel or "assistant_opportunity",
                    "signal_type": rule.get("signal_type") or "opportunity",
                    "counterparty": counterparty,
                },
                "orient": {
                    "summary": summary,
                    "tags": ["assistant_opportunity", "care", "cadence"],
                },
                "decide": {
                    "summary": _clean_text(str(rule.get("decision") or "Decide whether to pursue this opportunity now.")),
                    "recommended_actions": [action_text],
                    "approval_required": approval_required,
                    "ignored_consequence": ignored,
                },
                "act": {
                    "summary": action_text,
                    "action_plan": list(action_plan),
                    "external_action_policy": external_action_policy,
                    "stage": stage,
                },
                "trigger": {
                    "kind": trigger_kind,
                    "memory_mode": _trigger_memory_mode(rule, trigger=trigger, trigger_kind=trigger_kind),
                    "occurrence": runtime.occurrence,
                    "signal_key": runtime.signal_key,
                },
            },
        },
    )


def _opportunity_rule_stage(
    rule: Mapping[str, Any],
    *,
    action_text: str,
    external_action_policy: str,
) -> dict[str, Any]:
    raw_stage = rule.get("stage") if isinstance(rule.get("stage"), Mapping) else {}
    stage_kind = _clean_text(
        str(
            raw_stage.get("kind")
            or raw_stage.get("stage_kind")
            or raw_stage.get("type")
            or rule.get("stage_kind")
            or rule.get("stage_type")
            or "approval_packet"
        )
    )
    summary = _clean_text(
        str(
            raw_stage.get("summary")
            or raw_stage.get("description")
            or rule.get("stage_summary")
            or action_text
            or "Prepare one reversible next step for user approval."
        )
    )
    artifacts = _string_list(
        raw_stage.get("artifacts")
        or raw_stage.get("expected_artifacts")
        or rule.get("stage_artifacts")
        or rule.get("expected_artifacts")
    )
    approval_gate = _clean_text(
        str(
            raw_stage.get("approval_gate")
            or raw_stage.get("external_action_policy")
            or rule.get("approval_gate")
            or external_action_policy
        )
    )
    stage: dict[str, Any] = {
        "kind": stage_kind or "approval_packet",
        "summary": summary,
        "status": _clean_text(str(raw_stage.get("status") or rule.get("stage_status") or "planned")) or "planned",
        "approval_gate": approval_gate,
        "artifacts": list(artifacts),
    }
    for key in ("worker_hint", "adapter_hint"):
        value = _clean_text(str(raw_stage.get(key) or rule.get(key) or ""))
        if value:
            stage[key] = value
    for key in (
        "candidate_items",
        "candidates",
        "links",
        "draft",
        "draft_text",
        "draft_mode",
        "draft_request_text",
        "cart_url",
        "approval_url",
        "booking_options",
        "constraints",
        "evidence_refs",
        "work_type",
        "safe_work_type",
        "task_type",
        "worker_task",
        "worker_status",
        "work_status",
        "research_query",
        "search_queries",
        "target_sites",
        "selection_criteria",
        "comparison_dimensions",
        "budget",
        "deadline",
        "delivery_window",
        "recipient_context",
        "recipient_email",
        "recipient",
        "delivery_recipient_email",
        "counterparty_email",
        "locale",
        "currency",
        "quantity",
        "preferences",
        "requirements",
        "exclusions",
        "notes",
        "subject",
        "subject_hint",
        "post_approval_action",
        "auto_execute_action",
        "approved_action",
        "gmail_thread_id",
        "thread_id",
        "gmail_in_reply_to",
        "in_reply_to",
        "gmail_references",
        "references",
        "google_binding_id",
        "google_account_email",
        "account_email",
    ):
        if key in raw_stage:
            stage[key] = raw_stage.get(key)
        elif key in rule:
            stage[key] = rule.get(key)
    return stage


def _evaluate_opportunity_rule_trigger(
    trigger: Mapping[str, Any],
    *,
    timeout_seconds: int,
) -> OpportunityTriggerEvaluation:
    kind = str(trigger.get("kind") or "always").strip().lower()
    if kind in {"", "always"}:
        return OpportunityTriggerEvaluation(kind="always", matched=True)
    if kind in {"cooler_weather", "weather_below", "weather_at_or_below"}:
        context = _weather_context(trigger, timeout_seconds=timeout_seconds)
        if not context:
            return OpportunityTriggerEvaluation(kind=kind, matched=False)
        threshold = _float_value(
            trigger.get("temperature_at_or_below_c"),
            trigger.get("max_temperature_c"),
            trigger.get("threshold_c"),
        )
        if threshold is None:
            threshold = 24.0
        values = [value for value in (context.get("current_temperature_c"), context.get("min_forecast_temperature_c")) if isinstance(value, (int, float))]
        return OpportunityTriggerEvaluation(kind=kind, matched=any(float(value) <= threshold for value in values), weather_context=context)
    return OpportunityTriggerEvaluation(kind=kind or "always", matched=False)


def _opportunity_trigger_runtime(
    rule: Mapping[str, Any],
    *,
    trigger: Mapping[str, Any],
    rule_id: str,
    trigger_kind: str,
    matched: bool,
    now_epoch: int,
    cadence_seconds: int,
    principal_id: str,
    opportunity_state_store: JsonOodaStateStore | None,
    persist_opportunity_state: bool,
) -> OpportunityTriggerRuntime | None:
    memory_mode = _trigger_memory_mode(rule, trigger=trigger, trigger_kind=trigger_kind)
    if memory_mode == "periodic" or not principal_id or opportunity_state_store is None:
        if not matched:
            return None
        period = now_epoch // max(cadence_seconds, 1)
        return OpportunityTriggerRuntime(signal_key=f"period-{period}", occurrence=period, state={})

    previous_state = opportunity_state_store.load_opportunity_rule_state(principal_id, rule_id)
    previous_condition = _truthy_default(previous_state.get("last_condition"), default=False)
    occurrence = max(_safe_int(previous_state.get("occurrence")), 0)
    first_matched_at = _safe_int(previous_state.get("first_matched_at"))
    if matched and not previous_condition:
        occurrence += 1
        first_matched_at = now_epoch
    elif not matched:
        first_matched_at = None

    next_state: dict[str, Any] = {
        "last_condition": bool(matched),
        "occurrence": occurrence,
    }
    if first_matched_at is not None:
        next_state["first_matched_at"] = first_matched_at

    if persist_opportunity_state:
        opportunity_state_store.save_opportunity_rule_state(principal_id, rule_id, next_state)
    if not matched or occurrence <= 0:
        return None

    signal_key = f"occurrence-{occurrence}"
    if _rule_repeats_while_true(rule, trigger=trigger):
        anchor_epoch = first_matched_at or now_epoch
        period = max((now_epoch - anchor_epoch) // max(cadence_seconds, 1), 0)
        signal_key = f"{signal_key}:period-{period}"
    return OpportunityTriggerRuntime(signal_key=signal_key, occurrence=occurrence, state=next_state)


def _trigger_memory_mode(rule: Mapping[str, Any], *, trigger: Mapping[str, Any], trigger_kind: str) -> str:
    explicit = _clean_text(
        str(
            rule.get("trigger_memory_mode")
            or rule.get("retrigger_mode")
            or trigger.get("memory_mode")
            or trigger.get("retrigger_mode")
            or ""
        )
    ).lower()
    if explicit in {"edge", "stateful_edge", "rearm_on_false"}:
        return "edge"
    if explicit in {"periodic", "cadence"}:
        return "periodic"
    return "periodic" if trigger_kind == "always" else "edge"


def _rule_repeats_while_true(rule: Mapping[str, Any], *, trigger: Mapping[str, Any]) -> bool:
    value = rule.get("repeat_while_true")
    if value is None:
        value = trigger.get("repeat_while_true")
    return _truthy_default(value, default=False)


def _weather_context(trigger: Mapping[str, Any], *, timeout_seconds: int) -> dict[str, float] | None:
    current = _float_value(trigger.get("current_temperature_c"), trigger.get("temperature_c"))
    hourly_values = _float_list(trigger.get("hourly_temperature_c") or trigger.get("forecast_temperature_c"))
    if current is not None or hourly_values:
        values = ([current] if current is not None else []) + hourly_values
        return {
            "current_temperature_c": float(current if current is not None else values[0]),
            "min_forecast_temperature_c": float(min(values)),
        }
    latitude = _float_value(trigger.get("latitude"), trigger.get("lat"))
    longitude = _float_value(trigger.get("longitude"), trigger.get("lon"), trigger.get("lng"))
    if latitude is None or longitude is None:
        return None
    forecast_hours = max(_safe_int(trigger.get("forecast_hours") or 48), 1)
    params = urllib.parse.urlencode(
        {
            "latitude": f"{latitude:.5f}",
            "longitude": f"{longitude:.5f}",
            "current": "temperature_2m",
            "hourly": "temperature_2m",
            "forecast_days": 3,
            "timezone": "auto",
        }
    )
    request = urllib.request.Request(
        f"https://api.open-meteo.com/v1/forecast?{params}",
        headers={"User-Agent": "EA-Proactive-OODA/1.0"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    current_payload = payload.get("current") if isinstance(payload.get("current"), Mapping) else {}
    hourly_payload = payload.get("hourly") if isinstance(payload.get("hourly"), Mapping) else {}
    current_temperature = _float_value(current_payload.get("temperature_2m"))
    forecast_temperatures = _float_list(hourly_payload.get("temperature_2m"))[:forecast_hours]
    values = ([current_temperature] if current_temperature is not None else []) + forecast_temperatures
    if not values:
        return None
    return {
        "current_temperature_c": float(current_temperature if current_temperature is not None else values[0]),
        "min_forecast_temperature_c": float(min(values)),
    }


def _weather_sentence(context: Mapping[str, float], *, location: str) -> str:
    current = context.get("current_temperature_c")
    minimum = context.get("min_forecast_temperature_c")
    if isinstance(current, (int, float)) and isinstance(minimum, (int, float)):
        return f"{location} is about {current:.1f} C now, with a near-term low around {minimum:.1f} C."
    if isinstance(current, (int, float)):
        return f"{location} is about {current:.1f} C now."
    return ""


def _rule_id(rule: Mapping[str, Any], *, fallback: str) -> str:
    raw = str(rule.get("id") or rule.get("name") or "").strip()
    if raw:
        return re.sub(r"[^a-zA-Z0-9_.:-]+", "-", raw).strip("-") or fallback
    digest = hashlib.sha256(json.dumps(dict(rule), sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
    return f"{fallback}-{digest}"


def _truthy_default(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "n", "off", "disabled"}:
        return False
    return default


def _string_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (_clean_text(value),) if value.strip() else ()
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(_clean_text(str(item or "")) for item in value if str(item or "").strip())


def _float_value(*values: Any) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _float_list(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)):
        return []
    values: list[float] = []
    for item in value:
        parsed = _float_value(item)
        if parsed is not None:
            values.append(parsed)
    return values


def _signal_from_teable_record(fields: Mapping[str, Any], *, record_id: str, source: SignalSource) -> ProactiveSignal:
    field_map = {
        "source_ref": "source_ref",
        "signal_type": "signal_type",
        "channel": "channel",
        "title": "title",
        "summary": "summary",
        "counterparty": "counterparty",
        "due_at": "due_at",
        "external_id": "external_id",
        **{str(key): str(value) for key, value in dict(source.field_map or {}).items()},
    }
    title = _field_text(fields, field_map["title"])
    summary = _field_text(fields, field_map["summary"])
    source_ref = _field_text(fields, field_map["source_ref"]) or f"{source.channel}:teable:{source.ref}:{record_id}"
    signal_type = _field_text(fields, field_map["signal_type"]) or source.signal_type
    channel = _field_text(fields, field_map["channel"]) or source.channel
    counterparty = _field_text(fields, field_map["counterparty"]) or source.counterparty
    due_at = _field_text(fields, field_map["due_at"])
    external_id = _field_text(fields, field_map["external_id"]) or record_id
    return ProactiveSignal(
        source_ref=source_ref,
        signal_type=signal_type,
        channel=channel,
        title=_clean_text(title),
        summary=_clean_text(summary),
        counterparty=_clean_text(counterparty),
        due_at=due_at or None,
        external_id=external_id,
        payload={"source": "teable", "table": source.ref, "record_id": record_id},
    )


def _signal_from_row(row: Mapping[str, Any], *, source: SignalSource, index: int) -> ProactiveSignal:
    merged = dict(row)
    merged.setdefault("channel", source.channel)
    merged.setdefault("signal_type", source.signal_type)
    if source.counterparty:
        merged.setdefault("counterparty", source.counterparty)
    if not str(merged.get("source_ref") or "").strip():
        source_ref = str(merged.get("url") or merged.get("link") or merged.get("external_id") or "").strip()
        merged["source_ref"] = source_ref or f"{source.channel}:{source.ref}:{index}"
    return ProactiveSignal.from_mapping(merged)


def _candidate_principals(principal_id: str) -> list[str]:
    ordered: list[str] = []
    for value in (
        principal_id,
        os.getenv("EA_TELEGRAM_DEFAULT_PRINCIPAL_ID"),
        os.getenv("EA_DEFAULT_PRINCIPAL_ID"),
    ):
        normalized = str(value or "").strip()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return ordered


def _read_ref(ref: str, *, base_dir: Path, timeout_seconds: int) -> str:
    if _is_url(ref):
        request = urllib.request.Request(ref, headers={"User-Agent": "EA-Proactive-OODA/1.0"})
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.read().decode("utf-8", errors="replace")
    path = Path(ref)
    if not path.is_absolute():
        path = base_dir / path
    return path.read_text(encoding="utf-8")


def _infer_source_type(ref: str) -> str:
    lowered = str(ref or "").lower()
    if lowered.startswith("tbl"):
        return "teable"
    if lowered.endswith(".jsonl"):
        return "jsonl"
    if lowered.endswith(".xml") or lowered.endswith(".rss"):
        return "rss"
    return "json"


def _is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _xml_text(item: ElementTree.Element, tag: str) -> str:
    node = item.find(tag)
    if node is None:
        node = item.find(f"{{http://www.w3.org/2005/Atom}}{tag}")
    return str(node.text or "").strip() if node is not None else ""


def _atom_link(item: ElementTree.Element) -> str:
    node = item.find("{http://www.w3.org/2005/Atom}link")
    if node is None:
        return ""
    return str(node.attrib.get("href") or "").strip()


def _clean_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(without_tags.split()).strip()


def _first_sentence(value: str, limit: int = 140) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    match = re.search(r"(?<=[.!?])\s+", cleaned)
    first = cleaned[: match.start()].strip() if match else cleaned
    if len(first) <= limit:
        return first
    return first[: limit - 3].rstrip() + "..."


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _teable_table_id(ref: str) -> str:
    normalized = str(ref or "").strip()
    if normalized.startswith("teable:"):
        return normalized.split(":", 1)[1].strip()
    return normalized


def _field_text(fields: Mapping[str, Any], name: str) -> str:
    if not name:
        return ""
    value = fields.get(name)
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(_clean_text(str(item or "")) for item in value if str(item or "").strip())
    if isinstance(value, Mapping):
        return _clean_text(json.dumps(value, ensure_ascii=True, sort_keys=True))
    return _clean_text(str(value))


def _source_error_label(source: SignalSource, exc: Exception) -> str:
    source_type = _clean_text(source.source_type or "unknown")
    channel = _clean_text(source.channel or "discovery")
    ref_hash = _short_hash(source.ref)
    return f"{channel}:{source_type}:{exc.__class__.__name__}:{ref_hash}"


def _short_hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:12]


def _normalize_ooda_loop(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, Any] = {}
    for key in ("summary", "actor", "reviewed", "reviewed_at"):
        if key in value:
            normalized[key] = value[key]
    for section_name in ("observe", "orient", "decide", "act", "ltd_review"):
        section = value.get(section_name)
        if isinstance(section, Mapping):
            normalized[section_name] = _compact_mapping(section)
    return normalized


def _compact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    compacted: dict[str, Any] = {}
    for key, raw in value.items():
        if isinstance(raw, str):
            compacted[str(key)] = _clean_text(raw)
        elif isinstance(raw, (int, float, bool)) or raw is None:
            compacted[str(key)] = raw
        elif isinstance(raw, list):
            compacted[str(key)] = [_compact_value(item) for item in raw[:10]]
        elif isinstance(raw, Mapping):
            compacted[str(key)] = _compact_mapping(raw)
    return compacted


def _compact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return _compact_mapping(value)
    return _clean_text(str(value))


def _first_text(*values: Any) -> str:
    for value in values:
        normalized = _clean_text(str(value or ""))
        if normalized:
            return normalized
    return ""
