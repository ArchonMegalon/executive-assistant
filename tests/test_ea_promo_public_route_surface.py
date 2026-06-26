from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType


GENERATED_AT = "2026-06-19T15:00:00Z"


def _load_script(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "ea" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _prepare_route_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    promo_materializer = _load_script("materialize_ea_promo_review_bundle")
    review_output = tmp_path / "artifact"
    promo_materializer.materialize_ea_promo_review_bundle(output_dir=review_output, generated_at=GENERATED_AT)
    artifact_root = tmp_path / "published" / "ashline-circle"
    shutil.copytree(review_output, artifact_root)
    return artifact_root, artifact_root.parent


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_materialize_ea_promo_public_route_surface_generates_verified_route_proof(tmp_path: Path) -> None:
    materializer = _load_script("materialize_ea_promo_public_route_surface")
    verifier = _load_script("verify_ea_promo_public_route_surface")
    route_root, artifact_root = _prepare_route_artifacts(tmp_path)
    receipt_path = tmp_path / "route-surface.generated.json"

    result = materializer.materialize_ea_promo_public_route_surface(
        receipt_path=receipt_path,
        artifact_root_override=str(artifact_root),
        generated_at=GENERATED_AT,
    )

    assert result["status"] == "ready"
    assert result["route_deployment_verified"] is True
    assert result["local_app_route_surface_verified"] is True
    assert result["published_fallback_route_claim_allowed"] is True
    assert result["public_internet_deployment_verified"] is False
    assert result["publication_verdict"] == "READY_VIA_FALLBACK"
    assert result["checks"]["watch_http_200"] is True
    assert result["checks"]["json_http_200"] is True
    assert result["checks"]["watch_marks_in_app_fallback_route"] is True
    assert result["checks"]["watch_does_not_mark_route_pending"] is True
    assert result["route"] == "/ledger/factions/ashline-circle/promo"
    watch_html = result["route_snapshots"]["watch"]["body_text_preview"]  # type: ignore[index]
    assert "in-app fallback route" in watch_html
    assert "public deployment proof pending" not in watch_html
    assert route_root.is_dir()
    verification = verifier.verify_ea_promo_public_route_surface(receipt_path)
    assert verification["status"] == "pass"
    assert verification["issues"] == []


def test_verify_ea_promo_public_route_surface_rejects_tamper(tmp_path: Path) -> None:
    materializer = _load_script("materialize_ea_promo_public_route_surface")
    verifier = _load_script("verify_ea_promo_public_route_surface")
    route_root, artifact_root = _prepare_route_artifacts(tmp_path)
    receipt_path = tmp_path / "route-surface-tamper.generated.json"
    result = materializer.materialize_ea_promo_public_route_surface(
        receipt_path=receipt_path,
        artifact_root_override=str(artifact_root),
        generated_at=GENERATED_AT,
    )
    assert result["status"] == "ready"

    payload = _read(receipt_path)
    payload["route_deployment_verified"] = False
    payload["published_fallback_route_claim_allowed"] = False
    receipt_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verification = verifier.verify_ea_promo_public_route_surface(receipt_path)
    assert verification["status"] == "fail"
    assert "promo_public_route_verification_not_true" in verification["issues"]
    assert "promo_public_route_fallback_claim_not_allowed" in verification["issues"]


def test_ea_promo_public_route_surface_clis_work(tmp_path: Path) -> None:
    script_root = Path(__file__).resolve().parents[1] / "ea" / "scripts"
    route_root, artifact_root = _prepare_route_artifacts(tmp_path)
    receipt_path = tmp_path / "cli-route-surface.generated.json"

    materialized = subprocess.run(
        [
            sys.executable,
            str(script_root / "materialize_ea_promo_public_route_surface.py"),
            "--receipt",
            str(receipt_path),
            "--artifact-root",
            str(artifact_root),
            "--faction-id",
            "ashline-circle",
            "--generated-at",
            GENERATED_AT,
        ],
        cwd=Path(__file__).resolve().parents[1] / "ea",
        text=True,
        capture_output=True,
        check=False,
    )

    assert materialized.returncode == 0, materialized.stderr + materialized.stdout
    materialized_payload = json.loads(materialized.stdout)
    assert materialized_payload["status"] == "ready"
    assert materialized_payload["status"] == _read(receipt_path)["status"]
    assert materialized_payload["route_deployment_verified"] is True

    verified = subprocess.run(
        [
            sys.executable,
            str(script_root / "verify_ea_promo_public_route_surface.py"),
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


def test_ea_promo_public_route_surface_cli_defaults_use_published_receipt(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    materializer = _load_script("materialize_ea_promo_public_route_surface")
    verifier = _load_script("verify_ea_promo_public_route_surface")
    _route_root, artifact_root = _prepare_route_artifacts(tmp_path)
    receipt_path = tmp_path / "published-route-surface.generated.json"
    monkeypatch.setattr(materializer, "DEFAULT_ARTIFACT_ROOT", artifact_root)
    monkeypatch.setattr(materializer, "DEFAULT_RECEIPT", receipt_path)
    monkeypatch.setattr(verifier, "DEFAULT_RECEIPT", receipt_path)

    assert materializer.main([]) == 0
    materialized = json.loads(capsys.readouterr().out)
    assert materialized["status"] == "ready"
    assert receipt_path.is_file()

    assert verifier.main([]) == 0
    verification = json.loads(capsys.readouterr().out)
    assert verification["status"] == "pass"
