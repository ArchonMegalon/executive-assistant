#!/usr/bin/env python3
"""Verify a redacted VocalLab provider receipt as a promotion gate."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Mapping

try:
    from scripts.materialize_vocallab_provider_verification import (
        DEFAULT_OUTPUT,
        PROVIDER_CONTRACT_VERSION,
        VERIFICATION_CONTRACT,
        VERIFICATION_VALIDITY_SECONDS,
        VERIFICATION_VERSION,
        _parse_utc_timestamp,
    )
    from scripts.probe_vocallab_provider import (
        API_CONTRACT_VERSION,
        AUTHENTICATION_FIELD,
        DEFAULT_VERIFICATION_HMAC_KEY_FILE,
        SUPPORTED_MODELS,
        SYNTHETIC_TEXT_POINTS,
        SYNTHETIC_TEXT_SHA256,
        VocalLabAuthenticationError,
        VocalLabProbeError,
        _read_strict_owner_bytes,
        _reject_json_constant,
        _strict_json_object,
        load_verification_hmac_key,
        require_authenticated_payload,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from materialize_vocallab_provider_verification import (  # type: ignore[no-redef]
        DEFAULT_OUTPUT,
        PROVIDER_CONTRACT_VERSION,
        VERIFICATION_CONTRACT,
        VERIFICATION_VALIDITY_SECONDS,
        VERIFICATION_VERSION,
        _parse_utc_timestamp,
    )
    from probe_vocallab_provider import (  # type: ignore[no-redef]
        API_CONTRACT_VERSION,
        AUTHENTICATION_FIELD,
        DEFAULT_VERIFICATION_HMAC_KEY_FILE,
        SUPPORTED_MODELS,
        SYNTHETIC_TEXT_POINTS,
        SYNTHETIC_TEXT_SHA256,
        VocalLabAuthenticationError,
        VocalLabProbeError,
        _read_strict_owner_bytes,
        _reject_json_constant,
        _strict_json_object,
        load_verification_hmac_key,
        require_authenticated_payload,
    )


MAX_RECEIPT_BYTES = 256 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RECEIPT_KEYS = frozenset(
    {
        "contract_name",
        "version",
        "status",
        "generated_at",
        "expires_at",
        "provider",
        "provider_contract_version",
        "api_contract_version",
        "credential_binding_sha256",
        "credential_rotation_required",
        "credential_production_eligible",
        "probe_sha256",
        "catalog_sha256",
        "discovered_voice_hashes",
        "ping",
        "account",
        "models",
        "voices",
        "smoke",
        "request_safety",
        "retention",
        "blockers",
        "secrets_exposed",
        "manuscript_text_exposed",
        AUTHENTICATION_FIELD,
    }
)


class VocalLabReceiptError(RuntimeError):
    """Stable, content-free receipt read failure."""


def _read_receipt(path: Path) -> dict[str, Any]:
    try:
        raw = _read_strict_owner_bytes(
            path,
            minimum_bytes=1,
            maximum_bytes=MAX_RECEIPT_BYTES,
            reason="verification_receipt_identity_invalid",
        )
    except VocalLabProbeError as exc:
        raise VocalLabReceiptError(str(exc)) from exc
    if b"vl_live_" in raw:
        raise VocalLabReceiptError("verification_receipt_secret_leak_detected")
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError):
        raise VocalLabReceiptError("verification_receipt_json_invalid") from None
    if not isinstance(payload, dict):
        raise VocalLabReceiptError("verification_receipt_json_invalid")
    return payload


def _mapping(
    receipt: Mapping[str, Any],
    key: str,
    expected_keys: frozenset[str],
    issues: list[str],
) -> Mapping[str, Any]:
    value = receipt.get(key)
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        issues.append(f"schema:{key}")
        return {}
    return value


def verify_receipt(
    receipt: Mapping[str, Any],
    *,
    hmac_key: bytes,
    now: datetime | None = None,
) -> list[str]:
    try:
        require_authenticated_payload(
            receipt,
            hmac_key=hmac_key,
            signed_contract_name=VERIFICATION_CONTRACT,
        )
    except VocalLabAuthenticationError:
        return ["authentication:invalid"]

    issues: list[str] = []
    if set(receipt) != RECEIPT_KEYS:
        issues.append("schema:root")
    expected_scalars = {
        "contract_name": VERIFICATION_CONTRACT,
        "version": VERIFICATION_VERSION,
        "provider": "vocallab",
        "provider_contract_version": PROVIDER_CONTRACT_VERSION,
        "api_contract_version": API_CONTRACT_VERSION,
        "secrets_exposed": False,
        "manuscript_text_exposed": False,
    }
    for key, expected in expected_scalars.items():
        actual = receipt.get(key)
        if type(actual) is not type(expected) or actual != expected:
            issues.append(f"value:{key}")
    credential_rotation_required = receipt.get("credential_rotation_required")
    credential_production_eligible = receipt.get("credential_production_eligible")
    if (
        type(credential_rotation_required) is not bool
        or type(credential_production_eligible) is not bool
        or credential_rotation_required is not False
        or credential_production_eligible is not True
    ):
        issues.append("gate:credential_posture")
    for key in (
        "credential_binding_sha256",
        "probe_sha256",
        "catalog_sha256",
    ):
        if not isinstance(receipt.get(key), str) or not SHA256_RE.fullmatch(
            str(receipt.get(key, ""))
        ):
            issues.append(f"value:{key}")
    generated: datetime | None = None
    expires: datetime | None = None
    try:
        generated = _parse_utc_timestamp(
            receipt.get("generated_at"),
            reason="generated_at_invalid",
        )
        expires = _parse_utc_timestamp(
            receipt.get("expires_at"),
            reason="expires_at_invalid",
        )
    except RuntimeError:
        issues.append("value:verification_window")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        issues.append("value:verification_clock")
    elif generated is not None and expires is not None:
        current = current.astimezone(timezone.utc)
        if (
            int((expires - generated).total_seconds())
            != VERIFICATION_VALIDITY_SECONDS
            or generated.timestamp() > current.timestamp() + 300
            or current.timestamp() < generated.timestamp() - 300
            or current > expires
        ):
            issues.append("gate:freshness")

    discovered_voice_hashes = receipt.get("discovered_voice_hashes")
    if (
        not isinstance(discovered_voice_hashes, list)
        or any(
            not isinstance(item, str) or not SHA256_RE.fullmatch(item)
            for item in discovered_voice_hashes
        )
        or discovered_voice_hashes != sorted(set(discovered_voice_hashes))
    ):
        issues.append("value:discovered_voice_hashes")

    ping = _mapping(receipt, "ping", frozenset({"status"}), issues)
    account = _mapping(
        receipt,
        "account",
        frozenset(
            {
                "status",
                "api_access",
                "balance_sufficient_for_smoke",
                "exact_balance_exposed",
            }
        ),
        issues,
    )
    models = _mapping(
        receipt,
        "models",
        frozenset({"status", "keys"}),
        issues,
    )
    voices = _mapping(
        receipt,
        "voices",
        frozenset({"status", "voice_count", "raw_voice_ids_exposed"}),
        issues,
    )
    smoke = _mapping(
        receipt,
        "smoke",
        frozenset(
            {
                "status",
                "source_text_sha256",
                "audio_sha256",
                "content_type",
                "sample_rate",
                "points_used",
                "generation_id_sha256",
            }
        ),
        issues,
    )
    request_safety = _mapping(
        receipt,
        "request_safety",
        frozenset(
            {
                "status",
                "max_chars_per_request",
                "requests_per_minute",
                "max_in_flight",
                "minimum_remaining_points",
                "blind_post_retry_allowed",
                "url_fallback_enabled",
            }
        ),
        issues,
    )
    retention = _mapping(
        receipt,
        "retention",
        frozenset(
            {
                "status",
                "generation_history_days",
                "clone_retention",
                "subprocessors",
            }
        ),
        issues,
    )

    if ping.get("status") != "pass":
        issues.append("gate:ping")
    if account.get("status") != "pass" or account.get("api_access") is not True:
        issues.append("gate:account_api_access")
    if (
        account.get("balance_sufficient_for_smoke") is not True
        or account.get("exact_balance_exposed") is not False
    ):
        issues.append("gate:balance_reserve")
    model_keys = models.get("keys")
    if (
        models.get("status") != "pass"
        or not isinstance(model_keys, list)
        or model_keys != list(SUPPORTED_MODELS)
    ):
        issues.append("gate:models")
    if (
        voices.get("status") != "pass"
        or type(voices.get("voice_count")) is not int
        or not isinstance(discovered_voice_hashes, list)
        or voices.get("voice_count") != len(discovered_voice_hashes)
        or voices.get("voice_count", 0) <= 0
        or voices.get("raw_voice_ids_exposed") is not False
    ):
        issues.append("gate:voices")
    if (
        smoke.get("status") != "pass"
        or not isinstance(smoke.get("source_text_sha256"), str)
        or smoke.get("source_text_sha256") != SYNTHETIC_TEXT_SHA256
        or not isinstance(smoke.get("audio_sha256"), str)
        or not SHA256_RE.fullmatch(str(smoke.get("audio_sha256", "")))
        or smoke.get("content_type") != "audio/wav"
        or type(smoke.get("sample_rate")) is not int
        or smoke.get("sample_rate") != 44100
        or type(smoke.get("points_used")) is not int
        or smoke.get("points_used") != SYNTHETIC_TEXT_POINTS
        or not isinstance(smoke.get("generation_id_sha256"), str)
        or not SHA256_RE.fullmatch(
            str(smoke.get("generation_id_sha256", ""))
        )
    ):
        issues.append("gate:synthetic_smoke")
    if (
        request_safety.get("status") != "pass"
        or type(request_safety.get("max_chars_per_request")) is not int
        or request_safety.get("max_chars_per_request") != 1800
        or type(request_safety.get("requests_per_minute")) is not int
        or request_safety.get("requests_per_minute") != 30
        or type(request_safety.get("max_in_flight")) is not int
        or request_safety.get("max_in_flight") != 1
        or type(request_safety.get("minimum_remaining_points")) is not int
        or request_safety.get("minimum_remaining_points") != 3000
        or request_safety.get("blind_post_retry_allowed") is not False
        or request_safety.get("url_fallback_enabled") is not False
    ):
        issues.append("gate:request_safety")
    if (
        retention.get("status") != "acknowledged"
        or type(retention.get("generation_history_days")) is not int
        or retention.get("generation_history_days") != 90
        or retention.get("clone_retention") != "active_account"
        or retention.get("subprocessors") != ["inworld_ai"]
    ):
        issues.append("gate:retention")

    blockers = receipt.get("blockers")
    if (
        not isinstance(blockers, list)
        or any(not isinstance(item, str) for item in blockers)
        or blockers != sorted(set(blockers))
    ):
        issues.append("schema:blockers")
    elif blockers:
        issues.append("gate:blockers_present")
    if receipt.get("status") != "pass":
        issues.append("gate:status")
    return sorted(set(issues))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_OUTPUT)
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
        receipt = _read_receipt(args.input)
        issues = verify_receipt(receipt, hmac_key=verification_hmac_key)
    except (VocalLabReceiptError, VocalLabProbeError) as exc:
        print(json.dumps({"ok": False, "issues": [str(exc)]}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "ok": not issues,
                "status": receipt.get("status", "invalid"),
                "issues": issues,
            },
            sort_keys=True,
        )
    )
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
