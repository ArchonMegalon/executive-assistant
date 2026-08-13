from __future__ import annotations

import argparse
import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import wave

import pytest

from scripts import materialize_vocallab_provider_verification as materialize
from scripts import probe_vocallab_provider as probe
from scripts import verify_vocallab_provider_verification as verify


ROOT = Path(__file__).resolve().parents[1]
TEST_HMAC_KEY = b"0123456789abcdef0123456789abcdef"
WRONG_HMAC_KEY = b"fedcba9876543210fedcba9876543210"
PRIVATE_VOCALLAB_CONFIG_PATTERN = "config/vocallab_*"
PRIVATE_VOCALLAB_CONFIG_SIBLINGS = (
    "config/vocallab_api_key.bak",
    "config/vocallab_api_key~",
    "config/vocallab_credential_rotation_authority.local.json.tmp",
    "config/vocallab_verification_hmac_key.swp",
    "config/vocallab_voice_catalog.local.json.bak",
)


def _voice_catalog_payload(
    voice_ids: tuple[str, ...] = ("private-voice-id",),
    *,
    active: bool = True,
    rights_class: str = "professional",
) -> dict[str, object]:
    reviewed_at = materialize._utc_timestamp(datetime.now(timezone.utc))
    rows: list[dict[str, object]] = []
    for index, voice_id in enumerate(voice_ids, start=1):
        clone = rights_class == "consented_clone"
        rows.append(
            {
                "provider_voice_id": voice_id,
                "voice_id_sha256": hashlib.sha256(
                    voice_id.encode("utf-8")
                ).hexdigest(),
                "safe_label": f"Approved Narrator {index}",
                "provider_type": "clone" if clone else "preset",
                "rights_class": rights_class,
                "languages": ["en"],
                "tags": ["narration"],
                "allowed_uses": ["audiobook_narration"],
                "blocked_uses": ["memorial"],
                "rights_receipt_id": f"rights-{index}",
                "consent_receipt_id": f"consent-{index}" if clone else "",
                "reviewed_at": reviewed_at,
                "active": active,
            }
        )
    return {
        "contract_name": materialize.VOICE_CATALOG_CONTRACT,
        "catalog_version": 1,
        "voices": rows,
    }


def _voice_catalog(
    voice_ids: tuple[str, ...] = ("private-voice-id",),
    *,
    active: bool = True,
    rights_class: str = "professional",
) -> materialize.ValidatedVoiceCatalog:
    payload = _voice_catalog_payload(
        voice_ids,
        active=active,
        rights_class=rights_class,
    )
    raw = probe._canonical_bytes(payload)
    return materialize._validate_voice_catalog(
        payload,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        now=datetime.now(timezone.utc),
    )


class _InventoryClient:
    def __init__(self, *, voices: list[dict[str, object]] | None = None) -> None:
        self.requests_per_minute = probe.DEFAULT_REQUESTS_PER_MINUTE
        self.credential_binding_sha256 = "1" * 64
        self.calls: list[tuple[str, str]] = []
        exact_unit = (
            "points (billed by text length: ceil(chars/15) on the API; "
            "1 pt ≈ 1 second of audio)"
        )
        exact_voices = [
            (
                {
                    "accent": "neutral",
                    "category": "narration",
                    "id": row["id"],
                    "language_code": "en-US",
                    "languages": ["en"],
                    "name": "Approved fixture voice",
                    "slug": "approved-fixture-voice",
                    "type": "preset",
                }
                if set(row) == {"id"}
                else row
            )
            for row in (voices or [])
        ]
        self._payloads: dict[str, object] = {
            "/api/v1/ping": {
                "message": "Authenticated — your VocalLab API key is working.",
                "ok": True,
                "points": 24000,
                "unit": exact_unit,
            },
            "/api/v1/me": {
                "is_pro": True,
                "is_studio": True,
                "points": 24000,
                "unit": exact_unit,
            },
            "/api/v1/models": {
                "default": "v-pro",
                "models": [
                    {
                        "key": "v-studio",
                        "label": "VocalLab Studio",
                        "steerable": True,
                        "costMultiplier": 1,
                        "gated": True,
                    },
                    {
                        "key": "v-pro",
                        "label": "VocalLab Pro",
                        "steerable": False,
                        "costMultiplier": 1,
                        "gated": False,
                    },
                    {
                        "key": "v-lite",
                        "label": "VocalLab Lite",
                        "steerable": False,
                        "costMultiplier": 0.5,
                        "gated": False,
                    },
                ]
            },
            "/api/v1/voices": {
                "count": len(exact_voices),
                "has_more": False,
                "offset": 0,
                "total": len(exact_voices),
                "voices": exact_voices,
            },
        }

    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> tuple[int, object]:
        del payload
        self.calls.append((method, path))
        return 200, self._payloads[path]


def _inventory_probe(*, voices: list[dict[str, object]] | None = None) -> dict[str, object]:
    client = _InventoryClient(voices=voices)
    receipt = probe.probe_provider(  # type: ignore[arg-type]
        client,
        hmac_key=TEST_HMAC_KEY,
    )
    assert client.calls == [
        ("GET", "/api/v1/ping"),
        ("GET", "/api/v1/me"),
        ("GET", "/api/v1/models"),
        ("GET", "/api/v1/voices"),
    ]
    return receipt


def _canonical_sha256(payload: dict[str, object]) -> str:
    return hashlib.sha256(probe._canonical_bytes(payload)).hexdigest()


def _resign_probe(payload: dict[str, object]) -> dict[str, object]:
    return probe.sign_authenticated_payload(
        payload,
        hmac_key=TEST_HMAC_KEY,
        signed_contract_name=probe.PROBE_CONTRACT,
    )


def _resign_receipt(payload: dict[str, object]) -> dict[str, object]:
    return probe.sign_authenticated_payload(
        payload,
        hmac_key=TEST_HMAC_KEY,
        signed_contract_name=materialize.VERIFICATION_CONTRACT,
    )


def _passing_probe() -> dict[str, object]:
    passing_probe = copy.deepcopy(
        _inventory_probe(voices=[{"id": "private-voice-id"}])
    )
    passing_probe.pop(probe.AUTHENTICATION_FIELD)
    passing_probe["status"] = "pass"
    passing_probe["blockers"] = []
    passing_probe["credential_rotation_required"] = False
    passing_probe["credential_production_eligible"] = True
    passing_probe["request_policy"] = {
        "default_spend_authorized": False,
        "synthetic_tts_requested": True,
        "post_count": 1,
        "post_retry_count": 0,
        "minimum_remaining_points": 3000,
        "requests_per_minute": 30,
    }
    passing_probe["smoke"] = {
        "requested": True,
        "status": "pass",
        "source_text_sha256": probe.SYNTHETIC_TEXT_SHA256,
        "audio_sha256": "c" * 64,
        "content_type": "audio/wav",
        "sample_rate": 44100,
        "points_used": probe.SYNTHETIC_TEXT_POINTS,
        "generation_id_sha256": "d" * 64,
        "charge_state": "charged",
    }
    return _resign_probe(passing_probe)


def _passing_receipt() -> dict[str, object]:
    source_probe = _passing_probe()
    return materialize.materialize_verification(
        source_probe,
        probe_sha256=_canonical_sha256(source_probe),
        catalog=_voice_catalog(),
        hmac_key=TEST_HMAC_KEY,
    )


