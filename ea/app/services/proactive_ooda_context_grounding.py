from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
import re

from app.services.proactive_ooda_service import OodaInk, ProactiveOodaDigest


CandidateAssessor = Callable[[str, str, str, dict[str, object]], Mapping[str, Any] | None]


def ground_digest_with_context(
    digest: ProactiveOodaDigest,
    *,
    context_pack: Mapping[str, Any] | None = None,
    preference_bundle: Mapping[str, Any] | None = None,
    assess_candidate: CandidateAssessor | None = None,
) -> ProactiveOodaDigest:
    if not digest.items:
        return digest
    pack = dict(context_pack or {})
    bundle = dict(preference_bundle or {})
    changed = False
    grounded_items: list[OodaInk] = []
    for item_index, item in enumerate(digest.items, start=1):
        grounded_payload = _ground_stage_payload(
            item=item,
            item_index=item_index,
            context_pack=pack,
            preference_bundle=bundle,
            assess_candidate=assess_candidate,
        )
        if grounded_payload == dict(item.stage_payload or {}):
            grounded_items.append(item)
            continue
        grounded_items.append(replace(item, stage_payload=grounded_payload))
        changed = True
    if not changed:
        return digest
    return replace(digest, items=tuple(grounded_items))


def ground_digest_for_principal(
    digest: ProactiveOodaDigest,
    *,
    principal_id: str,
    memory_runtime: Any,
    preference_profiles: Any,
    task_key: str = "proactive_ooda",
    goal: str = "Ground proactive assistant decisions against current context and commitments.",
    limit: int = 5,
) -> ProactiveOodaDigest:
    if not digest.items:
        return digest
    try:
        from app.services.memory_reasoning_service import MemoryReasoningService
    except Exception:
        return digest
    try:
        context_pack = MemoryReasoningService(memory_runtime).build_context_pack(
            principal_id=principal_id,
            task_key=task_key,
            goal=goal,
            limit=limit,
        ).as_dict()
    except Exception:
        context_pack = {}
    try:
        preference_bundle = preference_profiles.get_profile_bundle(principal_id=principal_id, person_id="self")
    except Exception:
        preference_bundle = {}

    def _assess_candidate(
        domain: str,
        object_type: str,
        object_id: str,
        object_payload: dict[str, object],
    ) -> dict[str, object] | None:
        try:
            assessment = preference_profiles.assess_candidate(
                principal_id=principal_id,
                person_id="self",
                domain=domain,
                object_type=object_type,
                object_id=object_id,
                object_payload=object_payload,
                persist=False,
                require_existing_profile=False,
            )
        except Exception:
            return None
        return dict(assessment or {}) if isinstance(assessment, dict) else None

    return ground_digest_with_context(
        digest,
        context_pack=context_pack,
        preference_bundle=preference_bundle,
        assess_candidate=_assess_candidate,
    )


def _ground_stage_payload(
    *,
    item: OodaInk,
    item_index: int,
    context_pack: Mapping[str, Any],
    preference_bundle: Mapping[str, Any],
    assess_candidate: CandidateAssessor | None,
) -> dict[str, Any]:
    payload = dict(item.stage_payload or {})
    context_hints = _context_hints(context_pack=context_pack, preference_bundle=preference_bundle)
    _merge_stage_list(payload, "preferences", context_hints.get("preferences"))
    _merge_stage_list(payload, "requirements", context_hints.get("requirements"))
    _merge_stage_list(payload, "exclusions", context_hints.get("exclusions"))
    _merge_stage_list(payload, "notes", context_hints.get("notes"))
    if not str(payload.get("deadline") or "").strip() and str(context_hints.get("deadline") or "").strip():
        payload["deadline"] = str(context_hints.get("deadline") or "").strip()
    if not payload.get("recipient_context") and context_hints.get("recipient_context"):
        payload["recipient_context"] = dict(context_hints.get("recipient_context") or {})
    if context_hints.get("budget"):
        payload["budget"] = _merge_mapping(dict(payload.get("budget") or {}), dict(context_hints.get("budget") or {}))
    for bucket_key in ("candidate_items", "candidates", "booking_options"):
        if bucket_key not in payload:
            continue
        payload[bucket_key] = _ground_candidate_list(
            payload.get(bucket_key),
            stage_payload=payload,
            item=item,
            item_index=item_index,
            assess_candidate=assess_candidate,
        )
    return payload


