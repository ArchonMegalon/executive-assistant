from __future__ import annotations

import copy
import logging
from typing import Any

from app.repositories.preference_profiles import InMemoryPreferenceProfileRepository, PreferenceProfileRepository
from app.repositories.preference_profiles_postgres import PostgresPreferenceProfileRepository
from app.settings import Settings, ensure_storage_fallback_allowed


def _backend_mode(settings: Settings) -> str:
    return str(getattr(getattr(settings, "storage", None), "backend", "") or "auto").strip().lower() or "auto"


def build_preference_profile_repo(settings: Settings) -> PreferenceProfileRepository:
    backend = _backend_mode(settings)
    log = logging.getLogger("ea.preference_profiles")
    if backend == "memory":
        ensure_storage_fallback_allowed(settings, "preference profiles configured for memory")
        return InMemoryPreferenceProfileRepository()
    if backend == "postgres":
        if not settings.database_url:
            raise RuntimeError("EA_STORAGE_BACKEND=postgres requires DATABASE_URL")
        return PostgresPreferenceProfileRepository(settings.database_url)
    if settings.database_url:
        try:
            return PostgresPreferenceProfileRepository(settings.database_url)
        except Exception as exc:
            ensure_storage_fallback_allowed(settings, "preference profiles auto fallback", exc)
            log.warning("postgres preference-profile backend unavailable in auto mode; falling back to memory: %s", exc)
    ensure_storage_fallback_allowed(settings, "preference profiles auto backend without DATABASE_URL")
    return InMemoryPreferenceProfileRepository()


def build_preference_profile_service(settings: Settings) -> "PreferenceProfileService":
    return PreferenceProfileService(repo=build_preference_profile_repo(settings))


def _compact_text(value: object, *, fallback: str = "", limit: int = 160) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return fallback
    if len(text) <= limit:
        return text
    return f"{text[: max(limit - 3, 0)]}..."


def _normalize_strength(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"low", "medium", "high"}:
        return raw
    return "medium"


def _strength_weight(value: str) -> float:
    return {"low": 0.7, "medium": 1.5, "high": 2.5}.get(_normalize_strength(value), 1.5)


def _normalize_confidence(value: object, *, default: float = 0.5) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return max(0.0, min(1.0, out))


def _normalize_key(value: object) -> str:
    return str(value or "").strip().lower()