def test_default_probe_is_get_only_redacted_and_blocks_empty_voice_inventory() -> None:
    receipt = _inventory_probe()

    probe.require_authenticated_payload(
        receipt,
        hmac_key=TEST_HMAC_KEY,
        signed_contract_name=probe.PROBE_CONTRACT,
    )

    assert receipt["status"] == "blocked"
    assert receipt["credential_binding_sha256"] == "1" * 64
    assert receipt["credential_rotation_required"] is True
    assert receipt["credential_production_eligible"] is False
    assert receipt["voices"] == {
        "status": "pass",
        "http_status": 200,
        "voice_count": 0,
        "discovered_voice_hashes": [],
        "raw_voice_ids_exposed": False,
    }
    assert receipt["request_policy"] == {
        "default_spend_authorized": False,
        "synthetic_tts_requested": False,
        "post_count": 0,
        "post_retry_count": 0,
        "minimum_remaining_points": 3000,
        "requests_per_minute": 30,
    }
    assert "voices:empty" in receipt["blockers"]
    assert "smoke:explicit_spend_not_authorized" in receipt["blockers"]
    assert "credential:rotation_required" in receipt["blockers"]
    assert "credential:production_ineligible" in receipt["blockers"]
    encoded = json.dumps(receipt, sort_keys=True)
    assert "24000" not in encoded
    assert "private-account-id" not in encoded
    assert "vl_live_" not in encoded
    assert TEST_HMAC_KEY.decode("ascii") not in encoded


def test_default_probe_never_projects_raw_discovered_voice_ids() -> None:
    receipt = _inventory_probe(voices=[{"id": "private-voice-id"}])

    assert receipt["voices"]["voice_count"] == 1
    assert "private-voice-id" not in json.dumps(receipt, sort_keys=True)
    assert receipt["request_policy"]["post_count"] == 0


def test_verified_live_inventory_shapes_pass_exact_endpoint_parsers() -> None:
    receipt = _inventory_probe(voices=[{"id": "private-voice-id"}])

    assert receipt["ping"] == {"status": "pass", "http_status": 200}
    assert receipt["account"]["status"] == "pass"
    assert receipt["account"]["is_pro"] is True
    assert receipt["account"]["is_studio"] is True
    assert receipt["models"] == {
        "status": "pass",
        "http_status": 200,
        "keys": ["v-studio", "v-pro", "v-lite"],
        "model_count": 3,
    }
    assert receipt["voices"]["status"] == "pass"
    assert not any(
        blocker.endswith(":invalid_provider_response")
        for blocker in receipt["blockers"]
    )


@pytest.mark.parametrize(
    ("endpoint", "replacement", "blocker"),
    (
        (
            "/api/v1/ping",
            {
                "message": "arbitrary 200 response",
                "ok": True,
                "points": 24000,
                "unit": (
                    "points (billed by text length: ceil(chars/15) on the API; "
                    "1 pt ≈ 1 second of audio)"
                ),
            },
            "ping:invalid_provider_response",
        ),
        (
            "/api/v1/me",
            {
                "data": {
                    "is_pro": True,
                    "is_studio": True,
                    "points": 24000,
                }
            },
            "account:invalid_provider_response",
        ),
        (
            "/api/v1/models",
            {
                "default": "v-pro",
                "models": ["v-studio", "v-pro", "v-lite"],
            },
            "models:invalid_provider_response",
        ),
        (
            "/api/v1/voices",
            {"voices": [{"id": "private-voice-id"}]},
            "voices:invalid_provider_response",
        ),
    ),
)
def test_probe_blocks_nonexact_provider_inventory_without_leaking_payload(
    endpoint: str,
    replacement: dict[str, object],
    blocker: str,
) -> None:
    client = _InventoryClient(voices=[{"id": "private-voice-id"}])
    client._payloads[endpoint] = replacement

    receipt = probe.probe_provider(  # type: ignore[arg-type]
        client,
        hmac_key=TEST_HMAC_KEY,
    )

    assert receipt["status"] == "blocked"
    assert blocker in receipt["blockers"]
    section = blocker.split(":", 1)[0]
    assert receipt[section]["status"] == "blocked"
    assert "arbitrary 200 response" not in json.dumps(receipt, sort_keys=True)


def test_probe_blocks_inconsistent_ping_and_account_balance_without_exposing_it() -> None:
    client = _InventoryClient(voices=[{"id": "private-voice-id"}])
    account = client._payloads["/api/v1/me"]
    assert isinstance(account, dict)
    account["points"] = 23999

    receipt = probe.probe_provider(  # type: ignore[arg-type]
        client,
        hmac_key=TEST_HMAC_KEY,
    )

    assert "account:balance_inconsistent" in receipt["blockers"]
    assert receipt["account"]["status"] == "blocked"
    assert receipt["account"]["balance_sufficient_for_smoke"] is False
    assert "23999" not in json.dumps(receipt, sort_keys=True)


@pytest.mark.parametrize("unsafe_reserve", (2999, True, 3000.0))
def test_minimum_reserve_is_nonlowerable_before_any_provider_call(
    unsafe_reserve: object,
) -> None:
    client = _InventoryClient()

    with pytest.raises(
        probe.VocalLabProbeError,
        match="minimum_remaining_points_below_policy",
    ):
        probe.probe_provider(  # type: ignore[arg-type]
            client,
            hmac_key=TEST_HMAC_KEY,
            minimum_remaining_points=unsafe_reserve,
        )
    assert client.calls == []


def test_higher_reserve_is_preserved_inside_authenticated_probe() -> None:
    client = _InventoryClient()
    receipt = probe.probe_provider(  # type: ignore[arg-type]
        client,
        hmac_key=TEST_HMAC_KEY,
        minimum_remaining_points=4000,
    )

    probe.require_authenticated_payload(
        receipt,
        hmac_key=TEST_HMAC_KEY,
        signed_contract_name=probe.PROBE_CONTRACT,
    )
    assert receipt["request_policy"]["minimum_remaining_points"] == 4000
    assert probe._minimum_reserve("3000") == 3000
    with pytest.raises(argparse.ArgumentTypeError, match="at least 3000"):
        probe._minimum_reserve("2999")


def test_probe_refuses_to_sign_a_rate_not_enforced_by_its_client() -> None:
    client = _InventoryClient()
    client.requests_per_minute = 29

    with pytest.raises(
        probe.VocalLabProbeError,
        match="request_rate_limit_mismatch",
    ):
        probe.probe_provider(  # type: ignore[arg-type]
            client,
            hmac_key=TEST_HMAC_KEY,
            requests_per_minute=30,
        )
    assert client.calls == []


class _FakeJsonResponse:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __enter__(self) -> "_FakeJsonResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return b"{}"


class _FakeOpener:
    def __init__(self) -> None:
        self.methods: list[str] = []

    def open(self, request: object, *, timeout: int) -> _FakeJsonResponse:
        del timeout
        self.methods.append(str(request.get_method()))  # type: ignore[attr-defined]
        return _FakeJsonResponse()


