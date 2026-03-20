from __future__ import annotations

import inspect
import json
import os
import re
import shlex
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse, urlunparse

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult, artifact_preview_text, now_utc_iso
from app.services.tool_execution_common import ToolExecutionError
from app.services.tool_execution_connector_dispatch_adapter import ConnectorDispatchToolAdapter


def _extract_textish(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    if isinstance(value, list):
        return "\n".join(part for part in (_extract_textish(item) for item in value) if part).strip()
    if isinstance(value, dict):
        for key in ("text", "answer", "summary", "consensus", "recommendation", "message", "output", "result", "normalized_text"):
            text = _extract_textish(value.get(key))
            if text:
                return text
        try:
            return json.dumps(value, ensure_ascii=True)
        except Exception:
            return ""
    return ""


def _collect_text_fragments(value: object, *, limit: int = 64) -> tuple[str, ...]:
    collected: list[str] = []

    def _visit(node: object) -> None:
        if len(collected) >= limit:
            return
        if node is None:
            return
        if isinstance(node, (str, int, float, bool)):
            text = str(node).strip()
            if text:
                collected.append(text[:500])
            return
        if isinstance(node, dict):
            for key, nested in node.items():
                if len(collected) >= limit:
                    break
                key_text = str(key or "").strip()
                if key_text:
                    collected.append(key_text[:120])
                _visit(nested)
            return
        if isinstance(node, (list, tuple, set)):
            for nested in node:
                if len(collected) >= limit:
                    break
                _visit(nested)

    _visit(value)
    return tuple(collected)


def _has_marker(fragments: tuple[str, ...], markers: tuple[str, ...]) -> bool:
    lowered = tuple(fragment.lower() for fragment in fragments if fragment)
    return any(marker in fragment for fragment in lowered for marker in markers)


def _normalize_text_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, dict):
        values: list[str] = []
        for nested in value.values():
            values.extend(_normalize_text_list(nested))
        return values
    if isinstance(value, (list, tuple, set)):
        values: list[str] = []
        for nested in value:
            values.extend(_normalize_text_list(nested))
        return values
    text = str(value).strip()
    return [text] if text else []


def _chatplayground_roles(value: object) -> list[str]:
    roles = [entry.strip().lower() for entry in _normalize_text_list(value) if entry.strip()]
    if roles:
        return roles
    return ["factuality", "adversarial", "completeness", "risk"]


def _normalize_chatplayground_audit_payload(payload: dict[str, object] | None) -> tuple[str, str, list[str], list[str], list[str], list[str], dict[str, object]]:
    root = dict(payload or {})
    body = root.get("data") if isinstance(root.get("data"), dict) else root
    if not isinstance(body, dict):
        body = {}
    normalized = dict(body)
    consensus = str(
        normalized.get("consensus")
        or normalized.get("recommendation")
        or normalized.get("summary")
        or ""
    ).strip()
    recommendation = str(normalized.get("recommendation") or consensus or "").strip()
    disagreements = [entry for entry in _normalize_text_list(normalized.get("disagreements")) if entry]
    risks = [entry for entry in _normalize_text_list(normalized.get("risks")) if entry]
    model_deltas = [
        entry
        for entry in _normalize_text_list(normalized.get("model_deltas") or normalized.get("model_delta"))
        if entry
    ]
    instruction_trace = [entry for entry in _normalize_text_list(normalized.get("instruction_trace")) if entry]
    roles = _chatplayground_roles(normalized.get("roles"))
    return (
        consensus,
        recommendation,
        roles,
        disagreements,
        risks,
        model_deltas,
        {
            "consensus": consensus,
            "recommendation": recommendation,
            "disagreements": disagreements,
            "risks": risks,
            "model_deltas": model_deltas,
            "instruction_trace": instruction_trace,
            "roles": roles,
            "audit_scope": str(normalized.get("audit_scope") or "jury").strip() or "jury",
            "requested_models": _normalize_text_list(normalized.get("requested_models")),
            "requested_at": str(normalized.get("requested_at") or now_utc_iso()).strip() or now_utc_iso(),
            "raw_response": root,
            "parsed_at": now_utc_iso(),
        },
    )


def _strip_code_fences(text: object) -> str:
    raw = str(text or "").strip()
    if not raw.startswith("```"):
        return raw
    lines = raw.splitlines()
    if lines:
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _jsonish_candidates(text: object) -> tuple[str, ...]:
    raw = str(text or "").strip()
    if not raw:
        return ()
    candidates: list[str] = []

    def _add(candidate: object) -> None:
        normalized = str(candidate or "").strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    _add(_strip_code_fences(raw))
    _add(raw)
    for match in re.findall(r"```(?:json)?\s*(.*?)```", raw, flags=re.IGNORECASE | re.DOTALL):
        _add(match)
        _add(_strip_code_fences(match))
    for opener, closer in (("{", "}"), ("[", "]")):
        start = raw.find(opener)
        end = raw.rfind(closer)
        if start >= 0 and end > start:
            _add(raw[start : end + 1])
    return tuple(candidates)


def _load_jsonish(text: object) -> object | None:
    for candidate in _jsonish_candidates(text):
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


def _unwrap_browseract_output_payload(value: object) -> object | None:
    if value is None:
        return None
    if isinstance(value, dict):
        recognized = {
            "consensus",
            "recommendation",
            "summary",
            "disagreements",
            "risks",
            "model_deltas",
            "roles",
            "requested_models",
            "requested_at",
        }
        if recognized.intersection(value.keys()):
            return dict(value)
        for key in (
            "audit_response",
            "result",
            "output",
            "answer",
            "message",
            "content",
            "text",
            "string",
            "value",
            "generated_prompt",
        ):
            if key not in value:
                continue
            unwrapped = _unwrap_browseract_output_payload(value.get(key))
            if unwrapped is not None:
                return unwrapped
        if len(value) == 1:
            only_value = next(iter(value.values()))
            return _unwrap_browseract_output_payload(only_value)
        return dict(value)
    if isinstance(value, (list, tuple, set)):
        for nested in value:
            unwrapped = _unwrap_browseract_output_payload(nested)
            if unwrapped is not None:
                return unwrapped
        return None
    if isinstance(value, str):
        parsed = _load_jsonish(value)
        if parsed is not None and parsed != value:
            unwrapped = _unwrap_browseract_output_payload(parsed)
            if unwrapped is not None:
                return unwrapped
        text = value.strip()
        return text or None
    text = str(value).strip()
    return text or None


def _chatplayground_workflow_max_prompt_chars() -> int:
    raw = (
        str(os.getenv("BROWSERACT_CHATPLAYGROUND_WORKFLOW_MAX_PROMPT_CHARS") or "").strip()
        or str(os.getenv("EA_CHATPLAYGROUND_AUDIT_MAX_PROMPT_CHARS") or "").strip()
        or "16000"
    )
    try:
        return max(2000, min(120000, int(raw)))
    except Exception:
        return 16000


def _truncate_chatplayground_workflow_text(text: object, *, limit: int) -> str:
    value = str(text or "")
    if limit <= 0 or len(value) <= limit:
        return value
    if limit <= 96:
        return value[:limit]
    spacer = "\n\n[... omitted for ChatPlayground workflow transport ...]\n\n"
    remaining = limit - len(spacer)
    if remaining <= 32:
        return value[:limit]
    head = remaining // 2
    tail = remaining - head
    return f"{value[:head]}{spacer}{value[-tail:]}".strip()


