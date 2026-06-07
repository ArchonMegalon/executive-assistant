from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "analyze_nonverbia_custom_project.py"
    spec = importlib.util.spec_from_file_location("analyze_nonverbia_custom_project", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_worker_summary_uses_real_worker_shape() -> None:
    module = _load_script()
    summary = module._worker_summary(
        {
            "render_status": "completed_with_warnings",
            "body_text": "Manfred memorial avatar presenter with video call options.",
            "editor_url": "https://app.nonverbia.com/projects/123",
            "asset_path": "/tmp/nonverbia/result.html",
            "structured_output_json": {
                "page_title": "Manfred Project",
                "url": "https://app.nonverbia.com/projects/123",
                "warnings": ["minor"],
                "errors": [],
                "screenshot_path": "/tmp/nonverbia/preview.png",
                "html_path": "/tmp/nonverbia/result.html",
            },
        }
    )

    assert summary["authenticated_workspace_detected"] is True
    assert summary["title"] == "Manfred Project"
    assert summary["url"] == "https://app.nonverbia.com/projects/123"
    assert summary["warnings"] == ["minor"]


def test_analysis_scores_named_project_and_avatar_markers() -> None:
    module = _load_script()
    analysis = module._analysis(
        {
            "authenticated_workspace_detected": True,
            "render_status": "completed",
            "title": "Manfred Memorial Presenter",
            "url": "https://app.nonverbia.com/projects/manfred-memorial",
            "body_excerpt": "Avatar video presenter with camera scene and talking host setup.",
        },
        project_name="Manfred Memorial",
        fit_keywords=["camera", "memorial"],
    )

    assert analysis["project_found"] is True
    assert analysis["fit_verdict"] == "strong_fit"
    assert "camera" in analysis["matched_fit_keywords"]
    assert "avatar" in analysis["avatar_markers"]


def test_failed_summary_marks_blocked_analysis() -> None:
    module = _load_script()
    summary = module._failed_summary("nonverbia_analysis_worker_failed:invalid_credentials")
    assert summary["authenticated_workspace_detected"] is False
    assert summary["ui_failure_code"] == "invalid_credentials"


def test_output_written_with_hash(tmp_path: Path) -> None:
    module = _load_script()
    payload = {
        "provider_key": "nonverbia",
        "analysis": {"fit_verdict": "possible_fit"},
    }
    path = tmp_path / "analysis.json"
    module._write_json(path, payload)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["provider_key"] == "nonverbia"
