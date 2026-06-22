from __future__ import annotations

import json
import re
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from xml.etree import ElementTree

from app.services.proactive_ooda_service import ProactiveSignal


@dataclass(frozen=True)
class SignalSource:
    source_type: str
    ref: str
    channel: str = "discovery"
    signal_type: str = "external_signal"
    counterparty: str = ""
    limit: int = 20
    field_map: Mapping[str, str] | None = None

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
        )


@dataclass(frozen=True)
class SignalDiscoveryResult:
    signals: tuple[ProactiveSignal, ...]
    errors: tuple[str, ...]


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
) -> list[ProactiveSignal]:
    signals: list[ProactiveSignal] = []
    for source in sources:
        signals.extend(_discover_source(source, base_dir=base_dir, timeout_seconds=timeout_seconds))
    return signals


def discover_signals_resilient(
    *,
    sources: Iterable[SignalSource],
    base_dir: Path,
    timeout_seconds: int = 20,
) -> SignalDiscoveryResult:
    signals: list[ProactiveSignal] = []
    errors: list[str] = []
    for source in sources:
        try:
            signals.extend(_discover_source(source, base_dir=base_dir, timeout_seconds=timeout_seconds))
        except Exception as exc:
            errors.append(_source_error_label(source, exc))
    return SignalDiscoveryResult(signals=tuple(signals), errors=tuple(errors))


def _discover_source(source: SignalSource, *, base_dir: Path, timeout_seconds: int) -> list[ProactiveSignal]:
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
    )
    principals = _candidate_principals(principal_id)
    try:
        with psycopg.connect(url, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select observation_id, principal_id, channel, event_type, payload_json, created_at, source_id, external_id, dedupe_key
                    from observation_events
                    where principal_id = any(%s)
                      and event_type = any(%s)
                      and created_at >= now() - (%s || ' hours')::interval
                    order by created_at desc
                    limit %s
                    """,
                    (principals, list(event_types), int(lookback_hours), int(limit)),
                )
                rows = cursor.fetchall()
    except Exception:
        return []
    signals: list[ProactiveSignal] = []
    for row in rows:
        signal = observation_row_to_signal(
            observation_id=str(row[0] or ""),
            principal_id=str(row[1] or ""),
            channel=str(row[2] or ""),
            event_type=str(row[3] or ""),
            payload=row[4] if isinstance(row[4], Mapping) else {},
            created_at=str(row[5] or ""),
            source_id=str(row[6] or ""),
            external_id=str(row[7] or ""),
            dedupe_key=str(row[8] or ""),
        )
        if signal:
            signals.append(signal)
    return signals


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
        high_fit_total = _safe_int(payload.get("high_fit_total"))
        review_total = _safe_int(payload.get("review_created_total")) + _safe_int(payload.get("review_existing_total"))
        notified_total = _safe_int(payload.get("notified_total")) + _safe_int(payload.get("watch_notified_total"))
        failed_total = _safe_int(payload.get("failed_total"))
        if not (high_fit_total or review_total or notified_total or failed_total):
            return None
        title = "Property scout needs attention" if failed_total else "Property scout found items to review"
        summary = (
            f"Property scout {status}: {high_fit_total} high-fit, {review_total} review, "
            f"{notified_total} notified, {failed_total} failed."
        )
        counterparty = "Property Scout"
        signal_type = "property_scout"
        due_at = ""
    elif event_type == "telegram.message":
        title = _first_sentence(str(payload.get("analysis_summary") or payload.get("text") or "Telegram message"))
        summary = str(payload.get("analysis_summary") or payload.get("text") or "").strip()
        counterparty = "Telegram"
        signal_type = "telegram_message"
        due_at = ""
    else:
        return None
    if not title and not summary:
        return None
    source_ref = dedupe_key or external_id or source_id or observation_id
    return ProactiveSignal(
        source_ref=f"observation:{source_ref}",
        signal_type=signal_type,
        channel=channel or "observation",
        title=_clean_text(title),
        summary=_clean_text(summary),
        counterparty=counterparty,
        due_at=due_at or None,
        external_id=external_id or observation_id,
        payload={
            "observation_id": observation_id,
            "principal_id": principal_id,
            "event_type": event_type,
            "created_at": created_at,
            "ooda_loop": ooda_loop,
        },
    )


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
