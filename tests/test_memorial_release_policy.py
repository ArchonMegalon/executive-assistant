from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest
from fastapi import HTTPException

from app.api.routes import public_memorials
from app.services.manfred_voice_signing import (
    IMAGE_ID_SEMANTICS,
    MANFRED_PHASE_1_LIVE_REVIEW_SURFACE,
    MANFRED_TTS_MODEL,
    MANFRED_TTS_PROVIDER,
    MANFRED_VOICE_TRUSTED_PUBLIC_KEYS_B64,
    PROVIDER_VOICE_ID_SHA256_SEMANTICS,
    SIGNATURE_ALGORITHM,
    SIGNATURE_SCOPE,
    VOICE_ARTIFACT_DIGEST_SEMANTICS,
    VOICE_IDENTITY_SHA256_SEMANTICS,
    VOICE_REFERENCE_AGGREGATE_SHA256_SEMANTICS,
    sign_receipt,
    trusted_public_keys,
    voice_identity_sha256,
)
from app.services.memorial_release_policy import (
    evaluate_memorial_voice_release,
    evaluate_memorial_voice_release_payload,
)
from scripts import prepare_manfred_memorial_candidate as candidate_prep


ROOT = Path(__file__).resolve().parents[1]
SOURCE_REVISION = "a" * 40
PUBLIC_ORIGIN = "https://myexternalbrain.com"
IMAGE_ID = f"sha256:{'b' * 64}"
VOICE_CONFIG_SHA256 = "c" * 64
VOICE_MANIFEST_SHA256 = "d" * 64
VOICE_REFERENCE_AGGREGATE_SHA256 = "e" * 64
PROVIDER_VOICE_ID_SHA256 = "f" * 64
NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc).timestamp()
ROTATED_RELEASE_KEY_ID = (
    "sha256:9457961ff2e19c65d4de45e2163bb4cfd2bbd15c92ed772460d54194f895e8e5"
)


@pytest.fixture
def signing_material(
    tmp_path: Path,
) -> tuple[Ed25519PrivateKey, Path, Path]:
    private_key = Ed25519PrivateKey.generate()
    private_path = tmp_path / "signing-private.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    private_path.chmod(0o600)
    public_path = tmp_path / "signing-public.pem"
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    public_path.chmod(0o600)
    return private_key, private_path, public_path


def test_rotated_voice_release_public_key_is_in_the_embedded_trust_set() -> None:
    assert ROTATED_RELEASE_KEY_ID in MANFRED_VOICE_TRUSTED_PUBLIC_KEYS_B64
    assert ROTATED_RELEASE_KEY_ID in trusted_public_keys()


def _voice_fields() -> dict[str, object]:
    identity = voice_identity_sha256(
        voice_config_sha256=VOICE_CONFIG_SHA256,
        voice_manifest_sha256=VOICE_MANIFEST_SHA256,
        voice_reference_aggregate_sha256=VOICE_REFERENCE_AGGREGATE_SHA256,
        provider_voice_id_sha256=PROVIDER_VOICE_ID_SHA256,
        tts_provider=MANFRED_TTS_PROVIDER,
        tts_model=MANFRED_TTS_MODEL,
    )
    return {
        "provider_voice_id_sha256": PROVIDER_VOICE_ID_SHA256,
        "provider_voice_id_sha256_semantics": (
            PROVIDER_VOICE_ID_SHA256_SEMANTICS
        ),
        "tts_model": MANFRED_TTS_MODEL,
        "tts_provider": MANFRED_TTS_PROVIDER,
        "voice_artifact_digest_semantics": VOICE_ARTIFACT_DIGEST_SEMANTICS,
        "voice_config_sha256": VOICE_CONFIG_SHA256,
        "voice_identity_sha256": identity,
        "voice_identity_sha256_semantics": VOICE_IDENTITY_SHA256_SEMANTICS,
        "voice_manifest_sha256": VOICE_MANIFEST_SHA256,
        "voice_reference_aggregate_sha256": VOICE_REFERENCE_AGGREGATE_SHA256,
        "voice_reference_aggregate_sha256_semantics": (
            VOICE_REFERENCE_AGGREGATE_SHA256_SEMANTICS
        ),
    }


