from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping
import urllib.error
import urllib.request

from app.services.proactive_ooda_stage_packets import (
    FORBIDDEN_WITHOUT_EXPLICIT_APPROVAL,
    SAFE_WORK_ORDER_SCHEMA,
)


SAFE_WORK_RESULT_SCHEMA = "proactive_ooda.safe_work_result.v1"


@dataclass(frozen=True)
class SafeWorkResultWriteResult:
    paths: tuple[str, ...]
    result_refs: tuple[str, ...]
    errors: tuple[str, ...] = ()


def default_safe_work_result_dir(stage_packet_dir: str | Path) -> Path:
    path = Path(stage_packet_dir)
    return path.parent / "proactive_ooda_safe_work_results"


class _TitleExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            text = str(data or "").strip()
            if text:
                self._parts.append(text)

    def title(self) -> str:
        return " ".join(self._parts).strip()


def build_safe_work_result(
    packet: Mapping[str, Any],
    *,
    generated_at: str | None = None,
    network_fetch_enabled: bool = False,
    network_fetch_limit: int = 6,
    network_fetch_timeout_seconds: int = 10,
) -> dict[str, Any]:
    order = packet.get("safe_work_order") if isinstance(packet.get("safe_work_order"), Mapping) else {}
    input_contract = order.get("input_contract") if isinstance(order.get("input_contract"), Mapping) else {}
    stage = packet.get("stage") if isinstance(packet.get("stage"), Mapping) else {}
    stage_payload = stage.get("payload") if isinstance(stage.get("payload"), Mapping) else {}
    work_type = str(order.get("work_type") or "research").strip() or "research"
    page_checks = _page_checks(
        input_contract=input_contract,
        stage_payload=stage_payload,
        network_fetch_enabled=network_fetch_enabled,
        limit=network_fetch_limit,
        timeout_seconds=network_fetch_timeout_seconds,
    )
    candidate_items = _candidate_items(input_contract=input_contract, stage_payload=stage_payload)
    candidate_items = _enrich_candidate_items(candidate_items, page_checks=page_checks)
    candidate_items, comparison_table = _rank_candidate_items(
        input_contract=input_contract,
        stage_payload=stage_payload,
        candidate_items=candidate_items,
    )
    recommended = _recommended_option_or_draft(
        work_type=work_type,
        input_contract=input_contract,
        stage_payload=stage_payload,
        candidate_items=candidate_items,
    )
    staged_action_url = _staged_action_url(
        stage_payload=stage_payload,
        recommended=recommended,
        candidate_items=candidate_items,
    )
    has_material = bool(recommended.get("value") or candidate_items)
    result_id = _result_id(packet=packet, order=order, generated_at=generated_at or "")
    return {
        "schema": SAFE_WORK_RESULT_SCHEMA,
        "result_id": result_id,
        "result_ref": f"safe_work_result:{result_id}",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "source_packet_ref_hash": _hash_value(str(packet.get("packet_ref") or packet.get("packet_id") or "")),
        "work_order_id_hash": _hash_value(str(order.get("work_order_id") or "")),
        "work_order_schema": str(order.get("schema") or ""),
        "status": "staged_for_user_decision" if has_material else "blocked_needs_research_input",
        "work_type": work_type,
        "summary": _summary(
            packet=packet,
            order=order,
            recommended=recommended,
            has_material=has_material,
            page_checks=page_checks,
        ),
        "recommended_option_or_draft": recommended,
        "staged_action_url": staged_action_url,
        "shortlist": candidate_items,
        "comparison_table": comparison_table,
        "evidence_refs": _evidence_refs(
            input_contract=input_contract,
            stage_payload=stage_payload,
            candidate_items=candidate_items,
            page_checks=page_checks,
        ),
        "risks_or_tradeoffs": _risks_or_tradeoffs(input_contract=input_contract, stage_payload=stage_payload),
        "approval_prompt": _approval_prompt(packet=packet, order=order, recommended=recommended, has_material=has_material),
        "approval": {
            "required": True,
            "gate": str(order.get("approval_gate") or _approval_gate(packet) or "").strip(),
            "irreversible_actions_require_explicit_approval": True,
        },
        "execution_receipt": {
            "network_fetch_enabled": bool(network_fetch_enabled),
            "network_fetch_count": len(page_checks),
            "network_fetch_success_count": sum(1 for check in page_checks if check.get("reachable") is True),
            "page_checks": page_checks,
            "external_actions_attempted": [],
            "irreversible_actions_attempted": [],
            "forbidden_without_explicit_approval": list(FORBIDDEN_WITHOUT_EXPLICIT_APPROVAL),
            "safe_work_order_schema_valid": str(order.get("schema") or "") == SAFE_WORK_ORDER_SCHEMA,
        },
        "privacy": {
            "raw_principal_id_stored": False,
            "raw_signal_ref_stored": False,
            "private_links_may_be_present": True,
        },
    }


