from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
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

from app.services.audiobook_narration_planner import (
    CASTING_TRAIT_POLICY_NAME,
    PLANNER_CONTRACT_NAME,
    PlannerChapter,
    plan_narration,
)


WORK_PACKAGE_CONTRACT_NAME = "ea.memorial_narration_work_package.v4"
CAST_HANDOFF_CONTRACT_NAME = "ea.audiobook_speaker_cast_handoff.v3"
RECEIPT_CONTRACT_NAME = "ea.memorial_narration_work_package_receipt.v4"
REQUIRED_NARRATION_SOURCE_SCOPE = "memorial_audiobook_narration"
REQUIRED_SPEAKER_ATTRIBUTION_SCOPE = (
    "memorial_audiobook_speaker_attribution"
)
REQUIRED_SPEAKER_CASTING_SCOPE = "memorial_audiobook_speaker_casting_traits"
MAX_SPEAKER_CASTING_REVIEW_TTL = timedelta(days=30)

_APPROVED_REVIEW_STATUSES = frozenset({"approved", "published"})
_ARCHIVE_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,127}")
_MAX_ARCHIVE_MANIFEST_BYTES = 256 * 1024
_MAX_ARCHIVE_SOURCE_BYTES = 4 * 1024 * 1024
_MAX_JSON_INPUT_BYTES = 4 * 1024 * 1024
_MAX_APPROVED_SOURCE_COUNT = 128
_MAX_APPROVED_SOURCE_BYTES = 16 * 1024 * 1024
_PROFILE_TRAIT_ALIASES = {
    "gender_presentation": ("gender_presentation", "gender"),
    "age_band": ("age_band", "approximate_age", "age_range", "age"),
    "cultural_or_ethnic_background": (
        "cultural_or_ethnic_background",
        "cultural_background",
        "cultural_identity",
        "ethnic_background",
        "ethnicity",
    ),
    "accent": ("accent", "dialect"),
    "language": ("language", "locale", "spoken_language", "native_language"),
    "role": ("role", "character_role"),
    "style": ("style", "performance_style"),
}
_PROFILE_REFERENCE_KEYS = (
    "speaker_profile_id",
    "profile_id",
    "voice_profile_ref",
    "voice_profile_id",
)


@dataclass(frozen=True)
class _ApprovedSource:
    href: str
    text: str
    kind: str
    review_status: str
    narration_review_evidence_sha256: str


def _stable_json_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _profile_key(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip()).casefold()
    return "".join(char for char in normalized if char.isalnum())


def _normalized_text(value: object) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or "")).strip())


def _approved_review_status(value: object, *, allow_empty: bool) -> bool:
    status = str(value or "").strip().casefold()
    return (allow_empty and not status) or status in _APPROVED_REVIEW_STATUSES


def _narration_review_decision(
    value: object,
    *,
    source_text: str,
    exclusion_prefix: str,
) -> tuple[str, str]:
    if not isinstance(value, Mapping):
        return "", f"{exclusion_prefix}_narration_review_missing"
    review = dict(value)
    if str(review.get("status") or "").strip().casefold() != "approved":
        return "", f"{exclusion_prefix}_narration_review_not_approved"
    raw_scope = review.get("scope")
    scopes = (
        [str(item or "").strip() for item in raw_scope]
        if isinstance(raw_scope, list)
        else []
    )
    if scopes != [REQUIRED_NARRATION_SOURCE_SCOPE]:
        return "", f"{exclusion_prefix}_narration_scope_invalid"
    if review.get("revoked") is True:
        return "", f"{exclusion_prefix}_narration_review_revoked"
    if review.get("revoked") is not False:
        return "", f"{exclusion_prefix}_narration_revocation_state_missing"
    expected_source_sha256 = _text_sha256(source_text)
    reviewed_source_sha256 = str(review.get("source_text_sha256") or "").strip()
    if re.fullmatch(r"[0-9a-f]{64}", reviewed_source_sha256) is None:
        return "", f"{exclusion_prefix}_narration_source_sha256_invalid"
    if not hmac.compare_digest(reviewed_source_sha256, expected_source_sha256):
        return "", f"{exclusion_prefix}_narration_source_sha256_mismatch"
    safe_evidence = {
        "status": "approved",
        "scope": [REQUIRED_NARRATION_SOURCE_SCOPE],
        "revoked": False,
        "source_text_sha256": expected_source_sha256,
    }
    return _stable_json_sha256(safe_evidence), ""


def _card_source(
    raw: Mapping[str, object],
    *,
    slug: str,
    index: int,
) -> tuple[_ApprovedSource | None, str]:
    if str(raw.get("visibility") or "").strip().casefold() != "public":
        return None, "memorial_card_not_explicitly_public"
    if raw.get("approved") is not True:
        return None, "memorial_card_not_approved"
    if not _approved_review_status(raw.get("review_status"), allow_empty=False):
        return None, "memorial_card_review_not_approved"

    public_excerpt = raw.get("public_excerpt")
    text_value = (
        public_excerpt
        if isinstance(public_excerpt, str) and public_excerpt.strip()
        else raw.get("body")
    )
    if not isinstance(text_value, str) or not text_value.strip():
        return None, "memorial_card_text_missing"
    narration_review_evidence_sha256, narration_reason = (
        _narration_review_decision(
            raw.get("narration_review"),
            source_text=text_value,
            exclusion_prefix="memorial_card",
        )
    )
    if narration_reason:
        return None, narration_reason

    explicit_id = _normalized_text(raw.get("id"))
    token = (
        explicit_id
        or _text_sha256(f"{index}:{_normalized_text(raw.get('title'))}")[:16]
    )
    token = re.sub(r"[^a-zA-Z0-9_-]+", "-", token).strip("-") or f"card-{index}"
    return (
        _ApprovedSource(
            href=f"memorial://{slug}/memory-cards/{token}",
            text=text_value,
            kind="public_memory_card",
            review_status=str(raw.get("review_status") or "public_manifest_curated"),
            narration_review_evidence_sha256=narration_review_evidence_sha256,
        ),
        "",
    )


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(
            _read_contained_regular_text(
                path,
                root=path.parent,
                max_bytes=_MAX_JSON_INPUT_BYTES,
            )
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _read_contained_regular_text(
    path: Path,
    *,
    root: Path,
    max_bytes: int,
) -> str:
    if max_bytes <= 0 or _has_symlink_ancestor(path) or path.is_symlink():
        raise ValueError("narration_source_file_unsafe")
    resolved_root = root.resolve(strict=True)
    resolved_path = path.resolve(strict=True)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("narration_source_path_outside_root") from exc
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(resolved_path, flags)
    try:
        file_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_size <= 0
            or file_stat.st_size > max_bytes
        ):
            raise ValueError("narration_source_file_unsafe")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            payload = handle.read(max_bytes + 1)
        if not payload or len(payload) > max_bytes:
            raise ValueError("narration_source_file_unsafe")
        return payload.decode("utf-8")
    finally:
        os.close(descriptor)


