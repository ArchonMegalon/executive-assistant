from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import sys
from types import ModuleType
from typing import Any

import pytest

from scripts.materialize_memorial_room_audio_receipt import (
    ROOM_AUDIO_CHECK_REQUIREMENTS,
)
from scripts.materialize_release_authority_status import build_status
from scripts.verify_release_authority import validate_release_authority


ROOT = Path(__file__).resolve().parents[1]


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _release_module() -> ModuleType:
    return _load_module(
        ROOT / "ea" / "scripts" / "manfred_realtime_conversation_release.py",
        "test_manfred_realtime_conversation_release_module",
    )


def _readiness_materializer() -> ModuleType:
    return _load_module(
        ROOT
        / "ea"
        / "scripts"
        / "materialize_manfred_realtime_conversation_readiness.py",
        "test_release_readiness_materializer",
    )


def _readiness_test_fixtures() -> ModuleType:
    return _load_module(
        ROOT / "tests" / "test_manfred_realtime_conversation_readiness.py",
        "test_release_readiness_fixtures",
    )


def _write_json(
    path: Path, payload: dict[str, Any], *, mode: int = 0o600
) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    path.write_bytes(raw)
    path.chmod(mode)
    return raw


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _room_receipt(
    *, generated_at: str, source_head: str, fingerprint: str, origin: str
) -> dict[str, Any]:
    return {
        "contract_name": "ea.memorial_room_audio_public_origin",
        "generated_at": generated_at,
        "generated_by": "scripts/materialize_memorial_room_audio_receipt.py",
        "proof_type": "manual_room_attestation",
        "source_git_head": source_head,
        "head_semantics": "source_state",
        "source_tree_fingerprint": fingerprint,
        "source_state_fingerprint": fingerprint,
        "source_state_fingerprint_semantics": (
            "worktree_source_files_sha256_excluding_generated_only_paths"
        ),
        "dirty_worktree": False,
        "status": "pass",
        "base_url": origin,
        "slug": "manfred",
        "require_public_origin": True,
        "runtime_source_revision_required": True,
        "runtime_source_revision": source_head,
        "reviewer": "Anna Beispiel",
        "device_label": "Lenovo X1 Carbon presentation browser",
        "speaker_label": "Bose QuietComfort presentation headset",
        "room_label": "Wien Besprechungsraum Nord",
        "checks": {key: True for key in ROOM_AUDIO_CHECK_REQUIREMENTS},
        "check_requirements": dict(ROOM_AUDIO_CHECK_REQUIREMENTS),
        "manual_attestation": {
            "attestation_id": "room-attestation-20260720-001",
            "signed_at": generated_at,
            "source": "operator_room_review",
            "ci_must_not_auto_assert": True,
        },
        "notes": (
            "Natural spoken turn, interruption, retry, first syllable, "
            "fallback text and intended room output were reviewed in person."
        ),
        "failed_codes": [],
        "gold_claim_allowed": True,
    }


def _voice_consent(*, authorized_at: str) -> dict[str, Any]:
    return {
        "tts_plugin": "unmixr_clone",
        "voice_profile_id": "${UNMIXR_VOICE_ID}",
        "voice_label": "Manfred Hoza · Unmixr-Klon",
        "lang": "de-AT",
        "rate": 1.0,
        "pitch": 0.0,
        "volume": 1.0,
        "unmixr_speaking_rate": "0%",
        "unmixr_speaking_pitch": "0%",
        "unmixr_speaking_volume": "0%",
        "tts_postprocess_profile": "memorial_voice_v1",
        "voice_name_hints": ["Manfred", "de-AT", "private"],
        "tts_plugin_voice_id": "${UNMIXR_VOICE_ID}",
        "tts_base_voice_variant": "private_clone",
        "notes": "Private operator-authorized memorial voice profile.",
        "synthetic_voice_clone_of_memorial_person": True,
        "tts_mode": "unmixr_clone",
        "consent_basis": "owner_consented_voice_clone",
        "voice_consent": {
            "status": "approved",
            "scope": [
                "clone",
                "profile_build",
                "synthesize",
                "conversation_turn",
                "realtime",
            ],
            "authorized_by": "memorial_owner",
            "authorized_at": authorized_at,
            "source_assets_reviewed": True,
            "revoked": False,
        },
        "tts_backup_candidates": {},
    }