def build_safe_work_results(packets: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(build_safe_work_result(packet) for packet in packets)


def persist_safe_work_results(
    *,
    stage_packet_dir: str | Path,
    result_dir: str | Path | None = None,
    limit: int = 100,
    network_fetch_enabled: bool = False,
    network_fetch_limit: int = 6,
    network_fetch_timeout_seconds: int = 10,
) -> SafeWorkResultWriteResult:
    packets, load_errors = load_stage_packets(stage_packet_dir=stage_packet_dir, limit=limit)
    target = Path(result_dir) if result_dir is not None else default_safe_work_result_dir(stage_packet_dir)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return SafeWorkResultWriteResult(paths=(), result_refs=(), errors=(*load_errors, f"safe_work_result_dir:{exc.__class__.__name__}"))
    paths: list[str] = []
    refs: list[str] = []
    errors = list(load_errors)
    for packet in packets:
        try:
            result = build_safe_work_result(
                packet,
                network_fetch_enabled=network_fetch_enabled,
                network_fetch_limit=network_fetch_limit,
                network_fetch_timeout_seconds=network_fetch_timeout_seconds,
            )
            path = target / f"{result['result_id']}.json"
            path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            paths.append(str(path))
            refs.append(str(result["result_ref"]))
        except Exception as exc:
            packet_ref = str(packet.get("packet_ref") or packet.get("packet_id") or "unknown")
            errors.append(f"{packet_ref}:{exc.__class__.__name__}")
    return SafeWorkResultWriteResult(paths=tuple(paths), result_refs=tuple(refs), errors=tuple(errors))


def persist_safe_work_results_from_paths(
    *,
    stage_packet_paths: Iterable[str | Path],
    result_dir: str | Path,
    network_fetch_enabled: bool = False,
    network_fetch_limit: int = 6,
    network_fetch_timeout_seconds: int = 10,
) -> SafeWorkResultWriteResult:
    target = Path(result_dir)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return SafeWorkResultWriteResult(paths=(), result_refs=(), errors=(f"safe_work_result_dir:{exc.__class__.__name__}",))
    paths: list[str] = []
    refs: list[str] = []
    errors: list[str] = []
    for raw_path in stage_packet_paths:
        path = Path(raw_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                errors.append(f"{path.name}:packet_not_object")
                continue
            result = build_safe_work_result(
                payload,
                network_fetch_enabled=network_fetch_enabled,
                network_fetch_limit=network_fetch_limit,
                network_fetch_timeout_seconds=network_fetch_timeout_seconds,
            )
            result_path = target / f"{result['result_id']}.json"
            result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            paths.append(str(result_path))
            refs.append(str(result["result_ref"]))
        except Exception as exc:
            errors.append(f"{path.name}:{exc.__class__.__name__}")
    return SafeWorkResultWriteResult(paths=tuple(paths), result_refs=tuple(refs), errors=tuple(errors))


def load_stage_packets(*, stage_packet_dir: str | Path, limit: int = 100) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...]]:
    root = Path(stage_packet_dir)
    if not root.exists():
        return (), (f"stage_packet_dir_missing:{root}",)
    packets: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted(root.glob("*.json"))[: max(int(limit or 1), 1)]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{path.name}:{exc.__class__.__name__}")
            continue
        if isinstance(payload, dict):
            packets.append(payload)
        else:
            errors.append(f"{path.name}:packet_not_object")
    return tuple(packets), tuple(errors)


