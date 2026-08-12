from __future__ import annotations

import base64
from dataclasses import replace
from datetime import timedelta
import hashlib
import io
import json
from pathlib import Path
from typing import Any
import wave

import pytest

from app.services.audiobook_tts import AudiobookProviderError
from app.services.audiobook_tts.budget_ledger import AccountBalance
from app.services.audiobook_tts.providers.vocallab import (
    VocalLabConfig,
    VocalLabProvider,
    VocalLabProviderVerification,
)
from app.services.audiobook_tts.providers.vocallab_schema import (
    VOCALLAB_BILLING_UNIT,
)
from tests.vocallab_support import (
    API_KEY,
    NOW,
    VOICE_ID,
    authorized_case,
)


def wav_bytes() -> bytes:
    target = io.BytesIO()
    with wave.open(target, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(44100)
        writer.writeframes(b"\x00\x00" * 4410)
    return target.getvalue()


class FakeResponse:
    def __init__(
        self,
        status: int,
        payload: object,
        *,
        content_type: str = "application/json",
        raw: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status
        self.raw = raw if raw is not None else json.dumps(payload).encode()
        self.headers = {"Content-Type": content_type, **(headers or {})}
        self.closed = False

    def iter_content(self, *, chunk_size: int):  # type: ignore[no-untyped-def]
        assert chunk_size == 65536
        for offset in range(0, len(self.raw), chunk_size):
            yield self.raw[offset : offset + chunk_size]

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []
        self.get_calls = 0
        self.trust_env = True

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        assert isinstance(value, FakeResponse)
        return value

    def get(self, *_args: object, **_kwargs: object) -> None:
        self.get_calls += 1
        raise AssertionError("URL fetch must remain disabled")


class TickClock:
    def __init__(self) -> None:
        self.value = NOW - timedelta(seconds=2)

    def __call__(self):  # type: ignore[no-untyped-def]
        self.value += timedelta(seconds=2)
        return self.value


def me(points: int = 10000) -> FakeResponse:
    return FakeResponse(
        200,
        {
            "is_pro": True,
            "is_studio": True,
            "points": points,
            "unit": VOCALLAB_BILLING_UNIT,
        },
    )


def ready(request, *, audio: str | None = None, points: int | None = None):  # type: ignore[no-untyped-def]
    used = points if points is not None else (len(request.source_text) + 14) // 15
    payload: dict[str, object] = {
        "id": "generation-1",
        "status": "ready",
        "model": request.model,
        "format": "WAV",
        "points_used": used,
        "audio_base64": audio
        if audio is not None
        else base64.b64encode(wav_bytes()).decode(),
    }
    return FakeResponse(200, payload)


def failed(request) -> FakeResponse:  # type: ignore[no-untyped-def]
    return FakeResponse(
        200,
        {
            "id": "generation-1",
            "status": "failed",
            "model": request.model,
            "format": "WAV",
        },
    )


def config(**changes: object) -> VocalLabConfig:
    return replace(
        VocalLabConfig(
            enabled=True,
            credential_rotation_required=False,
            credential_production_eligible=True,
            api_key=API_KEY,
            poll_interval_seconds=0.001,
            poll_timeout_seconds=2,
        ),
        **changes,
    )


class OfflinePartitionedProvider(VocalLabProvider):
    """Test-only authority for exercising post-ID state transitions offline."""

    def _require_spending_balance_partition(self) -> AccountBalance:
        return AccountBalance(monthly_points=10000, topup_points=0)


def provider(tmp_path: Path, session: FakeSession, **changes: object):  # type: ignore[no-untyped-def]
    request, catalog, store, ledger, private = authorized_case(tmp_path)
    instance = OfflinePartitionedProvider(
        config=changes.pop(
            "config",
            config(account_state_root=str(ledger.account_state_root)),
        ),
        voice_catalog=changes.pop("voice_catalog", catalog),
        budget_ledger=changes.pop("budget_ledger", ledger),
        authority_store=changes.pop("authority_store", store),
        session=session,
        now=changes.pop("now", TickClock()),
        sleeper=lambda _seconds: None,
        **changes,
    )
    return request, instance, ledger, private


def test_direct_or_blank_verification_cannot_authorize(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="authenticated_verification_loader_required"):
        VocalLabProviderVerification(status="pass")
    with pytest.raises(ValueError, match="authenticated_verification_loader_required"):
        VocalLabProvider(config=config(), verification=object())

    request, catalog, _store, ledger, _private = authorized_case(tmp_path)
    instance = VocalLabProvider(
        config=config(),
        voice_catalog=catalog,
        budget_ledger=ledger,
        session=FakeSession([]),
        now=lambda: NOW,
    )
    with pytest.raises(AudiobookProviderError) as caught:
        instance.validate_route(request)
    assert caught.value.failure.code == "provider_authority_store_missing"


def test_enabled_provider_rejects_unrotated_credential_posture() -> None:
    with pytest.raises(ValueError, match="vocallab_configuration_invalid"):
        VocalLabProvider(
            config=VocalLabConfig(enabled=True, api_key=API_KEY),
            session=FakeSession([]),
        )


def test_unapproved_rotated_credential_posture_is_valid_but_disabled() -> None:
    instance = VocalLabProvider(
        config=VocalLabConfig(
            enabled=False,
            credential_rotation_required=False,
            credential_production_eligible=False,
        ),
        session=FakeSession([]),
    )
    with pytest.raises(AudiobookProviderError) as caught:
        instance.verify_capability()
    assert caught.value.failure.code == "provider_disabled"


def test_exact_post_uses_voice_never_voice_id_and_streams_json(tmp_path: Path) -> None:
    session = FakeSession([])
    request, instance, _ledger, _private = provider(tmp_path, session)
    ready_response = ready(request)
    session.responses[:] = [ready_response]

    result = instance.synthesize(request)

    assert result.audio_bytes == wav_bytes()
    post = next(call for call in session.calls if call["method"] == "POST")
    assert post["url"] == "https://api.vocallab.ai/api/v1/tts"
    assert post["json"]["voice"] == VOICE_ID  # type: ignore[index]
    assert "voice_id" not in post["json"]  # type: ignore[operator]
    assert post["stream"] is True
    assert ready_response.closed is True


def test_public_provider_spend_is_blocked_without_verified_balance_partition(
    tmp_path: Path,
) -> None:
    request, catalog, store, ledger, _private = authorized_case(tmp_path)
    session = FakeSession([])
    instance = VocalLabProvider(
        config=config(account_state_root=str(ledger.account_state_root)),
        voice_catalog=catalog,
        budget_ledger=ledger,
        authority_store=store,
        session=session,
        now=lambda: NOW,
    )
    with pytest.raises(AudiobookProviderError) as caught:
        instance.synthesize(request)
    assert caught.value.failure.code == "provider_balance_partition_unverified"
    assert session.calls == []
    assert ledger.public_projection()["reservation_status_counts"] == {}


def test_get_only_capability_never_installs_or_claims_authority(tmp_path: Path) -> None:
    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "message": "Authenticated — your VocalLab API key is working.",
                    "ok": True,
                    "points": 1,
                    "unit": VOCALLAB_BILLING_UNIT,
                },
            ),
            me(),
            FakeResponse(
                200,
                {
                    "default": "v-pro",
                    "models": [
                        {
                            "key": "v-studio",
                            "label": "Studio",
                            "gated": True,
                            "steerable": True,
                            "costMultiplier": 1,
                        },
                        {
                            "key": "v-pro",
                            "label": "Pro",
                            "gated": False,
                            "steerable": False,
                            "costMultiplier": 1,
                        },
                        {
                            "key": "v-lite",
                            "label": "Lite",
                            "gated": False,
                            "steerable": False,
                            "costMultiplier": 0.5,
                        },
                    ],
                },
            ),
            FakeResponse(200, {"voices": []}),
        ]
    )
    request, _catalog, _store, ledger, _private = authorized_case(tmp_path)
    instance = VocalLabProvider(
        config=config(),
        budget_ledger=ledger,
        session=session,
        now=TickClock(),
        sleeper=lambda _seconds: None,
    )
    observation = instance.verify_capability()
    assert observation["status"] == "observed_not_authorized"
    assert observation["runtime_authority_installed"] is False
    assert observation["exact_balance_exposed"] is False

    with pytest.raises(AudiobookProviderError) as caught:
        instance.validate_route(request)
    assert caught.value.failure.code == "voice_catalog_missing"


