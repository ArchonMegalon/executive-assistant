from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets

import pytest

from app.services import memorial_voice_preview_authority as authority


SOURCE_REVISION = "a" * 40
DEPLOYMENT_ID = f"ea-manfred-candidate-prod001-{SOURCE_REVISION[:12]}"
PUBLIC_ORIGIN = "https://myexternalbrain.com"
GENERATED_AT = "2026-07-20T12:00:00Z"


@pytest.fixture(autouse=True)
def _restore_test_directory_permissions(tmp_path: Path):
    yield
    for current, directories, _files in os.walk(tmp_path):
        for directory in directories:
            candidate = Path(current) / directory
            if not candidate.is_symlink():
                candidate.chmod(0o700)
    tmp_path.chmod(0o700)


def _encoded(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _atomic_write_immutable(path: Path, raw: bytes) -> None:
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    )
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise OSError("immutable_fixture_short_write")
            offset += written
        os.fchmod(descriptor, 0o440)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _write_packet(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    *,
    public_origin: str = PUBLIC_ORIGIN,
    deployment_id: str = DEPLOYMENT_ID,
    configure_env: bool = True,
) -> dict[str, Path]:
    root.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    project_modes = {
        "contract_name": "ea.project_modes",
        "generated_at": GENERATED_AT,
        "generated_by": "scripts/prepare_manfred_memorial_candidate.py",
        "source_git_head": SOURCE_REVISION,
        "head_semantics": "candidate_release",
        "modes": [{"key": "MEMORIAL"}, {"key": "PROPERTY"}],
    }
    deploy_context = {
        "contract_name": "ea.deploy_context.v1",
        "generated_at": GENERATED_AT,
        "generated_by": "scripts/prepare_manfred_memorial_candidate.py",
        "repository": "EA",
        "deployment_id": deployment_id,
        "deployment_id_source": "explicit",
        "public_origin": public_origin,
        "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": SOURCE_REVISION,
        "release_label": deployment_id,
        "project_mode": "MEMORIAL",
        "enabled_project_modes": ["MEMORIAL"],
        "compose_files": [
            "deploy/manfred-memorial/docker-compose.candidate.yml"
        ],
        "compose_overrides": [],
    }
    release_manifest = {
        "contract_name": "ea.release_manifest.v1",
        "generated_at": GENERATED_AT,
        "generated_by": "scripts/prepare_manfred_memorial_candidate.py",
        "repository": "EA",
        "branch": "main",
        "tracking_branch": "origin/main",
        "commit_sha": SOURCE_REVISION,
        "source_head_commit_sha": SOURCE_REVISION,
        "source_head_matches_candidate_commit": True,
        "source_remote_ref": "refs/remotes/origin/main",
        "source_remote_ref_commit_sha": SOURCE_REVISION,
        "source_remote_ref_evidence": "local_remote_tracking_ref",
        "source_commit_reachable_from_remote_ref": True,
        "git_remote_origin": authority._OFFICIAL_REMOTE,
        "live_remote_ref": "refs/heads/main",
        "live_remote_ref_commit_sha": SOURCE_REVISION,
        "live_remote_ref_evidence": authority._LIVE_REMOTE_EVIDENCE,
        "dirty_worktree": False,
        "source_worktree_dirty": False,
        "source_dirty_count": 0,
        "source_dirty_files": [],
        "source_dirty_omitted_count": 0,
        "source_dirty_status_sha256": "",
        "deploy_context_generated_at": GENERATED_AT,
        "deploy_context_branch": "main",
        "deploy_context_tracking_branch": "origin/main",
        "deploy_context_commit_sha": SOURCE_REVISION,
        "deployment_id": deployment_id,
        "deployment_id_source": "explicit",
        "public_origin": public_origin,
        "public_origin_source": "EA_PUBLIC_APP_BASE_URL",
        "project_mode": "MEMORIAL",
        "enabled_project_modes": ["MEMORIAL"],
        "compose_files": [
            "deploy/manfred-memorial/docker-compose.candidate.yml"
        ],
        "compose_overrides": [],
        "artifact_set": ["public_memorials/manfred/memorial.json"],
        "release_label": deployment_id,
    }
    container_paths = {
        name: f"{authority._PACKAGED_CONTAINER_ROOT}/{filename}"
        for name, (_, filename) in authority._DOCUMENTS.items()
    }
    container_paths["receipt"] = (
        f"{authority._PACKAGED_CONTAINER_ROOT}/{authority._RECEIPT_FILENAME}"
    )
    release_status = {
        "contract_name": "ea.release_authority_status.v1",
        "state": "clear",
        "authority_posture": "authoritative_runtime",
        "issues": [],
        "commit_sha": SOURCE_REVISION,
        "deployment_id": deployment_id,
        "manifest_path": container_paths["release_manifest"],
        "deploy_context_path": container_paths["deploy_context"],
        "project_modes_path": container_paths["project_modes"],
        "candidate_runtime": True,
        "promotion_authority": False,
        "gate": {
            "status": "pass",
            "issues": [],
            "manifest_path": container_paths["release_manifest"],
            "deploy_context_path": container_paths["deploy_context"],
            "project_modes_path": container_paths["project_modes"],
        },
    }
    payloads = {
        "deploy_context": deploy_context,
        "project_modes": project_modes,
        "release_manifest": release_manifest,
        "release_status": release_status,
    }
    paths = {
        name: root / filename
        for name, (_, filename) in authority._DOCUMENTS.items()
    }
    document_evidence: dict[str, dict[str, object]] = {}
    for name, payload in payloads.items():
        raw = _encoded(payload)
        _atomic_write_immutable(paths[name], raw)
        document_evidence[name] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        }
    receipt = {
        "schema": "ea.manfred_candidate_release_authority.v1",
        "status": "pass",
        "generated_at": GENERATED_AT,
        "commit_sha": SOURCE_REVISION,
        "image_id": "sha256:" + "b" * 64,
        "image_revision": SOURCE_REVISION,
        "deployment_id": deployment_id,
        "project_mode": "MEMORIAL",
        "enabled_project_modes": ["MEMORIAL"],
        "container_paths": container_paths,
        "documents": document_evidence,
        "runtime_authority_state": "clear",
        "runtime_authority_posture": "authoritative_runtime",
        "promotion_authority": False,
        "secret_material_recorded": False,
    }
    paths["receipt"] = root / authority._RECEIPT_FILENAME
    _atomic_write_immutable(paths["receipt"], _encoded(receipt))
    root.chmod(0o550)
    if configure_env:
        for name, (environment_name, _) in authority._DOCUMENTS.items():
            monkeypatch.setenv(environment_name, str(paths[name]))
        monkeypatch.setenv("EA_SOURCE_REVISION", SOURCE_REVISION)
        monkeypatch.setenv("EA_MEMORIAL_DEPLOYMENT_ID", deployment_id)
        monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", "MEMORIAL")
        monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", "MEMORIAL")
    return paths


