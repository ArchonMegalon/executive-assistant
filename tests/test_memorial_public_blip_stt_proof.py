from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import ModuleType
from typing import Callable

import pytest


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(UTC).replace(microsecond=0)
SOURCE_REVISION = "b" * 40
IMAGE_ID = "sha256:" + ("c" * 64)
DEPLOYMENT_ID = "manfred-live-20260726T180000Z-publicproof"
AUDIO_BYTES = b"offline-fixture-operator-voice-not-real-audio"
TRANSCRIPT_SENTINEL = "Das ist nur ein nicht gespeicherter Testtranskript-Satz."


def _load_script(name: str) -> ModuleType:
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


proof = _load_script("materialize_memorial_public_blip_stt_proof")
verifier = _load_script("verify_memorial_public_blip_stt_proof")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _write_private_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _write_private_bytes(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def _deployment() -> dict[str, object]:
    stt_policy = copy.deepcopy(proof.EXPECTED_STT_POLICY)
    stt_policy_binding = {
        "schema": proof.EXPECTED_STT_POLICY_BINDING_SCHEMA,
        "probe_source": "candidate_api_container_runtime_contract",
        "source_revision": SOURCE_REVISION,
        "image_id": IMAGE_ID,
        "api_container_id": "d" * 64,
    }
    return {
        "contract_name": "ea.memorial_joint_api_ingress_deploy.v2",
        "status": "pass",
        "deployment_id": DEPLOYMENT_ID,
        "source_revision": SOURCE_REVISION,
        "started_at": _iso(NOW - timedelta(minutes=30)),
        "completed_at": _iso(NOW - timedelta(minutes=20)),
        "candidate_image": {"image_id": IMAGE_ID},
        "release_source": {"source_revision": SOURCE_REVISION},
        "stt_policy": stt_policy,
        "stt_policy_binding": stt_policy_binding,
        "candidate_promotion_evidence": {
            "status": "pass",
            "source_revision": SOURCE_REVISION,
            "image_id": IMAGE_ID,
            "runtime_revision_matches_image": True,
            "runtime_identity": {
                "source_revision": SOURCE_REVISION,
                "authority_commit": SOURCE_REVISION,
                "oci_image_revision": SOURCE_REVISION,
                "revision_agreement_verified": True,
            },
            "stt_policy": stt_policy,
            "stt_policy_binding": stt_policy_binding,
        },
        "checks": [
            {"name": name, "status": "pass"}
            for name in sorted(proof._REQUIRED_DEPLOYMENT_CHECKS)
        ],
        "joint_atomicity": {
            "transaction_status": "committed",
            "api_rollback_baseline_verified": True,
            "ingress_rollback_baseline_verified": True,
            "network_rollback_baseline_captured": True,
            "public_edge_rollback_baseline_captured": True,
        },
        "rollback": {"status": "available"},
        "rollback_capsule": {
            "status": "sealed",
            "mode": "0600",
            "sha256": "sha256:" + ("e" * 64),
        },
        "rollback_render_preflight": {
            "status": "pass",
            "capsule_sha256": "sha256:" + ("e" * 64),
        },
        "recovery_journal_cleanup": {"status": "removed"},
    }


@dataclass
class Case:
    private_root: Path
    deployment: Path
    registry: Path
    signing_key: Path
    integrity_binding: Path
    challenge: Path
    state_root: Path
    output: Path
    audio: Path
    signer: object


def _integrity_binding_unsigned(
    deployment_binding: dict[str, object],
    signer: object,
    *,
    issued_at: datetime,
) -> dict[str, object]:
    return {
        "contract_name": proof.INTEGRITY_BINDING_CONTRACT_NAME,
        "contract_version": proof.INTEGRITY_BINDING_CONTRACT_VERSION,
        "issuer": signer.key_record.issuer,
        "environment": signer.key_record.environment,
        "issued_at": _iso(issued_at),
        "expires_at": _iso(issued_at + timedelta(hours=1)),
        "scope": {
            "proof_scope": proof.PROOF_SCOPE,
            "public_origin": proof.PUBLIC_ORIGIN,
            "public_endpoint": proof.PUBLIC_ENDPOINT,
            "method": "POST",
            "memorial_slug": proof.MEMORIAL_SLUG,
            "real_audio_required": True,
            "operator_upload_confirmation_required": True,
        },
        "deployment_binding": deployment_binding,
        "operator_integrity_key": proof._key_identity(signer.key_record),
    }


def _make_case(
    tmp_path: Path,
    *,
    issue_at: datetime = NOW,
    issue: bool = True,
) -> Case:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp_path.chmod(0o700)
    private_root = tmp_path / "private"
    private_root.mkdir(mode=0o700)
    seed = b"\x41" * 32
    signer = proof.Ed25519EnvelopeSigner.from_seed(
        seed,
        issuer="ea.sole_operator",
        environment="production",
        key_ref="memorial-public-blip-integrity",
        key_epoch=1,
        not_before=_iso(NOW - timedelta(hours=2)),
        not_after=_iso(NOW + timedelta(hours=2)),
    )
    registry = private_root / "trusted-registry.json"
    proof.Ed25519KeyRegistry([signer.key_record], path=registry)
    signing_key = private_root / "operator-integrity.seed"
    _write_private_bytes(signing_key, seed)
    deployment = private_root / "deployment.json"
    _write_private_json(deployment, _deployment())
    deployment_artifact = proof._load_private_json(
        deployment,
        label="deployment_receipt",
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
        maximum_bytes=proof.MAX_JSON_BYTES,
    )
    deployment_binding = proof._validate_deployment(
        deployment_artifact,
        observed_at=issue_at,
    )
    integrity = proof.sign_envelope(
        _integrity_binding_unsigned(
            deployment_binding.as_dict(),
            signer,
            issued_at=issue_at - timedelta(minutes=5),
        ),
        signer,
    )
    integrity_binding = private_root / "operator-integrity-binding.json"
    _write_private_json(integrity_binding, integrity)
    challenge = private_root / "challenge.json"
    state_root = private_root / "state"
    output = private_root / "proof.json"
    audio = private_root / "operator-audio.webm"
    _write_private_bytes(audio, AUDIO_BYTES)
    case = Case(
        private_root=private_root,
        deployment=deployment,
        registry=registry,
        signing_key=signing_key,
        integrity_binding=integrity_binding,
        challenge=challenge,
        state_root=state_root,
        output=output,
        audio=audio,
        signer=signer,
    )
    if issue:
        _issue(case, observed_at=issue_at)
    return case


def _issue(case: Case, *, observed_at: datetime = NOW) -> dict[str, object]:
    return proof.issue_challenge(
        deployment_receipt_path=case.deployment,
        operator_integrity_binding_path=case.integrity_binding,
        trusted_key_registry_path=case.registry,
        operator_integrity_signing_key_path=case.signing_key,
        state_root=case.state_root,
        challenge_output_path=case.challenge,
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
        observed_at=observed_at,
    )


def _success_observation(
    *,
    source_revision: str = SOURCE_REVISION,
) -> object:
    return proof.HttpObservation(
        status_code=200,
        headers=(
            ("cache-control", "no-store"),
            ("content-type", "application/json; charset=utf-8"),
            ("x-ea-source-revision", source_revision),
        ),
        body=json.dumps(
            {
                "transcription_status": "transcribed",
                "transcript_text": TRANSCRIPT_SENTINEL,
                "transcript_original_text": TRANSCRIPT_SENTINEL,
                "transcriber": "blipai/stt",
                "stt_ms": 123.5,
            }
        ).encode("utf-8"),
        tls_certificate_verified=True,
        hostname_verified=True,
        proxy_used=False,
        redirect_count=0,
    )


def _execute(
    case: Case,
    monkeypatch: pytest.MonkeyPatch,
    *,
    observation: object | None = None,
    phrase: str = proof.UPLOAD_AUTHORITY_PHRASE,
    observed_at: datetime = NOW,
    calls: list[int] | None = None,
) -> dict[str, object]:
    response = observation or _success_observation()

    def fake_post(
        _self: object,
        *,
        audio: bytearray,
        content_type: str,
        timeout: float,
    ) -> object:
        assert bytes(audio) == AUDIO_BYTES
        assert content_type == "audio/webm"
        assert timeout == proof.HTTP_TIMEOUT_SECONDS
        if calls is not None:
            calls.append(len(audio))
        return response

    monkeypatch.setattr(proof.DirectHttpsTransport, "post_audio", fake_post)
    descriptor = os.open(case.audio, os.O_RDONLY)
    try:
        return proof.execute_proof(
            challenge_ticket_path=case.challenge,
            deployment_receipt_path=case.deployment,
            operator_integrity_binding_path=case.integrity_binding,
            trusted_key_registry_path=case.registry,
            operator_integrity_signing_key_path=case.signing_key,
            state_root=case.state_root,
            output_path=case.output,
            audio_descriptor=descriptor,
            audio_content_type="audio/webm",
            operator_authorization_phrase=phrase,
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
            observed_at=observed_at,
        )
    finally:
        os.close(descriptor)


def _verify(case: Case, *, observed_at: datetime = NOW) -> dict[str, object]:
    return proof.verify_proof(
        case.output,
        challenge_ticket_path=case.challenge,
        deployment_receipt_path=case.deployment,
        operator_integrity_binding_path=case.integrity_binding,
        trusted_key_registry_path=case.registry,
        state_root=case.state_root,
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
        observed_at=observed_at,
    )


def test_only_executor_produces_signed_private_replay_bound_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path)
    calls: list[int] = []

    receipt = _execute(case, monkeypatch, calls=calls)
    verification = _verify(case)

    assert proof.HTTP_TIMEOUT_SECONDS == 60.0
    assert calls == [len(AUDIO_BYTES)]
    assert receipt["status"] == "pass"
    assert receipt["proof_eligible"] is True
    assert receipt["public_request"]["transcriber"] == "blipai/stt"
    assert receipt["public_request"]["x_ea_source_revision"] == SOURCE_REVISION
    assert receipt["immutable_deployment"]["stt_policy"] == {
        "primary": "blipai",
        "fallbacks": ["cartesia", "1min.ai"],
    }
    assert (
        receipt["integrity_evidence"]["trust_model"]
        == "sole_operator_protected_key_integrity_not_independent_approval"
    )
    assert receipt["claims"]["voice_flagship_or_gold_claim_allowed"] is False
    assert verification["status"] == "pass"
    assert verification["transcriber"] == "blipai/stt"
    assert stat.S_IMODE(case.output.stat().st_mode) == 0o600
    assert case.output.stat().st_uid == os.geteuid()
    assert case.output.stat().st_gid == os.getegid()
    assert case.output.stat().st_nlink == 1

    rendered = case.output.read_text(encoding="utf-8")
    assert AUDIO_BYTES.decode("ascii") not in rendered
    assert TRANSCRIPT_SENTINEL not in rendered
    assert proof.UPLOAD_AUTHORITY_PHRASE not in rendered
    assert "transcript_text" not in rendered
    assert "audio_sha" not in rendered
    assert receipt["privacy"]["audio_path_recorded"] is False
    assert "content_digest_recorded" in rendered
    journal = case.state_root / "challenge.journal.jsonl"
    rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert [row["state"] for row in rows] == [
        "issued",
        "execution_intent",
        "consumed_pass",
    ]
    assert all("audio" not in json.dumps(row).lower() for row in rows)
    assert stat.S_IMODE(journal.stat().st_mode) == 0o600