def test_every_http_call_requires_and_obeys_durable_account_rate_ledger(
    tmp_path: Path,
) -> None:
    no_ledger_session = FakeSession([me()])
    no_ledger = VocalLabProvider(
        config=config(),
        session=no_ledger_session,
        now=lambda: NOW,
    )
    with pytest.raises(AudiobookProviderError) as missing:
        no_ledger._request_json("GET", "me")  # noqa: SLF001
    assert missing.value.failure.code == "budget_ledger_missing"
    assert no_ledger_session.calls == []

    _request, _catalog, _store, ledger, _private = authorized_case(tmp_path)
    session = FakeSession([me(), me()])
    instance = VocalLabProvider(
        config=config(),
        budget_ledger=ledger,
        session=session,
        now=lambda: NOW,
        sleeper=lambda _seconds: None,
    )
    instance._request_json("GET", "me")  # noqa: SLF001
    with pytest.raises(AudiobookProviderError) as limited:
        instance._request_json("GET", "me")  # noqa: SLF001
    assert limited.value.failure.code == "provider_local_rate_limited"
    assert limited.value.failure.retryable is True
    assert len(session.calls) == 1


def test_three_upstream_failures_open_durable_new_work_circuit(
    tmp_path: Path,
) -> None:
    session = FakeSession([FakeResponse(503, {}) for _ in range(3)])
    request, instance, ledger, _private = provider(tmp_path, session)
    for _ in range(3):
        with pytest.raises(AudiobookProviderError) as unavailable:
            instance._request_json("GET", "ping")  # noqa: SLF001
        assert unavailable.value.failure.code == "upstream_unavailable"
    projection = ledger.public_projection()
    assert projection["circuit_breaker_status"] == "open"
    assert projection["consecutive_upstream_failures"] == 3
    with pytest.raises(AudiobookProviderError) as blocked:
        instance.synthesize(request)
    assert blocked.value.failure.code == "budget_circuit_breaker_open"
    assert sum(call["method"] == "POST" for call in session.calls) == 0


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("speed", True, "speed_invalid"),
        ("speed", float("nan"), "speed_invalid"),
        ("speed", 0.51, "speed_invalid"),
        ("temperature", False, "temperature_invalid"),
        ("temperature", float("inf"), "temperature_invalid"),
        ("temperature", 1.51, "temperature_invalid"),
        ("output_format", "mp3", "format_invalid"),
        ("sample_rate", 48000, "sample_rate_invalid"),
    ],
)
def test_numeric_and_output_contracts_are_strict(
    tmp_path: Path, field: str, value: object, code: str
) -> None:
    request, instance, _ledger, _private = provider(tmp_path, FakeSession([]))
    with pytest.raises(AudiobookProviderError) as caught:
        instance.validate_route(replace(request, **{field: value}))
    assert caught.value.failure.code == code