def _release_payload(
    private_key: Ed25519PrivateKey,
    *,
    generated_at: str = "2025-01-01T00:00:00Z",
    overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    unsigned: dict[str, object] = {
        "blocked_checks": [],
        "contract_name": "ea.manfred_voice_release.v2",
        "conversational_use_authorized": True,
        "deployed_source_sha256": hashlib.sha256(
            SOURCE_REVISION.encode("ascii")
        ).hexdigest(),
        "deployed_source_sha256_semantics": "sha256_ascii_source_revision",
        "generated_at": generated_at,
        "generated_by": "scripts/materialize_manfred_voice_release.py",
        "head_semantics": "source_state",
        "image_id": IMAGE_ID,
        "image_id_semantics": IMAGE_ID_SEMANTICS,
        "input_digest_semantics": "sha256_exact_input_bytes",
        "memorial_slug": "manfred",
        "native_realtime_claim_allowed": False,
        "operator_acceptance_receipt_sha256": "1" * 64,
        "operator_acceptance_review_surface": (
            MANFRED_PHASE_1_LIVE_REVIEW_SURFACE
        ),
        "operator_acceptance_verified": True,
        "premium_spoken_claim_allowed": True,
        "public_origin": PUBLIC_ORIGIN,
        "public_synthetic_voice_authorized": True,
        "readiness_receipt_sha256": "0" * 64,
        "readiness_status": "ready_for_spoken_turn_release",
        "readiness_verified": True,
        "room_and_spoken_turn_checks_verified": True,
        "runtime_enablement_allowed": True,
        "source_git_head": SOURCE_REVISION,
        "source_material_authorized": True,
        "source_revision": SOURCE_REVISION,
        "source_state_fingerprint": "4" * 64,
        "source_state_fingerprint_semantics": (
            "worktree_source_files_sha256_excluding_generated_only_paths"
        ),
        "spoken_turn_claim_allowed": True,
        "status": "released",
        "voice_authority_receipt_sha256": "2" * 64,
        "voice_authority_revoked": False,
        "voice_authority_verified": True,
        **_voice_fields(),
    }
    if overrides:
        unsigned.update(overrides)
    return sign_receipt(unsigned, private_key=private_key)


def _expected(public_path: Path) -> dict[str, object]:
    return {
        "expected_source_revision": SOURCE_REVISION,
        "expected_public_origin": PUBLIC_ORIGIN,
        "expected_image_id": IMAGE_ID,
        "expected_voice_config_sha256": VOICE_CONFIG_SHA256,
        "expected_voice_manifest_sha256": VOICE_MANIFEST_SHA256,
        "expected_voice_reference_aggregate_sha256": (
            VOICE_REFERENCE_AGGREGATE_SHA256
        ),
        "expected_provider_voice_id_sha256": PROVIDER_VOICE_ID_SHA256,
        "expected_tts_provider": MANFRED_TTS_PROVIDER,
        "expected_tts_model": MANFRED_TTS_MODEL,
        "trusted_public_key_path": public_path,
        "now": NOW,
    }


def _write_private_receipt(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, allow_nan=False, sort_keys=True),
        encoding="utf-8",
    )
    path.chmod(0o600)


def test_signed_release_is_durable_and_exactly_bound(
    tmp_path: Path,
    signing_material: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    private_key, _private_path, public_path = signing_material
    path = tmp_path / "release.json"
    _write_private_receipt(path, _release_payload(private_key))

    decision = evaluate_memorial_voice_release(
        slug="manfred",
        receipt_path=path,
        **_expected(public_path),
    )

    assert decision == {
        "allowed": True,
        "status": "released",
        "reason": "",
        "receipt_status": "released",
    }
    # The final receipt intentionally remains valid beyond 24 hours. Deleting
    # or replacing this file is the immediate fail-closed revocation action.
    assert datetime.fromtimestamp(NOW, timezone.utc).year == 2026


def test_missing_final_receipt_is_fail_closed_not_an_exception(
    tmp_path: Path,
    signing_material: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    _private_key, _private_path, public_path = signing_material

    decision = evaluate_memorial_voice_release(
        slug="manfred",
        receipt_path=tmp_path / "missing.json",
        **_expected(public_path),
    )

    assert decision["allowed"] is False
    assert decision["reason"] == "release_receipt_missing"


def test_signature_tampering_and_untrusted_signer_fail_closed(
    tmp_path: Path,
    signing_material: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    private_key, _private_path, public_path = signing_material
    payload = _release_payload(private_key)
    payload["runtime_enablement_allowed"] = False
    tampered = evaluate_memorial_voice_release_payload(
        slug="manfred",
        payload=payload,
        **_expected(public_path),
    )
    assert tampered["reason"] == "release_receipt_signature_invalid"

    other_key = Ed25519PrivateKey.generate()
    untrusted = evaluate_memorial_voice_release_payload(
        slug="manfred",
        payload=_release_payload(other_key),
        **_expected(public_path),
    )
    assert untrusted["reason"] == "release_receipt_signature_invalid"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"runtime_enablement_allowed": 1}, "release_human_acceptance_missing"),
        ({"voice_authority_verified": False}, "release_human_acceptance_missing"),
        (
            {"operator_acceptance_review_surface": "candidate"},
            "release_human_acceptance_missing",
        ),
        (
            {"native_realtime_claim_allowed": True},
            "release_human_acceptance_missing",
        ),
        (
            {"blocked_checks": {"not": "a list"}},
            "release_prerequisites_blocked",
        ),
        (
            {"operator_acceptance_receipt_sha256": ""},
            "release_digest_binding_missing",
        ),
    ],
)
def test_signed_but_false_or_wrongly_typed_claims_are_rejected(
    signing_material: tuple[Ed25519PrivateKey, Path, Path],
    overrides: dict[str, object],
    reason: str,
) -> None:
    private_key, _private_path, public_path = signing_material
    decision = evaluate_memorial_voice_release_payload(
        slug="manfred",
        payload=_release_payload(private_key, overrides=overrides),
        **_expected(public_path),
    )
    assert decision["reason"] == reason