def test_exact_operator_phrase_is_the_only_upload_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path)
    calls: list[int] = []
    with pytest.raises(
        proof.PublicBlipProofError,
        match="^operator_upload_authorization_missing$",
    ):
        _execute(case, monkeypatch, phrase="fast richtig", calls=calls)
    assert calls == []
    assert not case.output.exists()
    journal = case.state_root / "challenge.journal.jsonl"
    assert [json.loads(line)["state"] for line in journal.read_text().splitlines()] == [
        "issued"
    ]


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (
            lambda item: replace(item, status_code=201),
            "public_response_status_not_200",
        ),
        (
            lambda item: replace(
                item,
                headers=tuple(
                    ("cache-control", "no-cache")
                    if key == "cache-control"
                    else (key, value)
                    for key, value in item.headers
                ),
            ),
            "public_response_cache_control_invalid",
        ),
        (
            lambda item: replace(
                item,
                headers=tuple(
                    ("x-ea-source-revision", "0" * 40)
                    if key == "x-ea-source-revision"
                    else (key, value)
                    for key, value in item.headers
                ),
            ),
            "public_response_source_revision_mismatch",
        ),
        (
            lambda item: replace(
                item,
                body=json.dumps(
                    {
                        "transcription_status": "transcribed",
                        "transcript_text": "fallback",
                        "transcriber": "cartesia/ink-whisper",
                    }
                ).encode(),
            ),
            "public_response_blip_transcript_not_proven",
        ),
        (
            lambda item: replace(
                item,
                body=json.dumps(
                    {
                        "transcription_status": "transcribed",
                        "transcript_text": "",
                        "transcriber": "blipai/stt",
                    }
                ).encode(),
            ),
            "public_response_blip_transcript_not_proven",
        ),
        (
            lambda item: replace(item, redirect_count=1),
            "public_response_redirect_observed",
        ),
        (
            lambda item: replace(item, tls_certificate_verified=False),
            "public_response_tls_not_verified",
        ),
        (
            lambda item: replace(item, proxy_used=True),
            "public_response_proxy_used",
        ),
    ],
)
def test_live_http_observation_is_exact_and_failure_consumes_challenge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutator: Callable[[object], object],
    reason: str,
) -> None:
    case = _make_case(tmp_path)
    calls: list[int] = []
    response = mutator(_success_observation())

    with pytest.raises(proof.PublicBlipProofError, match=f"^{reason}$"):
        _execute(case, monkeypatch, observation=response, calls=calls)

    assert calls == [len(AUDIO_BYTES)]
    assert not case.output.exists()
    rows = [
        json.loads(line)
        for line in (case.state_root / "challenge.journal.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [row["state"] for row in rows] == [
        "issued",
        "execution_intent",
        "consumed_abort",
    ]
    assert rows[-1]["failure_code"] == reason
    with pytest.raises(
        proof.PublicBlipProofError,
        match="^challenge_not_issued_or_already_consumed$",
    ):
        _execute(case, monkeypatch, calls=calls)
    assert calls == [len(AUDIO_BYTES)]


def test_duplicate_response_headers_and_json_keys_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path)
    response = _success_observation()
    duplicated = proof.HttpObservation(
        status_code=200,
        headers=(*response.headers, ("x-ea-source-revision", SOURCE_REVISION)),
        body=(
            b'{"transcription_status":"transcribed","transcript_text":"x",'
            b'"transcriber":"blipai/stt","transcriber":"blipai/stt"}'
        ),
        tls_certificate_verified=True,
        hostname_verified=True,
        proxy_used=False,
        redirect_count=0,
    )
    with pytest.raises(
        proof.PublicBlipProofError,
        match="^public_response_x_ea_source_revision_invalid$",
    ):
        _execute(case, monkeypatch, observation=duplicated)

    second = _make_case(tmp_path / "duplicate-json")
    duplicate_json = replace(
        _success_observation(),
        body=(
            b'{"transcription_status":"transcribed","transcript_text":"x",'
            b'"transcriber":"blipai/stt","transcriber":"blipai/stt"}'
        ),
    )
    with pytest.raises(
        proof.PublicBlipProofError,
        match="^public_response_json_invalid$",
    ):
        _execute(second, monkeypatch, observation=duplicate_json)