@pytest.mark.parametrize(
    "changes",
    [
        {"enabled": 1},
        {"base_url": "https://api.vocallab.ai/api/v1"},
        {"base_url": "http://api.vocallab.ai"},
        {"requests_per_minute": 31},
        {"requests_per_minute": True},
        {"max_in_flight": 2},
        {"output_format": "mp3"},
        {"allowed_download_hosts": ("api.vocallab.ai",)},
        {"allowed_voice_classes": ("community",)},
        {"allowed_voice_classes": ("consented_clone", "professional")},
        {"allow_clones": True},
        {"account_state_root": "relative/provider-state"},
    ],
)
def test_configuration_contract_is_exact_and_type_strict(
    changes: dict[str, object]
) -> None:
    with pytest.raises(ValueError, match="vocallab_configuration_invalid"):
        VocalLabProvider(config=replace(config(), **changes))


def test_declared_safe_voice_class_default_instantiates_with_clones_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "EA_AUDIOBOOK_VOCALLAB_ALLOWED_VOICE_CLASSES",
        "professional,consented_clone",
    )

    runtime_config = VocalLabConfig.from_environment()
    instance = VocalLabProvider(
        config=runtime_config,
        session=FakeSession([]),
    )

    assert instance.config.allowed_voice_classes == (
        "professional",
        "consented_clone",
    )
    assert instance.config.allow_clones is False


