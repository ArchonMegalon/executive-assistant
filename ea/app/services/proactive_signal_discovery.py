from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from xml.etree import ElementTree

from app.services.proactive_ooda_service import JsonOodaStateStore, ProactiveSignal


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
        "locale",
        "currency",
        "quantity",
        "preferences",
        "requirements",
        "exclusions",
        "notes",
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