def _render_chatplayground_workflow_prompt(
    *,
    prompt: str,
    roles: list[str],
    audit_scope: str,
    requested_models: list[str],
) -> str:
    role_list = [str(role).strip() for role in roles if str(role).strip()]
    if not role_list:
        role_list = ["factuality", "adversarial", "completeness", "risk"]
    model_list = [str(model).strip() for model in requested_models if str(model).strip()]
    scope_label = "review_light" if str(audit_scope or "").strip().lower() == "review_light" else "jury"
    material = str(prompt or "").strip()
    if not material:
        return ""
    limit = _chatplayground_workflow_max_prompt_chars()
    base_lines = [
        "You are the jury/audit reviewer for an external automation system.",
        f"Audit scope: {scope_label}",
        f"Review roles: {', '.join(role_list)}",
    ]
    if model_list:
        base_lines.append(f"Requested comparison models: {', '.join(model_list)}")
    base_lines.extend(
        [
            "Review the material and return exactly one JSON object with no markdown fences and no prose outside the JSON.",
            'Use this schema: {{"consensus":"pass|fail|needs_revision|unavailable","recommendation":"short verdict","disagreements":["..."],"risks":["..."],"model_deltas":["..."]}}',
            "Rules:",
            "- consensus must be one of pass, fail, needs_revision, or unavailable",
            "- recommendation must be a short actionable verdict",
            "- disagreements, risks, and model_deltas must be arrays of short strings",
            "- if the material is too incomplete to judge, use needs_revision or unavailable and explain why",
            "",
            "Material to review:",
            "<material>",
            "{material}",
            "</material>",
        ]
    )
    template = "\n".join(base_lines)
    wrapped = template.format(material=material)
    if len(wrapped) <= limit:
        return wrapped
    available = limit - len(template.format(material=""))
    if available <= 512:
        available = max(512, limit // 2)
    compact_material = _truncate_chatplayground_workflow_text(material, limit=available)
    rendered = template.format(material=compact_material)
    if len(rendered) <= limit:
        return rendered
    return _truncate_chatplayground_workflow_text(rendered, limit=limit)


class BrowserActToolAdapter:
    def __init__(self, *, connector_dispatch: ConnectorDispatchToolAdapter) -> None:
        self._connector_dispatch = connector_dispatch
        self._chatplayground_audit = None
        self._gemini_web_generate = None
        self._onemin_billing_usage = None
        self._onemin_member_reconciliation = None

    @staticmethod
    def _looks_like_cloudflare_challenge(payload: dict[str, object]) -> bool:
        return _has_marker(
            _collect_text_fragments(payload),
            (
                "cloudflare",
                "just a moment",
                "checking your browser",
                "attention required",
                "verify you are human",
                "prove you are human",
                "human verification",
                "captcha",
                "security check",
                "browser integrity check",
            ),
        )

    @staticmethod
    def _looks_like_turnstile(payload: dict[str, object]) -> bool:
        return _has_marker(
            _collect_text_fragments(payload),
            (
                "turnstile",
                "cf-turnstile",
                "challenge-platform",
                "cf_challenge",
            ),
        )

    @staticmethod
    def _looks_like_chatgpt_human_verification(payload: dict[str, object]) -> bool:
        fragments = _collect_text_fragments(payload)
        has_product = _has_marker(fragments, ("chatgpt", "openai"))
        has_challenge = _has_marker(
            fragments,
            (
                "verify you are human",
                "prove you are human",
                "human verification",
                "captcha",
            ),
        )
        return has_product and has_challenge

    @staticmethod
    def _looks_like_ui_session_expired(payload: dict[str, object]) -> bool:
        return _has_marker(
            _collect_text_fragments(payload),
            (
                "session expired",
                "please sign in",
                "sign in to continue",
                "log in to continue",
                "login required",
                "reauthenticate",
            ),
        )

    @classmethod
    def _raise_for_ui_lane_failure(cls, *, payload: dict[str, object], backend: str) -> None:
        explicit = str(
            payload.get("ui_failure_code")
            or payload.get("failure_code")
            or payload.get("error_code")
            or payload.get("challenge_state")
            or ""
        ).strip().lower()
        if explicit in {"challenge_required", "challenge_loop", "session_expired", "lane_unavailable", "timeout"}:
            raise ToolExecutionError(f"ui_lane_failure:{backend}:{explicit}")
        if cls._looks_like_ui_session_expired(payload):
            raise ToolExecutionError(f"ui_lane_failure:{backend}:session_expired")
        if (
            cls._looks_like_turnstile(payload)
            or cls._looks_like_cloudflare_challenge(payload)
            or cls._looks_like_chatgpt_human_verification(payload)
        ):
            raise ToolExecutionError(f"ui_lane_failure:{backend}:challenge_required")

    @staticmethod
    def _normalize_lookup_key(value: object) -> str:
        return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")

    @classmethod
    def _browseract_scalar_map(cls, value: object, *, limit: int = 512) -> dict[str, str]:
        pairs: dict[str, str] = {}

        def _visit(node: object) -> None:
            if len(pairs) >= limit or node is None:
                return
            if isinstance(node, dict):
                for raw_key, nested in node.items():
                    if len(pairs) >= limit:
                        break
                    key = cls._normalize_lookup_key(raw_key)
                    if isinstance(nested, (str, int, float, bool)):
                        text = str(nested).strip()
                        if key and text and key not in pairs:
                            pairs[key] = text
                    _visit(nested)
                return
            if isinstance(node, (list, tuple, set)):
                for nested in node:
                    if len(pairs) >= limit:
                        break
                    _visit(nested)

        _visit(value)
        return pairs

    @classmethod
    def _browseract_text_candidates(cls, value: object, *, limit: int = 32) -> list[str]:
        candidates: list[str] = []

        def _add(text: object) -> None:
            normalized = str(text or "").strip()
            if normalized and normalized not in candidates:
                candidates.append(normalized)

        def _visit(node: object) -> None:
            if len(candidates) >= limit or node is None:
                return
            if isinstance(node, dict):
                for raw_key, nested in node.items():
                    if len(candidates) >= limit:
                        break
                    key = cls._normalize_lookup_key(raw_key)
                    if key in {
                        "raw_text",
                        "text",
                        "normalized_text",
                        "page_body",
                        "billing_usage_page",
                        "daily_bonus_page",
                        "members_page",
                        "output_text",
                        "content",
                        "message",
                        "result",
                        "summary",
                    }:
                        _add(_extract_textish(nested))
                    _visit(nested)
                return
            if isinstance(node, (list, tuple, set)):
                for nested in node:
                    if len(candidates) >= limit:
                        break
                    _visit(nested)
                return
            if isinstance(node, str):
                _add(node)

        _visit(value)
        if not candidates:
            _add(_extract_textish(value))
        return candidates[:limit]

    @classmethod
    def _first_scalar_for_aliases(cls, scalar_map: dict[str, str], *aliases: str) -> str:
        for alias in aliases:
            value = scalar_map.get(cls._normalize_lookup_key(alias))
            if value:
                return value
        return ""

    @staticmethod
    def _parse_number(value: object) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value or "").strip()
        if not text:
            return None
        match = re.search(r"-?\d[\d,]*(?:\.\d+)?", text.replace(" ", ""))
        if match is None:
            return None
        try:
            return float(match.group(0).replace(",", ""))
        except Exception:
            return None

    @staticmethod
    def _parse_credit_int(value: object) -> int | None:
        parsed = BrowserActToolAdapter._parse_number(value)
        if parsed is None:
            return None
        return max(0, int(round(parsed)))

    @staticmethod
    def _parse_percent(value: object) -> float | None:
        parsed = BrowserActToolAdapter._parse_number(value)
        if parsed is None:
            return None
        return max(0.0, min(100.0, round(float(parsed), 2)))

    @staticmethod
    def _parse_bool_text(value: object) -> bool | None:
        text = str(value or "").strip().lower()
        if not text:
            return None
        if any(marker in text for marker in ("rollover enabled", "rollover: yes", "lifetime credits roll over", "roll over")):
            return True
        if any(marker in text for marker in ("rollover disabled", "rollover: no", "no rollover")):
            return False
        if text in {"true", "yes", "enabled", "on"}:
            return True
        if text in {"false", "no", "disabled", "off"}:
            return False
        return None

    @staticmethod
    def _parse_datetime_text(value: object) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        normalized = text.replace("UTC", "+00:00").replace("Z", "+00:00")
        candidates = [normalized]
        if normalized.endswith("+00:00") and "T" not in normalized and " " in normalized:
            candidates.append(normalized.replace(" ", "T", 1))
        for candidate in candidates:
            try:
                parsed = datetime.fromisoformat(candidate)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            except Exception:
                continue
        for fmt in (
            "%Y-%m-%d",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%b %d, %Y",
            "%B %d, %Y",
            "%b %d, %Y %I:%M %p",
            "%B %d, %Y %I:%M %p",
            "%b %d %Y",
            "%B %d %Y",
        ):
            try:
                parsed = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
                return parsed.isoformat().replace("+00:00", "Z")
            except Exception:
                continue
        return text

    @classmethod
    def _find_label_value(cls, raw_text: str, labels: tuple[str, ...]) -> str:
        text = str(raw_text or "")
        if not text:
            return ""
        for label in labels:
            pattern = re.compile(
                rf"{re.escape(label)}\s*(?:[:\-]|is)?\s*([^\n\r|]+)",
                flags=re.IGNORECASE,
            )
            match = pattern.search(text)
            if match is not None:
                return str(match.group(1) or "").strip()
        return ""

    @classmethod
    def _normalize_onemin_billing_payload(
        cls,
        *,
        response: dict[str, object],
        source_url: str,
        account_label: str,
    ) -> dict[str, object]:
        scalar_map = cls._browseract_scalar_map(response)
        raw_text = "\n\n".join(cls._browseract_text_candidates(response)).strip()
        label_map = dict(scalar_map)

        remaining_credits = cls._parse_credit_int(
            cls._first_scalar_for_aliases(
                scalar_map,
                "remaining_credits",
                "free_credits",
                "credits_left",
                "available_credits",
                "credits_available",
            )
            or cls._find_label_value(
                raw_text,
                (
                    "Remaining credits",
                    "Credits left",
                    "Available credits",
                    "Credits available",
                ),
            )
        )
        max_credits = cls._parse_credit_int(
            cls._first_scalar_for_aliases(
                scalar_map,
                "max_credits",
                "total_credits",
                "credits_total",
                "plan_credits",
                "monthly_credits",
                "included_credits",
            )
            or cls._find_label_value(
                raw_text,
                (
                    "Total credits",
                    "Max credits",
                    "Monthly credits",
                    "Included credits",
                    "Plan credits",
                ),
            )
        )
        used_percent = cls._parse_percent(
            cls._first_scalar_for_aliases(scalar_map, "used_percent", "usage_percent", "percent_used")
            or cls._find_label_value(raw_text, ("Used", "Usage", "Used percent", "Usage percent"))
        )
        next_topup_at = cls._parse_datetime_text(
            cls._first_scalar_for_aliases(
                scalar_map,
                "next_topup_at",
                "next_billing",
                "next_renewal",
                "renews_on",
                "renewal_date",
            )
            or cls._find_label_value(raw_text, ("Next top-up", "Next billing", "Next renewal", "Renews on"))
        )
        cycle_start_at = cls._parse_datetime_text(
            cls._first_scalar_for_aliases(scalar_map, "cycle_start_at", "period_start", "cycle_start")
            or cls._find_label_value(raw_text, ("Cycle start", "Period start"))
        )
        cycle_end_at = cls._parse_datetime_text(
            cls._first_scalar_for_aliases(scalar_map, "cycle_end_at", "period_end", "cycle_end")
            or cls._find_label_value(raw_text, ("Cycle end", "Period end"))
        )
        topup_amount = cls._parse_credit_int(
            cls._first_scalar_for_aliases(scalar_map, "topup_amount", "monthly_allocation", "included_credits")
            or cls._find_label_value(raw_text, ("Top-up amount", "Monthly allocation", "Included credits", "Monthly credits"))
        )
        rollover_enabled = cls._parse_bool_text(
            cls._first_scalar_for_aliases(scalar_map, "rollover_enabled", "rollover")
            or raw_text
        )
        basis = "actual_billing_usage_page" if remaining_credits is not None else "page_seen_but_unparsed"
        return {
            "provider_backend": "onemin_billing_usage_page",
            "account_label": account_label,
            "remaining_credits": remaining_credits,
            "max_credits": max_credits,
            "used_percent": used_percent,
            "next_topup_at": next_topup_at,
            "cycle_start_at": cycle_start_at,
            "cycle_end_at": cycle_end_at,
            "topup_amount": topup_amount,
            "rollover_enabled": rollover_enabled,
            "source_url": source_url,
            "basis": basis,
            "structured_output_json": {
                "raw_text": raw_text,
                "label_map": label_map,
            },
        }

    @classmethod
    def _extract_member_rows(cls, response: dict[str, object]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []

        def _visit(node: object) -> None:
            if isinstance(node, dict):
                lowered = {cls._normalize_lookup_key(key): value for key, value in node.items()}
                if any(key in lowered for key in ("email", "member_email", "owner_email", "account_email")):
                    rows.append(
                        {
                            "name": str(
                                lowered.get("name")
                                or lowered.get("member_name")
                                or lowered.get("full_name")
                                or ""
                            ).strip(),
                            "email": str(
                                lowered.get("email")
                                or lowered.get("member_email")
                                or lowered.get("owner_email")
                                or lowered.get("account_email")
                                or ""
                            ).strip(),
                            "status": str(lowered.get("status") or lowered.get("member_status") or "").strip(),
                            "role": str(lowered.get("role") or lowered.get("member_role") or "").strip(),
                            "credit_limit": cls._parse_credit_int(
                                lowered.get("credit_limit")
                                or lowered.get("member_credit_limit")
                                or lowered.get("limit")
                            ),
                        }
                    )
                for nested in node.values():
                    _visit(nested)
            elif isinstance(node, (list, tuple, set)):
                for nested in node:
                    _visit(nested)

        _visit(response)
        if rows:
            unique: list[dict[str, object]] = []
            seen: set[str] = set()
            for row in rows:
                email = str(row.get("email") or "").strip().lower()
                if not email or email in seen:
                    continue
                seen.add(email)
                unique.append(row)
            return unique

        raw_text = "\n".join(cls._browseract_text_candidates(response)).strip()
        if not raw_text:
            return []
        email_re = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", flags=re.IGNORECASE)
        parsed_rows: list[dict[str, object]] = []
        for line in raw_text.splitlines():
            email_match = email_re.search(line)
            if email_match is None:
                continue
            lowered = line.lower()
            status = ""
            for candidate in ("active", "deactivated", "inactive", "pending"):
                if candidate in lowered:
                    status = candidate
                    break
            parsed_rows.append(
                {
                    "name": line[: email_match.start()].strip(" -|:"),
                    "email": email_match.group(0).strip(),
                    "status": status,
                    "role": "owner" if "owner" in lowered else ("member" if "member" in lowered else ""),
                    "credit_limit": cls._parse_credit_int(line if "limit" in lowered else None),
                }
            )
        return parsed_rows

    @classmethod
    def _normalize_onemin_member_reconciliation_payload(
        cls,
        *,
        response: dict[str, object],
        source_url: str,
        account_label: str,
    ) -> dict[str, object]:
        from app.services import responses_upstream as upstream

        members = cls._extract_member_rows(response)
        owner_entries = list(upstream._onemin_owner_entries())
        owner_emails = {
            str(row.get("owner_email") or "").strip().lower()
            for row in owner_entries
            if str(row.get("owner_email") or "").strip()
        }
        if not owner_emails:
            raw_owner_payload = upstream._load_onemin_owner_ledger_payload()
            candidate_rows = []
            if isinstance(raw_owner_payload, dict):
                if isinstance(raw_owner_payload.get("slots"), list):
                    candidate_rows = raw_owner_payload.get("slots") or []
                elif isinstance(raw_owner_payload.get("owners"), list):
                    candidate_rows = raw_owner_payload.get("owners") or []
            elif isinstance(raw_owner_payload, list):
                candidate_rows = raw_owner_payload
            owner_emails = {
                str((row or {}).get("owner_email") or (row or {}).get("email") or "").strip().lower()
                for row in candidate_rows
                if isinstance(row, dict) and str((row or {}).get("owner_email") or (row or {}).get("email") or "").strip()
            }
        member_emails = {str(row.get("email") or "").strip().lower() for row in members if str(row.get("email") or "").strip()}
        missing_owner_emails = sorted(email for email in owner_emails if email not in member_emails)
        owner_mismatches = [
            row for row in members
            if str(row.get("email") or "").strip().lower() not in owner_emails
        ]
        basis = "actual_members_page" if members else "page_seen_but_unparsed"
        return {
            "provider_backend": "onemin_members_page",
            "account_label": account_label,
            "member_count": len(members),
            "matched_owner_slots": len(member_emails.intersection(owner_emails)),
            "missing_owner_emails": missing_owner_emails,
            "owner_mismatches": owner_mismatches,
            "members_json": members,
            "source_url": source_url,
            "basis": basis,
            "structured_output_json": {
                "raw_text": "\n\n".join(cls._browseract_text_candidates(response)).strip(),
                "label_map": cls._browseract_scalar_map(response),
            },
        }

    def execute_extract(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        service_name = str(payload.get("service_name") or "").strip()
        principal_id, binding = self._resolve_browseract_binding(
            request=request,
            payload=payload,
            required_input_error="connector_binding_required:browseract.extract_account_facts",
            required_scopes=(service_name,) if service_name else None,
        )
        if not service_name:
            raise ToolExecutionError("service_name_required:browseract.extract_account_facts")
        record = self._extract_service_record(
            binding_auth_metadata_json=dict(binding.auth_metadata_json or {}),
            payload=payload,
            service_name=service_name,
            requested_fields=self._requested_fields(payload),
            allow_missing=False,
        )
        action_kind = str(request.action_kind or "account.extract") or "account.extract"
        structured_output_json = dict(record["structured_output_json"])
        structured_output_json.update(
            {"binding_id": binding.binding_id, "connector_name": binding.connector_name, "external_account_ref": binding.external_account_ref}
        )
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"browseract:{binding.binding_id}:{service_name.lower().replace(' ', '_')}",
            output_json={
                "binding_id": binding.binding_id,
                "connector_name": binding.connector_name,
                "external_account_ref": binding.external_account_ref,
                "service_name": record["service_name"],
                "facts_json": record["facts_json"],
                "requested_fields": record["requested_fields"],
                "missing_fields": record["missing_fields"],
                "account_email": record["account_email"],
                "plan_tier": record["plan_tier"],
                "discovery_status": record["discovery_status"],
                "verification_source": record["verification_source"],
                "last_verified_at": record["last_verified_at"],
                "instructions": record["instructions"],
                "account_hints_json": record["account_hints_json"],
                "requested_run_url": record["requested_run_url"],
                "live_discovery_error": record["live_discovery_error"],
                "normalized_text": record["normalized_text"],
                "preview_text": record["preview_text"],
                "mime_type": record["mime_type"],
                "structured_output_json": structured_output_json,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "binding_id": binding.binding_id,
                "connector_name": binding.connector_name,
                "external_account_ref": binding.external_account_ref,
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "principal_id": principal_id,
                "service_name": record["service_name"],
                "requested_fields": record["requested_fields"],
                "missing_fields": record["missing_fields"],
                "discovery_status": record["discovery_status"],
                "verification_source": record["verification_source"],
                "requested_run_url": record["requested_run_url"],
                "live_discovery_error": record["live_discovery_error"],
                "tool_version": definition.version,
            },
        )

    def execute_inventory(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        service_names = self._requested_service_names(payload)
        principal_id, binding = self._resolve_browseract_binding(
            request=request,
            payload=payload,
            required_input_error="connector_binding_required:browseract.extract_account_inventory",
            required_scopes=service_names,
        )
        if not service_names:
            service_names = self._configured_service_names(
                binding_auth_metadata_json=dict(binding.auth_metadata_json or {}),
                binding_scope_json=dict(binding.scope_json or {}),
            )
        if not service_names:
            raise ToolExecutionError("service_names_required:browseract.extract_account_inventory")
        requested_fields = self._requested_fields(payload)
        services_json = [
            self._extract_service_record(
                binding_auth_metadata_json=dict(binding.auth_metadata_json or {}),
                payload=payload,
                service_name=service_name,
                requested_fields=requested_fields,
                allow_missing=True,
            )
            for service_name in service_names
        ]
        missing_services = [str(row["service_name"]) for row in services_json if str(row["discovery_status"]) == "missing"]
        action_kind = str(request.action_kind or "account.extract_inventory") or "account.extract_inventory"
        normalized_text = self._inventory_summary_text(services_json)
        structured_output_json = {
            "service_names": list(service_names),
            "services_json": services_json,
            "missing_services": missing_services,
            "binding_id": binding.binding_id,
            "connector_name": binding.connector_name,
            "external_account_ref": binding.external_account_ref,
            "instructions": str(payload.get("instructions") or "").strip(),
            "account_hints_json": dict(payload.get("account_hints_json") or {}),
            "requested_run_url": str(payload.get("run_url") or "").strip(),
        }
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"browseract:{binding.binding_id}:inventory",
            output_json={
                "binding_id": binding.binding_id,
                "connector_name": binding.connector_name,
                "external_account_ref": binding.external_account_ref,
                "service_names": list(service_names),
                "services_json": services_json,
                "missing_services": missing_services,
                "instructions": structured_output_json["instructions"],
                "account_hints_json": structured_output_json["account_hints_json"],
                "requested_run_url": structured_output_json["requested_run_url"],
                "normalized_text": normalized_text,
                "preview_text": artifact_preview_text(normalized_text),
                "mime_type": "text/plain",
                "structured_output_json": structured_output_json,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "binding_id": binding.binding_id,
                "connector_name": binding.connector_name,
                "external_account_ref": binding.external_account_ref,
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "principal_id": principal_id,
                "service_names": list(service_names),
                "missing_services": missing_services,
                "requested_run_url": structured_output_json["requested_run_url"],
                "tool_version": definition.version,
            },
        )

    def execute_onemin_billing_usage(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        from app.services import responses_upstream as upstream

        payload = dict(request.payload_json or {})
        principal_id, binding = self._resolve_browseract_binding(
            request=request,
            payload=payload,
            required_input_error="connector_binding_required:browseract.onemin_billing_usage",
            required_scopes=None,
        )
        binding_metadata = dict(binding.auth_metadata_json or {})
        run_url = str(
            payload.get("run_url")
            or binding_metadata.get("onemin_billing_usage_run_url")
            or binding_metadata.get("browseract_onemin_billing_usage_run_url")
            or binding_metadata.get("run_url")
            or ""
        ).strip()
        workflow_id = str(
            payload.get("workflow_id")
            or binding_metadata.get("onemin_billing_usage_workflow_id")
            or binding_metadata.get("browseract_onemin_billing_usage_workflow_id")
            or ""
        ).strip()
        if not run_url and not workflow_id:
            raise ToolExecutionError("run_url_or_workflow_id_required:browseract.onemin_billing_usage")
        page_url = str(payload.get("page_url") or "https://app.1min.ai/billing-usage").strip() or "https://app.1min.ai/billing-usage"
        account_label = str(payload.get("account_label") or binding.external_account_ref or binding.binding_id).strip() or binding.binding_id
        try:
            timeout_seconds = max(30, min(1800, int(payload.get("timeout_seconds") or 180)))
        except Exception:
            timeout_seconds = 180

        callback = getattr(self, "_onemin_billing_usage", None)
        if callback is not None:
            maybe = callback(run_url=run_url, request_payload=dict(payload), page_url=page_url, account_label=account_label)
            if isinstance(maybe, dict):
                response = maybe
            elif workflow_id and not run_url:
                response = self._run_onemin_workflow_task(
                    workflow_id=workflow_id,
                    account_label=account_label,
                    timeout_seconds=timeout_seconds,
                )
            else:
                response = self._post_browseract_json(
                    run_url=run_url,
                    request_payload={
                        "page_url": page_url,
                        "account_label": account_label,
                        "capture_raw_text": bool(payload.get("capture_raw_text", True)),
                        "principal_id": principal_id,
                        "binding_id": binding.binding_id,
                        "external_account_ref": binding.external_account_ref,
                    },
                    timeout_seconds=timeout_seconds,
                )
        else:
            if workflow_id and not run_url:
                response = self._run_onemin_workflow_task(
                    workflow_id=workflow_id,
                    account_label=account_label,
                    timeout_seconds=timeout_seconds,
                )
            else:
                response = self._post_browseract_json(
                    run_url=run_url,
                    request_payload={
                        "page_url": page_url,
                        "account_label": account_label,
                        "capture_raw_text": bool(payload.get("capture_raw_text", True)),
                        "principal_id": principal_id,
                        "binding_id": binding.binding_id,
                        "external_account_ref": binding.external_account_ref,
                    },
                    timeout_seconds=timeout_seconds,
                )
        self._raise_for_ui_lane_failure(payload=response, backend="onemin_billing_usage")
        normalized = self._normalize_onemin_billing_payload(
            response=response,
            source_url=page_url,
            account_label=account_label,
        )
        snapshot = upstream.record_onemin_billing_snapshot(
            account_name=account_label,
            snapshot_json=normalized,
            source="browseract.onemin_billing_usage",
        )
        action_kind = str(request.action_kind or "billing.inspect") or "billing.inspect"
        normalized_text = json.dumps(normalized, ensure_ascii=True, separators=(",", ":"))
        structured_output_json = dict(normalized.get("structured_output_json") or {})
        structured_output_json["persisted_snapshot"] = snapshot
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"browseract:{binding.binding_id}:onemin_billing_usage:{account_label}",
            output_json={
                "binding_id": binding.binding_id,
                "connector_name": binding.connector_name,
                "external_account_ref": binding.external_account_ref,
                "account_label": account_label,
                "provider_backend": normalized.get("provider_backend"),
                "remaining_credits": normalized.get("remaining_credits"),
                "max_credits": normalized.get("max_credits"),
                "used_percent": normalized.get("used_percent"),
                "next_topup_at": normalized.get("next_topup_at"),
                "cycle_start_at": normalized.get("cycle_start_at"),
                "cycle_end_at": normalized.get("cycle_end_at"),
                "topup_amount": normalized.get("topup_amount"),
                "rollover_enabled": normalized.get("rollover_enabled"),
                "source_url": normalized.get("source_url"),
                "basis": normalized.get("basis"),
                "normalized_text": normalized_text,
                "preview_text": artifact_preview_text(normalized_text),
                "mime_type": "application/json",
                "structured_output_json": structured_output_json,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "binding_id": binding.binding_id,
                "connector_name": binding.connector_name,
                "external_account_ref": binding.external_account_ref,
                "principal_id": principal_id,
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "tool_version": definition.version,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
                "requested_url": run_url or f"browseract://workflow/{workflow_id}",
                "source_url": page_url,
                "account_label": account_label,
                "basis": normalized.get("basis"),
            },
        )

    def execute_onemin_member_reconciliation(
        self,
        request: ToolInvocationRequest,
        definition: ToolDefinition,
    ) -> ToolInvocationResult:
        from app.services import responses_upstream as upstream

        payload = dict(request.payload_json or {})
        principal_id, binding = self._resolve_browseract_binding(
            request=request,
            payload=payload,
            required_input_error="connector_binding_required:browseract.onemin_member_reconciliation",
            required_scopes=None,
        )
        binding_metadata = dict(binding.auth_metadata_json or {})
        run_url = str(
            payload.get("run_url")
            or binding_metadata.get("onemin_members_run_url")
            or binding_metadata.get("browseract_onemin_members_run_url")
            or binding_metadata.get("run_url")
            or ""
        ).strip()
        workflow_id = str(
            payload.get("workflow_id")
            or binding_metadata.get("onemin_members_workflow_id")
            or binding_metadata.get("browseract_onemin_members_workflow_id")
            or ""
        ).strip()
        if not run_url and not workflow_id:
            raise ToolExecutionError("run_url_or_workflow_id_required:browseract.onemin_member_reconciliation")
        page_url = str(payload.get("page_url") or "https://app.1min.ai/members").strip() or "https://app.1min.ai/members"
        account_label = str(payload.get("account_label") or binding.external_account_ref or binding.binding_id).strip() or binding.binding_id
        try:
            timeout_seconds = max(30, min(1800, int(payload.get("timeout_seconds") or 180)))
        except Exception:
            timeout_seconds = 180

        callback = getattr(self, "_onemin_member_reconciliation", None)
        if callback is not None:
            maybe = callback(run_url=run_url, request_payload=dict(payload), page_url=page_url, account_label=account_label)
            if isinstance(maybe, dict):
                response = maybe
            elif workflow_id and not run_url:
                response = self._run_onemin_workflow_task(
                    workflow_id=workflow_id,
                    account_label=account_label,
                    timeout_seconds=timeout_seconds,
                )
            else:
                response = self._post_browseract_json(
                    run_url=run_url,
                    request_payload={
                        "page_url": page_url,
                        "account_label": account_label,
                        "capture_raw_text": bool(payload.get("capture_raw_text", True)),
                        "principal_id": principal_id,
                        "binding_id": binding.binding_id,
                        "external_account_ref": binding.external_account_ref,
                    },
                    timeout_seconds=timeout_seconds,
                )
        else:
            if workflow_id and not run_url:
                response = self._run_onemin_workflow_task(
                    workflow_id=workflow_id,
                    account_label=account_label,
                    timeout_seconds=timeout_seconds,
                )
            else:
                response = self._post_browseract_json(
                    run_url=run_url,
                    request_payload={
                        "page_url": page_url,
                        "account_label": account_label,
                        "capture_raw_text": bool(payload.get("capture_raw_text", True)),
                        "principal_id": principal_id,
                        "binding_id": binding.binding_id,
                        "external_account_ref": binding.external_account_ref,
                    },
                    timeout_seconds=timeout_seconds,
                )
        self._raise_for_ui_lane_failure(payload=response, backend="onemin_members")
        normalized = self._normalize_onemin_member_reconciliation_payload(
            response=response,
            source_url=page_url,
            account_label=account_label,
        )
        snapshot = upstream.record_onemin_member_reconciliation_snapshot(
            account_name=account_label,
            snapshot_json=normalized,
            source="browseract.onemin_member_reconciliation",
        )
        action_kind = str(request.action_kind or "billing.reconcile_members") or "billing.reconcile_members"
        normalized_text = json.dumps(normalized, ensure_ascii=True, separators=(",", ":"))
        structured_output_json = dict(normalized.get("structured_output_json") or {})
        structured_output_json["persisted_snapshot"] = snapshot
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"browseract:{binding.binding_id}:onemin_member_reconciliation:{account_label}",
            output_json={
                "binding_id": binding.binding_id,
                "connector_name": binding.connector_name,
                "external_account_ref": binding.external_account_ref,
                "account_label": account_label,
                "provider_backend": normalized.get("provider_backend"),
                "member_count": normalized.get("member_count"),
                "matched_owner_slots": normalized.get("matched_owner_slots"),
                "missing_owner_emails": list(normalized.get("missing_owner_emails") or []),
                "owner_mismatches": list(normalized.get("owner_mismatches") or []),
                "members_json": list(normalized.get("members_json") or []),
                "source_url": normalized.get("source_url"),
                "basis": normalized.get("basis"),
                "normalized_text": normalized_text,
                "preview_text": artifact_preview_text(normalized_text),
                "mime_type": "application/json",
                "structured_output_json": structured_output_json,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "binding_id": binding.binding_id,
                "connector_name": binding.connector_name,
                "external_account_ref": binding.external_account_ref,
                "principal_id": principal_id,
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "tool_version": definition.version,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
                "requested_url": run_url or f"browseract://workflow/{workflow_id}",
                "source_url": page_url,
                "account_label": account_label,
                "basis": normalized.get("basis"),
            },
        )

    def execute_build_workflow_spec(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        workflow_name = str(payload.get("workflow_name") or "").strip()
        purpose = str(payload.get("purpose") or "").strip()
        login_url = str(payload.get("login_url") or "").strip()
        tool_url = str(payload.get("tool_url") or "").strip()
        if not workflow_name:
            raise ToolExecutionError("workflow_name_required:browseract.build_workflow_spec")
        if not purpose:
            raise ToolExecutionError("purpose_required:browseract.build_workflow_spec")
        if not login_url:
            raise ToolExecutionError("login_url_required:browseract.build_workflow_spec")
        if not tool_url:
            raise ToolExecutionError("tool_url_required:browseract.build_workflow_spec")
        workflow_kind = str(payload.get("workflow_kind") or "prompt_tool").strip().lower() or "prompt_tool"
        if workflow_kind not in {"prompt_tool", "page_extract"}:
            raise ToolExecutionError(f"workflow_kind_invalid:browseract.build_workflow_spec:{workflow_kind}")
        runtime_input_name = str(payload.get("runtime_input_name") or "").strip()
        prompt_selector = str(payload.get("prompt_selector") or "textarea").strip() or "textarea"
        submit_selector = str(payload.get("submit_selector") or "button").strip() or "button"
        result_selector = str(payload.get("result_selector") or "main, body").strip() or "main, body"
        wait_selector = str(payload.get("wait_selector") or result_selector).strip() or result_selector
        title_selector = str(payload.get("title_selector") or "").strip()
        result_field_name = str(payload.get("result_field_name") or ("page_body" if workflow_kind == "page_extract" else "result_text")).strip() or ("page_body" if workflow_kind == "page_extract" else "result_text")
        dismiss_selectors = self._normalize_string_list(payload.get("dismiss_selectors"))
        output_dir = str(payload.get("output_dir") or "/docker/fleet/state/browseract_bootstrap").strip() or "/docker/fleet/state/browseract_bootstrap"
        spec = self._build_workflow_spec(
            workflow_name=workflow_name,
            purpose=purpose,
            login_url=login_url,
            tool_url=tool_url,
            workflow_kind=workflow_kind,
            runtime_input_name=runtime_input_name,
            prompt_selector=prompt_selector,
            submit_selector=submit_selector,
            result_selector=result_selector,
            wait_selector=wait_selector,
            title_selector=title_selector,
            dismiss_selectors=dismiss_selectors,
            result_field_name=result_field_name,
            output_dir=output_dir,
        )
        slug = str(((spec.get("meta") or {}).get("slug")) or self._slugify(workflow_name))
        action_kind = str(request.action_kind or "workflow.spec_build") or "workflow.spec_build"
        normalized_text = "\n".join(
            [
                f"Workflow: {workflow_name}",
                f"Purpose: {purpose}",
                f"Kind: {workflow_kind}",
                f"Tool URL: {tool_url}",
                f"Runtime input: {runtime_input_name or '<none>'}",
                f"Prompt selector: {prompt_selector}",
                f"Submit selector: {submit_selector}",
                f"Result selector: {result_selector}",
                f"Wait selector: {wait_selector}",
                f"Title selector: {title_selector or '<none>'}",
                f"Dismiss selectors: {len(dismiss_selectors)}",
                f"Node count: {len(spec.get('nodes') or [])}",
                f"Edge count: {len(spec.get('edges') or [])}",
            ]
        )
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"browseract:workflow-spec:{slug}",
            output_json={
                "workflow_name": workflow_name,
                "workflow_slug": slug,
                "normalized_text": normalized_text,
                "preview_text": artifact_preview_text(normalized_text),
                "mime_type": "application/json",
                "structured_output_json": spec,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "workflow_name": workflow_name,
                "workflow_slug": slug,
                "tool_version": definition.version,
            },
        )

    def execute_repair_workflow_spec(self, request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        workflow_name = str(payload.get("workflow_name") or "").strip()
        purpose = str(payload.get("purpose") or "").strip()
        login_url = str(payload.get("login_url") or "public").strip() or "public"
        tool_url = str(payload.get("tool_url") or "").strip()
        failure_summary = str(payload.get("failure_summary") or payload.get("diagnosis") or "").strip()
        if not workflow_name:
            raise ToolExecutionError("workflow_name_required:browseract.repair_workflow_spec")
        if not purpose:
            raise ToolExecutionError("purpose_required:browseract.repair_workflow_spec")
        if not tool_url:
            raise ToolExecutionError("tool_url_required:browseract.repair_workflow_spec")
        if not failure_summary:
            raise ToolExecutionError("failure_summary_required:browseract.repair_workflow_spec")
        prompt_selector = str(payload.get("prompt_selector") or "textarea").strip() or "textarea"
        submit_selector = str(payload.get("submit_selector") or "button").strip() or "button"
        result_selector = str(payload.get("result_selector") or "main, body").strip() or "main, body"
        workflow_kind = str(payload.get("workflow_kind") or "prompt_tool").strip().lower() or "prompt_tool"
        runtime_input_name = str(payload.get("runtime_input_name") or "prompt").strip() or "prompt"
        wait_selector = str(payload.get("wait_selector") or result_selector).strip() or result_selector
        title_selector = str(payload.get("title_selector") or "").strip()
        result_field_name = str(payload.get("result_field_name") or ("page_body" if workflow_kind == "page_extract" else "result_text")).strip() or ("page_body" if workflow_kind == "page_extract" else "result_text")
        dismiss_selectors = self._normalize_string_list(payload.get("dismiss_selectors"))
        output_dir = str(payload.get("output_dir") or "/docker/fleet/state/browseract_bootstrap").strip() or "/docker/fleet/state/browseract_bootstrap"
        scaffold = self._build_workflow_spec(
            workflow_name=workflow_name,
            purpose=purpose,
            login_url=login_url,
            tool_url=tool_url,
            workflow_kind=workflow_kind,
            runtime_input_name=runtime_input_name,
            prompt_selector=prompt_selector,
            submit_selector=submit_selector,
            result_selector=result_selector,
            wait_selector=wait_selector,
            title_selector=title_selector,
            dismiss_selectors=dismiss_selectors,
            result_field_name=result_field_name,
            output_dir=output_dir,
        )
        failure_goals = self._normalize_string_list(payload.get("failing_step_goals"))
        current_spec = payload.get("current_workflow_spec_json") if isinstance(payload.get("current_workflow_spec_json"), dict) else {}
        repair_prompt = self._build_workflow_repair_prompt(
            workflow_name=workflow_name,
            purpose=purpose,
            login_url=login_url,
            tool_url=tool_url,
            failure_summary=failure_summary,
            failure_goals=failure_goals,
            current_spec=current_spec if isinstance(current_spec, dict) else {},
            scaffold=scaffold,
        )
        envelope, model = self._run_gemini_repair_prompt(repair_prompt)
        packet = self._normalize_workflow_repair_packet(
            envelope,
            workflow_name=workflow_name,
            purpose=purpose,
            scaffold=scaffold,
            failure_summary=failure_summary,
            failure_goals=failure_goals,
        )
        slug = str((((packet.get("workflow_spec") or {}).get("meta") or {}).get("slug")) or self._slugify(workflow_name))
        normalized_text = "\n".join(
            [
                f"Workflow: {workflow_name}",
                f"Failure: {failure_summary}",
                f"Diagnosis: {packet.get('diagnosis', '')}",
                f"Repair strategy: {packet.get('repair_strategy', '')}",
                f"Node count: {len(((packet.get('workflow_spec') or {}).get('nodes') or []))}",
                f"Edge count: {len(((packet.get('workflow_spec') or {}).get('edges') or []))}",
            ]
        )
        action_kind = str(request.action_kind or "workflow.spec_repair") or "workflow.spec_repair"
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"browseract:workflow-repair:{slug}:{uuid.uuid4()}",
            output_json={
                "workflow_name": workflow_name,
                "workflow_slug": slug,
                "normalized_text": normalized_text,
                "preview_text": artifact_preview_text(normalized_text),
                "mime_type": "application/json",
                "structured_output_json": packet,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "workflow_name": workflow_name,
                "workflow_slug": slug,
                "failure_summary": failure_summary,
                "failure_goals": failure_goals,
                "model": model,
                "tool_version": definition.version,
            },
            model_name=model,
            cost_usd=0.0,
        )

    def _resolve_browseract_binding(
        self,
        *,
        request: ToolInvocationRequest,
        payload: dict[str, object],
        required_input_error: str,
        required_scopes: tuple[str, ...] | None,
    ):
        principal_id, binding = self._connector_dispatch.resolve_connector_binding(
            request=request,
            payload=payload,
            required_connector_name="browseract",
            required_input_error=required_input_error,
        )
        requested_scopes = self._connector_dispatch.normalised_scopes(required_scopes or ())
        if requested_scopes:
            configured_scopes = self._connector_dispatch.normalised_scopes(
                self._configured_service_names(
                    binding_auth_metadata_json=dict(binding.auth_metadata_json or {}),
                    binding_scope_json=dict(binding.scope_json or {}),
                )
            )
            if not set(requested_scopes).issubset(set(configured_scopes)):
                raise ToolExecutionError(
                    f"connector_binding_scope_mismatch:{binding.binding_id}:{','.join(requested_scopes)}"
                )
        return principal_id, binding

    def _requested_fields(self, payload: dict[str, object]) -> tuple[str, ...]:
        raw = payload.get("requested_fields")
        if isinstance(raw, (list, tuple)):
            return tuple(str(value or "").strip() for value in raw if str(value or "").strip())
        if isinstance(raw, str) and raw.strip():
            return tuple(value.strip() for value in raw.split(",") if value.strip())
        return ()

    def _requested_service_names(self, payload: dict[str, object]) -> tuple[str, ...]:
        raw = payload.get("service_names")
        values: list[str] = []
        if isinstance(raw, (list, tuple)):
            values.extend(str(value or "").strip() for value in raw if str(value or "").strip())
        elif isinstance(raw, str) and raw.strip():
            values.extend(value.strip() for value in raw.split(",") if value.strip())
        if not values:
            single = str(payload.get("service_name") or "").strip()
            if single:
                values.append(single)
        ordered: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(value)
        return tuple(ordered)

    def _configured_service_names(
        self,
        *,
        binding_auth_metadata_json: dict[str, object],
        binding_scope_json: dict[str, object],
    ) -> tuple[str, ...]:
        ordered: list[str] = []
        seen: set[str] = set()

        def add(value: object) -> None:
            normalized = str(value or "").strip()
            if not normalized:
                return
            key = normalized.lower()
            if key in seen:
                return
            seen.add(key)
            ordered.append(normalized)

        raw_accounts = binding_auth_metadata_json.get("service_accounts_json")
        if isinstance(raw_accounts, dict):
            for key, value in raw_accounts.items():
                if isinstance(value, dict) and any(field in value for field in ("tier", "plan", "account_email", "email", "status")):
                    add(key)
                elif key in {"service_name", "service", "name"}:
                    add(value)
        elif isinstance(raw_accounts, list):
            for value in raw_accounts:
                if isinstance(value, dict):
                    add(value.get("service_name") or value.get("service") or value.get("name"))
        raw_scope_services = binding_scope_json.get("services")
        if isinstance(raw_scope_services, (list, tuple)):
            for value in raw_scope_services:
                add(value)
        if isinstance(raw_scope_services, str):
            add(raw_scope_services)
        raw_scopes = binding_scope_json.get("scopes")
        if isinstance(raw_scopes, (list, tuple)):
            for value in raw_scopes:
                add(value)
        elif isinstance(raw_scopes, str):
            add(raw_scopes)
        return tuple(ordered)

    def _slugify(self, value: str) -> str:
        cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or ""))
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")
        return cleaned.strip("_") or "adapter"

    def _build_workflow_spec(
        self,
        *,
        workflow_name: str,
        purpose: str,
        login_url: str,
        tool_url: str,
        workflow_kind: str,
        runtime_input_name: str,
        prompt_selector: str,
        submit_selector: str,
        result_selector: str,
        wait_selector: str,
        title_selector: str,
        dismiss_selectors: list[str],
        result_field_name: str,
        output_dir: str,
    ) -> dict[str, object]:
        slug = self._slugify(workflow_name)
        nodes: list[dict[str, object]] = []
        edges: list[list[str]] = []
        inputs: list[dict[str, str]] = []
        if login_url.lower() not in {"", "none", "public", "noauth"}:
            nodes.extend(
                [
                    {"id": "open_login", "type": "visit_page", "label": "Open Login", "config": {"url": login_url}},
                    {"id": "email", "type": "input_text", "label": "Email", "config": {"selector": "input[type=email]", "value_from_secret": "browseract_username"}},
                    {"id": "password", "type": "input_text", "label": "Password", "config": {"selector": "input[type=password]", "value_from_secret": "browseract_password"}},
                    {"id": "submit", "type": "click", "label": "Submit", "config": {"selector": "button[type=submit]"}},
                    {"id": "wait_dashboard", "type": "wait", "label": "Wait Dashboard", "config": {"selector": "body"}},
                ]
            )
            edges.extend(
                [
                    ["open_login", "email"],
                    ["email", "password"],
                    ["password", "submit"],
                    ["submit", "wait_dashboard"],
                    ["wait_dashboard", "open_tool"],
                ]
            )
        if workflow_kind == "page_extract":
            visit_config: dict[str, str] = {"url": tool_url}
            if runtime_input_name:
                visit_config = {"value_from_input": runtime_input_name}
                inputs.append(
                    {
                        "name": runtime_input_name,
                        "description": f"Target page URL for {workflow_name}.",
                    }
                )
            nodes.append({"id": "open_tool", "type": "visit_page", "label": "Open Target Page", "config": visit_config})
            last_node = "open_tool"
            for index, selector in enumerate(dismiss_selectors, start=1):
                node_id = f"dismiss_{index:02d}"
                nodes.append(
                    {
                        "id": node_id,
                        "type": "click",
                        "label": f"Dismiss Overlay {index}",
                        "config": {"selector": selector},
                    }
                )
                edges.append([last_node, node_id])
                last_node = node_id
            nodes.append({"id": "wait_content", "type": "wait", "label": "Wait Content", "config": {"selector": wait_selector}})
            edges.append([last_node, "wait_content"])
            last_node = "wait_content"
            if title_selector:
                nodes.append({"id": "extract_title", "type": "extract", "label": "Extract Title", "config": {"selector": title_selector}})
                edges.append([last_node, "extract_title"])
                last_node = "extract_title"
            nodes.append(
                {
                    "id": "extract_result",
                    "type": "extract",
                    "label": "Extract Result",
                    "config": {"selector": result_selector, "field_name": result_field_name, "mode": "text"},
                }
            )
            edges.append([last_node, "extract_result"])
            nodes.append(
                {
                    "id": "output_result",
                    "type": "output",
                    "label": "Output Result",
                    "config": {
                        "description": f"Publish the {result_field_name} field as the workflow output for API callers.",
                        "field_name": result_field_name,
                    },
                }
            )
            edges.append(["extract_result", "output_result"])
        else:
            inputs.append(
                {
                    "name": "prompt",
                    "description": f"Primary runtime prompt for {workflow_name}.",
                }
            )
            nodes.extend(
                [
                    {"id": "open_tool", "type": "visit_page", "label": "Open Tool", "config": {"url": tool_url}},
                    {"id": "input_prompt", "type": "input_text", "label": "Input Prompt", "config": {"selector": prompt_selector, "value_from_input": "prompt"}},
                    {"id": "generate", "type": "click", "label": "Generate", "config": {"selector": submit_selector}},
                    {
                        "id": "wait_result",
                        "type": "wait",
                        "label": "Wait Result",
                        "config": {
                            "selector": wait_selector,
                            "description": f"Wait until the result target {wait_selector} is visible and ready after submission.",
                            "timeout_ms": 60000,
                        },
                    },
                    {
                        "id": "extract_result",
                        "type": "extract",
                        "label": "Extract Result",
                        "config": {"selector": result_selector, "field_name": result_field_name, "mode": "text"},
                    },
                    {
                        "id": "output_result",
                        "type": "output",
                        "label": "Output Result",
                        "config": {
                            "description": f"Publish the {result_field_name} field as the workflow output for API callers.",
                            "field_name": result_field_name,
                        },
                    },
                ]
            )
            edges.extend(
                [
                    ["open_tool", "input_prompt"],
                    ["input_prompt", "generate"],
                    ["generate", "wait_result"],
                    ["wait_result", "extract_result"],
                    ["extract_result", "output_result"],
                ]
            )
        return {
            "workflow_name": workflow_name,
            "description": purpose,
            "publish": True,
            "mcp_ready": False,
            "inputs": inputs,
            "nodes": nodes,
            "edges": edges,
            "meta": {
                "slug": slug,
                "output_dir": output_dir,
                "status": "pending_browseract_seed",
                "workflow_kind": workflow_kind,
            },
        }

    def _normalize_string_list(self, raw: object) -> list[str]:
        values: list[str] = []
        if isinstance(raw, (list, tuple, set)):
            values.extend(str(value or "").strip() for value in raw if str(value or "").strip())
        elif isinstance(raw, str) and raw.strip():
            values.extend(part.strip() for part in raw.split("|") if part.strip())
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(value)
        return deduped

    def _gemini_command_base(self) -> list[str]:
        raw = str(os.environ.get("EA_GEMINI_VORTEX_COMMAND") or "gemini").strip() or "gemini"
        return shlex.split(raw)

    def _gemini_model(self) -> str:
        return str(os.environ.get("EA_GEMINI_VORTEX_MODEL") or "gemini-2.5-flash").strip() or "gemini-2.5-flash"

    def _gemini_timeout_seconds(self) -> int:
        raw = str(os.environ.get("EA_GEMINI_VORTEX_TIMEOUT_SECONDS") or "180").strip() or "180"
        try:
            return max(15, int(raw))
        except Exception:
            return 180

    def _strip_fences(self, text: str) -> str:
        raw = str(text or "").strip()
        if raw.startswith("```"):
            raw = raw.removeprefix("```json").removeprefix("```").strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
        return raw

    def _run_gemini_repair_prompt(self, prompt: str) -> tuple[dict[str, object], str]:
        model = self._gemini_model()
        command = self._gemini_command_base() + [
            "-p",
            prompt,
            "--output-format",
            "json",
            "--approval-mode",
            "yolo",
        ]
        if model:
            command.extend(["-m", model])
        try:
            completed = subprocess.run(
                command,
                check=True,
                text=True,
                capture_output=True,
                timeout=self._gemini_timeout_seconds(),
            )
        except FileNotFoundError as exc:
            raise ToolExecutionError("gemini_vortex_cli_missing:browseract.repair_workflow_spec") from exc
        except subprocess.TimeoutExpired as exc:
            raise ToolExecutionError("gemini_vortex_timeout:browseract.repair_workflow_spec") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise ToolExecutionError(f"gemini_vortex_failed:browseract.repair_workflow_spec:{detail[:400]}") from exc
        raw = str(completed.stdout or "").strip()
        if not raw:
            raise ToolExecutionError("gemini_vortex_empty_output:browseract.repair_workflow_spec")
        try:
            envelope = json.loads(raw)
        except Exception:
            envelope = {"response": raw}
        response = envelope.get("response") if isinstance(envelope, dict) else raw
        cleaned = self._strip_fences(str(response or raw))
        try:
            loaded = json.loads(cleaned)
        except Exception as exc:
            raise ToolExecutionError("gemini_vortex_non_json:browseract.repair_workflow_spec") from exc
        if not isinstance(loaded, dict):
            raise ToolExecutionError("gemini_vortex_non_object:browseract.repair_workflow_spec")
        return loaded, model

    def _build_workflow_repair_prompt(
        self,
        *,
        workflow_name: str,
        purpose: str,
        login_url: str,
        tool_url: str,
        failure_summary: str,
        failure_goals: list[str],
        current_spec: dict[str, object],
        scaffold: dict[str, object],
    ) -> str:
        schema = {
            "type": "object",
            "required": ["diagnosis", "repair_strategy", "workflow_spec"],
            "properties": {
                "diagnosis": {"type": "string"},
                "repair_strategy": {"type": "string"},
                "operator_checks": {"type": "array", "items": {"type": "string"}},
                "workflow_spec": {
                    "type": "object",
                    "required": ["workflow_name", "description", "publish", "mcp_ready", "nodes", "edges", "meta"],
                    "properties": {
                        "workflow_name": {"type": "string"},
                        "description": {"type": "string"},
                        "publish": {"type": "boolean"},
                        "mcp_ready": {"type": "boolean"},
                        "nodes": {"type": "array"},
                        "edges": {"type": "array"},
                        "meta": {"type": "object"},
                    },
                },
            },
        }
        return "\n\n".join(
            [
                "Return JSON only. No markdown fences or commentary.",
                "You are repairing a BrowserAct workflow spec after a runtime failure.",
                "Goal: produce a repaired workflow spec packet that keeps the intended workflow name and purpose but fixes the observed execution failure.",
                "Rules:",
                "- use Gemini judgment, not generic filler",
                "- keep the workflow grounded in actual BrowserAct node types like visit_page, input_text, click, wait, extract",
                "- preserve runtime input bindings when present; do not literalize placeholders like /text",
                "- if the evidence says a value_from_input binding was typed literally, repair the node config so BrowserAct treats it as a runtime input",
                "- keep publish true and mcp_ready false unless evidence clearly requires otherwise",
                "- keep nodes and edges compact and executable",
                "- operator_checks should be 2 to 4 short human verification checks",
                "Schema contract:\n" + json.dumps(schema, ensure_ascii=True),
                "Workflow brief:\n"
                + json.dumps(
                    {
                        "workflow_name": workflow_name,
                        "purpose": purpose,
                        "login_url": login_url,
                        "tool_url": tool_url,
                        "failure_summary": failure_summary,
                        "failing_step_goals": failure_goals,
                        "current_workflow_spec_json": current_spec,
                        "fallback_scaffold_spec_json": scaffold,
                    },
                    ensure_ascii=True,
                ),
            ]
        ).strip()

    def _normalize_workflow_repair_packet(
        self,
        raw: dict[str, object],
        *,
        workflow_name: str,
        purpose: str,
        scaffold: dict[str, object],
        failure_summary: str,
        failure_goals: list[str],
    ) -> dict[str, object]:
        packet = dict(raw)
        diagnosis = str(packet.get("diagnosis") or failure_summary).strip() or failure_summary
        repair_strategy = str(packet.get("repair_strategy") or "Repair the BrowserAct workflow spec to preserve runtime input binding and result extraction.").strip()
        operator_checks = self._normalize_string_list(packet.get("operator_checks"))[:4]
        workflow_spec = packet.get("workflow_spec")
        if not isinstance(workflow_spec, dict):
            workflow_spec = packet if isinstance(packet.get("nodes"), list) and isinstance(packet.get("edges"), list) else {}
        spec = dict(scaffold)
        spec.update({key: value for key, value in dict(workflow_spec).items() if key in {"workflow_name", "description", "publish", "mcp_ready", "nodes", "edges", "meta"}})
        spec["workflow_name"] = str(spec.get("workflow_name") or workflow_name).strip() or workflow_name
        spec["description"] = str(spec.get("description") or purpose).strip() or purpose
        spec["publish"] = bool(spec.get("publish", True))
        spec["mcp_ready"] = bool(spec.get("mcp_ready", False))
        nodes = spec.get("nodes")
        edges = spec.get("edges")
        if not isinstance(nodes, list) or not nodes:
            raise ToolExecutionError("workflow_nodes_required:browseract.repair_workflow_spec")
        if not isinstance(edges, list) or not edges:
            raise ToolExecutionError("workflow_edges_required:browseract.repair_workflow_spec")
        meta = dict(spec.get("meta") or {})
        meta["slug"] = str(meta.get("slug") or self._slugify(spec["workflow_name"])).strip() or self._slugify(spec["workflow_name"])
        meta["status"] = str(meta.get("status") or "pending_browseract_repair").strip() or "pending_browseract_repair"
        meta["repair_failure_summary"] = failure_summary
        meta["repair_failure_goals"] = failure_goals
        meta["repair_generated_at"] = now_utc_iso()
        meta["repair_source"] = "gemini_vortex"
        spec["meta"] = meta
        return {
            "diagnosis": diagnosis,
            "repair_strategy": repair_strategy,
            "operator_checks": operator_checks,
            "workflow_spec": spec,
        }

    def _service_facts(self, *, binding_auth_metadata_json: dict[str, object], service_name: str) -> dict[str, object] | None:
        normalized_service_name = str(service_name or "").strip().lower()
        raw = binding_auth_metadata_json.get("service_accounts_json")
        if isinstance(raw, dict):
            for key, value in raw.items():
                if str(key or "").strip().lower() != normalized_service_name:
                    continue
                if isinstance(value, dict):
                    return {str(entry_key): entry_value for entry_key, entry_value in value.items()}
                return {"value": value}
            if str(raw.get("service_name") or raw.get("service") or raw.get("name") or "").strip().lower() == normalized_service_name:
                return {str(key): value for key, value in raw.items()}
        if isinstance(raw, list):
            for value in raw:
                if not isinstance(value, dict):
                    continue
                candidate_name = str(value.get("service_name") or value.get("service") or value.get("name") or "").strip()
                if candidate_name.lower() != normalized_service_name:
                    continue
                return {str(key): entry_value for key, entry_value in value.items()}
        return None

    def _configured_api_key(self) -> str:
        for key_name in ("BROWSERACT_API_KEY", "BROWSERACT_API_KEY_FALLBACK_1", "BROWSERACT_API_KEY_FALLBACK_2", "BROWSERACT_API_KEY_FALLBACK_3"):
            value = str(os.getenv(key_name) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _resolve_principal_id(request: ToolInvocationRequest, payload: dict[str, object]) -> str:
        request_principal_id = str((request.context_json or {}).get("principal_id") or "").strip()
        if not request_principal_id:
            raise ToolExecutionError("principal_id_required")
        supplied_principal_id = str(payload.get("principal_id") or "").strip()
        if supplied_principal_id and supplied_principal_id != request_principal_id:
            raise ToolExecutionError("principal_scope_mismatch")
        return request_principal_id

    @staticmethod
    def _chatplayground_request_urls(base_url: str) -> tuple[str, ...]:
        seen: set[str] = set()
        candidates: list[str] = []

        def _add_url(raw: str) -> None:
            url = str(raw or "").strip()
            if not url:
                return
            parsed = urlparse(url)
            scheme = str(parsed.scheme or "https").lower()
            netloc = parsed.netloc
            path = parsed.path or "/"
            if path != "/" and path:
                path = path.rstrip("/")
            query = parsed.query or ""
            fragment = parsed.fragment or ""
            if not netloc and "://" in url:
                return
            if not scheme:
                url = f"https://{url}"
                parsed = urlparse(url)
                scheme = "https"
                netloc = parsed.netloc
                path = parsed.path or ""
                query = parsed.query or ""
                fragment = parsed.fragment or ""
            if not netloc:
                return
            normalized = urlunparse((scheme, netloc, path, "", query, fragment)) or url
            if normalized in seen:
                return
            seen.add(normalized)
            candidates.append(normalized)

        parsed = urlparse(base_url or "")
        if not parsed.scheme:
            parsed = urlparse(f"https://{base_url}")
        if parsed.netloc:
            parsed_path = (parsed.path or "").rstrip("/")
            netloc = parsed.netloc
            api_prefixes = (
                "/api/chat/lmsys",
                "/api/chat",
                "/api/chat/completions",
                "/api/v1/chat/lmsys",
                "/api/v1/chat/completions",
            )
            if parsed_path.startswith("/api/"):
                candidate_paths = [parsed_path, *[suffix for suffix in api_prefixes if suffix != parsed_path]]
            else:
                candidate_paths = []
                for suffix in api_prefixes:
                    if not parsed_path or parsed_path == "/":
                        candidate_path = suffix
                    else:
                        candidate_path = f"{parsed_path}{suffix}"
                    candidate_paths.append(candidate_path)
            for candidate_path in candidate_paths:
                _add_url(urlunparse((parsed.scheme or "https", netloc, candidate_path, "", "", "")))
            _add_url(base_url)
            if parsed.netloc.lower() == "web.chatplayground.ai":
                _add_url("https://app.chatplayground.ai/api/chat/lmsys")
                _add_url("https://app.chatplayground.ai/api/v1/chat/lmsys")
        else:
            _add_url(base_url)
        return tuple(candidates)

    @staticmethod
    def _browseract_api_base() -> str:
        return str(os.getenv("BROWSERACT_WORKFLOW_API_BASE") or "https://api.browseract.com/v2/workflow").strip().rstrip("/")

    def _browseract_api_request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        query: dict[str, str] | None = None,
        timeout_seconds: int = 120,
    ) -> dict[str, object]:
        api_key = self._configured_api_key()
        if not api_key:
            raise ToolExecutionError("browseract_api_key_missing")
        url = self._browseract_api_base() + path
        if query:
            url += "?" + urlencode(query)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "EA-BrowserAct/1.0",
        }
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ToolExecutionError(f"browseract_api_http_error:{exc.code}:{detail[:240]}") from exc
        except urllib.error.URLError as exc:
            raise ToolExecutionError(f"browseract_api_transport_error:{exc.reason}") from exc
        try:
            loaded = json.loads(body)
        except Exception as exc:
            raise ToolExecutionError("browseract_api_response_invalid") from exc
        return loaded if isinstance(loaded, dict) else {"data": loaded}

    @staticmethod
    def _browseract_extract_workflow_id(entry: dict[str, object]) -> str:
        for key in ("workflow_id", "id", "_id", "workflowId"):
            value = str(entry.get(key) or "").strip()
            if value:
                return value
        nested = entry.get("data")
        if isinstance(nested, dict):
            for key in ("workflow_id", "id", "_id", "workflowId"):
                value = str(nested.get(key) or "").strip()
                if value:
                    return value
        popup_url = str(entry.get("popup_url") or "").strip()
        if "/workflow/" in popup_url:
            tail = popup_url.split("/workflow/", 1)[1]
            workflow_id = tail.split("/", 1)[0].split("?", 1)[0].strip()
            if workflow_id:
                return workflow_id
        return ""

    def _browseract_list_workflows(self) -> list[dict[str, object]]:
        body = self._browseract_api_request("GET", "/list-workflows", timeout_seconds=120)
        for key in ("workflows", "data", "items", "rows"):
            value = body.get(key)
            if isinstance(value, list):
                return [entry for entry in value if isinstance(entry, dict)]
        return [body] if isinstance(body, dict) else []

    @staticmethod
    def _candidate_chatplayground_workflow_result_paths(
        *,
        payload: dict[str, object],
        binding_metadata: dict[str, object],
    ) -> tuple[Path, ...]:
        candidates: list[Path] = []
        for raw in (
            payload.get("workflow_result_path"),
            payload.get("result_path"),
            binding_metadata.get("chatplayground_workflow_result_path"),
            binding_metadata.get("workflow_result_path"),
            os.getenv("BROWSERACT_CHATPLAYGROUND_AUDIT_RESULT_PATH"),
            "/docker/fleet/state/browseract_bootstrap/runtime/ea_chatplayground_audit_live/result.json",
        ):
            value = str(raw or "").strip()
            if not value:
                continue
            path = Path(value).expanduser()
            if path not in candidates:
                candidates.append(path)
        return tuple(candidates)

    def _resolve_chatplayground_workflow(
        self,
        *,
        payload: dict[str, object],
        binding_metadata: dict[str, object],
    ) -> tuple[str, str]:
        for raw in (
            payload.get("workflow_id"),
            payload.get("browseract_workflow_id"),
            binding_metadata.get("chatplayground_workflow_id"),
            binding_metadata.get("browseract_workflow_id"),
            binding_metadata.get("workflow_id"),
            os.getenv("BROWSERACT_CHATPLAYGROUND_AUDIT_WORKFLOW_ID"),
        ):
            workflow_id = str(raw or "").strip()
            if workflow_id:
                return workflow_id, "explicit"

        for path in self._candidate_chatplayground_workflow_result_paths(payload=payload, binding_metadata=binding_metadata):
            if not path.exists():
                continue
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(loaded, dict):
                workflow_id = self._browseract_extract_workflow_id(loaded)
                if workflow_id:
                    return workflow_id, str(path)

        queries: list[str] = []
        for raw in (
            payload.get("workflow_query"),
            binding_metadata.get("chatplayground_workflow_query"),
            binding_metadata.get("workflow_query"),
            os.getenv("BROWSERACT_CHATPLAYGROUND_AUDIT_WORKFLOW_QUERY"),
            "ea_chatplayground_audit_live",
        ):
            value = str(raw or "").strip().lower()
            if value and value not in queries:
                queries.append(value)
        if not queries:
            return "", ""
        try:
            workflows = self._browseract_list_workflows()
        except ToolExecutionError:
            return "", ""
        for query_value in queries:
            for entry in workflows:
                workflow_id = self._browseract_extract_workflow_id(entry)
                if not workflow_id:
                    continue
                haystack = " ".join(
                    str(entry.get(field) or "")
                    for field in ("name", "title", "description", "slug", "workflow_name")
                ).lower()
                if query_value in haystack:
                    return workflow_id, query_value
        return "", ""

    @staticmethod
    def _browseract_task_id(body: dict[str, object]) -> str:
        for key in ("task_id", "id", "_id"):
            value = str(body.get(key) or "").strip()
            if value:
                return value
        nested = body.get("data")
        if isinstance(nested, dict):
            for key in ("task_id", "id", "_id"):
                value = str(nested.get(key) or "").strip()
                if value:
                    return value
        raise ToolExecutionError("browseract_task_id_missing")

    @staticmethod
    def _browseract_task_status(body: dict[str, object]) -> str:
        for key in ("status", "task_status", "state"):
            value = str(body.get(key) or "").strip()
            if value:
                return value.lower()
        nested = body.get("data")
        if isinstance(nested, dict):
            for key in ("status", "task_status", "state"):
                value = str(nested.get(key) or "").strip()
                if value:
                    return value.lower()
        return ""

    @staticmethod
    def _browseract_task_output(body: dict[str, object]) -> dict[str, object]:
        candidates = [
            body.get("output"),
            (body.get("data") or {}).get("output") if isinstance(body.get("data"), dict) else None,
            (body.get("result") or {}).get("output") if isinstance(body.get("result"), dict) else None,
        ]
        for candidate in candidates:
            if isinstance(candidate, dict):
                return dict(candidate)
        return {}

    @staticmethod
    def _browseract_output_has_content(value: object) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (int, float, bool)):
            return True
        if isinstance(value, dict):
            return any(BrowserActToolAdapter._browseract_output_has_content(nested) for nested in value.values())
        if isinstance(value, (list, tuple, set)):
            return any(BrowserActToolAdapter._browseract_output_has_content(nested) for nested in value)
        return bool(str(value).strip())

    @staticmethod
    def _browseract_task_finished_at(body: dict[str, object]) -> str:
        for key in ("finished_at", "finishedAt", "completed_at", "completedAt"):
            value = str(body.get(key) or "").strip()
            if value:
                return value
        nested = body.get("data")
        if isinstance(nested, dict):
            for key in ("finished_at", "finishedAt", "completed_at", "completedAt"):
                value = str(nested.get(key) or "").strip()
                if value:
                    return value
        return ""

    @staticmethod
    def _browseract_task_steps(body: dict[str, object]) -> list[dict[str, object]]:
        for key in ("steps",):
            value = body.get(key)
            if isinstance(value, list):
                return [entry for entry in value if isinstance(entry, dict)]
        nested = body.get("data")
        if isinstance(nested, dict):
            value = nested.get("steps")
            if isinstance(value, list):
                return [entry for entry in value if isinstance(entry, dict)]
        return []

    @staticmethod
    def _browseract_task_failure_info(body: dict[str, object]) -> dict[str, object]:
        for key in ("task_failure_info", "failure_info", "error"):
            value = body.get(key)
            if isinstance(value, dict):
                return dict(value)
        nested = body.get("data")
        if isinstance(nested, dict):
            for key in ("task_failure_info", "failure_info", "error"):
                value = nested.get(key)
                if isinstance(value, dict):
                    return dict(value)
        return {}

    def _chatplayground_workflow_timeout_seconds(self, payload: dict[str, object]) -> int:
        raw = str(
            payload.get("timeout_seconds")
            or os.getenv("BROWSERACT_CHATPLAYGROUND_AUDIT_TIMEOUT_SECONDS")
            or os.getenv("EA_RESPONSES_CHATPLAYGROUND_TIMEOUT_SECONDS")
            or "600"
        ).strip() or "600"
        try:
            return max(30, min(1800, int(raw)))
        except Exception:
            return 600

    def _browseract_created_stall_seconds(self, payload: dict[str, object]) -> int:
        raw = str(
            payload.get("created_stall_seconds")
            or os.getenv("BROWSERACT_CHATPLAYGROUND_AUDIT_CREATED_STALL_SECONDS")
            or "120"
        ).strip() or "120"
        try:
            return max(30, min(900, int(raw)))
        except Exception:
            return 120

    def _chatplayground_workflow_attempts(self, payload: dict[str, object]) -> int:
        raw = str(
            payload.get("workflow_attempts")
            or os.getenv("BROWSERACT_CHATPLAYGROUND_AUDIT_MAX_ATTEMPTS")
            or "3"
        ).strip() or "3"
        try:
            return max(1, min(4, int(raw)))
        except Exception:
            return 3

    def _run_browseract_workflow_task(
        self,
        *,
        workflow_id: str,
        prompt: str,
    ) -> dict[str, object]:
        return self._run_browseract_workflow_task_with_inputs(
            workflow_id=workflow_id,
            input_values={"prompt": prompt},
        )

    @staticmethod
    def _browseract_workflow_input_variants(input_values: dict[str, object]) -> list[object]:
        values = {str(key or "").strip(): value for key, value in input_values.items() if str(key or "").strip()}
        if not values:
            return []
        ordered = list(values.items())
        return [
            [{"name": key, "value": value} for key, value in ordered],
            [{"key": key, "value": value} for key, value in ordered],
            [{key: value for key, value in ordered}],
            {key: value for key, value in ordered},
        ]

    def _run_browseract_workflow_task_with_inputs(
        self,
        *,
        workflow_id: str,
        input_values: dict[str, object],
    ) -> dict[str, object]:
        payload_variants = [
            {"workflow_id": workflow_id, "input_parameters": candidate}
            for candidate in self._browseract_workflow_input_variants(input_values)
        ]
        last_error = "browseract_run_task_failed"
        for candidate in payload_variants:
            try:
                return self._browseract_api_request("POST", "/run-task", payload=candidate, timeout_seconds=120)
            except ToolExecutionError as exc:
                last_error = str(exc)
                continue
        raise ToolExecutionError(last_error)

    @staticmethod
    def _onemin_browser_password() -> str:
        return str(os.getenv("ONEMIN_DEFAULT_PASSWORD") or os.getenv("BROWSERACT_PASSWORD") or "").strip()

    @staticmethod
    def _onemin_owner_email_for_account(*, account_label: str) -> str:
        from app.services import responses_upstream as upstream

        normalized = str(account_label or "").strip()
        if not normalized:
            return ""
        for row in upstream.onemin_owner_rows():
            if normalized in {
                str(row.get("account_name") or "").strip(),
                str(row.get("slot") or "").strip(),
                str(row.get("owner_label") or "").strip(),
            }:
                return str(row.get("owner_email") or "").strip()
        return ""

    def _run_onemin_workflow_task(
        self,
        *,
        workflow_id: str,
        account_label: str,
        timeout_seconds: int,
    ) -> dict[str, object]:
        owner_email = self._onemin_owner_email_for_account(account_label=account_label)
        if not owner_email:
            raise ToolExecutionError(f"owner_email_required:onemin:{account_label}")
        password = self._onemin_browser_password()
        if not password:
            raise ToolExecutionError("onemin_password_missing")
        started = self._run_browseract_workflow_task_with_inputs(
            workflow_id=workflow_id,
            input_values={
                "browseract_username": owner_email,
                "browseract_password": password,
            },
        )
        return self._wait_for_browseract_task(
            task_id=self._browseract_task_id(started),
            timeout_seconds=timeout_seconds,
            created_stall_seconds=min(120, timeout_seconds),
        )

    def _wait_for_browseract_task(
        self,
        *,
        task_id: str,
        timeout_seconds: int,
        created_stall_seconds: int = 120,
    ) -> dict[str, object]:
        deadline = time.time() + max(30, timeout_seconds)
        last_status = ""
        created_started_at = time.time()
        inconsistent_started_at: float | None = None
        while time.time() < deadline:
            status_body = self._browseract_api_request(
                "GET",
                "/get-task-status",
                query={"task_id": task_id},
                timeout_seconds=60,
            )
            status = self._browseract_task_status(status_body)
            if status:
                last_status = status
            if status in {"created", "queued", "pending", "running", "processing"}:
                task_body = self._browseract_api_request(
                    "GET",
                    "/get-task",
                    query={"task_id": task_id},
                    timeout_seconds=120,
                )
                task_status = self._browseract_task_status(task_body)
                if task_status:
                    last_status = task_status
                failure_info = self._browseract_task_failure_info(task_body)
                if failure_info:
                    detail = json.dumps(failure_info, ensure_ascii=True)[:400]
                    raise ToolExecutionError(f"browseract_task_failed:{detail}")
                if self._browseract_output_has_content(self._browseract_task_output(task_body)):
                    return task_body
                if self._browseract_task_steps(task_body):
                    created_started_at = time.time()
                    inconsistent_started_at = None
                    time.sleep(5)
                    continue
                if self._browseract_task_finished_at(task_body):
                    if inconsistent_started_at is None:
                        inconsistent_started_at = time.time()
                    elif time.time() - inconsistent_started_at >= max(15, min(60, created_stall_seconds // 2 or 15)):
                        raise ToolExecutionError(f"browseract_task_inconsistent_terminal:{task_id}:{status or task_status or 'unknown'}")
                    time.sleep(5)
                    continue
                if time.time() - created_started_at >= max(30, created_stall_seconds):
                    raise ToolExecutionError(f"browseract_task_stuck_created:{task_id}:{status}")
            if status in {"done", "completed", "success", "succeeded", "finished"}:
                task_body = self._browseract_api_request(
                    "GET",
                    "/get-task",
                    query={"task_id": task_id},
                    timeout_seconds=120,
                )
                failure_info = self._browseract_task_failure_info(task_body)
                if failure_info:
                    detail = json.dumps(failure_info, ensure_ascii=True)[:400]
                    raise ToolExecutionError(f"browseract_task_failed:{detail}")
                if self._browseract_output_has_content(self._browseract_task_output(task_body)):
                    return task_body
                if self._browseract_task_steps(task_body):
                    inconsistent_started_at = None
                    time.sleep(5)
                    continue
                if self._browseract_task_finished_at(task_body):
                    if inconsistent_started_at is None:
                        inconsistent_started_at = time.time()
                    elif time.time() - inconsistent_started_at >= max(15, min(60, created_stall_seconds // 2 or 15)):
                        raise ToolExecutionError(f"browseract_task_inconsistent_terminal:{task_id}:{status}")
                    time.sleep(5)
                    continue
                return task_body
            if status in {"failed", "error", "cancelled", "canceled"}:
                detail = json.dumps(status_body, ensure_ascii=True)[:400]
                raise ToolExecutionError(f"browseract_task_failed:{detail}")
            time.sleep(5)
        raise ToolExecutionError(f"browseract_task_timeout:{last_status or 'unknown'}")

    def _normalize_chatplayground_workflow_task_payload(
        self,
        *,
        task_body: dict[str, object],
        workflow_id: str,
        workflow_source: str,
        task_id: str,
        roles: list[str],
        audit_scope: str,
        requested_models: list[str],
    ) -> dict[str, object]:
        output_json = self._browseract_task_output(task_body)
        unwrapped = _unwrap_browseract_output_payload(output_json)
        normalized: dict[str, object] = {}
        if isinstance(unwrapped, dict):
            normalized = dict(unwrapped)
        elif isinstance(unwrapped, str):
            normalized = {
                "consensus": unwrapped,
                "recommendation": unwrapped,
                "raw_response_text": unwrapped,
            }
        if not normalized:
            fallback_text = _extract_textish(output_json)
            if fallback_text:
                normalized = {
                    "consensus": fallback_text,
                    "recommendation": fallback_text,
                    "raw_response_text": fallback_text,
                }
        if not normalized:
            raise ToolExecutionError("browseract_chatplayground_empty_output")
        normalized.setdefault("roles", list(roles))
        normalized.setdefault("requested_roles", list(roles))
        normalized.setdefault("audit_scope", audit_scope)
        normalized.setdefault("requested_models", list(requested_models))
        normalized.setdefault("requested_at", now_utc_iso())
        normalized.setdefault("requested_url", f"browseract://workflow/{workflow_id}/task/{task_id}")
        normalized.setdefault("workflow_id", workflow_id)
        normalized.setdefault("task_id", task_id)
        normalized.setdefault("workflow_source", workflow_source)
        normalized.setdefault("task_status", self._browseract_task_status(task_body) or "finished")
        normalized.setdefault("workflow_output_json", output_json)
        return normalized

    def _live_extract(
        self,
        *,
        binding_auth_metadata_json: dict[str, object],
        payload: dict[str, object],
        service_name: str,
        requested_fields: tuple[str, ...],
    ) -> dict[str, object] | None:
        run_url = str(payload.get("run_url") or binding_auth_metadata_json.get("browseract_run_url") or binding_auth_metadata_json.get("run_url") or "").strip()
        api_key = self._configured_api_key()
        if not run_url or not api_key:
            return None
        request_body = {
            "service_name": service_name,
            "requested_fields": list(requested_fields),
            "instructions": str(payload.get("instructions") or binding_auth_metadata_json.get("instructions") or ""),
            "account_hints_json": dict(payload.get("account_hints_json") or {}),
        }
        request = urllib.request.Request(
            run_url,
            data=json.dumps(request_body).encode("utf-8"),
            headers={"authorization": f"Bearer {api_key}", "content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            raise ToolExecutionError(f"browseract_live_http_error:{exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ToolExecutionError(f"browseract_live_transport_error:{exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise ToolExecutionError("browseract_live_response_invalid") from exc
        candidates = (
            body.get("facts_json") if isinstance(body, dict) else None,
            ((body.get("data") or {}).get("facts_json")) if isinstance(body, dict) and isinstance(body.get("data"), dict) else None,
            ((body.get("result") or {}).get("facts_json")) if isinstance(body, dict) and isinstance(body.get("result"), dict) else None,
            ((body.get("output") or {}).get("facts_json")) if isinstance(body, dict) and isinstance(body.get("output"), dict) else None,
        )
        for candidate in candidates:
            if isinstance(candidate, dict):
                return {str(key): value for key, value in candidate.items()} | {"verification_source": "browseract_live"}
        if isinstance(body, dict):
            return {str(key): value for key, value in body.items()} | {"verification_source": "browseract_live"}
        raise ToolExecutionError("browseract_live_response_invalid")

    def _fact_present(self, value: object) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, dict, set)):
            return bool(value)
        return True

    def _summary_text(
        self,
        *,
        service_name: str,
        facts_json: dict[str, object],
        requested_fields: tuple[str, ...],
        missing_fields: tuple[str, ...],
        verification_source: str,
        last_verified_at: str,
    ) -> str:
        ordered_keys = requested_fields or tuple(key for key in facts_json.keys() if key not in {"service_name", "verification_source"})
        lines = [f"Service: {service_name}", f"Verification source: {verification_source}", f"Last verified at: {last_verified_at}"]
        for key in ordered_keys:
            value = facts_json.get(key)
            lines.append(f"{key}: {value}" if self._fact_present(value) else f"{key}: <missing>")
        if missing_fields:
            lines.append(f"Missing fields: {', '.join(missing_fields)}")
        return "\n".join(lines)

    def _inventory_summary_text(self, services_json: list[dict[str, object]]) -> str:
        summaries = [str((row.get("normalized_text") or "")).strip() for row in services_json if str((row.get("normalized_text") or "")).strip()]
        if not summaries:
            return "No BrowserAct-backed service inventory facts were discovered."
        return "\n\n".join(summaries)

    def _extract_service_record(
        self,
        *,
        binding_auth_metadata_json: dict[str, object],
        payload: dict[str, object],
        service_name: str,
        requested_fields: tuple[str, ...],
        allow_missing: bool,
    ) -> dict[str, object]:
        facts_json = self._service_facts(binding_auth_metadata_json=binding_auth_metadata_json, service_name=service_name)
        live_discovery_error = ""
        if facts_json is None:
            try:
                live_facts_json = self._live_extract(
                    binding_auth_metadata_json=binding_auth_metadata_json,
                    payload=payload,
                    service_name=service_name,
                    requested_fields=requested_fields,
                )
            except ToolExecutionError as exc:
                live_discovery_error = str(exc)
                live_facts_json = None
            if live_facts_json is not None:
                facts_json = dict(live_facts_json)
        elif requested_fields:
            try:
                live_facts_json = self._live_extract(
                    binding_auth_metadata_json=binding_auth_metadata_json,
                    payload=payload,
                    service_name=service_name,
                    requested_fields=requested_fields,
                )
            except ToolExecutionError as exc:
                live_discovery_error = str(exc)
                live_facts_json = None
            if live_facts_json is not None:
                merged_facts_json = {str(key): value for key, value in facts_json.items()}
                for key, value in live_facts_json.items():
                    if self._fact_present(value):
                        merged_facts_json[str(key)] = value
                facts_json = merged_facts_json
        verification_source = "connector_metadata"
        if facts_json is None:
            facts_json = {}
            verification_source = "missing"
        else:
            verification_source = str(facts_json.pop("verification_source", "") or "connector_metadata").strip() or "connector_metadata"
        normalized_facts_json = {str(key): value for key, value in facts_json.items()}
        normalized_facts_json.setdefault("service_name", service_name)
        resolved_requested_fields = requested_fields or tuple(key for key in normalized_facts_json.keys() if key != "service_name")
        if not resolved_requested_fields and allow_missing:
            resolved_requested_fields = ("tier", "account_email", "status")
        missing_fields = tuple(key for key in resolved_requested_fields if not self._fact_present(normalized_facts_json.get(key)))
        account_email = str(normalized_facts_json.get("account_email") or normalized_facts_json.get("email") or normalized_facts_json.get("login_email") or "").strip()
        plan_tier = str(normalized_facts_json.get("tier") or normalized_facts_json.get("plan") or normalized_facts_json.get("plan_tier") or normalized_facts_json.get("license_tier") or "").strip()
        last_verified_at = now_utc_iso()
        discovery_status = "missing" if verification_source == "missing" else ("complete" if resolved_requested_fields and not missing_fields else "partial")
        normalized_text = self._summary_text(
            service_name=service_name,
            facts_json=normalized_facts_json,
            requested_fields=resolved_requested_fields,
            missing_fields=missing_fields,
            verification_source=verification_source,
            last_verified_at=last_verified_at,
        )
        instructions = str(payload.get("instructions") or binding_auth_metadata_json.get("instructions") or "").strip()
        account_hints_json = dict(payload.get("account_hints_json") or {})
        requested_run_url = str(payload.get("run_url") or binding_auth_metadata_json.get("browseract_run_url") or binding_auth_metadata_json.get("run_url") or "").strip()
        structured_output_json = {
            "service_name": service_name,
            "facts_json": normalized_facts_json,
            "requested_fields": list(resolved_requested_fields),
            "missing_fields": list(missing_fields),
            "discovery_status": discovery_status,
            "verification_source": verification_source,
            "last_verified_at": last_verified_at,
            "account_email": account_email,
            "plan_tier": plan_tier,
            "instructions": instructions,
            "account_hints_json": account_hints_json,
            "requested_run_url": requested_run_url,
            "live_discovery_error": live_discovery_error,
        }
        return {
            "service_name": service_name,
            "facts_json": normalized_facts_json,
            "requested_fields": list(resolved_requested_fields),
            "missing_fields": list(missing_fields),
            "account_email": account_email,
            "plan_tier": plan_tier,
            "discovery_status": discovery_status,
            "verification_source": verification_source,
            "last_verified_at": last_verified_at,
            "instructions": instructions,
            "account_hints_json": account_hints_json,
            "requested_run_url": requested_run_url,
            "live_discovery_error": live_discovery_error,
            "normalized_text": normalized_text,
            "preview_text": artifact_preview_text(normalized_text),
            "mime_type": "text/plain",
            "structured_output_json": structured_output_json,
        }

    def execute_chatplayground_audit(
        self,
        request: ToolInvocationRequest,
        definition: ToolDefinition,
    ) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        binding = None
        binding_id = str(payload.get("binding_id") or "").strip()
        if binding_id:
            principal_id, binding = self._resolve_browseract_binding(
                request=request,
                payload=payload,
                required_input_error="connector_binding_required:browseract.chatplayground_audit",
                required_scopes=None,
            )
        else:
            principal_id = self._resolve_principal_id(request, payload)
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            raise ToolExecutionError(f"prompt_required:{definition.tool_name}")
        binding_metadata = dict(getattr(binding, "auth_metadata_json", {}) or {})
        resolved_binding_id = str(getattr(binding, "binding_id", "") or "")
        connector_name = str(getattr(binding, "connector_name", "") or "browseract") or "browseract"
        external_account_ref = str(getattr(binding, "external_account_ref", "") or "")
        run_url = str(
            payload.get("run_url")
            or binding_metadata.get("chatplayground_run_url")
            or binding_metadata.get("browseract_run_url")
            or binding_metadata.get("run_url")
            or os.environ.get("BROWSERACT_CHATPLAYGROUND_URL", "https://web.chatplayground.ai/").strip()
            or "https://web.chatplayground.ai/"
        ).strip()
        roles = [str(entry) for entry in (payload.get("roles") or ("factuality", "adversarial", "completeness", "risk")) if str(entry).strip()]
        if not roles:
            roles = ["factuality", "adversarial", "completeness", "risk"]
        audit_scope = str(payload.get("scope") or payload.get("audit_scope") or "").strip().lower()
        if not audit_scope:
            action_kind = str(request.action_kind or "").strip()
            if action_kind and "." in action_kind:
                audit_scope = action_kind.rsplit(".", 1)[-1].strip().lower()
            else:
                audit_scope = "jury"
        callback = getattr(self, "_chatplayground_audit", None)
        if callback is not None:
            callback_result = self._safe_call_chatplayground_audit_callback(
                callback=callback,
                request=request,
                payload=payload,
                definition=definition,
                prompt=prompt,
                roles=tuple(roles),
                audit_scope=audit_scope,
                run_url=run_url,
            )
            if callback_result is not None:
                return callback_result

        request_payload = {
            "prompt": prompt,
            "roles": list(roles),
            "requested_roles": list(roles),
            "audit_scope": audit_scope,
            "model": str(payload.get("model") or "").strip(),
            "requested_models": _normalize_text_list(payload.get("requested_models")),
            "principal_id": principal_id,
            "binding_id": resolved_binding_id,
            "external_account_ref": external_account_ref,
        }
        http_errors: list[str] = []
        workflow_id, workflow_source = self._resolve_chatplayground_workflow(
            payload=payload,
            binding_metadata=binding_metadata,
        )
        if workflow_id and self._configured_api_key():
            workflow_prompt = _render_chatplayground_workflow_prompt(
                prompt=prompt,
                roles=list(roles),
                audit_scope=audit_scope,
                requested_models=list(request_payload["requested_models"]),
            )
            max_attempts = self._chatplayground_workflow_attempts(payload)
            for attempt in range(max_attempts):
                try:
                    started = self._run_browseract_workflow_task(workflow_id=workflow_id, prompt=workflow_prompt or prompt)
                    task_id = self._browseract_task_id(started)
                    task_body = self._wait_for_browseract_task(
                        task_id=task_id,
                        timeout_seconds=self._chatplayground_workflow_timeout_seconds(payload),
                        created_stall_seconds=self._browseract_created_stall_seconds(payload),
                    )
                    response = self._normalize_chatplayground_workflow_task_payload(
                        task_body=task_body,
                        workflow_id=workflow_id,
                        workflow_source=workflow_source,
                        task_id=task_id,
                        roles=list(roles),
                        audit_scope=audit_scope,
                        requested_models=list(request_payload["requested_models"]),
                    )
                    self._raise_for_ui_lane_failure(payload=response, backend="chatplayground")
                    (
                        consensus,
                        recommendation,
                        normalized_roles,
                        disagreements,
                        risks,
                        model_deltas,
                        details,
                    ) = _normalize_chatplayground_audit_payload(response)
                    if consensus or recommendation:
                        safe_payload = {
                            **details,
                            "binding_id": resolved_binding_id,
                            "connector_name": connector_name,
                            "external_account_ref": external_account_ref,
                            "requested_url": str(response.get("requested_url") or f"browseract://workflow/{workflow_id}/task/{task_id}"),
                            "requested_roles": list(roles),
                            "audit_scope": audit_scope,
                            "consensus": consensus,
                            "recommendation": recommendation,
                            "roles": normalized_roles,
                            "disagreements": disagreements,
                            "risks": risks,
                            "model_deltas": model_deltas,
                            "prompt": prompt,
                            "workflow_prompt_chars": len(workflow_prompt or prompt),
                            "workflow_id": workflow_id,
                            "task_id": task_id,
                            "workflow_source": workflow_source,
                        }
                        action_kind = str(request.action_kind or "chatplayground_audit") or "chatplayground_audit"
                        normalized_text = str(safe_payload.get("normalized_text") or json.dumps(safe_payload, ensure_ascii=True, separators=(",", ":")))
                        return ToolInvocationResult(
                            tool_name=definition.tool_name,
                            action_kind=action_kind,
                            target_ref=f"browseract:{resolved_binding_id or 'env'}:chatplayground_audit:{task_id}",
                            output_json={
                                **safe_payload,
                                "tool_name": definition.tool_name,
                                "action_kind": action_kind,
                                "normalized_text": normalized_text,
                                "preview_text": artifact_preview_text(normalized_text),
                                "mime_type": "text/plain",
                                "structured_output_json": safe_payload,
                            },
                            receipt_json={
                                "binding_id": resolved_binding_id,
                                "connector_name": connector_name,
                                "external_account_ref": external_account_ref,
                                "principal_id": principal_id,
                                "handler_key": definition.tool_name,
                                "invocation_contract": "tool.v1",
                                "tool_version": definition.version,
                                "tool_name": definition.tool_name,
                                "action_kind": action_kind,
                                "requested_url": str(response.get("requested_url") or f"browseract://workflow/{workflow_id}/task/{task_id}"),
                                "requested_roles": list(roles),
                                "audit_scope": audit_scope,
                                "route": "browseract.chatplayground_audit",
                                "handler": "workflow_api",
                                "workflow_id": workflow_id,
                                "task_id": task_id,
                                "workflow_source": workflow_source,
                            },
                        )
                    http_errors.append(f"workflow:{workflow_id}:empty_audit")
                    break
                except ToolExecutionError as exc:
                    detail = str(exc)
                    retryable_prefixes = (
                        "browseract_task_inconsistent_terminal:",
                        "browseract_task_stuck_created:",
                    )
                    if detail.startswith(retryable_prefixes) and attempt + 1 < max_attempts:
                        time.sleep(min(10, 3 * (attempt + 1)))
                        continue
                    http_errors.append(f"workflow:{workflow_id}:{detail}")
                    break
        if self._configured_api_key():
            for candidate_url in self._chatplayground_request_urls(run_url):
                try:
                    response = self._post_browseract_json(
                        run_url=candidate_url,
                        request_payload=request_payload,
                        timeout_seconds=60,
                    )
                except ToolExecutionError as exc:
                    http_errors.append(f"{candidate_url}:{exc}")
                    continue
                self._raise_for_ui_lane_failure(payload=response, backend="chatplayground")
                (
                    consensus,
                    recommendation,
                    normalized_roles,
                    disagreements,
                    risks,
                    model_deltas,
                    details,
                ) = _normalize_chatplayground_audit_payload(response)
                if not consensus and not recommendation:
                    http_errors.append(f"{candidate_url}:empty_audit")
                    continue
                safe_payload = {
                    **details,
                    "binding_id": resolved_binding_id,
                    "connector_name": connector_name,
                    "external_account_ref": external_account_ref,
                    "requested_url": candidate_url,
                    "requested_roles": list(roles),
                    "audit_scope": audit_scope,
                    "consensus": consensus,
                    "recommendation": recommendation,
                    "roles": normalized_roles,
                    "disagreements": disagreements,
                    "risks": risks,
                    "model_deltas": model_deltas,
                    "prompt": prompt,
                }
                action_kind = str(request.action_kind or "chatplayground_audit") or "chatplayground_audit"
                normalized_text = str(safe_payload.get("normalized_text") or json.dumps(safe_payload, ensure_ascii=True, separators=(",", ":")))
                return ToolInvocationResult(
                    tool_name=definition.tool_name,
                    action_kind=action_kind,
                    target_ref=f"browseract:{resolved_binding_id or 'env'}:chatplayground_audit:{uuid.uuid4()}",
                    output_json={
                        **safe_payload,
                        "tool_name": definition.tool_name,
                        "action_kind": action_kind,
                        "normalized_text": normalized_text,
                        "preview_text": artifact_preview_text(normalized_text),
                        "mime_type": "text/plain",
                        "structured_output_json": safe_payload,
                    },
                    receipt_json={
                        "binding_id": resolved_binding_id,
                        "connector_name": connector_name,
                        "external_account_ref": external_account_ref,
                        "principal_id": principal_id,
                        "handler_key": definition.tool_name,
                        "invocation_contract": "tool.v1",
                        "tool_version": definition.version,
                        "tool_name": definition.tool_name,
                        "action_kind": action_kind,
                        "requested_url": candidate_url,
                        "requested_roles": list(roles),
                        "audit_scope": audit_scope,
                        "route": "browseract.chatplayground_audit",
                        "handler": "run_url",
                    },
                )

        if not binding_id:
            if http_errors:
                raise ToolExecutionError(f"browseract_chatplayground_audit_unavailable:{'; '.join(http_errors)}")
            raise ToolExecutionError("connector_binding_required:browseract.chatplayground_audit")

        normalized_text = "\n".join(
            [
                "ChatPlayground audit backend unavailable",
                f"run_url: {run_url or '<missing>'}",
                f"roles: {', '.join(roles) if roles else '<none>'}",
                f"errors: {'; '.join(http_errors) if http_errors else 'no_backend'}",
            ]
        )
        action_kind = str(request.action_kind or "chatplayground_audit") or "chatplayground_audit"
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=f"browseract:{resolved_binding_id or 'env'}:chatplayground_audit:{uuid.uuid4()}",
            output_json={
                "binding_id": resolved_binding_id,
                "connector_name": connector_name,
                "external_account_ref": external_account_ref,
                "prompt": prompt,
                "requested_url": run_url,
                "roles": roles,
                "requested_roles": roles,
                "audit_scope": audit_scope,
                "principal_id": principal_id,
                "normalized_text": normalized_text,
                "preview_text": artifact_preview_text(normalized_text),
                "mime_type": "text/plain",
                "structured_output_json": {
                    "prompt": prompt,
                    "requested_url": run_url,
                    "run_url": run_url,
                    "requested_roles": roles,
                    "roles": roles,
                    "audit_scope": audit_scope,
                    "principal_id": principal_id,
                    "binding_id": resolved_binding_id,
                    "connector_name": connector_name,
                    "external_account_ref": external_account_ref,
                    "status": "backend_unavailable",
                    "http_errors": list(http_errors),
                },
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "binding_id": resolved_binding_id,
                "connector_name": connector_name,
                "external_account_ref": external_account_ref,
                "principal_id": principal_id,
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "tool_version": definition.version,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
                "requested_url": run_url,
                "requested_roles": roles,
                "audit_scope": audit_scope,
                "route": "browseract.chatplayground_audit",
                "handler": "unavailable",
            },
        )

    @staticmethod
    def _safe_call_chatplayground_audit_callback(
        *,
        callback,
        request: ToolInvocationRequest,
        payload: dict[str, object],
        definition: ToolDefinition,
        prompt: str,
        roles: tuple[str, ...],
        audit_scope: str,
        run_url: str,
    ) -> ToolInvocationResult | None:
        candidate = None
        request_payload = dict(payload)
        request_payload["prompt"] = prompt
        request_payload["roles"] = list(roles)
        request_payload["requested_roles"] = list(roles)
        request_payload["audit_scope"] = audit_scope
        request_payload.setdefault("run_url", run_url)
        request_payload["requested_url"] = run_url
        signatures = None
        try:
            signatures = inspect.signature(callback)
        except Exception:
            signatures = None

        call_payload_variants: list[dict[str, object]] = [
            {"payload": request_payload, "run_url": run_url, "request_payload": request_payload},
            {"request_payload": request_payload, "run_url": run_url, "payload": request_payload},
            {"request": request, "payload": request_payload, "run_url": run_url, "audit_scope": audit_scope},
            {"request": request, "request_payload": request_payload, "run_url": run_url, "audit_scope": audit_scope},
            {"request": request, "payload": request_payload},
            {"request": request, "request_payload": request_payload},
            {"payload": request_payload},
            {"request_payload": request_payload},
            {"run_url": run_url, "request_payload": request_payload},
            {"request": request},
            {},
        ]

        def _bind_kwargs(candidates: dict[str, object]) -> dict[str, object]:
            if signatures is None:
                return candidates
            try:
                bound = signatures.bind_partial(**candidates)
            except TypeError:
                bound = {}
            else:
                return dict(bound.arguments)
            if not isinstance(candidates, dict):
                return {}
            fallback: dict[str, object] = {}
            for key, value in candidates.items():
                if key in signatures.parameters:
                    fallback[key] = value
            return fallback

        for call_kwargs in call_payload_variants:
            bound = _bind_kwargs(call_kwargs)
            try:
                if bound:
                    candidate = callback(**bound)
                    if candidate is not None:
                        break
                else:
                    if signatures is not None and len(signatures.parameters) == 0:
                        candidate = callback()
                        if candidate is not None:
                            break
                    if signatures is not None:
                        continue
                    candidate = callback()
                    if candidate is not None:
                        break
            except TypeError as exc:
                message = str(exc)
                if "missing" in message and "required" in message:
                    raise
                continue
            if candidate is not None:
                break
        if candidate is None:
            return None
        if isinstance(candidate, ToolInvocationResult):
            return candidate
        if not isinstance(candidate, dict):
            return None
        safe_payload = dict(candidate)
        BrowserActToolAdapter._raise_for_ui_lane_failure(payload=safe_payload, backend="chatplayground")
        safe_payload.setdefault("requested_url", run_url)
        safe_payload.setdefault("requested_roles", list(roles))
        safe_payload.setdefault("roles", list(roles))
        safe_payload.setdefault("audit_scope", audit_scope)
        safe_payload.setdefault("prompt", prompt)
        action_kind = str(request.action_kind or "chatplayground_audit") or "chatplayground_audit"
        normalized_text = str(safe_payload.get("normalized_text") or json.dumps(safe_payload))
        requested_roles_raw = safe_payload.get("requested_roles") or safe_payload.get("roles") or roles
        try:
            requested_roles = [str(role).strip() for role in list(requested_roles_raw) if str(role).strip()]
        except Exception:
            requested_roles = list(roles)
            if not requested_roles:
                requested_roles = ["factuality", "adversarial", "completeness", "risk"]
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=str(safe_payload.get("target_ref") or "browseract:chatplayground_audit:callback"),
            output_json={
                **safe_payload,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
                "normalized_text": normalized_text,
                "preview_text": artifact_preview_text(normalized_text),
                "requested_url": str(safe_payload.get("requested_url") or run_url),
                "requested_roles": requested_roles,
                "audit_scope": str(safe_payload.get("audit_scope") or audit_scope),
                "mime_type": "text/plain",
                "structured_output_json": safe_payload,
            },
            receipt_json={
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "tool_version": definition.version,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
                "requested_url": str(safe_payload.get("requested_url") or run_url),
                "requested_roles": requested_roles,
                "audit_scope": str(safe_payload.get("audit_scope") or audit_scope),
                "route": "browseract.chatplayground_audit",
                "handler": "callback",
            },
        )

    def execute_gemini_web_generate(
        self,
        request: ToolInvocationRequest,
        definition: ToolDefinition,
    ) -> ToolInvocationResult:
        payload = dict(request.payload_json or {})
        principal_id, binding = self._resolve_browseract_binding(
            request=request,
            payload=payload,
            required_input_error="connector_binding_required:browseract.gemini_web_generate",
            required_scopes=None,
        )
        packet = payload.get("packet")
        if not isinstance(packet, dict) or not packet:
            raise ToolExecutionError(f"packet_required:{definition.tool_name}")
        binding_metadata = dict(binding.auth_metadata_json or {})
        run_url = str(
            payload.get("run_url")
            or binding_metadata.get("gemini_web_run_url")
            or binding_metadata.get("browseract_gemini_web_run_url")
            or os.environ.get("BROWSERACT_GEMINI_WEB_URL", "").strip()
            or ""
        ).strip()
        mode = str(payload.get("mode") or "thinking").strip().lower() or "thinking"
        if mode not in {"thinking", "fast", "pro"}:
            mode = "thinking"
        deep_think = bool(payload.get("deep_think"))
        try:
            timeout_seconds = max(60, min(1800, int(payload.get("timeout_seconds") or 600)))
        except Exception:
            timeout_seconds = 600

        callback = getattr(self, "_gemini_web_generate", None)
        if callback is not None:
            callback_result = self._safe_call_gemini_web_generate_callback(
                callback=callback,
                request=request,
                payload=payload,
                definition=definition,
                packet=packet,
                mode=mode,
                deep_think=deep_think,
                run_url=run_url,
            )
            if callback_result is not None:
                return callback_result

        if run_url:
            response = self._post_browseract_json(
                run_url=run_url,
                request_payload={
                    "packet": packet,
                    "mode": mode,
                    "deep_think": deep_think,
                    "timeout_seconds": timeout_seconds,
                    "principal_id": principal_id,
                    "binding_id": binding.binding_id,
                    "external_account_ref": binding.external_account_ref,
                },
                timeout_seconds=timeout_seconds,
            )
            self._raise_for_ui_lane_failure(payload=response, backend="gemini_web")
            text = _extract_textish(
                response.get("text")
                or response.get("answer")
                or response.get("result")
                or response.get("normalized_text")
            )
            if text:
                action_kind = str(request.action_kind or "content.generate") or "content.generate"
                return ToolInvocationResult(
                    tool_name=definition.tool_name,
                    action_kind=action_kind,
                    target_ref=f"browseract:{binding.binding_id}:gemini_web_generate:{uuid.uuid4()}",
                    output_json={
                        "binding_id": binding.binding_id,
                        "connector_name": binding.connector_name,
                        "external_account_ref": binding.external_account_ref,
                        "text": text,
                        "mode_used": str(response.get("mode_used") or mode),
                        "deep_think": bool(response.get("deep_think", deep_think)),
                        "requested_url": run_url,
                        "provider_backend": "gemini_web",
                        "citations": list(response.get("citations") or []) if isinstance(response.get("citations"), list) else [],
                        "latency_ms": int(response.get("latency_ms") or 0),
                        "normalized_text": text,
                        "preview_text": artifact_preview_text(text),
                        "mime_type": "text/plain",
                        "structured_output_json": dict(response),
                        "tool_name": definition.tool_name,
                        "action_kind": action_kind,
                    },
                    receipt_json={
                        "binding_id": binding.binding_id,
                        "connector_name": binding.connector_name,
                        "external_account_ref": binding.external_account_ref,
                        "principal_id": principal_id,
                        "handler_key": definition.tool_name,
                        "invocation_contract": "tool.v1",
                        "tool_version": definition.version,
                        "requested_url": run_url,
                        "mode_used": str(response.get("mode_used") or mode),
                        "provider_backend": "gemini_web",
                        "route": "browseract.gemini_web_generate",
                        "handler": "run_url",
                    },
                )

        raise ToolExecutionError("browseract_gemini_web_generate_unavailable")

    def _post_browseract_json(
        self,
        *,
        run_url: str,
        request_payload: dict[str, object],
        timeout_seconds: int,
    ) -> dict[str, object]:
        api_key = self._configured_api_key()
        if not run_url or not api_key:
            raise ToolExecutionError("browseract_run_url_or_key_missing")
        request = urllib.request.Request(
            run_url,
            data=json.dumps(request_payload).encode("utf-8"),
            headers={"authorization": f"Bearer {api_key}", "content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            raise ToolExecutionError(f"browseract_live_http_error:{exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ToolExecutionError(f"browseract_live_transport_error:{exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise ToolExecutionError("browseract_live_response_invalid") from exc
        if isinstance(body, dict):
            return {str(key): value for key, value in body.items()}
        raise ToolExecutionError("browseract_live_response_invalid")

    @staticmethod
    def _safe_call_gemini_web_generate_callback(
        *,
        callback,
        request: ToolInvocationRequest,
        payload: dict[str, object],
        definition: ToolDefinition,
        packet: dict[str, object],
        mode: str,
        deep_think: bool,
        run_url: str,
    ) -> ToolInvocationResult | None:
        request_payload = dict(payload)
        request_payload["packet"] = dict(packet)
        request_payload["mode"] = mode
        request_payload["deep_think"] = deep_think
        request_payload["run_url"] = run_url
        signatures = None
        try:
            signatures = inspect.signature(callback)
        except Exception:
            signatures = None

        def _bind_kwargs(candidates: dict[str, object]) -> dict[str, object]:
            if signatures is None:
                return candidates
            try:
                bound = signatures.bind_partial(**candidates)
            except TypeError:
                bound = {}
            else:
                return dict(bound.arguments)
            fallback: dict[str, object] = {}
            for key, value in candidates.items():
                if key in signatures.parameters:
                    fallback[key] = value
            return fallback

        variants = (
            {"request": request, "payload": request_payload, "run_url": run_url},
            {"request_payload": request_payload, "run_url": run_url},
            {"payload": request_payload},
            {"request": request},
            {},
        )
        candidate = None
        for call_kwargs in variants:
            bound = _bind_kwargs(call_kwargs)
            try:
                if bound:
                    candidate = callback(**bound)
                else:
                    if signatures is not None and len(signatures.parameters) > 0:
                        continue
                    candidate = callback()
            except TypeError as exc:
                message = str(exc)
                if "missing" in message and "required" in message:
                    raise
                continue
            if candidate is not None:
                break
        if candidate is None:
            return None
        if isinstance(candidate, ToolInvocationResult):
            return candidate
        if not isinstance(candidate, dict):
            return None
        safe_payload = dict(candidate)
        BrowserActToolAdapter._raise_for_ui_lane_failure(payload=safe_payload, backend="gemini_web")
        text = _extract_textish(
            safe_payload.get("text")
            or safe_payload.get("answer")
            or safe_payload.get("result")
            or safe_payload.get("normalized_text")
        )
        if not text:
            return None
        action_kind = str(request.action_kind or "content.generate") or "content.generate"
        return ToolInvocationResult(
            tool_name=definition.tool_name,
            action_kind=action_kind,
            target_ref=str(safe_payload.get("target_ref") or "browseract:gemini_web_generate:callback"),
            output_json={
                **safe_payload,
                "text": text,
                "normalized_text": text,
                "preview_text": artifact_preview_text(text),
                "mime_type": "text/plain",
                "mode_used": str(safe_payload.get("mode_used") or mode),
                "deep_think": bool(safe_payload.get("deep_think", deep_think)),
                "requested_url": str(safe_payload.get("requested_url") or run_url),
                "provider_backend": "gemini_web",
                "structured_output_json": safe_payload,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
            },
            receipt_json={
                "handler_key": definition.tool_name,
                "invocation_contract": "tool.v1",
                "tool_version": definition.version,
                "tool_name": definition.tool_name,
                "action_kind": action_kind,
                "requested_url": str(safe_payload.get("requested_url") or run_url),
                "mode_used": str(safe_payload.get("mode_used") or mode),
                "provider_backend": "gemini_web",
                "route": "browseract.gemini_web_generate",
                "handler": "callback",
            },
        )
