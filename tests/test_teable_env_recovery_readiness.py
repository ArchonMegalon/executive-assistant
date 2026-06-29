from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.materialize_teable_env_recovery_readiness import build_teable_env_recovery_readiness
from scripts.verify_teable_env_recovery_readiness import verify
import scripts.materialize_teable_env_recovery_readiness as readiness_module
import scripts.verify_teable_env_recovery_readiness as readiness_verifier_module


def _write_contract_surface(root: Path) -> None:
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / ".codex-studio" / "published").mkdir(parents=True, exist_ok=True)
    (root / "Makefile").write_text(
        "\n".join(
            [
                "env-check-teable:",
                "\t$(PYTHON_BIN) scripts/sync_env_to_teable.py check",
                "env-fresh-host-teable:",
                "\t@scripts/bootstrap_from_teable.sh --fresh-host",
                "env-probe-teable:",
                "\t@scripts/bootstrap_from_teable.sh --probe",
                "verify-env-teable-recovery:",
                "\t$(PYTHON_BIN) scripts/sync_env_to_teable.py verify",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "\n".join(
            [
                "make env-fresh-host-teable",
                "make env-probe-teable",
                "make env-check-teable",
                "make env-drill-teable",
                "make env-local-status-teable",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "scripts" / "bootstrap_from_teable.sh").write_text(
        "\n".join(
            [
                "scripts/bootstrap_from_teable.sh --fresh-host",
                "scripts/bootstrap_from_teable.sh --probe",
                "scripts/bootstrap_from_teable.sh --check",
                "scripts/bootstrap_from_teable.sh --drill",
                "scripts/bootstrap_from_teable.sh --ensure-local",
                "TEABLE_API_KEY must be seeded in the shell for fresh-host recovery.",
                "TEABLE_API_KEY must be seeded in the shell for fresh-host probe recovery.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "scripts" / "sync_env_to_teable.py").write_text(
        "\n".join(
            [
                '"recover",',
                '"drill",',
                '"check",',
                '"verify",',
                '"local-status",',
                '"ensure-local",',
                "--require-seeded-api-key",
                "ea.teable_env_recovery_proof.v1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_teable_env_recovery_readiness_materializes_local_command_surface_without_overclaiming(tmp_path: Path, monkeypatch) -> None:
    _write_contract_surface(tmp_path)
    monkeypatch.setattr(readiness_module, "_git_head", lambda path: "source-head")
    monkeypatch.setattr(readiness_module, "_source_fingerprint", lambda path: "source-fingerprint")
    monkeypatch.setattr(readiness_verifier_module, "_git_head", lambda path=tmp_path: "source-head")
    monkeypatch.setattr(readiness_verifier_module, "_source_fingerprint", lambda path=tmp_path: "source-fingerprint")

    output = tmp_path / ".codex-studio/published/teable_env_recovery_readiness.generated.json"
    receipt = build_teable_env_recovery_readiness(root=tmp_path, output_path=output, generated_at="2026-06-22T15:00:00Z")
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    assert receipt["contract_name"] == "ea.teable_env_recovery_readiness.v1"
    assert receipt["status"] == "ready_local_audit"
    assert receipt["command_surface_ready"] is True
    assert receipt["fresh_host_drill_receipt_mirrored"] is False
    assert receipt["claim_limit"] == "local_command_contract_readiness_not_fresh_host_drill"
    assert receipt["required_next_receipts"] == ["fresh_host_teable_recovery_drill_receipt"]
    assert verify(output, root=tmp_path) == []


def test_teable_env_recovery_readiness_blocks_missing_contract_surface(tmp_path: Path, monkeypatch) -> None:
    _write_contract_surface(tmp_path)
    (tmp_path / "README.md").write_text("make env-check-teable\n", encoding="utf-8")
    monkeypatch.setattr(readiness_module, "_git_head", lambda path: "source-head")
    monkeypatch.setattr(readiness_module, "_source_fingerprint", lambda path: "source-fingerprint")

    receipt = build_teable_env_recovery_readiness(
        root=tmp_path,
        output_path=tmp_path / ".codex-studio/published/teable_env_recovery_readiness.generated.json",
        generated_at="2026-06-22T15:00:00Z",
    )

    assert receipt["status"] == "blocked"
    assert receipt["command_surface_ready"] is False
    assert "readme_contract_missing:fresh_host_doc" in receipt["issues"]


def test_teable_env_recovery_readiness_cli_writes_receipt(tmp_path: Path, monkeypatch) -> None:
    _write_contract_surface(tmp_path)
    output = tmp_path / ".codex-studio/published/teable_env_recovery_readiness.generated.json"
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)

    subprocess.run(
        [
            "python3",
            "scripts/materialize_teable_env_recovery_readiness.py",
            "--root",
            str(tmp_path),
            "--output",
            str(output),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )

    issues = verify(output, root=tmp_path)
    assert issues == []


def test_teable_env_recovery_readiness_verifier_accepts_post_commit_head_change_when_source_fingerprint_matches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_contract_surface(tmp_path)
    output = tmp_path / ".codex-studio/published/teable_env_recovery_readiness.generated.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "contract_name": "ea.teable_env_recovery_readiness.v1",
                "generated_by": "scripts/materialize_teable_env_recovery_readiness.py",
                "source_git_head": "old-head",
                "source_state_fingerprint": "source-fingerprint",
                "source_state_fingerprint_semantics": "worktree_source_files_sha256_excluding_generated_only_paths",
                "status": "ready_local_audit",
                "command_surface_ready": True,
                "fresh_host_drill_receipt_mirrored": False,
                "claim_limit": "local_command_contract_readiness_not_fresh_host_drill",
                "verifier_commands": sorted(
                    [
                        "make verify-teable-env-recovery-readiness",
                        "make verify-env-teable-recovery",
                        "make env-check-teable",
                        "make env-probe-teable",
                        "make env-fresh-host-teable",
                    ]
                ),
                "required_next_receipts": ["fresh_host_teable_recovery_drill_receipt"],
                "rules": [
                    "This receipt proves local command and documentation readiness only; it does not prove a fresh-host recovery drill happened.",
                    "Do not claim Teable recovery pass from this receipt alone.",
                    "A seeded fresh-host probe or drill receipt must be mirrored separately before the recover lens can claim pass.",
                ],
                "checks": {
                    "makefile": {key: True for key in readiness_verifier_module.EXPECTED_CHECK_KEYS["makefile"]},
                    "readme": {key: True for key in readiness_verifier_module.EXPECTED_CHECK_KEYS["readme"]},
                    "bootstrap_script": {key: True for key in readiness_verifier_module.EXPECTED_CHECK_KEYS["bootstrap_script"]},
                    "sync_script": {key: True for key in readiness_verifier_module.EXPECTED_CHECK_KEYS["sync_script"]},
                },
                "issues": [],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(readiness_verifier_module, "_git_head", lambda path=tmp_path: "new-head")
    monkeypatch.setattr(readiness_verifier_module, "_source_fingerprint", lambda path=tmp_path: "source-fingerprint")

    assert verify(output, root=tmp_path) == []