def _release_documents(
    *, generated_at: str, source_head: str, origin: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    deployment_id = "deploy-eu1-20260720-001"
    compose_files = [
        "docker-compose.yml",
        "docker-compose.memorial.yml",
    ]
    compose_overrides = ["docker-compose.memorial.yml"]
    common = {
        "repository": "girschele/executive-assistant",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": source_head,
        "deployment_id": deployment_id,
        "deployment_id_source": "deploy_platform",
        "public_origin": origin,
        "public_origin_source": "deploy_context",
        "release_label": f"memorial-{source_head[:12]}",
        "project_mode": "MEMORIAL",
        "enabled_project_modes": ["MEMORIAL"],
        "compose_files": compose_files,
        "compose_overrides": compose_overrides,
    }
    deploy_context = {
        "contract_name": "ea.deploy_context.v1",
        "generated_at": generated_at,
        **common,
    }
    manifest = {
        "contract_name": "ea.release_manifest.v1",
        "generated_by": "scripts/materialize_release_manifest.py",
        "generated_at": generated_at,
        **common,
        "git_remote_origin": "git@github.com:girschele/executive-assistant.git",
        "source_remote_ref": "refs/remotes/origin/main",
        "source_remote_ref_commit_sha": source_head,
        "source_remote_ref_evidence": "local_remote_tracking_ref",
        "source_commit_reachable_from_remote_ref": True,
        "deploy_context_generated_at": generated_at,
        "deploy_context_branch": "main",
        "deploy_context_tracking_branch": "origin/main",
        "deploy_context_commit_sha": source_head,
        "artifact_set": ["ea-api", "memorial-public-origin"],
        "dirty_worktree": False,
        "source_worktree_dirty": False,
        "source_dirty_count": 0,
        "source_dirty_files": [],
        "source_dirty_omitted_count": 0,
        "source_dirty_status_sha256": hashlib.sha256(b"").hexdigest(),
    }
    project_modes = {
        "contract_name": "ea.project_modes.v1",
        "modes": [
            {"key": "EA_CORE"},
            {"key": "MEMORIAL"},
            {"key": "PROPERTY"},
        ],
    }
    return manifest, deploy_context, project_modes


def _bundle(
    tmp_path: Path, *, evidence_age: timedelta = timedelta(0)
) -> dict[str, Any]:
    tmp_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp_path.chmod(0o700)
    module = _release_module()
    materializer = _readiness_materializer()
    fixture_source = _readiness_test_fixtures()
    now = datetime.now(UTC).replace(microsecond=0)
    generated_at = now.isoformat().replace("+00:00", "Z")
    evidence_generated_at = (now - evidence_age).isoformat().replace(
        "+00:00", "Z"
    )
    source_head = materializer.resolve_source_state_head(materializer.REPO_ROOT)
    fingerprint = materializer.resolve_source_worktree_fingerprint(
        materializer.REPO_ROOT
    )
    assert len(source_head) == 40
    assert len(fingerprint) == 64
    # Keep this synthetic bundle internally source-stable even when another
    # agent edits the shared worktree while the test is running.
    materializer.resolve_source_state_head = lambda _root: source_head
    materializer.resolve_source_worktree_fingerprint = (
        lambda _root: fingerprint
    )
    origin = "https://memorial.example.com"

    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir(mode=0o700)
    evidence_payloads = fixture_source._ready_evidence_payloads(
        materializer, generated_at=evidence_generated_at
    )
    evidence_payloads[
        "memorial_room_audio_public_origin.generated.json"
    ] = _room_receipt(
        generated_at=evidence_generated_at,
        source_head=source_head,
        fingerprint=fingerprint,
        origin=origin,
    )
    fixture_source._write_evidence_payloads(
        evidence_root, evidence_payloads
    )
    for name in evidence_payloads:
        (evidence_root / name).chmod(0o600)

    readiness_path = tmp_path / "inputs" / "readiness.json"
    readiness_path.parent.mkdir(mode=0o700)
    readiness = (
        materializer.materialize_manfred_realtime_conversation_readiness(
            receipt_path=readiness_path,
            generated_at=generated_at,
            refresh=True,
            evidence_root=evidence_root,
        )
    )
    readiness_path.chmod(0o600)
    assert readiness["status"] == "ready_for_realtime_conversation_review"
    assert readiness["stt"]
    assert readiness["tts"]
    assert readiness["room_audio_attestation"]
    assert readiness["input_evidence"]

    voice_path = tmp_path / "private" / "manfred" / "tts_voice.json"
    _write_json(
        voice_path,
        _voice_consent(
            authorized_at=(now - timedelta(days=1))
            .isoformat()
            .replace("+00:00", "Z")
        ),
    )
    manifest, deploy_context, project_modes = _release_documents(
        generated_at=generated_at,
        source_head=source_head,
        origin=origin,
    )
    manifest_path = tmp_path / "release" / "release_manifest.json"
    deploy_context_path = tmp_path / "release" / "deploy_context.json"
    project_modes_path = tmp_path / "release" / "project_modes.json"
    _write_json(manifest_path, manifest)
    _write_json(deploy_context_path, deploy_context)
    _write_json(project_modes_path, project_modes)
    assert validate_release_authority(
        release_manifest=manifest,
        project_modes=project_modes,
    ) == []

    authority_status = build_status(
        release_manifest_path=manifest_path,
        deploy_context_path=deploy_context_path,
        project_modes_path=project_modes_path,
        generated_at=generated_at,
    )
    assert authority_status["state"] == "clear"
    assert authority_status["gate"]["status"] == "pass"
    assert authority_status["deploy_context_gate"]["status"] == "pass"
    authority_path = tmp_path / "release" / "release_authority_status.json"
    _write_json(authority_path, authority_status)

    output_parent = tmp_path / "output"
    output_parent.mkdir(mode=0o700)
    output_path = output_parent / "conversation-release.json"
    common = {
        "readiness_receipt_path": readiness_path,
        "readiness_evidence_root": evidence_root,
        "room_receipt_path": (
            evidence_root
            / "memorial_room_audio_public_origin.generated.json"
        ),
        "tts_voice_path": voice_path,
        "release_manifest_path": manifest_path,
        "release_authority_status_path": authority_path,
        "project_modes_path": project_modes_path,
        "expected_source_git_head": source_head,
        "expected_source_state_fingerprint": fingerprint,
        "now": now,
    }
    return {
        "module": module,
        "now": now,
        "generated_at": generated_at,
        "source_head": source_head,
        "fingerprint": fingerprint,
        "origin": origin,
        "output_path": output_path,
        "common": common,
        "evidence_payloads": evidence_payloads,
        "readiness": readiness,
        "deploy_context_path": deploy_context_path,
    }


def _materialize(bundle: dict[str, Any]) -> dict[str, Any]:
    return bundle["module"].materialize_manfred_realtime_conversation_release(
        output_path=bundle["output_path"],
        generated_at=bundle["generated_at"],
        **bundle["common"],
    )


def _rewrite(path: Path, mutate) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    _write_json(path, payload)
    return payload


def _rematerialize_readiness(bundle: dict[str, Any]) -> None:
    common = bundle["common"]
    materializer = _readiness_materializer()
    materializer.resolve_source_state_head = (
        lambda _root: bundle["source_head"]
    )
    materializer.resolve_source_worktree_fingerprint = (
        lambda _root: bundle["fingerprint"]
    )
    receipt = materializer.materialize_manfred_realtime_conversation_readiness(
        receipt_path=common["readiness_receipt_path"],
        generated_at=bundle["generated_at"],
        refresh=True,
        evidence_root=common["readiness_evidence_root"],
    )
    common["readiness_receipt_path"].chmod(0o600)
    assert receipt["status"] == "ready_for_realtime_conversation_review"


def test_release_aggregates_explicitly_bound_prerequisites_without_overclaim(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle = _bundle(tmp_path)
    module = bundle["module"]
    canonical_calls = 0
    original_validate = module.validate_release_authority

    def counted_validate(**kwargs):
        nonlocal canonical_calls
        canonical_calls += 1
        return original_validate(**kwargs)

    monkeypatch.setattr(module, "validate_release_authority", counted_validate)
    receipt = _materialize(bundle)

    assert canonical_calls == 1
    assert receipt["status"] == "pass"
    assert receipt["conversation_prerequisites_pass"] is True
    assert receipt["release_context_verified"] is True
    assert receipt["project_mode"] == "MEMORIAL"
    assert receipt["enabled_project_modes"] == ["MEMORIAL"]
    assert receipt["source_git_head"] == bundle["source_head"]
    assert receipt["deployment_revision"] == bundle["source_head"]
    assert receipt["public_origin"] == bundle["origin"]
    assert receipt["effective_expires_at"] == (
        bundle["now"] + timedelta(hours=24)
    ).isoformat().replace("+00:00", "Z")
    rendered = json.dumps(receipt, sort_keys=True)
    assert "whole_project" not in rendered
    assert "goal_completion" not in rendered
    assert "conversation_release_allowed" not in rendered
    assert "runtime_enablement_allowed" not in rendered
    assert "release_authority_verified" not in rendered
    assert "root_permit" not in rendered
    assert "gold" not in rendered.lower()
    assert "operator_acceptance" not in rendered
    assert "voice_authority_receipt" not in rendered

    direct_paths = {
        "readiness_receipt": bundle["common"]["readiness_receipt_path"],
        "room_audio_receipt": bundle["common"]["room_receipt_path"],
        "tts_voice_consent": bundle["common"]["tts_voice_path"],
        "release_manifest": bundle["common"]["release_manifest_path"],
        "release_authority_status": bundle["common"][
            "release_authority_status_path"
        ],
        "project_modes": bundle["common"]["project_modes_path"],
    }
    assert receipt["raw_input_sha256"] == {
        key: _sha(path) for key, path in direct_paths.items()
    }
    expected_evidence_hashes = {
        key: _sha(
            bundle["common"]["readiness_evidence_root"] / receipt_name
        )
        for key, (receipt_name, _contract) in (
            module.readiness_materializer.EVIDENCE_RECEIPTS.items()
        )
    }
    assert (
        receipt["readiness_evidence_raw_sha256"]
        == expected_evidence_hashes
    )
    assert stat.S_IMODE(bundle["output_path"].stat().st_mode) == 0o600
    assert module.verify_manfred_realtime_conversation_release(
        receipt_path=bundle["output_path"],
        **bundle["common"],
    ) == {
        "contract_name": (
            "ea.manfred_realtime_conversation_release.verify.v1"
        ),
        "status": "pass",
        "issues": [],
    }


def test_release_api_and_cli_require_explicit_exact_source_binding(
) -> None:
    module = _release_module()
    valid_head = "a" * 40
    valid_fingerprint = "b" * 64

    with pytest.raises(TypeError, match="expected_source_git_head"):
        module.materialize_manfred_realtime_conversation_release()
    with pytest.raises(TypeError, match="expected_source_git_head"):
        module.verify_manfred_realtime_conversation_release()
    with pytest.raises(SystemExit):
        module._parser().parse_args([])

    for head, fingerprint, expected in (
        ("", "", "explicit_source_binding_required"),
        (
            f" {valid_head}",
            valid_fingerprint,
            "explicit_source_binding_not_exact",
        ),
    ):
        with pytest.raises(module.ReleaseContractError, match=expected):
            module._source_binding(
                expected_source_git_head=head,
                expected_source_state_fingerprint=fingerprint,
            )


def test_release_canonical_readiness_explicit_bindings_are_thread_isolated(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    module = bundle["module"]
    common = bundle["common"]
    source_head = bundle["source_head"]
    fingerprint = bundle["fingerprint"]
    wrong_head = ("0" if source_head[0] != "0" else "1") + source_head[1:]

    assert not hasattr(module, "_CANONICAL_READINESS_LOCK")

    def canonical(expected_head: str) -> tuple[str, str, tuple[str, ...]]:
        result = (
            module.readiness_verifier.verify_manfred_realtime_conversation_readiness(
                common["readiness_receipt_path"],
                evidence_root=common["readiness_evidence_root"],
                expected_source_git_head=expected_head,
                expected_source_state_fingerprint=fingerprint,
            )
        )
        return "canonical", result["status"], tuple(result["issues"])

    def aggregator(expected_head: str) -> tuple[str, str, tuple[str, ...]]:
        try:
            module._canonical_readiness_pass(
                receipt_path=common["readiness_receipt_path"],
                evidence_root=common["readiness_evidence_root"],
                expected_head=expected_head,
                expected_fingerprint=fingerprint,
            )
        except module.ReleaseContractError as exc:
            return "aggregator", "fail", (exc.code,)
        return "aggregator", "pass", ()

    jobs = [
        (canonical, source_head),
        (canonical, wrong_head),
        (aggregator, source_head),
        (aggregator, wrong_head),
    ] * 6
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(call, head) for call, head in jobs]
        results = [future.result() for future in futures]

    for (call, head), (_kind, status, issues) in zip(jobs, results):
        if head == source_head:
            assert status == "pass"
            assert issues == ()
        elif call is canonical:
            assert status == "fail"
            assert "manfred_realtime_source_head_stale" in issues
        else:
            assert status == "fail"
            assert issues == ("canonical_readiness_verifier_not_pass",)


def test_release_rejects_readiness_and_bound_evidence_tamper(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    readiness_path = bundle["common"]["readiness_receipt_path"]
    _rewrite(
        readiness_path,
        lambda payload: payload.__setitem__(
            "realtime_conversation_claim_allowed", True
        ),
    )
    with pytest.raises(
        bundle["module"].ReleaseContractError,
        match="canonical_readiness_verifier_not_pass",
    ):
        _materialize(bundle)

    bundle = _bundle(tmp_path / "evidence-tamper")
    room_path = bundle["common"]["room_receipt_path"]
    _rewrite(
        room_path,
        lambda payload: payload["checks"].__setitem__(
            "retry_path_confirmed", False
        ),
    )
    with pytest.raises(
        bundle["module"].ReleaseContractError,
        match="canonical_readiness_verifier_not_pass",
    ):
        _materialize(bundle)


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda voice: voice["voice_consent"].__setitem__(
                "revoked", True
            ),
            "voice_consent_not_current",
        ),
        (
            lambda voice: voice["voice_consent"].__setitem__(
                "scope", ["clone", "synthesize"]
            ),
            "voice_consent_not_current",
        ),
        (
            lambda voice: voice.__setitem__("tts_plugin", "openvoice"),
            "voice_unmixr_clone_contract_mismatch",
        ),
        (
            lambda voice: voice.__setitem__(
                "synthetic_voice_clone_of_memorial_person", False
            ),
            "voice_synthetic_clone_disclosure_missing",
        ),
    ],
)
def test_release_rejects_revoked_or_weakened_private_voice_consent(
    tmp_path: Path, mutate, expected: str
) -> None:
    bundle = _bundle(tmp_path)
    _rewrite(bundle["common"]["tts_voice_path"], mutate)
    with pytest.raises(
        bundle["module"].ReleaseContractError, match=expected
    ):
        _materialize(bundle)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("voice_profile_id", "different_person_private_voice"),
        ("tts_plugin_voice_id", "${OTHER_PERSON_VOICE_ID}"),
        ("voice_label", "Different Person · Unmixr-Klon"),
        ("lang", "de-DE"),
    ],
)
def test_release_rejects_non_manfred_voice_identity(
    tmp_path: Path, field: str, value: str
) -> None:
    bundle = _bundle(tmp_path)
    _rewrite(
        bundle["common"]["tts_voice_path"],
        lambda voice: voice.__setitem__(field, value),
    )
    with pytest.raises(
        bundle["module"].ReleaseContractError,
        match="voice_manfred_identity_mismatch",
    ):
        _materialize(bundle)