def _rewrite_document_and_rebind_receipt(
    paths: dict[str, Path],
    *,
    name: str,
    payload: dict[str, object],
) -> None:
    root = paths["receipt"].parent
    root.chmod(0o700)
    raw = _encoded(payload)
    try:
        _atomic_write_immutable(paths[name], raw)
        receipt = json.loads(paths["receipt"].read_text(encoding="utf-8"))
        receipt["documents"][name] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        }
        _atomic_write_immutable(paths["receipt"], _encoded(receipt))
    finally:
        root.chmod(0o550)


def test_authority_loader_accepts_live_mount_path_but_exact_packaged_candidate_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "data" / "memorial_data" / "release-authority"
    paths = _write_packet(monkeypatch, root)

    context = authority.validated_memorial_voice_preview_release_context()

    assert context == authority.MemorialVoicePreviewReleaseContext(
        source_revision=SOURCE_REVISION,
        deployment_id=DEPLOYMENT_ID,
        public_origin=PUBLIC_ORIGIN,
    )
    assert authority._PACKAGED_CONTAINER_ROOT == "/data/release-authority"
    assert root.stat().st_mode & 0o777 == 0o550
    assert all(path.stat().st_mode & 0o777 == 0o440 for path in paths.values())


@pytest.mark.parametrize(
    ("mode", "expected_error"),
    [
        (0o750, "preview_release_document_root_mutable"),
        (0o570, "preview_release_document_root_untrusted"),
        (0o552, "preview_release_document_root_untrusted"),
    ],
)
def test_authority_loader_rejects_any_writable_authority_root_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: int,
    expected_error: str,
) -> None:
    root = tmp_path / "release-authority"
    _write_packet(monkeypatch, root)
    root.chmod(mode)

    with pytest.raises(
        authority.MemorialVoicePreviewAuthorityError,
        match=expected_error,
    ):
        authority.validated_memorial_voice_preview_release_context()