def _candidate_items(*, input_contract: Mapping[str, Any], stage_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    for key in ("candidate_items", "candidates", "booking_options"):
        value = _stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key=key)
        items = _object_list(value)
        if items:
            return items
    links = _string_list(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="links"))
    target_sites = _string_list(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="target_sites"))
    return [{"label": _label_from_url(url), "url": url} for url in (*links, *target_sites)]


def _rank_candidate_items(
    *,
    input_contract: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
    candidate_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not candidate_items:
        return candidate_items, []
    context = _candidate_evaluation_context(input_contract=input_contract, stage_payload=stage_payload)
    analyses = [
        _candidate_analysis(candidate=item, index=index, context=context, candidate_items=candidate_items)
        for index, item in enumerate(candidate_items)
    ]
    order = sorted(
        range(len(candidate_items)),
        key=lambda index: (
            -float(analyses[index]["score"]),
            len(analyses[index]["constraint_violations"]),
            0 if candidate_items[index].get("reachable") is True else 1 if candidate_items[index].get("reachable") is False else 2,
            index,
        ),
    )
    ordered_items = [dict(candidate_items[index]) for index in order]
    comparison_table: list[dict[str, Any]] = []
    for rank, index in enumerate(order, start=1):
        item = candidate_items[index]
        analysis = analyses[index]
        row = {
            "label": str(item.get("label") or item.get("title") or f"candidate-{rank}").strip(),
            "url": str(item.get("url") or item.get("link") or item.get("href") or "").strip(),
            "assistant_rank": rank,
            "assistant_score": round(float(analysis["score"]), 2),
            "recommended": rank == 1,
            "matched_criteria": list(analysis["matched_criteria"]),
            "constraint_violations": list(analysis["constraint_violations"]),
            "recommendation_reasons": list(analysis["recommendation_reasons"]),
        }
        for key in ("reachable", "page_title", "final_url"):
            if key in item:
                row[key] = item.get(key)
        for key in ("price", "price_value", "currency", "delivery_days", "eta_days", "lead_time_days"):
            if key in item:
                row[key] = item.get(key)
        comparison_table.append(row)
    return ordered_items, comparison_table


def _candidate_evaluation_context(
    *,
    input_contract: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
) -> dict[str, Any]:
    selection_criteria = _criteria_texts(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="selection_criteria"))
    comparison_dimensions = _criteria_texts(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="comparison_dimensions"))
    preferences = _criteria_texts(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="preferences"))
    requirements = _criteria_texts(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="requirements"))
    exclusions = _criteria_texts(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="exclusions"))
    budget = _mapping_value(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="budget"))
    constraints = _mapping_value(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="constraints"))
    budget_max = _float_value(
        budget.get("max"),
        budget.get("budget_max"),
        constraints.get("max"),
        constraints.get("budget_max"),
        constraints.get("price_max"),
    )
    budget_min = _float_value(
        budget.get("min"),
        budget.get("budget_min"),
        constraints.get("min"),
        constraints.get("budget_min"),
        constraints.get("price_min"),
    )
    budget_currency = _upper_text(
        budget.get("currency"),
        constraints.get("currency"),
    )
    all_text = tuple(dict.fromkeys((*selection_criteria, *comparison_dimensions, *preferences, *requirements)))
    return {
        "selection_criteria": selection_criteria,
        "comparison_dimensions": comparison_dimensions,
        "preferences": preferences,
        "requirements": requirements,
        "exclusions": exclusions,
        "budget_max": budget_max,
        "budget_min": budget_min,
        "budget_currency": budget_currency,
        "all_text": all_text,
        "price_relevant": any(_text_mentions(term, ("price", "budget", "cheap", "cost", "value")) for term in all_text),
        "timing_relevant": any(_text_mentions(term, ("timing", "delivery", "soon", "fast", "quick", "eta")) for term in all_text),
        "reversibility_relevant": any(_text_mentions(term, ("reversible", "refund", "return", "cancel", "flexib")) for term in all_text),
        "availability_relevant": any(_text_mentions(term, ("stock", "available", "availability", "ready")) for term in all_text),
    }