def _ground_candidate_list(
    raw_value: Any,
    *,
    stage_payload: Mapping[str, Any],
    item: OodaInk,
    item_index: int,
    assess_candidate: CandidateAssessor | None,
) -> list[dict[str, Any]]:
    candidates = [dict(row) for row in _object_list(raw_value)]
    if not candidates or assess_candidate is None:
        return candidates
    grounded: list[dict[str, Any]] = []
    for candidate_index, candidate in enumerate(candidates, start=1):
        if isinstance(candidate.get("preference_assessment"), Mapping):
            grounded.append(candidate)
            continue
        domain = _candidate_domain(candidate, stage_payload=stage_payload)
        object_type = "listing" if domain == "willhaben" else "candidate"
        object_id = _candidate_object_id(candidate, item=item, item_index=item_index, candidate_index=candidate_index)
        try:
            assessment = assess_candidate(domain, object_type, object_id, candidate)
        except Exception:
            assessment = None
        if isinstance(assessment, Mapping):
            candidate["preference_assessment"] = _json_safe(assessment)
        grounded.append(candidate)
    return grounded


def _context_hints(
    *,
    context_pack: Mapping[str, Any],
    preference_bundle: Mapping[str, Any],
) -> dict[str, Any]:
    notes: list[str] = []
    summary = str(context_pack.get("summary") or "").strip()
    if summary:
        notes.append(summary)
    notes.extend(_context_risk_notes(context_pack))
    notes.extend(_decision_window_notes(context_pack))
    budget = _generic_budget_from_preferences(preference_bundle)
    preferences = _generic_list_preferences(preference_bundle, category="soft_preference")
    requirements = _generic_list_preferences(preference_bundle, category="constraint")
    exclusions = _generic_list_preferences(preference_bundle, category="aversion")
    deadline = _earliest_context_deadline(context_pack)
    recipient_context = _recipient_context(context_pack)
    return {
        "budget": budget,
        "preferences": preferences,
        "requirements": requirements,
        "exclusions": exclusions,
        "notes": tuple(dict.fromkeys(note for note in notes if note)),
        "deadline": deadline,
        "recipient_context": recipient_context,
    }


def _context_risk_notes(context_pack: Mapping[str, Any]) -> tuple[str, ...]:
    notes: list[str] = []
    for row in list(context_pack.get("commitment_risks") or [])[:3]:
        if not isinstance(row, Mapping):
            continue
        summary = " ".join(str(row.get("summary") or "").split()).strip()
        due_at = str(row.get("due_at") or "").strip()
        severity = str(row.get("severity") or "").strip()
        if summary:
            notes.append(f"{severity or 'open'} risk: {summary}{f' Due {due_at}.' if due_at else ''}".strip())
    return tuple(notes)


def _decision_window_notes(context_pack: Mapping[str, Any]) -> tuple[str, ...]:
    notes: list[str] = []
    for row in list(context_pack.get("decision_windows") or [])[:2]:
        if not isinstance(row, Mapping):
            continue
        title = " ".join(str(row.get("title") or "").split()).strip()
        closes_at = str(row.get("closes_at") or "").strip()
        authority_required = str(row.get("authority_required") or "").strip()
        if title:
            detail = f"Decision window: {title}"
            if closes_at:
                detail += f" closes at {closes_at}"
            if authority_required:
                detail += f"; authority {authority_required}"
            notes.append(detail + ".")
    return tuple(notes)


def _generic_budget_from_preferences(preference_bundle: Mapping[str, Any]) -> dict[str, Any]:
    budget: dict[str, Any] = {}
    for row in _generic_preference_nodes(preference_bundle):
        category = _normalized_text(row.get("category"))
        key = _normalized_text(row.get("key"))
        value = row.get("value_json")
        if category not in {"constraint", "soft_preference"}:
            continue
        if key in {"max_budget", "budget_max", "max_price", "price_max"}:
            numeric = _float_value(value)
            if numeric is not None:
                budget.setdefault("max", numeric)
        elif key in {"min_budget", "budget_min", "min_price", "price_min"}:
            numeric = _float_value(value)
            if numeric is not None:
                budget.setdefault("min", numeric)
        elif key in {"currency", "required_currency", "preferred_currency", "budget_currency"}:
            text = str(value or "").strip().upper()
            if text:
                budget.setdefault("currency", text)
    return budget