def _archive_source(
    raw: Mapping[str, object],
    *,
    slug: str,
    archive_root: Path | None,
) -> tuple[_ApprovedSource | None, str]:
    if str(raw.get("audience") or "").strip().casefold() != "public":
        return None, "archive_entry_not_explicitly_public"
    # The registry's published review state plus the document manifest's
    # explicit approval are the two authoritative publication gates. An
    # explicit registry denial still wins.
    if raw.get("approved") is False:
        return None, "archive_entry_not_approved"
    if not _approved_review_status(raw.get("review_status"), allow_empty=False):
        return None, "archive_entry_review_not_approved"
    if archive_root is None:
        return None, "archive_root_unavailable"

    publication_slug = str(raw.get("slug") or raw.get("id") or "").strip().casefold()
    if _ARCHIVE_SLUG_RE.fullmatch(publication_slug) is None:
        return None, "archive_entry_slug_invalid"
    public_root = (archive_root / "public").resolve()
    document_root = (public_root / publication_slug).resolve()
    try:
        document_root.relative_to(public_root)
    except ValueError:
        return None, "archive_entry_path_outside_public_root"

    try:
        manifest_text = _read_contained_regular_text(
            document_root / "manifest.json",
            root=document_root,
            max_bytes=_MAX_ARCHIVE_MANIFEST_BYTES,
        )
        parsed_manifest = json.loads(manifest_text)
        document_manifest = (
            dict(parsed_manifest) if isinstance(parsed_manifest, dict) else {}
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None, "archive_document_manifest_missing_or_unsafe"
    if str(document_manifest.get("audience") or "").strip().casefold() != "public":
        return None, "archive_document_not_explicitly_public"
    if document_manifest.get("approved") is not True:
        return None, "archive_document_not_approved"
    if not _approved_review_status(
        document_manifest.get("review_status"), allow_empty=False
    ):
        return None, "archive_document_review_not_approved"

    source_path = document_root / "source.md"
    try:
        source_text = _read_contained_regular_text(
            source_path,
            root=document_root,
            max_bytes=_MAX_ARCHIVE_SOURCE_BYTES,
        )
    except (OSError, UnicodeDecodeError, ValueError):
        return None, "archive_document_source_missing_or_unsafe"
    if not source_text.strip():
        return None, "archive_document_source_empty"
    narration_review_evidence_sha256, narration_reason = (
        _narration_review_decision(
            document_manifest.get("narration_review"),
            source_text=source_text,
            exclusion_prefix="archive_document",
        )
    )
    if narration_reason:
        return None, narration_reason
    return (
        _ApprovedSource(
            href=f"archive://{slug}/{publication_slug}/source.md",
            text=source_text,
            kind="approved_public_archive_document",
            review_status=str(document_manifest.get("review_status") or "approved"),
            narration_review_evidence_sha256=narration_review_evidence_sha256,
        ),
        "",
    )


def _collect_approved_sources(
    *,
    slug: str,
    memorial_manifest: Mapping[str, object],
    archive_registry: Mapping[str, object] | None,
    archive_root: Path | None,
) -> tuple[list[_ApprovedSource], Counter[str]]:
    sources: list[_ApprovedSource] = []
    excluded: Counter[str] = Counter()
    seen_hrefs: set[str] = set()
    approved_source_bytes = 0
    approved_source_byte_limit_reached = False

    def _append_source(source: _ApprovedSource) -> None:
        nonlocal approved_source_bytes, approved_source_byte_limit_reached
        if source.href in seen_hrefs:
            excluded["duplicate_public_source"] += 1
            return
        encoded_size = len(source.text.encode("utf-8"))
        if len(sources) >= _MAX_APPROVED_SOURCE_COUNT:
            excluded["approved_source_count_limit_exceeded"] += 1
            return
        if approved_source_bytes + encoded_size > _MAX_APPROVED_SOURCE_BYTES:
            excluded["approved_source_byte_limit_exceeded"] += 1
            approved_source_byte_limit_reached = True
            return
        seen_hrefs.add(source.href)
        sources.append(source)
        approved_source_bytes += encoded_size

    raw_cards = memorial_manifest.get("memory_cards")
    for index, raw in enumerate(
        raw_cards if isinstance(raw_cards, list) else [], start=1
    ):
        if not isinstance(raw, Mapping):
            excluded["memorial_card_invalid"] += 1
            continue
        source, reason = _card_source(raw, slug=slug, index=index)
        if source is None:
            excluded[reason] += 1
        else:
            _append_source(source)

    registry = dict(archive_registry or {})
    raw_publications = registry.get("fliplink_publications")
    for raw in raw_publications if isinstance(raw_publications, list) else []:
        if (
            len(sources) >= _MAX_APPROVED_SOURCE_COUNT
            or approved_source_byte_limit_reached
            or approved_source_bytes >= _MAX_APPROVED_SOURCE_BYTES
        ):
            excluded["approved_source_limit_reached"] += 1
            continue
        if not isinstance(raw, Mapping):
            excluded["archive_entry_invalid"] += 1
            continue
        source, reason = _archive_source(raw, slug=slug, archive_root=archive_root)
        if source is None:
            excluded[reason] += 1
        else:
            _append_source(source)
    return sources, excluded


def _speaker_attribution_span_fingerprint(row: Mapping[str, object]) -> str:
    return _stable_json_sha256(
        {
            "speaker_id": str(row.get("speaker_id") or ""),
            "source_chapter_index": int(row.get("source_chapter_index") or 0),
            "source_href": str(row.get("source_href") or ""),
            "char_start": int(row.get("char_start") or 0),
            "char_end": int(row.get("char_end") or 0),
            "source_text_sha256": str(row.get("source_text_sha256") or ""),
            "attribution_provenance": str(
                row.get("attribution_provenance") or ""
            ),
            "attribution_confidence": round(
                float(row.get("attribution_confidence") or 0.0), 3
            ),
        }
    )


def _speaker_attribution_requirements(
    plan: Mapping[str, object],
) -> list[dict[str, object]]:
    requirements: list[dict[str, object]] = []
    for raw in list(plan.get("spans") or []):
        if not isinstance(raw, Mapping) or str(raw.get("kind") or "") != "dialogue":
            continue
        speaker_id = str(raw.get("speaker_id") or "")
        confidence = float(raw.get("attribution_confidence") or 0.0)
        if confidence >= 0.8 and not speaker_id.startswith("speaker_unknown_"):
            continue
        requirements.append(
            {
                "speaker_id": speaker_id,
                "source_chapter_index": int(raw.get("source_chapter_index") or 0),
                "source_href": str(raw.get("source_href") or ""),
                "char_start": int(raw.get("char_start") or 0),
                "char_end": int(raw.get("char_end") or 0),
                "source_text_sha256": str(raw.get("source_text_sha256") or ""),
                "attribution_provenance": str(
                    raw.get("attribution_provenance") or ""
                ),
                "attribution_confidence": round(confidence, 3),
                "span_fingerprint": _speaker_attribution_span_fingerprint(raw),
            }
        )
    requirements.sort(
        key=lambda row: (
            int(row["source_chapter_index"]),
            int(row["char_start"]),
            str(row["speaker_id"]),
        )
    )
    return requirements


def _speaker_attribution_review_decisions(
    memorial_manifest: Mapping[str, object],
    requirements: list[dict[str, object]],
    *,
    observed_at: datetime,
) -> tuple[list[dict[str, object]], Counter[str]]:
    by_fingerprint = {
        str(row["span_fingerprint"]): row for row in requirements
    }
    accepted: dict[str, tuple[str, str]] = {}
    duplicate_fingerprints: set[str] = set()
    observed_current_fingerprints: set[str] = set()
    excluded: Counter[str] = Counter()
    raw_reviews = memorial_manifest.get("speaker_attribution_reviews")
    for raw in raw_reviews if isinstance(raw_reviews, list) else []:
        if not isinstance(raw, Mapping):
            excluded["speaker_attribution_review_invalid"] += 1
            continue
        fingerprint = str(raw.get("span_fingerprint") or "").strip()
        requirement = by_fingerprint.get(fingerprint)
        if requirement is None:
            excluded["speaker_attribution_review_not_current"] += 1
            continue
        if (
            fingerprint in observed_current_fingerprints
            or fingerprint in duplicate_fingerprints
        ):
            accepted.pop(fingerprint, None)
            duplicate_fingerprints.add(fingerprint)
            excluded["speaker_attribution_review_duplicate"] += 1
            continue
        observed_current_fingerprints.add(fingerprint)
        if str(raw.get("status") or "").strip().casefold() != "approved":
            excluded["speaker_attribution_review_not_approved"] += 1
            continue
        raw_scope = raw.get("scope")
        scopes = (
            [str(item or "").strip() for item in raw_scope]
            if isinstance(raw_scope, list)
            else []
        )
        if scopes != [REQUIRED_SPEAKER_ATTRIBUTION_SCOPE]:
            excluded["speaker_attribution_review_scope_invalid"] += 1
            continue
        if raw.get("revoked") is not False:
            excluded["speaker_attribution_review_revocation_state_invalid"] += 1
            continue
        authority_classes = [
            authority_class
            for key, authority_class in (
                ("approved_by_family", "family"),
                ("approved_by_user", "user"),
                ("approved_by_reviewer", "reviewer"),
            )
            if raw.get(key) is True
        ]
        if len(authority_classes) != 1:
            excluded["speaker_attribution_review_approver_missing"] += 1
            continue
        authority_class = authority_classes[0]
        reviewed_at = _normalized_text(raw.get("reviewed_at"))
        if not reviewed_at:
            excluded["speaker_attribution_review_timestamp_missing"] += 1
            continue
        try:
            reviewed_datetime = datetime.fromisoformat(
                reviewed_at.replace("Z", "+00:00")
            )
        except ValueError:
            reviewed_datetime = None
        if reviewed_datetime is None or reviewed_datetime.tzinfo is None:
            excluded["speaker_attribution_review_timestamp_invalid"] += 1
            continue
        if reviewed_datetime.astimezone(UTC) > observed_at + timedelta(minutes=5):
            excluded["speaker_attribution_review_timestamp_in_future"] += 1
            continue
        if str(raw.get("speaker_id") or "") != str(
            requirement["speaker_id"]
        ):
            excluded["speaker_attribution_review_speaker_mismatch"] += 1
            continue
        if str(raw.get("source_text_sha256") or "") != str(
            requirement["source_text_sha256"]
        ):
            excluded["speaker_attribution_review_source_mismatch"] += 1
            continue
        accepted[fingerprint] = (
            _stable_json_sha256(
                {
                    "status": "approved",
                    "scope": [REQUIRED_SPEAKER_ATTRIBUTION_SCOPE],
                    "revoked": False,
                    "authority_class": authority_class,
                    "speaker_id": str(requirement["speaker_id"]),
                    "span_fingerprint": fingerprint,
                    "source_text_sha256": str(
                        requirement["source_text_sha256"]
                    ),
                    "reviewed_at": reviewed_at,
                }
            ),
            authority_class,
        )
    reviewed = [
        {
            **row,
            "review_evidence_sha256": (
                accepted.get(str(row["span_fingerprint"]), ("", ""))[0]
            ),
            "review_authority_class": (
                accepted.get(str(row["span_fingerprint"]), ("", ""))[1]
            ),
            "review_approved": str(row["span_fingerprint"]) in accepted,
        }
        for row in sorted(
            requirements,
            key=lambda item: str(item.get("speaker_key") or ""),
        )
    ]
    return reviewed, excluded


def _speaker_profile_trait_values(
    profile: Mapping[str, object],
) -> dict[str, str]:
    traits: dict[str, str] = {}
    for canonical_key, aliases in _PROFILE_TRAIT_ALIASES.items():
        value = ""
        for key in aliases:
            value = _normalized_text(profile.get(key))
            if value:
                break
        if not value:
            continue
        traits[canonical_key] = value
    return traits


def _speaker_casting_review_decision(
    *,
    label: str,
    profile: Mapping[str, object],
    observed_at: datetime,
) -> tuple[dict[str, object], str]:
    trait_values = _speaker_profile_trait_values(profile)
    profile_ref = next(
        (
            str(profile.get(reference_key) or "").strip()
            for reference_key in _PROFILE_REFERENCE_KEYS
            if str(profile.get(reference_key) or "").strip()
        ),
        "",
    )
    requirement = {
        "speaker_key": _profile_key(label),
        "speaker_profile_ref_sha256": (
            _text_sha256(profile_ref) if profile_ref else ""
        ),
        "speaker_traits_sha256": _stable_json_sha256(trait_values),
        "required_scope": REQUIRED_SPEAKER_CASTING_SCOPE,
    }
    raw_review = profile.get("casting_review")
    if not isinstance(raw_review, Mapping):
        return requirement, "speaker_casting_review_missing"
    review = dict(raw_review)
    if str(review.get("status") or "").strip().casefold() != "approved":
        return requirement, "speaker_casting_review_not_approved"
    raw_scope = review.get("scope")
    scopes = (
        [str(item or "").strip() for item in raw_scope]
        if isinstance(raw_scope, list)
        else []
    )
    if scopes != [REQUIRED_SPEAKER_CASTING_SCOPE]:
        return requirement, "speaker_casting_review_scope_invalid"
    if review.get("revoked") is not False:
        return requirement, "speaker_casting_review_revocation_state_invalid"
    authority_classes = [
        authority_class
        for key, authority_class in (
            ("approved_by_family", "family"),
            ("approved_by_user", "user"),
            ("approved_by_reviewer", "reviewer"),
        )
        if review.get(key) is True
    ]
    if len(authority_classes) != 1:
        return requirement, "speaker_casting_review_approver_invalid"
    if not profile_ref:
        return requirement, "speaker_casting_profile_ref_missing"
    if str(review.get("speaker_profile_ref_sha256") or "") != str(
        requirement["speaker_profile_ref_sha256"]
    ):
        return requirement, "speaker_casting_profile_ref_mismatch"
    if str(review.get("speaker_traits_sha256") or "") != str(
        requirement["speaker_traits_sha256"]
    ):
        return requirement, "speaker_casting_traits_hash_mismatch"
    try:
        reviewed_at = datetime.fromisoformat(
            str(review.get("reviewed_at") or "").replace("Z", "+00:00")
        )
        expires_at = datetime.fromisoformat(
            str(review.get("expires_at") or "").replace("Z", "+00:00")
        )
    except ValueError:
        return requirement, "speaker_casting_review_timestamp_invalid"
    if reviewed_at.tzinfo is None or expires_at.tzinfo is None:
        return requirement, "speaker_casting_review_timestamp_invalid"
    reviewed_at = reviewed_at.astimezone(UTC)
    expires_at = expires_at.astimezone(UTC)
    if reviewed_at > observed_at + timedelta(minutes=5):
        return requirement, "speaker_casting_review_timestamp_in_future"
    if expires_at <= observed_at:
        return requirement, "speaker_casting_review_expired"
    if expires_at <= reviewed_at:
        return requirement, "speaker_casting_review_expiry_not_after_review"
    if expires_at - reviewed_at > MAX_SPEAKER_CASTING_REVIEW_TTL:
        return requirement, "speaker_casting_review_expiry_too_distant"
    conflict_acknowledged = review.get("source_conflict_acknowledged") is True
    reviewed_plan_sha256 = str(review.get("reviewed_plan_sha256") or "")
    evidence_payload = {
        **requirement,
        "status": "approved",
        "scope": [REQUIRED_SPEAKER_CASTING_SCOPE],
        "revoked": False,
        "authority_class": authority_classes[0],
        "reviewed_at": reviewed_at.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "source_conflict_acknowledged": conflict_acknowledged,
        "reviewed_plan_sha256": reviewed_plan_sha256,
    }
    evidence = {
        **evidence_payload,
        "review_evidence_sha256": _stable_json_sha256(evidence_payload),
    }
    return evidence, ""


def _explicit_trait_payload(
    profile: Mapping[str, object],
    *,
    casting_review_evidence: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    traits: dict[str, dict[str, object]] = {}
    for canonical_key, value in _speaker_profile_trait_values(profile).items():
        traits[canonical_key] = {
            "value": value,
            "provenance": "explicit_approved_speaker_profile",
            "confidence": 1.0,
            "sensitive_hint": canonical_key == "cultural_or_ethnic_background",
            "casting_eligible": True,
            "requires_human_approval": False,
            "casting_approved": True,
            "casting_review_evidence_sha256": (
                str(casting_review_evidence.get("review_evidence_sha256") or "")
            ),
            "casting_review_scope": REQUIRED_SPEAKER_CASTING_SCOPE,
            "casting_review_revoked": False,
            "casting_review_authority_class": str(
                casting_review_evidence.get("authority_class") or ""
            ),
            "casting_review_reviewed_at": str(
                casting_review_evidence.get("reviewed_at") or ""
            ),
            "casting_review_expires_at": str(
                casting_review_evidence.get("expires_at") or ""
            ),
        }
    return traits


def _approved_speaker_profiles(
    profiles: Mapping[str, Mapping[str, object]] | None,
    *,
    observed_at: datetime,
) -> tuple[
    dict[str, dict[str, object]],
    dict[str, dict[str, dict[str, object]]],
    dict[str, str],
    dict[str, dict[str, object]],
    list[dict[str, object]],
    Counter[str],
]:
    planner_profiles: dict[str, dict[str, object]] = {}
    traits_by_key: dict[str, dict[str, dict[str, object]]] = {}
    profile_refs: dict[str, str] = {}
    reviews_by_key: dict[str, dict[str, object]] = {}
    review_requirements: list[dict[str, object]] = []
    excluded: Counter[str] = Counter()
    labels_by_key: dict[str, list[str]] = {}
    for label, raw_profile in dict(profiles or {}).items():
        if not isinstance(raw_profile, Mapping):
            continue
        key = _profile_key(label)
        if not key:
            continue
        labels_by_key.setdefault(key, []).append(str(label))
        if raw_profile.get("casting_approved") is not True:
            continue
        if not (
            raw_profile.get("approved") is True
            or _approved_review_status(raw_profile.get("review_status"), allow_empty=False)
        ):
            continue
        review_evidence, review_reason = _speaker_casting_review_decision(
            label=str(label),
            profile=raw_profile,
            observed_at=observed_at,
        )
        review_requirements.append(
            {
                "speaker_label": str(label),
                "speaker_key": key,
                "speaker_profile_ref_sha256": str(
                    review_evidence.get("speaker_profile_ref_sha256") or ""
                ),
                "speaker_traits_sha256": str(
                    review_evidence.get("speaker_traits_sha256") or ""
                ),
                "required_scope": REQUIRED_SPEAKER_CASTING_SCOPE,
                "review_approved": not review_reason,
                "review_reason": review_reason,
                "review_evidence_sha256": str(
                    review_evidence.get("review_evidence_sha256") or ""
                ),
                "review_authority_class": str(
                    review_evidence.get("authority_class") or ""
                ),
                "reviewed_at": str(
                    review_evidence.get("reviewed_at") or ""
                ),
                "expires_at": str(
                    review_evidence.get("expires_at") or ""
                ),
                "revoked": (
                    review_evidence.get("revoked")
                    if not review_reason
                    else None
                ),
                "source_conflict_acknowledged": (
                    review_evidence.get("source_conflict_acknowledged") is True
                ),
                "reviewed_plan_sha256": str(
                    review_evidence.get("reviewed_plan_sha256") or ""
                ),
            }
        )
        if review_reason:
            excluded[review_reason] += 1
            continue
        traits = _explicit_trait_payload(
            raw_profile,
            casting_review_evidence=review_evidence,
        )
        planner_profiles[str(label)] = {
            name: str(evidence.get("value") or "") for name, evidence in traits.items()
        }
        traits_by_key[key] = traits
        reviews_by_key[key] = review_evidence
        profile_ref = next(
            (
                str(raw_profile.get(reference_key) or "").strip()
                for reference_key in _PROFILE_REFERENCE_KEYS
                if str(raw_profile.get(reference_key) or "").strip()
            ),
            "",
        )
        profile_refs[key] = _stable_json_sha256(
            {
                "profile_ref": profile_ref,
                "speaker_key": key,
                "approved_traits": traits,
            }
        )
    duplicate_keys = {
        key for key, labels in labels_by_key.items() if len(labels) > 1
    }
    for key in duplicate_keys:
        for label in labels_by_key[key]:
            planner_profiles.pop(label, None)
        traits_by_key.pop(key, None)
        profile_refs.pop(key, None)
        reviews_by_key.pop(key, None)
        excluded["speaker_casting_profile_key_collision"] += 1
    for requirement in review_requirements:
        if str(requirement.get("speaker_key") or "") in duplicate_keys:
            requirement["review_approved"] = False
            requirement["review_reason"] = (
                "speaker_casting_profile_key_collision"
            )
            requirement["review_evidence_sha256"] = ""
    review_requirements.sort(key=lambda row: str(row["speaker_key"]))
    return (
        planner_profiles,
        traits_by_key,
        profile_refs,
        reviews_by_key,
        review_requirements,
        excluded,
    )


def _speaker_casting_conflict_requirements(
    plan: Mapping[str, object],
    *,
    casting_reviews_by_key: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    plan_sha256 = str(plan.get("plan_sha256") or "")
    requirements: list[dict[str, object]] = []
    for raw_speaker in list(plan.get("speakers") or []):
        if not isinstance(raw_speaker, Mapping):
            continue
        speaker_id = str(raw_speaker.get("speaker_id") or "")
        speaker_key = _profile_key(raw_speaker.get("speaker_label"))
        casting_review = dict(casting_reviews_by_key.get(speaker_key) or {})
        for trait_kind, raw_evidence in dict(
            raw_speaker.get("traits") or {}
        ).items():
            if not isinstance(raw_evidence, Mapping) or raw_evidence.get(
                "conflicting_evidence_present"
            ) is not True:
                continue
            base = {
                "speaker_id": speaker_id,
                "speaker_key": speaker_key,
                "trait_kind": str(trait_kind),
                "approved_trait_value_sha256": _text_sha256(
                    raw_evidence.get("value")
                ),
                "superseded_provenance": str(
                    raw_evidence.get("superseded_provenance") or ""
                ),
                "superseded_evidence_sha256": str(
                    raw_evidence.get("superseded_evidence_sha256") or ""
                ),
                "reviewed_plan_sha256": plan_sha256,
            }
            conflict_fingerprint = _stable_json_sha256(base)
            approved = (
                casting_review.get("source_conflict_acknowledged") is True
                and str(casting_review.get("reviewed_plan_sha256") or "")
                == plan_sha256
            )
            conflict_review_evidence_sha256 = (
                _stable_json_sha256(
                    {
                        **base,
                        "conflict_fingerprint": conflict_fingerprint,
                        "casting_review_evidence_sha256": str(
                            casting_review.get("review_evidence_sha256") or ""
                        ),
                        "source_conflict_acknowledged": True,
                    }
                )
                if approved
                else ""
            )
            requirements.append(
                {
                    **base,
                    "conflict_fingerprint": conflict_fingerprint,
                    "conflict_review_approved": approved,
                    "conflict_review_evidence_sha256": (
                        conflict_review_evidence_sha256
                    ),
                }
            )
    requirements.sort(
        key=lambda row: (
            str(row["speaker_id"]),
            str(row["trait_kind"]),
        )
    )
    return requirements


def _sanitize_plan_traits(
    plan: Mapping[str, object],
    *,
    approved_traits_by_key: Mapping[str, Mapping[str, Mapping[str, object]]],
    casting_conflict_requirements: list[dict[str, object]],
) -> dict[str, object]:
    sanitized = deepcopy(dict(plan))
    for collection_key in ("speakers", "spans", "passages"):
        raw_rows = sanitized.get(collection_key)
        if not isinstance(raw_rows, list):
            continue
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            speaker_key = _profile_key(row.get("speaker_label"))
            sanitized_traits = {
                name: dict(evidence)
                for name, evidence in dict(
                    approved_traits_by_key.get(speaker_key) or {}
                ).items()
            }
            speaker_id = str(row.get("speaker_id") or "")
            for trait_kind, evidence in sanitized_traits.items():
                conflict = next(
                    (
                        requirement
                        for requirement in casting_conflict_requirements
                        if str(requirement.get("speaker_id") or "")
                        == speaker_id
                        and str(requirement.get("trait_kind") or "")
                        == str(trait_kind)
                    ),
                    None,
                )
                if conflict is not None:
                    evidence["conflicting_evidence_present"] = True
                    evidence["superseded_provenance"] = str(
                        conflict.get("superseded_provenance") or ""
                    )
                    evidence["superseded_evidence_sha256"] = str(
                        conflict.get("superseded_evidence_sha256") or ""
                    )
                    evidence["conflict_review_approved"] = (
                        conflict.get("conflict_review_approved") is True
                    )
                    evidence["conflict_review_evidence_sha256"] = str(
                        conflict.get("conflict_review_evidence_sha256") or ""
                    )
            row["traits"] = sanitized_traits
            row["traits_from_explicit_approved_profile_only"] = True
    sanitized["demographic_trait_policy"] = "explicit_approved_profiles_only"
    sanitized["source_inferred_trait_values_removed"] = True
    sanitized["casting_trait_policy"] = CASTING_TRAIT_POLICY_NAME
    sanitized["planner_plan_sha256"] = str(
        sanitized.get("plan_sha256") or ""
    )
    sanitized["casting_plan_sha256"] = _stable_json_sha256(
        {
            key: value
            for key, value in sanitized.items()
            if key != "casting_plan_sha256"
        }
    )
    return sanitized


def _voice_consent_decision(
    voice_profile: Mapping[str, object],
    *,
    required_scope: str,
) -> dict[str, object]:
    raw_consent = voice_profile.get("voice_consent")
    consent = dict(raw_consent) if isinstance(raw_consent, Mapping) else {}
    status = str(consent.get("status") or "").strip().casefold()
    revoked = bool(consent.get("revoked"))
    scopes = {
        str(value or "").strip()
        for value in (
            consent.get("scope") if isinstance(consent.get("scope"), list) else []
        )
        if str(value or "").strip()
    }
    if revoked:
        reason = "voice_consent_revoked"
    elif status != "approved":
        reason = "voice_consent_not_approved"
    elif required_scope not in scopes:
        reason = "voice_consent_scope_missing"
    else:
        reason = ""
    return {
        "authorized": not reason,
        "status": status or "missing",
        "revoked": revoked,
        "required_scope": required_scope,
        "required_scope_present": required_scope in scopes,
        "evidence_sha256": _stable_json_sha256(consent),
        "reason": reason,
    }


def _narrator_profile_ref_sha256(voice_profile: Mapping[str, object]) -> str:
    profile_ref = str(voice_profile.get("voice_profile_id") or "").strip()
    if not profile_ref:
        return ""
    return _text_sha256(profile_ref)


def _speaker_casting_review_evidence_rows(
    requirements: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            "speaker_key": str(row.get("speaker_key") or ""),
            "speaker_profile_ref_sha256": str(
                row.get("speaker_profile_ref_sha256") or ""
            ),
            "speaker_traits_sha256": str(
                row.get("speaker_traits_sha256") or ""
            ),
            "review_evidence_sha256": str(
                row.get("review_evidence_sha256") or ""
            ),
            "review_authority_class": str(
                row.get("review_authority_class") or ""
            ),
            "reviewed_at": str(row.get("reviewed_at") or ""),
            "expires_at": str(row.get("expires_at") or ""),
        }
        for row in sorted(
            requirements,
            key=lambda item: str(item.get("speaker_key") or ""),
        )
    ]


def build_speaker_attribution_review_registry_snapshot(
    *,
    memorial_manifest: Mapping[str, object],
    narration_plan: Mapping[str, object],
    observed_at: datetime | None = None,
) -> dict[str, object]:
    checked_at = (observed_at or datetime.now(UTC)).astimezone(UTC)
    requirements = _speaker_attribution_requirements(narration_plan)
    reviewed, excluded = _speaker_attribution_review_decisions(
        memorial_manifest,
        requirements,
        observed_at=checked_at,
    )
    evidence_rows = [
        {
            "speaker_id": str(row.get("speaker_id") or ""),
            "span_fingerprint": str(row.get("span_fingerprint") or ""),
            "source_text_sha256": str(row.get("source_text_sha256") or ""),
            "review_evidence_sha256": str(
                row.get("review_evidence_sha256") or ""
            ),
            "review_authority_class": str(
                row.get("review_authority_class") or ""
            ),
        }
        for row in reviewed
    ]
    payload: dict[str, object] = {
        "contract_name": (
            "ea.memorial_speaker_attribution_review_registry_snapshot.v1"
        ),
        "version": 1,
        "requirements": reviewed,
        "review_evidence_aggregate_sha256": _stable_json_sha256(
            evidence_rows
        ),
        "excluded_reason_counts": dict(sorted(excluded.items())),
        "private_payload": True,
    }
    payload["snapshot_sha256"] = _stable_json_sha256(payload)
    return payload


def build_speaker_casting_review_registry_snapshot(
    *,
    speaker_profiles: Mapping[str, Mapping[str, object]] | None,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    checked_at = (observed_at or datetime.now(UTC)).astimezone(UTC)
    (
        _planner_profiles,
        _approved_traits,
        _profile_refs,
        _reviews_by_key,
        requirements,
        excluded,
    ) = _approved_speaker_profiles(
        speaker_profiles,
        observed_at=checked_at,
    )
    evidence_rows = _speaker_casting_review_evidence_rows(requirements)
    payload: dict[str, object] = {
        "contract_name": (
            "ea.memorial_speaker_casting_review_registry_snapshot.v1"
        ),
        "version": 1,
        "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
        "requirements": requirements,
        "review_evidence_aggregate_sha256": _stable_json_sha256(
            evidence_rows
        ),
        "excluded_reason_counts": dict(sorted(excluded.items())),
        "private_payload": True,
    }
    payload["snapshot_sha256"] = _stable_json_sha256(
        {
            key: value
            for key, value in payload.items()
            if key != "checked_at"
        }
    )
    return payload


def _cast_handoff(
    *,
    plan: Mapping[str, object],
    consent: Mapping[str, object],
    voice_profile: Mapping[str, object],
    approved_profile_refs: Mapping[str, str],
    attribution_requirements: list[dict[str, object]],
    casting_review_requirements: list[dict[str, object]],
) -> dict[str, object]:
    attribution_review_complete = all(
        row.get("review_approved") is True for row in attribution_requirements
    )
    casting_review_complete = all(
        row.get("review_approved") is True
        for row in casting_review_requirements
    )
    casting_review_evidence_rows = _speaker_casting_review_evidence_rows(
        casting_review_requirements
    )
    casting_review_evidence_aggregate_sha256 = _stable_json_sha256(
        casting_review_evidence_rows
    )
    if consent.get("authorized") is not True:
        return {
            "contract_name": CAST_HANDOFF_CONTRACT_NAME,
            "casting_trait_policy": CASTING_TRAIT_POLICY_NAME,
            "status": "blocked_voice_consent",
            "reason": str(consent.get("reason") or "voice_consent_required"),
            "speakers": [],
            "speaker_attribution_review_required_count": len(
                attribution_requirements
            ),
            "speaker_attribution_review_complete": attribution_review_complete,
            "speaker_casting_review_required_count": len(
                casting_review_requirements
            ),
            "speaker_casting_review_complete": casting_review_complete,
            "speaker_casting_review_evidence_aggregate_sha256": (
                casting_review_evidence_aggregate_sha256
            ),
            "cast_map_sha256": "",
            "raw_voice_ids_embedded": False,
            "sensitive_trait_values_embedded": False,
            "provider_resolution_performed": False,
        }

    rows: list[dict[str, object]] = [
        {
            "speaker_id": "narrator",
            "speaker_role": "narrator",
            "mapping": "approved_memorial_voice_profile",
            "profile_ref_sha256": _narrator_profile_ref_sha256(voice_profile),
            "private_profile_lookup_required": True,
            "explicit_profile": True,
            "attribution_review_required": False,
            "attribution_review_complete": True,
            "casting_review_required": False,
            "casting_review_complete": True,
        }
    ]
    raw_speakers = plan.get("speakers")
    for raw in raw_speakers if isinstance(raw_speakers, list) else []:
        if (
            not isinstance(raw, Mapping)
            or str(raw.get("speaker_id") or "") == "narrator"
        ):
            continue
        speaker_id = str(raw.get("speaker_id") or "speaker_unknown")
        speaker_key = _profile_key(raw.get("speaker_label"))
        explicit_profile = speaker_key in approved_profile_refs
        casting_review = next(
            (
                row
                for row in casting_review_requirements
                if str(row.get("speaker_key") or "") == speaker_key
            ),
            {},
        )
        speaker_attribution_requirements = [
            row
            for row in attribution_requirements
            if str(row.get("speaker_id") or "") == speaker_id
        ]
        speaker_attribution_review_complete = all(
            row.get("review_approved") is True
            for row in speaker_attribution_requirements
        )
        attribution_review_evidence_rows = [
            {
                "span_fingerprint": str(row.get("span_fingerprint") or ""),
                "review_evidence_sha256": str(
                    row.get("review_evidence_sha256") or ""
                ),
                "review_authority_class": str(
                    row.get("review_authority_class") or ""
                ),
            }
            for row in speaker_attribution_requirements
        ]
        ambiguous = (
            speaker_id.startswith("speaker_unknown_")
            or bool(speaker_attribution_requirements)
            or speaker_key == _profile_key("Unknown speaker")
        )
        mapping = (
            "explicit_approved_speaker_profile"
            if explicit_profile
            else "neutral_ambiguity"
            if ambiguous
            else "neutral_unprofiled_speaker"
        )
        rows.append(
            {
                "speaker_id": speaker_id,
                "speaker_role": "dialogue",
                "mapping": mapping,
                "profile_ref_sha256": approved_profile_refs.get(speaker_key, ""),
                "private_profile_lookup_required": explicit_profile,
                "explicit_profile": explicit_profile,
                "neutral_fallback": not explicit_profile,
                "casting_review_required": explicit_profile,
                "casting_review_complete": (
                    not explicit_profile
                    or casting_review.get("review_approved") is True
                ),
                "casting_review_evidence_sha256": str(
                    casting_review.get("review_evidence_sha256") or ""
                ),
                "speaker_traits_sha256": str(
                    casting_review.get("speaker_traits_sha256") or ""
                ),
                "casting_review_expires_at": str(
                    casting_review.get("expires_at") or ""
                ),
                "attribution_review_required": bool(
                    speaker_attribution_requirements
                ),
                "attribution_review_complete": (
                    speaker_attribution_review_complete
                ),
                "attribution_review_required_span_count": len(
                    speaker_attribution_requirements
                ),
                "attribution_review_evidence_aggregate_sha256": (
                    _stable_json_sha256(attribution_review_evidence_rows)
                    if attribution_review_evidence_rows
                    else ""
                ),
            }
        )
    rows.sort(key=lambda row: (str(row["speaker_role"]), str(row["speaker_id"])))
    cast_map_sha256 = _stable_json_sha256(rows)
    return {
        "contract_name": CAST_HANDOFF_CONTRACT_NAME,
        "casting_trait_policy": CASTING_TRAIT_POLICY_NAME,
        "status": (
            "ready_for_private_audiobook_cast_resolution"
            if attribution_review_complete and casting_review_complete
            else "blocked_speaker_attribution_review"
            if not attribution_review_complete
            else "blocked_speaker_casting_review"
        ),
        "reason": (
            ""
            if attribution_review_complete and casting_review_complete
            else "speaker_attribution_review_required"
            if not attribution_review_complete
            else "speaker_casting_review_required"
        ),
        "planner_contract_name": str(plan.get("contract_name") or ""),
        "speakers": rows,
        "speaker_attribution_review_required_count": len(
            attribution_requirements
        ),
        "speaker_attribution_review_complete": attribution_review_complete,
        "speaker_casting_review_required_count": len(
            casting_review_requirements
        ),
        "speaker_casting_review_complete": casting_review_complete,
        "speaker_casting_review_evidence_aggregate_sha256": (
            casting_review_evidence_aggregate_sha256
        ),
        "cast_map_sha256": cast_map_sha256,
        "raw_voice_ids_embedded": False,
        "sensitive_trait_values_embedded": False,
        "provider_resolution_performed": False,
    }


def _empty_plan(*, language: str) -> dict[str, object]:
    plan: dict[str, object] = {
        "contract_name": PLANNER_CONTRACT_NAME,
        "version": 4,
        "status": "blocked_no_approved_public_sources",
        "language": language,
        "speakers": [],
        "spans": [],
        "passages": [],
        "coverage_complete": False,
        "casting_trait_policy": CASTING_TRAIT_POLICY_NAME,
        "private_payload": True,
        "raw_source_text_embedded": False,
    }
    plan["planner_plan_sha256"] = ""
    plan["casting_plan_sha256"] = _stable_json_sha256(plan)
    return plan


def build_memorial_narration_work_package(
    *,
    slug: str,
    memorial_manifest: Mapping[str, object],
    voice_profile: Mapping[str, object],
    archive_registry: Mapping[str, object] | None = None,
    archive_root: Path | None = None,
    speaker_profiles: Mapping[str, Mapping[str, object]] | None = None,
    language: str = "",
    max_chars: int = 1200,
    required_voice_scope: str = "synthesize",
    observed_at: datetime | None = None,
) -> dict[str, object]:
    build_observed_at = (observed_at or datetime.now(UTC)).astimezone(UTC)
    normalized_slug = str(slug or "").strip().casefold()
    if (
        not normalized_slug
        or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", normalized_slug) is None
    ):
        raise ValueError("memorial_slug_invalid")

    selected_language = (
        str(language or "").strip()
        or str(voice_profile.get("lang") or "").strip()
        or "und"
    )
    sources, excluded = _collect_approved_sources(
        slug=normalized_slug,
        memorial_manifest=memorial_manifest,
        archive_registry=archive_registry,
        archive_root=archive_root,
    )
    embedded_profiles: dict[str, Mapping[str, object]] = {}
    raw_embedded_profiles = memorial_manifest.get("speaker_profiles")
    if isinstance(raw_embedded_profiles, Mapping):
        embedded_profiles.update(
            {
                str(key): value
                for key, value in raw_embedded_profiles.items()
                if isinstance(value, Mapping)
            }
        )
    embedded_profiles.update(dict(speaker_profiles or {}))
    (
        planner_profiles,
        approved_traits,
        profile_refs,
        casting_reviews_by_key,
        speaker_casting_review_requirements,
        speaker_casting_review_excluded,
    ) = _approved_speaker_profiles(
        embedded_profiles,
        observed_at=build_observed_at,
    )
    if sources:
        chapters = tuple(
            PlannerChapter(index=index, source_href=source.href, text=source.text)
            for index, source in enumerate(sources, start=1)
        )
        raw_plan = plan_narration(
            chapters,
            language=selected_language,
            max_chars=max_chars,
            approved_speaker_profiles=planner_profiles,
        )
        speaker_casting_conflict_requirements = (
            _speaker_casting_conflict_requirements(
                raw_plan,
                casting_reviews_by_key=casting_reviews_by_key,
            )
        )
        plan = _sanitize_plan_traits(
            raw_plan,
            approved_traits_by_key=approved_traits,
            casting_conflict_requirements=(
                speaker_casting_conflict_requirements
            ),
        )
    else:
        plan = _empty_plan(language=selected_language)
        speaker_casting_conflict_requirements = []
    present_speaker_keys = {
        _profile_key(row.get("speaker_label"))
        for row in list(plan.get("speakers") or [])
        if isinstance(row, Mapping)
        and str(row.get("speaker_id") or "") != "narrator"
    }
    speaker_casting_review_requirements = [
        row
        for row in speaker_casting_review_requirements
        if str(row.get("speaker_key") or "") in present_speaker_keys
    ]
    missing_speaker_casting_reviews = [
        row
        for row in speaker_casting_review_requirements
        if row.get("review_approved") is not True
    ]
    missing_speaker_casting_conflict_reviews = [
        row
        for row in speaker_casting_conflict_requirements
        if row.get("conflict_review_approved") is not True
    ]

    attribution_requirements = _speaker_attribution_requirements(plan)
    attribution_requirements, attribution_review_excluded = (
        _speaker_attribution_review_decisions(
            memorial_manifest,
            attribution_requirements,
            observed_at=build_observed_at,
        )
    )
    missing_attribution_reviews = [
        row
        for row in attribution_requirements
        if row.get("review_approved") is not True
    ]

    consent = _voice_consent_decision(
        voice_profile, required_scope=required_voice_scope
    )
    cast_handoff = _cast_handoff(
        plan=plan,
        consent=consent,
        voice_profile=voice_profile,
        approved_profile_refs=profile_refs,
        attribution_requirements=attribution_requirements,
        casting_review_requirements=speaker_casting_review_requirements,
    )
    cast_handoff_sha256 = _stable_json_sha256(cast_handoff)
    if not sources:
        status = "blocked_no_approved_public_sources"
        reason = status
    elif consent.get("authorized") is not True:
        status = "blocked_voice_consent"
        reason = str(consent.get("reason") or "voice_consent_required")
    elif str(plan.get("status") or "") != "ready":
        status = "blocked_narration_plan"
        reason = str(plan.get("status") or "narration_plan_not_ready")
    elif missing_speaker_casting_reviews:
        status = "blocked_speaker_casting_review"
        reason = "speaker_casting_review_required"
    elif missing_speaker_casting_conflict_reviews:
        status = "blocked_speaker_casting_conflict_review"
        reason = "speaker_casting_conflict_review_required"
    elif missing_attribution_reviews:
        status = "blocked_speaker_attribution_review"
        reason = "speaker_attribution_review_required"
    else:
        status = "ready_for_private_cast_resolution"
        reason = ""

    source_rows = [
        {
            "source_href": source.href,
            "kind": source.kind,
            "review_status": source.review_status,
            "text_sha256": _text_sha256(source.text),
            "narration_review_evidence_sha256": (
                source.narration_review_evidence_sha256
            ),
            "char_count": len(source.text),
            "visibility": "public",
        }
        for source in sources
    ]
    narration_review_evidence_rows = [
        {
            "source_href": source.href,
            "kind": source.kind,
            "text_sha256": _text_sha256(source.text),
            "narration_review_evidence_sha256": (
                source.narration_review_evidence_sha256
            ),
        }
        for source in sources
    ]
    attribution_review_evidence_rows = [
        {
            "speaker_id": str(row.get("speaker_id") or ""),
            "span_fingerprint": str(row.get("span_fingerprint") or ""),
            "source_text_sha256": str(row.get("source_text_sha256") or ""),
            "review_evidence_sha256": str(
                row.get("review_evidence_sha256") or ""
            ),
            "review_authority_class": str(
                row.get("review_authority_class") or ""
            ),
        }
        for row in attribution_requirements
    ]
    speaker_casting_review_evidence_rows = (
        _speaker_casting_review_evidence_rows(
            speaker_casting_review_requirements
        )
    )
    speaker_casting_review_evidence_aggregate_sha256 = _stable_json_sha256(
        speaker_casting_review_evidence_rows
    )
    source_kind_counts = dict(
        sorted(Counter(source.kind for source in sources).items())
    )
    dialogue_cast_rows = [
        row
        for row in list(cast_handoff.get("speakers") or [])
        if isinstance(row, Mapping) and row.get("speaker_role") == "dialogue"
    ]
    receipt: dict[str, object] = {
        "contract_name": RECEIPT_CONTRACT_NAME,
        "status": status,
        "reason": reason,
        # Planning and consent make private resolution eligible, but they do
        # not authorize a provider call.  A separate, hash-bound private cast
        # resolution and human review must pass before synthesis.
        "cast_resolution_authorized": status == "ready_for_private_cast_resolution",
        "render_authorized": False,
        "synthesis_authorized": False,
        "cast_mapping_review_required": True,
        "human_listening_review_required": True,
        "planner_contract_name": str(plan.get("contract_name") or ""),
        "plan_sha256": str(plan.get("plan_sha256") or ""),
        "casting_plan_sha256": str(
            plan.get("casting_plan_sha256") or ""
        ),
        "dialogue_attribution_evidence_sha256": str(
            plan.get("dialogue_attribution_evidence_sha256") or ""
        ),
        "source_aggregate_sha256": _stable_json_sha256(source_rows),
        "purpose_specific_narration_review_required": True,
        "narration_review_scope_array_required": True,
        "required_narration_source_scope": REQUIRED_NARRATION_SOURCE_SCOPE,
        "purpose_specific_speaker_attribution_review_required": True,
        "purpose_specific_speaker_casting_review_required": True,
        "required_speaker_casting_scope": REQUIRED_SPEAKER_CASTING_SCOPE,
        "speaker_casting_review_required_count": len(
            speaker_casting_review_requirements
        ),
        "speaker_casting_review_approved_count": (
            len(speaker_casting_review_requirements)
            - len(missing_speaker_casting_reviews)
        ),
        "speaker_casting_review_evidence_aggregate_sha256": (
            speaker_casting_review_evidence_aggregate_sha256
        ),
        "speaker_casting_review_excluded_reason_counts": dict(
            sorted(speaker_casting_review_excluded.items())
        ),
        "speaker_casting_conflict_review_required_count": len(
            speaker_casting_conflict_requirements
        ),
        "speaker_casting_conflict_review_approved_count": (
            len(speaker_casting_conflict_requirements)
            - len(missing_speaker_casting_conflict_reviews)
        ),
        "speaker_casting_conflict_review_evidence_aggregate_sha256": (
            _stable_json_sha256(speaker_casting_conflict_requirements)
        ),
        "required_speaker_attribution_scope": (
            REQUIRED_SPEAKER_ATTRIBUTION_SCOPE
        ),
        "speaker_attribution_review_required_count": len(
            attribution_requirements
        ),
        "speaker_attribution_review_approved_count": (
            len(attribution_requirements) - len(missing_attribution_reviews)
        ),
        "speaker_attribution_review_evidence_aggregate_sha256": (
            _stable_json_sha256(attribution_review_evidence_rows)
        ),
        "speaker_attribution_review_excluded_reason_counts": dict(
            sorted(attribution_review_excluded.items())
        ),
        "approved_narration_permission_count": len(
            narration_review_evidence_rows
        ),
        "narration_permission_evidence_aggregate_sha256": (
            _stable_json_sha256(narration_review_evidence_rows)
        ),
        "approved_public_source_count": len(sources),
        "approved_public_source_kind_counts": source_kind_counts,
        "excluded_source_count": sum(excluded.values()),
        "excluded_source_reason_counts": dict(sorted(excluded.items())),
        "private_sources_excluded_by_default": True,
        "source_coverage_complete": bool(plan.get("coverage_complete")),
        "narrator_passage_count": sum(
            1
            for row in list(plan.get("passages") or [])
            if isinstance(row, Mapping) and row.get("speaker_role") == "narrator"
        ),
        "dialogue_passage_count": sum(
            1
            for row in list(plan.get("passages") or [])
            if isinstance(row, Mapping) and row.get("speaker_role") == "dialogue"
        ),
        "explicit_profile_dialogue_speaker_count": sum(
            1 for row in dialogue_cast_rows if row.get("explicit_profile") is True
        ),
        "neutral_dialogue_speaker_count": sum(
            1 for row in dialogue_cast_rows if row.get("neutral_fallback") is True
        ),
        "cast_map_sha256": str(cast_handoff.get("cast_map_sha256") or ""),
        "cast_handoff_sha256": cast_handoff_sha256,
        "voice_consent": {
            "status": consent.get("status"),
            "revoked": consent.get("revoked"),
            "required_scope": consent.get("required_scope"),
            "required_scope_present": consent.get("required_scope_present"),
            "evidence_sha256": consent.get("evidence_sha256"),
        },
        "demographic_trait_policy": "explicit_approved_profiles_only",
        "casting_trait_policy": CASTING_TRAIT_POLICY_NAME,
        "provider_calls_made": 0,
        "synthesis_requested": False,
        "raw_source_text_exposed": False,
        "raw_voice_ids_exposed": False,
        "sensitive_trait_values_exposed": False,
    }
    package_without_receipt = {
        "contract_name": WORK_PACKAGE_CONTRACT_NAME,
        "version": 4,
        "status": status,
        "reason": reason,
        "slug": normalized_slug,
        "language": selected_language,
        "source_policy": {
            "public_visibility_required": True,
            "approved_review_required_for_archive": True,
            "purpose_specific_narration_review_required": True,
            "narration_review_scope_array_required": True,
            "required_narration_source_scope": REQUIRED_NARRATION_SOURCE_SCOPE,
            "purpose_specific_speaker_attribution_review_required": True,
            "purpose_specific_speaker_casting_review_required": True,
            "required_speaker_casting_scope": REQUIRED_SPEAKER_CASTING_SCOPE,
            "required_speaker_attribution_scope": (
                REQUIRED_SPEAKER_ATTRIBUTION_SCOPE
            ),
            "exact_source_hash_binding_required": True,
            "dialogue_attribution_integrity_required": True,
            "casting_trait_policy": CASTING_TRAIT_POLICY_NAME,
            "private_sources_excluded_by_default": True,
        },
        "sources": source_rows,
        "speaker_attribution_review_requirements": attribution_requirements,
        "speaker_casting_review_requirements": (
            speaker_casting_review_requirements
        ),
        "speaker_casting_review_evidence_aggregate_sha256": (
            speaker_casting_review_evidence_aggregate_sha256
        ),
        "speaker_casting_conflict_review_requirements": (
            speaker_casting_conflict_requirements
        ),
        "narration_plan": plan,
        "casting_plan_sha256": str(
            plan.get("casting_plan_sha256") or ""
        ),
        "dialogue_attribution_evidence_sha256": str(
            plan.get("dialogue_attribution_evidence_sha256") or ""
        ),
        "cast_handoff": cast_handoff,
        "casting_trait_policy": CASTING_TRAIT_POLICY_NAME,
        "cast_handoff_sha256": cast_handoff_sha256,
        "cast_resolution_authorized": receipt["cast_resolution_authorized"],
        "render_authorized": False,
        "synthesis_authorized": False,
        "cast_mapping_review_required": True,
        "human_listening_review_required": True,
        "private_payload": True,
        "provider_calls_made": 0,
        "synthesis_requested": False,
    }
    receipt["work_package_sha256"] = _stable_json_sha256(package_without_receipt)
    return {**package_without_receipt, "provider_safe_receipt": receipt}


def provider_safe_receipt(work_package: Mapping[str, object]) -> dict[str, object]:
    raw = work_package.get("provider_safe_receipt")
    if not isinstance(raw, Mapping):
        raise ValueError("provider_safe_receipt_missing")
    return deepcopy(dict(raw))


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


def _prepare_artifact_parent(path: Path, *, private: bool) -> None:
    if _has_symlink_ancestor(path):
        raise ValueError("narration_artifact_symlink_ancestor_forbidden")
    existed = path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if _has_symlink_ancestor(path) or path.parent.is_symlink():
        raise ValueError("narration_artifact_symlink_ancestor_forbidden")
    parent_stat = path.parent.lstat()
    if not stat.S_ISDIR(parent_stat.st_mode):
        raise ValueError("narration_artifact_parent_not_directory")
    if private:
        if not existed:
            path.parent.chmod(0o700)
            parent_stat = path.parent.lstat()
        if parent_stat.st_uid != os.geteuid() or parent_stat.st_mode & 0o077:
            raise ValueError("narration_private_artifact_parent_unsafe")


def write_json_artifact(
    path: Path, payload: Mapping[str, object], *, private: bool
) -> None:
    _prepare_artifact_parent(path, private=private)
    mode = 0o600 if private else 0o644
    if path.is_symlink():
        raise ValueError("narration_artifact_symlink_forbidden")
    document = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(document)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        path.chmod(mode)
        directory_descriptor = os.open(
            path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary_path.unlink(missing_ok=True)


def materialize_memorial_narration_work_package(
    *,
    slug: str,
    memorial_manifest_path: Path,
    voice_profile_path: Path,
    output_path: Path,
    archive_registry_path: Path | None = None,
    archive_root: Path | None = None,
    receipt_output_path: Path | None = None,
    max_chars: int = 1200,
) -> dict[str, object]:
    if receipt_output_path is not None and os.path.abspath(
        os.fspath(receipt_output_path)
    ) == os.path.abspath(os.fspath(output_path)):
        raise ValueError("narration_output_paths_must_be_distinct")
    memorial_manifest = _load_json_object(memorial_manifest_path)
    voice_profile = _load_json_object(voice_profile_path)
    archive_registry = (
        _load_json_object(archive_registry_path)
        if archive_registry_path is not None and archive_registry_path.is_file()
        else {}
    )
    work_package = build_memorial_narration_work_package(
        slug=slug,
        memorial_manifest=memorial_manifest,
        voice_profile=voice_profile,
        archive_registry=archive_registry,
        archive_root=archive_root,
        max_chars=max_chars,
    )
    write_json_artifact(output_path, work_package, private=True)
    receipt = provider_safe_receipt(work_package)
    if receipt_output_path is not None:
        write_json_artifact(receipt_output_path, receipt, private=False)
    return work_package