def test_provider_contract_cast_and_external_digests_are_mandatory(tmp_path: Path) -> None:
    request, instance, _ledger, _private = provider(tmp_path, FakeSession([]))
    for changed, code in (
        (replace(request, provider_contract_version=""), "provider_contract_version_missing"),
        (replace(request, cast_snapshot_sha256=""), "route_authority_digest_invalid"),
        (
            replace(request, external_processing_authorization_sha256=""),
            "external_authorization_digest_invalid",
        ),
    ):
        with pytest.raises(AudiobookProviderError) as caught:
            instance.validate_route(changed)
        assert caught.value.failure.code == code


def test_runtime_voice_label_and_canonical_coordinator_are_exactly_bound(
    tmp_path: Path,
) -> None:
    request, instance, ledger, _private = provider(tmp_path, FakeSession([]))
    mismatched_label = replace(
        request,
        voice=replace(request.voice, safe_label="PRIVATE RAW CALLER LABEL"),
    )
    with pytest.raises(AudiobookProviderError) as label:
        instance.validate_route(mismatched_label)
    assert label.value.failure.code == "voice_safe_label_mismatch"

    alternate_root = replace(
        instance.config,
        account_state_root=str(ledger.account_state_root.parent / "alternate"),
    )
    with pytest.raises(AudiobookProviderError) as root:
        OfflinePartitionedProvider(
            config=alternate_root,
            voice_catalog=instance._voice_catalog,  # noqa: SLF001
            budget_ledger=ledger,
            authority_store=instance._authorities,  # noqa: SLF001
            session=FakeSession([]),
            now=lambda: NOW,
        ).validate_route(request)
    assert root.value.failure.code == "budget_coordinator_scope_mismatch"

    alternate_credential = replace(
        instance.config,
        api_key="vl_" + "live_" + "b" * 24,
    )
    with pytest.raises(AudiobookProviderError) as credential:
        OfflinePartitionedProvider(
            config=alternate_credential,
            voice_catalog=instance._voice_catalog,  # noqa: SLF001
            budget_ledger=ledger,
            authority_store=instance._authorities,  # noqa: SLF001
            session=FakeSession([]),
            now=lambda: NOW,
        ).validate_route(request)
    assert credential.value.failure.code == "budget_coordinator_scope_mismatch"


def test_studio_only_controlled_direction_and_bracketed_source_block(tmp_path: Path) -> None:
    request, instance, _ledger, _private = provider(tmp_path, FakeSession([]))
    with pytest.raises(AudiobookProviderError) as wrong_model:
        instance._provider_text(replace(request, performance_direction="warm"))  # noqa: SLF001
    assert wrong_model.value.failure.code == "performance_direction_model_mismatch"
    with pytest.raises(AudiobookProviderError) as arbitrary:
        instance._provider_text(
            replace(request, model="v-studio", performance_direction="[raw]")
        )  # noqa: SLF001
    assert arbitrary.value.failure.code == "performance_direction_not_allowed"
    with pytest.raises(AudiobookProviderError) as bracket:
        instance._provider_text(
            replace(
                request,
                model="v-studio",
                performance_direction="warm",
                source_text="Text [whisper]",
            )
        )  # noqa: SLF001
    assert bracket.value.failure.code == "studio_source_control_tokens_blocked"


@pytest.mark.parametrize(
    ("status", "code", "charge", "retryable"),
    [
        (401, "authentication_failed", "unknown", False),
        (402, "balance_exhausted", "unknown", False),
        (403, "plan_or_api_access_denied", "unknown", False),
        (413, "input_too_long", "unknown", False),
        (429, "rate_limited", "unknown", False),
        (503, "upstream_unavailable", "unknown", False),
    ],
)
def test_post_error_mapping_is_sanitized_and_charge_aware(
    tmp_path: Path, status: int, code: str, charge: str, retryable: bool
) -> None:
    session = FakeSession([])
    request, instance, _ledger, _private = provider(tmp_path, session)
    session.responses[:] = [FakeResponse(status, {"error": "PRIVATE TEXT KEY URL"})]
    with pytest.raises(AudiobookProviderError) as caught:
        instance.synthesize(request)
    assert caught.value.failure.code == code
    assert caught.value.failure.charge_state == charge
    assert caught.value.failure.retryable is retryable
    assert "PRIVATE" not in f"{caught.value!s} {caught.value!r}"


