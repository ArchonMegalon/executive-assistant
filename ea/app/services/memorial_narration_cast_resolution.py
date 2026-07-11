from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import unicodedata

from app.services.memorial_narration_work_package import (
    RECEIPT_CONTRACT_NAME,
    REQUIRED_NARRATION_SOURCE_SCOPE,
    WORK_PACKAGE_CONTRACT_NAME,
)


CAST_RESOLUTION_CONTRACT_NAME = "ea.memorial_narration_cast_resolution.v1"
CAST_REVIEW_CONTRACT_NAME = "ea.memorial_narration_cast_review.v1"
CAST_VERIFICATION_RECEIPT_CONTRACT_NAME = (
    "ea.memorial_narration_cast_verification_receipt.v1"
)
REQUIRED_REVIEW_SCOPE = "memorial_audiobook_cast_mapping"
MAX_PRIVATE_ARTIFACT_BYTES = 32 * 1024 * 1024
MAX_SIGNING_SECRET_BYTES = 16 * 1024
MAX_MAPPING_REVIEW_TTL = timedelta(days=7)

_APPROVED_STATUSES = frozenset(
    {"approved", "accepted", "selected_by_user", "accepted_by_user"}
)
_DEMOGRAPHIC_TRAIT_KINDS = frozenset(
    {
        "gender_presentation",
        "age_band",
        "cultural_or_ethnic_background",
        "accent",
    }
)
_TRAIT_ALIASES = {
    "gender": "gender_presentation",
    "age": "age_band",
    "age_range": "age_band",
    "approximate_age": "age_band",
    "ethnicity": "cultural_or_ethnic_background",
    "ethnic_background": "cultural_or_ethnic_background",
    "cultural_background": "cultural_or_ethnic_background",
    "cultural_identity": "cultural_or_ethnic_background",
    "dialect": "accent",
    "locale": "language",
}


def _stable_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _stable_json_sha256(value: object) -> str:
    return hashlib.sha256(_stable_json_bytes(value)).hexdigest()


def _text_sha256(value: object) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _normalized_text(value: object) -> str:
    return re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFKC", str(value or "")).strip(),
    )


def _normalized_tag(value: object) -> str:
    raw = unicodedata.normalize("NFKD", _normalized_text(value)).casefold()
    raw = "".join(char for char in raw if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "_", raw).strip("_")


def _canonical_trait_kind(value: object) -> str:
    normalized = _normalized_tag(value)
    return _TRAIT_ALIASES.get(normalized, normalized)


def _canonical_trait_value(kind: str, value: object) -> str:
    normalized = _normalized_tag(value)
    if kind == "gender_presentation":
        return {
            "f": "female",
            "feminine": "female",
            "girl": "female",
            "woman": "female",
            "m": "male",
            "masculine": "male",
            "boy": "male",
            "man": "male",
            "nb": "nonbinary",
            "non_binary": "nonbinary",
            "gender_neutral": "neutral",
        }.get(normalized, normalized)
    if kind == "age_band":
        try:
            years = int(float(str(value).strip()))
        except (TypeError, ValueError):
            years = -1
        if years >= 0:
            if years < 13:
                return "child"
            if years < 20:
                return "teen"
            if years < 35:
                return "young_adult"
            if years < 55:
                return "adult"
            if years < 70:
                return "mature"
            return "senior"
        return {
            "kid": "child",
            "young": "young_adult",
            "youngadult": "young_adult",
            "middle_age": "mature",
            "middle_aged": "mature",
            "older": "senior",
            "older_adult": "senior",
            "older_adults": "senior",
            "elderly": "senior",
            "old": "senior",
        }.get(normalized, normalized)
    if kind == "language":
        return _normalized_text(value).replace("_", "-").casefold()
    return normalized


def _language_compatible(required: object, selected: object) -> bool:
    required_value = _canonical_trait_value("language", required)
    selected_value = _canonical_trait_value("language", selected)
    if not required_value or required_value == "und":
        return bool(selected_value)
    if not selected_value:
        return False
    return required_value == selected_value or (
        required_value.split("-", 1)[0] == selected_value.split("-", 1)[0]
    )


def _mapping_value(
    value: Mapping[str, object],
    *keys: str,
) -> str:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, (str, int, float)) and str(candidate).strip():
            return str(candidate).strip()
    return ""


def _nested_mapping(value: Mapping[str, object], *keys: str) -> dict[str, object]:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, Mapping):
            return dict(candidate)
    return {}


def _voice_descriptor(value: Mapping[str, object]) -> dict[str, str]:
    nested = _nested_mapping(value, "tts_plugin", "voice", "provider_voice", "clone")
    provider = _mapping_value(
        value,
        "provider",
        "provider_name",
        "tts_provider",
        "tts_plugin",
        "tts_plugin_name",
        "tts_engine",
        "engine",
        "voice_provider",
        "voice_type",
        "clone_provider",
        "provider_adapter",
    ) or _mapping_value(
        nested,
        "provider",
        "provider_name",
        "name",
        "type",
        "engine",
    )
    voice_id = _mapping_value(
        value,
        "tts_plugin_voice_id",
        "plugin_voice_id",
        "tts_voice_id",
        "provider_voice_id",
        "unmixr_voice_id",
        "voice_id",
        "clone_voice_id",
    ) or _mapping_value(
        nested,
        "voice_id",
        "provider_voice_id",
        "id",
        "uuid",
    )
    language = _mapping_value(
        value,
        "language",
        "lang",
        "locale",
    ) or _mapping_value(nested, "language", "lang", "locale")
    return {
        "provider": provider,
        "voice_id": voice_id,
        "language": language,
    }


def _consent_decision(
    voice_profile: Mapping[str, object],
    *,
    now: datetime,
) -> dict[str, object]:
    raw = voice_profile.get("voice_consent")
    consent = dict(raw) if isinstance(raw, Mapping) else {}
    status = _normalized_tag(consent.get("status"))
    scopes = {
        _normalized_text(item)
        for item in (
            consent.get("scope") if isinstance(consent.get("scope"), list) else []
        )
        if _normalized_text(item)
    }
    expires_at = _parse_datetime(consent.get("expires_at"))
    if consent.get("revoked") is True:
        reason = "voice_consent_revoked"
    elif status != "approved":
        reason = "voice_consent_not_approved"
    elif "synthesize" not in scopes:
        reason = "voice_consent_scope_missing"
    elif str(consent.get("expires_at") or "").strip() and expires_at is None:
        reason = "voice_consent_expiry_invalid"
    elif expires_at is not None and expires_at <= now:
        reason = "voice_consent_expired"
    else:
        reason = ""
    return {
        "authorized": not reason,
        "reason": reason,
        "status": status or "missing",
        "revoked": consent.get("revoked") is True,
        "required_scope": "synthesize",
        "required_scope_present": "synthesize" in scopes,
        "expires_at": (
            expires_at.isoformat().replace("+00:00", "Z") if expires_at else ""
        ),
        "evidence_sha256": _stable_json_sha256(consent),
    }