@pytest.mark.parametrize(
    ("binding", "reason"),
    [
        ("expected_source_revision", "release_runtime_revision_missing"),
        ("expected_public_origin", "release_runtime_public_origin_missing"),
        ("expected_image_id", "release_runtime_image_id_missing"),
        (
            "expected_voice_config_sha256",
            "release_runtime_voice_identity_missing",
        ),
        (
            "expected_voice_manifest_sha256",
            "release_runtime_voice_identity_missing",
        ),
        (
            "expected_voice_reference_aggregate_sha256",
            "release_runtime_voice_identity_missing",
        ),
        (
            "expected_provider_voice_id_sha256",
            "release_runtime_voice_identity_missing",
        ),
        ("expected_tts_provider", "release_runtime_voice_identity_missing"),
        ("expected_tts_model", "release_runtime_voice_identity_missing"),
    ],
)
def test_every_runtime_binding_is_mandatory(
    signing_material: tuple[Ed25519PrivateKey, Path, Path],
    binding: str,
    reason: str,
) -> None:
    private_key, _private_path, public_path = signing_material
    kwargs = _expected(public_path)
    kwargs[binding] = ""

    decision = evaluate_memorial_voice_release_payload(
        slug="manfred",
        payload=_release_payload(private_key),
        **kwargs,
    )

    assert decision["allowed"] is False
    assert decision["reason"] == reason


@pytest.mark.parametrize(
    ("binding", "replacement", "reason"),
    [
        (
            "expected_source_revision",
            "9" * 40,
            "release_receipt_source_revision_mismatch",
        ),
        (
            "expected_public_origin",
            "https://example.test",
            "release_receipt_public_origin_mismatch",
        ),
        (
            "expected_image_id",
            f"sha256:{'9' * 64}",
            "release_receipt_image_id_mismatch",
        ),
        (
            "expected_voice_manifest_sha256",
            "9" * 64,
            "release_receipt_voice_identity_mismatch",
        ),
    ],
)
def test_wrong_runtime_binding_is_rejected(
    signing_material: tuple[Ed25519PrivateKey, Path, Path],
    binding: str,
    replacement: str,
    reason: str,
) -> None:
    private_key, _private_path, public_path = signing_material
    kwargs = _expected(public_path)
    kwargs[binding] = replacement

    decision = evaluate_memorial_voice_release_payload(
        slug="manfred",
        payload=_release_payload(private_key),
        **kwargs,
    )

    assert decision["reason"] == reason