def test_unknown_post_result_blocks_retry_and_duplicate_fingerprint(tmp_path: Path) -> None:
    session = FakeSession([])
    request, instance, ledger, _private = provider(tmp_path, session)
    session.responses[:] = [RuntimeError("PRIVATE transport")]
    with pytest.raises(AudiobookProviderError):
        instance.synthesize(request)
    with pytest.raises(AudiobookProviderError) as retry:
        instance.synthesize(request)
    assert retry.value.failure.code == "budget_request_charge_unknown"
    assert sum(call["method"] == "POST" for call in session.calls) == 1

    different = replace(request, idempotency_key="different-key")
    with pytest.raises(AudiobookProviderError) as duplicate:
        instance.synthesize(different)
    assert duplicate.value.failure.code == "duplicate_synthesis_fingerprint"
    assert ledger.public_projection()["reservation_status_counts"] == {"unknown": 1}


def test_pending_generation_polls_by_id_without_repost(tmp_path: Path) -> None:
    session = FakeSession([])
    request, instance, _ledger, _private = provider(tmp_path, session)
    pending = FakeResponse(
        200,
        {
            "id": "generation-1",
            "status": "pending",
            "model": "v-pro",
            "format": "WAV",
        },
    )
    session.responses[:] = [pending, ready(request)]
    assert instance.synthesize(request).provider_generation_id_private == "generation-1"
    assert [call["method"] for call in session.calls] == ["POST", "GET"]


def test_generation_id_then_get_429_resumes_get_without_second_post(
    tmp_path: Path,
) -> None:
    session = FakeSession([])
    request, instance, ledger, _private = provider(tmp_path, session)
    pending = FakeResponse(
        200,
        {
            "id": "generation-1",
            "status": "pending",
            "model": request.model,
            "format": "WAV",
        },
    )
    session.responses[:] = [pending, FakeResponse(429, {"error": "private"})]
    with pytest.raises(AudiobookProviderError) as first:
        instance.synthesize(request)
    assert first.value.failure.code == "rate_limited"
    assert first.value.failure.charge_state == "unknown"
    assert ledger.public_projection()["reservation_status_counts"] == {
        "generation_known": 1
    }

    session.responses[:] = [ready(request)]
    assert instance.synthesize(request).provider_generation_id_private == "generation-1"
    assert sum(call["method"] == "POST" for call in session.calls) == 1


def test_pending_inline_audio_materializes_without_poll(tmp_path: Path) -> None:
    session = FakeSession([])
    request, instance, _ledger, _private = provider(tmp_path, session)
    points = (len(request.source_text) + 14) // 15
    session.responses[:] = [
        FakeResponse(
            200,
            {
                "id": "generation-1",
                "status": "pending",
                "model": request.model,
                "format": "WAV",
                "points_used": points,
                "audio_base64": base64.b64encode(wav_bytes()).decode(),
                "audio_url": None,
            },
        )
    ]
    assert instance.synthesize(request).points_used == points
    assert [call["method"] for call in session.calls] == ["POST"]


def test_generation_failure_after_id_remains_resumable_without_repost(
    tmp_path: Path,
) -> None:
    session = FakeSession([])
    request, instance, ledger, _private = provider(tmp_path, session)
    session.responses[:] = [
        FakeResponse(
            200,
            {
                "id": "generation-1",
                "status": "pending",
                "model": request.model,
                "format": "WAV",
            },
        ),
        failed(request),
    ]
    with pytest.raises(AudiobookProviderError) as caught:
        instance.synthesize(request)
    assert caught.value.failure.code == "generation_failed"
    assert caught.value.failure.charge_state == "unknown"
    assert ledger.public_projection()["reservation_status_counts"] == {
        "generation_known": 1
    }
    session.responses[:] = [ready(request)]
    assert instance.synthesize(request).provider_generation_id_private == "generation-1"
    assert sum(call["method"] == "POST" for call in session.calls) == 1


