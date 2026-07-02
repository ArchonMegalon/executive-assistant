from __future__ import annotations

import json
from pathlib import Path
import pytest

from scripts.materialize_teable_env_recovery_proof import build_teable_env_recovery_proof
from scripts.verify_teable_env_recovery_proof import verify
import scripts.materialize_teable_env_recovery_proof as proof_module
import scripts.verify_teable_env_recovery_proof as verifier_module


def test_materialize_teable_env_recovery_proof_sanitizes_runtime_paths(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / ".codex-studio/published/teable_env_recovery_proof.generated.json"
    raw_secret_path = tmp_path / "config" / "secret-provider.json"
    raw_secret_path.parent.mkdir(parents=True, exist_ok=True)
    raw_secret_path.write_text('{"api_key":"super-secret"}', encoding="utf-8")
    monkeypatch.setenv("TEABLE_API_KEY", "seeded-teable-key")
    monkeypatch.setattr(proof_module, "_git_head", lambda path: "fresh-head")
    monkeypatch.setattr(proof_module, "_source_fingerprint", lambda path: "source-fingerprint")
    monkeypatch.setattr(verifier_module, "_git_head", lambda path=tmp_path: "fresh-head")
    monkeypatch.setattr(verifier_module, "_source_fingerprint", lambda path=tmp_path: "source-fingerprint")
    monkeypatch.setattr(
        proof_module.sync_env_to_teable,
        "discover_table_id",
        lambda **kwargs: "tbl_live_recovery",
    )
    monkeypatch.setattr(
        proof_module.sync_env_to_teable,
        "recover_from_teable",
        lambda **kwargs: {
            "status": "recovered",
            "recovery_proof": {
                "contract_name": "ea.teable_env_recovery_proof.v1",
                "host_profile": "ea-prod",
                "secret_values_redacted": True,
                "env_files": [
                    {
                        "scope": "ea_root",
                        "path": str(tmp_path / ".env"),
                        "restored": 2,
                        "hash_verified": 2,
                        "hash_mismatch_count": 0,
                        "backup_created": False,
                        "mode": "0o600",
                    },
                    {
                        "scope": "ea_root_local",
                        "path": str(tmp_path / ".env.local"),
                        "restored": 1,
                        "hash_verified": 1,
                        "hash_mismatch_count": 0,
                        "backup_created": False,
                        "mode": "0o600",
                    },
                    {
                        "scope": "ea_service",
                        "path": str(tmp_path / "ea" / ".env"),
                        "restored": 1,
                        "hash_verified": 1,
                        "hash_mismatch_count": 0,
                        "backup_created": False,
                        "mode": "0o600",
                    },
                ],
                "referenced_files": {
                    "restored": 1,
                    "hash_verified": 1,
                    "hash_mismatch_count": 0,
                    "backup_count": 0,
                    "path_count": 1,
                    "paths": [str(raw_secret_path)],
                    "modes": [{"path": str(raw_secret_path), "mode": "0o600"}],
                },
                "verification": {
                    "status": "pass",
                    "expected_rows": 4,
                    "same_hash": 4,
                    "missing_count": 0,
                    "different_hash_count": 0,
                    "missing_secret_value_count": 0,
                    "extra_restorable_count": 0,
                },
            },
        },
    )

    receipt = build_teable_env_recovery_proof(
        root=tmp_path,
        output_path=output,
        table_name="ea_environment_secrets_recovery",
        host_profile="ea-prod",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    assert receipt["contract_name"] == "ea.teable_env_recovery_proof.v1"
    assert receipt["status"] == "pass"
    assert receipt["recovery_status"] == "recovered"
    assert receipt["fresh_host_api_key_source"] == "process_env"
    assert receipt["drill_output_removed"] is True
    assert receipt["table_discovery_mode"] == "discovered_by_name"
    assert receipt["table_id_sha256"]
    assert receipt["verification"]["status"] == "pass"
    assert all(row["path_sha256"] for row in receipt["env_files"])
    assert receipt["privacy"] == {
        "raw_paths_exposed": False,
        "raw_table_id_exposed": False,
        "raw_api_key_exposed": False,
        "secret_values_exposed": False,
    }
    serialized = json.dumps(receipt, sort_keys=True)
    assert str(raw_secret_path) not in serialized
    assert "seeded-teable-key" not in serialized
    assert "tbl_live_recovery" not in serialized
    assert verify(output, root=tmp_path) == []


def test_materialize_teable_env_recovery_proof_reads_only_teable_keys_from_env_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / ".codex-studio/published/teable_env_recovery_proof.generated.json"
    (tmp_path / ".env").write_text(
        "\n".join(
            (
                "BROKEN_SHELL_SECRET=value with spaces and ) syntax",
                "TEABLE_API_KEY=seeded-from-env-file",
                "TEABLE_BASE_URL=https://teable.example.test",
                "EA_ENV_TEABLE_TABLE_ID=tbl_from_env_file",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("TEABLE_API_KEY", raising=False)
    monkeypatch.delenv("TEABLE_BASE_URL", raising=False)
    monkeypatch.delenv("EA_ENV_TEABLE_TABLE_ID", raising=False)
    monkeypatch.setattr(proof_module, "_git_head", lambda path: "fresh-head")
    monkeypatch.setattr(proof_module, "_source_fingerprint", lambda path: "source-fingerprint")
    monkeypatch.setattr(
        proof_module.sync_env_to_teable,
        "discover_table_id",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("table id should come from targeted env file")),
    )

    def _recover_from_teable(**kwargs: object) -> dict[str, object]:
        assert kwargs["base_url"] == "https://teable.example.test"
        assert kwargs["api_key"] == "seeded-from-env-file"
        assert kwargs["table_id"] == "tbl_from_env_file"
        return {
            "status": "recovered",
            "recovery_proof": {
                "contract_name": "ea.teable_env_recovery_proof.v1",
                "host_profile": "ea-prod",
                "secret_values_redacted": True,
                "env_files": [
                    {
                        "scope": "ea_root",
                        "path": str(tmp_path / ".env"),
                        "restored": 1,
                        "hash_verified": 1,
                        "hash_mismatch_count": 0,
                        "backup_created": False,
                        "mode": "0o600",
                    },
                    {
                        "scope": "ea_root_local",
                        "path": str(tmp_path / ".env.local"),
                        "restored": 1,
                        "hash_verified": 1,
                        "hash_mismatch_count": 0,
                        "backup_created": False,
                        "mode": "0o600",
                    },
                    {
                        "scope": "ea_service",
                        "path": str(tmp_path / "ea" / ".env"),
                        "restored": 1,
                        "hash_verified": 1,
                        "hash_mismatch_count": 0,
                        "backup_created": False,
                        "mode": "0o600",
                    },
                ],
                "referenced_files": {
                    "restored": 0,
                    "hash_verified": 0,
                    "hash_mismatch_count": 0,
                    "backup_count": 0,
                    "path_count": 0,
                    "paths": [],
                    "modes": [],
                },
                "verification": {
                    "status": "pass",
                    "expected_rows": 3,
                    "same_hash": 3,
                    "missing_count": 0,
                    "different_hash_count": 0,
                    "missing_secret_value_count": 0,
                    "extra_restorable_count": 0,
                },
            },
        }

    monkeypatch.setattr(proof_module.sync_env_to_teable, "recover_from_teable", _recover_from_teable)

    receipt = build_teable_env_recovery_proof(root=tmp_path, output_path=output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    serialized = json.dumps(receipt, sort_keys=True)

    assert receipt["status"] == "pass"
    assert receipt["fresh_host_api_key_source"] == "process_env"
    assert receipt["teable_config_sources"]["api_key"] == "targeted_env_file"
    assert receipt["teable_config_sources"]["base_url"] == "targeted_env_file"
    assert receipt["teable_config_sources"]["table_id"] == "targeted_env_file"
    assert receipt["teable_config_sources"]["targeted_env_file_fallback_used"] is True
    assert "seeded-from-env-file" not in serialized
    assert "tbl_from_env_file" not in serialized
    assert "BROKEN_SHELL_SECRET" not in serialized
    assert verify(output, root=tmp_path) == []


def test_materialize_teable_env_recovery_proof_requires_seeded_api_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TEABLE_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="teable_seeded_api_key_required"):
        build_teable_env_recovery_proof(
            root=tmp_path,
            output_path=tmp_path / "proof.json",
            require_seeded_api_key=True,
        )


def test_materialize_teable_env_recovery_proof_writes_blocked_receipt_without_seeded_api_key(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("TEABLE_API_KEY", raising=False)
    monkeypatch.setattr(proof_module, "_git_head", lambda path: "fresh-head")
    monkeypatch.setattr(proof_module, "_source_fingerprint", lambda path: "source-fingerprint")

    receipt = build_teable_env_recovery_proof(
        root=tmp_path,
        output_path=tmp_path / "proof.json",
        require_seeded_api_key=False,
    )
    serialized = json.dumps(receipt, sort_keys=True)

    assert receipt["status"] == "blocked_setup_required"
    assert receipt["recovery_status"] == "not_attempted"
    assert receipt["blocking_reason"] == "teable_seeded_api_key_required"
    assert receipt["next_action"] == "seed_teable_api_key_and_rerun_fresh_host_recovery_drill"
    assert receipt["fresh_host_api_key_source"] == "missing"
    assert receipt["drill_output_removed"] is True
    assert receipt["secret_values_redacted"] is True
    assert receipt["privacy"]["raw_api_key_exposed"] is False
    assert "seeded-teable-key" not in serialized


def test_teable_env_recovery_proof_verifier_flags_stale_receipt(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / ".codex-studio/published/teable_env_recovery_proof.generated.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "contract_name": "ea.teable_env_recovery_proof.v1",
                "generated_by": "scripts/materialize_teable_env_recovery_proof.py",
                "source_git_head": "old-head",
                "source_state_fingerprint": "old-source-fingerprint",
                "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
                "status": "pass",
                "recovery_status": "recovered",
                "fresh_host_api_key_source": "process_env",
                "teable_config_sources": {
                    "api_key": "process_env",
                    "base_url": "default",
                    "table_id": "argument",
                    "table_name": "argument",
                    "host_profile": "argument",
                    "targeted_env_file_fallback_used": False,
                },
                "secret_values_redacted": True,
                "drill_output_removed": True,
                "privacy": {
                    "raw_paths_exposed": False,
                    "raw_table_id_exposed": False,
                    "raw_api_key_exposed": False,
                    "secret_values_exposed": False,
                },
                "env_files": [
                    {
                        "scope": "ea_root",
                        "path_sha256": "1",
                        "path_recorded": True,
                        "restored": 1,
                        "hash_verified": 1,
                        "hash_mismatch_count": 0,
                        "backup_created": False,
                        "mode": "0o600",
                    },
                    {
                        "scope": "ea_root_local",
                        "path_sha256": "2",
                        "path_recorded": True,
                        "restored": 1,
                        "hash_verified": 1,
                        "hash_mismatch_count": 0,
                        "backup_created": False,
                        "mode": "0o600",
                    },
                    {
                        "scope": "ea_service",
                        "path_sha256": "3",
                        "path_recorded": True,
                        "restored": 1,
                        "hash_verified": 1,
                        "hash_mismatch_count": 0,
                        "backup_created": False,
                        "mode": "0o600",
                    },
                ],
                "referenced_files": {
                    "restored": 0,
                    "hash_verified": 0,
                    "hash_mismatch_count": 0,
                    "backup_count": 0,
                    "path_count": 0,
                    "path_sha256": [],
                    "modes": [],
                },
                "verification": {
                    "status": "pass",
                    "expected_rows": 3,
                    "same_hash": 3,
                    "missing_count": 0,
                    "different_hash_count": 0,
                    "missing_secret_value_count": 0,
                    "extra_restorable_count": 0,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(verifier_module, "_git_head", lambda path=tmp_path: "fresh-head")
    monkeypatch.setattr(verifier_module, "_source_fingerprint", lambda path=tmp_path: "fresh-source-fingerprint")

    issues = verify(output, root=tmp_path)

    assert "receipt is stale relative to current source HEAD" in issues
    assert "receipt is stale relative to current source fingerprint" in issues


def test_teable_env_recovery_proof_verifier_accepts_post_commit_head_change_when_source_fingerprint_matches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output = tmp_path / ".codex-studio/published/teable_env_recovery_proof.generated.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "contract_name": "ea.teable_env_recovery_proof.v1",
                "generated_by": "scripts/materialize_teable_env_recovery_proof.py",
                "source_git_head": "old-head",
                "source_state_fingerprint": "source-fingerprint",
                "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
                "status": "pass",
                "recovery_status": "recovered",
                "fresh_host_api_key_source": "process_env",
                "teable_config_sources": {
                    "api_key": "process_env",
                    "base_url": "default",
                    "table_id": "argument",
                    "table_name": "argument",
                    "host_profile": "argument",
                    "targeted_env_file_fallback_used": False,
                },
                "secret_values_redacted": True,
                "drill_output_removed": True,
                "privacy": {
                    "raw_paths_exposed": False,
                    "raw_table_id_exposed": False,
                    "raw_api_key_exposed": False,
                    "secret_values_exposed": False,
                },
                "env_files": [
                    {
                        "scope": "ea_root",
                        "path_sha256": "1",
                        "path_recorded": True,
                        "restored": 1,
                        "hash_verified": 1,
                        "hash_mismatch_count": 0,
                        "backup_created": False,
                        "mode": "0o600",
                    },
                    {
                        "scope": "ea_root_local",
                        "path_sha256": "2",
                        "path_recorded": True,
                        "restored": 1,
                        "hash_verified": 1,
                        "hash_mismatch_count": 0,
                        "backup_created": False,
                        "mode": "0o600",
                    },
                    {
                        "scope": "ea_service",
                        "path_sha256": "3",
                        "path_recorded": True,
                        "restored": 1,
                        "hash_verified": 1,
                        "hash_mismatch_count": 0,
                        "backup_created": False,
                        "mode": "0o600",
                    },
                ],
                "referenced_files": {
                    "restored": 0,
                    "hash_verified": 0,
                    "hash_mismatch_count": 0,
                    "backup_count": 0,
                    "path_count": 0,
                    "path_sha256": [],
                    "modes": [],
                },
                "verification": {
                    "status": "pass",
                    "expected_rows": 3,
                    "same_hash": 3,
                    "missing_count": 0,
                    "different_hash_count": 0,
                    "missing_secret_value_count": 0,
                    "extra_restorable_count": 0,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(verifier_module, "_git_head", lambda path=tmp_path: "new-head")
    monkeypatch.setattr(verifier_module, "_source_fingerprint", lambda path=tmp_path: "source-fingerprint")

    assert verify(output, root=tmp_path) == []