def test_one_client_limiter_covers_inventory_post_and_poll_requests() -> None:
    client = probe.VocalLabProbeClient(
        api_key="vl_live_0123456789abcdef",
        base_url=probe.OFFICIAL_BASE_URL,
        timeout_seconds=1,
    )
    opener = _FakeOpener()
    acquisitions = 0

    class _CountingLimiter:
        def acquire(self) -> None:
            nonlocal acquisitions
            acquisitions += 1

    client._opener = opener  # type: ignore[assignment]
    client._rate_limiter = _CountingLimiter()  # type: ignore[assignment]

    client.request_json("GET", "/api/v1/voices")
    client.request_json("POST", "/api/v1/tts", {"synthetic": True})
    client.request_json("GET", "/api/v1/tts/private-generation-id")

    assert acquisitions == 3
    assert opener.methods == ["GET", "POST", "GET"]


class _RawJsonResponse:
    status = 200

    def __init__(self, raw: bytes, *, content_type: str) -> None:
        self._raw = raw
        self.headers = {"Content-Type": content_type}

    def __enter__(self) -> "_RawJsonResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self._raw


class _RawJsonOpener:
    def __init__(self, response: _RawJsonResponse) -> None:
        self._response = response

    def open(self, _request: object, *, timeout: int) -> _RawJsonResponse:
        del timeout
        return self._response


@pytest.mark.parametrize(
    ("raw", "content_type", "reason"),
    (
        (
            b'{"ok":true,"ok":true}',
            "application/json",
            "provider_json_invalid",
        ),
        (
            b'{"points":NaN}',
            "application/json",
            "provider_json_invalid",
        ),
        (b"[]", "application/json", "provider_json_shape_invalid"),
        (b"{}", "text/json", "provider_content_type_invalid"),
    ),
)
def test_probe_client_rejects_ambiguous_json_and_nonexact_mime(
    raw: bytes,
    content_type: str,
    reason: str,
) -> None:
    client = probe.VocalLabProbeClient(
        api_key="vl_live_0123456789abcdef",
        base_url=probe.OFFICIAL_BASE_URL,
        timeout_seconds=1,
    )
    client._opener = _RawJsonOpener(  # type: ignore[assignment]
        _RawJsonResponse(raw, content_type=content_type)
    )

    with pytest.raises(probe.VocalLabProbeError, match=reason) as failure:
        client.request_json("GET", "/api/v1/ping")

    assert "vl_live_" not in str(failure.value)
    assert raw.decode("utf-8") not in str(failure.value)


def test_rolling_window_limiter_enforces_thirty_requests_deterministically() -> None:
    current = 0.0
    sleeps: list[float] = []

    def monotonic() -> float:
        return current

    def sleep(seconds: float) -> None:
        nonlocal current
        sleeps.append(seconds)
        current += seconds

    limiter = probe.RollingWindowRateLimiter(
        requests_per_minute=30,
        monotonic=monotonic,
        sleep=sleep,
    )

    for _ in range(31):
        limiter.acquire()

    assert sleeps == [60.0]
    assert current == 60.0


def test_materialized_verification_honestly_blocks_current_empty_inventory() -> None:
    source_probe = _inventory_probe()
    catalog = _voice_catalog()
    receipt = materialize.materialize_verification(
        source_probe,
        probe_sha256=_canonical_sha256(source_probe),
        catalog=catalog,
        hmac_key=TEST_HMAC_KEY,
    )

    assert receipt["status"] == "blocked"
    assert "voices_empty" in receipt["blockers"]
    assert "synthetic_smoke_not_passed" in receipt["blockers"]
    assert receipt["version"] == 2
    assert receipt["catalog_sha256"] == catalog.source_sha256
    assert receipt["voices"]["raw_voice_ids_exposed"] is False
    issues = verify.verify_receipt(receipt, hmac_key=TEST_HMAC_KEY)
    assert "gate:voices" in issues
    assert "value:discovered_voice_hashes" not in issues


def test_passing_synthetic_projection_verifies_without_exposing_private_ids() -> None:
    source_probe = _passing_probe()
    receipt = materialize.materialize_verification(
        source_probe,
        probe_sha256=_canonical_sha256(source_probe),
        catalog=_voice_catalog(),
        hmac_key=TEST_HMAC_KEY,
    )

    assert receipt["status"] == "pass"
    assert receipt["blockers"] == []
    assert verify.verify_receipt(receipt, hmac_key=TEST_HMAC_KEY) == []
    assert set(receipt) == {
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
        "authentication",
    }
    generated = materialize._parse_utc_timestamp(
        receipt["generated_at"],
        reason="test",
    )
    expires = materialize._parse_utc_timestamp(
        receipt["expires_at"],
        reason="test",
    )
    assert int((expires - generated).total_seconds()) == 86400
    assert receipt["models"]["keys"] == ["v-studio", "v-pro", "v-lite"]
    assert receipt["discovered_voice_hashes"] == [
        hashlib.sha256(b"private-voice-id").hexdigest()
    ]
    assert receipt["voices"]["voice_count"] == len(
        receipt["discovered_voice_hashes"]
    )
    assert receipt["request_safety"] == {
        "status": "pass",
        "max_chars_per_request": 1800,
        "requests_per_minute": 30,
        "max_in_flight": 1,
        "minimum_remaining_points": 3000,
        "blind_post_retry_allowed": False,
        "url_fallback_enabled": False,
    }
    encoded = json.dumps(receipt, sort_keys=True)
    assert "private-voice-id" not in encoded
    assert "vl_live_" not in encoded


def test_production_eligible_posture_requires_verified_rotation_evidence() -> None:
    client = _InventoryClient(voices=[{"id": "private-voice-id"}])

    with pytest.raises(probe.VocalLabProbeError, match="credential_posture_invalid"):
        probe.probe_provider(  # type: ignore[arg-type]
            client,
            hmac_key=TEST_HMAC_KEY,
            credential_rotation_required=False,
            credential_production_eligible=True,
        )
    assert client.calls == []


def test_explicit_key_file_overrides_stale_private_env_but_not_process_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale_key = "vl_live_" + "a" * 24
    replacement_key = "vl_live_" + "b" * 24
    process_key = "vl_live_" + "c" * 24
    env_file = tmp_path / ".env"
    key_file = tmp_path / "replacement.key"
    env_file.write_text(f"VOCALLAB_API_KEY={stale_key}\n", encoding="utf-8")
    key_file.write_text(replacement_key + "\n", encoding="utf-8")
    env_file.chmod(0o600)
    key_file.chmod(0o600)
    monkeypatch.delenv("VOCALLAB_API_KEY", raising=False)

    assert probe._load_api_key(key_file, env_file=env_file) == replacement_key

    monkeypatch.setenv("VOCALLAB_API_KEY", process_key)
    with pytest.raises(probe.VocalLabProbeError, match="api_key_sources_disagree"):
        probe._load_api_key(key_file, env_file=env_file)


