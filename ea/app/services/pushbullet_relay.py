from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from app.services.pushbullet_delivery import (
    list_pushbullet_pushes,
    pushbullet_client_by_key,
    pushbullet_client_email,
    probe_pushbullet_client,
    send_pushbullet_note,
)

_PAYPAL_RE = re.compile(r"\bpaypal\b", re.IGNORECASE)
_PAYPAL_CODE_RE = re.compile(
    r"\b(?:code|security code|verification code|login code|otp|one-time|einmalcode|sicherheitscode)\b",
    re.IGNORECASE,
)
_NUMERIC_CODE_RE = re.compile(r"\b\d{4,8}\b")
_DEFAULT_PRIMARY_CLIENT = "default"
_DEFAULT_SECONDARY_CLIENT = "elisabeth"
_DEFAULT_STATE_FILENAME = "pushbullet_relay_state.json"


@dataclass(frozen=True)
class PushbulletRelayRule:
    key: str
    source_client_key: str
    target_client_key: str
    filter_mode: str


def _email_identity(email: object) -> str:
    normalized = str(email or "").strip().lower()
    if "@" not in normalized:
        return normalized
    local, domain = normalized.split("@", 1)
    if domain in {"gmail.com", "googlemail.com"}:
        return f"{local.replace('.', '')}@gmail.com"
    return f"{local}@{domain}"