def _work_package_payload(work_package: Mapping[str, object]) -> dict[str, object]:
    return {
        str(key): value
        for key, value in work_package.items()
        if str(key) != "provider_safe_receipt"
    }


def _work_package_bindings(
    work_package: Mapping[str, object],
) -> tuple[dict[str, object], list[str]]:
    issues: list[str] = []
    receipt = (
        dict(work_package.get("provider_safe_receipt") or {})
        if isinstance(work_package.get("provider_safe_receipt"), Mapping)
        else {}
    )
    plan = (
        dict(work_package.get("narration_plan") or {})
        if isinstance(work_package.get("narration_plan"), Mapping)
        else {}
    )
    cast_handoff = (
        dict(work_package.get("cast_handoff") or {})
        if isinstance(work_package.get("cast_handoff"), Mapping)
        else {}
    )
    source_policy = (
        dict(work_package.get("source_policy") or {})
        if isinstance(work_package.get("source_policy"), Mapping)
        else {}
    )
    raw_source_rows = work_package.get("sources")
    source_rows: list[dict[str, object]] = []
    if not isinstance(raw_source_rows, list):
        issues.append("work_package_sources_invalid")
    else:
        for raw_source_row in raw_source_rows:
            if not isinstance(raw_source_row, Mapping):
                issues.append("work_package_source_entry_invalid")
                continue
            source_rows.append(dict(raw_source_row))
    calculated_work_package_sha256 = _stable_json_sha256(
        _work_package_payload(work_package)
    )
    calculated_cast_handoff_sha256 = _stable_json_sha256(cast_handoff)
    if work_package.get("contract_name") != WORK_PACKAGE_CONTRACT_NAME:
        issues.append("work_package_contract_mismatch")
    if int(work_package.get("version") or 0) != 3:
        issues.append("work_package_version_mismatch")
    if work_package.get("private_payload") is not True:
        issues.append("work_package_private_contract_missing")
    if str(work_package.get("status") or "") != "ready_for_private_cast_resolution":
        issues.append("work_package_not_ready_for_cast_resolution")
    if work_package.get("cast_resolution_authorized") is not True:
        issues.append("work_package_cast_resolution_not_authorized")
    if work_package.get("render_authorized") is not False:
        issues.append("work_package_premature_render_authority")
    if work_package.get("synthesis_authorized") is not False:
        issues.append("work_package_premature_synthesis_authority")
    if work_package.get("provider_calls_made") not in (0, None):
        issues.append("work_package_provider_call_claim_invalid")
    if work_package.get("synthesis_requested") is not False:
        issues.append("work_package_synthesis_request_claim_invalid")
    if source_policy.get("purpose_specific_narration_review_required") is not True:
        issues.append("work_package_narration_review_policy_missing")
    if source_policy.get("narration_review_scope_array_required") is not True:
        issues.append("work_package_narration_scope_shape_policy_missing")
    if str(source_policy.get("required_narration_source_scope") or "") != (
        REQUIRED_NARRATION_SOURCE_SCOPE
    ):
        issues.append("work_package_narration_scope_policy_mismatch")
    if source_policy.get("exact_source_hash_binding_required") is not True:
        issues.append("work_package_narration_source_hash_policy_missing")
    if not source_rows:
        issues.append("work_package_sources_missing")
    permission_evidence_rows: list[dict[str, object]] = []
    source_hrefs: set[str] = set()
    for row in source_rows:
        source_href = str(row.get("source_href") or "")
        kind = str(row.get("kind") or "")
        evidence_sha256 = str(
            row.get("narration_review_evidence_sha256") or ""
        )
        text_sha256 = str(row.get("text_sha256") or "")
        if not source_href:
            issues.append("work_package_source_href_missing")
        elif source_href in source_hrefs:
            issues.append("work_package_source_href_duplicate")
        source_hrefs.add(source_href)
        if not kind:
            issues.append("work_package_source_kind_missing")
        if row.get("visibility") != "public":
            issues.append("work_package_source_visibility_invalid")
        if re.fullmatch(r"[0-9a-f]{64}", text_sha256) is None:
            issues.append("work_package_source_text_sha256_invalid")
        if re.fullmatch(r"[0-9a-f]{64}", evidence_sha256) is None:
            issues.append("work_package_narration_permission_evidence_invalid")
        permission_evidence_rows.append(
            {
                "source_href": source_href,
                "kind": kind,
                "text_sha256": text_sha256,
                "narration_review_evidence_sha256": evidence_sha256,
            }
        )
    if receipt.get("contract_name") != RECEIPT_CONTRACT_NAME:
        issues.append("receipt_contract_mismatch")
    if receipt.get("purpose_specific_narration_review_required") is not True:
        issues.append("receipt_narration_review_policy_missing")
    if receipt.get("narration_review_scope_array_required") is not True:
        issues.append("receipt_narration_scope_shape_policy_missing")
    if str(receipt.get("required_narration_source_scope") or "") != (
        REQUIRED_NARRATION_SOURCE_SCOPE
    ):
        issues.append("receipt_narration_scope_mismatch")
    if int(receipt.get("approved_narration_permission_count") or 0) != len(
        source_rows
    ):
        issues.append("receipt_narration_permission_count_mismatch")
    if int(receipt.get("approved_public_source_count") or 0) != len(source_rows):
        issues.append("receipt_approved_source_count_mismatch")
    if str(receipt.get("source_aggregate_sha256") or "") != (
        _stable_json_sha256(source_rows)
    ):
        issues.append("receipt_source_aggregate_mismatch")
    if str(receipt.get("narration_permission_evidence_aggregate_sha256") or "") != (
        _stable_json_sha256(permission_evidence_rows)
    ):
        issues.append("receipt_narration_permission_evidence_mismatch")
    if str(receipt.get("work_package_sha256") or "") != (
        calculated_work_package_sha256
    ):
        issues.append("work_package_sha256_mismatch")
    if str(work_package.get("cast_handoff_sha256") or "") != (
        calculated_cast_handoff_sha256
    ):
        issues.append("cast_handoff_sha256_mismatch")
    if str(receipt.get("cast_handoff_sha256") or "") != (
        calculated_cast_handoff_sha256
    ):
        issues.append("receipt_cast_handoff_sha256_mismatch")
    plan_sha256 = str(plan.get("plan_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", plan_sha256):
        issues.append("narration_plan_sha256_missing")
    if str(receipt.get("plan_sha256") or "") != plan_sha256:
        issues.append("receipt_plan_sha256_mismatch")
    if plan.get("coverage_complete") is not True or plan.get(
        "source_integrity_verified"
    ) is not True:
        issues.append("narration_plan_source_integrity_not_verified")
    if str(plan.get("status") or "") != "ready":
        issues.append("narration_plan_not_ready")
    return (
        {
            "slug": _normalized_tag(work_package.get("slug")),
            "language": _normalized_text(work_package.get("language")),
            "work_package_sha256": calculated_work_package_sha256,
            "plan_sha256": plan_sha256,
            "source_aggregate_sha256": str(
                receipt.get("source_aggregate_sha256") or ""
            ),
            "planner_source_aggregate_sha256": str(
                plan.get("source_aggregate_sha256") or ""
            ),
            "cast_handoff_sha256": calculated_cast_handoff_sha256,
            "cast_map_sha256": str(cast_handoff.get("cast_map_sha256") or ""),
            "consent_evidence_sha256": str(
                dict(receipt.get("voice_consent") or {}).get("evidence_sha256")
                if isinstance(receipt.get("voice_consent"), Mapping)
                else ""
            ),
        },
        sorted(set(issues)),
    )


def _dialogue_handoff_rows(
    work_package: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    handoff = dict(work_package.get("cast_handoff") or {})
    rows = []
    for raw in list(handoff.get("speakers") or []):
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        if str(row.get("speaker_role") or "") == "dialogue":
            rows.append(row)
    return tuple(sorted(rows, key=lambda row: str(row.get("speaker_id") or "")))


def _plan_traits_for_speaker(
    work_package: Mapping[str, object], speaker_id: str
) -> dict[str, dict[str, object]]:
    plan = dict(work_package.get("narration_plan") or {})
    for raw in list(plan.get("speakers") or []):
        if not isinstance(raw, Mapping) or str(raw.get("speaker_id") or "") != speaker_id:
            continue
        if raw.get("traits_from_explicit_approved_profile_only") is not True:
            return {}
        traits: dict[str, dict[str, object]] = {}
        for raw_kind, raw_evidence in dict(raw.get("traits") or {}).items():
            if not isinstance(raw_evidence, Mapping):
                continue
            if str(raw_evidence.get("provenance") or "") != (
                "explicit_approved_speaker_profile"
            ):
                continue
            kind = _canonical_trait_kind(raw_kind)
            value = _canonical_trait_value(kind, raw_evidence.get("value"))
            if value:
                traits[kind] = {
                    "value": value,
                    "provenance": "explicit_approved_speaker_profile",
                    "sensitive": kind == "cultural_or_ethnic_background",
                }
        return traits
    return {}


def _mapping_rows(value: object) -> tuple[dict[str, object], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        root = dict(value)
        if isinstance(root.get("mappings"), list):
            rows = [dict(row) for row in root["mappings"] if isinstance(row, Mapping)]
            neutral = root.get("neutral_mapping")
            if isinstance(neutral, Mapping):
                rows.append({"neutral_mapping": True, **dict(neutral)})
            return tuple(rows)
        rows = []
        for key, raw in root.items():
            if not isinstance(raw, Mapping):
                continue
            row = dict(raw)
            if str(key) == "neutral_mapping":
                rows.append({"neutral_mapping": True, **row})
                continue
            row.setdefault("speaker_id", str(key))
            rows.append(row)
        return tuple(rows)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(dict(row) for row in value if isinstance(row, Mapping))
    return ()


def _mapping_is_approved(row: Mapping[str, object]) -> bool:
    status = _normalized_tag(row.get("status") or row.get("approval_status"))
    explicit_approver = any(
        row.get(key) is True
        for key in (
            "approved_by_user",
            "approved_by_family",
            "approved_by_operator",
            "approved_by_reviewer",
        )
    )
    return explicit_approver and status in _APPROVED_STATUSES


def _mapping_profile_ref_sha256(row: Mapping[str, object]) -> str:
    explicit_hash = str(row.get("speaker_profile_ref_sha256") or "").strip()
    if re.fullmatch(r"[0-9a-f]{64}", explicit_hash):
        return explicit_hash
    profile_ref = _mapping_value(
        row,
        "speaker_profile_id",
        "profile_id",
        "voice_profile_ref",
        "voice_profile_id",
    )
    return _stable_json_sha256(
        {
            "profile_ref": profile_ref,
            "speaker_key": _normalized_tag(row.get("speaker_label")),
            "approved_traits": dict(row.get("speaker_traits") or {}),
        }
    ) if profile_ref else ""


def _mapping_for_speaker(
    mappings: tuple[dict[str, object], ...],
    handoff_row: Mapping[str, object],
) -> tuple[dict[str, object], str]:
    speaker_id = str(handoff_row.get("speaker_id") or "")
    exact = [row for row in mappings if str(row.get("speaker_id") or "") == speaker_id]
    approved_exact = [row for row in exact if _mapping_is_approved(row)]
    if len(approved_exact) == 1:
        return dict(approved_exact[0]), "explicit_approved_per_speaker_mapping"
    if len(approved_exact) > 1:
        return {}, "dialogue_voice_mapping_ambiguous"
    if exact:
        return {}, "dialogue_voice_mapping_not_explicitly_approved"
    neutral = [
        row
        for row in mappings
        if row.get("neutral_mapping") is True
        and row.get("neutral_approved") is True
        and _mapping_is_approved(row)
        and (
            not isinstance(row.get("speaker_ids"), list)
            or speaker_id in {str(value) for value in row.get("speaker_ids") or []}
        )
    ]
    if len(neutral) == 1:
        return dict(neutral[0]), "explicit_approved_neutral_mapping"
    if len(neutral) > 1:
        return {}, "neutral_dialogue_voice_mapping_ambiguous"
    return {}, "dialogue_voice_mapping_missing"


def _voice_traits(row: Mapping[str, object]) -> dict[str, str]:
    raw_traits = row.get("voice_traits") or row.get("catalog_traits") or {}
    if not isinstance(raw_traits, Mapping):
        return {}
    traits: dict[str, str] = {}
    for raw_kind, raw_value in raw_traits.items():
        kind = _canonical_trait_kind(raw_kind)
        if isinstance(raw_value, Mapping):
            raw_value = raw_value.get("value")
        value = _canonical_trait_value(kind, raw_value)
        if value:
            traits[kind] = value
    return traits


def _trait_comparison(
    source_traits: Mapping[str, Mapping[str, object]],
    voice_traits: Mapping[str, str],
) -> dict[str, object]:
    matched: list[str] = []
    mismatched: list[str] = []
    unverified: list[str] = []
    for kind, source_evidence in source_traits.items():
        if kind not in _DEMOGRAPHIC_TRAIT_KINDS:
            continue
        source_value = str(source_evidence.get("value") or "")
        voice_value = str(voice_traits.get(kind) or "")
        if not voice_value:
            unverified.append(kind)
        elif source_value == voice_value:
            matched.append(kind)
        else:
            mismatched.append(kind)
    return {
        "status": (
            "mismatch"
            if mismatched
            else "unverified"
            if unverified
            else "matched_or_human_approved"
        ),
        "matched_trait_kinds": sorted(matched),
        "mismatched_trait_kinds": sorted(mismatched),
        "unverified_trait_kinds": sorted(unverified),
        "source_trait_value_sha256": {
            kind: _text_sha256(evidence.get("value"))
            for kind, evidence in sorted(source_traits.items())
            if kind in _DEMOGRAPHIC_TRAIT_KINDS
        },
        "voice_trait_value_sha256": {
            kind: _text_sha256(value)
            for kind, value in sorted(voice_traits.items())
            if kind in _DEMOGRAPHIC_TRAIT_KINDS
        },
    }


def _resolved_cast_map_sha256(
    narrator: Mapping[str, object], dialogue_cast: Sequence[Mapping[str, object]]
) -> str:
    rows = [
        {
            "speaker_id": "narrator",
            "provider": str(narrator.get("provider") or ""),
            "voice_id_sha256": str(narrator.get("voice_id_sha256") or ""),
            "mapping_kind": "approved_private_memorial_voice_profile",
        }
    ]
    rows.extend(
        {
            "speaker_id": str(row.get("speaker_id") or ""),
            "provider": str(row.get("provider") or ""),
            "voice_id_sha256": str(row.get("voice_id_sha256") or ""),
            "mapping_kind": str(row.get("mapping_kind") or ""),
        }
        for row in dialogue_cast
    )
    return _stable_json_sha256(rows)


def _blocked_resolution(
    *,
    bindings: Mapping[str, object],
    issues: Sequence[str],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_name": CAST_RESOLUTION_CONTRACT_NAME,
        "version": 1,
        "status": "blocked",
        "reason": str(issues[0] if issues else "cast_resolution_blocked"),
        "issues": sorted(set(str(issue) for issue in issues if str(issue))),
        "generated_at": _now_iso(),
        "bindings": dict(bindings),
        "narrator": {},
        "dialogue_cast": [],
        "resolved_cast_map_sha256": "",
        "private_payload": True,
        "provider_calls_made": 0,
        "synthesis_requested": False,
        "synthesis_authorized": False,
    }
    payload["resolution_sha256"] = _stable_json_sha256(payload)
    return payload


def resolve_memorial_narration_cast(
    *,
    work_package: Mapping[str, object],
    voice_profile: Mapping[str, object],
    speaker_voice_mappings: object = None,
    now: datetime | None = None,
) -> dict[str, object]:
    observed_at = (now or datetime.now(UTC)).astimezone(UTC)
    bindings, issues = _work_package_bindings(work_package)
    consent = _consent_decision(voice_profile, now=observed_at)
    if consent["authorized"] is not True:
        issues.append(str(consent["reason"]))
    if bindings.get("consent_evidence_sha256") != consent.get("evidence_sha256"):
        issues.append("voice_consent_evidence_changed_since_work_package")

    descriptor = _voice_descriptor(voice_profile)
    if not descriptor["provider"]:
        issues.append("narrator_provider_missing")
    if not descriptor["voice_id"]:
        issues.append("narrator_private_voice_id_missing")
    if not _language_compatible(bindings.get("language"), descriptor["language"]):
        issues.append("narrator_voice_language_incompatible_or_unverified")

    profile_ref = _mapping_value(voice_profile, "voice_profile_id")
    narrator_handoff = next(
        (
            dict(row)
            for row in list(dict(work_package.get("cast_handoff") or {}).get("speakers") or [])
            if isinstance(row, Mapping)
            and str(row.get("speaker_role") or "") == "narrator"
        ),
        {},
    )
    if narrator_handoff.get("mapping") != "approved_memorial_voice_profile":
        issues.append("narrator_handoff_not_approved_memorial_profile")
    if not profile_ref:
        issues.append("narrator_voice_profile_ref_missing")
    elif str(narrator_handoff.get("profile_ref_sha256") or "") != _text_sha256(
        profile_ref
    ):
        issues.append("narrator_voice_profile_ref_mismatch")

    if issues:
        return _blocked_resolution(bindings=bindings, issues=issues)

    narrator = {
        "speaker_id": "narrator",
        "mapping_kind": "approved_private_memorial_voice_profile",
        "provider": descriptor["provider"],
        "voice_id": descriptor["voice_id"],
        "voice_id_sha256": _text_sha256(descriptor["voice_id"]),
        "voice_profile_ref_sha256": _text_sha256(profile_ref),
        "language": descriptor["language"],
        "consent": consent,
    }

    mappings = _mapping_rows(speaker_voice_mappings)
    dialogue_cast: list[dict[str, object]] = []
    dialogue_issues: list[str] = []
    used_voice_ids: set[str] = set()
    for handoff_row in _dialogue_handoff_rows(work_package):
        speaker_id = str(handoff_row.get("speaker_id") or "")
        mapping, mapping_kind_or_reason = _mapping_for_speaker(mappings, handoff_row)
        if not mapping:
            dialogue_issues.append(f"{mapping_kind_or_reason}:{speaker_id}")
            continue
        mapping_kind = mapping_kind_or_reason
        mapping_descriptor = _voice_descriptor(mapping)
        if not mapping_descriptor["provider"]:
            dialogue_issues.append(f"dialogue_voice_provider_missing:{speaker_id}")
            continue
        if _normalized_tag(mapping_descriptor["provider"]) != _normalized_tag(
            descriptor["provider"]
        ):
            dialogue_issues.append(f"dialogue_voice_provider_unsupported:{speaker_id}")
            continue
        voice_id = mapping_descriptor["voice_id"]
        if not voice_id:
            dialogue_issues.append(f"dialogue_private_voice_id_missing:{speaker_id}")
            continue
        if voice_id == descriptor["voice_id"]:
            dialogue_issues.append(f"dialogue_voice_not_distinct_from_narrator:{speaker_id}")
            continue
        if voice_id in used_voice_ids:
            dialogue_issues.append(f"dialogue_voice_not_distinct_between_speakers:{speaker_id}")
            continue
        if not _language_compatible(
            bindings.get("language"), mapping_descriptor["language"]
        ):
            dialogue_issues.append(
                f"dialogue_voice_language_incompatible_or_unverified:{speaker_id}"
            )
            continue
        expected_profile_ref = str(handoff_row.get("profile_ref_sha256") or "")
        if handoff_row.get("explicit_profile") is True and expected_profile_ref:
            if _mapping_profile_ref_sha256(mapping) != expected_profile_ref:
                dialogue_issues.append(
                    f"dialogue_speaker_profile_ref_mismatch:{speaker_id}"
                )
                continue
        source_traits = _plan_traits_for_speaker(work_package, speaker_id)
        if mapping_kind == "explicit_approved_neutral_mapping" and source_traits:
            dialogue_issues.append(
                f"neutral_mapping_for_profiled_speaker_forbidden:{speaker_id}"
            )
            continue
        catalog_traits = _voice_traits(mapping)
        comparison = _trait_comparison(source_traits, catalog_traits)
        if comparison["mismatched_trait_kinds"]:
            dialogue_issues.append(f"dialogue_voice_trait_mismatch:{speaker_id}")
            continue
        if comparison["unverified_trait_kinds"]:
            dialogue_issues.append(f"dialogue_voice_trait_unverified:{speaker_id}")
            continue
        used_voice_ids.add(voice_id)
        dialogue_cast.append(
            {
                "speaker_id": speaker_id,
                "mapping_kind": mapping_kind,
                "provider": mapping_descriptor["provider"],
                "voice_id": voice_id,
                "voice_id_sha256": _text_sha256(voice_id),
                "language": mapping_descriptor["language"],
                "speaker_profile_ref_sha256": expected_profile_ref,
                "source_traits": source_traits,
                "voice_traits": catalog_traits,
                "trait_comparison": comparison,
                "identity_or_demographics_inferred": False,
            }
        )
    if dialogue_issues:
        return _blocked_resolution(bindings=bindings, issues=dialogue_issues)

    dialogue_cast.sort(key=lambda row: str(row["speaker_id"]))
    resolved_cast_map_sha256 = _resolved_cast_map_sha256(narrator, dialogue_cast)
    payload = {
        "contract_name": CAST_RESOLUTION_CONTRACT_NAME,
        "version": 1,
        "status": "ready_for_mapping_review",
        "reason": "",
        "issues": [],
        "generated_at": observed_at.isoformat().replace("+00:00", "Z"),
        "bindings": {
            **bindings,
            "consent_evidence_sha256": consent["evidence_sha256"],
        },
        "narrator": narrator,
        "dialogue_cast": dialogue_cast,
        "resolved_cast_map_sha256": resolved_cast_map_sha256,
        "dialogue_speaker_count": len(dialogue_cast),
        "all_dialogue_voices_distinct": len(used_voice_ids) == len(dialogue_cast),
        "narrator_excluded_from_dialogue": descriptor["voice_id"] not in used_voice_ids,
        "demographic_policy": "explicit_approved_traits_and_mappings_only",
        "identity_or_demographics_inferred": False,
        "authorization_capability": False,
        "informational_receipt": True,
        "private_payload": True,
        "provider_calls_made": 0,
        "synthesis_requested": False,
        "synthesis_authorized": False,
        "cast_mapping_review_required": True,
    }
    payload["resolution_sha256"] = _stable_json_sha256(payload)
    return payload


def _resolution_without_hash(resolution: Mapping[str, object]) -> dict[str, object]:
    return {
        str(key): value
        for key, value in resolution.items()
        if str(key) != "resolution_sha256"
    }


def _resolution_integrity_issues(resolution: Mapping[str, object]) -> list[str]:
    issues: list[str] = []
    if resolution.get("contract_name") != CAST_RESOLUTION_CONTRACT_NAME:
        issues.append("cast_resolution_contract_mismatch")
    if int(resolution.get("version") or 0) != 1:
        issues.append("cast_resolution_version_mismatch")
    if str(resolution.get("status") or "") != "ready_for_mapping_review":
        issues.append("cast_resolution_not_ready_for_review")
    if resolution.get("private_payload") is not True:
        issues.append("cast_resolution_private_contract_missing")
    if resolution.get("synthesis_authorized") is not False:
        issues.append("cast_resolution_premature_synthesis_authority")
    if resolution.get("provider_calls_made") not in (0, None):
        issues.append("cast_resolution_provider_call_claim_invalid")
    expected_resolution_sha256 = _stable_json_sha256(
        _resolution_without_hash(resolution)
    )
    if str(resolution.get("resolution_sha256") or "") != expected_resolution_sha256:
        issues.append("cast_resolution_sha256_mismatch")
    narrator = dict(resolution.get("narrator") or {})
    narrator_voice_id = str(narrator.get("voice_id") or "")
    if not narrator_voice_id or str(narrator.get("voice_id_sha256") or "") != (
        _text_sha256(narrator_voice_id)
    ):
        issues.append("cast_resolution_narrator_voice_hash_mismatch")
    used_voice_ids: set[str] = set()
    for raw in list(resolution.get("dialogue_cast") or []):
        if not isinstance(raw, Mapping):
            issues.append("cast_resolution_dialogue_entry_invalid")
            continue
        voice_id = str(raw.get("voice_id") or "")
        speaker_id = str(raw.get("speaker_id") or "")
        if not voice_id or str(raw.get("voice_id_sha256") or "") != _text_sha256(
            voice_id
        ):
            issues.append(f"cast_resolution_dialogue_voice_hash_mismatch:{speaker_id}")
        if voice_id == narrator_voice_id:
            issues.append(f"cast_resolution_dialogue_matches_narrator:{speaker_id}")
        if voice_id in used_voice_ids:
            issues.append(f"cast_resolution_dialogue_voice_reused:{speaker_id}")
        used_voice_ids.add(voice_id)
        comparison = dict(raw.get("trait_comparison") or {})
        if list(comparison.get("mismatched_trait_kinds") or []):
            issues.append(f"cast_resolution_trait_mismatch:{speaker_id}")
        if raw.get("identity_or_demographics_inferred") is not False:
            issues.append(f"cast_resolution_demographic_inference_claim:{speaker_id}")
    if str(resolution.get("resolved_cast_map_sha256") or "") != (
        _resolved_cast_map_sha256(
            narrator,
            [
                dict(row)
                for row in list(resolution.get("dialogue_cast") or [])
                if isinstance(row, Mapping)
            ],
        )
    ):
        issues.append("resolved_cast_map_sha256_mismatch")
    return sorted(set(issues))


def _signing_secret(value: str | bytes) -> bytes:
    secret = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    if len(secret) < 16:
        raise ValueError("review_signing_secret_too_short")
    if len(secret) > MAX_SIGNING_SECRET_BYTES:
        raise ValueError("review_signing_secret_too_large")
    return secret


def build_memorial_narration_cast_review(
    *,
    resolution: Mapping[str, object],
    reviewer: str,
    signing_secret: str | bytes,
    status: str = "approved",
    scope: str = REQUIRED_REVIEW_SCOPE,
    reviewed_at: str = "",
    expires_at: str = "",
    revoked: bool = False,
    note: str = "",
) -> dict[str, object]:
    integrity_issues = _resolution_integrity_issues(resolution)
    if integrity_issues:
        raise ValueError(integrity_issues[0])
    reviewer_value = _normalized_text(reviewer)
    if not reviewer_value:
        raise ValueError("cast_reviewer_required")
    decision = _normalized_tag(status)
    if decision not in {"approved", "rejected"}:
        raise ValueError("cast_review_status_invalid")
    scope_value = _normalized_text(scope)
    if scope_value != REQUIRED_REVIEW_SCOPE:
        raise ValueError("cast_review_scope_invalid")
    reviewed_value = reviewed_at or _now_iso()
    reviewed_datetime = _parse_datetime(reviewed_value)
    if reviewed_datetime is None:
        raise ValueError("cast_review_timestamp_invalid")
    if reviewed_datetime > datetime.now(UTC) + timedelta(minutes=5):
        raise ValueError("cast_review_timestamp_in_future")
    expires_datetime = _parse_datetime(expires_at)
    if not expires_at:
        raise ValueError("cast_review_expiry_required")
    if expires_datetime is None:
        raise ValueError("cast_review_expiry_invalid")
    if expires_datetime <= reviewed_datetime:
        raise ValueError("cast_review_expiry_not_after_review")
    if expires_datetime - reviewed_datetime > MAX_MAPPING_REVIEW_TTL:
        raise ValueError("cast_review_expiry_too_distant")
    base: dict[str, object] = {
        "contract_name": CAST_REVIEW_CONTRACT_NAME,
        "version": 1,
        "decision": decision,
        "approved": decision == "approved" and not revoked,
        "revoked": bool(revoked),
        "reviewer": reviewer_value,
        "reviewed_at": reviewed_value,
        "scope": scope_value,
        "expires_at": expires_at,
        "note": _normalized_text(note)[:2000],
        "resolution_sha256": str(resolution.get("resolution_sha256") or ""),
        "work_package_sha256": str(
            dict(resolution.get("bindings") or {}).get("work_package_sha256") or ""
        ),
        "plan_sha256": str(
            dict(resolution.get("bindings") or {}).get("plan_sha256") or ""
        ),
        "resolved_cast_map_sha256": str(
            resolution.get("resolved_cast_map_sha256") or ""
        ),
        "signature_algorithm": "hmac-sha256",
        "private_payload": True,
    }
    review_sha256 = _stable_json_sha256(base)
    signed = {**base, "review_sha256": review_sha256}
    signature = hmac.new(
        _signing_secret(signing_secret),
        _stable_json_bytes(signed),
        hashlib.sha256,
    ).hexdigest()
    return {**signed, "signature": signature}


def _review_integrity_issues(
    review: Mapping[str, object],
    *,
    resolution: Mapping[str, object],
    signing_secret: str | bytes,
    now: datetime,
) -> list[str]:
    issues: list[str] = []
    if review.get("contract_name") != CAST_REVIEW_CONTRACT_NAME:
        issues.append("cast_review_contract_mismatch")
    if int(review.get("version") or 0) != 1:
        issues.append("cast_review_version_mismatch")
    if review.get("private_payload") is not True:
        issues.append("cast_review_private_contract_missing")
    if str(review.get("signature_algorithm") or "") != "hmac-sha256":
        issues.append("cast_review_signature_algorithm_mismatch")
    base = {
        str(key): value
        for key, value in review.items()
        if str(key) not in {"review_sha256", "signature"}
    }
    calculated_review_sha256 = _stable_json_sha256(base)
    if str(review.get("review_sha256") or "") != calculated_review_sha256:
        issues.append("cast_review_sha256_mismatch")
    signed = {**base, "review_sha256": calculated_review_sha256}
    expected_signature = hmac.new(
        _signing_secret(signing_secret),
        _stable_json_bytes(signed),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(
        str(review.get("signature") or ""), expected_signature
    ):
        issues.append("cast_review_signature_invalid")
    if str(review.get("resolution_sha256") or "") != str(
        resolution.get("resolution_sha256") or ""
    ):
        issues.append("cast_review_resolution_binding_mismatch")
    bindings = dict(resolution.get("bindings") or {})
    if str(review.get("work_package_sha256") or "") != str(
        bindings.get("work_package_sha256") or ""
    ):
        issues.append("cast_review_work_package_binding_mismatch")
    if str(review.get("plan_sha256") or "") != str(
        bindings.get("plan_sha256") or ""
    ):
        issues.append("cast_review_plan_binding_mismatch")
    if str(review.get("resolved_cast_map_sha256") or "") != str(
        resolution.get("resolved_cast_map_sha256") or ""
    ):
        issues.append("cast_review_cast_binding_mismatch")
    if _normalized_tag(review.get("decision")) != "approved" or review.get(
        "approved"
    ) is not True:
        issues.append("cast_review_not_approved")
    if review.get("revoked") is True:
        issues.append("cast_review_revoked")
    if _normalized_text(review.get("scope")) != REQUIRED_REVIEW_SCOPE:
        issues.append("cast_review_scope_missing")
    reviewed_at = _parse_datetime(review.get("reviewed_at"))
    if reviewed_at is None:
        issues.append("cast_review_timestamp_invalid")
    elif reviewed_at > now:
        issues.append("cast_review_timestamp_in_future")
    expires_text = str(review.get("expires_at") or "").strip()
    expires_at = _parse_datetime(expires_text)
    if not expires_text:
        issues.append("cast_review_expiry_required")
    elif expires_at is None:
        issues.append("cast_review_expiry_invalid")
    elif expires_at is not None and expires_at <= now:
        issues.append("cast_review_expired")
    if reviewed_at is not None and expires_at is not None:
        if expires_at <= reviewed_at:
            issues.append("cast_review_expiry_not_after_review")
        elif expires_at - reviewed_at > MAX_MAPPING_REVIEW_TTL:
            issues.append("cast_review_expiry_too_distant")
    if not _normalized_text(review.get("reviewer")):
        issues.append("cast_reviewer_missing")
    return sorted(set(issues))


def _current_profile_issues(
    *,
    work_package: Mapping[str, object],
    resolution: Mapping[str, object],
    voice_profile: Mapping[str, object],
    speaker_voice_mappings: object,
    now: datetime,
) -> list[str]:
    issues: list[str] = []
    bindings, package_issues = _work_package_bindings(work_package)
    issues.extend(package_issues)
    resolution_bindings = dict(resolution.get("bindings") or {})
    for key in (
        "slug",
        "language",
        "work_package_sha256",
        "plan_sha256",
        "source_aggregate_sha256",
        "planner_source_aggregate_sha256",
        "cast_handoff_sha256",
        "cast_map_sha256",
    ):
        if str(resolution_bindings.get(key) or "") != str(bindings.get(key) or ""):
            issues.append(f"cast_resolution_{key}_binding_mismatch")
    consent = _consent_decision(voice_profile, now=now)
    if consent["authorized"] is not True:
        issues.append(str(consent["reason"]))
    if str(resolution_bindings.get("consent_evidence_sha256") or "") != str(
        consent.get("evidence_sha256") or ""
    ):
        issues.append("voice_consent_evidence_changed_since_resolution")
    descriptor = _voice_descriptor(voice_profile)
    narrator = dict(resolution.get("narrator") or {})
    profile_ref = _mapping_value(voice_profile, "voice_profile_id")
    if not profile_ref:
        issues.append("narrator_voice_profile_ref_missing")
    elif str(narrator.get("voice_profile_ref_sha256") or "") != _text_sha256(
        profile_ref
    ):
        issues.append("narrator_voice_profile_ref_changed_since_resolution")
    if str(narrator.get("provider") or "") != descriptor["provider"]:
        issues.append("narrator_provider_changed_since_resolution")
    if str(narrator.get("voice_id") or "") != descriptor["voice_id"]:
        issues.append("narrator_voice_changed_since_resolution")
    if not _language_compatible(bindings.get("language"), descriptor["language"]):
        issues.append("narrator_voice_language_incompatible_or_unverified")
    required_dialogue_ids = {
        str(row.get("speaker_id") or "")
        for row in _dialogue_handoff_rows(work_package)
        if str(row.get("speaker_id") or "")
    }
    resolved_dialogue_rows = [
        dict(row)
        for row in list(resolution.get("dialogue_cast") or [])
        if isinstance(row, Mapping)
    ]
    resolved_dialogue_ids = {
        str(row.get("speaker_id") or "")
        for row in resolved_dialogue_rows
        if str(row.get("speaker_id") or "")
    }
    if required_dialogue_ids != resolved_dialogue_ids:
        issues.append("cast_resolution_dialogue_coverage_mismatch")
    if int(resolution.get("dialogue_speaker_count") or 0) != len(
        resolved_dialogue_rows
    ):
        issues.append("cast_resolution_dialogue_count_mismatch")
    current_resolution = resolve_memorial_narration_cast(
        work_package=work_package,
        voice_profile=voice_profile,
        speaker_voice_mappings=speaker_voice_mappings,
        now=now,
    )
    if current_resolution.get("status") != "ready_for_mapping_review":
        issues.extend(
            f"current_cast_{issue}"
            for issue in list(current_resolution.get("issues") or [])
            if str(issue)
        )
        if not list(current_resolution.get("issues") or []):
            issues.append("current_cast_not_resolvable")
    else:
        if str(current_resolution.get("resolved_cast_map_sha256") or "") != str(
            resolution.get("resolved_cast_map_sha256") or ""
        ):
            issues.append("current_cast_map_changed_since_resolution")
        if _stable_json_sha256(
            dict(current_resolution.get("narrator") or {})
        ) != _stable_json_sha256(narrator):
            issues.append("current_narrator_cast_changed_since_resolution")
        if _stable_json_sha256(
            list(current_resolution.get("dialogue_cast") or [])
        ) != _stable_json_sha256(resolved_dialogue_rows):
            issues.append("current_dialogue_cast_changed_since_resolution")
    return sorted(set(issues))


def _safe_bindings(value: Mapping[str, object]) -> dict[str, object]:
    allowed = {
        "slug",
        "language",
        "work_package_sha256",
        "plan_sha256",
        "source_aggregate_sha256",
        "planner_source_aggregate_sha256",
    }
    return {key: value.get(key) for key in sorted(allowed) if value.get(key)}


def cast_resolution_safe_receipt(
    resolution: Mapping[str, object],
) -> dict[str, object]:
    narrator = dict(resolution.get("narrator") or {})
    dialogue: list[dict[str, object]] = []
    for speaker_index, raw in enumerate(
        list(resolution.get("dialogue_cast") or []), start=1
    ):
        if not isinstance(raw, Mapping):
            continue
        comparison = dict(raw.get("trait_comparison") or {})
        dialogue.append(
            {
                "speaker_index": speaker_index,
                "mapping_kind": str(raw.get("mapping_kind") or ""),
                "provider": str(raw.get("provider") or ""),
                "trait_match_status": str(comparison.get("status") or ""),
                "matched_trait_count": len(
                    list(comparison.get("matched_trait_kinds") or [])
                ),
                "mismatched_trait_count": len(
                    list(comparison.get("mismatched_trait_kinds") or [])
                ),
                "unverified_trait_count": len(
                    list(comparison.get("unverified_trait_kinds") or [])
                ),
                "identity_or_demographics_inferred": False,
            }
        )
    issue_codes = sorted(
        {
            str(issue).split(":", 1)[0]
            for issue in list(resolution.get("issues") or [])
            if str(issue)
        }
    )
    return {
        "contract_name": f"{CAST_RESOLUTION_CONTRACT_NAME}.receipt",
        "status": str(resolution.get("status") or "blocked"),
        "reason": str(resolution.get("reason") or "").split(":", 1)[0],
        "issues": issue_codes,
        "resolution_sha256": str(resolution.get("resolution_sha256") or ""),
        "bindings": _safe_bindings(dict(resolution.get("bindings") or {})),
        "provider": str(narrator.get("provider") or ""),
        "dialogue_cast": dialogue,
        "dialogue_speaker_count": int(
            resolution.get("dialogue_speaker_count") or 0
        ),
        "provider_calls_made": 0,
        "synthesis_requested": False,
        "synthesis_authorized": False,
        "cast_mapping_review_required": True,
        "raw_voice_ids_exposed": False,
        "sensitive_trait_values_exposed": False,
        "authorization_capability": False,
        "informational_receipt": True,
        "identity_or_demographics_inferred": False,
    }


def cast_review_safe_receipt(review: Mapping[str, object]) -> dict[str, object]:
    return {
        "contract_name": f"{CAST_REVIEW_CONTRACT_NAME}.receipt",
        "decision": str(review.get("decision") or ""),
        "approved": review.get("approved") is True,
        "revoked": review.get("revoked") is True,
        "scope": str(review.get("scope") or ""),
        "expiry_present": bool(str(review.get("expires_at") or "")),
        "resolution_sha256": str(review.get("resolution_sha256") or ""),
        "signature_present": bool(str(review.get("signature") or "")),
        "raw_reviewer_exposed": False,
        "raw_voice_ids_exposed": False,
        "sensitive_trait_values_exposed": False,
        "authorization_capability": False,
        "informational_receipt": True,
    }


def verify_memorial_narration_cast(
    *,
    work_package: Mapping[str, object],
    resolution: Mapping[str, object],
    review: Mapping[str, object],
    voice_profile: Mapping[str, object],
    signing_secret: str | bytes,
    speaker_voice_mappings: object = None,
    now: datetime | None = None,
) -> dict[str, object]:
    observed_at = (now or datetime.now(UTC)).astimezone(UTC)
    issues = _resolution_integrity_issues(resolution)
    issues.extend(
        _current_profile_issues(
            work_package=work_package,
            resolution=resolution,
            voice_profile=voice_profile,
            speaker_voice_mappings=speaker_voice_mappings,
            now=observed_at,
        )
    )
    issues.extend(
        _review_integrity_issues(
            review,
            resolution=resolution,
            signing_secret=signing_secret,
            now=observed_at,
        )
    )
    issues = sorted(set(issues))
    safe_issues = sorted(
        {str(issue).split(":", 1)[0] for issue in issues if str(issue)}
    )
    resolution_receipt = cast_resolution_safe_receipt(resolution)
    review_receipt = cast_review_safe_receipt(review)
    return {
        "contract_name": CAST_VERIFICATION_RECEIPT_CONTRACT_NAME,
        "status": "pass" if not issues else "blocked",
        "reason": str(safe_issues[0] if safe_issues else ""),
        "issues": safe_issues,
        "verified_at": observed_at.isoformat().replace("+00:00", "Z"),
        "cast_mapping_reviewed": not issues,
        "ready_for_provider_preflight": not issues,
        "ready_for_private_audition": False,
        "audition_authorized": False,
        "synthesis_authorized": False,
        "render_authorized": False,
        "human_listening_review_required": True,
        "provider_capability_receipt_required": True,
        "audition_sample_hashes_verified": False,
        "provider_capability_verified": False,
        "source_freshness_revalidation_required": True,
        "resolution": resolution_receipt,
        "review": review_receipt,
        "provider_calls_made": 0,
        "synthesis_requested": False,
        "raw_voice_ids_exposed": False,
        "sensitive_trait_values_exposed": False,
        "reviewer_identity_exposed": False,
        "reviewer_identity_verified": False,
        "identity_or_demographics_inferred": False,
        "authorization_capability": False,
        "informational_receipt": True,
    }


def _has_symlink_ancestor(path: Path) -> bool:
    current = path.expanduser().absolute().parent
    while True:
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                return True
        except FileNotFoundError:
            pass
        if current == current.parent:
            return False
        current = current.parent


def _assert_output_path_safe(path: Path, *, private: bool) -> None:
    if _has_symlink_ancestor(path):
        raise ValueError("narration_cast_artifact_symlink_ancestor_forbidden")
    existed = path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if _has_symlink_ancestor(path) or path.parent.is_symlink() or path.is_symlink():
        raise ValueError("narration_cast_artifact_symlink_forbidden")
    parent_stat = path.parent.lstat()
    if not stat.S_ISDIR(parent_stat.st_mode):
        raise ValueError("narration_cast_artifact_parent_not_directory")
    if private:
        if not existed:
            path.parent.chmod(0o700)
            parent_stat = path.parent.lstat()
        if parent_stat.st_uid != os.geteuid() or parent_stat.st_mode & 0o077:
            raise ValueError("narration_cast_private_parent_permissions_invalid")


def write_json_artifact(
    path: Path,
    payload: Mapping[str, object],
    *,
    private: bool,
) -> None:
    _assert_output_path_safe(path, private=private)
    file_mode = 0o600 if private else 0o644
    # A public receipt may live in a shared or sticky directory such as /tmp,
    # or beside a private artifact in a mode-0700 directory. Never mutate an
    # existing public parent: the receipt's own mode is the security boundary.
    document = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), file_mode)
            handle.write(document)
            handle.flush()
            os.fsync(handle.fileno())
        if path.is_symlink():
            raise ValueError("narration_cast_artifact_symlink_forbidden")
        os.replace(temporary_path, path)
        path.chmod(file_mode)
        directory_descriptor = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary_path.unlink(missing_ok=True)


def _read_bounded_file_via_dirfd(
    path: Path,
    *,
    max_bytes: int,
    private: bool,
    missing_code: str,
    owner_code: str,
    permissions_code: str,
    parent_permissions_code: str,
    size_code: str,
) -> bytes:
    if max_bytes <= 0 or _has_symlink_ancestor(path):
        raise ValueError(missing_code)
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        parent_descriptor = os.open(path.parent, directory_flags)
    except OSError as exc:
        raise ValueError(missing_code) from exc
    try:
        parent_stat = os.fstat(parent_descriptor)
        if private and (
            parent_stat.st_uid != os.geteuid() or parent_stat.st_mode & 0o077
        ):
            raise ValueError(parent_permissions_code)
        try:
            descriptor = os.open(path.name, file_flags, dir_fd=parent_descriptor)
        except OSError as exc:
            raise ValueError(missing_code) from exc
        try:
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode):
                raise ValueError(missing_code)
            if private and file_stat.st_uid != os.geteuid():
                raise ValueError(owner_code)
            if private and file_stat.st_mode & 0o077:
                raise ValueError(permissions_code)
            if file_stat.st_size <= 0 or file_stat.st_size > max_bytes:
                raise ValueError(size_code)
            payload = bytearray()
            while len(payload) <= max_bytes:
                chunk = os.read(descriptor, min(64 * 1024, max_bytes + 1 - len(payload)))
                if not chunk:
                    break
                payload.extend(chunk)
            if not payload or len(payload) > max_bytes:
                raise ValueError(size_code)
            return bytes(payload)
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_descriptor)


