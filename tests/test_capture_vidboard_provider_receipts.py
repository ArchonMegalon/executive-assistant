from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "capture_vidboard_provider_receipts.py"
    spec = importlib.util.spec_from_file_location("capture_vidboard_provider_receipts", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_verify_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_avatar_presenter_provider.py"
    spec = importlib.util.spec_from_file_location("verify_avatar_presenter_provider", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_capture_summary_marks_authenticated_completed_results() -> None:
    module = _load_script()

    summary = module._capture_summary(
        {
            "render_status": "completed",
            "structured_output_json": {
                "page_title": "VidBoard Dashboard",
                "url": "https://app.vidboard.ai/dashboard",
                "warnings": [],
                "errors": [],
                "screenshot_path": "/tmp/preview.png",
            },
            "body_text": "Avatar studio and export tools visible.",
            "editor_url": "https://app.vidboard.ai/dashboard",
        }
    )

    assert summary["provider_key"] == "vidboard"
    assert summary["authenticated_workspace_detected"] is True
    assert summary["render_status"] == "completed"
    assert summary["title"] == "VidBoard Dashboard"
    assert summary["url"] == "https://app.vidboard.ai/dashboard"


def test_login_capture_receipt_is_verified_only_after_authenticated_capture() -> None:
    module = _load_script()
    capture_path = Path("/tmp/capture.json")

    receipt = module._receipt_payload(
        "login_capture",
        {
            "captured_at": "2026-06-07T12:00:00Z",
            "authenticated_workspace_detected": True,
            "render_status": "completed",
            "url": "https://app.vidboard.ai/dashboard",
            "title": "VidBoard Dashboard",
        },
        capture_path=capture_path,
        capture_file_sha256="abc123",
    )

    assert receipt["verified"] is True
    assert receipt["provider_key"] == "vidboard"
    assert receipt["capture_path"] == capture_path.as_posix()
    assert receipt["capture_file_sha256"] == "abc123"


def test_manual_receipts_remain_unverified_and_write_to_disk(tmp_path: Path) -> None:
    module = _load_script()
    capture_path = tmp_path / "capture.json"
    capture_path.write_text("{}", encoding="utf-8")

    receipt = module._receipt_payload(
        "watermark_export_receipt",
        {
            "captured_at": "2026-06-07T12:00:00Z",
            "authenticated_workspace_detected": True,
            "render_status": "completed",
            "url": "https://app.vidboard.ai/dashboard",
            "title": "VidBoard Dashboard",
        },
        capture_path=capture_path,
        capture_file_sha256="def456",
    )
    path = tmp_path / "receipt.json"
    module._write_json(path, receipt)

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["verified"] is False
    assert loaded["receipt_type"] == "watermark_export_receipt"
    assert loaded["reviewed_by"] == ""


def test_failed_capture_summary_marks_captcha_blocker() -> None:
    module = _load_script()

    summary = module._failed_capture_summary("vidboard_capture_worker_failed:template_worker_failed:captcha_required")

    assert summary["authenticated_workspace_detected"] is False
    assert summary["render_status"] == "failed"
    assert summary["ui_failure_code"] == "captcha_required"


def test_capture_summary_reads_worker_structured_output_paths() -> None:
    module = _load_script()

    summary = module._capture_summary(
        {
            "render_status": "completed_with_warnings",
            "structured_output_json": {
                "page_title": "Workspace",
                "url": "https://app.vidboard.ai/workspace",
                "warnings": ["slow_ui"],
                "errors": [],
                "screenshot_path": "/tmp/preview.png",
                "html_path": "/tmp/page.html",
                "auth_handoff": {"status": "authenticated"},
            },
        }
    )

    assert summary["authenticated_workspace_detected"] is True
    assert summary["screenshot_path"] == "/tmp/preview.png"
    assert summary["html_path"] == "/tmp/page.html"
    assert summary["auth_handoff"] == {"status": "authenticated"}


def test_capture_main_writes_failed_capture_and_unverified_receipts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_script()
    output_path = tmp_path / "capture.json"
    receipt_dir = tmp_path / "receipts"
    handoff_path = tmp_path / "handoff.json"

    monkeypatch.setattr(module, "_login_email", lambda value: "operator@example.com")
    monkeypatch.setattr(module, "_login_password", lambda value: "secret")
    monkeypatch.setattr(module, "_run_worker", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("template_worker_failed:captcha_required")))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "capture_vidboard_provider_receipts.py",
            "--output",
            str(output_path),
            "--receipt-dir",
            str(receipt_dir),
            "--handoff-output",
            str(handoff_path),
        ],
    )

    exit_code = module.main()

    assert exit_code == 1
    capture = json.loads(output_path.read_text(encoding="utf-8"))
    assert capture["ui_failure_code"] == "captcha_required"
    login_receipt = json.loads((receipt_dir / "vidboard_login_capture.json").read_text(encoding="utf-8"))
    assert login_receipt["verified"] is False
    assert login_receipt["capture_path"] == output_path.as_posix()
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    assert handoff["status"] == "operator_action_required"
    assert handoff["failure_code"] == "captcha_required"
    assert handoff["capture_path"] == output_path.as_posix()


def test_generated_failed_receipts_do_not_promote_provider(tmp_path: Path) -> None:
    capture_module = _load_script()
    verify_module = _load_verify_script()
    output_path = tmp_path / "capture.json"
    receipt_dir = tmp_path / "receipts"
    capture_summary = capture_module._failed_capture_summary("template_worker_failed:captcha_required")
    capture_module._write_json(output_path, capture_summary)
    capture_sha = capture_module._sha256_file(output_path)
    receipt_dir.mkdir()
    for receipt_type in capture_module.RECEIPT_TYPES:
        capture_module._write_json(
            receipt_dir / f"vidboard_{receipt_type}.json",
            capture_module._receipt_payload(
                receipt_type,
                capture_summary,
                capture_path=output_path,
                capture_file_sha256=capture_sha,
            ),
        )

    payload = verify_module.build_payload("vidboard", allow_fallback=False, receipt_dir=receipt_dir)

    assert payload["verdict"] == "NOT_READY"
    assert payload["provider_ready"] is False