@pytest.mark.parametrize("mode", [0o640, 0o460, 0o442])
def test_authority_loader_rejects_any_writable_document_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: int,
) -> None:
    paths = _write_packet(monkeypatch, tmp_path / "release-authority")
    paths["release_manifest"].chmod(mode)

    with pytest.raises(
        authority.MemorialVoicePreviewAuthorityError,
        match="preview_release_document_untrusted",
    ):
        authority.validated_memorial_voice_preview_release_context()


@pytest.mark.parametrize(
    "origin",
    [
        "https://localhost",
        "https://memorial.local",
        "https://memorial.internal",
        "https://memorial.home.arpa",
        "https://memorial.test",
        "https://127.0.0.1",
        "https://8.8.8.8",
        "https://singlelabel",
        "https://example.com",
        "https://voice.example.com",
        "https://myexternalbrain.com/",
        "http://myexternalbrain.com",
        "https://www.myexternalbrain.com",
    ],
)
def test_authority_loader_rejects_noncanonical_or_nonpublic_origin(
    origin: str,
) -> None:
    with pytest.raises(
        authority.MemorialVoicePreviewAuthorityError,
        match="preview_release_public_origin",
    ):
        authority._canonical_public_origin(origin)


def test_authority_loader_rejects_intermediate_symlink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real"
    root = real_parent / "release-authority"
    paths = _write_packet(monkeypatch, root)
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    for name, (environment_name, _) in authority._DOCUMENTS.items():
        monkeypatch.setenv(
            environment_name,
            str(linked_parent / "release-authority" / paths[name].name),
        )

    with pytest.raises(
        authority.MemorialVoicePreviewAuthorityError,
        match="preview_release_document_root_unavailable",
    ):
        authority.validated_memorial_voice_preview_release_context()


def test_authority_loader_rejects_root_path_swap_during_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "authority" / "release-authority"
    _write_packet(monkeypatch, root)
    replacement = tmp_path / "authority" / "replacement"
    _write_packet(monkeypatch, replacement, configure_env=False)
    original_reader = authority._read_document_at
    calls = 0

    def swapping_reader(
        snapshot: authority._AuthorityRootSnapshot,
        filename: str,
    ) -> tuple[dict[str, object], dict[str, object]]:
        nonlocal calls
        result = original_reader(snapshot, filename)
        calls += 1
        if calls == 1:
            old = root.with_name("release-authority-old")
            os.rename(root, old)
            os.rename(replacement, root)
        return result

    monkeypatch.setattr(authority, "_read_document_at", swapping_reader)

    with pytest.raises(
        authority.MemorialVoicePreviewAuthorityError,
        match="preview_release_document_root_changed",
    ):
        authority.validated_memorial_voice_preview_release_context()


def test_authority_loader_never_accepts_environment_identity_over_packet(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "release-authority"
    paths = _write_packet(monkeypatch, root)
    manifest = json.loads(paths["release_manifest"].read_text(encoding="utf-8"))
    manifest["deployment_id"] = "local-fallback"
    manifest["deployment_id_source"] = "local_fallback"
    root.chmod(0o700)
    try:
        _atomic_write_immutable(paths["release_manifest"], _encoded(manifest))
    finally:
        root.chmod(0o550)
    monkeypatch.setenv("EA_DEPLOYMENT_ID", DEPLOYMENT_ID)
    monkeypatch.setenv("EA_PUBLIC_APP_BASE_URL", PUBLIC_ORIGIN)

    with pytest.raises(
        authority.MemorialVoicePreviewAuthorityError,
        match="preview_release_authority_binding_invalid",
    ):
        authority.validated_memorial_voice_preview_release_context()


@pytest.mark.parametrize(
    "runtime_deployment_id",
    ["", "ea-manfred-candidate-other-aaaaaaaaaaaa"],
)
def test_authority_loader_requires_exact_runtime_deployment_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runtime_deployment_id: str,
) -> None:
    _write_packet(monkeypatch, tmp_path / "release-authority")
    if runtime_deployment_id:
        monkeypatch.setenv(
            "EA_MEMORIAL_DEPLOYMENT_ID",
            runtime_deployment_id,
        )
    else:
        monkeypatch.delenv("EA_MEMORIAL_DEPLOYMENT_ID", raising=False)

    with pytest.raises(
        authority.MemorialVoicePreviewAuthorityError,
        match="preview_release_authority_binding_invalid",
    ):
        authority.validated_memorial_voice_preview_release_context()


