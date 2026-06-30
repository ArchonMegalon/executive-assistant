from __future__ import annotations

import html
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping
import urllib.error
import urllib.parse
import urllib.request

from app.services.proactive_ooda_browser_actions import (
    browser_action_handoff_required,
    browser_action_user_prompt,
    build_browser_action_receipt,
)
from app.services.proactive_ooda_stage_packets import (
    FORBIDDEN_WITHOUT_EXPLICIT_APPROVAL,
    SAFE_WORK_ORDER_SCHEMA,
)


SAFE_WORK_RESULT_SCHEMA = "proactive_ooda.safe_work_result.v1"
_EMAIL_PATTERN = re.compile(r"(?i)(?:mailto:)?([a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,})")
_PROVIDER_PAGE_MARKERS = (
    "contact",
    "kontakt",
    "email",
    "phone",
    "office",
    "services",
    "leistungen",
    "impressum",
    "befund",
    "befundung",
    "inspection",
    "quote",
    "estimate",
    "meister",
)
_STRONG_PROVIDER_PAGE_MARKERS = (
    "appointment",
    "availability",
    "befund",
    "befundung",
    "booking",
    "chimney sweep",
    "estimate",
    "gutachten",
    "gutachter",
    "inspection",
    "leistungen",
    "meister",
    "quote",
    "rauchfangkehrer",
    "sachverstaendiger",
    "sachverständiger",
    "schornsteinfeger",
    "services",
)
_NON_PROVIDER_MARKERS = (
    "cuisine",
    "encyclopedia",
    "german language",
    "michelin",
    "menu",
    "opera",
    "restaurant",
    "wikipedia",
)
_EDUCATIONAL_REFERENCE_MARKERS = (
    "difference between",
    "german language",
    "grammar",
    "how to say",
    "language lesson",
    "translation",
    "vocabulary",
)
_LOW_INFORMATION_QUERY_TOKENS = {
    "a",
    "about",
    "als",
    "am",
    "an",
    "and",
    "anfrage",
    "as",
    "at",
    "brauche",
    "contact",
    "details",
    "dem",
    "den",
    "der",
    "des",
    "die",
    "ein",
    "draft",
    "du",
    "einem",
    "einen",
    "eine",
    "einer",
    "eines",
    "email",
    "emailanfrage",
    "for",
    "formuliere",
    "found",
    "gefunden",
    "hast",
    "here",
    "ich",
    "im",
    "in",
    "inbox",
    "inquiry",
    "kann",
    "link",
    "look",
    "me",
    "mein",
    "meine",
    "meiner",
    "meinen",
    "mir",
    "my",
    "need",
    "needs",
    "of",
    "one",
    "or",
    "please",
    "provider",
    "reachability",
    "request",
    "review",
    "save",
    "search",
    "send",
    "schicke",
    "speicher",
    "sie",
    "such",
    "suche",
    "the",
    "to",
    "und",
    "verwenden",
    "vendor",
    "visible",
    "wenn",
    "what",
    "when",
    "whether",
    "with",
    "you",
}
_LOCATION_LIKE_QUERY_TOKENS = {
    "austria",
    "oesterreich",
    "osterreich",
    "vienna",
    "wien",
}
_PROVIDER_BLOCKING_CONSTRAINT_MARKERS = (
    "educational or reference page",
    "encyclopedia result",
    "link not reachable",
    "not a direct provider page",
    "outside stored country context",
    "provider search query too generic",
)


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


