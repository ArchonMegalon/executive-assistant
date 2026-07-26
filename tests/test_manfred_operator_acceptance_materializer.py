from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
from types import ModuleType

import pytest

from app.services.manfred_voice_signing import (
    MANFRED_PHASE_1_LIVE_REVIEW_SURFACE,
    MANFRED_TTS_MODEL,
    MANFRED_TTS_PROVIDER,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "scripts"
    / "materialize_manfred_spoken_conversation_operator_acceptance.py"
)
SOURCE_REVISION = "a" * 40
PUBLIC_ORIGIN = "https://myexternalbrain.com"
IMAGE_ID = f"sha256:{'b' * 64}"
VOICE_CONFIG_SHA256 = "c" * 64
VOICE_MANIFEST_SHA256 = "d" * 64
VOICE_REFERENCE_AGGREGATE_SHA256 = "e" * 64
PROVIDER_VOICE_ID_SHA256 = "f" * 64
REVIEWER_REF_SHA256 = "1" * 64
NOW = datetime(2026, 7, 23, 11, 30, tzinfo=UTC)


@pytest.fixture
def module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "materialize_manfred_spoken_conversation_operator_acceptance",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def _checks(module: ModuleType) -> dict[str, bool]:
    return {
        check_id: True
        for check_id in module.ROOM_AND_SPOKEN_TURN_CHECK_IDS
    }


def _kwargs(
    module: ModuleType,
    tmp_path: Path,
    **overrides: object,
) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "output_path": tmp_path / "operator-acceptance.json",
        "reviewer_ref_sha256": REVIEWER_REF_SHA256,
        "source_revision": SOURCE_REVISION,
        "public_origin": PUBLIC_ORIGIN,
        "image_id": IMAGE_ID,
        "voice_config_sha256": VOICE_CONFIG_SHA256,
        "voice_manifest_sha256": VOICE_MANIFEST_SHA256,
        "voice_reference_aggregate_sha256": (
            VOICE_REFERENCE_AGGREGATE_SHA256
        ),
        "provider_voice_id_sha256": PROVIDER_VOICE_ID_SHA256,
        "tts_provider": MANFRED_TTS_PROVIDER,
        "tts_model": MANFRED_TTS_MODEL,
        "checks": _checks(module),
        "confirmation": module.OPERATOR_ACCEPTANCE_CONFIRMATION,
        "now": NOW,
    }
    kwargs.update(overrides)
    return kwargs