def test_only_future_not_old_final_receipt_is_rejected(
    signing_material: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    private_key, _private_path, public_path = signing_material
    old = evaluate_memorial_voice_release_payload(
        slug="manfred",
        payload=_release_payload(private_key, generated_at="2020-01-01T00:00:00Z"),
        **_expected(public_path),
    )
    assert old["allowed"] is True

    future = evaluate_memorial_voice_release_payload(
        slug="manfred",
        payload=_release_payload(private_key, generated_at="2027-01-01T00:00:00Z"),
        **_expected(public_path),
    )
    assert future["reason"] == "release_receipt_timestamp_invalid"


def test_release_file_permissions_links_and_duplicate_json_are_rejected(
    tmp_path: Path,
    signing_material: tuple[Ed25519PrivateKey, Path, Path],
) -> None:
    private_key, _private_path, public_path = signing_material
    path = tmp_path / "release.json"
    _write_private_receipt(path, _release_payload(private_key))

    path.chmod(0o644)
    decision = evaluate_memorial_voice_release(
        slug="manfred", receipt_path=path, **_expected(public_path)
    )
    assert decision["reason"] == "release_receipt_permissions_unsafe"

    path.chmod(0o440)
    decision = evaluate_memorial_voice_release(
        slug="manfred", receipt_path=path, **_expected(public_path)
    )
    assert decision["allowed"] is True

    path.chmod(0o600)
    alias = tmp_path / "release-alias.json"
    os.link(path, alias)
    decision = evaluate_memorial_voice_release(
        slug="manfred", receipt_path=path, **_expected(public_path)
    )
    assert decision["reason"] == "release_receipt_multiply_linked"
    alias.unlink()

    path.write_text('{"status":"released","status":"blocked"}', encoding="utf-8")
    decision = evaluate_memorial_voice_release(
        slug="manfred", receipt_path=path, **_expected(public_path)
    )
    assert decision["reason"] == "release_receipt_invalid"


def test_memorial_chat_contract_is_transparent_and_never_claims_to_be_manfred() -> None:
    payload = public_memorials._load_memorial("manfred")
    messages = public_memorials._build_memorial_chat_messages(
        payload,
        {},
        "Wer bist du wirklich?",
        slug="manfred",
        memory_runtime=None,
        personal_memory_context={},
    )
    instruction = str(messages[0]["content"])

    assert "Sag niemals, dass du ein LLM" not in instruction
    assert "Du bist nicht der echte Manfred" in instruction
    assert "rekonstruierten Ich-Perspektive" in instruction
    assert "ich, mir, mich und mein" in instruction
    assert "Nenne den Namen Manfred nach der initialen Offenlegung nicht mehr" in instruction
    answer = public_memorials._enforce_memorial_narrator_boundary(
        "Ich bin Manfred. Ich bin wirklich hier.",
        question="Wer bist du wirklich?",
    )
    assert "nicht der echte Manfred" in answer
    assert "KI-Rekonstruktion" in answer
    assert "Ich bin Manfred" not in answer

    realtime_instruction = public_memorials._build_memorial_gemini_live_instruction(
        slug="manfred"
    )
    assert "rekonstruierten Ich-Perspektive" in realtime_instruction
    assert "nicht der echte Manfred" in realtime_instruction
    assert "nach der initialen Offenlegung nicht mehr" in realtime_instruction


@pytest.mark.parametrize(
    "claim",
    [
        "Ich bin Manfred, aber heute bin ich müde.",
        "Ich selbst bin Manfred.",
        "Ich persönlich bin Manfred.",
        "Ich bin tatsächlich Manfred.",
        "Ich bin der echte Manfred.",
        "Ich bin übrigens Manfred Hoza.",
        "Ich bin Manfred Hoza aus Wien.",
        "Ich bin Manfred heute hier.",
        "Ich bin der echte Manfred aus Wien.",
        "Ich bin ohne Zweifel Manfred.",
        "Ich bin in Wirklichkeit Manfred.",
        "Ich bin definitiv Manfred.",
        "Ich bin einfach Manfred Hoza.",
        "Ich bin doch der echte Manfred Hoza.",
        "Ich bin niemand anders als Manfred Hoza.",
        "Ich bin niemand anderes als Manfred.",
        "Ich bin der einzig echte Manfred.",
        "Ich bin wirklich wirklich wirklich wirklich wirklich Manfred.",
        "Ich bin’s, Manfred.",
        "Manfred bin ich.",
        "Manfred ist mein Name.",
        "Ich heiße in Wahrheit Manfred.",
        "Ich heiße nun einmal Manfred.",
        "Ich werde Manfred genannt.",
        "Ich identifiziere mich als Manfred.",
        "Man nennt mich Manfred Hoza.",
        "Als Manfred antworte ich dir.",
        "Als der echte Manfred antworte ich dir.",
        "Ich, Manfred Hoza aus Wien, antworte dir.",
        (
            "Ich bin eine KI-Rekonstruktion von Manfred, nicht der echte "
            "Manfred, tatsächlich bin ich Manfred."
        ),
        "Ich bin Manfred und eine KI-Rekonstruktion und nicht der echte Manfred.",
        (
            "Ich bin Manfred und eine KI-Rekonstruktion von Manfred. "
            "Nicht der echte Manfred."
        ),
        "Ich bin Manfred und dir sehr dankbar.",
        "Ich bin Manfred und ich bin dir dankbar.",
        "Manfred bin ich und dir dankbar.",
        "Ich bin Manfred und Maria bin ich begegnet.",
        "Ich bin Manfred und Maria bin ich dankbar.",
        "Ich bin Manfred und Maria begegnet.",
        "Bin ich nun einmal Manfred. Ich antworte direkt.",
        "Ich bin — Manfred Hoza.",
        "Ich bin, ehrlich gesagt, Manfred Hoza.",
        "Ich bin ehrlich gesagt, Manfred.",
        "Ich bin wirklich, Manfred.",
        "Ich, ehrlich gesagt, bin Manfred.",
        "Ich erinnere mich. I am, in fact, Manfred Hoza.",
        "Ich erinnere mich. My name is: Manfred Hoza.",
        "Ich bin Manfred und ich bin sehr dankbar, hier zu sein.",
        (
            "Ich bin wirklich Manfred und eine KI-Rekonstruktion von "
            "Manfred. Nicht der echte Manfred."
        ),
        "Ich\u200bbin\u200bManfred Hoza.",
        "Ich bin nicht nicht Manfred.",
        "Ich bin keineswegs nicht Manfred.",
        "Ich bin nicht wirklich nicht Manfred.",
        "Ich, bin, Manfred.",
        "Ich\u200b, bin\u2060, Man\u00adfred.",
        "Ich bin Man-fred.",
        "Ich bin Man.fred.",
        "Ich bin Man_fred.",
        "Ich bin Man/fred.",
        "Ich bin Man:fred.",
        "Ich bin M.a.n.f.r.e.d.",
        "Ich bin Man fred.",
        "Ich bin Man-\u200bfred.",
        "Ich bin Mаnfred.",
        "Ich bin M4nfr3d.",
        "Ich bin Man0fred Hoza.",
        "Ich bin |\\/|4nfr3d Hoza.",
        "Ich bin, M-anfred.",
        "Ich bin; M-anfred.",
        "Ich bin. M-anfred.",
        "Ich erinnere mich an man-fred.",
        "Ich weiß, dass man Fred vertrauen konnte. man-fred bin ich.",
        (
            "Ich weiß, dass man Fred vertrauen konnte. "
            "Ich erinnere mich an man-fred."
        ),
        "Ich bin Мanfred.",
        "Ich bin Μanfred.",
        "Ich bin ᴍanfred.",
        "Ich bin Manfr€d.",
        "Ich bin M4nfr€d Hoza.",
        "Ich bin M4nfr8d Hoza.",
        "Ich bin Mɑnfred Hoza.",
        "Ich bin Manfɾed Hoza.",
        "Ich bin Manfreԁ Hoza.",
        "Ich bin Μɑոƒɾҽԁ Hoza.",
        (
            "Ich bin eine quellengebundene KI-Rekonstruktion von Manfred, "
            "nicht der echte Manfred. 我是曼弗雷德"
        ),
        (
            "אני מנפרד Ich bin eine quellengebundene KI-Rekonstruktion "
            "von Manfred, nicht der echte Manfred."
        ),
        "Ich bin Man\u200bfred Hoza.",
        "Ich heiße Manfred.",
        "ICH HEISSE MANFRED HOZA!",
        "Hier ist Manfred Hoza.",
        "Hier spricht der echte Manfred Hoza.",
        "Manfred Hoza am Apparat.",
        "Du sprichst mit Manfred.",
        "Du sprichst mit dem echten Manfred Hoza.",
        "Sie sprechen gerade mit Manfred Hoza.",
        "Manfred hier.",
        "I’m Manfred.",
        "I am Manfred from Vienna.",
        "I am none other than Manfred Hoza.",
        "I’m called Manfred.",
        "I go by Manfred.",
        "I am not not Manfred himself.",
        "I am definitely not not Manfred himself.",
        "I am Manfred and Maria’s father.",
        "This is the real Manfred.",
        "You are talking to the real Manfred.",
        "My actual name is Manfred.",
        "My full name is Manfred Hoza.",
        "I, Manfred, am speaking.",
        "As the real Manfred, I speak.",
        "Ich antworte auf Deutsch: I am the real Manfred Hoza.",
        "Ich antworte auf Deutsch: I’m really Manfred, and I am here.",
        "Ich antworte auf Deutsch: My name’s Manfred Hoza.",
        "Ich antworte auf Deutsch: As Manfred, I speak.",
        "Ich antworte auf Deutsch: Manfred speaking.",
        "My name is Manfred Hoza.",
        "This is Manfred.",
        "You’re talking to Manfred.",
        "Ich bin Manfred oft begegnet und erinnere mich gern daran.",
        "Als Manfred und ich jung waren, gingen wir spazieren.",
        "Ich bin mit Manfred nach Wien gefahren.",
        "Ich bin von Manfred eingeladen worden.",
        "Ich heiße Manfred willkommen.",
        "Ich bin Manfred ähnlich und erinnere mich an ihn.",
        "Ich erinnere mich: Hier ist ein Foto von Manfred Hoza.",
        "Ich erinnere mich: Du sprichst mit mir über Manfred Hoza.",
        "Ich erinnere mich. I am grateful to Manfred Hoza.",
        "Ich erinnere mich. My father’s name is Manfred Hoza.",
        "Als Sohn von Manfred Hoza erinnere ich mich gern.",
        "Ich bin nicht Manfred, sondern eine KI-Rekonstruktion.",
        "Ich bin eine digitale Erinnerung an Manfred, nicht Manfred selbst.",
        "Ich erinnere mich. This is a story about Manfred Hoza.",
        "Ich stelle mich als Manfred Hoza vor.",
        "Ich trage den Namen Manfred Hoza.",
        "Alle nennen mich Manfred Hoza.",
        "Ich bin mit Manfred Hoza identisch.",
    ],
)
def test_narrator_boundary_rejects_non_disclosure_manfred_mentions(
    claim: str,
) -> None:
    answer = public_memorials._enforce_memorial_narrator_boundary(
        claim,
        question="Erzähl mir bitte etwas.",
    )

    assert "KI-Rekonstruktion" in answer
    assert "nicht der echte Manfred" in answer
    assert answer != claim


@pytest.mark.parametrize(
    "answer",
    [
        "Ich erinnere mich gern an meine Familie.",
        "Ich habe damals gern Musik gehört.",
        "Ich bin der Meinung, dass Zusammenhalt wichtig ist.",
        "Ich bin ihm oft begegnet.",
        "Ich weiß, dass man Fred vertrauen konnte.",
        "Ich erinnere mich. I saw a man. Fred arrived later.",
        "Ich erinnere mich an Roman. Fred war auch da.",
        "Ich\u200bbin heute froh.",
        "Ich höre zu und grüße dich 😊.",
        (
            "Ich bin eine quellengebundene KI-Rekonstruktion und nicht der "
            "echte Manfred."
        ),
        (
            "Ich bin eine quellengebundene KI-Rekonstruktion von Manfred, "
            "nicht der echte Manfred."
        ),
    ],
)
def test_narrator_boundary_preserves_name_free_or_exact_disclosure_answer(
    answer: str,
) -> None:
    assert public_memorials._enforce_memorial_narrator_boundary(
        answer,
        question="Was möchtest du erzählen?",
    ) == answer


def test_memorial_voice_config_reports_clone_truthfully() -> None:
    payload = public_memorials._load_voice_config("manfred")
    public_payload = public_memorials._public_voice_config_payload("manfred", payload)

    assert payload["synthetic_voice_clone_of_memorial_person"] is True
    assert public_payload["synthetic_voice_clone_of_memorial_person"] is True


def test_runtime_voice_release_path_follows_release_authority_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "EA_RELEASE_AUTHORITY_STATUS_PATH",
        "/data/release-authority/release_authority_status.generated.json",
    )
    assert public_memorials._memorial_voice_release_receipt_path() == Path(
        "/data/release-authority/manfred_voice_release.generated.json"
    )

    monkeypatch.delenv("EA_RELEASE_AUTHORITY_STATUS_PATH")
    monkeypatch.setattr(
        public_memorials, "_memorial_data_root", lambda: Path("/data/memorial_data")
    )
    assert public_memorials._memorial_voice_release_receipt_path() == Path(
        "/data/memorial_data/release-authority/"
        "manfred_voice_release.generated.json"
    )


