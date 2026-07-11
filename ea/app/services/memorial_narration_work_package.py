from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata

from app.services.audiobook_narration_planner import PlannerChapter, plan_narration


WORK_PACKAGE_CONTRACT_NAME = "ea.memorial_narration_work_package.v1"
CAST_HANDOFF_CONTRACT_NAME = "ea.audiobook_speaker_cast_handoff.v2"
RECEIPT_CONTRACT_NAME = "ea.memorial_narration_work_package_receipt.v1"

_APPROVED_REVIEW_STATUSES = frozenset({"approved", "published"})
_ARCHIVE_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,127}")
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


def _card_source(
    raw: Mapping[str, object],
    *,
    slug: str,
    index: int,
) -> tuple[_ApprovedSource | None, str]:
    if str(raw.get("visibility") or "").strip().casefold() != "public":
        return None, "memorial_card_not_explicitly_public"
    if raw.get("approved") is False:
        return None, "memorial_card_not_approved"
    if not _approved_review_status(raw.get("review_status"), allow_empty=True):
        return None, "memorial_card_review_not_approved"

    public_excerpt = raw.get("public_excerpt")
    text_value = (
        public_excerpt
        if isinstance(public_excerpt, str) and public_excerpt.strip()
        else raw.get("body")
    )
    if not isinstance(text_value, str) or not text_value.strip():
        return None, "memorial_card_text_missing"

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
        ),
        "",
    )


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _archive_source(
    raw: Mapping[str, object],
    *,
    slug: str,
    archive_root: Path | None,
) -> tuple[_ApprovedSource | None, str]:
    if str(raw.get("audience") or "").strip().casefold() != "public":
        return None, "archive_entry_not_explicitly_public"
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

    document_manifest = _load_json_object(document_root / "manifest.json")
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
        source_text = source_path.read_text(encoding="utf-8")
    except OSError:
        return None, "archive_document_source_missing"
    if not source_text.strip():
        return None, "archive_document_source_empty"
    return (
        _ApprovedSource(
            href=f"archive://{slug}/{publication_slug}/source.md",
            text=source_text,
            kind="approved_public_archive_document",
            review_status=str(document_manifest.get("review_status") or "approved"),
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
            sources.append(source)

    registry = dict(archive_registry or {})
    raw_publications = registry.get("fliplink_publications")
    for raw in raw_publications if isinstance(raw_publications, list) else []:
        if not isinstance(raw, Mapping):
            excluded["archive_entry_invalid"] += 1
            continue
        source, reason = _archive_source(raw, slug=slug, archive_root=archive_root)
        if source is None:
            excluded[reason] += 1
        else:
            sources.append(source)

    unique: list[_ApprovedSource] = []
    seen_hrefs: set[str] = set()
    for source in sources:
        if source.href in seen_hrefs:
            excluded["duplicate_public_source"] += 1
            continue
        seen_hrefs.add(source.href)
        unique.append(source)
    return unique, excluded


def _explicit_trait_payload(
    profile: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    traits: dict[str, dict[str, object]] = {}
    for canonical_key, aliases in _PROFILE_TRAIT_ALIASES.items():
        value = ""
        for key in aliases:
            value = _normalized_text(profile.get(key))
            if value:
                break
        if not value:
            continue
        traits[canonical_key] = {
            "value": value,
            "provenance": "explicit_approved_speaker_profile",
            "confidence": 1.0,
            "sensitive_hint": canonical_key == "cultural_or_ethnic_background",
        }
    return traits


def _approved_speaker_profiles(
    profiles: Mapping[str, Mapping[str, object]] | None,
) -> tuple[
    dict[str, dict[str, object]],
    dict[str, dict[str, dict[str, object]]],
    dict[str, str],
]:
    planner_profiles: dict[str, dict[str, object]] = {}
    traits_by_key: dict[str, dict[str, dict[str, object]]] = {}
    profile_refs: dict[str, str] = {}
    for label, raw_profile in dict(profiles or {}).items():
        if not isinstance(raw_profile, Mapping):
            continue
        if not (
            raw_profile.get("approved") is True
            or raw_profile.get("casting_approved") is True
            or _approved_review_status(
                raw_profile.get("review_status"), allow_empty=False
            )
        ):
            continue
        key = _profile_key(label)
        if not key:
            continue
        traits = _explicit_trait_payload(raw_profile)
        planner_profiles[str(label)] = {
            name: str(evidence.get("value") or "") for name, evidence in traits.items()
        }
        traits_by_key[key] = traits
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
    return planner_profiles, traits_by_key, profile_refs


def _sanitize_plan_traits(
    plan: Mapping[str, object],
    *,
    approved_traits_by_key: Mapping[str, Mapping[str, Mapping[str, object]]],
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
            row["traits"] = {
                name: dict(evidence)
                for name, evidence in dict(
                    approved_traits_by_key.get(speaker_key) or {}
                ).items()
            }
            row["traits_from_explicit_approved_profile_only"] = True
    sanitized["demographic_trait_policy"] = "explicit_approved_profiles_only"
    sanitized["source_inferred_trait_values_removed"] = True
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


def _cast_handoff(
    *,
    plan: Mapping[str, object],
    consent: Mapping[str, object],
    voice_profile: Mapping[str, object],
    approved_profile_refs: Mapping[str, str],
) -> dict[str, object]:
    if consent.get("authorized") is not True:
        return {
            "contract_name": CAST_HANDOFF_CONTRACT_NAME,
            "status": "blocked_voice_consent",
            "reason": str(consent.get("reason") or "voice_consent_required"),
            "speakers": [],
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
        confidence = float(raw.get("attribution_confidence") or 0.0)
        ambiguous = (
            speaker_id.startswith("speaker_unknown_")
            or confidence < 0.7
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
            }
        )
    rows.sort(key=lambda row: (str(row["speaker_role"]), str(row["speaker_id"])))
    cast_map_sha256 = _stable_json_sha256(rows)
    return {
        "contract_name": CAST_HANDOFF_CONTRACT_NAME,
        "status": "ready_for_private_audiobook_cast_resolution",
        "planner_contract_name": str(plan.get("contract_name") or ""),
        "speakers": rows,
        "cast_map_sha256": cast_map_sha256,
        "raw_voice_ids_embedded": False,
        "sensitive_trait_values_embedded": False,
        "provider_resolution_performed": False,
    }


def _empty_plan(*, language: str) -> dict[str, object]:
    return {
        "contract_name": "ea.audiobook_narration_plan.v2",
        "version": 2,
        "status": "blocked_no_approved_public_sources",
        "language": language,
        "speakers": [],
        "spans": [],
        "passages": [],
        "coverage_complete": False,
        "private_payload": True,
        "raw_source_text_embedded": False,
    }


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
) -> dict[str, object]:
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
    planner_profiles, approved_traits, profile_refs = _approved_speaker_profiles(
        embedded_profiles
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
        plan = _sanitize_plan_traits(raw_plan, approved_traits_by_key=approved_traits)
    else:
        plan = _empty_plan(language=selected_language)

    consent = _voice_consent_decision(
        voice_profile, required_scope=required_voice_scope
    )
    cast_handoff = _cast_handoff(
        plan=plan,
        consent=consent,
        voice_profile=voice_profile,
        approved_profile_refs=profile_refs,
    )
    if not sources:
        status = "blocked_no_approved_public_sources"
        reason = status
    elif consent.get("authorized") is not True:
        status = "blocked_voice_consent"
        reason = str(consent.get("reason") or "voice_consent_required")
    elif str(plan.get("status") or "") != "ready":
        status = "blocked_narration_plan"
        reason = str(plan.get("status") or "narration_plan_not_ready")
    else:
        status = "ready_for_private_cast_resolution"
        reason = ""

    source_rows = [
        {
            "source_href": source.href,
            "kind": source.kind,
            "review_status": source.review_status,
            "text_sha256": _text_sha256(source.text),
            "char_count": len(source.text),
            "visibility": "public",
        }
        for source in sources
    ]
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
        "render_authorized": status == "ready_for_private_cast_resolution",
        "planner_contract_name": str(plan.get("contract_name") or ""),
        "plan_sha256": str(plan.get("plan_sha256") or ""),
        "source_aggregate_sha256": _stable_json_sha256(source_rows),
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
        "voice_consent": {
            "status": consent.get("status"),
            "revoked": consent.get("revoked"),
            "required_scope": consent.get("required_scope"),
            "required_scope_present": consent.get("required_scope_present"),
            "evidence_sha256": consent.get("evidence_sha256"),
        },
        "demographic_trait_policy": "explicit_approved_profiles_only",
        "provider_calls_made": 0,
        "synthesis_requested": False,
        "raw_source_text_exposed": False,
        "raw_voice_ids_exposed": False,
        "sensitive_trait_values_exposed": False,
    }
    package_without_receipt = {
        "contract_name": WORK_PACKAGE_CONTRACT_NAME,
        "version": 1,
        "status": status,
        "reason": reason,
        "slug": normalized_slug,
        "language": selected_language,
        "source_policy": {
            "public_visibility_required": True,
            "approved_review_required_for_archive": True,
            "private_sources_excluded_by_default": True,
        },
        "sources": source_rows,
        "narration_plan": plan,
        "cast_handoff": cast_handoff,
        "render_authorized": receipt["render_authorized"],
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


def write_json_artifact(
    path: Path, payload: Mapping[str, object], *, private: bool
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = 0o600 if private else 0o644
    try:
        path.parent.chmod(0o700 if private else 0o755)
    except OSError:
        pass
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