def test_rotation_authority_binds_revoked_exposed_key_to_replacement(
    tmp_path: Path,
) -> None:
    exposed = hashlib.sha256(b"exposed-key").hexdigest()
    replacement = hashlib.sha256(b"replacement-key").hexdigest()
    authority_file = tmp_path / "rotation.json"
    payload = {
        "contract_name": probe.CREDENTIAL_ROTATION_AUTHORITY_CONTRACT,
        "version": 1,
        "status": "pass",
        "exposed_credential_binding_sha256": exposed,
        "replacement_credential_binding_sha256": replacement,
        "exposed_key_revoked": True,
        "rotation_id_sha256": "d" * 64,
        "approved_by_sha256": "e" * 64,
    }
    authority_file.write_bytes(probe._canonical_bytes(payload))
    authority_file.chmod(0o600)

    probe._load_credential_rotation_authority(
        authority_file,
        exposed_credential_binding_sha256=exposed,
        replacement_credential_binding_sha256=replacement,
    )
    payload["replacement_credential_binding_sha256"] = exposed
    authority_file.write_bytes(probe._canonical_bytes(payload))
    authority_file.chmod(0o600)
    with pytest.raises(
        probe.VocalLabProbeError,
        match="credential_rotation_authority_invalid",
    ):
        probe._load_credential_rotation_authority(
            authority_file,
            exposed_credential_binding_sha256=exposed,
            replacement_credential_binding_sha256=exposed,
        )
    payload["replacement_credential_binding_sha256"] = replacement
    payload["exposed_credential_binding_sha256"] = "f" * 64
    authority_file.write_bytes(probe._canonical_bytes(payload))
    authority_file.chmod(0o600)
    with pytest.raises(
        probe.VocalLabProbeError,
        match="credential_rotation_authority_invalid",
    ):
        probe._load_credential_rotation_authority(
            authority_file,
            exposed_credential_binding_sha256=exposed,
            replacement_credential_binding_sha256=replacement,
        )


def test_make_probe_requires_explicit_key_and_rotation_authority_inputs() -> None:
    source = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "VOCALLAB_PROBE_KEY_FILE ?=" in source
    assert "VOCALLAB_CREDENTIAL_ROTATION_AUTHORITY_FILE ?=" in source
    assert "--key-file \"$(VOCALLAB_PROBE_KEY_FILE)\"" in source
    assert (
        "--credential-rotation-authority-file "
        '\"$(VOCALLAB_CREDENTIAL_ROTATION_AUTHORITY_FILE)\"'
    ) in source


def test_promotion_receipt_requires_the_runtime_exact_signed_reserve() -> None:
    source_probe = _passing_probe()
    source_probe["request_policy"]["minimum_remaining_points"] = 4000
    source_probe = _resign_probe(source_probe)

    receipt = materialize.materialize_verification(
        source_probe,
        probe_sha256=_canonical_sha256(source_probe),
        catalog=_voice_catalog(),
        hmac_key=TEST_HMAC_KEY,
    )

    assert receipt["status"] == "blocked"
    assert "request_safety_unverified" in receipt["blockers"]
    assert receipt["request_safety"]["minimum_remaining_points"] == 4000
    assert receipt["request_safety"]["status"] == "blocked"


def test_materializer_and_verifier_keep_unrotated_credential_blocked() -> None:
    source_probe = _passing_probe()
    source_probe.pop(probe.AUTHENTICATION_FIELD)
    source_probe["credential_rotation_required"] = True
    source_probe["credential_production_eligible"] = False
    source_probe = _resign_probe(source_probe)

    receipt = materialize.materialize_verification(
        source_probe,
        probe_sha256=_canonical_sha256(source_probe),
        catalog=_voice_catalog(),
        hmac_key=TEST_HMAC_KEY,
    )

    assert receipt["status"] == "blocked"
    assert "credential_rotation_required" in receipt["blockers"]
    assert "credential_production_ineligible" in receipt["blockers"]
    issues = verify.verify_receipt(receipt, hmac_key=TEST_HMAC_KEY)
    assert "gate:credential_posture" in issues


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("audio_sha256", ""),
        ("audio_sha256", "not-a-sha256"),
        ("generation_id_sha256", ""),
        ("generation_id_sha256", "not-a-sha256"),
        ("source_text_sha256", "f" * 64),
        ("content_type", "audio/mpeg"),
        ("charge_state", "not_charged"),
        ("points_used", 0),
        ("points_used", probe.SYNTHETIC_TEXT_POINTS + 1),
    ),
)
def test_materializer_rejects_fabricated_smoke_evidence(
    field: str,
    value: object,
) -> None:
    tampered = _passing_probe()
    tampered["smoke"][field] = value

    with pytest.raises(
        materialize.VocalLabVerificationError,
        match="probe_authentication_invalid",
    ):
        materialize.materialize_verification(
            tampered,
            probe_sha256=_canonical_sha256(tampered),
            catalog=_voice_catalog(),
            hmac_key=TEST_HMAC_KEY,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("audio_sha256", ""),
        ("audio_sha256", "not-a-sha256"),
        ("generation_id_sha256", ""),
        ("generation_id_sha256", "not-a-sha256"),
        ("source_text_sha256", "f" * 64),
        ("content_type", "audio/mpeg"),
        ("charge_state", "not_charged"),
        ("points_used", 0),
        ("points_used", probe.SYNTHETIC_TEXT_POINTS + 1),
    ),
)
def test_verifier_rejects_tampered_smoke_evidence(
    field: str,
    value: object,
) -> None:
    source_probe = _passing_probe()
    receipt = materialize.materialize_verification(
        source_probe,
        probe_sha256=_canonical_sha256(source_probe),
        catalog=_voice_catalog(),
        hmac_key=TEST_HMAC_KEY,
    )
    receipt["smoke"][field] = value

    assert verify.verify_receipt(receipt, hmac_key=TEST_HMAC_KEY) == [
        "authentication:invalid"
    ]


def _synthetic_wav_bytes(
    *,
    frame_count: int = 4410,
    sample: bytes = b"\x01\x00",
) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        handle.writeframes(sample * frame_count)
    return output.getvalue()


def _synthetic_wav_base64() -> str:
    return base64.b64encode(_synthetic_wav_bytes()).decode("ascii")


class _CapturingSyntheticClient:
    def __init__(self) -> None:
        self.requests_per_minute = probe.DEFAULT_REQUESTS_PER_MINUTE
        self.credential_binding_sha256 = "1" * 64
        self.requests: list[
            tuple[str, str, dict[str, object] | None]
        ] = []
        exact_unit = (
            "points (billed by text length: ceil(chars/15) on the API; "
            "1 pt ≈ 1 second of audio)"
        )
        self._inventory = {
            "/api/v1/ping": {
                "message": "Authenticated — your VocalLab API key is working.",
                "ok": True,
                "points": 24000,
                "unit": exact_unit,
            },
            "/api/v1/me": {
                "is_pro": True,
                "is_studio": True,
                "points": 24000,
                "unit": exact_unit,
            },
            "/api/v1/models": {
                "default": "v-pro",
                "models": [
                    {
                        "key": "v-studio",
                        "label": "VocalLab Studio",
                        "steerable": True,
                        "costMultiplier": 1,
                        "gated": True,
                    },
                    {
                        "key": "v-pro",
                        "label": "VocalLab Pro",
                        "steerable": False,
                        "costMultiplier": 1,
                        "gated": False,
                    },
                    {
                        "key": "v-lite",
                        "label": "VocalLab Lite",
                        "steerable": False,
                        "costMultiplier": 0.5,
                        "gated": False,
                    },
                ],
            },
            "/api/v1/voices": {
                "count": 1,
                "has_more": False,
                "offset": 0,
                "total": 1,
                "voices": [
                    {
                        "accent": "neutral",
                        "category": "narration",
                        "id": "private-voice-id",
                        "language_code": "en-US",
                        "languages": ["en"],
                        "name": "Approved fixture voice",
                        "slug": "approved-fixture-voice",
                        "type": "preset",
                    }
                ],
            },
        }

    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> tuple[int, object]:
        captured = copy.deepcopy(payload)
        self.requests.append((method, path, captured))
        if method == "POST":
            return 200, {
                "id": "private-generation-id",
                "status": "ready",
                "model": "v-pro",
                "format": "WAV",
                "audio_base64": _synthetic_wav_base64(),
                "points_used": probe.SYNTHETIC_TEXT_POINTS,
            }
        return 200, self._inventory[path]


