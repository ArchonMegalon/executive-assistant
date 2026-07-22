#!/usr/bin/env python3
"""Materialize a strict redacted VocalLab provider-verification receipt."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
from typing import Any, Mapping

try:
    from scripts.probe_vocallab_provider import (
        API_CONTRACT_VERSION,
        AUTHENTICATION_FIELD,
        DEFAULT_VERIFICATION_HMAC_KEY_FILE,
        DEFAULT_REQUESTS_PER_MINUTE,
        MINIMUM_REQUIRED_REMAINING_POINTS,
        PRIVATE_ID_RE,
        PROBE_CONTRACT,
        PROBE_VERSION,
        ROOT,
        SUPPORTED_MODELS,
        SYNTHETIC_TEXT_POINTS,
        SYNTHETIC_TEXT_SHA256,
        VocalLabAuthenticationError,
        VocalLabProbeError,
        _read_strict_owner_bytes,
        _reject_json_constant,
        _strict_json_object,
        _write_private_json,
        load_verification_hmac_key,
        require_authenticated_payload,
        sign_authenticated_payload,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from probe_vocallab_provider import (  # type: ignore[no-redef]
        API_CONTRACT_VERSION,
        AUTHENTICATION_FIELD,
        DEFAULT_VERIFICATION_HMAC_KEY_FILE,
        DEFAULT_REQUESTS_PER_MINUTE,
        MINIMUM_REQUIRED_REMAINING_POINTS,
        PRIVATE_ID_RE,
        PROBE_CONTRACT,
        PROBE_VERSION,
        ROOT,
        SUPPORTED_MODELS,
        SYNTHETIC_TEXT_POINTS,
        SYNTHETIC_TEXT_SHA256,
        VocalLabAuthenticationError,
        VocalLabProbeError,
        _read_strict_owner_bytes,
        _reject_json_constant,
        _strict_json_object,
        _write_private_json,
        load_verification_hmac_key,
        require_authenticated_payload,
        sign_authenticated_payload,
    )


VERIFICATION_CONTRACT = "ea.audiobook_vocallab_provider_verification.v1"
VERIFICATION_VERSION = 2
PROVIDER_CONTRACT_VERSION = "ea.audiobook_tts.vocallab.v1"
VERIFICATION_VALIDITY_SECONDS = 86400
DEFAULT_PROBE = ROOT / ".runtime/vocallab-provider-probe.generated.json"
DEFAULT_OUTPUT = ROOT / ".runtime/vocallab-provider-verification.generated.json"
DEFAULT_VOICE_CATALOG = ROOT / "config/vocallab_voice_catalog.local.json"
VOICE_CATALOG_CONTRACT = "ea.audiobook_vocallab_voice_catalog.v1"
VOICE_CATALOG_MAX_AGE_DAYS = 30
ALLOWED_VOICE_RIGHTS_CLASSES = frozenset(
    {"professional", "consented_clone"}
)
MAX_PROBE_BYTES = 256 * 1024
MAX_CATALOG_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
PROBE_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "generated_at",
        "provider",
        "api_contract_version",
        "credential_binding_sha256",
        "credential_rotation_required",
        "credential_production_eligible",
        "api_key_present",
        "api_key_exposed",
        "request_policy",
        "ping",
        "account",
        "models",
        "voices",
        "smoke",
        "blockers",
        "secrets_exposed",
        "manuscript_text_exposed",
        "raw_response_bodies_exposed",
        AUTHENTICATION_FIELD,
    }
)
REQUEST_POLICY_KEYS = frozenset(
    {
        "default_spend_authorized",
        "synthetic_tts_requested",
        "post_count",
        "post_retry_count",
        "minimum_remaining_points",
        "requests_per_minute",
    }
)
ENDPOINT_KEYS = frozenset({"status", "http_status"})
ACCOUNT_KEYS = ENDPOINT_KEYS | frozenset(
    {
        "is_pro",
        "is_studio",
        "balance_reported",
        "balance_sufficient_for_smoke",
    }
)
MODELS_KEYS = ENDPOINT_KEYS | frozenset({"keys", "model_count"})
VOICES_KEYS = ENDPOINT_KEYS | frozenset(
    {"voice_count", "discovered_voice_hashes", "raw_voice_ids_exposed"}
)
SMOKE_KEYS = frozenset(
    {
        "requested",
        "status",
        "source_text_sha256",
        "audio_sha256",
        "content_type",
        "sample_rate",
        "points_used",
        "generation_id_sha256",
        "charge_state",
    }
)
VOICE_CATALOG_ROOT_KEYS = frozenset(
    {"contract_name", "catalog_version", "voices"}
)
VOICE_CATALOG_ENTRY_KEYS = frozenset(
    {
        "provider_voice_id",
        "voice_id_sha256",
        "safe_label",
        "provider_type",
        "rights_class",
        "languages",
        "tags",
        "allowed_uses",
        "blocked_uses",
        "rights_receipt_id",
        "consent_receipt_id",
        "reviewed_at",
        "active",
    }
)


class VocalLabVerificationError(RuntimeError):
    """Stable, content-free verification materialization failure."""


@dataclass(frozen=True, slots=True)
class ValidatedVoiceCatalog:
    source_sha256: str
    voice_hashes: tuple[str, ...]
    active_voice_hashes: tuple[str, ...]


def _read_private_probe(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = _read_strict_owner_bytes(
            path,
            minimum_bytes=1,
            maximum_bytes=MAX_PROBE_BYTES,
            reason="probe_identity_invalid",
        )
    except VocalLabProbeError as exc:
        raise VocalLabVerificationError(str(exc)) from exc
    if b"vl_live_" in raw:
        raise VocalLabVerificationError("probe_secret_leak_detected")
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError):
        raise VocalLabVerificationError("probe_json_invalid") from None
    if not isinstance(payload, dict):
        raise VocalLabVerificationError("probe_json_invalid")
    return payload, raw


def _required_string(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VocalLabVerificationError("voice_catalog_schema_invalid")
    return value.strip()


def _string_list(
    value: object,
    *,
    required: bool,
) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise VocalLabVerificationError("voice_catalog_schema_invalid")
    normalized = tuple(item.strip() for item in value)
    if len(normalized) != len(set(normalized)) or (required and not normalized):
        raise VocalLabVerificationError("voice_catalog_schema_invalid")
    return normalized


def _validate_voice_catalog(
    payload: Mapping[str, Any],
    *,
    source_sha256: str,
    now: datetime,
) -> ValidatedVoiceCatalog:
    if set(payload) != VOICE_CATALOG_ROOT_KEYS:
        raise VocalLabVerificationError("voice_catalog_schema_invalid")
    catalog_version = payload.get("catalog_version")
    rows = payload.get("voices")
    if (
        payload.get("contract_name") != VOICE_CATALOG_CONTRACT
        or type(catalog_version) is not int
        or catalog_version < 1
        or not isinstance(rows, list)
    ):
        raise VocalLabVerificationError("voice_catalog_schema_invalid")
    if now.tzinfo is None or now.utcoffset() is None:
        raise VocalLabVerificationError("voice_catalog_time_invalid")
    current = now.astimezone(timezone.utc)
    raw_ids: set[str] = set()
    voice_hashes: set[str] = set()
    active_hashes: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != VOICE_CATALOG_ENTRY_KEYS:
            raise VocalLabVerificationError("voice_catalog_schema_invalid")
        provider_voice_id = _required_string(row.get("provider_voice_id"))
        if not PRIVATE_ID_RE.fullmatch(provider_voice_id):
            raise VocalLabVerificationError("voice_catalog_schema_invalid")
        voice_hash = _required_string(row.get("voice_id_sha256"))
        if not SHA256_RE.fullmatch(voice_hash) or not hmac.compare_digest(
            voice_hash,
            hashlib.sha256(provider_voice_id.encode("utf-8")).hexdigest(),
        ):
            raise VocalLabVerificationError("voice_catalog_voice_hash_invalid")
        safe_label = _required_string(row.get("safe_label"))
        if provider_voice_id in safe_label:
            raise VocalLabVerificationError("voice_catalog_schema_invalid")
        provider_type = _required_string(row.get("provider_type")).lower()
        rights_class = _required_string(row.get("rights_class")).lower()
        if rights_class not in ALLOWED_VOICE_RIGHTS_CLASSES:
            raise VocalLabVerificationError("voice_catalog_rights_invalid")
        consent_receipt_id = row.get("consent_receipt_id")
        if not isinstance(consent_receipt_id, str):
            raise VocalLabVerificationError("voice_catalog_schema_invalid")
        if (
            rights_class == "professional"
            and (provider_type != "preset" or consent_receipt_id.strip())
        ) or (
            rights_class == "consented_clone"
            and (provider_type != "clone" or not consent_receipt_id.strip())
        ):
            raise VocalLabVerificationError("voice_catalog_rights_invalid")
        _required_string(row.get("rights_receipt_id"))
        _string_list(row.get("languages"), required=True)
        _string_list(row.get("tags"), required=False)
        _string_list(row.get("allowed_uses"), required=True)
        _string_list(row.get("blocked_uses"), required=False)
        active = row.get("active")
        if type(active) is not bool:
            raise VocalLabVerificationError("voice_catalog_schema_invalid")
        reviewed_at = _parse_utc_timestamp(
            row.get("reviewed_at"),
            reason="voice_catalog_time_invalid",
        )
        if (
            reviewed_at > current + timedelta(minutes=5)
            or current - reviewed_at > timedelta(days=VOICE_CATALOG_MAX_AGE_DAYS)
        ):
            raise VocalLabVerificationError("voice_catalog_stale")
        if provider_voice_id in raw_ids or voice_hash in voice_hashes:
            raise VocalLabVerificationError("voice_catalog_duplicate_voice")
        raw_ids.add(provider_voice_id)
        voice_hashes.add(voice_hash)
        if active:
            active_hashes.add(voice_hash)
    return ValidatedVoiceCatalog(
        source_sha256=source_sha256,
        voice_hashes=tuple(sorted(voice_hashes)),
        active_voice_hashes=tuple(sorted(active_hashes)),
    )


def _read_private_catalog(
    path: Path,
    *,
    now: datetime,
) -> ValidatedVoiceCatalog:
    try:
        raw = _read_strict_owner_bytes(
            path,
            minimum_bytes=2,
            maximum_bytes=MAX_CATALOG_BYTES,
            reason="voice_catalog_identity_invalid",
        )
    except VocalLabProbeError as exc:
        raise VocalLabVerificationError(str(exc)) from exc
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError):
        raise VocalLabVerificationError("voice_catalog_json_invalid") from None
    if not isinstance(payload, dict):
        raise VocalLabVerificationError("voice_catalog_json_invalid")
    return _validate_voice_catalog(
        payload,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        now=now,
    )


def _parse_utc_timestamp(value: object, *, reason: str) -> datetime:
    if not isinstance(value, str) or not UTC_TIMESTAMP_RE.fullmatch(value):
        raise VocalLabVerificationError(reason)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        raise VocalLabVerificationError(reason) from None
    return parsed


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mapping(
    payload: Mapping[str, Any],
    key: str,
    expected_keys: frozenset[str],
) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise VocalLabVerificationError(f"probe_{key}_schema_invalid")
    return value


def _validate_probe_schema(payload: Mapping[str, Any]) -> None:
    if set(payload) != PROBE_KEYS:
        raise VocalLabVerificationError("probe_schema_invalid")
    if (
        payload.get("contract_name") != PROBE_CONTRACT
        or payload.get("version") != PROBE_VERSION
        or type(payload.get("version")) is not int
        or payload.get("provider") != "vocallab"
        or payload.get("api_contract_version") != API_CONTRACT_VERSION
        or payload.get("status") not in {"pass", "blocked"}
        or not isinstance(payload.get("credential_binding_sha256"), str)
        or not SHA256_RE.fullmatch(
            str(payload.get("credential_binding_sha256", ""))
        )
        or not isinstance(payload.get("generated_at"), str)
        or type(payload.get("credential_rotation_required")) is not bool
        or type(payload.get("credential_production_eligible")) is not bool
        or payload.get("credential_rotation_required")
        == payload.get("credential_production_eligible")
        or type(payload.get("api_key_present")) is not bool
        or type(payload.get("api_key_exposed")) is not bool
        or not isinstance(payload.get("blockers"), list)
        or any(not isinstance(item, str) for item in payload.get("blockers", []))
    ):
        raise VocalLabVerificationError("probe_schema_invalid")
    _parse_utc_timestamp(
        payload.get("generated_at"),
        reason="probe_generated_at_invalid",
    )
    blockers = payload.get("blockers")
    assert isinstance(blockers, list)
    if blockers != sorted(set(blockers)) or (
        (payload.get("status") == "pass") != (len(blockers) == 0)
    ):
        raise VocalLabVerificationError("probe_status_invalid")
    request_policy = _mapping(payload, "request_policy", REQUEST_POLICY_KEYS)
    ping = _mapping(payload, "ping", ENDPOINT_KEYS)
    account = _mapping(payload, "account", ACCOUNT_KEYS)
    models = _mapping(payload, "models", MODELS_KEYS)
    voices = _mapping(payload, "voices", VOICES_KEYS)
    smoke = _mapping(payload, "smoke", SMOKE_KEYS)
    if (
        request_policy.get("default_spend_authorized") is not False
        or type(request_policy.get("synthetic_tts_requested")) is not bool
        or type(request_policy.get("post_count")) is not int
        or type(request_policy.get("post_retry_count")) is not int
        or request_policy.get("post_count") not in (0, 1)
        or request_policy.get("post_retry_count") != 0
        or type(request_policy.get("minimum_remaining_points")) is not int
        or request_policy.get("minimum_remaining_points", 0)
        < MINIMUM_REQUIRED_REMAINING_POINTS
        or type(request_policy.get("requests_per_minute")) is not int
        or request_policy.get("requests_per_minute", 0) <= 0
        or request_policy.get("requests_per_minute")
        != DEFAULT_REQUESTS_PER_MINUTE
    ):
        raise VocalLabVerificationError("probe_request_policy_invalid")
    for endpoint in (ping, account, models, voices):
        if (
            endpoint.get("status") not in {"pass", "blocked"}
            or type(endpoint.get("http_status")) is not int
        ):
            raise VocalLabVerificationError("probe_endpoint_schema_invalid")
    if any(
        type(account.get(key)) is not bool
        for key in (
            "is_pro",
            "is_studio",
            "balance_reported",
            "balance_sufficient_for_smoke",
        )
    ):
        raise VocalLabVerificationError("probe_account_schema_invalid")
    model_keys = models.get("keys")
    if (
        not isinstance(model_keys, list)
        or any(model not in SUPPORTED_MODELS for model in model_keys)
        or len(model_keys) != len(set(model_keys))
        or model_keys
        != [model for model in SUPPORTED_MODELS if model in set(model_keys)]
        or type(models.get("model_count")) is not int
        or models.get("model_count", -1) < 0
        or models.get("model_count") != len(model_keys)
    ):
        raise VocalLabVerificationError("probe_models_schema_invalid")
    discovered_voice_hashes = voices.get("discovered_voice_hashes")
    if (
        type(voices.get("voice_count")) is not int
        or voices.get("voice_count", -1) < 0
        or not isinstance(discovered_voice_hashes, list)
        or any(
            not isinstance(item, str) or not SHA256_RE.fullmatch(item)
            for item in discovered_voice_hashes
        )
        or discovered_voice_hashes != sorted(set(discovered_voice_hashes))
        or voices.get("voice_count") != len(discovered_voice_hashes)
        or voices.get("raw_voice_ids_exposed") is not False
    ):
        raise VocalLabVerificationError("probe_voices_schema_invalid")
    if (
        type(smoke.get("requested")) is not bool
        or smoke.get("status") not in {"pass", "blocked", "not_run"}
        or not isinstance(smoke.get("source_text_sha256"), str)
        or not isinstance(smoke.get("audio_sha256"), str)
        or not isinstance(smoke.get("content_type"), str)
        or type(smoke.get("sample_rate")) is not int
        or smoke.get("sample_rate", -1) < 0
        or type(smoke.get("points_used")) is not int
        or smoke.get("points_used", -1) < 0
        or not isinstance(smoke.get("generation_id_sha256"), str)
        or smoke.get("charge_state") not in {"not_charged", "charged", "unknown"}
    ):
        raise VocalLabVerificationError("probe_smoke_schema_invalid")
    if (
        request_policy.get("synthetic_tts_requested") != smoke.get("requested")
        or (smoke.get("status") == "pass" and request_policy.get("post_count") != 1)
        or (
            request_policy.get("synthetic_tts_requested") is False
            and request_policy.get("post_count") != 0
        )
    ):
        raise VocalLabVerificationError("probe_smoke_policy_invalid")
    if smoke.get("status") == "pass" and (
        smoke.get("requested") is not True
        or request_policy.get("synthetic_tts_requested") is not True
        or request_policy.get("post_count") != 1
        or request_policy.get("post_retry_count") != 0
        or smoke.get("source_text_sha256") != SYNTHETIC_TEXT_SHA256
        or not SHA256_RE.fullmatch(str(smoke.get("audio_sha256", "")))
        or not SHA256_RE.fullmatch(
            str(smoke.get("generation_id_sha256", ""))
        )
        or smoke.get("content_type") != "audio/wav"
        or smoke.get("sample_rate") != 44100
        or smoke.get("charge_state") != "charged"
        or smoke.get("points_used") != SYNTHETIC_TEXT_POINTS
    ):
        raise VocalLabVerificationError("probe_smoke_evidence_invalid")


def materialize_verification(
    probe: Mapping[str, Any],
    *,
    probe_sha256: str,
    catalog: ValidatedVoiceCatalog,
    hmac_key: bytes,
) -> dict[str, object]:
    try:
        require_authenticated_payload(
            probe,
            hmac_key=hmac_key,
            signed_contract_name=PROBE_CONTRACT,
        )
    except VocalLabAuthenticationError as exc:
        raise VocalLabVerificationError("probe_authentication_invalid") from exc
    _validate_probe_schema(probe)
    if not SHA256_RE.fullmatch(probe_sha256):
        raise VocalLabVerificationError("probe_digest_invalid")
    if (
        not isinstance(catalog, ValidatedVoiceCatalog)
        or not SHA256_RE.fullmatch(catalog.source_sha256)
        or catalog.voice_hashes != tuple(sorted(set(catalog.voice_hashes)))
        or catalog.active_voice_hashes
        != tuple(sorted(set(catalog.active_voice_hashes)))
        or any(not SHA256_RE.fullmatch(item) for item in catalog.voice_hashes)
        or any(
            not SHA256_RE.fullmatch(item)
            for item in catalog.active_voice_hashes
        )
        or not set(catalog.active_voice_hashes).issubset(catalog.voice_hashes)
    ):
        raise VocalLabVerificationError("voice_catalog_digest_invalid")

    request_policy = probe["request_policy"]
    ping = probe["ping"]
    account = probe["account"]
    models = probe["models"]
    voices = probe["voices"]
    smoke = probe["smoke"]
    assert isinstance(request_policy, Mapping)
    assert isinstance(ping, Mapping)
    assert isinstance(account, Mapping)
    assert isinstance(models, Mapping)
    assert isinstance(voices, Mapping)
    assert isinstance(smoke, Mapping)
    generated = _parse_utc_timestamp(
        probe.get("generated_at"),
        reason="probe_generated_at_invalid",
    )
    expires = generated + timedelta(seconds=VERIFICATION_VALIDITY_SECONDS)
    discovered_voice_hashes = list(voices.get("discovered_voice_hashes", []))

    blockers: list[str] = []
    if probe.get("credential_rotation_required") is not False:
        blockers.append("credential_rotation_required")
    if probe.get("credential_production_eligible") is not True:
        blockers.append("credential_production_ineligible")
    if ping.get("status") != "pass" or ping.get("http_status") != 200:
        blockers.append("ping_unverified")
    if account.get("status") != "pass" or account.get("http_status") != 200:
        blockers.append("account_unverified")
    if account.get("is_pro") is not True and account.get("is_studio") is not True:
        blockers.append("api_access_unverified")
    if account.get("balance_sufficient_for_smoke") is not True:
        blockers.append("balance_reserve_unverified")
    if models.get("status") != "pass" or models.get("http_status") != 200:
        blockers.append("models_unverified")
    if set(models.get("keys", [])) != set(SUPPORTED_MODELS):
        blockers.append("required_models_missing")
    if voices.get("status") != "pass" or voices.get("http_status") != 200:
        blockers.append("voices_unverified")
    if voices.get("voice_count", 0) <= 0:
        blockers.append("voices_empty")
    if not discovered_voice_hashes:
        blockers.append("voice_hash_inventory_empty")
    if not catalog.active_voice_hashes:
        blockers.append("voice_catalog_active_inventory_empty")
    if not set(catalog.active_voice_hashes).issubset(
        set(discovered_voice_hashes)
    ):
        blockers.append("voice_catalog_discovery_mismatch")
    if smoke.get("status") != "pass":
        blockers.append("synthetic_smoke_not_passed")
    if (
        request_policy.get("default_spend_authorized") is not False
        or request_policy.get("post_count") != 1
        or request_policy.get("post_retry_count") != 0
        or request_policy.get("minimum_remaining_points")
        != MINIMUM_REQUIRED_REMAINING_POINTS
        or request_policy.get("requests_per_minute", 0)
        > DEFAULT_REQUESTS_PER_MINUTE
    ):
        blockers.append("request_safety_unverified")
    if (
        probe.get("api_key_present") is not True
        or probe.get("api_key_exposed") is not False
        or probe.get("secrets_exposed") is not False
        or probe.get("manuscript_text_exposed") is not False
        or probe.get("raw_response_bodies_exposed") is not False
        or voices.get("raw_voice_ids_exposed") is not False
    ):
        blockers.append("redaction_contract_unverified")
    if probe.get("status") != "pass":
        blockers.append("probe_reported_blocked")

    blockers = sorted(set(blockers))
    model_keys = [
        model for model in SUPPORTED_MODELS if model in set(models.get("keys", []))
    ]
    unsigned_receipt = {
        "contract_name": VERIFICATION_CONTRACT,
        "version": VERIFICATION_VERSION,
        "status": "pass" if not blockers else "blocked",
        "generated_at": _utc_timestamp(generated),
        "expires_at": _utc_timestamp(expires),
        "provider": "vocallab",
        "provider_contract_version": PROVIDER_CONTRACT_VERSION,
        "api_contract_version": API_CONTRACT_VERSION,
        "credential_binding_sha256": probe["credential_binding_sha256"],
        "credential_rotation_required": probe[
            "credential_rotation_required"
        ],
        "credential_production_eligible": probe[
            "credential_production_eligible"
        ],
        "probe_sha256": probe_sha256,
        "catalog_sha256": catalog.source_sha256,
        "discovered_voice_hashes": discovered_voice_hashes,
        "ping": {"status": ping["status"]},
        "account": {
            "status": account["status"],
            "api_access": bool(account["is_pro"] or account["is_studio"]),
            "balance_sufficient_for_smoke": account[
                "balance_sufficient_for_smoke"
            ],
            "exact_balance_exposed": False,
        },
        "models": {"status": models["status"], "keys": model_keys},
        "voices": {
            "status": voices["status"],
            "voice_count": len(discovered_voice_hashes),
            "raw_voice_ids_exposed": False,
        },
        "smoke": {
            "status": smoke["status"],
            "source_text_sha256": smoke["source_text_sha256"],
            "audio_sha256": smoke["audio_sha256"],
            "content_type": smoke["content_type"],
            "sample_rate": smoke["sample_rate"],
            "points_used": smoke["points_used"],
            "generation_id_sha256": smoke["generation_id_sha256"],
        },
        "request_safety": {
            "status": (
                "pass"
                if request_policy["post_count"] == 1
                and request_policy["post_retry_count"] == 0
                and request_policy["minimum_remaining_points"]
                == MINIMUM_REQUIRED_REMAINING_POINTS
                and request_policy["requests_per_minute"]
                == DEFAULT_REQUESTS_PER_MINUTE
                else "blocked"
            ),
            "max_chars_per_request": 1800,
            "requests_per_minute": 30,
            "max_in_flight": 1,
            "minimum_remaining_points": request_policy[
                "minimum_remaining_points"
            ],
            "blind_post_retry_allowed": False,
            "url_fallback_enabled": False,
        },
        "retention": {
            "status": "acknowledged",
            "generation_history_days": 90,
            "clone_retention": "active_account",
            "subprocessors": ["inworld_ai"],
        },
        "blockers": blockers,
        "secrets_exposed": False,
        "manuscript_text_exposed": False,
    }
    try:
        return sign_authenticated_payload(
            unsigned_receipt,
            hmac_key=hmac_key,
            signed_contract_name=VERIFICATION_CONTRACT,
        )
    except VocalLabAuthenticationError as exc:
        raise VocalLabVerificationError(
            "verification_authentication_failed"
        ) from exc


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, default=DEFAULT_PROBE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--voice-catalog-file",
        type=Path,
        default=DEFAULT_VOICE_CATALOG,
    )
    parser.add_argument(
        "--verification-hmac-key-file",
        type=Path,
        default=DEFAULT_VERIFICATION_HMAC_KEY_FILE,
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        verification_hmac_key = load_verification_hmac_key(
            args.verification_hmac_key_file
        )
        probe, raw = _read_private_probe(args.probe)
        catalog = _read_private_catalog(
            args.voice_catalog_file,
            now=datetime.now(timezone.utc),
        )
        receipt = materialize_verification(
            probe,
            probe_sha256=hashlib.sha256(raw).hexdigest(),
            catalog=catalog,
            hmac_key=verification_hmac_key,
        )
        _write_private_json(args.output, receipt)
    except (VocalLabVerificationError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "status": receipt["status"],
                "output": str(args.output),
                "blockers": receipt["blockers"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