def _candidate_analysis(
    *,
    candidate: Mapping[str, Any],
    index: int,
    context: Mapping[str, Any],
    candidate_items: list[dict[str, Any]],
) -> dict[str, Any]:
    score = 0.0
    matched_criteria: list[str] = []
    constraint_violations: list[str] = []
    recommendation_reasons: list[str] = []
    search_text = _candidate_search_text(candidate)
    price_value = _candidate_price_value(candidate)
    candidate_currency = _upper_text(candidate.get("currency"))
    delivery_days = _float_value(candidate.get("delivery_days"), candidate.get("eta_days"), candidate.get("lead_time_days"))
    reversible = _candidate_boolean(candidate, "reversible_before_approval", "reversible", "refundable", "cancellable_before_approval")
    available = _candidate_availability(candidate)

    if candidate.get("reachable") is True:
        score += 18
        recommendation_reasons.append("link verified reachable")
    elif candidate.get("reachable") is False:
        score -= 12
        constraint_violations.append("link not reachable")

    if context.get("budget_max") is not None and price_value is not None:
        budget_max = float(context["budget_max"])
        if price_value <= budget_max:
            score += 14
            matched_criteria.append(f"within budget <= {budget_max:g}")
            recommendation_reasons.append(f"within budget ({price_value:g})")
        else:
            score -= 30
            constraint_violations.append(f"over budget ({price_value:g} > {budget_max:g})")
    if context.get("budget_min") is not None and price_value is not None:
        budget_min = float(context["budget_min"])
        if price_value < budget_min:
            score -= 12
            constraint_violations.append(f"below minimum budget ({price_value:g} < {budget_min:g})")
    budget_currency = str(context.get("budget_currency") or "").strip()
    if budget_currency and candidate_currency:
        if candidate_currency == budget_currency:
            score += 6
            matched_criteria.append(f"currency {candidate_currency}")
        else:
            score -= 10
            constraint_violations.append(f"currency mismatch ({candidate_currency} vs {budget_currency})")

    if context.get("reversibility_relevant") and reversible is not None:
        if reversible:
            score += 16
            matched_criteria.append("reversible before approval")
            recommendation_reasons.append("reversible before approval")
        else:
            score -= 18
            constraint_violations.append("not reversible before approval")

    if context.get("availability_relevant") and available is not None:
        if available:
            score += 8
            matched_criteria.append("available now")
        else:
            score -= 16
            constraint_violations.append("not currently available")

    for phrase in context.get("selection_criteria", ()):
        if _candidate_matches_phrase(candidate, search_text=search_text, phrase=phrase):
            score += 8
            matched_criteria.append(phrase)
    for phrase in context.get("comparison_dimensions", ()):
        if _candidate_matches_phrase(candidate, search_text=search_text, phrase=phrase):
            score += 4
            matched_criteria.append(phrase)
    for phrase in context.get("preferences", ()):
        if _candidate_matches_phrase(candidate, search_text=search_text, phrase=phrase):
            score += 6
            matched_criteria.append(phrase)
    for phrase in context.get("requirements", ()):
        if _candidate_matches_phrase(candidate, search_text=search_text, phrase=phrase):
            score += 8
            matched_criteria.append(phrase)
    for phrase in context.get("exclusions", ()):
        if _candidate_matches_phrase(candidate, search_text=search_text, phrase=phrase):
            score -= 30
            constraint_violations.append(f"matches exclusion '{phrase}'")

    if context.get("price_relevant") and price_value is not None:
        relative_bonus = _relative_metric_bonus(
            price_value,
            values=[
                _candidate_price_value(item)
                for item in candidate_items
                if _candidate_price_value(item) is not None
                and (
                    not budget_currency
                    or not _upper_text(item.get("currency"))
                    or _upper_text(item.get("currency")) == budget_currency
                )
            ],
            prefer_lower=True,
            max_bonus=12,
        )
        if relative_bonus > 0:
            score += relative_bonus
            recommendation_reasons.append("strong price fit")

    if context.get("timing_relevant") and delivery_days is not None:
        relative_bonus = _relative_metric_bonus(
            delivery_days,
            values=[
                _float_value(item.get("delivery_days"), item.get("eta_days"), item.get("lead_time_days"))
                for item in candidate_items
                if _float_value(item.get("delivery_days"), item.get("eta_days"), item.get("lead_time_days")) is not None
            ],
            prefer_lower=True,
            max_bonus=10,
        )
        if relative_bonus > 0:
            score += relative_bonus
            recommendation_reasons.append("faster timing")

    return {
        "index": index,
        "score": score,
        "matched_criteria": tuple(dict.fromkeys(item for item in matched_criteria if item)),
        "constraint_violations": tuple(dict.fromkeys(item for item in constraint_violations if item)),
        "recommendation_reasons": tuple(dict.fromkeys(item for item in recommendation_reasons if item))[:4],
    }