class _ScriptedGenerationClient:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self._responses = copy.deepcopy(responses)
        self.requests: list[tuple[str, str]] = []

    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> tuple[int, object]:
        del payload
        self.requests.append((method, path))
        if not self._responses:
            raise AssertionError("unexpected request")
        return 200, self._responses.pop(0)


def _valid_generation(**overrides: object) -> dict[str, object]:
    response: dict[str, object] = {
        "id": "private-generation-id",
        "status": "ready",
        "model": "v-pro",
        "format": "WAV",
        "audio_base64": _synthetic_wav_base64(),
        "points_used": probe.SYNTHETIC_TEXT_POINTS,
    }
    response.update(overrides)
    return response


def _pending_generation(**overrides: object) -> dict[str, object]:
    response: dict[str, object] = {
        "id": "private-generation-id",
        "status": "pending",
        "model": "v-pro",
        "format": "WAV",
    }
    response.update(overrides)
    return response


def test_synthetic_smoke_is_fail_closed_until_durable_spend_lane_exists() -> None:
    client = _CapturingSyntheticClient()

    with pytest.raises(
        probe.VocalLabProbeError,
        match="synthetic_tts_spending_lane_disabled",
    ):
        probe.probe_provider(  # type: ignore[arg-type]
            client,
            hmac_key=TEST_HMAC_KEY,
            allow_synthetic_tts=True,
            voice_id="private-voice-id",
            poll_interval_seconds=1,
            poll_timeout_seconds=1,
        )

    assert client.requests == []


@pytest.mark.parametrize(
    "audio",
    (
        b"RIFF\x24\x00\x00\x00WAVE",
        _synthetic_wav_bytes(frame_count=1),
        _synthetic_wav_bytes(sample=b"\x00\x00"),
    ),
)
def test_smoke_wav_requires_real_frames_duration_and_signal(audio: bytes) -> None:
    with pytest.raises(probe.VocalLabProbeError, match="generation_audio_invalid"):
        probe._validate_wav(audio, expected_sample_rate=44100)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    (
        ("status", "", "generation_response_invalid"),
        ("model", "v-studio", "generation_response_invalid"),
        ("model", None, "generation_response_invalid"),
        ("format", "wav", "generation_response_invalid"),
        ("format", None, "generation_response_invalid"),
        ("content_type", "audio/wav", "generation_response_invalid"),
        ("points_used", True, "generation_response_invalid"),
        ("points_used", -1, "generation_response_invalid"),
        ("points_used", 0, "generation_response_invalid"),
        (
            "points_used",
            probe.SYNTHETIC_TEXT_POINTS + 1,
            "generation_points_invalid",
        ),
    ),
)
def test_smoke_requires_explicit_exact_generation_evidence(
    field: str,
    value: object,
    reason: str,
) -> None:
    client = _ScriptedGenerationClient([_valid_generation(**{field: value})])

    with pytest.raises(probe.VocalLabProbeError, match=reason):
        probe._perform_synthetic_smoke(  # type: ignore[arg-type]
            client,
            voice_id="private-voice-id",
            poll_interval_seconds=0,
            poll_timeout_seconds=1,
            max_audio_bytes=probe.DEFAULT_MAX_AUDIO_BYTES,
        )


def test_smoke_requires_generation_id_on_post() -> None:
    response = _valid_generation()
    del response["id"]
    client = _ScriptedGenerationClient([response])

    with pytest.raises(
        probe.VocalLabProbeError,
        match="generation_response_invalid",
    ):
        probe._perform_synthetic_smoke(  # type: ignore[arg-type]
            client,
            voice_id="private-voice-id",
            poll_interval_seconds=0,
            poll_timeout_seconds=1,
            max_audio_bytes=probe.DEFAULT_MAX_AUDIO_BYTES,
        )


def test_smoke_poll_requires_same_generation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _pending_generation()
    completed = _valid_generation(id="different-generation-id")
    client = _ScriptedGenerationClient([pending, completed])
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)

    with pytest.raises(
        probe.VocalLabProbeError,
        match="generation_response_invalid",
    ):
        probe._perform_synthetic_smoke(  # type: ignore[arg-type]
            client,
            voice_id="private-voice-id",
            poll_interval_seconds=1,
            poll_timeout_seconds=1,
            max_audio_bytes=probe.DEFAULT_MAX_AUDIO_BYTES,
        )
    assert client.requests == [
        ("POST", "/api/v1/tts"),
        ("GET", "/api/v1/tts/private-generation-id"),
    ]


def test_smoke_poll_accepts_only_same_completed_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _pending_generation()
    client = _ScriptedGenerationClient([pending, _valid_generation()])
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)

    result = probe._perform_synthetic_smoke(  # type: ignore[arg-type]
        client,
        voice_id="private-voice-id",
        poll_interval_seconds=1,
        poll_timeout_seconds=1,
        max_audio_bytes=probe.DEFAULT_MAX_AUDIO_BYTES,
    )

    assert result["status"] == "pass"
    assert result["points_used"] == probe.SYNTHETIC_TEXT_POINTS
    assert client.requests == [
        ("POST", "/api/v1/tts"),
        ("GET", "/api/v1/tts/private-generation-id"),
    ]


def test_smoke_materializes_exact_inline_audio_without_forced_poll() -> None:
    client = _ScriptedGenerationClient(
        [
            _pending_generation(
                audio_base64=_synthetic_wav_base64(),
                audio_url=None,
                points_used=probe.SYNTHETIC_TEXT_POINTS,
            )
        ]
    )

    result = probe._perform_synthetic_smoke(  # type: ignore[arg-type]
        client,
        voice_id="private-voice-id",
        poll_interval_seconds=1,
        poll_timeout_seconds=1,
        max_audio_bytes=probe.DEFAULT_MAX_AUDIO_BYTES,
    )

    assert result["status"] == "pass"
    assert result["points_used"] == probe.SYNTHETIC_TEXT_POINTS
    assert client.requests == [("POST", "/api/v1/tts")]


def test_materializer_rejects_unsigned_in_memory_passing_smoke() -> None:
    unsigned = _passing_probe()
    unsigned.pop(probe.AUTHENTICATION_FIELD)

    with pytest.raises(
        materialize.VocalLabVerificationError,
        match="probe_authentication_invalid",
    ):
        materialize.materialize_verification(
            unsigned,
            probe_sha256=_canonical_sha256(unsigned),
            catalog=_voice_catalog(),
            hmac_key=TEST_HMAC_KEY,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("hmac_sha256", "0" * 64),
        ("payload_sha256", "1" * 64),
        ("key_id_sha256", "2" * 64),
        ("algorithm", "sha256"),
    ),
)
def test_materializer_rejects_probe_authentication_tamper(
    field: str,
    value: object,
) -> None:
    tampered = _passing_probe()
    tampered[probe.AUTHENTICATION_FIELD][field] = value

    with pytest.raises(
        materialize.VocalLabVerificationError,
        match="probe_authentication_invalid",
    ):
        materialize.materialize_verification(
            tampered,
            probe_sha256=_canonical_sha256(tampered),
            catalog=_voice_catalog(),
            hmac_key=TEST_HMAC_KEY,
        )