def _list_value(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    if isinstance(value, tuple):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


class PreferenceProfileService:
    def __init__(self, *, repo: PreferenceProfileRepository) -> None:
        self._repo = repo

    def ensure_profile(
        self,
        *,
        principal_id: str,
        person_id: str = "self",
        display_name: str | None = None,
        profile_scope: str | None = None,
        consent_mode: str | None = None,
        learning_enabled: bool | None = None,
        high_stakes_domains_enabled: bool | None = None,
    ) -> dict[str, object]:
        return self._repo.ensure_person_profile(
            principal_id=principal_id,
            person_id=person_id,
            display_name=display_name,
            profile_scope=profile_scope,
            consent_mode=consent_mode,
            learning_enabled=learning_enabled,
            high_stakes_domains_enabled=high_stakes_domains_enabled,
        )

    def get_profile_bundle(self, *, principal_id: str, person_id: str = "self") -> dict[str, object]:
        profile = self._repo.get_person_profile(principal_id=principal_id, person_id=person_id)
        if profile is None:
            profile = self.ensure_profile(principal_id=principal_id, person_id=person_id)
        return {
            "profile": copy.deepcopy(profile),
            "preference_nodes": self._repo.list_preference_nodes(principal_id=principal_id, person_id=person_id, limit=300),
            "recent_evidence_events": self._repo.list_evidence_events(principal_id=principal_id, person_id=person_id, limit=50),
            "recent_decision_assessments": self._repo.list_decision_assessments(principal_id=principal_id, person_id=person_id, limit=25),
            "recent_corrections": self._repo.list_profile_corrections(principal_id=principal_id, person_id=person_id, limit=25),
        }

    def upsert_preference_node(
        self,
        *,
        principal_id: str,
        person_id: str = "self",
        domain: str,
        category: str,
        key: str,
        value_json: object,
        strength: str = "medium",
        confidence: float = 0.5,
        source_mode: str = "explicit",
        status: str = "active",
        decay_policy: str = "reinforce_only",
        last_confirmed_at: str = "",
        last_observed_at: str = "",
        node_id: str | None = None,
    ) -> dict[str, object]:
        self.ensure_profile(principal_id=principal_id, person_id=person_id)
        return self._repo.upsert_preference_node(
            principal_id=principal_id,
            person_id=person_id,
            domain=domain,
            category=category,
            key=key,
            value_json=value_json,
            strength=strength,
            confidence=confidence,
            source_mode=source_mode,
            status=status,
            decay_policy=decay_policy,
            last_confirmed_at=last_confirmed_at,
            last_observed_at=last_observed_at,
            node_id=node_id,
        )

    def apply_correction(
        self,
        *,
        principal_id: str,
        person_id: str = "self",
        domain: str,
        category: str,
        key: str,
        value_json: object,
        strength: str = "high",
        reason: str = "",
        corrected_by: str = "",
    ) -> dict[str, object]:
        existing = next(
            (
                row
                for row in self._repo.list_preference_nodes(
                    principal_id=principal_id,
                    person_id=person_id,
                    domain=domain,
                    category=category,
                    limit=200,
                )
                if _normalize_key(row.get("key")) == _normalize_key(key)
            ),
            None,
        )
        updated = self.upsert_preference_node(
            principal_id=principal_id,
            person_id=person_id,
            domain=domain,
            category=category,
            key=key,
            value_json=value_json,
            strength=strength,
            confidence=1.0,
            source_mode="explicit_correction",
            status="active",
            decay_policy="manual_only",
            last_confirmed_at=existing.get("updated_at", "") if isinstance(existing, dict) else "",
        )
        correction = self._repo.record_profile_correction(
            principal_id=principal_id,
            person_id=person_id,
            target_type="preference_node",
            target_id=str(updated.get("node_id") or ""),
            old_value_json=dict(existing or {}) if isinstance(existing, dict) else {},
            new_value_json=dict(updated or {}),
            reason=reason,
            corrected_by=corrected_by,
        )
        return {
            "node": updated,
            "correction": correction,
        }

    def record_evidence_event(
        self,
        *,
        principal_id: str,
        person_id: str = "self",
        domain: str,
        event_type: str,
        object_type: str,
        object_id: str,
        source_ref: str = "",
        raw_signal_json: dict[str, object] | None = None,
        interpreted_signal_json: dict[str, object] | None = None,
        signal_strength: float = 0.5,
        reversible: bool = True,
    ) -> dict[str, object]:
        self.ensure_profile(principal_id=principal_id, person_id=person_id)
        event = self._repo.record_evidence_event(
            principal_id=principal_id,
            person_id=person_id,
            domain=domain,
            event_type=event_type,
            object_type=object_type,
            object_id=object_id,
            source_ref=source_ref,
            raw_signal_json=raw_signal_json or {},
            interpreted_signal_json=interpreted_signal_json or {},
            signal_strength=signal_strength,
            reversible=reversible,
        )
        applied_nodes = self._apply_inference_from_event(
            principal_id=principal_id,
            person_id=person_id,
            event=event,
        )
        return {
            "event": event,
            "applied_nodes": applied_nodes,
        }

    def assess_candidate(
        self,
        *,
        principal_id: str,
        person_id: str = "self",
        domain: str,
        object_type: str,
        object_id: str,
        object_payload: dict[str, object],
        persist: bool = True,
        require_existing_profile: bool = False,
    ) -> dict[str, object] | None:
        profile = self._repo.get_person_profile(principal_id=principal_id, person_id=person_id)
        if profile is None:
            if require_existing_profile:
                return None
            profile = self.ensure_profile(principal_id=principal_id, person_id=person_id)
        nodes = self._repo.list_preference_nodes(principal_id=principal_id, person_id=person_id, domain=domain, limit=300)
        if not nodes and require_existing_profile:
            return None
        if str(domain or "").strip().lower() == "willhaben":
            assessment = self._assess_willhaben(
                object_id=object_id,
                object_payload=object_payload,
                nodes=nodes,
            )
        else:
            assessment = self._assess_generic(
                object_id=object_id,
                object_payload=object_payload,
                nodes=nodes,
            )
        if persist:
            stored = self._repo.record_decision_assessment(
                principal_id=principal_id,
                person_id=person_id,
                domain=domain,
                object_type=object_type,
                object_id=object_id,
                fit_score=float(assessment["fit_score"]),
                confidence=float(assessment["confidence"]),
                predicted_reaction=str(assessment["predicted_reaction"]),
                recommendation=str(assessment["recommendation"]),
                match_reasons_json=list(assessment.get("match_reasons_json") or []),
                mismatch_reasons_json=list(assessment.get("mismatch_reasons_json") or []),
                unknowns_json=list(assessment.get("unknowns_json") or []),
                blocking_constraints_json=list(assessment.get("blocking_constraints_json") or []),
                assessment_json=assessment,
            )
            return stored
        return assessment

    def build_teable_projection_records(self, *, principal_id: str, person_id: str = "self") -> dict[str, list[dict[str, object]]]:
        bundle = self.get_profile_bundle(principal_id=principal_id, person_id=person_id)
        profile = dict(bundle.get("profile") or {})
        return {
            "preference_review_queue": [
                {
                    "projection_id": str(row.get("node_id") or ""),
                    "person_id": str(row.get("person_id") or ""),
                    "display_name": str(profile.get("display_name") or person_id),
                    "domain": str(row.get("domain") or ""),
                    "category": str(row.get("category") or ""),
                    "key": str(row.get("key") or ""),
                    "confidence": float(row.get("confidence") or 0.0),
                    "source_mode": str(row.get("source_mode") or ""),
                    "status": str(row.get("status") or ""),
                    "target_ref": f"preference_node:{row.get('node_id')}",
                    "projection_version": str(row.get("updated_at") or ""),
                    "editable_fields_allowlist": ["value_json", "strength", "status"],
                    "evidence_ref_count": self._node_evidence_count(bundle=bundle, node=row),
                    "last_updated_at": str(row.get("updated_at") or ""),
                    "expiry_at": "",
                    "correlation_id": f"{principal_id}:{person_id}:{row.get('node_id')}",
                }
                for row in list(bundle.get("preference_nodes") or [])[:50]
            ],
            "preference_recent_assessments": [
                {
                    "projection_id": str(row.get("assessment_id") or ""),
                    "person_id": str(row.get("person_id") or ""),
                    "display_name": str(profile.get("display_name") or person_id),
                    "domain": str(row.get("domain") or ""),
                    "object_type": str(row.get("object_type") or ""),
                    "object_id": str(row.get("object_id") or ""),
                    "fit_score": float(row.get("fit_score") or 0.0),
                    "confidence": float(row.get("confidence") or 0.0),
                    "recommendation": str(row.get("recommendation") or ""),
                    "predicted_reaction": str(row.get("predicted_reaction") or ""),
                    "updated_at": str(row.get("generated_at") or ""),
                    "correlation_id": f"{principal_id}:{person_id}:{row.get('assessment_id')}",
                }
                for row in list(bundle.get("recent_decision_assessments") or [])[:50]
            ],
        }

    def _node_evidence_count(self, *, bundle: dict[str, object], node: dict[str, object]) -> int:
        key = _normalize_key(node.get("key"))
        domain = _normalize_key(node.get("domain"))
        count = 0
        for row in list(bundle.get("recent_evidence_events") or []):
            if _normalize_key(row.get("domain")) != domain:
                continue
            interpreted = dict(row.get("interpreted_signal_json") or {})
            for hint in list(interpreted.get("preference_hints") or []):
                if _normalize_key(dict(hint).get("key")) == key:
                    count += 1
        return count

    def _apply_inference_from_event(
        self,
        *,
        principal_id: str,
        person_id: str,
        event: dict[str, object],
    ) -> list[dict[str, object]]:
        profile = self._repo.get_person_profile(principal_id=principal_id, person_id=person_id)
        if profile is None:
            return []
        consent_mode = str(profile.get("consent_mode") or "").strip().lower()
        learning_enabled = bool(profile.get("learning_enabled"))
        interpreted = dict(event.get("interpreted_signal_json") or {})
        if consent_mode == "paused":
            return []
        if consent_mode == "explicit_only" and not interpreted.get("preference_hints"):
            return []
        if consent_mode != "explicit_only" and not learning_enabled and not interpreted.get("preference_hints"):
            return []
        applied: list[dict[str, object]] = []
        for hint in list(interpreted.get("preference_hints") or []):
            if not isinstance(hint, dict):
                continue
            applied_row = self._apply_preference_hint(
                principal_id=principal_id,
                person_id=person_id,
                hint=hint,
                event=event,
            )
            if applied_row:
                applied.append(applied_row)
        if interpreted.get("preference_hints"):
            return applied
        inferred = self._infer_hints_from_event(event)
        for hint in inferred:
            applied_row = self._apply_preference_hint(
                principal_id=principal_id,
                person_id=person_id,
                hint=hint,
                event=event,
            )
            if applied_row:
                applied.append(applied_row)
        return applied

    def _apply_preference_hint(
        self,
        *,
        principal_id: str,
        person_id: str,
        hint: dict[str, object],
        event: dict[str, object],
    ) -> dict[str, object] | None:
        domain = str(hint.get("domain") or event.get("domain") or "general").strip().lower()
        category = str(hint.get("category") or "").strip().lower()
        key = str(hint.get("key") or "").strip().lower()
        if not domain or not category or not key:
            return None
        value_json = copy.deepcopy(hint.get("value_json"))
        merge_mode = str(hint.get("merge_mode") or "replace").strip().lower()
        existing = next(
            (
                row
                for row in self._repo.list_preference_nodes(
                    principal_id=principal_id,
                    person_id=person_id,
                    domain=domain,
                    category=category,
                    limit=50,
                )
                if _normalize_key(row.get("key")) == key
            ),
            None,
        )
        if merge_mode == "append_unique":
            values = []
            if isinstance(existing, dict):
                values.extend(_list_value(existing.get("value_json")))
            values.extend(_list_value(value_json))
            deduped: list[str] = []
            seen: set[str] = set()
            for item in values:
                normalized = _normalize_key(item)
                if normalized and normalized not in seen:
                    deduped.append(item)
                    seen.add(normalized)
            value_json = deduped
        confidence = max(
            _normalize_confidence(hint.get("confidence"), default=0.55),
            _normalize_confidence(event.get("signal_strength"), default=0.5),
        )
        return self.upsert_preference_node(
            principal_id=principal_id,
            person_id=person_id,
            domain=domain,
            category=category,
            key=key,
            value_json=value_json,
            strength=str(hint.get("strength") or "medium"),
            confidence=confidence,
            source_mode=str(hint.get("source_mode") or "behavioral_inference"),
            status=str(hint.get("status") or "active"),
            decay_policy=str(hint.get("decay_policy") or "reinforce_only"),
            last_observed_at=str(event.get("recorded_at") or ""),
            node_id=str((existing or {}).get("node_id") or "") or None,
        )

    def _infer_hints_from_event(self, event: dict[str, object]) -> list[dict[str, object]]:
        domain = _normalize_key(event.get("domain"))
        event_type = _normalize_key(event.get("event_type"))
        raw = dict(event.get("raw_signal_json") or {})
        hints: list[dict[str, object]] = []
        district = str(raw.get("district") or raw.get("postal_name") or raw.get("location") or "").strip()
        heating = str(raw.get("heating") or raw.get("heating_type") or "").strip()
        if domain == "willhaben" and event_type in {"listing_shortlisted", "listing_saved", "listing_accepted"}:
            if district:
                hints.append(
                    {
                        "domain": "willhaben",
                        "category": "soft_preference",
                        "key": "preferred_districts",
                        "value_json": [district],
                        "strength": "medium",
                        "merge_mode": "append_unique",
                    }
                )
            if bool(raw.get("has_floorplan")):
                hints.append(
                    {
                        "domain": "willhaben",
                        "category": "soft_preference",
                        "key": "requires_floorplan_for_remote_review",
                        "value_json": True,
                        "strength": "medium",
                    }
                )
        if domain == "willhaben" and event_type in {"listing_rejected", "listing_dismissed"}:
            if heating:
                hints.append(
                    {
                        "domain": "willhaben",
                        "category": "aversion",
                        "key": "avoid_heating_types",
                        "value_json": [heating],
                        "strength": "medium",
                        "merge_mode": "append_unique",
                    }
                )
        return hints

    def _assess_generic(self, *, object_id: str, object_payload: dict[str, object], nodes: list[dict[str, object]]) -> dict[str, object]:
        del object_id, object_payload
        confidence = 0.2 if nodes else 0.0
        recommendation = "ask_for_clarification" if nodes else "mention"
        return {
            "domain": "general",
            "object_type": "candidate",
            "object_id": "",
            "fit_score": 50.0,
            "confidence": confidence,
            "predicted_reaction": "consider",
            "recommendation": recommendation,
            "match_reasons_json": [],
            "mismatch_reasons_json": [],
            "unknowns_json": ["No domain-specific scoring model is configured yet for this candidate type."],
            "blocking_constraints_json": [],
        }

    def _assess_willhaben(
        self,
        *,
        object_id: str,
        object_payload: dict[str, object],
        nodes: list[dict[str, object]],
    ) -> dict[str, object]:
        facts = dict(object_payload or {})
        attributes = dict(facts.get("attribute_map") or {})
        district = str(facts.get("postal_name") or facts.get("district") or facts.get("location") or "").strip()
        total_rent = facts.get("total_rent_eur")
        rooms = facts.get("rooms")
        area_sqm = facts.get("area_sqm")
        heating = str(facts.get("heating") or attributes.get("HEIZUNGSART") or attributes.get("HEATING_TYPE") or "").strip()
        has_floorplan = bool(facts.get("floorplan_count") or facts.get("has_floorplan") or facts.get("floorplan_urls_json"))
        has_360 = str(facts.get("tour_media_mode") or "").strip().lower() == "panorama_360" or bool(facts.get("source_virtual_tour_url"))
        has_balcony = "balkon" in _normalize_key(facts.get("headline_hook")) or "balkon" in _normalize_key(attributes.get("GENERAL_TEXT_ADVERT/Ausstattung"))
        has_lift = "lift" in _normalize_key(facts.get("headline_hook")) or "lift" in _normalize_key(attributes.get("GENERAL_TEXT_ADVERT/Ausstattung"))
        score = 50.0
        match_reasons: list[str] = []
        mismatch_reasons: list[str] = []
        unknowns: list[str] = list(dict(facts.get("decision_summary") or {}).get("unknowns") or [])
        blocking_constraints: list[str] = []

        for node in nodes:
            category = _normalize_key(node.get("category"))
            key = _normalize_key(node.get("key"))
            value = node.get("value_json")
            weight = _strength_weight(str(node.get("strength") or "medium")) * max(float(node.get("confidence") or 0.5), 0.3)

            if category == "constraint" and key == "max_total_rent_eur" and isinstance(total_rent, (int, float)):
                try:
                    ceiling = float(value)
                except Exception:
                    ceiling = None
                if ceiling is not None and total_rent > ceiling:
                    blocking_constraints.append(f"Total monthly burden exceeds the preferred ceiling of EUR {ceiling:g}.")
                    score -= 20.0
            elif category == "constraint" and key == "min_rooms" and isinstance(rooms, (int, float)):
                try:
                    minimum_rooms = float(value)
                except Exception:
                    minimum_rooms = None
                if minimum_rooms is not None and rooms < minimum_rooms:
                    blocking_constraints.append(f"Room count is below the required minimum of {minimum_rooms:g}.")
                    score -= 20.0
            elif category == "constraint" and key == "min_area_sqm" and isinstance(area_sqm, (int, float)):
                try:
                    minimum_area = float(value)
                except Exception:
                    minimum_area = None
                if minimum_area is not None and area_sqm < minimum_area:
                    blocking_constraints.append(f"Living area is below the required minimum of {minimum_area:g} m².")
                    score -= 20.0
            elif category == "constraint" and key == "require_floorplan":
                if bool(value) and not has_floorplan:
                    blocking_constraints.append("A floor plan is required for remote screening, but the listing does not provide one.")
                    score -= 12.0
            elif category == "constraint" and key == "require_360":
                if bool(value) and not has_360:
                    blocking_constraints.append("A live 360 or panorama source is required, but the listing does not provide one.")
                    score -= 18.0
            elif category in {"soft_preference", "aversion"} and key == "preferred_districts":
                preferred = {_normalize_key(item) for item in _list_value(value)}
                if district and _normalize_key(district) in preferred:
                    score += 5.0 * weight
                    match_reasons.append(f"The listing is in {district}, which matches established district preferences.")
            elif category in {"soft_preference", "aversion"} and key == "avoided_districts":
                avoided = {_normalize_key(item) for item in _list_value(value)}
                if district and _normalize_key(district) in avoided:
                    score -= 6.0 * weight
                    mismatch_reasons.append(f"The listing is in {district}, which matches a recorded location aversion.")
            elif category == "aversion" and key == "avoid_heating_types":
                avoided_heating = {_normalize_key(item) for item in _list_value(value)}
                if heating and _normalize_key(heating) in avoided_heating:
                    score -= 8.0 * weight
                    mismatch_reasons.append(f"{heating} matches a recorded heating aversion.")
            elif category == "soft_preference" and key == "requires_floorplan_for_remote_review":
                if bool(value):
                    if has_floorplan:
                        score += 4.0 * weight
                        match_reasons.append("A floor plan is available, which supports the preferred remote review workflow.")
                    else:
                        score -= 4.0 * weight
                        mismatch_reasons.append("No floor plan is available, which conflicts with the preferred remote review workflow.")
            elif category == "soft_preference" and key == "prefer_balcony":
                if bool(value):
                    if has_balcony:
                        score += 3.0 * weight
                        match_reasons.append("The listing appears to include balcony or outdoor value, which matches the stated preference.")
                    else:
                        score -= 2.0 * weight
                        mismatch_reasons.append("The listing does not clearly show balcony or outdoor value.")
            elif category == "soft_preference" and key == "prefer_lift":
                if bool(value):
                    if has_lift:
                        score += 3.0 * weight
                        match_reasons.append("Lift access appears available, which matches the preferred accessibility workflow.")
                    else:
                        score -= 2.0 * weight
                        mismatch_reasons.append("Lift access is not clearly available, which conflicts with the preferred accessibility workflow.")
            elif category == "soft_preference" and key == "prefer_360_for_remote_review":
                if bool(value):
                    if has_360:
                        score += 4.0 * weight
                        match_reasons.append("A live 360 source is available, which matches the preferred remote review workflow.")
                    else:
                        score -= 3.0 * weight
                        mismatch_reasons.append("No live 360 source is available, which conflicts with the preferred remote review workflow.")
            elif category == "constraint" and key == "require_lift":
                if bool(value) and not has_lift:
                    blocking_constraints.append("Lift access is required, but the listing does not clearly provide it.")
                    score -= 10.0

        if has_360:
            score += 4.0
            match_reasons.append("A live 360 source is available, so layout and spatial feel are easier to verify.")
        elif not any("360" in entry.lower() for entry in mismatch_reasons):
            mismatch_reasons.append("The listing does not provide a live 360 source, so remote screening has higher uncertainty.")

        if heating and not any(heating.lower() in entry.lower() for entry in mismatch_reasons):
            unknowns.append(f"Check the operating cost and efficiency implications of {heating}.")
        if not district:
            unknowns.append("The micro-location still needs manual review.")

        confidence = 0.25 if not nodes else min(0.9, 0.35 + min(len(nodes), 8) * 0.07)
        if blocking_constraints:
            recommendation = "reject"
            predicted_reaction = "reject"
        elif score >= 68:
            recommendation = "shortlist"
            predicted_reaction = "shortlist"
        elif score >= 55:
            recommendation = "mention"
            predicted_reaction = "consider"
        elif score >= 45:
            recommendation = "ask_for_clarification"
            predicted_reaction = "mixed"
        else:
            recommendation = "reject"
            predicted_reaction = "reject"

        return {
            "domain": "willhaben",
            "object_type": "listing",
            "object_id": object_id,
            "fit_score": round(max(0.0, min(100.0, score)), 2),
            "confidence": round(confidence, 2),
            "predicted_reaction": predicted_reaction,
            "recommendation": recommendation,
            "match_reasons_json": match_reasons[:6],
            "mismatch_reasons_json": mismatch_reasons[:6],
            "unknowns_json": unknowns[:6],
            "blocking_constraints_json": blocking_constraints[:4],
        }