def _recommended_option_or_draft(
    *,
    work_type: str,
    input_contract: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
    candidate_items: list[dict[str, Any]],
) -> dict[str, Any]:
    if work_type == "draft":
        draft = stage_payload.get("draft_text") or stage_payload.get("draft")
        return {"kind": "draft_text", "value": _json_safe(draft), "source": "stage_payload"} if draft else {}
    if work_type == "prepare_booking_candidate":
        candidate = _preferred_candidate(candidate_items)
        return {"kind": "booking_candidate", "value": candidate, "source": "stage_payload"} if candidate else {}
    if work_type == "prepare_cart_or_link":
        preferred_candidate = _preferred_candidate(candidate_items)
        value = (
            stage_payload.get("cart_url")
            or stage_payload.get("approval_url")
            or _first_url([preferred_candidate] if preferred_candidate else [])
            or _first_url(_object_list(input_contract.get("links")))
        )
        return {"kind": "reversible_cart_or_link", "value": value, "source": "stage_payload"} if value else {}
    if candidate_items:
        return {"kind": "shortlist_candidate", "value": _preferred_candidate(candidate_items), "source": "stage_payload"}
    query = input_contract.get("research_query") or _first_string(input_contract.get("search_queries"))
    return {"kind": "research_query", "value": str(query).strip(), "source": "input_contract"} if str(query or "").strip() else {}


def _summary(
    *,
    packet: Mapping[str, Any],
    order: Mapping[str, Any],
    recommended: Mapping[str, Any],
    has_material: bool,
    page_checks: list[dict[str, Any]],
) -> str:
    live_summary = _page_check_summary(page_checks)
    if has_material:
        outcome = str(order.get("requested_outcome") or "").strip()
        base = outcome or "Safe work produced a reversible result for user approval."
        return f"{base} {live_summary}".strip() if live_summary else base
    stage = packet.get("stage") if isinstance(packet.get("stage"), Mapping) else {}
    base = str(stage.get("summary") or "Safe work needs additional research input before a recommendation can be staged.").strip()
    return f"{base} {live_summary}".strip() if live_summary else base


def _staged_action_url(
    *,
    stage_payload: Mapping[str, Any],
    recommended: Mapping[str, Any],
    candidate_items: list[dict[str, Any]],
) -> str:
    for value in (
        stage_payload.get("cart_url"),
        stage_payload.get("approval_url"),
        recommended.get("value"),
        candidate_items,
    ):
        url = _url_from_value(value)
        if url:
            return url
    return ""