def read_json_artifact(
    path: Path,
    *,
    private: bool,
    max_bytes: int = MAX_PRIVATE_ARTIFACT_BYTES,
) -> dict[str, object]:
    raw = _read_bounded_file_via_dirfd(
        path,
        max_bytes=max_bytes,
        private=private,
        missing_code="narration_cast_artifact_missing_or_symlink",
        owner_code="narration_cast_private_artifact_owner_invalid",
        permissions_code="narration_cast_private_artifact_permissions_invalid",
        parent_permissions_code="narration_cast_private_parent_permissions_invalid",
        size_code="narration_cast_artifact_size_invalid",
    )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("narration_cast_artifact_json_invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("narration_cast_artifact_object_required")
    return dict(payload)


def read_signing_secret(path: Path) -> bytes:
    payload = _read_bounded_file_via_dirfd(
        path,
        max_bytes=MAX_SIGNING_SECRET_BYTES,
        private=True,
        missing_code="review_signing_secret_file_missing_or_symlink",
        owner_code="review_signing_secret_owner_invalid",
        permissions_code="review_signing_secret_permissions_invalid",
        parent_permissions_code="review_signing_secret_parent_permissions_invalid",
        size_code="review_signing_secret_size_invalid",
    )
    return _signing_secret(payload.rstrip(b"\r\n"))
