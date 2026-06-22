from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from app.services.memorial_chatlab_integration import chatlab_runtime_preflight, write_chatlab_runtime_preflight


CHATLAB_ENV = (
    "EA_MEMORIAL_CHATLAB_ENABLED",
    "EA_MEMORIAL_CHAT_LAB_ENABLED",
    "EA_MEMORIAL_CHATLAB_PROVIDER",
    "EA_MEMORIAL_CHAT_LAB_PROVIDER",
    "EA_MEMORIAL_CHATLAB_API_KEY",
    "EA_MEMORIAL_CHATLAB_API_URL",
    "EA_MEMORIAL_CHATLAB_ALLOW_PROVIDER_RUNTIME",
    "CHATLAB_API_KEY",
    "CHATLAB_API_URL",
    "EA_MEMORIAL_CHATLAB_EXTERNAL_EVIDENCE_RECEIPT",
)


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "ea" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _clear_chatlab_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in CHATLAB_ENV:
        monkeypatch.delenv(name, raising=False)


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_chatlab_runtime_preflight_defaults_to_warn_fallback_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_chatlab_env(monkeypatch)

    receipt = chatlab_runtime_preflight(slug="manfred")

    assert receipt["contract_name"] == "ea.memorial_chatlab_runtime_preflight.v1"
    assert receipt["status"] == "warn"
    assert receipt["readiness_state"] == "fallback_first_party_chat"
    assert receipt["provider_ready"] is False
    assert receipt["live_provider_runtime_verified"] is False
    assert receipt["provider_truth_allowed"] is False
    assert receipt["memory_truth_allowed"] is False
    assert receipt["publication_allowed"] is False
    assert receipt["provider"]["provider_configured"] is False  # type: ignore[index]
    assert receipt["provider"]["credential_values_exposed"] is False  # type: ignore[index]
    assert receipt["receipts"]["chatlab_runtime_probe_receipt"]["status"] == "not_run"  # type: ignore[index]
    assert receipt["receipts"]["chatlab_no_private_context_upload_receipt"]["status"] == "pass_policy"  # type: ignore[index]
    assert "runtime_probe_receipt_present" in receipt["warned_checks"]
    assert receipt["failed_checks"] == []


