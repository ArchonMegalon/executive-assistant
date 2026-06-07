from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_avatar_presenter_provider.py"
    spec = importlib.util.spec_from_file_location("verify_avatar_presenter_provider", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_capture_summary(path: Path, *, provider_key: str = "vidboard", authenticated: bool = True) -> str:
    payload = {
        "provider_key": provider_key,
        "template_key": "vidboard_workspace_reader",
        "authenticated_workspace_detected": authenticated,
        "render_status": "completed" if authenticated else "failed",
        "url": "https://app.vidboard.ai/dashboard",
        "title": "VidBoard Dashboard",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return _load_script()._sha256_file(path)


def test_verify_vidboard_avatar_provider_fails_closed_without_proof(tmp_path: Path) -> None:
    module = _load_script()

    payload = module.build_payload("vidboard", allow_fallback=True)

    assert payload["provider"] == "VidBoard"
    assert payload["verdict"] == "READY_VIA_FALLBACK"
    assert payload["provider_ready"] is False
    assert payload["fallback_mode"] == "fallback_static_storyboard"
    assert payload["verification_checklist"]["lip_sync_quality"]["verified"] is False
    assert payload["verification_checklist"]["watermark_free_export"]["verified"] is False

    path = module.write_payload(payload, tmp_path)
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["provider_key"] == "vidboard"


def test_verify_nonverbia_avatar_provider_returns_not_ready_without_fallback() -> None:
    module = _load_script()

    payload = module.build_payload("nonverbia", allow_fallback=False)

    assert payload["provider"] == "Nonverbia"
    assert payload["verdict"] == "NOT_READY"
    assert payload["provider_ready"] is False


def test_verify_vidboard_avatar_provider_promotes_with_complete_receipts(tmp_path: Path) -> None:
    module = _load_script()
    receipt_dir = tmp_path / "receipts"
    receipt_dir.mkdir()
    capture_path = tmp_path / "vidboard_workspace_capture.generated.json"
    capture_sha = _write_capture_summary(capture_path)
    receipt_types = [
        "login_capture",
        "commercial_use_terms_receipt",
        "watermark_export_receipt",
        "lip_sync_review_receipt",
        "viseme_quality_receipt",
        "privacy_terms_receipt",
        "source_data_boundary_receipt",
    ]
    for receipt_type in receipt_types:
        (receipt_dir / f"{receipt_type}.json").write_text(
            json.dumps(
                {
                    "provider_key": "vidboard",
                    "receipt_type": receipt_type,
                    "verified": True,
                    "captured_at": "2026-06-07T12:00:00Z",
                    "source_capture_authenticated": True,
                    "capture_path": capture_path.as_posix(),
                    "capture_file_sha256": capture_sha,
                    "reviewed_by": "" if receipt_type == "login_capture" else "operator-1",
                    "reviewed_at": "" if receipt_type == "login_capture" else "2026-06-07T12:10:00Z",
                    "evidence_ref": "" if receipt_type == "login_capture" else "https://evidence.example/review/1",
                }
            ),
            encoding="utf-8",
        )

    payload = module.build_payload("vidboard", allow_fallback=False, receipt_dir=receipt_dir)

    assert payload["provider"] == "VidBoard"
    assert payload["verdict"] == "VERIFIED_PROVIDER"
    assert payload["provider_ready"] is True
    assert len(payload["receipts_loaded"]) == len(receipt_types)
    assert payload["verification_checklist"]["lip_sync_quality"]["verified"] is True
    assert payload["verification_checklist"]["watermark_free_export"]["verified"] is True


def test_verify_vidboard_avatar_provider_rejects_forged_receipts_without_capture_provenance(tmp_path: Path) -> None:
    module = _load_script()
    receipt_dir = tmp_path / "receipts"
    receipt_dir.mkdir()
    for receipt_type in [
        "login_capture",
        "commercial_use_terms_receipt",
        "watermark_export_receipt",
        "lip_sync_review_receipt",
        "viseme_quality_receipt",
        "privacy_terms_receipt",
        "source_data_boundary_receipt",
    ]:
        (receipt_dir / f"{receipt_type}.json").write_text(
            json.dumps(
                {
                    "provider_key": "vidboard",
                    "receipt_type": receipt_type,
                    "verified": True,
                    "captured_at": "2026-06-07T12:00:00Z",
                }
            ),
            encoding="utf-8",
        )

    payload = module.build_payload("vidboard", allow_fallback=False, receipt_dir=receipt_dir)

    assert payload["verdict"] == "NOT_READY"
    assert payload["provider_ready"] is False
    assert any(item["trusted"] is False for item in payload["receipts_loaded"])


def test_verify_avatar_provider_cli_returns_success_for_fallback_payload(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "verify_avatar_presenter_provider.py"
    out_dir = tmp_path / "out"

    completed = subprocess.run(
        [
            "python3",
            str(script),
            "--provider",
            "vidboard",
            "--allow-fallback",
            "--write-dir",
            str(out_dir),
            "--receipt-dir",
            str(tmp_path / "receipts"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    generated = out_dir / "vidboard_AVATAR_PRESENTER_PROVIDER_PROOF.generated.json"
    payload = json.loads(generated.read_text(encoding="utf-8"))
    assert payload["verdict"] == "READY_VIA_FALLBACK"


def test_verify_avatar_provider_cli_returns_nonzero_when_trust_requirements_are_unmet(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "verify_avatar_presenter_provider.py"
    receipt_dir = tmp_path / "receipts"
    receipt_dir.mkdir()
    for receipt_type in [
        "login_capture",
        "commercial_use_terms_receipt",
        "watermark_export_receipt",
        "lip_sync_review_receipt",
        "viseme_quality_receipt",
        "privacy_terms_receipt",
        "source_data_boundary_receipt",
    ]:
        (receipt_dir / f"{receipt_type}.json").write_text(
            json.dumps(
                {
                    "provider_key": "vidboard",
                    "receipt_type": receipt_type,
                    "verified": True,
                    "captured_at": "2026-06-07T12:00:00Z",
                }
            ),
            encoding="utf-8",
        )

    completed = subprocess.run(
        [
            "python3",
            str(script),
            "--provider",
            "vidboard",
            "--write-dir",
            str(tmp_path / "out"),
            "--receipt-dir",
            str(receipt_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