def test_one_time_challenge_cannot_be_replayed_after_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path)
    calls: list[int] = []
    _execute(case, monkeypatch, calls=calls)
    replay_case = replace(
        case,
        output=case.private_root / "proof-replay-attempt.json",
    )
    with pytest.raises(
        proof.PublicBlipProofError,
        match="^challenge_not_issued_or_already_consumed$",
    ):
        _execute(replay_case, monkeypatch, calls=calls)
    assert calls == [len(AUDIO_BYTES)]
    assert _verify(case)["status"] == "pass"


def test_plain_or_tampered_json_cannot_pass_without_valid_signature(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path)
    _execute(case, monkeypatch)
    receipt = json.loads(case.output.read_text(encoding="utf-8"))
    receipt["public_request"]["transcriber"] = "blipai/stt"
    receipt.pop("signature")
    _write_private_json(case.output, receipt)

    result = _verify(case)

    assert result["status"] == "fail"
    assert result["issues"] == ["proof_schema_invalid"]


def test_valid_key_cannot_co_substitute_nonce_without_journal_consumption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path)
    _execute(case, monkeypatch)
    ticket = json.loads(case.challenge.read_text(encoding="utf-8"))
    ticket["challenge_id"] = "9" * 64
    substituted_ticket = proof.sign_envelope(ticket, case.signer)
    _write_private_json(case.challenge, substituted_ticket)

    receipt = json.loads(case.output.read_text(encoding="utf-8"))
    receipt["challenge"]["challenge_id"] = "9" * 64
    receipt["challenge"]["ticket_digest"] = proof.bounded_sha256(
        substituted_ticket,
        prefixed=True,
    )
    substituted_receipt = proof.sign_envelope(receipt, case.signer)
    _write_private_json(case.output, substituted_receipt)

    result = _verify(case)

    assert result["status"] == "fail"
    assert result["issues"] == ["challenge_consumption_not_proven"]


