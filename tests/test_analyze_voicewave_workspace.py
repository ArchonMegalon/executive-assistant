from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "analyze_voicewave_workspace.py"
    spec = importlib.util.spec_from_file_location("analyze_voicewave_workspace", path)
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
            "body_text": "Voice cloning, timeline editor, export wav mp3, commercial use, my voices.",
            "editor_url": "https://www.voicewave.ai/app",
            "asset_path": "/tmp/voicewave/result.html",
            "structured_output_json": {
                "page_title": "VoiceWave Studio",
                "url": "https://www.voicewave.ai/app",
                "warnings": ["minor"],
                "errors": [],
                "screenshot_path": "/tmp/voicewave/preview.png",
                "html_path": "/tmp/voicewave/result.html",
            },
        }
    )

    assert summary["authenticated_workspace_detected"] is True
    assert summary["title"] == "VoiceWave Studio"
    assert summary["url"] == "https://www.voicewave.ai/app"
    assert summary["warnings"] == ["minor"]


def test_worker_summary_rejects_marketing_homepage_as_authenticated_workspace() -> None:
    module = _load_script()
    summary = module._worker_summary(
        {
            "render_status": "completed",
            "body_text": "Get Lifetime Access. 7-day money back. AI voices for creators, marketers & businesses.",
            "editor_url": "https://www.voicewave.ai/",
            "structured_output_json": {
                "page_title": "AI Voices for Creators, Marketers & Businesses - VoiceWave.ai",
                "url": "https://www.voicewave.ai/",
                "warnings": [],
                "errors": [],
            },
        }
    )

    assert summary["authenticated_workspace_detected"] is False


def test_analysis_scores_workspace_voice_feature_markers() -> None:
    module = _load_script()
    analysis = module._analysis(
        {
            "authenticated_workspace_detected": True,
            "render_status": "completed",
            "title": "Manfred Memorial VoiceWave Studio",
            "url": "https://www.voicewave.ai/app/projects/manfred",
            "body_excerpt": "Voice cloning with timeline editor, export wav mp3, commercial use and custom voices.",
        },
        project_name="Manfred Memorial Voice",
        fit_keywords=["timeline", "export", "memorial"],
    )

    assert analysis["project_found"] is True
    assert analysis["fit_verdict"] == "strong_fit"
    assert "timeline" in analysis["matched_fit_keywords"]
    assert "voice" in analysis["feature_markers"]


def test_failed_summary_marks_blocked_analysis() -> None:
    module = _load_script()
    summary = module._failed_summary("voicewave_analysis_worker_failed:invalid_credentials")
    assert summary["authenticated_workspace_detected"] is False
    assert summary["ui_failure_code"] == "invalid_credentials"


def test_output_written_with_hash(tmp_path: Path) -> None:
    module = _load_script()
    payload = {
        "provider_key": "voicewave",
        "analysis": {"fit_verdict": "possible_fit"},
    }
    path = tmp_path / "analysis.json"
    module._write_json(path, payload)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["provider_key"] == "voicewave"
