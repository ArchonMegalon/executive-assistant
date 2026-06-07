from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "capture_vidboard_provider_receipts.py"
    spec = importlib.util.spec_from_file_location("capture_vidboard_provider_receipts", path)
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
            "title": "VidBoard Dashboard",
            "body_text": "Avatar studio and export tools visible.",
            "url": "https://app.vidboard.ai/dashboard",
            "warnings": [],
            "errors": [],
        }
    )

    assert summary["provider_key"] == "vidboard"
    assert summary["authenticated_workspace_detected"] is True
    assert summary["render_status"] == "completed"


def test_login_capture_receipt_is_verified_only_after_authenticated_capture() -> None:
    module = _load_script()

    receipt = module._receipt_payload(
        "login_capture",
        {
            "captured_at": "2026-06-07T12:00:00Z",
            "authenticated_workspace_detected": True,
            "render_status": "completed",
            "url": "https://app.vidboard.ai/dashboard",
            "title": "VidBoard Dashboard",
        },
    )

    assert receipt["verified"] is True
    assert receipt["provider_key"] == "vidboard"


def test_manual_receipts_remain_unverified_and_write_to_disk(tmp_path: Path) -> None:
    module = _load_script()

    receipt = module._receipt_payload(
        "watermark_export_receipt",
        {
            "captured_at": "2026-06-07T12:00:00Z",
            "authenticated_workspace_detected": True,
            "render_status": "completed",
            "url": "https://app.vidboard.ai/dashboard",
            "title": "VidBoard Dashboard",
        },
    )
    path = tmp_path / "receipt.json"
    module._write_json(path, receipt)

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["verified"] is False
    assert loaded["receipt_type"] == "watermark_export_receipt"