def _generic_list_preferences(preference_bundle: Mapping[str, Any], *, category: str) -> tuple[str, ...]:
    texts: list[str] = []
    for row in _generic_preference_nodes(preference_bundle):
        if _normalized_text(row.get("category")) != category:
            continue
        key = _normalized_text(row.get("key"))
        value = row.get("value_json")
        texts.extend(_preference_texts_for_node(key=key, value=value, category=category))
    return tuple(dict.fromkeys(text for text in texts if text))


def _generic_preference_nodes(preference_bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in list(preference_bundle.get("preference_nodes") or []):
        if not isinstance(raw, Mapping):
            continue
        domain = _normalized_text(raw.get("domain"))
        if domain in {"willhaben", "propertyquarry"}:
            continue
        status = _normalized_text(raw.get("status")) or "active"
        if status not in {"active", "draft"}:
            continue
        rows.append(dict(raw))
    return rows


def _preference_texts_for_node(*, key: str, value: Any, category: str) -> list[str]:
    texts: list[str] = []
    list_keys = {
        "preferred_keywords": "keywords",
        "preferred_tags": "tags",
        "preferred_sites": "sites",
        "preferred_domains": "domains",
        "preferred_brands": "brands",
        "required_keywords": "keywords",
        "required_tags": "tags",
        "required_sites": "sites",
        "required_domains": "domains",
        "required_brands": "brands",
        "avoided_keywords": "keywords",
        "avoided_tags": "tags",
        "avoided_sites": "sites",
        "avoided_domains": "domains",
        "avoided_brands": "brands",
    }
    if key in list_keys:
        label = list_keys[key]
        for item in _list_value(value):
            texts.append(f"{label} {item}".strip())
        return texts
    if key in {"prefer_reversible_before_approval", "require_reversible_before_approval"} and bool(value):
        return ["reversible before approval"]
    if key in {"prefer_available_now", "require_available_now"} and bool(value):
        return ["available now"]
    if key in {"prefer_fast_delivery", "require_fast_delivery"} and bool(value):
        return ["fast delivery"]
    if key in {"preferred_currency", "required_currency"} and str(value or "").strip():
        return [f"currency {str(value).strip().upper()}"]
    if category == "soft_preference" and key in {"selection_criteria", "preferred_features"}:
        return _list_value(value)
    return texts


def _earliest_context_deadline(context_pack: Mapping[str, Any]) -> str:
    candidates: list[datetime] = []
    for bucket_key, field_name in (
        ("commitment_risks", "due_at"),
        ("commitments", "due_at"),
        ("decision_windows", "closes_at"),
        ("follow_ups", "due_at"),
    ):
        for row in list(context_pack.get(bucket_key) or [])[:5]:
            if not isinstance(row, Mapping):
                continue
            parsed = _parse_datetime(row.get(field_name))
            if parsed is not None:
                candidates.append(parsed)
    if not candidates:
        return ""
    return min(candidates).isoformat()


def _recipient_context(context_pack: Mapping[str, Any]) -> dict[str, Any]:
    stakeholders = [dict(row) for row in list(context_pack.get("stakeholders") or [])[:3] if isinstance(row, Mapping)]
    follow_ups = [dict(row) for row in list(context_pack.get("follow_ups") or [])[:3] if isinstance(row, Mapping)]
    location = _recipient_location_context(context_pack)
    if not stakeholders and not follow_ups and not location:
        return {}
    payload: dict[str, Any] = {
        "stakeholders": [
            {
                "display_name": str(row.get("display_name") or "").strip(),
                "authority_level": str(row.get("authority_level") or "").strip(),
                "tone_pref": str(row.get("tone_pref") or "").strip(),
            }
            for row in stakeholders
            if str(row.get("display_name") or "").strip()
        ],
        "follow_ups": [
            {
                "topic": str(row.get("topic") or "").strip(),
                "due_at": str(row.get("due_at") or "").strip(),
                "channel_hint": str(row.get("channel_hint") or "").strip(),
            }
            for row in follow_ups
            if str(row.get("topic") or "").strip()
        ],
    }
    if location:
        payload["location"] = location
    return payload


def _recipient_location_context(context_pack: Mapping[str, Any]) -> dict[str, Any]:
    phrases: list[str] = []
    city_terms: list[str] = []
    postal_codes: list[str] = []
    country_codes: list[str] = []
    country_names: list[str] = []
    for row in list(context_pack.get("memory_items") or [])[:8]:
        if not isinstance(row, Mapping):
            continue
        _collect_location_fields(
            row.get("fact_json"),
            key_hint="",
            phrases=phrases,
            city_terms=city_terms,
            postal_codes=postal_codes,
            country_codes=country_codes,
            country_names=country_names,
        )
    if not any((phrases, city_terms, postal_codes, country_codes, country_names)):
        return {}
    return {
        "phrases": list(dict.fromkeys(phrases))[:4],
        "city_terms": list(dict.fromkeys(city_terms))[:3],
        "postal_codes": list(dict.fromkeys(postal_codes))[:3],
        "country_codes": list(dict.fromkeys(country_codes))[:2],
        "country_names": list(dict.fromkeys(country_names))[:2],
    }


def _collect_location_fields(
    value: Any,
    *,
    key_hint: str,
    phrases: list[str],
    city_terms: list[str],
    postal_codes: list[str],
    country_codes: list[str],
    country_names: list[str],
) -> None:
    normalized_key = _normalized_text(key_hint)
    if isinstance(value, Mapping):
        for nested_key, nested_value in value.items():
            _collect_location_fields(
                nested_value,
                key_hint=str(nested_key),
                phrases=phrases,
                city_terms=city_terms,
                postal_codes=postal_codes,
                country_codes=country_codes,
                country_names=country_names,
            )
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _collect_location_fields(
                item,
                key_hint=key_hint,
                phrases=phrases,
                city_terms=city_terms,
                postal_codes=postal_codes,
                country_codes=country_codes,
                country_names=country_names,
            )
        return
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return
    if normalized_key in {"country_code", "country"}:
        if normalized_key == "country_code":
            normalized_code = re.sub(r"[^A-Za-z]", "", text).upper()
            if 2 <= len(normalized_code) <= 3:
                country_codes.append(normalized_code)
        elif text:
            country_names.append(text)
        return
    locationish_key = normalized_key in {
        "address",
        "address_line",
        "address_lines",
        "city",
        "district",
        "home",
        "home_city",
        "location",
        "location_name",
        "postal_name",
        "postal_code",
        "postcode",
        "residence",
        "zip",
    }
    if not locationish_key:
        return
    postal_match = re.search(r"\b(\d{4,5})\b", text)
    if postal_match is not None:
        postal_codes.append(postal_match.group(1))
        if not (normalized_key in {"postal_code", "postcode", "zip"} and re.fullmatch(r"\d{4,5}", text)):
            phrases.append(text)
        remainder = re.sub(r"^\D*", "", text)
        city_match = re.search(r"\b\d{4,5}\s+(.+)$", remainder)
        if city_match is not None:
            city = city_match.group(1).strip(" ,")
            if city:
                city_terms.append(city)
        return
    if normalized_key in {"city", "district", "location", "location_name", "home_city", "residence"}:
        city_terms.append(text)
        return
    if normalized_key in {"address", "address_line", "address_lines"}:
        return
    if text and len(text) <= 80:
        phrases.append(text)


def _candidate_domain(candidate: Mapping[str, Any], *, stage_payload: Mapping[str, Any]) -> str:
    explicit = _normalized_text(candidate.get("domain") or candidate.get("preference_domain") or stage_payload.get("preference_domain"))
    if explicit:
        return explicit
    site = str(candidate.get("site") or "").strip()
    if site:
        return _normalized_text(site)
    url = str(candidate.get("url") or candidate.get("link") or candidate.get("href") or "").strip().lower()
    if "willhaben" in url:
        return "willhaben"
    return "general"


def _candidate_object_id(candidate: Mapping[str, Any], *, item: OodaInk, item_index: int, candidate_index: int) -> str:
    for key in ("candidate_id", "id", "object_id", "url", "link", "href", "label", "title"):
        value = str(candidate.get(key) or "").strip()
        if value:
            return value
    return f"{item.signal_ref}:item:{item_index}:candidate:{candidate_index}"


def _merge_stage_list(payload: dict[str, Any], key: str, values: Any) -> None:
    incoming = _list_value(values)
    if not incoming:
        return
    existing = _list_value(payload.get(key))
    merged = list(dict.fromkeys((*existing, *incoming)))
    if merged:
        payload[key] = merged


def _merge_mapping(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if key not in merged or merged.get(key) in {None, "", [], {}}:
            merged[key] = value
    return merged


def _object_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _list_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item or "").strip() for item in value if str(item or "").strip()]


def _parse_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _float_value(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except Exception:
        return None


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, depth=depth + 1) for item in value]
    return str(value)