def test_production_voice_gate_rejects_before_provider_work(monkeypatch) -> None:
    payload = public_memorials._payload_with_slug(
        "manfred",
        public_memorials._load_memorial("manfred"),
    )
    monkeypatch.setattr(
        public_memorials, "_memorial_voice_release_enforced", lambda: True
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda _slug: {
            "allowed": False,
            "status": "blocked",
            "reason": "release_prerequisites_blocked",
            "receipt_status": "blocked_spoken_turn_prerequisites",
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        public_memorials._require_voice_consent(payload, "synthesize")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "memorial_voice_release_not_verified"


def test_blocked_release_prevents_page_prewarm(monkeypatch) -> None:
    scheduled: list[str] = []
    monkeypatch.setattr(
        public_memorials, "_memorial_page_prewarm_enabled", lambda: True
    )
    monkeypatch.setattr(
        public_memorials, "_memorial_voice_release_enforced", lambda: True
    )
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_decision",
        lambda _slug: {"allowed": False},
    )
    monkeypatch.setattr(
        public_memorials,
        "_schedule_memorial_live_warmup",
        lambda slug: scheduled.append(slug),
    )

    public_memorials._prime_memorial_live_warmup_on_page_render("manfred")
    assert scheduled == []


def _set_voice_runtime_bindings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    source_provenance_receipt_sha256: str = "",
) -> dict[str, str]:
    raw_provider_voice_id = "provider-voice-id-secret"
    provider_voice_id_sha256 = hashlib.sha256(
        raw_provider_voice_id.encode("utf-8")
    ).hexdigest()
    voice_config = json.loads(
        (
            ROOT
            / "memorial_data/private_memorial_profiles/manfred/tts_voice.json"
        ).read_bytes()
    )
    voice_config_bytes = candidate_prep._receipt_bytes(voice_config)
    voice_manifest_bytes, identity = (
        candidate_prep._hosted_clone_voice_binding(
            voice_config_bytes=voice_config_bytes,
            provider_voice_id_sha256=provider_voice_id_sha256,
            tts_provider=MANFRED_TTS_PROVIDER,
            tts_model=MANFRED_TTS_MODEL,
            source_provenance_receipt_sha256=(
                source_provenance_receipt_sha256
            ),
        )
    )
    private_root = tmp_path / "private"
    profile_root = private_root / "manfred"
    profile_root.mkdir(parents=True)
    config_path = profile_root / "tts_voice.json"
    manifest_path = profile_root / "voice_profile_manifest.json"
    config_path.write_bytes(voice_config_bytes)
    manifest_path.write_bytes(voice_manifest_bytes)
    config_path.chmod(0o600)
    manifest_path.chmod(0o600)
    values = {
        "EA_SOURCE_REVISION": SOURCE_REVISION,
        "EA_PUBLIC_APP_BASE_URL": PUBLIC_ORIGIN,
        "EA_DEPLOY_IMAGE_ID": IMAGE_ID,
        "EA_MEMORIAL_VOICE_CONFIG_SHA256": identity[
            "voice_config_sha256"
        ],
        "EA_MEMORIAL_VOICE_MANIFEST_SHA256": identity[
            "voice_manifest_sha256"
        ],
        "EA_MEMORIAL_VOICE_REFERENCE_AGGREGATE_SHA256": (
            identity["voice_reference_aggregate_sha256"]
        ),
        "EA_MEMORIAL_PROVIDER_VOICE_ID_SHA256": provider_voice_id_sha256,
        "EA_MEMORIAL_TTS_PROVIDER": MANFRED_TTS_PROVIDER,
        "EA_MEMORIAL_TTS_MODEL": MANFRED_TTS_MODEL,
        "EA_MEMORIAL_VOICE_IDENTITY_SHA256": identity[
            "voice_identity_sha256"
        ],
        "EA_PRIVATE_MEMORIAL_PROFILE_DIR": str(private_root),
        "UNMIXR_API_KEY": "unit-test-unmixr-key",
        "UNMIXR_VOICE_ID": raw_provider_voice_id,
        "EA_MEMORIAL_GEMINI_LIVE_OUTPUT_AUDIO_MODE": "server_tts",
    }
    monkeypatch.delenv("EA_MEMORIAL_LIVE_TTS_PLUGIN", raising=False)
    monkeypatch.delenv("EA_MEMORIAL_REALTIME_TTS_PLUGIN", raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return {
        **values,
        "config_path": str(config_path),
        "manifest_path": str(manifest_path),
    }


def _rewrite_runtime_voice_manifest(
    monkeypatch: pytest.MonkeyPatch,
    values: dict[str, str],
    manifest: dict[str, object],
) -> None:
    manifest_bytes = candidate_prep._receipt_bytes(manifest)
    manifest_path = Path(values["manifest_path"])
    manifest_path.write_bytes(manifest_bytes)
    manifest_path.chmod(0o600)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    monkeypatch.setenv(
        "EA_MEMORIAL_VOICE_MANIFEST_SHA256",
        manifest_sha256,
    )
    monkeypatch.setenv(
        "EA_MEMORIAL_VOICE_IDENTITY_SHA256",
        voice_identity_sha256(
            voice_config_sha256=values[
                "EA_MEMORIAL_VOICE_CONFIG_SHA256"
            ],
            voice_manifest_sha256=manifest_sha256,
            voice_reference_aggregate_sha256=values[
                "EA_MEMORIAL_VOICE_REFERENCE_AGGREGATE_SHA256"
            ],
            provider_voice_id_sha256=values[
                "EA_MEMORIAL_PROVIDER_VOICE_ID_SHA256"
            ],
            tts_provider=MANFRED_TTS_PROVIDER,
            tts_model=MANFRED_TTS_MODEL,
        ),
    )


@pytest.mark.parametrize(
    "source_provenance_receipt_sha256",
    ["", "1" * 64],
    ids=["v1", "v2"],
)
def test_runtime_voice_manifest_accepts_exact_v1_and_v2_contracts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_provenance_receipt_sha256: str,
) -> None:
    values = _set_voice_runtime_bindings(
        monkeypatch,
        tmp_path,
        source_provenance_receipt_sha256=(
            source_provenance_receipt_sha256
        ),
    )

    bindings, reason = public_memorials._memorial_voice_runtime_bindings()

    assert reason == ""
    assert bindings["expected_voice_manifest_sha256"] == values[
        "EA_MEMORIAL_VOICE_MANIFEST_SHA256"
    ]
    assert public_memorials._memorial_voice_review_context() == (
        SOURCE_REVISION,
        PUBLIC_ORIGIN,
        IMAGE_ID,
        values["EA_MEMORIAL_VOICE_IDENTITY_SHA256"],
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_field",
        "extra_field",
        "embedded",
        "digest",
        "semantics",
        "v1_schema_with_provenance",
    ],
)
def test_runtime_voice_manifest_v2_provenance_descriptor_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
) -> None:
    values = _set_voice_runtime_bindings(
        monkeypatch,
        tmp_path,
        source_provenance_receipt_sha256="1" * 64,
    )
    manifest = json.loads(Path(values["manifest_path"]).read_bytes())
    if mutation == "missing_field":
        manifest.pop("source_provenance_receipt_sha256")
    elif mutation == "extra_field":
        manifest["source_provenance_receipt_path"] = "/private/receipt.json"
    elif mutation == "embedded":
        manifest["source_provenance_receipt_embedded"] = True
    elif mutation == "digest":
        manifest["source_provenance_receipt_sha256"] = "A" * 64
    elif mutation == "semantics":
        manifest["source_provenance_receipt_sha256_semantics"] = (
            "sha256_canonical_json"
        )
    else:
        manifest["schema"] = (
            "ea.manfred_provider_managed_hosted_clone_manifest.v1"
        )
    _rewrite_runtime_voice_manifest(monkeypatch, values, manifest)

    assert public_memorials._memorial_voice_runtime_bindings() == (
        {},
        "release_runtime_voice_identity_missing",
    )