def _env_mapping(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return env if env is not None else os.environ


def _env_bool(values: Mapping[str, str], key: str, *, default: bool) -> bool:
    raw = str(values.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _state_path(values: Mapping[str, str], *, state_path: str | Path = "") -> Path:
    if state_path:
        return Path(state_path)
    explicit = str(values.get("EA_PUSHBULLET_RELAY_STATE_PATH") or "").strip()
    if explicit:
        return Path(explicit)
    ledger_dir = str(values.get("EA_RESPONSES_PROVIDER_LEDGER_DIR") or "").strip()
    if ledger_dir:
        return Path(ledger_dir) / _DEFAULT_STATE_FILENAME
    return Path("state") / _DEFAULT_STATE_FILENAME


def _utc_now(observed_at: datetime | None = None) -> datetime:
    base = observed_at or datetime.now(UTC)
    if base.tzinfo is None:
        return base.replace(tzinfo=UTC)
    return base.astimezone(UTC)


def _client_key(value: object, *, default: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    return normalized or default


def _relay_rules(values: Mapping[str, str]) -> tuple[PushbulletRelayRule, ...]:
    primary_client_key = _client_key(
        values.get("EA_PUSHBULLET_RELAY_PRIMARY_CLIENT") or values.get("EA_PUSHBULLET_PRIMARY_CLIENT"),
        default=_DEFAULT_PRIMARY_CLIENT,
    )
    secondary_client_key = _client_key(
        values.get("EA_PUSHBULLET_RELAY_SECONDARY_CLIENT") or values.get("EA_PUSHBULLET_SECONDARY_CLIENT"),
        default=_DEFAULT_SECONDARY_CLIENT,
    )
    rules: list[PushbulletRelayRule] = []
    if _env_bool(values, "EA_PUSHBULLET_RELAY_PRIMARY_TO_SECONDARY_PAYPAL_ENABLED", default=True):
        rules.append(
            PushbulletRelayRule(
                key="primary_paypal_to_secondary",
                source_client_key=primary_client_key,
                target_client_key=secondary_client_key,
                filter_mode="paypal_code",
            )
        )
    if _env_bool(values, "EA_PUSHBULLET_RELAY_SECONDARY_TO_PRIMARY_ALL_ENABLED", default=True):
        rules.append(
            PushbulletRelayRule(
                key="secondary_all_to_primary",
                source_client_key=secondary_client_key,
                target_client_key=primary_client_key,
                filter_mode="all",
            )
        )
    return tuple(rules)


def _load_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "rules": {}}
    except Exception:
        return {"version": 1, "rules": {}}
    if not isinstance(payload, dict):
        return {"version": 1, "rules": {}}
    rules = payload.get("rules")
    payload["rules"] = dict(rules) if isinstance(rules, dict) else {}
    payload["version"] = int(payload.get("version") or 1)
    return payload


def _save_state(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _rule_state_entry(raw: object) -> dict[str, Any]:
    entry = dict(raw) if isinstance(raw, dict) else {}
    seen = entry.get("seen_push_idens")
    if not isinstance(seen, list):
        seen = []
    entry["seen_push_idens"] = [str(item) for item in seen if str(item or "").strip()]
    entry["modified_after"] = max(float(entry.get("modified_after") or 0.0), 0.0)
    return entry


def _push_pair_matches(push: Mapping[str, object], *, source_email: str, target_email: str) -> bool:
    sender = _email_identity(push.get("sender_email_normalized") or push.get("sender_email") or "")
    receiver = _email_identity(push.get("receiver_email_normalized") or push.get("receiver_email") or "")
    pair = {_email_identity(source_email), _email_identity(target_email)}
    return bool(sender and receiver and {sender, receiver} == pair)


def _matches_filter(push: Mapping[str, object], filter_mode: str) -> bool:
    normalized = str(filter_mode or "").strip().lower()
    if normalized == "all":
        return True
    text = "\n".join(
        [
            str(push.get("title") or "").strip(),
            str(push.get("body") or "").strip(),
        ]
    ).strip()
    if normalized == "paypal_code":
        return bool(_PAYPAL_RE.search(text) and (_PAYPAL_CODE_RE.search(text) or _NUMERIC_CODE_RE.search(text)))
    return False


def _relay_title_body(push: Mapping[str, object]) -> tuple[str, str, str]:
    push_type = str(push.get("type") or "note").strip().lower()
    title = str(push.get("title") or "").strip()
    body = str(push.get("body") or "").strip()
    url = str(push.get("url") or "").strip()
    if push_type == "list":
        items = []
        for item in list(push.get("items") or []):
            if isinstance(item, dict):
                text = str(item.get("text") or "").strip()
                if text:
                    items.append(f"- {text}")
        body = body or "\n".join(items)
    elif push_type == "file":
        file_name = str(push.get("file_name") or "").strip()
        file_url = str(push.get("file_url") or "").strip()
        if not title and file_name:
            title = file_name
        extras = [part for part in (body, file_url) if part]
        body = "\n\n".join(extras)
    if not title:
        title = "Pushbullet message"
    if not body and url:
        body = url
    return title, body, url if push_type == "link" and url else ""


def run_pushbullet_relay_once(
    *,
    state_path: str | Path = "",
    env: Mapping[str, str] | None = None,
    opener=None,
    timeout: float = 20.0,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    values = _env_mapping(env)
    now = _utc_now(observed_at)
    resolved_state_path = _state_path(values, state_path=state_path)
    state = _load_state(resolved_state_path)
    rules_state = dict(state.get("rules") or {})
    rule_rows: list[dict[str, object]] = []
    forwarded_total = 0
    inspected_total = 0
    matched_total = 0
    skipped_total = 0
    blocked_rule_count = 0
    primed_rule_count = 0
    errors = 0
    source_probe_cache: dict[str, dict[str, object]] = {}

    for rule in _relay_rules(values):
        source_client = pushbullet_client_by_key(rule.source_client_key, values)
        target_client = pushbullet_client_by_key(rule.target_client_key, values)
        source_email = pushbullet_client_email(rule.source_client_key, values)
        target_email = pushbullet_client_email(rule.target_client_key, values)
        row = {
            "key": rule.key,
            "source_client_key": rule.source_client_key,
            "target_client_key": rule.target_client_key,
            "filter_mode": rule.filter_mode,
            "forwarded": 0,
            "inspected": 0,
            "matched": 0,
            "skipped": 0,
            "blocked": False,
            "blocked_reason": "",
            "primed": False,
        }
        existing_entry = rules_state.get(rule.key)
        if not isinstance(existing_entry, dict):
            rules_state[rule.key] = {
                "modified_after": now.timestamp(),
                "seen_push_idens": [],
                "updated_at": now.isoformat().replace("+00:00", "Z"),
            }
            row["primed"] = True
            primed_rule_count += 1
            rule_rows.append(row)
            continue
        entry = _rule_state_entry(existing_entry)
        if source_client is None:
            row["blocked"] = True
            row["blocked_reason"] = f"pushbullet_client_missing:{rule.source_client_key}"
            blocked_rule_count += 1
            rule_rows.append(row)
            continue
        if target_client is None:
            row["blocked"] = True
            row["blocked_reason"] = f"pushbullet_client_missing:{rule.target_client_key}"
            blocked_rule_count += 1
            rule_rows.append(row)
            continue
        if not source_email:
            row["blocked"] = True
            row["blocked_reason"] = f"pushbullet_email_missing:{rule.source_client_key}"
            blocked_rule_count += 1
            rule_rows.append(row)
            continue
        if not target_email:
            row["blocked"] = True
            row["blocked_reason"] = f"pushbullet_email_missing:{rule.target_client_key}"
            blocked_rule_count += 1
            rule_rows.append(row)
            continue
        source_probe = source_probe_cache.get(rule.source_client_key)
        if source_probe is None:
            source_probe = probe_pushbullet_client(
                rule.source_client_key,
                env=values,
                opener=opener,
                timeout=timeout,
            )
            source_probe_cache[rule.source_client_key] = source_probe
        source_probe_status = str(source_probe.get("status") or "").strip().lower()
        if source_probe_status != "pass":
            reason = str(source_probe.get("reason") or "pushbullet_source_probe_failed").strip() or "pushbullet_source_probe_failed"
            row["blocked"] = True
            row["blocked_reason"] = f"pushbullet_source_probe_failed:{rule.source_client_key}:{reason}"
            blocked_rule_count += 1
            errors += 1
            rule_rows.append(row)
            continue
        try:
            pushes = list_pushbullet_pushes(
                rule.source_client_key,
                modified_after=float(entry.get("modified_after") or 0.0),
                env=values,
                opener=opener,
                timeout=timeout,
            )
        except RuntimeError as exc:
            row["blocked"] = True
            row["blocked_reason"] = str(exc or "pushbullet_relay_source_failed")
            blocked_rule_count += 1
            errors += 1
            rule_rows.append(row)
            continue

        seen_push_idens = [str(item) for item in list(entry.get("seen_push_idens") or []) if str(item or "").strip()]
        seen_push_iden_set = set(seen_push_idens)
        modified_after = max(float(entry.get("modified_after") or 0.0), 0.0)
        for push in pushes:
            push_iden = str(push.get("iden") or "").strip()
            if not push_iden:
                continue
            modified_after = max(modified_after, float(push.get("modified") or 0.0))
            if push_iden in seen_push_iden_set:
                continue
            seen_push_idens.append(push_iden)
            seen_push_iden_set.add(push_iden)
            row["inspected"] = int(row["inspected"]) + 1
            inspected_total += 1
            if _push_pair_matches(push, source_email=source_email, target_email=target_email):
                row["skipped"] = int(row["skipped"]) + 1
                skipped_total += 1
                continue
            if not _matches_filter(push, rule.filter_mode):
                row["skipped"] = int(row["skipped"]) + 1
                skipped_total += 1
                continue
            row["matched"] = int(row["matched"]) + 1
            matched_total += 1
            title, body, url = _relay_title_body(push)
            try:
                send_pushbullet_note(
                    client_key=rule.source_client_key,
                    title=title,
                    body=body,
                    url=url,
                    target_email=target_email,
                    env=values,
                    opener=opener,
                    timeout=timeout,
                )
            except RuntimeError:
                row["blocked"] = True
                row["blocked_reason"] = "pushbullet_relay_send_failed"
                blocked_rule_count += 1
                errors += 1
                break
            row["forwarded"] = int(row["forwarded"]) + 1
            forwarded_total += 1

        rules_state[rule.key] = {
            "modified_after": modified_after,
            "seen_push_idens": seen_push_idens[-500:],
            "updated_at": now.isoformat().replace("+00:00", "Z"),
        }
        rule_rows.append(row)

    state["version"] = 1
    state["updated_at"] = now.isoformat().replace("+00:00", "Z")
    state["rules"] = rules_state
    _save_state(resolved_state_path, state)
    return {
        "ran": True,
        "state_path": str(resolved_state_path),
        "forwarded_total": forwarded_total,
        "inspected_total": inspected_total,
        "matched_total": matched_total,
        "skipped_total": skipped_total,
        "blocked_rule_count": blocked_rule_count,
        "primed_rule_count": primed_rule_count,
        "errors": errors,
        "rules": rule_rows,
    }