def test_materializer_rejects_probe_signed_by_wrong_key() -> None:
    source_probe = _passing_probe()

    with pytest.raises(
        materialize.VocalLabVerificationError,
        match="probe_authentication_invalid",
    ):
        materialize.materialize_verification(
            source_probe,
            probe_sha256=_canonical_sha256(source_probe),
            catalog=_voice_catalog(),
            hmac_key=WRONG_HMAC_KEY,
        )


def test_materializer_checks_structural_evidence_after_valid_authentication() -> None:
    invalid = _passing_probe()
    invalid["smoke"]["content_type"] = "audio/mpeg"
    invalid = _resign_probe(invalid)

    with pytest.raises(
        materialize.VocalLabVerificationError,
        match="probe_smoke_evidence_invalid",
    ):
        materialize.materialize_verification(
            invalid,
            probe_sha256=_canonical_sha256(invalid),
            catalog=_voice_catalog(),
            hmac_key=TEST_HMAC_KEY,
        )


@pytest.mark.parametrize(
    ("case", "reason"),
    (
        ("model_count", "probe_models_schema_invalid"),
        ("model_order", "probe_models_schema_invalid"),
        ("voice_count", "probe_voices_schema_invalid"),
    ),
)
def test_materializer_rejects_authenticated_inventory_count_or_order_drift(
    case: str,
    reason: str,
) -> None:
    invalid = _passing_probe()
    invalid.pop(probe.AUTHENTICATION_FIELD)
    if case == "model_count":
        invalid["models"]["model_count"] = 4
    elif case == "model_order":
        invalid["models"]["keys"] = ["v-pro", "v-studio", "v-lite"]
    elif case == "voice_count":
        invalid["voices"]["voice_count"] = 2
    else:  # pragma: no cover - protects the test table itself
        raise AssertionError(case)
    invalid = _resign_probe(invalid)

    with pytest.raises(materialize.VocalLabVerificationError, match=reason):
        materialize.materialize_verification(
            invalid,
            probe_sha256=_canonical_sha256(invalid),
            catalog=_voice_catalog(),
            hmac_key=TEST_HMAC_KEY,
        )


def test_verifier_refuses_unsigned_or_wrong_key_receipt_before_gates() -> None:
    source_probe = _passing_probe()
    receipt = materialize.materialize_verification(
        source_probe,
        probe_sha256=_canonical_sha256(source_probe),
        catalog=_voice_catalog(),
        hmac_key=TEST_HMAC_KEY,
    )
    unsigned = copy.deepcopy(receipt)
    unsigned.pop(probe.AUTHENTICATION_FIELD)

    assert verify.verify_receipt(unsigned, hmac_key=TEST_HMAC_KEY) == [
        "authentication:invalid"
    ]
    assert verify.verify_receipt(receipt, hmac_key=WRONG_HMAC_KEY) == [
        "authentication:invalid"
    ]


def test_verifier_checks_gates_only_after_valid_authentication() -> None:
    source_probe = _passing_probe()
    receipt = materialize.materialize_verification(
        source_probe,
        probe_sha256=_canonical_sha256(source_probe),
        catalog=_voice_catalog(),
        hmac_key=TEST_HMAC_KEY,
    )
    receipt["smoke"]["sample_rate"] = 22050
    receipt = _resign_receipt(receipt)

    assert "gate:synthetic_smoke" in verify.verify_receipt(
        receipt,
        hmac_key=TEST_HMAC_KEY,
    )


@pytest.mark.parametrize(
    ("section", "field", "value", "issue"),
    (
        ("root", "version", True, "value:version"),
        ("root", "secrets_exposed", 0, "value:secrets_exposed"),
        (
            "account",
            "exact_balance_exposed",
            0,
            "gate:balance_reserve",
        ),
        ("smoke", "points_used", 0, "gate:synthetic_smoke"),
        ("smoke", "points_used", True, "gate:synthetic_smoke"),
        ("smoke", "sample_rate", True, "gate:synthetic_smoke"),
        ("request_safety", "max_in_flight", True, "gate:request_safety"),
        (
            "request_safety",
            "minimum_remaining_points",
            True,
            "gate:request_safety",
        ),
        (
            "request_safety",
            "minimum_remaining_points",
            4000,
            "gate:request_safety",
        ),
        (
            "request_safety",
            "blind_post_retry_allowed",
            0,
            "gate:request_safety",
        ),
        (
            "retention",
            "generation_history_days",
            True,
            "gate:retention",
        ),
    ),
)
def test_verifier_is_type_strict_after_valid_resigning(
    section: str,
    field: str,
    value: object,
    issue: str,
) -> None:
    receipt = _passing_receipt()
    if section == "root":
        receipt[field] = value
    else:
        nested = receipt[section]
        assert isinstance(nested, dict)
        nested[field] = value
    receipt = _resign_receipt(receipt)

    assert issue in verify.verify_receipt(receipt, hmac_key=TEST_HMAC_KEY)


def test_verifier_rejects_authenticated_legacy_and_invalid_freshness() -> None:
    source_probe = _passing_probe()
    receipt = materialize.materialize_verification(
        source_probe,
        probe_sha256=_canonical_sha256(source_probe),
        catalog=_voice_catalog(),
        hmac_key=TEST_HMAC_KEY,
    )

    legacy = copy.deepcopy(receipt)
    legacy["version"] = 1
    legacy = _resign_receipt(legacy)
    assert "value:version" in verify.verify_receipt(
        legacy,
        hmac_key=TEST_HMAC_KEY,
    )

    expired = copy.deepcopy(receipt)
    generated = datetime(2026, 1, 1, tzinfo=timezone.utc)
    expired["generated_at"] = materialize._utc_timestamp(generated)
    expired["expires_at"] = materialize._utc_timestamp(
        generated + timedelta(days=1)
    )
    expired = _resign_receipt(expired)
    assert "gate:freshness" in verify.verify_receipt(
        expired,
        hmac_key=TEST_HMAC_KEY,
        now=generated + timedelta(days=2),
    )