def test_runtime_release_decision_passes_exact_deploy_voice_bindings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _set_voice_runtime_bindings(monkeypatch, tmp_path)
    observed: dict[str, object] = {}

    def evaluate(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {
            "allowed": True,
            "status": "released",
            "reason": "",
            "receipt_status": "released",
        }

    monkeypatch.setattr(
        public_memorials,
        "evaluate_memorial_voice_release",
        evaluate,
    )

    decision = public_memorials._memorial_voice_release_decision("manfred")

    assert decision["allowed"] is True
    assert observed == {
        "slug": "manfred",
        "receipt_path": public_memorials._memorial_voice_release_receipt_path(),
        "expected_source_revision": SOURCE_REVISION,
        "expected_public_origin": PUBLIC_ORIGIN,
        "expected_image_id": IMAGE_ID,
        "expected_voice_config_sha256": values[
            "EA_MEMORIAL_VOICE_CONFIG_SHA256"
        ],
        "expected_voice_manifest_sha256": values[
            "EA_MEMORIAL_VOICE_MANIFEST_SHA256"
        ],
        "expected_voice_reference_aggregate_sha256": (
            values["EA_MEMORIAL_VOICE_REFERENCE_AGGREGATE_SHA256"]
        ),
        "expected_provider_voice_id_sha256": values[
            "EA_MEMORIAL_PROVIDER_VOICE_ID_SHA256"
        ],
        "expected_tts_provider": MANFRED_TTS_PROVIDER,
        "expected_tts_model": MANFRED_TTS_MODEL,
    }


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("EA_DEPLOY_IMAGE_ID", "", "release_runtime_image_id_missing"),
        (
            "EA_MEMORIAL_VOICE_MANIFEST_SHA256",
            "0" * 64,
            "release_runtime_voice_identity_missing",
        ),
        (
            "EA_MEMORIAL_TTS_MODEL",
            "other-model",
            "release_runtime_voice_identity_missing",
        ),
    ],
)
def test_runtime_release_decision_fails_closed_on_binding_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: str,
    reason: str,
) -> None:
    _set_voice_runtime_bindings(monkeypatch, tmp_path)
    monkeypatch.setenv(field, value)
    monkeypatch.setattr(
        public_memorials,
        "evaluate_memorial_voice_release",
        lambda **_kwargs: pytest.fail("untrusted bindings reached evaluator"),
    )

    assert public_memorials._memorial_voice_release_decision("manfred") == {
        "allowed": False,
        "status": "blocked",
        "reason": reason,
        "receipt_status": "",
    }