class _SearchResultExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._collect_label = False
        self._collect_snippet = False
        self._current_index: int | None = None
        self._results: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {str(key).lower(): str(value or "") for key, value in attrs}
        css = attributes.get("class", "").lower()
        if tag.lower() == "a" and ("result__a" in css or "result-link" in css):
            href = _normalized_search_result_url(attributes.get("href", ""))
            if href:
                self._results.append({"url": href, "label": "", "snippet": ""})
                self._current_index = len(self._results) - 1
                self._collect_label = True
                self._collect_snippet = False
            return
        if self._current_index is not None and ("result__snippet" in css or "result-snippet" in css):
            self._collect_snippet = True

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "a" and self._collect_label:
            self._collect_label = False
            return
        if lowered in {"a", "div", "span"} and self._collect_snippet:
            self._collect_snippet = False

    def handle_data(self, data: str) -> None:
        if self._current_index is None:
            return
        text = str(data or "").strip()
        if not text:
            return
        if self._collect_label:
            existing = self._results[self._current_index]["label"]
            self._results[self._current_index]["label"] = f"{existing} {text}".strip() if existing else text
            return
        if self._collect_snippet:
            existing = self._results[self._current_index]["snippet"]
            self._results[self._current_index]["snippet"] = f"{existing} {text}".strip() if existing else text

    def results(self) -> list[dict[str, str]]:
        deduped: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in self._results:
            url = str(item.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            deduped.append(
                {
                    "url": url,
                    "label": str(item.get("label") or "").strip(),
                    "snippet": str(item.get("snippet") or "").strip(),
                }
            )
        return deduped


class _YahooSearchResultExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_result_block = False
        self._result_block_depth = 0
        self._in_title = False
        self._collect_label = False
        self._collect_snippet = False
        self._current_index: int | None = None
        self._results: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {str(key).lower(): str(value or "") for key, value in attrs}
        css = attributes.get("class", "").lower()
        classes = {item for item in css.split() if item}
        lowered = tag.lower()
        if lowered == "div" and {"dd", "algo", "algo-sr"}.issubset(classes):
            self._in_result_block = True
            self._result_block_depth = 1
            self._in_title = False
            self._collect_label = False
            self._collect_snippet = False
            self._current_index = None
            return
        if self._in_result_block and lowered == "div":
            self._result_block_depth += 1
        if not self._in_result_block:
            return
        if lowered == "h3" and "title" in classes:
            self._in_title = True
            return
        if lowered == "a" and self._in_title:
            raw_href = attributes.get("href", "")
            if "://r.search.yahoo.com/" not in raw_href:
                return
            href = _normalized_search_result_url(raw_href)
            if href:
                self._results.append({"url": href, "label": "", "snippet": ""})
                self._current_index = len(self._results) - 1
                self._collect_label = True
            return
        if self._current_index is not None and lowered == "p":
            self._collect_snippet = True

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if self._in_result_block and lowered == "div":
            self._result_block_depth -= 1
            if self._result_block_depth <= 0:
                self._in_result_block = False
                self._result_block_depth = 0
                self._in_title = False
                self._collect_label = False
                self._collect_snippet = False
                self._current_index = None
                return
        if lowered == "h3":
            self._in_title = False
            return
        if lowered == "a" and self._collect_label:
            self._collect_label = False
            return
        if lowered == "p" and self._collect_snippet:
            self._collect_snippet = False

    def handle_data(self, data: str) -> None:
        if self._current_index is None:
            return
        text = str(data or "").strip()
        if not text:
            return
        if self._collect_label:
            existing = self._results[self._current_index]["label"]
            self._results[self._current_index]["label"] = f"{existing} {text}".strip() if existing else text
            return
        if self._collect_snippet:
            existing = self._results[self._current_index]["snippet"]
            self._results[self._current_index]["snippet"] = f"{existing} {text}".strip() if existing else text

    def results(self) -> list[dict[str, str]]:
        deduped: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in self._results:
            url = str(item.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            deduped.append(
                {
                    "url": url,
                    "label": str(item.get("label") or "").strip(),
                    "snippet": str(item.get("snippet") or "").strip(),
                }
            )
        return deduped


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
    candidate_items = _candidate_items(input_contract=input_contract, stage_payload=stage_payload)
    if not candidate_items and network_fetch_enabled:
        candidate_items = _research_candidate_items(
            input_contract=input_contract,
            stage_payload=stage_payload,
            limit=network_fetch_limit,
            timeout_seconds=network_fetch_timeout_seconds,
        )
    context = _candidate_evaluation_context(input_contract=input_contract, stage_payload=stage_payload)
    page_checks = _page_checks(
        input_contract=input_contract,
        stage_payload=stage_payload,
        candidate_items=candidate_items,
        network_fetch_enabled=network_fetch_enabled,
        limit=network_fetch_limit,
        timeout_seconds=network_fetch_timeout_seconds,
    )
    candidate_items = _enrich_candidate_items(candidate_items, page_checks=page_checks)
    candidate_items, comparison_table = _rank_candidate_items(
        input_contract=input_contract,
        stage_payload=stage_payload,
        candidate_items=candidate_items,
        context=context,
    )
    recommendable_candidate_items = _recommendable_candidate_items(
        candidate_items=candidate_items,
        comparison_table=comparison_table,
        context=context,
    )
    comparison_table = _mark_recommendable_comparison_rows(
        candidate_items=candidate_items,
        comparison_table=comparison_table,
        recommendable_candidate_items=recommendable_candidate_items,
        context=context,
    )
    recommended = _recommended_option_or_draft(
        work_type=work_type,
        input_contract=input_contract,
        stage_payload=stage_payload,
        candidate_items=recommendable_candidate_items,
        context=context,
    )
    if (
        work_type != "draft"
        and context.get("provider_discovery_relevant")
        and candidate_items
        and not recommendable_candidate_items
    ):
        recommended = {}
    approval_required = bool(dict(packet.get("approval") or {}).get("required"))
    staged_action_url = _staged_action_url(
        stage_payload=stage_payload,
        recommended=recommended,
        candidate_items=recommendable_candidate_items,
    )
    audit = _safe_work_audit(
        work_type=work_type,
        input_contract=input_contract,
        stage_payload=stage_payload,
        context=context,
        candidate_items=candidate_items,
        recommended=recommended,
        recommendable_candidate_items=recommendable_candidate_items,
    )
    browser_action_receipt = build_browser_action_receipt(
        packet,
        generated_at=generated_at,
    )
    has_material = bool(
        recommended.get("value")
        or (
            candidate_items
            and (
                not context.get("provider_discovery_relevant")
                or bool(recommendable_candidate_items)
            )
        )
    )
    status = "staged_for_user_decision" if has_material else "blocked_needs_research_input"
    if browser_action_handoff_required(browser_action_receipt):
        status = "blocked_human_handoff_required"
    elif browser_action_receipt and not has_material:
        status = "blocked_needs_browser_action"
    summary = _summary(
        packet=packet,
        order=order,
        recommended=recommended,
        has_material=has_material,
        page_checks=page_checks,
    )
    approval_prompt = _approval_prompt(packet=packet, order=order, recommended=recommended, has_material=has_material)
    if status == "blocked_human_handoff_required":
        summary = _browser_action_summary(browser_action_receipt) or summary
        approval_prompt = browser_action_user_prompt(browser_action_receipt) or approval_prompt
    result_id = _result_id(packet=packet, order=order, generated_at=generated_at or "")
    return {
        "schema": SAFE_WORK_RESULT_SCHEMA,
        "result_id": result_id,
        "result_ref": f"safe_work_result:{result_id}",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "source_packet_ref_hash": _hash_value(str(packet.get("packet_ref") or packet.get("packet_id") or "")),
        "work_order_id_hash": _hash_value(str(order.get("work_order_id") or "")),
        "work_order_schema": str(order.get("schema") or ""),
        "status": status,
        "work_type": work_type,
        "summary": summary,
        "recommended_option_or_draft": recommended,
        "staged_action_url": staged_action_url,
        "shortlist": candidate_items,
        "comparison_table": comparison_table,
        "browser_action_receipt": browser_action_receipt,
        "audit": audit,
        "evidence_refs": _evidence_refs(
            input_contract=input_contract,
            stage_payload=stage_payload,
            candidate_items=candidate_items,
            page_checks=page_checks,
        ),
        "risks_or_tradeoffs": _risks_or_tradeoffs(input_contract=input_contract, stage_payload=stage_payload),
        "approval_prompt": approval_prompt,
        "approval": {
            "required": approval_required,
            "gate": str(order.get("approval_gate") or _approval_gate(packet) or "").strip(),
            "irreversible_actions_require_explicit_approval": True,
        },
        "execution_receipt": {
            "network_fetch_enabled": bool(network_fetch_enabled),
            "network_fetch_count": len(page_checks),
            "network_fetch_success_count": sum(1 for check in page_checks if check.get("reachable") is True),
            "search_candidate_count": sum(1 for item in candidate_items if str(item.get("candidate_source") or "") == "search_result"),
            "search_queries_used": _search_queries(input_contract=input_contract, stage_payload=stage_payload, limit=network_fetch_limit),
            "page_checks": page_checks,
            "browser_action_receipt_ref": str(browser_action_receipt.get("receipt_ref") or "").strip(),
            "browser_action_status": str(browser_action_receipt.get("status") or "").strip(),
            "browser_action_user_action_required": bool(browser_action_receipt.get("user_action_required")),
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
    if links:
        return [{"label": _label_from_url(url), "url": url} for url in links]
    target_sites = _string_list(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="target_sites"))
    if target_sites and _search_queries(input_contract=input_contract, stage_payload=stage_payload, limit=max(len(target_sites), 1)):
        return []
    return [{"label": _label_from_url(url), "url": url} for url in target_sites]


def _research_candidate_items(
    *,
    input_contract: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
    limit: int,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    queries = _search_queries(input_contract=input_contract, stage_payload=stage_payload, limit=limit)
    if not queries:
        return []
    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    max_results = max(int(limit or 1), 1)
    per_query_limit = max(1, min(3, max_results))
    for query in queries:
        for rank, result in enumerate(_search_results_for_query(query=query, timeout_seconds=timeout_seconds, limit=per_query_limit), start=1):
            url = str(result.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            candidates.append(
                {
                    "label": str(result.get("label") or _label_from_url(url)).strip() or _label_from_url(url),
                    "url": url,
                    "snippet": str(result.get("snippet") or "").strip(),
                    "source_query": query,
                    "candidate_source": "search_result",
                    "source_rank": rank,
                }
            )
            if len(candidates) >= max_results:
                return candidates
    return candidates


def _rank_candidate_items(
    *,
    input_contract: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
    candidate_items: list[dict[str, Any]],
    context: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not candidate_items:
        return candidate_items, []
    resolved_context = dict(context or _candidate_evaluation_context(input_contract=input_contract, stage_payload=stage_payload))
    analyses = [
        _candidate_analysis(candidate=item, index=index, context=resolved_context, candidate_items=candidate_items)
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


def _recommendable_candidate_items(
    *,
    candidate_items: list[dict[str, Any]],
    comparison_table: list[dict[str, Any]],
    context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not candidate_items or not context.get("provider_discovery_relevant"):
        return candidate_items
    recommendable: list[dict[str, Any]] = []
    for candidate, row in zip(candidate_items, comparison_table):
        if _candidate_recommendable_for_provider_decision(candidate=candidate, comparison_row=row, context=context):
            recommendable.append(candidate)
    return recommendable


def _candidate_recommendable_for_provider_decision(
    *,
    candidate: Mapping[str, Any],
    comparison_row: Mapping[str, Any],
    context: Mapping[str, Any],
) -> bool:
    if candidate.get("reachable") is False or comparison_row.get("reachable") is False:
        return False
    violations = " | ".join(str(item or "").strip().lower() for item in list(comparison_row.get("constraint_violations") or []))
    if any(marker in violations for marker in _PROVIDER_BLOCKING_CONSTRAINT_MARKERS):
        return False
    return _candidate_suitable_for_outreach_draft(candidate, context=context)


def _mark_recommendable_comparison_rows(
    *,
    candidate_items: list[dict[str, Any]],
    comparison_table: list[dict[str, Any]],
    recommendable_candidate_items: list[dict[str, Any]],
    context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not candidate_items or not context.get("provider_discovery_relevant"):
        return comparison_table
    if not recommendable_candidate_items:
        return [dict(row, recommended=False) for row in comparison_table]
    preferred_key = _candidate_identity_key(recommendable_candidate_items[0])
    marked: list[dict[str, Any]] = []
    for candidate, row in zip(candidate_items, comparison_table):
        marked.append(dict(row, recommended=_candidate_identity_key(candidate) == preferred_key))
    return marked


def _candidate_identity_key(candidate: Mapping[str, Any]) -> str:
    for key in ("final_url", "url", "link", "href", "label", "title"):
        value = str(candidate.get(key) or "").strip()
        if value:
            return value
    return json.dumps(_json_safe(candidate), sort_keys=True)


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
    target_hosts = _target_hosts(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="target_sites"))
    budget = _mapping_value(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="budget"))
    constraints = _mapping_value(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="constraints"))
    recipient_context = _mapping_value(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="recipient_context"))
    location_context = _location_context(recipient_context)
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
    delivery_days_max = _delivery_days_limit(
        deadline=_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="deadline"),
        delivery_window=_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="delivery_window"),
        constraints=constraints,
    )
    provider_query_texts = _provider_query_texts(input_contract=input_contract, stage_payload=stage_payload)
    provider_query_terms = _informative_provider_query_terms(provider_query_texts)
    all_text = tuple(dict.fromkeys((*selection_criteria, *comparison_dimensions, *preferences, *requirements)))
    provider_relevance_text = tuple(dict.fromkeys((*all_text, *provider_query_texts)))
    return {
        "selection_criteria": selection_criteria,
        "comparison_dimensions": comparison_dimensions,
        "preferences": preferences,
        "requirements": requirements,
        "exclusions": exclusions,
        "recipient_context": recipient_context,
        "location_context": location_context,
        "target_hosts": target_hosts,
        "budget_max": budget_max,
        "budget_min": budget_min,
        "budget_currency": budget_currency,
        "delivery_days_max": delivery_days_max,
        "provider_query_texts": provider_query_texts,
        "provider_query_terms": provider_query_terms,
        "provider_search_query_too_generic": bool(provider_query_texts) and not provider_query_terms,
        "all_text": all_text,
        "location_relevant": bool(location_context.get("phrases") or location_context.get("city_terms") or location_context.get("postal_codes")),
        "price_relevant": any(_text_mentions(term, ("price", "budget", "cheap", "cost", "value")) for term in all_text),
        "timing_relevant": any(_text_mentions(term, ("timing", "delivery", "soon", "fast", "quick", "eta")) for term in all_text),
        "reversibility_relevant": any(_text_mentions(term, ("reversible", "refund", "return", "cancel", "flexib")) for term in all_text),
        "availability_relevant": any(_text_mentions(term, ("stock", "available", "availability", "ready")) for term in all_text),
        "provider_discovery_relevant": any(
            _text_mentions(
                term,
                (
                    "contact",
                    "reachability",
                    "fit to request",
                    "vendor",
                    "provider",
                    "contractor",
                    "specialist",
                    "inquiry",
                    "anfrage",
                    "gutachten",
                    "befund",
                    "inspection",
                    "estimate",
                    "quote",
                ),
            )
            for term in provider_relevance_text
        ),
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
    candidate_host = _url_host(str(candidate.get("final_url") or candidate.get("url") or candidate.get("link") or candidate.get("href") or ""))
    candidate_contact_email = _candidate_contact_email(candidate)

    location_analysis = _candidate_location_analysis(candidate=candidate, search_text=search_text, context=context)
    score += float(location_analysis["score"])
    matched_criteria.extend(location_analysis["matched_criteria"])
    constraint_violations.extend(location_analysis["constraint_violations"])
    recommendation_reasons.extend(location_analysis["recommendation_reasons"])

    for target_host in context.get("target_hosts", ()):
        if _host_matches(candidate_host, target_host):
            score += 6
            matched_criteria.append(f"target site {target_host}")
            recommendation_reasons.append("matches preferred site")
            break

    if candidate.get("reachable") is True:
        score += 18
        recommendation_reasons.append("link verified reachable")
    elif candidate.get("reachable") is False:
        score -= 12
        constraint_violations.append("link not reachable")

    if context.get("provider_discovery_relevant"):
        provider_signal = _candidate_has_provider_signal(search_text)
        strong_provider_signal = _candidate_has_strong_provider_signal(search_text, context=context)
        request_term_matches = _provider_query_term_matches(search_text, context=context)
        educational_reference = _candidate_is_educational_reference(search_text)
        non_provider_reference = _candidate_is_non_provider_reference(search_text)
        generic_provider_query = bool(context.get("provider_search_query_too_generic"))
        if generic_provider_query and not strong_provider_signal:
            score -= 20
            constraint_violations.append("provider search query too generic")
        if context.get("provider_query_terms") and not request_term_matches:
            score -= 28
            constraint_violations.append("provider request terms missing")
        if candidate_contact_email and not educational_reference and (not generic_provider_query or strong_provider_signal):
            score += 20
            matched_criteria.append("contact details visible")
            recommendation_reasons.append("contact details found")
        elif provider_signal:
            score += 8
            recommendation_reasons.append("provider-style page")
        if candidate_host.endswith("wikipedia.org"):
            score -= 36
            constraint_violations.append("encyclopedia result")
        elif educational_reference and not strong_provider_signal:
            score -= 36
            constraint_violations.append("educational or reference page")
        elif non_provider_reference and not strong_provider_signal:
            score -= 24
            constraint_violations.append("not a direct provider page")

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

    if context.get("delivery_days_max") is not None and delivery_days is not None:
        delivery_days_max = float(context["delivery_days_max"])
        if delivery_days <= delivery_days_max:
            score += 12
            matched_criteria.append(f"delivery within {delivery_days_max:g} days")
            recommendation_reasons.append("meets timing window")
        else:
            score -= 20
            constraint_violations.append(f"misses timing window ({delivery_days:g}d > {delivery_days_max:g}d)")

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

    preference_assessment = _mapping_value(candidate.get("preference_assessment"))
    if preference_assessment:
        fit_score = _float_value(preference_assessment.get("fit_score"))
        if fit_score is not None:
            score += max(-20.0, min(20.0, round((fit_score - 50.0) * 0.4, 2)))
            if fit_score >= 55:
                matched_criteria.append(f"profile fit {fit_score:g}")
        recommendation = str(preference_assessment.get("recommendation") or "").strip().lower()
        if recommendation == "shortlist":
            score += 6
            recommendation_reasons.append("profile recommends shortlist")
        elif recommendation == "mention":
            score += 2
        elif recommendation == "reject":
            score -= 8
        for value in list(preference_assessment.get("match_reasons_json") or [])[:2]:
            text = str(value or "").strip()
            if text:
                recommendation_reasons.append(text)
        for value in list(preference_assessment.get("mismatch_reasons_json") or [])[:2]:
            text = str(value or "").strip()
            if text:
                constraint_violations.append(text)
        for value in list(preference_assessment.get("blocking_constraints_json") or [])[:2]:
            text = str(value or "").strip()
            if text:
                score -= 25
                constraint_violations.append(text)

    return {
        "index": index,
        "score": score,
        "matched_criteria": tuple(dict.fromkeys(item for item in matched_criteria if item)),
        "constraint_violations": tuple(dict.fromkeys(item for item in constraint_violations if item)),
        "recommendation_reasons": tuple(dict.fromkeys(item for item in recommendation_reasons if item))[:4],
    }


def _candidate_location_analysis(
    *,
    candidate: Mapping[str, Any],
    search_text: str,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    location_context = _mapping_value(context.get("location_context"))
    if not location_context:
        return {"score": 0.0, "matched_criteria": (), "constraint_violations": (), "recommendation_reasons": ()}
    matched_criteria: list[str] = []
    constraint_violations: list[str] = []
    recommendation_reasons: list[str] = []
    score = 0.0
    matched_locality = False
    candidate_host = _url_host(str(candidate.get("final_url") or candidate.get("url") or candidate.get("link") or candidate.get("href") or ""))
    normalized_text = _ascii_fold_text(search_text)
    for phrase in list(location_context.get("phrases") or []):
        normalized_phrase = _ascii_fold_text(str(phrase or "").strip().lower())
        if normalized_phrase and normalized_phrase in normalized_text:
            matched_locality = True
            score += 12
            matched_criteria.append(f"location {str(phrase).strip()}")
            recommendation_reasons.append("matches stored location context")
            break
    if not matched_locality:
        for postal_code in list(location_context.get("postal_codes") or []):
            normalized_code = str(postal_code or "").strip()
            if normalized_code and normalized_code in normalized_text:
                matched_locality = True
                score += 10
                matched_criteria.append(f"postal {normalized_code}")
                recommendation_reasons.append("matches stored postal context")
                break
    if not matched_locality:
        for city in list(location_context.get("city_terms") or []):
            normalized_city = _ascii_fold_text(str(city or "").strip().lower())
            if normalized_city and normalized_city in normalized_text:
                matched_locality = True
                score += 8
                matched_criteria.append(f"city {str(city).strip()}")
                recommendation_reasons.append("matches stored city context")
                break
            if normalized_city and candidate_host.endswith(f".{normalized_city}"):
                matched_locality = True
                score += 8
                matched_criteria.append(f"city {str(city).strip()}")
                recommendation_reasons.append("matches stored city context")
                break
    country_codes = [str(item or "").strip().upper() for item in list(location_context.get("country_codes") or []) if str(item or "").strip()]
    if country_codes:
        preferred_tlds = {f".{code.lower()}" for code in country_codes if len(code) == 2}
        if any(candidate_host.endswith(tld) for tld in preferred_tlds):
            score += 8
            recommendation_reasons.append("country-level host match")
        elif candidate_host and any(candidate_host.endswith(f".{code}") for code in ("de", "fr", "it", "uk", "us")) and not matched_locality:
            preferred = country_codes[0]
            if preferred not in {"DE", "FR", "IT", "UK", "US"}:
                score -= 18
                constraint_violations.append("outside stored country context")
    return {
        "score": score,
        "matched_criteria": tuple(dict.fromkeys(item for item in matched_criteria if item)),
        "constraint_violations": tuple(dict.fromkeys(item for item in constraint_violations if item)),
        "recommendation_reasons": tuple(dict.fromkeys(item for item in recommendation_reasons if item))[:2],
    }


def _recommended_option_or_draft(
    *,
    work_type: str,
    input_contract: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
    candidate_items: list[dict[str, Any]],
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if work_type == "draft":
        return _draft_recommended_option_or_draft(
            input_contract=input_contract,
            stage_payload=stage_payload,
            candidate_items=candidate_items,
            context=context,
        )
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


def _draft_recommended_option_or_draft(
    *,
    input_contract: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
    candidate_items: list[dict[str, Any]],
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    draft_mode = str(stage_payload.get("draft_mode") or "").strip().lower()
    resolved_context = dict(context or _candidate_evaluation_context(input_contract=input_contract, stage_payload=stage_payload))
    preferred_candidate = _preferred_draft_candidate(
        candidate_items,
        context=resolved_context,
    )
    if draft_mode == "research_backed_inquiry" and preferred_candidate:
        draft_text = _research_backed_draft_text(
            input_contract=input_contract,
            stage_payload=stage_payload,
            candidate=preferred_candidate,
        )
        if draft_text:
            recipient_email = _candidate_contact_email(preferred_candidate)
            return {
                "kind": "draft_text",
                "value": draft_text,
                "source": "candidate_synthesis",
                "candidate": preferred_candidate,
                "recipient_email": recipient_email,
            }
    draft = stage_payload.get("draft_text") or stage_payload.get("draft")
    if draft:
        return {"kind": "draft_text", "value": _json_safe(draft), "source": "stage_payload"}
    if draft_mode == "research_backed_inquiry":
        if resolved_context.get("provider_discovery_relevant"):
            return {}
        fallback = _fallback_research_backed_draft_text(input_contract=input_contract, stage_payload=stage_payload)
        if fallback:
            return {"kind": "draft_text", "value": fallback, "source": "request_fallback"}
    return {}


def _research_backed_draft_text(
    *,
    input_contract: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> str:
    request_text = _outreach_request_text(input_contract=input_contract, stage_payload=stage_payload)
    locale = _draft_locale(stage_payload)
    request_line = request_text or str(stage_payload.get("research_query") or _first_string(input_contract.get("search_queries")) or "").strip()
    candidate_label = str(
        candidate.get("label")
        or candidate.get("page_title")
        or candidate.get("final_url")
        or candidate.get("url")
        or "the contact"
    ).strip()
    url = str(candidate.get("final_url") or candidate.get("url") or "").strip()
    requester_contact = _requester_contact_context(input_contract=input_contract, stage_payload=stage_payload)
    onsite_relevant = _outreach_onsite_appointment_relevant(request_line, stage_payload=stage_payload, input_contract=input_contract)
    request_sentence = _sentence_fragment(request_line or candidate_label)
    if locale == "de":
        if onsite_relevant:
            lines = [
                "Draft to review:",
                "",
                "Guten Tag,",
                "",
                f"ich brauche einen Vor-Ort-Termin fuer folgende Anfrage: {request_sentence}.",
            ]
            if requester_contact.get("address"):
                lines.append(f"Adresse: {requester_contact['address']}")
            if requester_contact.get("phone"):
                lines.append(f"Telefon: {requester_contact['phone']}")
            lines.append("Koennen Sie mir bitte sagen, ob Sie dafuer zustaendig sind und wann ein Termin moeglich waere?")
            lines.extend(["", "Beste Gruesse"])
            return "\n".join(lines).strip()
        lines = [
            "Draft to review:",
            "",
            "Guten Tag,",
            "",
            f"ich habe Sie als moeglichen Ansprechpartner fuer folgende Anfrage gefunden: {request_sentence}.",
            "Koennen Sie mir bitte sagen, ob Sie dafuer zustaendig sind, welche Unterlagen Sie benoetigen und wann ein Termin moeglich waere?",
        ]
        if candidate_label:
            lines.append(f"Gefundener Kontakt: {candidate_label}.")
        if url:
            lines.append(f"Quelle: {url}")
        lines.extend(["", "Beste Gruesse"])
        return "\n".join(lines).strip()
    lines = [
        "Draft to review:",
        "",
        "Hello,",
        "",
        (
            f"I need an on-site appointment for this request: {request_sentence}."
            if onsite_relevant
            else f"I found you as a possible contact for this request: {request_sentence}."
        ),
    ]
    if onsite_relevant and requester_contact.get("address"):
        lines.append(f"Address: {requester_contact['address']}")
    if onsite_relevant and requester_contact.get("phone"):
        lines.append(f"Phone: {requester_contact['phone']}")
    lines.extend([
        "Please let me know whether you handle this, what information you need from me, and when you would have availability.",
    ])
    if candidate_label:
        lines.append(f"Contact found: {candidate_label}.")
    if url:
        lines.append(f"Source: {url}")
    lines.extend(["", "Best regards"])
    return "\n".join(lines).strip()


def _sentence_fragment(value: str) -> str:
    return str(value or "").strip(" \t\r\n.,;:")


def _requester_contact_context(*, input_contract: Mapping[str, Any], stage_payload: Mapping[str, Any]) -> dict[str, str]:
    recipient_context = _mapping_value(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="recipient_context"))
    contact = _mapping_value(recipient_context.get("contact"))
    location = _mapping_value(recipient_context.get("location"))
    address = _first_present_string(
        recipient_context.get("address"),
        recipient_context.get("street_address"),
        recipient_context.get("postal_address"),
        contact.get("address"),
        contact.get("street_address"),
        location.get("address"),
        location.get("street_address"),
        location.get("primary_address"),
        _first_string(location.get("addresses")),
    )
    phone = _first_present_string(
        recipient_context.get("phone"),
        recipient_context.get("phone_number"),
        recipient_context.get("tel"),
        recipient_context.get("telephone"),
        recipient_context.get("mobile"),
        contact.get("phone"),
        contact.get("phone_number"),
        contact.get("tel"),
        contact.get("telephone"),
        contact.get("mobile"),
    )
    return {
        "address": address,
        "phone": phone,
    }


def _first_present_string(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _outreach_onsite_appointment_relevant(
    request_text: str,
    *,
    input_contract: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
) -> bool:
    haystack = " ".join(
        str(value or "")
        for value in (
            request_text,
            stage_payload.get("appointment_type"),
            stage_payload.get("subject_hint"),
            stage_payload.get("research_query"),
            input_contract.get("appointment_type"),
            input_contract.get("subject_hint"),
            input_contract.get("research_query"),
            " ".join(_criteria_texts(stage_payload.get("selection_criteria"))),
            " ".join(_criteria_texts(input_contract.get("selection_criteria"))),
        )
    )
    normalized = _ascii_fold_text(haystack)
    return any(
        marker in normalized
        for marker in (
            "vor ort",
            "vor-ort",
            "onsite",
            "on site",
            "on-site",
            "termin",
            "appointment",
            "besichtigung",
            "ausmessen",
        )
    )


def _fallback_research_backed_draft_text(
    *,
    input_contract: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
) -> str:
    request_text = _outreach_request_text(input_contract=input_contract, stage_payload=stage_payload)
    if not request_text:
        return ""
    locale = _draft_locale(stage_payload)
    if locale == "de":
        return "\n".join(
            [
                "Draft to review:",
                "",
                "Guten Tag,",
                "",
                f"ich moechte zu folgender Anfrage Kontakt aufnehmen: {request_text}.",
                "Koennen Sie mir bitte sagen, ob Sie dafuer zustaendig sind, welche Unterlagen Sie benoetigen und wann ein Termin moeglich waere?",
                "",
                "Beste Gruesse",
            ]
        ).strip()
    return "\n".join(
        [
            "Draft to review:",
            "",
            "Hello,",
            "",
            f"I would like to reach out about the following request: {request_text}.",
            "Please let me know whether you handle this, what information you need from me, and when you would have availability.",
            "",
            "Best regards",
        ]
    ).strip()


def _outreach_request_text(*, input_contract: Mapping[str, Any], stage_payload: Mapping[str, Any]) -> str:
    request_text = _draft_request_text(input_contract=input_contract, stage_payload=stage_payload)
    if not request_text:
        return ""
    sanitized = _sanitize_outreach_request_text(request_text)
    if sanitized:
        return sanitized if _outreach_request_text_has_actionable_content(sanitized) else ""
    if _outreach_meta_clause(request_text):
        return ""
    return request_text if _outreach_request_text_has_actionable_content(request_text) else ""


def _sanitize_outreach_request_text(request_text: str) -> str:
    text = " ".join(str(request_text or "").split()).strip()
    if not text:
        return ""
    clauses = [
        part.strip(" ,")
        for part in re.split(r"(?<=[.!?])\s+", text)
        if part.strip(" ,")
    ]
    kept = [part for part in clauses if not _outreach_meta_clause(part)]
    normalized = " ".join(kept).strip() if kept else text
    normalized = re.sub(
        r"\b(?:when|if)\s+you\s+find\s+(?:one|someone)\b.*$",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip(" ,")
    normalized = re.sub(
        r"\bwenn\s+du\s+ein(?:en|e)?\s+gefunden\s+hast\b.*$",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip(" ,")
    normalized = re.sub(
        r"\b(?:schick(?:e)?\s+mir\s+h(?:ie|ier)\s+den\s+link|send\s+me\s+(?:the\s+)?link)\b.*$",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip(" ,")
    normalized = re.sub(
        r"^(?:suche\s+mir|suche|such|find\s+me|find|look\s+for)\s+[^-,:;.!?]+[-,:;]\s*(?=(?:ich\s+brauche|ich\s+benoetige|i\s+need|ob\s+ich|whether\s+i))",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip(" ,")
    normalized = re.sub(r"\s+", " ", normalized).strip(" ,")
    return normalized


def _outreach_meta_clause(text: str) -> bool:
    lowered = " ".join(str(text or "").strip().lower().split())
    if not lowered:
        return False
    meta_markers = (
        "als draft",
        "als entwurf",
        "draft in meiner inbox",
        "draft in my inbox",
        "emailanfrage",
        "formuliere",
        "for approval",
        "in meiner inbox",
        "in my inbox",
        "schicke mir hier den link",
        "save it as a draft",
        "save the draft",
        "send me the link",
        "speicher",
    )
    return any(marker in lowered for marker in meta_markers)


def _outreach_request_text_has_actionable_content(text: str) -> bool:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return False
    if _informative_provider_query_terms((normalized,)):
        return True
    return len(re.findall(r"[A-Za-z0-9]{3,}", _ascii_fold_text(normalized))) >= 5


def _draft_request_text(*, input_contract: Mapping[str, Any], stage_payload: Mapping[str, Any]) -> str:
    for value in (
        stage_payload.get("draft_request_text"),
        stage_payload.get("request"),
        stage_payload.get("request_text"),
        stage_payload.get("user_request"),
        stage_payload.get("task_request"),
        stage_payload.get("research_query"),
        input_contract.get("draft_request_text"),
        input_contract.get("request"),
        input_contract.get("request_text"),
        input_contract.get("user_request"),
        input_contract.get("task_request"),
        input_contract.get("research_query"),
        _first_string(input_contract.get("search_queries")),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _draft_locale(stage_payload: Mapping[str, Any]) -> str:
    normalized = str(stage_payload.get("locale") or "").strip().lower()
    return "de" if normalized.startswith("de") else "en"


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


def _browser_action_summary(receipt: Mapping[str, Any]) -> str:
    if not receipt:
        return ""
    target = receipt.get("target") if isinstance(receipt.get("target"), Mapping) else {}
    handoff = receipt.get("handoff") if isinstance(receipt.get("handoff"), Mapping) else {}
    host = str(target.get("site_host") or "").strip()
    reason = str(handoff.get("reason") or "").strip()
    if host and reason:
        return f"Browser task for {host} needs a human handoff before EA can continue."
    if reason:
        return "Browser task needs a human handoff before EA can continue."
    return ""


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
    approval_required = bool(dict(packet.get("approval") or {}).get("required"))
    if has_material:
        kind = str(recommended.get("kind") or "result").replace("_", " ")
        if not approval_required:
            return f"EA can proceed with this staged {kind} without extra approval. {gate}"
        return f"Approve whether EA should proceed with this staged {kind}. {gate}"
    if not approval_required:
        return f"EA can research further or change constraints without extra approval. {gate}"
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
        if key in {"candidate_source", "source_query", "source_rank", "url", "link", "href", "final_url"}:
            return
        text = str(value).strip()
        if not text:
            return
        pieces.append(f"{key} {text}".strip() if key else text)

    _visit(candidate)
    return " ".join(pieces).lower()


def _provider_query_texts(*, input_contract: Mapping[str, Any], stage_payload: Mapping[str, Any]) -> tuple[str, ...]:
    texts: list[str] = []
    for key in ("search_queries", "research_query", "request", "request_text", "user_request", "task_request", "draft_request_text", "subject_hint"):
        value = _stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key=key)
        if isinstance(value, (list, tuple)):
            texts.extend(_string_list(value))
            continue
        text = str(value or "").strip()
        if text:
            texts.append(text)
    return tuple(dict.fromkeys(text for text in texts if text))


def _informative_provider_query_terms(query_texts: Iterable[str]) -> tuple[str, ...]:
    terms: list[str] = []
    for query in query_texts:
        normalized = _ascii_fold_text(str(query or ""))
        for token in re.findall(r"[a-z0-9]{3,}", normalized):
            if token.isdigit():
                continue
            if token in _LOW_INFORMATION_QUERY_TOKENS or token in _LOCATION_LIKE_QUERY_TOKENS:
                continue
            terms.append(token)
    return tuple(dict.fromkeys(terms))[:12]


def _candidate_has_provider_signal(search_text: str) -> bool:
    return _text_mentions(search_text, _PROVIDER_PAGE_MARKERS)


def _candidate_has_strong_provider_signal(search_text: str, *, context: Mapping[str, Any]) -> bool:
    if _candidate_has_strong_provider_marker(search_text):
        return True
    return bool(_provider_query_term_matches(search_text, context=context))


def _provider_query_term_matches(search_text: str, *, context: Mapping[str, Any]) -> tuple[str, ...]:
    normalized = _ascii_fold_text(search_text)
    tokens = set(re.findall(r"[a-z0-9]{3,}", normalized))
    matches: list[str] = []
    for term in tuple(context.get("provider_query_terms") or ()):
        normalized_term = str(term or "").strip().lower()
        if not normalized_term:
            continue
        if normalized_term in tokens or (len(normalized_term) >= 6 and normalized_term in normalized):
            matches.append(normalized_term)
    return tuple(dict.fromkeys(matches))


def _candidate_has_strong_provider_marker(search_text: str) -> bool:
    return _text_mentions(search_text, _STRONG_PROVIDER_PAGE_MARKERS)


def _candidate_is_educational_reference(search_text: str) -> bool:
    return _text_mentions(search_text, _EDUCATIONAL_REFERENCE_MARKERS)


def _candidate_is_non_provider_reference(search_text: str) -> bool:
    return _text_mentions(search_text, _NON_PROVIDER_MARKERS) or _candidate_is_educational_reference(search_text)


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


def _delivery_days_limit(
    *,
    deadline: Any,
    delivery_window: Any,
    constraints: Mapping[str, Any],
) -> float | None:
    for source in (constraints, _mapping_value(delivery_window)):
        limit = _float_value(
            source.get("delivery_days_max"),
            source.get("eta_days_max"),
            source.get("lead_time_days_max"),
            source.get("max_delivery_days"),
        )
        if limit is not None:
            return limit
    deadline_text = str(deadline or "").strip()
    if deadline_text:
        parsed = _parse_datetime(deadline_text)
        if parsed is not None:
            remaining = max((parsed - datetime.now(timezone.utc)).total_seconds() / 86400.0, 0.0)
            return round(remaining, 2)
    window_text = str(delivery_window or "").strip()
    if window_text:
        limit = _float_value(window_text)
        if limit is not None:
            return limit
    return None


def _parse_datetime(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _upper_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text.upper()
    return ""


def _text_mentions(text: str, needles: tuple[str, ...]) -> bool:
    haystack = str(text or "").lower()
    return any(needle in haystack for needle in needles)


def _ascii_fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def _location_context(recipient_context: Mapping[str, Any]) -> dict[str, Any]:
    location = _mapping_value(recipient_context.get("location"))
    if not location:
        return {}
    return {
        "phrases": list(dict.fromkeys(_string_list(location.get("phrases") or location.get("terms"))))[:4],
        "city_terms": list(dict.fromkeys(_string_list(location.get("city_terms") or location.get("cities"))))[:3],
        "postal_codes": list(dict.fromkeys(_string_list(location.get("postal_codes") or location.get("postcodes"))))[:3],
        "country_codes": [str(item or "").strip().upper() for item in list(location.get("country_codes") or []) if str(item or "").strip()][:2],
        "country_names": list(dict.fromkeys(_string_list(location.get("country_names") or location.get("countries"))))[:2],
    }


def _location_query_variants(location_context: Mapping[str, Any]) -> tuple[str, ...]:
    variants: list[str] = []
    for phrase in list(location_context.get("phrases") or []):
        text = str(phrase or "").strip()
        if re.search(r"\b\d{4,5}\b", text):
            variants.append(text)
    for city in list(location_context.get("city_terms") or []):
        text = str(city or "").strip()
        if text:
            variants.append(text)
    return tuple(dict.fromkeys(variants))[:3]


def _search_query_has_locality(query: str, location_variants: Iterable[str]) -> bool:
    normalized_query = _ascii_fold_text(query)
    return any(_ascii_fold_text(str(variant or "").strip()) in normalized_query for variant in location_variants if str(variant or "").strip())


def _label_from_url(url: str) -> str:
    normalized = str(url or "").strip()
    return normalized.split("//", 1)[-1].split("/", 1)[0] or normalized or "link"


def _preferred_candidate(items: list[dict[str, Any]]) -> dict[str, Any]:
    return items[0] if items else {}


def _preferred_draft_candidate(
    items: list[dict[str, Any]],
    *,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    for item in items:
        if _candidate_suitable_for_outreach_draft(item, context=context):
            return dict(item)
    return {}


def _candidate_suitable_for_outreach_draft(candidate: Mapping[str, Any], *, context: Mapping[str, Any]) -> bool:
    if not candidate:
        return False
    if not context.get("provider_discovery_relevant"):
        return True
    search_text = _candidate_search_text(candidate)
    candidate_host = _url_host(str(candidate.get("final_url") or candidate.get("url") or candidate.get("link") or candidate.get("href") or ""))
    contact_email = _candidate_contact_email(candidate)
    provider_signal = _candidate_has_provider_signal(search_text)
    strong_provider_signal = _candidate_has_strong_provider_signal(search_text, context=context)
    strong_provider_marker = _candidate_has_strong_provider_marker(search_text)
    request_term_matches = _provider_query_term_matches(search_text, context=context)
    if candidate_host.endswith("wikipedia.org"):
        return False
    if _candidate_is_educational_reference(search_text) and not strong_provider_marker:
        return False
    if _candidate_is_non_provider_reference(search_text) and not strong_provider_marker:
        return False
    if context.get("provider_search_query_too_generic") and not strong_provider_signal:
        return False
    if context.get("provider_query_terms") and not request_term_matches:
        return False
    return bool(contact_email or provider_signal)


def _safe_work_audit(
    *,
    work_type: str,
    input_contract: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
    context: Mapping[str, Any],
    candidate_items: list[dict[str, Any]],
    recommended: Mapping[str, Any],
    recommendable_candidate_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    recommendable_count = len(recommendable_candidate_items or [])
    if not recommended and not candidate_items:
        issues.append(
            {
                "code": "no_decision_ready_material",
                "severity": "warn",
                "detail": "Safe work produced no recommendation, draft, shortlist, or action link to review.",
            }
        )
    if (
        work_type != "draft"
        and context.get("provider_discovery_relevant")
        and candidate_items
        and recommendable_count <= 0
    ):
        issues.append(
            {
                "code": "no_provider_safe_candidate",
                "severity": "warn",
                "detail": "Observed candidates were retained for audit, but none looked safe enough to recommend as a direct provider contact.",
            }
        )
    if work_type == "draft" and str(stage_payload.get("draft_mode") or "").strip().lower() == "research_backed_inquiry":
        if context.get("provider_search_query_too_generic"):
            issues.append(
                {
                    "code": "provider_query_too_generic",
                    "severity": "warn",
                    "detail": "The provider search query was too generic to trust for outreach without review.",
                }
            )
        raw_request = _draft_request_text(input_contract=input_contract, stage_payload=stage_payload)
        sanitized_request = _outreach_request_text(input_contract=input_contract, stage_payload=stage_payload)
        if raw_request and sanitized_request and raw_request != sanitized_request:
            issues.append(
                {
                    "code": "operator_meta_removed_from_outreach_request",
                    "severity": "info",
                    "detail": "Provider-facing draft text removed operator workflow instructions before synthesis.",
                }
            )
        top_candidate = candidate_items[0] if candidate_items else {}
        if top_candidate and not _candidate_suitable_for_outreach_draft(top_candidate, context=context):
            issues.append(
                {
                    "code": "top_candidate_not_provider_like",
                    "severity": "warn",
                    "detail": "The top-ranked candidate does not look like a direct provider contact page.",
                }
            )
        if str(recommended.get("source") or "").strip() == "request_fallback":
            issues.append(
                {
                    "code": "draft_used_request_fallback",
                    "severity": "warn",
                    "detail": "No provider-safe contact candidate passed the outreach checks, so the draft was kept generic.",
                }
            )
        if not str(recommended.get("value") or "").strip():
            issues.append(
                {
                    "code": "draft_not_created",
                    "severity": "warn",
                    "detail": "EA did not have enough provider-safe request context to create an outreach draft.",
                }
            )
    return {
        "status": "review" if issues else "pass",
        "issues": issues,
    }


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
            contact_email = str(check.get("contact_email") or "").strip()
            if contact_email:
                candidate["contact_email"] = contact_email
            if isinstance(check.get("contact_emails"), list) and check.get("contact_emails"):
                candidate["contact_emails"] = list(check.get("contact_emails") or [])
            if check.get("error_code"):
                candidate["fetch_error_code"] = str(check.get("error_code") or "").strip()
        enriched.append(candidate)
    return enriched


def _page_checks(
    *,
    input_contract: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
    candidate_items: list[dict[str, Any]],
    network_fetch_enabled: bool,
    limit: int,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    if not network_fetch_enabled:
        return []
    urls: list[str] = []
    for item in candidate_items:
        urls.extend(_candidate_urls(item))
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
        "contact_email": "",
        "contact_emails": [],
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
        emails = _extract_contact_emails(page_text)
        check.update(
            {
                "reachable": True,
                "final_url": final_url,
                "page_title": title,
                "content_type": content_type,
                "status_code": status_code,
                "contact_email": emails[0] if emails else "",
                "contact_emails": list(emails),
            }
        )
        return check
    except urllib.error.HTTPError as exc:
        final_url = str(getattr(exc, "geturl", lambda: url)() or url).strip()
        body = exc.read(65536)
        charset = exc.headers.get_content_charset() if exc.headers is not None else None
        page_text = body.decode(charset or "utf-8", errors="replace") if body else ""
        title = _extract_html_title(page_text) if page_text else ""
        emails = _extract_contact_emails(page_text) if page_text else ()
        check.update(
            {
                "final_url": final_url,
                "page_title": title,
                "content_type": str(exc.headers.get("Content-Type") or "").strip() if exc.headers is not None else "",
                "status_code": int(exc.code or 0),
                "error_code": f"http_{int(exc.code or 0)}",
                "contact_email": emails[0] if emails else "",
                "contact_emails": list(emails),
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


def _extract_contact_emails(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in _EMAIL_PATTERN.findall(str(text or "")):
        normalized = str(match or "").strip().strip(" .,:;<>[](){}").lower()
        if not normalized or normalized in found:
            continue
        found.append(normalized)
    return tuple(found[:4])


def _candidate_contact_email(candidate: Mapping[str, Any]) -> str:
    for value in (
        candidate.get("contact_email"),
        candidate.get("email"),
        candidate.get("contact_emails"),
    ):
        if isinstance(value, (list, tuple)):
            for item in value:
                normalized = str(item or "").strip()
                if normalized:
                    return normalized
            continue
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""


def _search_queries(
    *,
    input_contract: Mapping[str, Any],
    stage_payload: Mapping[str, Any],
    limit: int,
) -> tuple[str, ...]:
    base_queries = []
    for value in (
        _stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="search_queries"),
        _stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="research_query"),
        _stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="request"),
        _stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="request_text"),
        _stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="user_request"),
        _stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="task_request"),
        _stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="draft_request_text"),
    ):
        if isinstance(value, (list, tuple)):
            base_queries.extend(_string_list(value))
        else:
            text = str(value or "").strip()
            if text:
                base_queries.append(text)
    hosts = _target_hosts(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="target_sites"))
    location_variants = _location_query_variants(_location_context(_mapping_value(_stage_or_input(stage_payload=stage_payload, input_contract=input_contract, key="recipient_context"))))
    queries: list[str] = []
    for query in base_queries:
        if not query:
            continue
        expanded_queries = [query]
        if location_variants and not _search_query_has_locality(query, location_variants):
            expanded_queries = [f"{query} {variant}".strip() for variant in location_variants[:2]] + expanded_queries
        for expanded_query in expanded_queries:
            if hosts:
                for host in hosts[:2]:
                    if "site:" in expanded_query.lower():
                        break
                    queries.append(f"site:{host} {expanded_query}")
            queries.append(expanded_query)
    deduped = tuple(dict.fromkeys(text.strip() for text in queries if text.strip()))
    return deduped[: max(int(limit or 1), 1)]


def _search_results_for_query(*, query: str, timeout_seconds: int, limit: int) -> list[dict[str, str]]:
    max_results = max(int(limit or 1), 1)
    for provider, request in _search_requests_for_query(query):
        try:
            with urllib.request.urlopen(request, timeout=max(int(timeout_seconds or 1), 1)) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                body = response.read(131072)
        except Exception:
            continue
        results = _parse_search_results(provider=provider, body=body, charset=charset)
        if results:
            return results[:max_results]
    return []


def _search_requests_for_query(query: str) -> tuple[tuple[str, urllib.request.Request], ...]:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; EA-Proactive-OODA/1.0)",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
    }
    ddg_params = urllib.parse.urlencode({"q": query})
    yahoo_params = urllib.parse.urlencode({"p": query})
    return (
        (
            "duckduckgo",
            urllib.request.Request(
                f"https://html.duckduckgo.com/html/?{ddg_params}",
                headers=headers,
                method="GET",
            ),
        ),
        (
            "yahoo",
            urllib.request.Request(
                f"https://search.yahoo.com/search?{yahoo_params}",
                headers=headers,
                method="GET",
            ),
        ),
    )


def _parse_search_results(*, provider: str, body: bytes, charset: str) -> list[dict[str, str]]:
    page = body.decode(charset, errors="replace")
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider == "duckduckgo":
        if _duckduckgo_search_challenge(page):
            return []
        parser = _SearchResultExtractor()
        parser.feed(page)
        return parser.results()
    if normalized_provider == "yahoo":
        return _yahoo_search_results(page)
    return []


def _duckduckgo_search_challenge(page: str) -> bool:
    lowered = str(page or "").lower()
    return (
        "anomaly-modal" in lowered
        or "bots use duckduckgo too" in lowered
        or "please complete the following challenge" in lowered
    )


def _yahoo_search_results(page: str) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    pattern = re.compile(
        r'href="(?P<href>https://r\.search\.yahoo\.com/[^"]+)"[^>]*>'
        r'(?P<anchor>.*?)</a>.*?'
        r'<div class="compText[^"]*"[^>]*>\s*<p[^>]*>(?P<snippet>.*?)</p>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(str(page or "")):
        title_match = re.search(
            r'<h3[^>]*class="[^"]*\btitle\b[^"]*"[^>]*>(?P<label>.*?)</h3>',
            match.group("anchor"),
            flags=re.IGNORECASE | re.DOTALL,
        )
        if title_match is None:
            continue
        url = _normalized_search_result_url(html.unescape(match.group("href")))
        label = _html_fragment_text(title_match.group("label"))
        snippet = _html_fragment_text(match.group("snippet"))
        if not url or not label or url in seen:
            continue
        seen.add(url)
        results.append({"url": url, "label": label, "snippet": snippet})
    return results


def _html_fragment_text(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(fragment or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _normalized_search_result_url(value: str) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        candidate = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
        return urllib.parse.unquote(candidate).strip()
    if parsed.netloc.endswith("search.yahoo.com"):
        match = re.search(r"/RU=([^/]+)/RK=", parsed.path)
        if match is not None:
            return urllib.parse.unquote(match.group(1)).strip()
    return url


def _target_hosts(value: Any) -> tuple[str, ...]:
    hosts: list[str] = []
    for raw in _string_list(value):
        host = _url_host(raw)
        if host and host not in hosts:
            hosts.append(host)
    return tuple(hosts)


def _url_host(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"https://{text}"
    parsed = urllib.parse.urlparse(text)
    return str(parsed.netloc or parsed.path).lower().split("@")[-1].split(":")[0].strip()


def _host_matches(candidate_host: str, target_host: str) -> bool:
    candidate = str(candidate_host or "").lower().strip()
    target = str(target_host or "").lower().strip()
    if not candidate or not target:
        return False
    return candidate == target or candidate.endswith(f".{target}")


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