def test_release_effective_expiry_uses_earliest_bound_evidence_expiry(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path, evidence_age=timedelta(hours=23))

    receipt = _materialize(bundle)

    assert receipt["effective_expires_at"] == (
        bundle["now"] + timedelta(hours=1)
    ).isoformat().replace("+00:00", "Z")


def test_release_rejects_room_attestation_signed_before_observation(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    stale_signed_at = (bundle["now"] - timedelta(days=365)).isoformat().replace(
        "+00:00", "Z"
    )
    _rewrite(
        bundle["common"]["room_receipt_path"],
        lambda room: room["manual_attestation"].__setitem__(
            "signed_at", stale_signed_at
        ),
    )
    _rematerialize_readiness(bundle)

    with pytest.raises(
        bundle["module"].ReleaseContractError,
        match="room_attestation_time_invalid",
    ):
        _materialize(bundle)


def test_release_rejects_non_operator_room_attestation_source(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    _rewrite(
        bundle["common"]["room_receipt_path"],
        lambda room: room["manual_attestation"].__setitem__(
            "source", "ci_generated"
        ),
    )
    _rematerialize_readiness(bundle)

    with pytest.raises(
        bundle["module"].ReleaseContractError,
        match="room_manual_attestation_invalid",
    ):
        _materialize(bundle)


def test_release_rejects_backdated_final_receipt_timestamp(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)

    with pytest.raises(
        bundle["module"].ReleaseContractError,
        match="release_generated_at_not_current",
    ):
        bundle[
            "module"
        ].materialize_manfred_realtime_conversation_release(
            output_path=bundle["output_path"],
            generated_at="2000-01-01T00:00:00Z",
            **bundle["common"],
        )


def test_release_rejects_runtime_incompatible_room_binding_after_reaggregation(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    room_path = bundle["common"]["room_receipt_path"]
    _rewrite(
        room_path,
        lambda payload: payload.__setitem__(
            "runtime_source_revision", "b" * 40
        ),
    )
    _rematerialize_readiness(bundle)
    with pytest.raises(
        bundle["module"].ReleaseContractError,
        match="room_source_or_runtime_binding_mismatch",
    ):
        _materialize(bundle)


def test_release_rejects_non_authoritative_or_divergent_release_status(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    status_path = bundle["common"]["release_authority_status_path"]
    _rewrite(
        status_path,
        lambda payload: payload["gate"].__setitem__("status", "fail"),
    )
    with pytest.raises(
        bundle["module"].ReleaseContractError,
        match="release_authority_status_not_exact_pass",
    ):
        _materialize(bundle)

    bundle = _bundle(tmp_path / "local-id")
    manifest_path = bundle["common"]["release_manifest_path"]
    _rewrite(
        manifest_path,
        lambda payload: payload.update(
            {
                "deployment_id": "local-fallback",
                "deployment_id_source": "local_fallback",
            }
        ),
    )
    with pytest.raises(
        bundle["module"].ReleaseContractError,
        match="canonical_release_authority_not_pass",
    ):
        _materialize(bundle)


def test_release_expires_at_canonical_readiness_freshness_boundary(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    bundle["common"]["now"] = bundle["now"] + timedelta(hours=24)
    with pytest.raises(
        bundle["module"].ReleaseContractError, match="readiness_expired"
    ):
        _materialize(bundle)


@pytest.mark.parametrize(
    ("path_key", "mode", "expected"),
    [
        ("tts_voice_path", 0o644, "tts_voice_consent_permissions_not_private"),
        ("release_manifest_path", 0o666, "release_manifest_permissions_unsafe"),
    ],
)
def test_release_rejects_unsafe_input_permissions(
    tmp_path: Path, path_key: str, mode: int, expected: str
) -> None:
    bundle = _bundle(tmp_path)
    bundle["common"][path_key].chmod(mode)
    with pytest.raises(
        bundle["module"].ReleaseContractError, match=expected
    ):
        _materialize(bundle)


def test_release_rejects_symlink_and_input_change_before_commit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle = _bundle(tmp_path)
    voice_path = bundle["common"]["tts_voice_path"]
    target = voice_path.with_name("target.json")
    voice_path.rename(target)
    voice_path.symlink_to(target.name)
    with pytest.raises(
        bundle["module"].ReleaseContractError,
        match="tts_voice_consent_path_unsafe_or_missing",
    ):
        _materialize(bundle)

    bundle = _bundle(tmp_path / "input-race")
    module = bundle["module"]
    original_assert = module._assert_inputs_unchanged
    raced = False

    def race_once(snapshots):
        nonlocal raced
        if not raced:
            raced = True
            _rewrite(
                bundle["common"]["tts_voice_path"],
                lambda payload: payload["voice_consent"].__setitem__(
                    "revoked", True
                ),
            )
        return original_assert(snapshots)

    monkeypatch.setattr(module, "_assert_inputs_unchanged", race_once)
    with pytest.raises(
        module.ReleaseContractError,
        match="tts_voice_consent_changed_before_commit",
    ):
        _materialize(bundle)
    assert not bundle["output_path"].exists()


def test_atomic_output_rejects_parent_replacement_race(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle = _bundle(tmp_path)
    module = bundle["module"]
    output_parent = bundle["output_path"].parent
    moved_parent = output_parent.with_name("output-original")
    original_location = module._output_location
    location_calls = 0

    def replace_parent(path: Path):
        nonlocal location_calls
        location_calls += 1
        if location_calls == 2:
            output_parent.rename(moved_parent)
            output_parent.mkdir(mode=0o700)
        return original_location(path)

    monkeypatch.setattr(module, "_output_location", replace_parent)
    with pytest.raises(
        module.ReleaseContractError,
        match="output_parent_changed_during_commit",
    ):
        _materialize(bundle)
    assert not bundle["output_path"].exists()
    assert (moved_parent / bundle["output_path"].name).is_file()


def test_verifier_rejects_output_tamper_and_input_revocation(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    _materialize(bundle)
    module = bundle["module"]
    _rewrite(
        bundle["output_path"],
        lambda payload: payload.__setitem__("deployment_id", "tampered"),
    )
    verification = module.verify_manfred_realtime_conversation_release(
        receipt_path=bundle["output_path"],
        **bundle["common"],
    )
    assert verification["status"] == "fail"
    assert verification["issues"] == ["release_receipt_content_mismatch"]

    _materialize(bundle)
    _rewrite(
        bundle["common"]["tts_voice_path"],
        lambda payload: payload["voice_consent"].__setitem__(
            "revoked", True
        ),
    )
    verification = module.verify_manfred_realtime_conversation_release(
        receipt_path=bundle["output_path"],
        **bundle["common"],
    )
    assert verification["status"] == "fail"
    assert verification["issues"] == ["voice_consent_not_current"]