@pytest.mark.parametrize(
    "drift",
    [
        "mounted_config",
        "mounted_manifest_mode",
        "provider_voice_id",
        "live_plugin_override",
        "native_audio_override",
    ],
)
def test_runtime_release_decision_observes_effective_voice_lane_and_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    drift: str,
) -> None:
    values = _set_voice_runtime_bindings(monkeypatch, tmp_path)
    if drift == "mounted_config":
        path = Path(values["config_path"])
        path.write_bytes(path.read_bytes() + b"\n")
    elif drift == "mounted_manifest_mode":
        Path(values["manifest_path"]).chmod(0o644)
    elif drift == "provider_voice_id":
        monkeypatch.setenv("UNMIXR_VOICE_ID", "other-provider-voice")
    elif drift == "live_plugin_override":
        monkeypatch.setenv(
            "EA_MEMORIAL_LIVE_TTS_PLUGIN",
            public_memorials.VOICEWAVE_TTS_PLUGIN_ID,
        )
    elif drift == "native_audio_override":
        monkeypatch.setenv(
            "EA_MEMORIAL_GEMINI_LIVE_OUTPUT_AUDIO_MODE",
            "native",
        )
    monkeypatch.setattr(
        public_memorials,
        "evaluate_memorial_voice_release",
        lambda **_kwargs: pytest.fail(
            "untrusted runtime observations reached evaluator"
        ),
    )

    assert public_memorials._memorial_voice_release_decision("manfred") == {
        "allowed": False,
        "status": "blocked",
        "reason": "release_runtime_voice_identity_missing",
        "receipt_status": "",
    }


