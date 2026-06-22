from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


GENERATED_AT = "2026-06-19T12:30:00Z"
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
)


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "ea" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _clear_chatlab_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in CHATLAB_ENV:
        monkeypatch.delenv(name, raising=False)


def test_materialize_memorial_chatlab_receipt_defaults_to_first_party_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_chatlab_env(monkeypatch)
    materializer = _load_script("materialize_memorial_chatlab_contract_receipt")
    verifier = _load_script("verify_memorial_chatlab_contract_receipt")
    receipt_path = tmp_path / "chatlab.generated.json"

    receipt = materializer.materialize_memorial_chatlab_contract_receipt(
        receipt_path=receipt_path,
        slug="manfred",
        generated_at=GENERATED_AT,
    )

    assert receipt["status"] == "ready_fallback_contract"
    assert receipt["slug"] == "manfred"
    assert receipt["provider_ready"] is False
    assert receipt["live_provider_runtime_verified"] is False
    assert receipt["provider_truth_allowed"] is False
    assert receipt["persona_truth_allowed"] is False
    assert receipt["memory_truth_allowed"] is False
    assert receipt["publication_allowed"] is False
    assert receipt["raw_private_context_exposed"] is False
    assert receipt["boundaries"]["first_party_chat_authoritative"] is True  # type: ignore[index]
    chatlab = receipt["chatlab_contract"]
    assert chatlab["integration_state"] == "fallback_first_party_chat"  # type: ignore[index]
    assert chatlab["provider_key"] == ""  # type: ignore[index]
    assert chatlab["first_party_chat_remains_authoritative"] is True  # type: ignore[index]
    assert "chatlab_runtime_probe_receipt" in chatlab["required_next_receipts"]  # type: ignore[index]

    persisted = _load(receipt_path)
    assert persisted["generated_at"] == GENERATED_AT
    verification = verifier.verify_memorial_chatlab_contract_receipt(receipt_path)
    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_materialize_memorial_chatlab_configured_contract_omits_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_chatlab_env(monkeypatch)
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_ENABLED", "1")
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_PROVIDER", "chatlab")
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_API_KEY", "test-chatlab-key")
    monkeypatch.setenv("EA_MEMORIAL_CHATLAB_API_URL", "https://chatlab.example.test")
    materializer = _load_script("materialize_memorial_chatlab_contract_receipt")
    verifier = _load_script("verify_memorial_chatlab_contract_receipt")
    receipt_path = tmp_path / "configured.generated.json"

    receipt = materializer.materialize_memorial_chatlab_contract_receipt(
        receipt_path=receipt_path,
        slug="Manfred Hoza",
        generated_at=GENERATED_AT,
    )

    assert receipt["status"] == "configured_contract_only"
    assert receipt["slug"] == "manfred-hoza"
    assert receipt["provider_key"] == "chatlab"
    assert receipt["provider_label"] == "ChatLab"
    assert receipt["provider_configured"] is True
    assert receipt["runtime_probe_required"] is False
    assert receipt["live_provider_runtime_verified"] is False
    text = receipt_path.read_text(encoding="utf-8")
    assert "test-chatlab-key" not in text
    assert "chatlab.example.test" not in text
    verification = verifier.verify_memorial_chatlab_contract_receipt(receipt_path)
    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_verify_memorial_chatlab_receipt_rejects_overclaims_and_sensitive_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_chatlab_env(monkeypatch)
    materializer = _load_script("materialize_memorial_chatlab_contract_receipt")
    verifier = _load_script("verify_memorial_chatlab_contract_receipt")
    receipt_path = tmp_path / "tampered.generated.json"
    materializer.materialize_memorial_chatlab_contract_receipt(
        receipt_path=receipt_path,
        slug="manfred",
        generated_at=GENERATED_AT,
    )
    receipt = _load(receipt_path)
    receipt["provider_ready"] = True
    receipt["publication_allowed"] = True
    receipt["chatlab_contract"]["provider_truth_allowed"] = True  # type: ignore[index]
    receipt["chatlab_contract"]["first_party_chat_remains_authoritative"] = False  # type: ignore[index]
    receipt["debug_value"] = "Authorization: Bearer leaked"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_memorial_chatlab_contract_receipt(receipt_path)

    assert verification["status"] == "fail"
    assert "memorial_chatlab_provider_ready_overclaim" in verification["issues"]
    assert "memorial_chatlab_publication_overclaim" in verification["issues"]
    assert "memorial_chatlab_nested_provider_truth_overclaim" in verification["issues"]
    assert "memorial_chatlab_first_party_not_authoritative" in verification["issues"]
    assert "memorial_chatlab_sensitive_value_exposed" in verification["issues"]


def test_memorial_chatlab_receipt_clis_work(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_chatlab_env(monkeypatch)
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    receipt_path = tmp_path / "cli-chatlab.generated.json"
    materialized = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_memorial_chatlab_contract_receipt.py"),
            "--receipt",
            str(receipt_path),
            "--slug",
            "manfred",
            "--generated-at",
            GENERATED_AT,
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert materialized.returncode == 0, materialized.stderr + materialized.stdout
    receipt = json.loads(materialized.stdout)
    assert receipt["status"] == "ready_fallback_contract"
    assert receipt["receipt"] == receipt_path.as_posix()

    verified = subprocess.run(
        [
            sys.executable,
            str(script_root / "verify_memorial_chatlab_contract_receipt.py"),
            "--receipt",
            str(receipt_path),
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr + verified.stdout
    verification = json.loads(verified.stdout)
    assert verification["status"] == "pass"