@pytest.mark.parametrize(
    ("primary_mode", "enabled_modes"),
    [
        (None, None),
        ("memorial", "MEMORIAL"),
        ("MEMORIAL", "memorial"),
        ("MEMORIAL", "MEMORIAL,PROPERTY"),
        ("MEMORIAL", "MEMORIAL,MEMORIAL"),
        ("EA_CORE", "MEMORIAL"),
    ],
)
def test_authority_loader_requires_exact_memorial_only_runtime_topology(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    primary_mode: str | None,
    enabled_modes: str | None,
) -> None:
    _write_packet(monkeypatch, tmp_path / "release-authority")
    if primary_mode is None:
        monkeypatch.delenv("EA_DEPLOY_PRIMARY_MODE", raising=False)
    else:
        monkeypatch.setenv("EA_DEPLOY_PRIMARY_MODE", primary_mode)
    if enabled_modes is None:
        monkeypatch.delenv("EA_DEPLOY_ENABLED_MODES", raising=False)
    else:
        monkeypatch.setenv("EA_DEPLOY_ENABLED_MODES", enabled_modes)

    with pytest.raises(
        authority.MemorialVoicePreviewAuthorityError,
        match="preview_release_authority_binding_invalid",
    ):
        authority.validated_memorial_voice_preview_release_context()


@pytest.mark.parametrize(
    "mutation",
    [
        {"issues": ["deployment_id_local_fallback"]},
        {
            "diagnostics": {
                "release": {
                    "gate": {"authority_posture": "local_only_deploy_id"}
                }
            }
        },
    ],
)
def test_authority_loader_recursively_rejects_local_only_blockers_even_when_rebound(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: dict[str, object],
) -> None:
    paths = _write_packet(monkeypatch, tmp_path / "release-authority")
    status = json.loads(paths["release_status"].read_text(encoding="utf-8"))
    status.update(mutation)
    _rewrite_document_and_rebind_receipt(
        paths,
        name="release_status",
        payload=status,
    )

    with pytest.raises(
        authority.MemorialVoicePreviewAuthorityError,
        match="preview_release_authority_binding_invalid",
    ):
        authority.validated_memorial_voice_preview_release_context()


def test_authority_loader_rejects_nested_gate_issue_even_with_clear_top_level(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = _write_packet(monkeypatch, tmp_path / "release-authority")
    status = json.loads(paths["release_status"].read_text(encoding="utf-8"))
    status["gate"]["issues"] = [
        {"release_authority": {"reason": "deployment-id-local-fallback"}}
    ]
    _rewrite_document_and_rebind_receipt(
        paths,
        name="release_status",
        payload=status,
    )

    with pytest.raises(
        authority.MemorialVoicePreviewAuthorityError,
        match="preview_release_authority_binding_invalid",
    ):
        authority.validated_memorial_voice_preview_release_context()


def test_authority_loader_rejects_property_in_conversation_enabled_topology(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = _write_packet(monkeypatch, tmp_path / "release-authority")
    for name in ("deploy_context", "release_manifest"):
        payload = json.loads(paths[name].read_text(encoding="utf-8"))
        payload["enabled_project_modes"] = ["MEMORIAL", "PROPERTY"]
        _rewrite_document_and_rebind_receipt(
            paths,
            name=name,
            payload=payload,
        )
    receipt = json.loads(paths["receipt"].read_text(encoding="utf-8"))
    receipt["enabled_project_modes"] = ["MEMORIAL", "PROPERTY"]
    root = paths["receipt"].parent
    root.chmod(0o700)
    try:
        _atomic_write_immutable(paths["receipt"], _encoded(receipt))
    finally:
        root.chmod(0o550)

    with pytest.raises(
        authority.MemorialVoicePreviewAuthorityError,
        match="preview_release_authority_binding_invalid",
    ):
        authority.validated_memorial_voice_preview_release_context()