def test_charged_pending_failure_never_regresses_charge_state(tmp_path: Path) -> None:
    session = FakeSession([])
    request, instance, ledger, _private = provider(tmp_path, session)
    session.responses[:] = [ready(request, audio="not-base64")]
    with pytest.raises(AudiobookProviderError):
        instance.synthesize(request)
    session.responses[:] = [failed(request)]
    with pytest.raises(AudiobookProviderError) as caught:
        instance.synthesize(request)
    assert caught.value.failure.code == "generation_failed"
    assert caught.value.failure.charge_state == "charged"
    assert ledger.public_projection()["reservation_status_counts"] == {
        "charged_pending_materialization": 1
    }


def test_charged_invalid_audio_resumes_get_and_never_reposts(tmp_path: Path) -> None:
    session = FakeSession([])
    request, instance, ledger, _private = provider(tmp_path, session)
    session.responses[:] = [ready(request, audio="not-base64")]
    with pytest.raises(AudiobookProviderError) as invalid:
        instance.synthesize(request)
    assert invalid.value.failure.charge_state == "charged"
    assert ledger.public_projection()["reservation_status_counts"] == {
        "charged_pending_materialization": 1
    }

    session.responses[:] = [ready(request)]
    result = instance.synthesize(request)
    assert result.audio_sha256 == hashlib.sha256(wav_bytes()).hexdigest()
    assert sum(call["method"] == "POST" for call in session.calls) == 1
    assert ledger.public_projection()["reservation_status_counts"] == {"complete": 1}


def test_url_only_output_is_charged_pending_and_never_fetched(tmp_path: Path) -> None:
    session = FakeSession([])
    request, instance, ledger, _private = provider(tmp_path, session)
    payload = {
        "id": "generation-1",
        "status": "ready",
        "model": "v-pro",
        "format": "WAV",
        "points_used": (len(request.source_text) + 14) // 15,
        "audio_url": "https://provider.invalid/private.wav",
    }
    session.responses[:] = [FakeResponse(200, payload)]
    with pytest.raises(AudiobookProviderError) as caught:
        instance.synthesize(request)
    assert caught.value.failure.code == "audio_url_fallback_disabled"
    assert session.get_calls == 0
    assert ledger.public_projection()["reservation_status_counts"] == {
        "charged_pending_materialization": 1
    }


def test_generation_id_is_immutable_across_poll(tmp_path: Path) -> None:
    session = FakeSession([])
    request, instance, _ledger, _private = provider(tmp_path, session)
    session.responses[:] = [
        FakeResponse(
            200,
            {"id": "generation-1", "status": "pending", "model": "v-pro", "format": "WAV"},
        ),
            FakeResponse(
                200,
                {
                    "id": "generation-2",
                    "status": "ready",
                    "model": "v-pro",
                    "format": "WAV",
                    "points_used": 3,
                    "audio_base64": base64.b64encode(wav_bytes()).decode(),
                },
            ),
    ]
    with pytest.raises(AudiobookProviderError) as caught:
        instance.synthesize(request)
    assert caught.value.failure.code == "provider_generation_id_changed"
    assert sum(call["method"] == "POST" for call in session.calls) == 1


def test_budget_overrun_is_charged_and_opens_circuit(tmp_path: Path) -> None:
    session = FakeSession([])
    request, instance, ledger, _private = provider(tmp_path, session)
    estimate = (len(request.source_text) + 14) // 15
    session.responses[:] = [ready(request, points=estimate + 1)]
    with pytest.raises(AudiobookProviderError) as caught:
        instance.synthesize(request)
    assert caught.value.failure.code == "provider_points_exceeded_reservation"
    projection = ledger.public_projection()
    assert projection["circuit_breaker_status"] == "open"
    assert projection["reservation_status_counts"] == {
        "complete_budget_violation": 1
    }


