from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


GENERATED_AT = "2026-06-19T13:30:00Z"


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


def test_active_media_ltd_goal_bundle_materializes_verified_local_evidence(tmp_path: Path) -> None:
    materializer = _load_script("materialize_active_media_ltd_goal_bundle")
    verifier = _load_script("verify_active_media_ltd_goal_bundle")
    receipt_path = tmp_path / "active-media-ltd.generated.json"

    receipt = materializer.materialize_active_media_ltd_goal_bundle(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        refresh=True,
    )

    assert receipt["status"] == "ready_local_evidence"
    assert receipt["goal_completion_claim_allowed"] is False
    assert receipt["provider_ready"] is False
    assert receipt["live_provider_runtime_verified"] is False
    assert receipt["public_route_claim_allowed"] is False
    for key, row in receipt["verifications"].items():  # type: ignore[union-attr]
        assert row["status"] == "pass", key
        assert row["issues"] == [], key
    assert receipt["verifications"]["audiobook_live_readiness"]["status"] == "pass"  # type: ignore[index]
    assert receipt["verifications"]["audiobook_live_readiness"]["receipt"]["exists"] is True  # type: ignore[index]
    assert "named promo video provider account/runtime proof" in receipt["remaining_external_proofs"]
    audiobook_delivery = receipt["external_proof_posture"]["audiobook_live_delivery"]  # type: ignore[index]
    assert audiobook_delivery["status"] in {"missing", "blocked_external_proof", "live_delivery_verified"}
    assert audiobook_delivery["real_user_playback_acceptance_verified"] is False
    assert audiobook_delivery["goal_completion_claim_allowed"] is False
    assert audiobook_delivery["privacy"].get("raw_public_share_url_included") is not True

    verification = verifier.verify_active_media_ltd_goal_bundle(receipt_path)

    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_active_media_ltd_goal_bundle_verifier_rejects_completion_and_provider_overclaims(tmp_path: Path) -> None:
    materializer = _load_script("materialize_active_media_ltd_goal_bundle")
    verifier = _load_script("verify_active_media_ltd_goal_bundle")
    receipt_path = tmp_path / "tampered.generated.json"
    materializer.materialize_active_media_ltd_goal_bundle(
        receipt_path=receipt_path,
        generated_at=GENERATED_AT,
        refresh=True,
    )
    receipt = _load(receipt_path)
    receipt["goal_completion_claim_allowed"] = True
    receipt["provider_ready"] = True
    receipt["verifications"]["promo_quality_rubric"]["status"] = "fail"  # type: ignore[index]
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_active_media_ltd_goal_bundle(receipt_path)

    assert verification["status"] == "fail"
    assert "active_bundle_goal_completion_overclaim" in verification["issues"]
    assert "active_bundle_provider_ready_overclaim" in verification["issues"]
    assert "active_bundle_verification_status_not_pass:promo_quality_rubric" in verification["issues"]


def test_active_media_ltd_goal_bundle_clis_work(tmp_path: Path) -> None:
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    receipt_path = tmp_path / "cli-active-media-ltd.generated.json"
    materialized = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_active_media_ltd_goal_bundle.py"),
            "--receipt",
            str(receipt_path),
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
    assert receipt["status"] == "ready_local_evidence"
    assert receipt["receipt"] == receipt_path.as_posix()

    verified = subprocess.run(
        [
            sys.executable,
            str(script_root / "verify_active_media_ltd_goal_bundle.py"),
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