def _evidence_refs(
    *,
    input_contract: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
    candidate_items: list[dict[str, Any]],
    page_checks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    check_by_url = {
        str(check.get("url") or "").strip(): check
        for check in page_checks
        if str(check.get("url") or "").strip()
    }
    refs: list[dict[str, Any]] = []
    for index, item in enumerate(candidate_items, start=1):
        url = str(item.get("url") or item.get("link") or "").strip()
        label = str(item.get("label") or item.get("title") or f"candidate-{index}").strip()
        ref = {"kind": "candidate", "label": label, "url": url, "url_hash": _hash_value(url) if url else ""}
        check = check_by_url.get(url)
        if check is not None:
            ref["reachable"] = bool(check.get("reachable"))
            ref["page_title"] = str(check.get("page_title") or "").strip()
            ref["final_url"] = str(check.get("final_url") or "").strip()
        refs.append(ref)
    for url in _string_list(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="target_sites")):
        if not any(ref.get("url") == url for ref in refs):
            ref = {"kind": "target_site", "label": _label_from_url(url), "url": url, "url_hash": _hash_value(url)}
            check = check_by_url.get(url)
            if check is not None:
                ref["reachable"] = bool(check.get("reachable"))
                ref["page_title"] = str(check.get("page_title") or "").strip()
                ref["final_url"] = str(check.get("final_url") or "").strip()
            refs.append(ref)
    return refs


def _risks_or_tradeoffs(*, input_contract: Mapping[str, Any], stage_payload: Mapping[str, Any]) -> list[str]:
    values = []
    for key in ("risks", "risk", "tradeoffs", "constraints", "exclusions"):
        raw = _stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key=key)
        if isinstance(raw, Mapping):
            values.extend(f"{name}: {value}" for name, value in raw.items())
        elif isinstance(raw, (list, tuple)):
            values.extend(str(item).strip() for item in raw if str(item).strip())
        elif str(raw or "").strip():
            values.append(str(raw).strip())
    return values


def _approval_prompt(
    *,
    packet: Mapping[str, Any],
    order: Mapping[str, Any],
    recommended: Mapping[str, Any],
    has_material: bool,
) -> str:
    gate = str(order.get("approval_gate") or _approval_gate(packet) or "Explicit approval required before any irreversible action.").strip()
    if has_material:
        kind = str(recommended.get("kind") or "result").replace("_", " ")
        return f"Approve whether EA should proceed with this staged {kind}. {gate}"
    return f"Approve whether EA should research further or change constraints. {gate}"


def _approval_gate(packet: Mapping[str, Any]) -> str:
    approval = packet.get("approval") if isinstance(packet.get("approval"), Mapping) else {}
    return str(approval.get("gate") or approval.get("external_action_policy") or "").strip()


def _object_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _string_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _first_string(value: Any) -> str:
    for item in _string_list(value):
        return item
    return ""


def _first_url(items: list[dict[str, Any]]) -> str:
    for item in items:
        for key in ("url", "link", "href"):
            value = str(item.get(key) or "").strip()
            if value:
                return value
    return ""


def _url_from_value(value: Any) -> str:
    if isinstance(value, Mapping):
        return _first_url([dict(value)])
    if isinstance(value, list):
        return _first_url([dict(item) for item in value if isinstance(item, Mapping)])
    text = str(value or "").strip()
    return text if re.match(r"^https?://", text, flags=re.IGNORECASE) else ""


def _mapping_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _criteria_texts(value: Any) -> tuple[str, ...]:
    texts: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(item, bool):
                if item:
                    texts.append(str(key).strip())
                continue
            if isinstance(item, (list, tuple)):
                for nested in _criteria_texts(item):
                    texts.append(f"{key} {nested}".strip())
                continue
            text = " ".join(str(part).strip() for part in (key, item) if str(part).strip())
            if text:
                texts.append(text)
    elif isinstance(value, (list, tuple)):
        for item in value:
            texts.extend(_criteria_texts(item))
    else:
        text = str(value or "").strip()
        if text:
            texts.append(text)
    return tuple(dict.fromkeys(text for text in texts if text))


def _candidate_search_text(candidate: Mapping[str, Any]) -> str:
    pieces: list[str] = []

    def _visit(value: Any, *, key: str = "") -> None:
        if isinstance(value, Mapping):
            for nested_key, nested_value in value.items():
                _visit(nested_value, key=str(nested_key))
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                _visit(item, key=key)
            return
        if value is None:
            return
        if key in {"url", "link", "href", "final_url"}:
            return
        text = str(value).strip()
        if not text:
            return
        pieces.append(f"{key} {text}".strip() if key else text)

    _visit(candidate)
    return " ".join(pieces).lower()


