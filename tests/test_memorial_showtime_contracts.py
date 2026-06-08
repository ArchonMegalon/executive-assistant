from __future__ import annotations

import argparse
import json
from pathlib import Path


def test_showtime_builds_live_steps(tmp_path: Path) -> None:
    import scripts.memorial_showtime as showtime

    args = argparse.Namespace(
        slug="manfred",
        base_url="https://example.test",
        questions="",
        skip_tts=False,
        skip_chat=False,
        skip_unit_contracts=False,
        skip_snapshot=False,
        skip_exit_gates=True,
        optional_exit_gates=False,
    )

    steps = showtime.build_steps(args, tmp_path)
    names = [step.name for step in steps]

    assert "filesystem_preflight" in names
    assert "live_preflight" in names
    assert "live_demo_rehearsal" in names
    assert "launch_snapshot" in names
    assert "full_exit_gates" not in names


def test_showtime_report_status_transitions(tmp_path: Path) -> None:
    import scripts.memorial_showtime as showtime

    report = showtime.ShowtimeReport(slug="manfred", base_url="", started_at_epoch=1, output_dir=str(tmp_path))
    report.results.append(showtime.ShowtimeResult("ok", ["true"], str(tmp_path), "required", 0, 1))
    assert report.status == "pass"

    report.results.append(showtime.ShowtimeResult("warn", ["true"], str(tmp_path), "warning", 0, 1, semantic_status="warn"))
    assert report.status == "warn"

    report.results.append(showtime.ShowtimeResult("fail", ["false"], str(tmp_path), "required", 1, 1))
    assert report.status == "fail"


def test_showtime_warns_when_json_semantic_status_warn(tmp_path: Path) -> None:
    import scripts.memorial_showtime as showtime

    json_payload = {"status": "warn", "checks": [{"status": "warn", "code": "difficult_memory_guardrail_unclear"}]}
    result = showtime.ShowtimeResult(
        name="live_demo_rehearsal",
        command=["python3", "scripts/memorial_demo_rehearsal.py"],
        cwd=str(tmp_path),
        gate="required",
        returncode=0,
        duration_ms=1,
        stdout_tail=json.dumps(json_payload),
    )
    payload = showtime._extract_json_payload(result)
    semantic_status, semantic_detail = showtime._semantic_from_payload(payload)
    result.semantic_status = semantic_status
    result.semantic_detail = semantic_detail

    assert result.effective_status == "warn"
    assert result.semantic_detail["warn_codes"] == ["difficult_memory_guardrail_unclear"]


def test_showtime_adds_avatar_gate_when_optional_exit_gates_enabled(tmp_path: Path) -> None:
    import scripts.memorial_showtime as showtime

    args = argparse.Namespace(
        slug="manfred",
        base_url="https://example.test",
        questions="",
        skip_tts=False,
        skip_chat=False,
        skip_unit_contracts=False,
        skip_snapshot=False,
        skip_exit_gates=True,
        optional_exit_gates=True,
    )

    steps = showtime.build_steps(args, tmp_path)
    names = [step.name for step in steps]

    assert "avatar_video_call_status" in names
