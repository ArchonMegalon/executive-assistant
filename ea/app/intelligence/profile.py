from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable


@dataclass(frozen=True)
class StableProfile:
    tone: str = "concise"
    urgency_tolerance: str = "normal"
    noise_suppression_mode: str = "aggressive"
    spending_sensitivity: str = "high"
    quiet_hours: str = ""


@dataclass(frozen=True)
class SituationalProfile:
    timestamp_utc: datetime
    mode: str = "standard"
    timezone: str = "UTC"
    location_hint: str = ""


@dataclass(frozen=True)
class LearnedProfile:
    preferred_sources: tuple[str, ...] = field(default_factory=tuple)
    sticky_dislikes: tuple[str, ...] = field(default_factory=tuple)
    top_domains: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ConfidenceProfile:
    state: str = "healthy"  # healthy | degraded
    score: float = 1.0
    note: str = ""


@dataclass(frozen=True)
class PersonProfileContext:
    tenant: str
    person_id: str
    stable: StableProfile
    situational: SituationalProfile
    learned: LearnedProfile
    confidence: ConfidenceProfile


def _safe_json_obj(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    if isinstance(raw, str):
        txt = raw.strip()
        if not txt:
            return {}
        try:
            parsed = json.loads(txt)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _safe_json_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if raw is None:
        return []
    if isinstance(raw, str):
        txt = raw.strip()
        if not txt:
            return []
        try:
            parsed = json.loads(txt)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _as_str_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        item = str(v or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return tuple(out)


def _coerce_float(value: Any, default: float) -> float:
    try:
        f = float(value)
    except Exception:
        return float(default)
    return max(0.0, min(1.0, f))


def _normalize_confidence_state(value: str) -> str:
    v = str(value or "").strip().lower()
    return "degraded" if v in {"degraded", "low", "warn", "warning"} else "healthy"


def _load_profile_state(tenant: str, person_id: str) -> dict[str, dict[str, Any]]:
    """
    Best-effort persisted profile load.
    Falls back to empty dicts if DB or table is unavailable.
    """
    try:
        from app.db import get_db

        db = get_db()
        row = db.fetchone(
            """
            SELECT stable_json, situational_json, learned_json, confidence_json
            FROM profile_context_state
            WHERE tenant = %s AND person_id = %s
            """,
            (str(tenant or ""), str(person_id or "")),
        )
        if not isinstance(row, dict):
            return {"stable": {}, "situational": {}, "learned": {}, "confidence": {}}
        return {
            "stable": _safe_json_obj(row.get("stable_json")),
            "situational": _safe_json_obj(row.get("situational_json")),
            "learned": _safe_json_obj(row.get("learned_json")),
            "confidence": _safe_json_obj(row.get("confidence_json")),
        }
    except Exception:
        return {"stable": {}, "situational": {}, "learned": {}, "confidence": {}}


def _load_interest_profile(tenant: str, person_id: str) -> dict[str, tuple[str, ...]]:
    """
    Derive learned preferences from v1.17 personalization weights.
    """
    preferred_sources: list[str] = []
    sticky_dislikes: list[str] = []
    top_domains: list[str] = []
    try:
        from app.db import get_db

        db = get_db()
        rows = db.fetchall(
            """
            SELECT concept_key, weight, hard_dislike
            FROM user_interest_profiles
            WHERE tenant_key = %s AND principal_id = %s
            ORDER BY updated_at DESC
            LIMIT 128
            """,
            (str(tenant or ""), str(person_id or "")),
        ) or []
    except Exception:
        rows = []

    weighted_sources: list[tuple[float, str]] = []
    weighted_domains: list[tuple[float, str]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        concept = str(r.get("concept_key") or "").strip()
        if not concept:
            continue
        try:
            weight = float(r.get("weight") or 0.0)
        except Exception:
            weight = 0.0
        hard_dislike = bool(r.get("hard_dislike"))
        clean_concept = concept.split(":", 1)[1].strip() if ":" in concept else concept
        if hard_dislike or weight <= -0.75:
            sticky_dislikes.append(clean_concept)
        if weight <= 0:
            continue
        if concept.startswith("source:"):
            weighted_sources.append((weight, clean_concept))
        elif concept.startswith("domain:"):
            weighted_domains.append((weight, clean_concept))
        else:
            weighted_domains.append((weight, clean_concept))

    weighted_sources.sort(key=lambda x: x[0], reverse=True)
    weighted_domains.sort(key=lambda x: x[0], reverse=True)
    preferred_sources.extend([name for _, name in weighted_sources[:8]])
    top_domains.extend([name for _, name in weighted_domains[:8]])
    return {
        "preferred_sources": _as_str_tuple(preferred_sources),
        "sticky_dislikes": _as_str_tuple(sticky_dislikes),
        "top_domains": _as_str_tuple(top_domains),
    }


def _merge_string_tuples(*parts: Iterable[str]) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for raw in part:
            v = str(raw or "").strip()
            if not v or v in seen:
                continue
            seen.add(v)
            merged.append(v)
    return tuple(merged)


def build_profile_context(
    *,
    tenant: str,
    person_id: str,
    timezone_name: str = "UTC",
    runtime_confidence_note: str | None = None,
    mode: str | None = None,
    location_hint: str | None = None,
) -> PersonProfileContext:
    persisted = _load_profile_state(tenant=str(tenant or ""), person_id=str(person_id or ""))
    stable_seed = persisted.get("stable") or {}
    situational_seed = persisted.get("situational") or {}
    learned_seed = persisted.get("learned") or {}
    confidence_seed = persisted.get("confidence") or {}

    stable = StableProfile(
        tone=str(stable_seed.get("tone") or "concise"),
        urgency_tolerance=str(stable_seed.get("urgency_tolerance") or "normal"),
        noise_suppression_mode=str(stable_seed.get("noise_suppression_mode") or "aggressive"),
        spending_sensitivity=str(stable_seed.get("spending_sensitivity") or "high"),
        quiet_hours=str(stable_seed.get("quiet_hours") or ""),
    )

    derived = _load_interest_profile(tenant=str(tenant or ""), person_id=str(person_id or ""))
    learned = LearnedProfile(
        preferred_sources=_merge_string_tuples(
            _safe_json_list(learned_seed.get("preferred_sources")),
            derived.get("preferred_sources", ()),
        ),
        sticky_dislikes=_merge_string_tuples(
            _safe_json_list(learned_seed.get("sticky_dislikes")),
            derived.get("sticky_dislikes", ()),
        ),
        top_domains=_merge_string_tuples(
            _safe_json_list(learned_seed.get("top_domains")),
            derived.get("top_domains", ()),
        ),
    )

    runtime_note = str(runtime_confidence_note or "").strip()
    persisted_state = _normalize_confidence_state(str(confidence_seed.get("state") or "healthy"))
    persisted_score = _coerce_float(confidence_seed.get("score"), 0.98)
    persisted_note = str(confidence_seed.get("note") or "").strip()
    degraded = bool(runtime_note)
    confidence = ConfidenceProfile(
        state="degraded" if degraded else persisted_state,
        score=min(persisted_score, 0.55) if degraded else persisted_score,
        note=runtime_note if degraded else persisted_note,
    )

    effective_mode = str(mode or situational_seed.get("mode") or "standard")
    effective_tz = str(timezone_name or situational_seed.get("timezone") or "UTC")
    effective_location = str(location_hint if location_hint is not None else situational_seed.get("location_hint") or "")
    situational = SituationalProfile(
        timestamp_utc=datetime.now(timezone.utc),
        mode=effective_mode,
        timezone=effective_tz,
        location_hint=effective_location,
    )
    return PersonProfileContext(
        tenant=str(tenant or ""),
        person_id=str(person_id or ""),
        stable=stable,
        situational=situational,
        learned=learned,
        confidence=confidence,
    )


def save_profile_context(
    *,
    tenant: str,
    person_id: str,
    stable: dict[str, Any] | None = None,
    situational: dict[str, Any] | None = None,
    learned: dict[str, Any] | None = None,
    confidence: dict[str, Any] | None = None,
) -> bool:
    """
    Persist profile layer snapshots for later compose cycles.
    Returns True on success and False on best-effort skip/failure.
    """
    try:
        from app.db import get_db

        db = get_db()
        db.execute(
            """
            INSERT INTO profile_context_state
                (tenant, person_id, stable_json, situational_json, learned_json, confidence_json)
            VALUES
                (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)
            ON CONFLICT (tenant, person_id)
            DO UPDATE SET
                stable_json = EXCLUDED.stable_json,
                situational_json = EXCLUDED.situational_json,
                learned_json = EXCLUDED.learned_json,
                confidence_json = EXCLUDED.confidence_json,
                updated_at = NOW()
            """,
            (
                str(tenant or ""),
                str(person_id or ""),
                json.dumps(_safe_json_obj(stable), ensure_ascii=False),
                json.dumps(_safe_json_obj(situational), ensure_ascii=False),
                json.dumps(_safe_json_obj(learned), ensure_ascii=False),
                json.dumps(_safe_json_obj(confidence), ensure_ascii=False),
            ),
        )
        return True
    except Exception:
        return False
