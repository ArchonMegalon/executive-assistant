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
        avatar_required=False,
        avatar_optional=False,
    )

    steps = showtime.build_steps(args, tmp_path)
    names = [step.name for step in steps]

    assert "filesystem_preflight" in names
    assert "live_preflight" in names
    assert "live_demo_rehearsal" in names
    assert "voice_roundtrip_validation" in names
    assert "launch_snapshot" in names
    assert "full_exit_gates" not in names
    voice_step = next(step for step in steps if step.name == "voice_roundtrip_validation")
    snapshot_step = next(step for step in steps if step.name == "launch_snapshot")
    assert "--require-stt" in voice_step.command
    assert snapshot_step.parse_json_status is True
    assert snapshot_step.output_path_arg


def test_showtime_launch_mode_allows_exit_gate_skip_for_root_gate_recursion_guard(tmp_path: Path) -> None:
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
        avatar_required=False,
        avatar_optional=True,
    )

    steps = showtime.build_steps(args, tmp_path)
    names = [step.name for step in steps]

    assert "full_exit_gates" not in names
    assert "voice_roundtrip_validation" in names
    voice_step = next(step for step in steps if step.name == "voice_roundtrip_validation")
    assert "--require-stt" in voice_step.command


def test_showtime_allows_explicit_offline_stt_skip_outside_launch_mode(tmp_path: Path) -> None:
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
        allow_missing_stt=True,
        avatar_required=False,
        avatar_optional=False,
    )

    steps = showtime.build_steps(args, tmp_path)
    voice_step = next(step for step in steps if step.name == "voice_roundtrip_validation")

    assert "--require-stt" not in voice_step.command


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


def test_showtime_warns_when_launch_snapshot_json_status_warn(tmp_path: Path) -> None:
    import scripts.memorial_showtime as showtime

    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "status": "warn",
                "commands": [
                    {
                        "command": ["python3", "scripts/verify_memorial_video_call_avatar_ready.py"],
                        "returncode": 0,
                        "semantic_status": "warn",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = showtime.ShowtimeResult(
        name="launch_snapshot",
        command=["python3", "scripts/memorial_launch_snapshot.py"],
        cwd=str(tmp_path),
        gate="required",
        returncode=0,
        duration_ms=1,
    )
    payload = showtime._extract_json_payload(result, output_path_arg=str(snapshot_path))
    result.semantic_status, result.semantic_detail = showtime._semantic_from_payload(payload)

    assert result.effective_status == "warn"
    assert result.semantic_detail["command_count"] == 1
    assert result.semantic_detail["warn_commands"] == ["python3 scripts/verify_memorial_video_call_avatar_ready.py"]


def test_launch_snapshot_extracts_semantic_status_from_json_stdout() -> None:
    import scripts.memorial_launch_snapshot as snapshot

    status, detail = snapshot._extract_json_status(
        json.dumps(
            {
                "status": "warn",
                "findings": [
                    {"status": "pass", "code": "landing_available"},
                    {"status": "warn", "code": "avatar_video_not_published"},
                ],
            }
        )
    )

    assert status == "warn"
    assert detail["finding_count"] == 2
    assert detail["warn_codes"] == ["avatar_video_not_published"]


def test_launch_snapshot_status_uses_returncode_and_semantic_status() -> None:
    import scripts.memorial_launch_snapshot as snapshot

    assert snapshot.snapshot_status([{"returncode": 0}]) == "pass"
    assert snapshot.snapshot_status([{"returncode": 0, "semantic_status": "warn"}]) == "warn"
    assert snapshot.snapshot_status([{"returncode": 0, "semantic_status": "fail"}]) == "fail"
    assert snapshot.snapshot_status([{"returncode": 1, "semantic_status": "pass"}]) == "fail"


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
        avatar_required=False,
        avatar_optional=True,
    )

    steps = showtime.build_steps(args, tmp_path)
    names = [step.name for step in steps]

    assert "avatar_video_call_status" in names


def test_showtime_marks_avatar_gate_required_when_requested(tmp_path: Path) -> None:
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
        avatar_required=True,
        avatar_optional=False,
    )

    steps = showtime.build_steps(args, tmp_path)
    avatar_step = next(step for step in steps if step.name == "avatar_video_call_status")
    assert avatar_step.gate == "required"
