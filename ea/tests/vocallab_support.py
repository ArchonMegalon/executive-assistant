from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from pathlib import Path

from app.services.audiobook_tts.authorities import VocalLabAuthorityStore
from app.services.audiobook_tts.budget_ledger import VocalLabBudgetLedger
from app.services.audiobook_tts.contracts import (
    ProviderVoiceRef,
    SpeechSynthesisRequest,
)
from app.services.audiobook_tts.voice_catalog import VocalLabVoiceCatalog
from app.services.audiobook_tts.providers.vocallab_schema import (
    VOCALLAB_VERIFICATION_SYNTHETIC_POINTS,
)


NOW = datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
VOICE_ID = "private-provider-voice-01"
VOICE_SHA = hashlib.sha256(VOICE_ID.encode()).hexdigest()
HMAC_KEY = b"verification-test-key-material-32b!"
API_KEY = "vl_" + "live_" + "a" * 24
CREDENTIAL_BINDING_SHA256 = hashlib.sha256(API_KEY.encode()).hexdigest()
PROVIDER_CONTRACT = "ea.audiobook_tts.vocallab.v1"
PROBE_TEXT = "EA VocalLab provider verification. This is synthetic test content."


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def write_private(path: Path, payload: dict[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.write_bytes(encoded)
    path.chmod(0o600)
    return hashlib.sha256(encoded).hexdigest()


def catalog(private: Path) -> VocalLabVoiceCatalog:
    path = private / "catalog.json"
    write_private(
        path,
        {
            "contract_name": "ea.audiobook_vocallab_voice_catalog.v1",
            "catalog_version": 1,
            "voices": [
                {
                    "provider_voice_id": VOICE_ID,
                    "voice_id_sha256": VOICE_SHA,
                    "safe_label": "Approved narrator",
                    "provider_type": "preset",
                    "rights_class": "professional",
                    "languages": ["en-US"],
                    "tags": ["narration"],
                    "allowed_uses": [
                        "audiobook_narration",
                        "dialogue",
                        "voice_audition",
                    ],
                    "blocked_uses": ["memorial"],
                    "rights_receipt_id": "rights-1",
                    "consent_receipt_id": "",
                    "reviewed_at": NOW.isoformat().replace("+00:00", "Z"),
                    "active": True,
                }
            ],
        },
    )
    return VocalLabVoiceCatalog.from_file(path, now=NOW)


def verification_payload(
    catalog_sha256: str,
    *,
    credential_binding_sha256: str = CREDENTIAL_BINDING_SHA256,
    points_used: int = VOCALLAB_VERIFICATION_SYNTHETIC_POINTS,
) -> dict[str, object]:
    generated = NOW.isoformat().replace("+00:00", "Z")
    expires = (NOW + timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    unsigned: dict[str, object] = {
        "contract_name": "ea.audiobook_vocallab_provider_verification.v1",
        "version": 2,
        "status": "pass",
        "generated_at": generated,
        "expires_at": expires,
        "provider": "vocallab",
        "provider_contract_version": PROVIDER_CONTRACT,
        "api_contract_version": "2026-07-22",
        "probe_sha256": "a" * 64,
        "catalog_sha256": catalog_sha256,
        "credential_binding_sha256": credential_binding_sha256,
        "credential_rotation_required": False,
        "credential_production_eligible": True,
        "discovered_voice_hashes": [VOICE_SHA],
        "ping": {"status": "pass"},
        "account": {
            "status": "pass",
            "api_access": True,
            "balance_sufficient_for_smoke": True,
            "exact_balance_exposed": False,
        },
        "models": {
            "status": "pass",
            "keys": ["v-studio", "v-pro", "v-lite"],
        },
        "voices": {
            "status": "pass",
            "voice_count": 1,
            "raw_voice_ids_exposed": False,
        },
        "smoke": {
            "status": "pass",
            "source_text_sha256": sha(PROBE_TEXT),
            "audio_sha256": "b" * 64,
            "content_type": "audio/wav",
            "sample_rate": 44100,
            "points_used": points_used,
            "generation_id_sha256": "c" * 64,
        },
        "request_safety": {
            "status": "pass",
            "max_chars_per_request": 1800,
            "requests_per_minute": 30,
            "max_in_flight": 1,
            "minimum_remaining_points": 3000,
            "blind_post_retry_allowed": False,
            "url_fallback_enabled": False,
        },
        "retention": {
            "status": "acknowledged",
            "generation_history_days": 90,
            "clone_retention": "active_account",
            "subprocessors": ["inworld_ai"],
        },
        "blockers": [],
        "secrets_exposed": False,
        "manuscript_text_exposed": False,
    }
    unsigned_bytes = (
        json.dumps(
            unsigned,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()
    message = (
        b"ea-vocallab-verification-provenance-v1\x00"
        b"ea.audiobook_vocallab_provider_verification.v1\x00"
        + unsigned_bytes
    )
    unsigned["authentication"] = {
        "contract_name": "ea.audiobook_vocallab_verification_provenance.v1",
        "version": 1,
        "algorithm": "HMAC-SHA256",
        "signed_contract_name": "ea.audiobook_vocallab_provider_verification.v1",
        "key_id_sha256": hashlib.sha256(HMAC_KEY).hexdigest(),
        "payload_sha256": hashlib.sha256(unsigned_bytes).hexdigest(),
        "hmac_sha256": hmac.new(HMAC_KEY, message, hashlib.sha256).hexdigest(),
    }
    return unsigned


def base_request(*, workload: str = "audiobook") -> SpeechSynthesisRequest:
    text = "Synthetic governed narration segment."
    return SpeechSynthesisRequest(
        job_id="job-1",
        chapter_id="chapter-1",
        segment_id="segment-1",
        source_text=text,
        source_text_sha256=sha(text),
        language="en-US",
        speaker_id="speaker-1",
        speaker_role="narrator",
        voice=ProviderVoiceRef(
            provider="vocallab",
            provider_voice_id=VOICE_ID,
            voice_id_sha256=VOICE_SHA,
            safe_label="Approved narrator",
            language="en-US",
            supported_languages=("en-US",),
            rights_class="professional",
            rights_receipt_id="rights-1",
        ),
        model="v-pro",
        speed=1.0,
        temperature=1.0,
        output_format="wav",
        sample_rate=44100,
        performance_direction="",
        external_processing_authorization_id="external-auth-1",
        idempotency_key="idempotency-1",
        workload=workload,  # type: ignore[arg-type]
        publication_intent=workload != "voice_audition",
        external_processing_authorization_sha256="0" * 64,
        cast_snapshot_sha256="0" * 64,
        audition_authorization_id=(
            "audition-auth-1" if workload == "voice_audition" else ""
        ),
        audition_authorization_sha256="0" * 64,
        provider_contract_version=PROVIDER_CONTRACT,
    )


def authorized_case(
    tmp_path: Path,
    *,
    workload: str = "audiobook",
) -> tuple[
    SpeechSynthesisRequest,
    VocalLabVoiceCatalog,
    VocalLabAuthorityStore,
    VocalLabBudgetLedger,
    Path,
]:
    private = tmp_path / "private"
    private.mkdir(parents=True, mode=0o700)
    private.chmod(0o700)
    voice_catalog = catalog(private)
    verification_path = private / "verification.json"
    write_private(
        verification_path,
        verification_payload(voice_catalog.source_sha256),
    )
    request = base_request(workload=workload)
    external_path = private / "external.json"
    external_sha = write_private(
        external_path,
        {
            "contract_name": "ea.audiobook_external_processing_authorization.v2",
            "version": 2,
            "authorization_id": request.external_processing_authorization_id,
            "job_id_sha256": sha(request.job_id),
            "source_sha256": request.source_text_sha256,
            "authorized_segment_sha256s": [sha(request.segment_id)],
            "rights_basis": "owner_authored",
            "allowed_providers": ["vocallab"],
            "allowed_subprocessors": ["inworld_ai"],
            "allowed_content_scope": "selected_segments",
            "generated_at": NOW.isoformat().replace("+00:00", "Z"),
            "expires_at": (NOW + timedelta(days=7)).isoformat().replace(
                "+00:00", "Z"
            ),
            "approved_by_sha256": "d" * 64,
            "revoked": False,
        },
    )
    request = replace(
        request,
        external_processing_authorization_sha256=external_sha,
    )
    cast_path: Path | None = None
    audition_path: Path | None = None
    if workload == "voice_audition":
        audition_path = private / "audition.json"
        audition_sha = write_private(
            audition_path,
            {
                "contract_name": "ea.audiobook_voice_audition_authorization.v1",
                "version": 1,
                "authorization_id": request.audition_authorization_id,
                "job_id_sha256": sha(request.job_id),
                "speaker_id_sha256": sha(request.speaker_id),
                "provider": "vocallab",
                "voice_id_sha256": request.voice.voice_id_sha256,
                "model": request.model,
                "generated_at": NOW.isoformat().replace("+00:00", "Z"),
                "expires_at": (NOW + timedelta(days=1)).isoformat().replace(
                    "+00:00", "Z"
                ),
                "revoked": False,
            },
        )
        request = replace(request, audition_authorization_sha256=audition_sha)
    else:
        cast_path = private / "cast.json"
        cast_sha = write_private(
            cast_path,
            {
                "contract_name": "ea.audiobook_speaker_cast_snapshot.v2",
                "version": 2,
                "snapshot_id": "cast-1",
                "job_id_sha256": sha(request.job_id),
                "generated_at": NOW.isoformat().replace("+00:00", "Z"),
                "expires_at": (NOW + timedelta(days=30)).isoformat().replace(
                    "+00:00", "Z"
                ),
                "entries": [
                    {
                        "speaker_id_sha256": sha(request.speaker_id),
                        "provider": "vocallab",
                        "voice_id_sha256": request.voice.voice_id_sha256,
                        "model": request.model,
                        "rights_receipt_sha256": sha(
                            request.voice.rights_receipt_id
                        ),
                        "consent_receipt_sha256": "",
                    }
                ],
            },
        )
        request = replace(request, cast_snapshot_sha256=cast_sha)
    store = VocalLabAuthorityStore(
        verification_path=verification_path,
        verification_hmac_key=HMAC_KEY,
        external_authorization_path=external_path,
        cast_snapshot_path=cast_path,
        audition_authorization_path=audition_path,
    )
    ledger = VocalLabBudgetLedger(
        private / "coordinator",
        credential_binding_sha256=CREDENTIAL_BINDING_SHA256,
        minimum_account_reserve=3000,
        maximum_points_per_job=1000,
    )
    return request, voice_catalog, store, ledger, private