def test_materializes_exact_private_source_image_origin_and_voice_bound_receipt(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    output = tmp_path / "operator-acceptance.json"

    receipt = (
        module.materialize_manfred_spoken_conversation_operator_acceptance(
            **_kwargs(module, tmp_path)
        )
    )

    assert output.exists()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.stat().st_nlink == 1
    assert json.loads(output.read_text(encoding="utf-8")) == receipt
    assert receipt["contract_name"] == (
        "ea.manfred_spoken_conversation_operator_acceptance.v2"
    )
    assert receipt["accepted"] is True
    assert receipt["spoken_turn_claim_accepted"] is True
    assert receipt["native_realtime_claim_accepted"] is False
    assert receipt["reviewer_ref_sha256"] == REVIEWER_REF_SHA256
    assert receipt["reviewer_ref_sha256_semantics"] == (
        "sha256_utf8_pseudonymous_operator_reference_v1"
    )
    assert receipt["deployed_source_revision"] == SOURCE_REVISION
    assert receipt["public_origin"] == PUBLIC_ORIGIN
    assert receipt["review_surface"] == MANFRED_PHASE_1_LIVE_REVIEW_SURFACE
    assert receipt["image_id"] == IMAGE_ID
    assert receipt["checks"] == _checks(module)
    assert set(receipt["checks"]) == set(
        module.ROOM_AND_SPOKEN_TURN_CHECK_IDS
    )


@pytest.mark.parametrize(
    "failed_check",
    (
        "actual_device_checked",
        "actual_speaker_checked",
        "first_syllable_not_clipped",
        "intelligibility_confirmed",
        "answer_text_fallback_visible",
        "no_internet_search_confirmed",
        "normal_spoken_turn_confirmed",
        "interruption_behavior_confirmed",
        "retry_path_confirmed",
        "likeness_accepted",
        "warmth_accepted",
        "pronunciation_accepted",
    ),
)
def test_each_named_human_confirmation_is_individually_required(
    module: ModuleType,
    tmp_path: Path,
    failed_check: str,
) -> None:
    checks = _checks(module)
    checks[failed_check] = False

    with pytest.raises(
        module.VoiceReleaseError,
        match=f"operator_acceptance_check_failed:{failed_check}",
    ):
        module.materialize_manfred_spoken_conversation_operator_acceptance(
            **_kwargs(module, tmp_path, checks=checks)
        )
    assert not (tmp_path / "operator-acceptance.json").exists()


@pytest.mark.parametrize(
    ("overrides", "reason"),
    (
        (
            {"reviewer_ref_sha256": "not-a-digest"},
            "operator_acceptance_reviewer_ref_invalid",
        ),
        (
            {"source_revision": "A" * 40},
            "operator_acceptance_source_revision_invalid",
        ),
        (
            {"public_origin": f"{PUBLIC_ORIGIN}/"},
            "operator_acceptance_public_origin_invalid",
        ),
        (
            {"image_id": "b" * 64},
            "operator_acceptance_image_id_invalid",
        ),
        (
            {"voice_manifest_sha256": "not-a-digest"},
            "voice_identity_digest_invalid",
        ),
        (
            {"tts_provider": "other-provider"},
            "operator_acceptance_tts_identity_invalid",
        ),
        (
            {"confirmation": "yes"},
            "operator_acceptance_confirmation_missing",
        ),
    ),
)
def test_materializer_rejects_unbound_or_implicit_acceptance(
    module: ModuleType,
    tmp_path: Path,
    overrides: dict[str, object],
    reason: str,
) -> None:
    with pytest.raises(module.VoiceReleaseError, match=reason):
        module.materialize_manfred_spoken_conversation_operator_acceptance(
            **_kwargs(module, tmp_path, **overrides)
        )
    assert not (tmp_path / "operator-acceptance.json").exists()


def test_existing_non_private_or_multiply_linked_output_is_rejected(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    output = tmp_path / "operator-acceptance.json"
    output.write_text("{}\n", encoding="utf-8")
    output.chmod(0o640)
    with pytest.raises(
        module.VoiceReleaseError,
        match="release_output_path_unsafe",
    ):
        module.materialize_manfred_spoken_conversation_operator_acceptance(
            **_kwargs(module, tmp_path)
        )

    output.chmod(0o600)
    alias = tmp_path / "operator-acceptance-alias.json"
    os.link(output, alias)
    with pytest.raises(
        module.VoiceReleaseError,
        match="release_output_path_unsafe",
    ):
        module.materialize_manfred_spoken_conversation_operator_acceptance(
            **_kwargs(module, tmp_path)
        )


def test_cli_requires_every_named_confirmation(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    with pytest.raises(SystemExit) as exc:
        module.main(
            [
                "--output",
                str(tmp_path / "operator-acceptance.json"),
                "--reviewer-ref-sha256",
                REVIEWER_REF_SHA256,
                "--source-revision",
                SOURCE_REVISION,
                "--public-origin",
                PUBLIC_ORIGIN,
                "--image-id",
                IMAGE_ID,
                "--voice-config-sha256",
                VOICE_CONFIG_SHA256,
                "--voice-manifest-sha256",
                VOICE_MANIFEST_SHA256,
                "--voice-reference-aggregate-sha256",
                VOICE_REFERENCE_AGGREGATE_SHA256,
                "--provider-voice-id-sha256",
                PROVIDER_VOICE_ID_SHA256,
                "--tts-provider",
                MANFRED_TTS_PROVIDER,
                "--tts-model",
                MANFRED_TTS_MODEL,
                "--confirmation",
                module.OPERATOR_ACCEPTANCE_CONFIRMATION,
            ]
        )
    assert exc.value.code == 2
    assert not (tmp_path / "operator-acceptance.json").exists()