def test_streamed_json_is_bounded_exact_content_type_and_always_closed(tmp_path: Path) -> None:
    request, instance, _ledger, _private = provider(tmp_path, FakeSession([]))
    for response in (
        FakeResponse(200, {}, content_type="text/html"),
        FakeResponse(200, {}, raw=b"{" + b"x" * (2 * 1024 * 1024 + 1)),
        FakeResponse(200, {}, raw=b"not-json"),
        FakeResponse(200, {}, raw=b'{"value":1,"value":2}'),
        FakeResponse(200, {}, raw=b'{"value":NaN}'),
    ):
        instance._session.responses[:] = [response]  # noqa: SLF001
        with pytest.raises(AudiobookProviderError) as caught:
            instance._request_json("GET", "me")  # noqa: SLF001
        assert caught.value.failure.code == "invalid_provider_response"
        assert response.closed is True
    assert request.provider_contract_version


def test_key_file_env_resolution_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = "vl_" + "live_" + "z" * 24
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EA_AUDIOBOOK_VOCALLAB_ENABLED", "1")
    monkeypatch.setenv("VOCALLAB_API_KEY", key)
    monkeypatch.setenv("VOCALLAB_API_KEY_FILE", "config/vocallab_api_key")
    assert VocalLabConfig.from_environment().api_key == key

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    key_path = config_dir / "vocallab_api_key"
    key_path.write_text("different")
    key_path.chmod(0o600)
    with pytest.raises(ValueError, match="vocallab_key_sources_disagree"):
        VocalLabConfig.from_environment()


def test_disabled_default_configuration_does_not_require_or_read_key_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EA_AUDIOBOOK_VOCALLAB_ENABLED", "0")
    monkeypatch.delenv("VOCALLAB_API_KEY", raising=False)
    monkeypatch.setenv("VOCALLAB_API_KEY_FILE", "config/vocallab_api_key")
    loaded = VocalLabConfig.from_environment()
    assert loaded.enabled is False
    assert loaded.api_key == ""


def test_key_file_rejects_mode_symlink_hardlink_and_symlinked_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = "vl_" + "live_" + "k" * 24
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EA_AUDIOBOOK_VOCALLAB_ENABLED", "1")
    monkeypatch.delenv("VOCALLAB_API_KEY", raising=False)
    monkeypatch.setenv("VOCALLAB_API_KEY_FILE", "config/vocallab_api_key")
    config_dir = tmp_path / "config"
    config_dir.mkdir(mode=0o700)
    key_path = config_dir / "vocallab_api_key"
    key_path.write_text(key)
    key_path.chmod(0o600)
    assert VocalLabConfig.from_environment().api_key == key

    key_path.chmod(0o644)
    with pytest.raises(ValueError, match="vocallab_key_file_unsafe"):
        VocalLabConfig.from_environment()
    key_path.chmod(0o600)

    hardlink = config_dir / "other-key"
    hardlink.hardlink_to(key_path)
    with pytest.raises(ValueError, match="vocallab_key_file_unsafe"):
        VocalLabConfig.from_environment()
    hardlink.unlink()

    key_path.unlink()
    target = tmp_path / "target-key"
    target.write_text(key)
    target.chmod(0o600)
    key_path.symlink_to(target)
    with pytest.raises(ValueError, match="vocallab_key_file_unsafe"):
        VocalLabConfig.from_environment()

    symlink_root = tmp_path / "symlink-root"
    symlink_root.mkdir(mode=0o700)
    real_config = symlink_root / "real-config"
    real_config.mkdir(mode=0o700)
    real_key = real_config / "vocallab_api_key"
    real_key.write_text(key)
    real_key.chmod(0o600)
    (symlink_root / "config").symlink_to(real_config, target_is_directory=True)
    monkeypatch.chdir(symlink_root)
    with pytest.raises(ValueError, match="vocallab_key_file_unsafe"):
        VocalLabConfig.from_environment()


def test_audition_has_explicit_authority_but_no_publication_authority(tmp_path: Path) -> None:
    request, catalog, store, ledger, _private = authorized_case(
        tmp_path, workload="voice_audition"
    )
    instance = VocalLabProvider(
        config=config(account_state_root=str(ledger.account_state_root)),
        voice_catalog=catalog,
        authority_store=store,
        budget_ledger=ledger,
        session=FakeSession([]),
        now=lambda: NOW,
    )
    instance.validate_route(request)
    with pytest.raises(AudiobookProviderError) as caught:
        instance.validate_route(replace(request, publication_intent=True))
    assert caught.value.failure.code == "audition_authorization_missing"