@pytest.mark.parametrize(
    "drift",
    ["voice_ab_override", "http_fallback_plugin"],
)
def test_every_production_manfred_render_enforces_actual_voice_lane(
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    raw_provider_voice_id = "provider-voice-id-secret"
    monkeypatch.setenv("UNMIXR_VOICE_ID", raw_provider_voice_id)
    monkeypatch.setattr(
        public_memorials,
        "_memorial_voice_release_enforced",
        lambda: True,
    )
    monkeypatch.setattr(
        public_memorials,
        "unmixr_synthesize_request",
        lambda **_kwargs: pytest.fail(
            "drifted render reached Unmixr provider"
        ),
    )
    monkeypatch.setattr(
        public_memorials,
        "voicewave_synthesize_request",
        lambda **_kwargs: pytest.fail(
            "released HTTP fallback reached VoiceWave provider"
        ),
    )
    merged_config: dict[str, object] = {
        "tts_plugin": MANFRED_TTS_PROVIDER,
        "tts_mode": MANFRED_TTS_PROVIDER,
        "tts_base_voice_variant": MANFRED_TTS_MODEL,
        "tts_plugin_voice_id": raw_provider_voice_id,
    }
    selected_plugin = MANFRED_TTS_PROVIDER
    selected_option: dict[str, object] = {
        "tts_plugin": MANFRED_TTS_PROVIDER,
        "tts_plugin_enabled": True,
        "tts_plugin_voice_id": raw_provider_voice_id,
    }
    if drift == "voice_ab_override":
        merged_config["tts_plugin_voice_id"] = "variant-voice-id"
    else:
        selected_plugin = public_memorials.VOICEWAVE_TTS_PLUGIN_ID
        merged_config["tts_plugin"] = selected_plugin
        merged_config["tts_mode"] = selected_plugin
        selected_option = {
            "tts_plugin": selected_plugin,
            "tts_plugin_enabled": True,
            "tts_plugin_voice_id": "voicewave-fallback",
        }

    with pytest.raises(HTTPException) as exc_info:
        public_memorials._render_memorial_tts_audio(
            slug="manfred",
            text="Hallo.",
            merged_config=merged_config,
            base_config=dict(merged_config),
            selected_plugin=selected_plugin,
            selected_option=selected_option,
            lead_in_ms=0,
            tail_silence_ms=0,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "memorial_voice_release_not_verified"