def test_unregistered_integrity_key_or_wrong_private_key_fails_closed(
    tmp_path: Path,
) -> None:
    case = _make_case(tmp_path, issue=False)
    wrong_seed = b"\x42" * 32
    _write_private_bytes(case.signing_key, wrong_seed)
    with pytest.raises(
        proof.PublicBlipProofError,
        match="^operator_integrity_signing_key_not_registered$",
    ):
        _issue(case)
    assert not case.challenge.exists()
    assert not case.state_root.exists()


def test_integrity_binding_is_tamper_evidence_not_independent_approval(
    tmp_path: Path,
) -> None:
    case = _make_case(tmp_path, issue=False)
    binding = json.loads(case.integrity_binding.read_text(encoding="utf-8"))
    assert binding["signature"]["key_fingerprint"] == binding["operator_integrity_key"][
        "key_fingerprint"
    ]
    binding["deployment_binding"]["source_revision"] = "0" * 40
    _write_private_json(case.integrity_binding, binding)
    with pytest.raises(
        proof.PublicBlipProofError,
        match="^operator_integrity_signature_invalid$",
    ):
        _issue(case)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda payload: payload.__setitem__(
                "stt_policy",
                {"primary": "cartesia", "fallbacks": ["blipai", "1min.ai"]},
            ),
            "deployment_stt_policy_invalid",
        ),
        (
            lambda payload: payload["stt_policy"]["fallbacks"].reverse(),
            "deployment_stt_policy_invalid",
        ),
        (
            lambda payload: payload.__setitem__("source_revision", "0" * 40),
            "deployment_immutable_identity_invalid",
        ),
    ],
)
def test_deployment_policy_and_source_are_exact_before_challenge_issue(
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], None],
    reason: str,
) -> None:
    case = _make_case(tmp_path, issue=False)
    deployment = json.loads(case.deployment.read_text(encoding="utf-8"))
    mutation(deployment)
    _write_private_json(case.deployment, deployment)
    with pytest.raises(proof.PublicBlipProofError, match=f"^{reason}$"):
        _issue(case)
    assert not case.challenge.exists()
    assert not case.state_root.exists()