def _candidate_matches_phrase(candidate: Mapping[str, Any], *, search_text: str, phrase: str) -> bool:
    normalized = str(phrase or "").strip().lower()
    if not normalized:
        return False
    if normalized in search_text:
        return True
    if _text_mentions(normalized, ("reversible", "refund", "return", "cancel", "flexib")):
        reversible = _candidate_boolean(candidate, "reversible_before_approval", "reversible", "refundable", "cancellable_before_approval")
        return reversible is True
    if _text_mentions(normalized, ("stock", "available", "availability", "ready")):
        available = _candidate_availability(candidate)
        return available is True
    return False


def _candidate_price_value(candidate: Mapping[str, Any]) -> float | None:
    return _float_value(candidate.get("price_value"), candidate.get("price"), candidate.get("amount"), candidate.get("total"))


def _candidate_boolean(candidate: Mapping[str, Any], *keys: str) -> bool | None:
    for key in keys:
        if key not in candidate:
            continue
        value = candidate.get(key)
        if isinstance(value, bool):
            return value
        normalized = str(value or "").strip().lower()
        if normalized in {"1", "true", "yes", "y", "on", "available", "in_stock"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", "unavailable", "out_of_stock"}:
            return False
    return None


def _candidate_availability(candidate: Mapping[str, Any]) -> bool | None:
    available = _candidate_boolean(candidate, "in_stock", "available")
    if available is not None:
        return available
    raw = str(candidate.get("availability") or "").strip().lower()
    if raw in {"in stock", "available", "ready", "now"}:
        return True
    if raw in {"out of stock", "unavailable", "delayed"}:
        return False
    return None


def _relative_metric_bonus(
    value: float,
    *,
    values: list[float | None],
    prefer_lower: bool,
    max_bonus: int,
) -> float:
    comparable = [float(item) for item in values if item is not None]
    if not comparable:
        return 0.0
    minimum = min(comparable)
    maximum = max(comparable)
    if maximum <= minimum:
        return float(max_bonus // 2)
    position = (maximum - value) / (maximum - minimum) if prefer_lower else (value - minimum) / (maximum - minimum)
    position = max(0.0, min(position, 1.0))
    return round(position * max_bonus, 2)


def _float_value(*values: Any) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        if isinstance(value, (int, float)):
            return float(value)
        match = re.search(r"-?\d+(?:[.,]\d+)?", str(value))
        if not match:
            continue
        try:
            return float(match.group(0).replace(",", "."))
        except ValueError:
            continue
    return None


def _upper_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text.upper()
    return ""


def _text_mentions(text: str, needles: tuple[str, ...]) -> bool:
    haystack = str(text or "").lower()
    return any(needle in haystack for needle in needles)


def _label_from_url(url: str) -> str:
    normalized = str(url or "").strip()
    return normalized.split("//", 1)[-1].split("/", 1)[0] or normalized or "link"


def _preferred_candidate(items: list[dict[str, Any]]) -> dict[str, Any]:
    return items[0] if items else {}


def _enrich_candidate_items(
    items: list[dict[str, Any]],
    *,
    page_checks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    check_by_url = {
        str(check.get("url") or "").strip(): check
        for check in page_checks
        if str(check.get("url") or "").strip()
    }
    enriched: list[dict[str, Any]] = []
    for item in items:
        candidate = dict(item)
        url = str(candidate.get("url") or candidate.get("link") or candidate.get("href") or "").strip()
        check = check_by_url.get(url)
        if check is not None:
            candidate["reachable"] = bool(check.get("reachable"))
            if check.get("page_title"):
                candidate["page_title"] = str(check.get("page_title") or "").strip()
            if check.get("final_url"):
                candidate["final_url"] = str(check.get("final_url") or "").strip()
            if check.get("error_code"):
                candidate["fetch_error_code"] = str(check.get("error_code") or "").strip()
        enriched.append(candidate)
    return enriched


def _page_checks(
    *,
    input_contract: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
    network_fetch_enabled: bool,
    limit: int,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    if not network_fetch_enabled:
        return []
    urls: list[str] = []
    for item in _object_list(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="candidate_items")):
        urls.extend(_candidate_urls(item))
    for item in _object_list(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="candidates")):
        urls.extend(_candidate_urls(item))
    for item in _object_list(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="booking_options")):
        urls.extend(_candidate_urls(item))
    for value in (
        stage_payload.get("cart_url"),
        stage_payload.get("approval_url"),
        _stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="links"),
        _stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="target_sites"),
    ):
        urls.extend(_string_list(value))
    checks: list[dict[str, Any]] = []
    seen: set[str] = set()
    fetch_limit = max(int(limit or 1), 1)
    for url in urls:
        normalized = str(url or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        checks.append(_fetch_page_check(normalized, timeout_seconds=timeout_seconds))
        if len(checks) >= fetch_limit:
            break
    return checks


def _candidate_urls(item: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(item.get(key) or "").strip()
        for key in ("url", "link", "href")
        if str(item.get(key) or "").strip()
    )


def _fetch_page_check(url: str, *, timeout_seconds: int) -> dict[str, Any]:
    fetched_at = datetime.now(timezone.utc).isoformat()
    check = {
        "url": url,
        "url_hash": _hash_value(url),
        "reachable": False,
        "fetched_at": fetched_at,
        "final_url": "",
        "page_title": "",
        "content_type": "",
        "status_code": 0,
        "error_code": "",
    }
    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        check["error_code"] = "unsupported_url_scheme"
        return check
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "EA-Proactive-OODA/1.0",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(int(timeout_seconds or 1), 1)) as response:
            final_url = str(getattr(response, "geturl", lambda: url)() or url).strip()
            content_type = str(response.headers.get("Content-Type") or "").strip()
            status_code = int(getattr(response, "status", 0) or getattr(response, "getcode", lambda: 0)() or 0)
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read(65536)
        page_text = body.decode(charset, errors="replace")
        title = _extract_html_title(page_text)
        check.update(
            {
                "reachable": True,
                "final_url": final_url,
                "page_title": title,
                "content_type": content_type,
                "status_code": status_code,
            }
        )
        return check
    except urllib.error.HTTPError as exc:
        final_url = str(getattr(exc, "geturl", lambda: url)() or url).strip()
        body = exc.read(65536)
        charset = exc.headers.get_content_charset() if exc.headers is not None else None
        title = _extract_html_title(body.decode(charset or "utf-8", errors="replace")) if body else ""
        check.update(
            {
                "final_url": final_url,
                "page_title": title,
                "content_type": str(exc.headers.get("Content-Type") or "").strip() if exc.headers is not None else "",
                "status_code": int(exc.code or 0),
                "error_code": f"http_{int(exc.code or 0)}",
            }
        )
        return check
    except Exception as exc:
        check["error_code"] = exc.__class__.__name__
        return check


def _extract_html_title(text: str) -> str:
    parser = _TitleExtractor()
    try:
        parser.feed(str(text or ""))
        parser.close()
    except Exception:
        return ""
    return parser.title()


def _page_check_summary(page_checks: list[dict[str, Any]]) -> str:
    if not page_checks:
        return ""
    total = len(page_checks)
    successes = sum(1 for check in page_checks if check.get("reachable") is True)
    return f"Live page checks verified {successes}/{total} URLs."


def _stage_or_input(*, stage_payload: Mapping[str, Any], input_contract: Mapping[str, Any], key: str) -> Any:
    if key in stage_payload:
        return stage_payload.get(key)
    return input_contract.get(key)


def _result_id(*, packet: Mapping[str, Any], order: Mapping[str, Any], generated_at: str) -> str:
    # Safe-work results should refresh the same staged artifact across deferred retries.
    material = "|".join((str(packet.get("packet_id") or packet.get("packet_ref") or ""), str(order.get("work_order_id") or "")))
    return f"proactive-ooda-safe-work-{_hash_value(material)[:24]}"


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


def _hash_value(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()
