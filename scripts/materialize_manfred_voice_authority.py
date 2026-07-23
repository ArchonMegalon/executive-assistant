#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from typing import Any


SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from materialize_manfred_voice_release import (  # noqa: E402
    ATTESTOR_REF_SHA256_SEMANTICS,
    MEMORIAL_SLUG,
    VOICE_AUTHORITY_CONTRACT,
    VoiceReleaseError,
    _canonical_utc_now,
    _expected_voice_binding,
    _read_signing_private_key,
    _trusted_public_keys_with_identity,
    _write_private_atomic,
)

REPO_ROOT = SCRIPT_ROOT.parent
EA_ROOT = REPO_ROOT / "ea"
if str(EA_ROOT) not in sys.path:
    sys.path.insert(0, str(EA_ROOT))

from app.services.manfred_voice_signing import (  # noqa: E402
    ManfredVoiceSignatureError,
    public_key_id,
    sign_receipt,
    valid_sha256,
)


AUTHORITY_CONFIRMATION = (
    "PUBLIC_SYNTHETIC_CONVERSATIONAL_MANFRED_VOICE_AUTHORIZED"
)


def materialize_manfred_voice_authority(
    *,
    signing_private_key_path: str | Path,
    output_path: str | Path,
    attestor_ref_sha256: str,
    confirmation: str,
    voice_config_sha256: str,
    voice_manifest_sha256: str,
    voice_reference_aggregate_sha256: str,
    provider_voice_id_sha256: str,
    tts_provider: str,
    tts_model: str,
    trusted_public_key_path: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if confirmation != AUTHORITY_CONFIRMATION:
        raise VoiceReleaseError("voice_authority_confirmation_missing")
    if not valid_sha256(attestor_ref_sha256):
        raise VoiceReleaseError("voice_authority_attestor_ref_invalid")
    distinct_paths: list[str | Path] = [
        signing_private_key_path,
        output_path,
    ]
    if trusted_public_key_path is not None:
        distinct_paths.append(trusted_public_key_path)
    normalized_paths = [
        os.path.abspath(os.fspath(path))
        for path in distinct_paths
    ]
    if len(set(normalized_paths)) != len(normalized_paths):
        raise VoiceReleaseError("voice_authority_paths_not_distinct")

    voice_binding = _expected_voice_binding(
        voice_config_sha256=voice_config_sha256,
        voice_manifest_sha256=voice_manifest_sha256,
        voice_reference_aggregate_sha256=voice_reference_aggregate_sha256,
        provider_voice_id_sha256=provider_voice_id_sha256,
        tts_provider=tts_provider,
        tts_model=tts_model,
    )
    signing_key, signing_key_identity = _read_signing_private_key(
        signing_private_key_path
    )
    try:
        trusted_keys, trusted_public_key_identity = (
            _trusted_public_keys_with_identity(
                trusted_public_key_path
            )
        )
        if public_key_id(signing_key.public_key()) not in trusted_keys:
            raise VoiceReleaseError("signing_private_key_untrusted")
    except ManfredVoiceSignatureError as exc:
        raise VoiceReleaseError(str(exc)) from exc

    observed_at = _canonical_utc_now(now)
    unsigned_authority: dict[str, object] = {
        "attested_at": observed_at.replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "attestor_ref_sha256": attestor_ref_sha256,
        "attestor_ref_sha256_semantics": ATTESTOR_REF_SHA256_SEMANTICS,
        "authority_verified": True,
        "contract_name": VOICE_AUTHORITY_CONTRACT,
        "conversational_use_authorized": True,
        "memorial_slug": MEMORIAL_SLUG,
        "public_synthetic_voice_authorized": True,
        "revoked": False,
        "source_material_authorized": True,
        **voice_binding,
    }
    try:
        authority = sign_receipt(unsigned_authority, private_key=signing_key)
    except ManfredVoiceSignatureError as exc:
        raise VoiceReleaseError(str(exc)) from exc
    input_identities = {signing_key_identity}
    if trusted_public_key_identity is not None:
        input_identities.add(trusted_public_key_identity)
    _write_private_atomic(
        output_path,
        authority,
        input_identities=input_identities,
    )
    return authority


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Sign the explicit public conversational Manfred voice authority."
        )
    )
    parser.add_argument("--signing-private-key", required=True)
    parser.add_argument("--trusted-public-key")
    parser.add_argument("--output", required=True)
    parser.add_argument("--attestor-ref-sha256", required=True)
    parser.add_argument("--confirm-authority-scope", required=True)
    parser.add_argument("--voice-config-sha256", required=True)
    parser.add_argument("--voice-manifest-sha256", required=True)
    parser.add_argument("--voice-reference-aggregate-sha256", required=True)
    parser.add_argument("--provider-voice-id-sha256", required=True)
    parser.add_argument("--tts-provider", required=True)
    parser.add_argument("--tts-model", required=True)
    args = parser.parse_args(argv)
    try:
        authority = materialize_manfred_voice_authority(
            signing_private_key_path=args.signing_private_key,
            trusted_public_key_path=args.trusted_public_key,
            output_path=args.output,
            attestor_ref_sha256=args.attestor_ref_sha256,
            confirmation=args.confirm_authority_scope,
            voice_config_sha256=args.voice_config_sha256,
            voice_manifest_sha256=args.voice_manifest_sha256,
            voice_reference_aggregate_sha256=(
                args.voice_reference_aggregate_sha256
            ),
            provider_voice_id_sha256=args.provider_voice_id_sha256,
            tts_provider=args.tts_provider,
            tts_model=args.tts_model,
        )
    except VoiceReleaseError as exc:
        print(
            json.dumps(
                {"status": "blocked", "reason": str(exc)},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "contract_name": authority["contract_name"],
                "output": str(args.output),
                "status": "authorized",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