@pytest.mark.parametrize(
    ("target", "reason"),
    [
        ("deployment", "deployment_receipt_mode_not_0600"),
        ("registry", "trusted_key_registry_mode_not_0600"),
        ("integrity_binding", "operator_integrity_binding_mode_not_0600"),
        ("challenge", "challenge_ticket_mode_not_0600"),
    ],
)
def test_every_json_source_requires_0600_expected_owner_and_single_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    reason: str,
) -> None:
    case = _make_case(tmp_path)
    selected = getattr(case, target)
    selected.chmod(0o640)
    with pytest.raises(proof.PublicBlipProofError, match=f"^{reason}$"):
        _execute(case, monkeypatch)


def test_hardlink_and_symlink_sources_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path)
    hardlink = case.private_root / "deployment-hardlink.json"
    os.link(case.deployment, hardlink)
    with pytest.raises(
        proof.PublicBlipProofError,
        match="^deployment_receipt_link_count_invalid$",
    ):
        _execute(case, monkeypatch)
    hardlink.unlink()
    real_challenge = case.private_root / "challenge-real.json"
    case.challenge.replace(real_challenge)
    case.challenge.symlink_to(real_challenge.name)
    with pytest.raises(
        proof.PublicBlipProofError,
        match="^challenge_ticket_symlink_forbidden$",
    ):
        _execute(case, monkeypatch)


