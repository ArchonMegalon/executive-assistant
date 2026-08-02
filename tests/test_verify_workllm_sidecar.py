from __future__ import annotations

import json
import stat
from pathlib import Path

from scripts.verify_workllm_sidecar import build_receipt


def _write_env(path: Path) -> None:
    path.write_text(
        """\
WORKLLM_BASE_URL=https://workspace.example.test
WORKLLM_EMAIL=fixture@example.test
WORKLLM_PASSWORD=fixture-password
WORKLLM_PROVIDER_VERIFIED=0
WORKLLM_RUNTIME_ENABLED=0
""",
        encoding="utf-8",
    )
    path.chmod(0o600)


def test_verifier_writes_candidate_only_redacted_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_path = tmp_path / ".env"
    output_path = tmp_path / "receipt.json"
    _write_env(env_path)

    monkeypatch.setattr(
        "scripts.verify_workllm_sidecar.PUBLIC_REACHABILITY_RECEIPT",
        Path(__file__).resolve().parents[1]
        / ".codex-studio"
        / "published"
        / "WORKLLM_PUBLIC_REACHABILITY.missing.test.json",
    )
    receipt = build_receipt(
        env_path=env_path,
        output_path=output_path,
    )
    serialized = json.dumps(receipt)

    assert output_path.is_file()
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert receipt["verdict"] == "CANDIDATE_ONLY"
    assert receipt["checks"]["local_contract_ready"] is True
    assert receipt["checks"]["credentials_protected"] is True
    assert receipt["checks"]["tenant_surface_reachable"] is False
    assert receipt["promotion"]["account_verified"] is False
    assert receipt["promotion"]["provider_verified"] is False
    assert receipt["promotion"]["manual_lane_promoted"] is False
    assert receipt["promotion"]["api_lane_promoted"] is False
    assert receipt["default_authorized_data_classes"] == ["public"]
    assert receipt["stronger_data_gate"]["enabled"] is False
    assert "fixture@example.test" not in serialized
    assert "fixture-password" not in serialized


def test_verifier_does_not_accept_permissive_secret_file_mode(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    output_path = tmp_path / "receipt.json"
    _write_env(env_path)
    env_path.chmod(0o644)

    receipt = build_receipt(
        env_path=env_path,
        output_path=output_path,
    )

    assert stat.S_IMODE(env_path.stat().st_mode) == 0o644
    assert receipt["credential_presence"]["env_mode_600"] is False
    assert receipt["checks"]["credentials_protected"] is False
