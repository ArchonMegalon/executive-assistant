from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


GENERATED_AT = "2026-06-19T13:00:00Z"


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


def test_memorial_chatlab_route_surface_materializes_fallback_and_configured_snapshots(tmp_path: Path) -> None:
    materializer = _load_script("materialize_memorial_chatlab_route_surface")
    verifier = _load_script("verify_memorial_chatlab_route_surface")
    receipt_path = tmp_path / "chatlab-route.generated.json"

    receipt = materializer.materialize_memorial_chatlab_route_surface(
        receipt_path=receipt_path,
        slug="manfred",
        generated_at=GENERATED_AT,
    )

    assert receipt["status"] == "ready"
    persisted = _load(receipt_path)
    assert persisted["generated_at"] == GENERATED_AT
    assert persisted["route_checks"]["fallback_first_party_state"] is True  # type: ignore[index]
    assert persisted["route_checks"]["configured_contract_only_state"] is True  # type: ignore[index]
    fallback = persisted["snapshots"]["fallback_first_party_chat"]["response"]["chatlab"]  # type: ignore[index]
    configured = persisted["snapshots"]["configured_contract_only"]["response"]["chatlab"]  # type: ignore[index]
    assert fallback["integration_state"] == "fallback_first_party_chat"
    assert configured["integration_state"] == "provider_configured_contract_only"
    assert configured["provider_key"] == "chatlab"
    assert configured["provider_runtime_allowed"] is False
    assert "route-surface-secret-key" not in receipt_path.read_text(encoding="utf-8")
    assert "chatlab-route.example.test" not in receipt_path.read_text(encoding="utf-8")

    verification = verifier.verify_memorial_chatlab_route_surface(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_verify_memorial_chatlab_route_surface_rejects_overclaims_and_leaks(tmp_path: Path) -> None:
    materializer = _load_script("materialize_memorial_chatlab_route_surface")
    verifier = _load_script("verify_memorial_chatlab_route_surface")
    receipt_path = tmp_path / "tampered.generated.json"
    materializer.materialize_memorial_chatlab_route_surface(
        receipt_path=receipt_path,
        slug="manfred",
        generated_at=GENERATED_AT,
    )
    receipt = _load(receipt_path)
    receipt["provider_ready"] = True
    receipt["snapshots"]["configured_contract_only"]["response"]["chatlab"]["provider_truth_allowed"] = True  # type: ignore[index]
    receipt["debug"] = "Authorization: Bearer leaked"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_memorial_chatlab_route_surface(receipt_path)

    assert verification["status"] == "fail"
    assert "chatlab_route_provider_ready_overclaim" in verification["issues"]
    assert "chatlab_route_nested_provider_truth_overclaim" in verification["issues"]
    assert "chatlab_route_sensitive_value_exposed" in verification["issues"]


def test_memorial_chatlab_route_surface_clis_work(tmp_path: Path) -> None:
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    receipt_path = tmp_path / "cli-chatlab-route.generated.json"
    materialized = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_memorial_chatlab_route_surface.py"),
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
    result = json.loads(materialized.stdout)
    assert result["status"] == "ready"
    assert result["receipt"] == receipt_path.as_posix()

    verified = subprocess.run(
        [
            sys.executable,
            str(script_root / "verify_memorial_chatlab_route_surface.py"),
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