def test_chatlab_runtime_preflight_configured_runtime_opt_in_still_does_not_claim_live(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_chatlab_env(monkeypatch)
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_ENABLED", "1")
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_PROVIDER", "chatlab")
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_API_KEY", "test-chatlab-key")
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_API_URL", "https://chatlab.example.test")
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_ALLOW_PROVIDER_RUNTIME", "1")
    verifier = _load_script("verify_memorial_chatlab_runtime_preflight")
    output_path = tmp_path / "chatlab-runtime.generated.json"

    receipt = write_chatlab_runtime_preflight(output_path=output_path, slug="manfred")

    assert receipt["status"] == "warn"
    assert receipt["readiness_state"] == "configured_runtime_probe_pending"
    assert receipt["provider"]["provider_key"] == "chatlab"  # type: ignore[index]
    assert receipt["provider"]["provider_configured"] is True  # type: ignore[index]
    assert receipt["provider"]["runtime_opt_in"] is True  # type: ignore[index]
    assert receipt["provider_ready"] is False
    assert receipt["live_provider_runtime_verified"] is False
    text = output_path.read_text(encoding="utf-8")
    assert "test-chatlab-key" not in text
    assert "chatlab.example.test" not in text
    verification = verifier.verify_chatlab_runtime_preflight(output_path)
    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_chatlab_runtime_preflight_consumes_redacted_external_evidence_without_live_overclaim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_chatlab_env(monkeypatch)
    evidence_path = tmp_path / "chatlab-external.generated.json"
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_EXTERNAL_EVIDENCE_RECEIPT", str(evidence_path))
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_ENABLED", "1")
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_PROVIDER", "chatlab")
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_API_KEY", "test-chatlab-key")
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_API_URL", "https://chatlab.example.test")
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_ALLOW_PROVIDER_RUNTIME", "1")
    from app.services.memorial_chatlab_integration import write_chatlab_external_evidence_receipt

    write_chatlab_external_evidence_receipt(
        output_path=evidence_path,
        slug="manfred",
        provider_key="chatlab",
        account_capability_evidence="operator saw account tier and integration access",
        runtime_probe_evidence="operator ran prompt through live provider and received bounded draft",
        no_private_context_evidence="operator confirmed request omitted raw private memorial context",
        guardrail_preservation_evidence="operator confirmed difficult-memory guardrail stayed first-party",
        observed_at="2026-06-20T04:15:00Z",
    )
    output_path = tmp_path / "chatlab-runtime.generated.json"

    receipt = write_chatlab_runtime_preflight(output_path=output_path, slug="manfred")

    assert receipt["status"] == "pass"
    assert receipt["provider_ready"] is False
    assert receipt["live_provider_runtime_verified"] is False
    assert receipt["external_evidence"]["status"] == "pass"  # type: ignore[index]
    assert receipt["receipts"]["chatlab_account_capability_receipt"]["status"] == "pass_redacted_external_evidence"  # type: ignore[index]
    assert receipt["receipts"]["chatlab_runtime_probe_receipt"]["status"] == "pass_redacted_external_evidence"  # type: ignore[index]
    assert receipt["receipts"]["chatlab_no_private_context_upload_receipt"]["status"] == "pass_redacted_external_evidence"  # type: ignore[index]
    assert receipt["receipts"]["chatlab_guardrail_preservation_receipt"]["status"] == "pass_redacted_external_evidence"  # type: ignore[index]
    text = output_path.read_text(encoding="utf-8") + evidence_path.read_text(encoding="utf-8")
    assert "operator saw account tier" not in text
    assert "test-chatlab-key" not in text
    assert "chatlab.example.test" not in text
    verifier = _load_script("verify_memorial_chatlab_runtime_preflight")
    verification = verifier.verify_chatlab_runtime_preflight(output_path)
    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_chatlab_runtime_preflight_fails_enabled_provider_without_secret_or_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_chatlab_env(monkeypatch)
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_ENABLED", "1")
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_PROVIDER", "chatplayground")
    output_path = tmp_path / "missing-config.generated.json"
    receipt = write_chatlab_runtime_preflight(output_path=output_path, slug="manfred")
    verifier = _load_script("verify_memorial_chatlab_runtime_preflight")

    assert receipt["status"] == "fail"
    assert "api_key_present_when_enabled" in receipt["failed_checks"]
    assert "endpoint_present_when_enabled" in receipt["failed_checks"]
    verification = verifier.verify_chatlab_runtime_preflight(output_path)
    assert verification["status"] == "fail"
    assert "chatlab_preflight_status_not_pass_or_warn" in verification["issues"]
    assert "chatlab_preflight_failed_check:api_key_present_when_enabled" in verification["issues"]


def test_verify_chatlab_runtime_preflight_rejects_overclaims(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_chatlab_env(monkeypatch)
    output_path = tmp_path / "tampered.generated.json"
    write_chatlab_runtime_preflight(output_path=output_path, slug="manfred")
    payload = _load(output_path)
    payload["provider_ready"] = True
    payload["live_provider_runtime_verified"] = True
    payload["receipts"]["chatlab_runtime_probe_receipt"]["status"] = "provider_runtime_verified"  # type: ignore[index]
    payload["chatlab_contract"]["provider_memory_write_allowed"] = True  # type: ignore[index]
    payload["debug"] = "Authorization: Bearer leaked"
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verifier = _load_script("verify_memorial_chatlab_runtime_preflight")

    verification = verifier.verify_chatlab_runtime_preflight(output_path)

    assert verification["status"] == "fail"
    assert "chatlab_preflight_provider_ready_overclaim" in verification["issues"]
    assert "chatlab_preflight_live_runtime_overclaim" in verification["issues"]
    assert "chatlab_preflight_runtime_probe_overclaim" in verification["issues"]
    assert "chatlab_preflight_nested_memory_write_overclaim" in verification["issues"]
    assert "chatlab_preflight_sensitive_value_exposed" in verification["issues"]


def test_chatlab_runtime_preflight_clis_work(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_chatlab_env(monkeypatch)
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    evidence_path = tmp_path / "cli-chatlab-external.generated.json"
    output_path = tmp_path / "cli-chatlab-runtime.generated.json"
    materialized_evidence = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_memorial_chatlab_external_evidence.py"),
            "--out",
            str(evidence_path),
            "--slug",
            "manfred",
            "--account-capability-evidence",
            "redacted account capability proof",
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert materialized_evidence.returncode == 0, materialized_evidence.stderr + materialized_evidence.stdout
    evidence_result = json.loads(materialized_evidence.stdout)
    assert evidence_result["status"] == "incomplete"
    assert evidence_path.is_file()
    materialized = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_memorial_chatlab_runtime_preflight.py"),
            "--out",
            str(output_path),
            "--slug",
            "manfred",
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert materialized.returncode == 0, materialized.stderr + materialized.stdout
    result = json.loads(materialized.stdout)
    assert result["status"] == "warn"
    assert result["receipt_path"] == output_path.as_posix()

    verified = subprocess.run(
        [
            sys.executable,
            str(script_root / "verify_memorial_chatlab_runtime_preflight.py"),
            "--preflight",
            str(output_path),
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr + verified.stdout
    verification = json.loads(verified.stdout)
    assert verification["status"] == "pass"