def test_private_voice_catalog_digest_requires_owner_only_regular_json(
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "catalog.json"
    payload = _voice_catalog_payload()
    raw = probe._canonical_bytes(payload)
    catalog.write_bytes(raw)
    catalog.chmod(0o600)

    validated = materialize._read_private_catalog(
        catalog,
        now=datetime.now(timezone.utc),
    )
    assert validated.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert validated.voice_hashes == (
        hashlib.sha256(b"private-voice-id").hexdigest(),
    )

    catalog.chmod(0o640)
    with pytest.raises(
        materialize.VocalLabVerificationError,
        match="voice_catalog_identity_invalid",
    ):
        materialize._read_private_catalog(
            catalog,
            now=datetime.now(timezone.utc),
        )


@pytest.mark.parametrize(
    ("case", "reason"),
    (
        ("extra_root_key", "voice_catalog_schema_invalid"),
        ("boolean_version", "voice_catalog_schema_invalid"),
        ("community_rights", "voice_catalog_rights_invalid"),
        ("clone_without_consent", "voice_catalog_rights_invalid"),
        ("voice_hash_mismatch", "voice_catalog_voice_hash_invalid"),
        ("duplicate_voice", "voice_catalog_duplicate_voice"),
    ),
)
def test_voice_catalog_is_exact_rights_bound_active_and_nonempty(
    case: str,
    reason: str,
) -> None:
    payload = _voice_catalog_payload()
    rows = payload["voices"]
    assert isinstance(rows, list)
    row = rows[0]
    assert isinstance(row, dict)
    if case == "extra_root_key":
        payload["unexpected"] = True
    elif case == "boolean_version":
        payload["catalog_version"] = True
    elif case == "community_rights":
        row["rights_class"] = "community"
    elif case == "clone_without_consent":
        row["rights_class"] = "consented_clone"
        row["provider_type"] = "clone"
        row["consent_receipt_id"] = ""
    elif case == "voice_hash_mismatch":
        row["voice_id_sha256"] = "0" * 64
    elif case == "duplicate_voice":
        rows.append(copy.deepcopy(row))
    else:  # pragma: no cover - protects the test table itself
        raise AssertionError(case)

    with pytest.raises(materialize.VocalLabVerificationError, match=reason):
        materialize._validate_voice_catalog(
            payload,
            source_sha256="a" * 64,
            now=datetime.now(timezone.utc),
        )


@pytest.mark.parametrize("case", ("empty", "inactive_only"))
def test_schema_valid_catalog_without_active_voices_materializes_blocked(
    case: str,
) -> None:
    payload = _voice_catalog_payload()
    rows = payload["voices"]
    assert isinstance(rows, list)
    if case == "empty":
        payload["voices"] = []
    else:
        assert isinstance(rows[0], dict)
        rows[0]["active"] = False
    raw = probe._canonical_bytes(payload)
    catalog = materialize._validate_voice_catalog(
        payload,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        now=datetime.now(timezone.utc),
    )

    receipt = materialize.materialize_verification(
        _inventory_probe(),
        probe_sha256="a" * 64,
        catalog=catalog,
        hmac_key=TEST_HMAC_KEY,
    )

    assert receipt["status"] == "blocked"
    assert "voice_catalog_active_inventory_empty" in receipt["blockers"]


def test_materializer_binds_only_active_catalog_inventory_to_discovery() -> None:
    source_probe = _passing_probe()
    payload = _voice_catalog_payload(
        ("private-voice-id", "retired-private-voice-id")
    )
    rows = payload["voices"]
    assert isinstance(rows, list)
    assert isinstance(rows[1], dict)
    rows[1]["active"] = False
    raw = probe._canonical_bytes(payload)
    catalog = materialize._validate_voice_catalog(
        payload,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        now=datetime.now(timezone.utc),
    )

    receipt = materialize.materialize_verification(
        source_probe,
        probe_sha256=_canonical_sha256(source_probe),
        catalog=catalog,
        hmac_key=TEST_HMAC_KEY,
    )

    assert receipt["status"] == "pass"
    assert "retired-private-voice-id" not in json.dumps(receipt, sort_keys=True)
    assert hashlib.sha256(b"retired-private-voice-id").hexdigest() not in receipt[
        "discovered_voice_hashes"
    ]


def test_approved_catalog_is_a_subset_of_provider_discovery_inventory() -> None:
    source_probe = _passing_probe()
    source_probe.pop(probe.AUTHENTICATION_FIELD)
    extra_hash = hashlib.sha256(b"unapproved-provider-voice").hexdigest()
    discovered = source_probe["voices"]["discovered_voice_hashes"]
    assert isinstance(discovered, list)
    discovered.append(extra_hash)
    discovered.sort()
    source_probe["voices"]["voice_count"] = len(discovered)
    source_probe = _resign_probe(source_probe)

    receipt = materialize.materialize_verification(
        source_probe,
        probe_sha256=_canonical_sha256(source_probe),
        catalog=_voice_catalog(),
        hmac_key=TEST_HMAC_KEY,
    )

    assert receipt["status"] == "pass"
    assert receipt["discovered_voice_hashes"] == discovered
    assert "voice_catalog_discovery_mismatch" not in receipt["blockers"]


def test_materializer_blocks_catalog_discovery_hash_mismatch() -> None:
    source_probe = _passing_probe()
    receipt = materialize.materialize_verification(
        source_probe,
        probe_sha256=_canonical_sha256(source_probe),
        catalog=_voice_catalog(("different-private-voice-id",)),
        hmac_key=TEST_HMAC_KEY,
    )

    assert receipt["status"] == "blocked"
    assert "voice_catalog_discovery_mismatch" in receipt["blockers"]
    encoded = json.dumps(receipt, sort_keys=True)
    assert "different-private-voice-id" not in encoded
    assert "private-voice-id" not in encoded


def _write_hmac_key(path: Path, value: bytes = TEST_HMAC_KEY) -> None:
    path.write_bytes(value)
    path.chmod(0o600)


def test_verification_hmac_key_loader_requires_exact_private_identity(
    tmp_path: Path,
) -> None:
    key_path = tmp_path / "verification.key"
    _write_hmac_key(key_path)

    assert probe.load_verification_hmac_key(key_path) == TEST_HMAC_KEY

    key_path.chmod(0o400)
    with pytest.raises(
        probe.VocalLabProbeError,
        match="verification_hmac_key_invalid",
    ):
        probe.load_verification_hmac_key(key_path)


@pytest.mark.parametrize("size", (0, 31, 257))
def test_verification_hmac_key_loader_rejects_unbounded_sizes(
    tmp_path: Path,
    size: int,
) -> None:
    key_path = tmp_path / "verification.key"
    _write_hmac_key(key_path, b"x" * size)

    with pytest.raises(
        probe.VocalLabProbeError,
        match="verification_hmac_key_invalid",
    ):
        probe.load_verification_hmac_key(key_path)


def test_verification_hmac_key_loader_rejects_symlink_and_hardlink(
    tmp_path: Path,
) -> None:
    key_path = tmp_path / "verification.key"
    symlink_path = tmp_path / "verification.symlink"
    hardlink_path = tmp_path / "verification.hardlink"
    _write_hmac_key(key_path)
    symlink_path.symlink_to(key_path)

    with pytest.raises(
        probe.VocalLabProbeError,
        match="verification_hmac_key_invalid",
    ):
        probe.load_verification_hmac_key(symlink_path)

    os.link(key_path, hardlink_path)
    with pytest.raises(
        probe.VocalLabProbeError,
        match="verification_hmac_key_invalid",
    ):
        probe.load_verification_hmac_key(key_path)
    with pytest.raises(
        probe.VocalLabProbeError,
        match="verification_hmac_key_invalid",
    ):
        probe.load_verification_hmac_key(hardlink_path)


def test_api_key_and_voice_id_loaders_reject_symlink_and_hardlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VOCALLAB_API_KEY", raising=False)
    monkeypatch.delenv("VOCALLAB_API_KEY_FILE", raising=False)
    env_file = tmp_path / "absent.env"
    api_key = tmp_path / "api.key"
    api_symlink = tmp_path / "api.symlink"
    api_hardlink = tmp_path / "api.hardlink"
    api_key.write_text("vl_live_0123456789abcdef", encoding="utf-8")
    api_key.chmod(0o600)

    assert probe._load_api_key(api_key, env_file=env_file) == (
        "vl_live_0123456789abcdef"
    )
    api_symlink.symlink_to(api_key)
    with pytest.raises(probe.VocalLabProbeError, match="api_key_file_invalid"):
        probe._load_api_key(api_symlink, env_file=env_file)
    os.link(api_key, api_hardlink)
    with pytest.raises(probe.VocalLabProbeError, match="api_key_file_invalid"):
        probe._load_api_key(api_key, env_file=env_file)
    with pytest.raises(probe.VocalLabProbeError, match="api_key_file_invalid"):
        probe._load_api_key(api_hardlink, env_file=env_file)

    voice_id = tmp_path / "voice.id"
    voice_symlink = tmp_path / "voice.symlink"
    voice_hardlink = tmp_path / "voice.hardlink"
    voice_id.write_text("private-voice-id", encoding="utf-8")
    voice_id.chmod(0o600)
    assert probe._read_owner_secret(
        voice_id,
        reason="voice_id_file_invalid",
    ) == "private-voice-id"
    voice_symlink.symlink_to(voice_id)
    with pytest.raises(probe.VocalLabProbeError, match="voice_id_file_invalid"):
        probe._read_owner_secret(
            voice_symlink,
            reason="voice_id_file_invalid",
        )
    os.link(voice_id, voice_hardlink)
    with pytest.raises(probe.VocalLabProbeError, match="voice_id_file_invalid"):
        probe._read_owner_secret(
            voice_id,
            reason="voice_id_file_invalid",
        )
    with pytest.raises(probe.VocalLabProbeError, match="voice_id_file_invalid"):
        probe._read_owner_secret(
            voice_hardlink,
            reason="voice_id_file_invalid",
        )


def test_strict_secret_loader_rejects_path_swap_after_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_path = tmp_path / "verification.key"
    replacement = tmp_path / "replacement.key"
    _write_hmac_key(key_path)
    _write_hmac_key(replacement, WRONG_HMAC_KEY)
    real_open = probe.os.open
    swapped = False

    def swapping_open(
        path: object,
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        nonlocal swapped
        descriptor = real_open(path, flags, *args, **kwargs)
        if Path(path) == key_path and not swapped:
            swapped = True
            key_path.unlink()
            key_path.symlink_to(replacement)
        return descriptor

    monkeypatch.setattr(probe.os, "open", swapping_open)

    with pytest.raises(
        probe.VocalLabProbeError,
        match="verification_hmac_key_invalid",
    ):
        probe.load_verification_hmac_key(key_path)
    assert swapped


def test_hmac_loader_detects_same_inode_mutation_between_double_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_path = tmp_path / "verification.key"
    _write_hmac_key(key_path)
    real_lseek = probe.os.lseek
    mutated = False

    def mutating_lseek(descriptor: int, offset: int, whence: int) -> int:
        nonlocal mutated
        if not mutated:
            mutated = True
            writer = os.open(key_path, os.O_WRONLY)
            try:
                os.write(writer, WRONG_HMAC_KEY)
                os.fsync(writer)
            finally:
                os.close(writer)
        return real_lseek(descriptor, offset, whence)

    monkeypatch.setattr(probe.os, "lseek", mutating_lseek)

    with pytest.raises(
        probe.VocalLabProbeError,
        match="verification_hmac_key_invalid",
    ):
        probe.load_verification_hmac_key(key_path)
    assert mutated


def test_verification_hmac_key_initializer_is_explicit_random_and_one_shot(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    key_path = tmp_path / "private" / "verification.key"

    probe.initialize_verification_hmac_key(key_path)

    first = probe.load_verification_hmac_key(key_path)
    assert capsys.readouterr().out == ""
    assert len(first) == probe.MIN_VERIFICATION_HMAC_KEY_BYTES
    assert key_path.stat().st_mode & 0o777 == 0o600
    assert key_path.stat().st_nlink == 1
    with pytest.raises(
        probe.VocalLabProbeError,
        match="verification_hmac_key_create_failed",
    ):
        probe.initialize_verification_hmac_key(key_path)
    assert probe.load_verification_hmac_key(key_path) == first


def test_makefile_exposes_only_explicit_non_ci_vocallab_targets() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "probe-vocallab-provider:" in makefile
    assert "init-vocallab-verification-hmac-key:" in makefile
    assert "--initialize-verification-hmac-key" in makefile
    assert "scripts/probe_vocallab_provider.py" in makefile
    assert "materialize-vocallab-provider-verification:" in makefile
    assert "scripts/materialize_vocallab_provider_verification.py" in makefile
    assert "verify-vocallab-provider-verification:" in makefile
    assert "scripts/verify_vocallab_provider_verification.py" in makefile
    assert (
        "VOCALLAB_VERIFICATION_HMAC_KEY_FILE ?= "
        "config/vocallab_verification_hmac_key"
    ) in makefile
    assert (
        makefile.count(
            '--verification-hmac-key-file "$(VOCALLAB_VERIFICATION_HMAC_KEY_FILE)"'
        )
        == 4
    )
    assert '--voice-catalog-file "$(VOCALLAB_VOICE_CATALOG_FILE)"' in makefile
    ci_gates = makefile.split("ci-gates:\n", 1)[1].split("\n\n", 1)[0]
    assert "probe-vocallab-provider" not in ci_gates
    assert "init-vocallab-verification-hmac-key" not in ci_gates


def test_private_vocallab_artifacts_are_explicitly_git_ignored() -> None:
    required = {
        "config/vocallab_api_key",
        "config/vocallab_credential_rotation_authority.local.json",
        "config/vocallab_verification_hmac_key",
        "config/vocallab_voice_catalog.local.json",
    }
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    ignored = set(lines)

    assert required <= ignored
    assert all(lines.count(entry) == 1 for entry in required)
    assert lines.count(PRIVATE_VOCALLAB_CONFIG_PATTERN) == 1
    assert all(
        Path(path).match(PRIVATE_VOCALLAB_CONFIG_PATTERN)
        for path in PRIVATE_VOCALLAB_CONFIG_SIBLINGS
    )
    assert not {f"!{entry}" for entry in required} & ignored
    assert not any(line.startswith("!config/vocallab_") for line in lines)
    assert "state/vocallab_provider_verification/" in ignored
    assert "state/vocallab_budget_ledgers/" in ignored
    assert "state/vocallab_request_ledgers/" in ignored
    assert "data/audiobooks/vocallab_provider_verification/" in ignored
    assert "data/audiobooks/vocallab_budget_ledgers/" in ignored
    assert "data/audiobooks/vocallab_request_ledgers/" in ignored


def test_private_vocallab_inputs_are_excluded_from_docker_build_context() -> None:
    required = {
        "config/vocallab_api_key",
        "config/vocallab_credential_rotation_authority.local.json",
        "config/vocallab_verification_hmac_key",
        "config/vocallab_voice_catalog.local.json",
    }
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert required <= set(lines)
    assert all(lines.count(path) == 1 for path in required)
    assert lines.count(PRIVATE_VOCALLAB_CONFIG_PATTERN) == 1
    assert all(
        Path(path).match(PRIVATE_VOCALLAB_CONFIG_PATTERN)
        for path in PRIVATE_VOCALLAB_CONFIG_SIBLINGS
    )
    assert not {f"!{path}" for path in required} & set(lines)
    assert not any(line.startswith("!config/vocallab_") for line in lines)