def test_wrong_expected_uid_fails_before_any_transport_or_state_change(
    tmp_path: Path,
) -> None:
    case = _make_case(tmp_path)
    result = proof.verify_proof(
        case.output,
        challenge_ticket_path=case.challenge,
        deployment_receipt_path=case.deployment,
        operator_integrity_binding_path=case.integrity_binding,
        trusted_key_registry_path=case.registry,
        state_root=case.state_root,
        expected_uid=os.geteuid() + 1,
        expected_gid=os.getegid(),
        observed_at=NOW,
    )
    assert result["status"] == "fail"
    assert result["issues"] == ["deployment_receipt_uid_mismatch"]


def test_output_hardlink_is_rejected_before_http_and_nonce_consumption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path)
    _write_private_bytes(case.output, b"old")
    linked = case.private_root / "proof-linked.json"
    os.link(case.output, linked)
    calls: list[int] = []
    with pytest.raises(
        proof.PublicBlipProofError,
        match="^proof_output_link_count_invalid$",
    ):
        _execute(case, monkeypatch, calls=calls)
    assert calls == []
    rows = [
        json.loads(line)["state"]
        for line in (case.state_root / "challenge.journal.jsonl")
        .read_text()
        .splitlines()
    ]
    assert rows == ["issued"]


def test_existing_regular_outputs_are_never_replaced_before_live_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unissued = _make_case(tmp_path / "issue", issue=False)
    _write_private_bytes(unissued.challenge, b"preserve-existing-challenge")
    with pytest.raises(
        proof.PublicBlipProofError,
        match="^challenge_ticket_already_exists$",
    ):
        _issue(unissued)
    assert unissued.challenge.read_bytes() == b"preserve-existing-challenge"
    assert not unissued.state_root.exists()

    case = _make_case(tmp_path / "execute")
    _write_private_bytes(case.output, b"preserve-existing-proof")
    calls: list[int] = []
    with pytest.raises(
        proof.PublicBlipProofError,
        match="^proof_output_already_exists$",
    ):
        _execute(case, monkeypatch, calls=calls)
    assert calls == []
    assert case.output.read_bytes() == b"preserve-existing-proof"
    states = [
        json.loads(line)["state"]
        for line in (case.state_root / "challenge.journal.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert states == ["issued"]


def test_journal_tamper_or_pending_recovery_blocks_verifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path)
    _execute(case, monkeypatch)
    journal = case.state_root / "challenge.journal.jsonl"
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    rows[-1]["proof_digest"] = "sha256:" + ("0" * 64)
    journal.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    journal.chmod(0o600)
    result = _verify(case)
    assert result["status"] == "fail"
    assert result["issues"] == ["challenge_journal_record_digest_invalid"]


def test_interrupted_intent_is_terminally_aborted_before_new_challenge(
    tmp_path: Path,
) -> None:
    case = _make_case(tmp_path)
    ticket = json.loads(case.challenge.read_text(encoding="utf-8"))
    artifact = proof._load_private_json(
        case.deployment,
        label="deployment_receipt",
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
        maximum_bytes=proof.MAX_JSON_BYTES,
    )
    deployment = proof._validate_deployment(artifact, observed_at=NOW)
    integrity_artifact = proof._load_private_json(
        case.integrity_binding,
        label="operator_integrity_binding",
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
        maximum_bytes=proof.MAX_INTEGRITY_BINDING_BYTES,
    )
    registry = proof._load_registry(
        case.registry,
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
    )
    integrity = proof._validate_operator_integrity_binding(
        integrity_artifact,
        registry=registry,
        deployment=deployment,
        observed_at=NOW,
    )
    ticket_digest = proof.bounded_sha256(ticket, prefixed=True)
    journal = proof.ChallengeJournal(
        case.state_root,
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
    )
    with journal.locked(recover_pending=True) as records:
        descriptor = journal._open_owned_file(
            journal.journal_path,
            create=True,
            append=True,
        )
        try:
            journal.append(
                descriptor,
                records,
                challenge_id=ticket["challenge_id"],
                state_value="execution_intent",
                ticket_digest=ticket_digest,
                deployment_receipt_digest=deployment.deployment_receipt_digest,
                operator_integrity_payload_digest=integrity.payload_digest,
                issued_at=ticket["issued_at"],
                expires_at=ticket["expires_at"],
                observed_at=_iso(NOW),
            )
        finally:
            os.close(descriptor)

    next_case = replace(
        case,
        challenge=case.private_root / "challenge-after-recovery.json",
    )
    _issue(next_case)

    states = [
        json.loads(line)["state"]
        for line in (case.state_root / "challenge.journal.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert states == [
        "issued",
        "execution_intent",
        "consumed_abort",
        "issued",
    ]


def test_sensitive_process_hardening_is_fail_closed_and_linux_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limits: list[tuple[int, tuple[int, int]]] = []
    prctl_calls: list[tuple[int, int, int, int, int]] = []

    class FakePrctl:
        argtypes: object = None
        restype: object = None

        def __call__(self, *args: int) -> int:
            prctl_calls.append(tuple(args))
            return 0

    class FakeLibc:
        prctl = FakePrctl()

    monkeypatch.setattr(
        proof.resource,
        "setrlimit",
        lambda resource_id, value: limits.append((resource_id, value)),
    )
    monkeypatch.setattr(
        proof.resource,
        "getrlimit",
        lambda _resource_id: (0, 0),
    )
    monkeypatch.setattr(proof.ctypes, "CDLL", lambda *_args, **_kwargs: FakeLibc())
    monkeypatch.setattr(proof.sys, "platform", "linux")

    proof._harden_sensitive_process()

    assert limits == [(proof.resource.RLIMIT_CORE, (0, 0))]
    assert prctl_calls == [(4, 0, 0, 0, 0), (3, 0, 0, 0, 0)]

    def fail_setrlimit(_resource_id: int, _value: tuple[int, int]) -> None:
        raise OSError("denied")

    monkeypatch.setattr(proof.resource, "setrlimit", fail_setrlimit)
    with pytest.raises(
        proof.PublicBlipProofError,
        match="^process_core_dump_hardening_failed$",
    ):
        proof._harden_sensitive_process()


def test_expired_challenge_never_reaches_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path, issue_at=NOW - timedelta(minutes=20))
    calls: list[int] = []
    with pytest.raises(
        proof.PublicBlipProofError,
        match="^challenge_ticket_signature_invalid$",
    ):
        _execute(case, monkeypatch, calls=calls)
    assert calls == []
    assert not case.output.exists()


def test_verifier_cli_reopens_all_protected_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _make_case(tmp_path)
    _execute(case, monkeypatch)
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_memorial_public_blip_stt_proof.py"),
            "--receipt",
            str(case.output),
            "--challenge-ticket",
            str(case.challenge),
            "--deployment-receipt",
            str(case.deployment),
            "--operator-integrity-binding",
            str(case.integrity_binding),
            "--trusted-key-registry",
            str(case.registry),
            "--state-root",
            str(case.state_root),
            "--expected-uid",
            str(os.geteuid()),
            "--expected-gid",
            str(os.getegid()),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "pass"
    assert TRANSCRIPT_SENTINEL not in completed.stdout
    assert proof.UPLOAD_AUTHORITY_PHRASE not in completed.stdout


def test_transport_substitution_is_rejected_even_with_valid_key_and_nonce(
    tmp_path: Path,
) -> None:
    case = _make_case(tmp_path)

    class FakeTransport(proof.DirectHttpsTransport):
        pass

    descriptor = os.open(case.audio, os.O_RDONLY)
    try:
        with pytest.raises(
            proof.PublicBlipProofError,
            match="^governed_https_transport_required$",
        ):
            proof.execute_proof(
                challenge_ticket_path=case.challenge,
                deployment_receipt_path=case.deployment,
                operator_integrity_binding_path=case.integrity_binding,
                trusted_key_registry_path=case.registry,
                operator_integrity_signing_key_path=case.signing_key,
                state_root=case.state_root,
                output_path=case.output,
                audio_descriptor=descriptor,
                audio_content_type="audio/webm",
                operator_authorization_phrase=proof.UPLOAD_AUTHORITY_PHRASE,
                expected_uid=os.geteuid(),
                expected_gid=os.getegid(),
                observed_at=NOW,
                transport=FakeTransport(),
            )
    finally:
        os.close(descriptor)
    assert not case.output.exists()
