from __future__ import annotations

from pathlib import Path


def _approved_source() -> dict[str, object]:
    return {
        "approved": True,
        "source_id": "origin-dossier-ashline",
        "title": "Ashline Circle Signal",
        "summary": "A faction promo packet about a rumor pattern that turns into a public hook.",
        "language": "en-US",
        "topic": "faction promo",
        "source_anchor_ids": ["packet:ashline", "brief:public"],
        "narrator_posture": "continuous_cinematic_narrator",
    }


def test_cinematic_narration_window_requires_approved_source() -> None:
    from app.services.cinematic_narration_pipeline import build_cinematic_narration_window

    window = build_cinematic_narration_window(
        source_packet={"source_id": "draft-only", "summary": "Unreviewed draft"},
        scene_signal={"focus": "the scene"},
        generated_at="2026-06-19T12:00:00Z",
    )

    assert window["status"] == "blocked"
    assert window["reason"] == "approved_source_packet_required"
    assert window["ea_is_product_truth"] is False
    assert window["provider_output_truth_allowed"] is False


def test_cinematic_narration_window_is_scene_conditioned_but_not_scene_bound() -> None:
    from app.services.cinematic_narration_pipeline import build_cinematic_narration_window

    window = build_cinematic_narration_window(
        source_packet=_approved_source(),
        rolling_state={
            "recent_summary": "The narrator established the rainy public hook.",
            "continuity_callbacks": ["rain on glass"],
            "narrator_posture": "continuous_cinematic_narrator",
        },
        scene_signal={
            "focus": "a torn faction mark on the transit shelter",
            "stakes": "the rumor is becoming visible",
            "mood": "tense public pressure",
            "intensity": "rising",
            "tempo": "measured",
        },
        generated_at="2026-06-19T12:00:00Z",
    )

    assert window["status"] == "planned"
    assert window["scene_bound"] is False
    assert window["current_scene_conditioned"] is True
    assert window["rolling_state_preserved"] is True
    assert "torn faction mark" in window["script_text"]
    assert "rain on glass" in str(window["script_text"]).lower()
    assert window["narrator_posture"] == "continuous_cinematic_narrator"
    assert window["scene_signal_is_canon"] is False
    assert window["provider_output_truth_allowed"] is False


def test_cinematic_narration_state_chains_windows_without_resetting_narrator() -> None:
    from app.services.cinematic_narration_pipeline import (
        build_cinematic_narration_receipt,
        build_cinematic_narration_window,
        update_rolling_narration_state,
    )

    source = _approved_source()
    initial_state = {
        "recent_summary": "The city heard the first rumor.",
        "continuity_callbacks": ["neon rain"],
        "narrator_posture": "continuous_cinematic_narrator",
    }
    first = build_cinematic_narration_window(
        source_packet=source,
        rolling_state=initial_state,
        scene_signal={"focus": "the first public clue", "stakes": "a quiet escalation"},
        generated_at="2026-06-19T12:00:00Z",
    )
    state_after_first = update_rolling_narration_state(rolling_state=initial_state, window=first)
    second = build_cinematic_narration_window(
        source_packet=source,
        rolling_state=state_after_first,
        scene_signal={"focus": "the team choosing an angle", "stakes": "the hook is now actionable"},
        generated_at="2026-06-19T12:00:10Z",
    )
    state_after_second = update_rolling_narration_state(rolling_state=state_after_first, window=second)
    receipt = build_cinematic_narration_receipt(
        window=second,
        rolling_state_before=state_after_first,
        rolling_state_after=state_after_second,
        generated_at="2026-06-19T12:00:11Z",
    )

    assert second["window_index"] == 2
    assert second["previous_window_digest"] == first["window_digest"]
    assert second["narrator_posture"] == first["narrator_posture"]
    assert second["scene_signal_digest"] != first["scene_signal_digest"]
    assert state_after_second["last_window_digest"] == second["window_digest"]
    assert receipt["status"] == "pass"
    assert receipt["scene_bound"] is False
    assert receipt["current_scene_conditioned"] is True
    assert receipt["rolling_state_preserved"] is True
    assert receipt["narrator_posture_stable"] is True
    assert receipt["raw_source_text_exposed"] is False
    assert receipt["raw_scene_private_context_exposed"] is False
    assert receipt["scene_signal_is_canon"] is False
    assert receipt["provider_output_truth_allowed"] is False


def test_cinematic_narration_segment_append_renders_scene_conditioned_audio_receipt(tmp_path: Path) -> None:
    from app.services.cinematic_narration_pipeline import append_cinematic_narration_segment

    audio_path = tmp_path / "segment-001.wav"
    audio_path.write_bytes(b"audio bytes for the first rolling narration segment")
    rendered_scripts: list[str] = []

    def render_audio(window: dict[str, object]) -> dict[str, object]:
        rendered_scripts.append(str(window["script_text"]))
        return {
            "status": "ok",
            "audio_path": str(audio_path),
            "duration_seconds": window["expected_duration_seconds"],
            "audio_quality": {"status": "pass", "issues": []},
        }

    append = append_cinematic_narration_segment(
        source_packet=_approved_source(),
        rolling_state={
            "recent_summary": "The narrator established the public hook.",
            "continuity_callbacks": ["neon rain"],
            "narrator_posture": "continuous_cinematic_narrator",
        },
        scene_signal={
            "focus": "the crew sees the source marker",
            "stakes": "the hook now has a verifiable trail",
            "target_duration_seconds": 10,
        },
        render_audio=render_audio,
        generated_at="2026-06-19T12:00:00Z",
    )

    segment = append["segment"]
    assert append["status"] == "ready"
    assert append["render_called"] is True
    assert rendered_scripts and "source marker" in rendered_scripts[0]
    assert segment["status"] == "ready"  # type: ignore[index]
    assert segment["scene_bound"] is False  # type: ignore[index]
    assert segment["current_scene_conditioned"] is True  # type: ignore[index]
    assert segment["rolling_state_preserved"] is True  # type: ignore[index]
    assert segment["audio_file"] == "segment-001.wav"  # type: ignore[index]
    assert segment["audio_sha256"]  # type: ignore[index]
    assert segment["audio_path_exposed"] is False  # type: ignore[index]
    assert segment["raw_provider_voice_id_exposed"] is False  # type: ignore[index]
    assert segment["provider_output_truth_allowed"] is False  # type: ignore[index]
    assert segment["quality_gate"]["status"] == "pass"  # type: ignore[index]
    assert append["rolling_state_after"]["last_window_digest"] == append["window"]["window_digest"]  # type: ignore[index]


def test_cinematic_narration_segment_chain_preserves_previous_segment_continuity(tmp_path: Path) -> None:
    from app.services.cinematic_narration_pipeline import append_cinematic_narration_segment

    source = _approved_source()
    state = {
        "recent_summary": "The city heard the first rumor.",
        "continuity_callbacks": ["rain on glass"],
        "narrator_posture": "continuous_cinematic_narrator",
    }

    def render_audio(window: dict[str, object]) -> dict[str, object]:
        audio_path = tmp_path / f"{window['window_id']}.wav"
        audio_path.write_bytes(str(window["window_digest"]).encode("utf-8"))
        return {
            "status": "ok",
            "audio_path": str(audio_path),
            "duration_seconds": window["expected_duration_seconds"],
            "audio_quality": {"status": "pass", "issues": []},
        }

    first = append_cinematic_narration_segment(
        source_packet=source,
        rolling_state=state,
        scene_signal={"focus": "the first visible clue", "stakes": "a quiet escalation"},
        render_audio=render_audio,
        generated_at="2026-06-19T12:00:00Z",
    )
    second = append_cinematic_narration_segment(
        source_packet=source,
        rolling_state=first["rolling_state_after"],  # type: ignore[arg-type]
        scene_signal={"focus": "the next angle", "stakes": "the signal becomes actionable"},
        render_audio=render_audio,
        previous_segment=first["segment"],  # type: ignore[arg-type]
        generated_at="2026-06-19T12:00:10Z",
        planned_crossfade_ms=480,
    )

    assert second["status"] == "ready"
    assert second["window"]["previous_window_digest"] == first["window"]["window_digest"]  # type: ignore[index]
    assert second["segment"]["previous_segment_digest"] == first["segment"]["segment_digest"]  # type: ignore[index]
    assert second["segment"]["continuity_gate"]["status"] == "pass"  # type: ignore[index]
    assert second["segment"]["continuity_gate"]["crossfade_ms"] == 480  # type: ignore[index]
    assert second["rolling_state_after"]["last_window_digest"] == second["window"]["window_digest"]  # type: ignore[index]


def test_cinematic_narration_segment_blocks_bad_audio_quality_and_provider_truth(tmp_path: Path) -> None:
    from app.services.cinematic_narration_pipeline import append_cinematic_narration_segment

    audio_path = tmp_path / "quiet-tail.wav"
    audio_path.write_bytes(b"quiet ending")

    def render_audio(window: dict[str, object]) -> dict[str, object]:
        return {
            "status": "ok",
            "audio_path": str(audio_path),
            "duration_seconds": window["expected_duration_seconds"],
            "provider_output_truth_allowed": True,
            "audio_quality": {"status": "fail", "issues": ["quiet_tail"], "quiet_tail": True},
        }

    append = append_cinematic_narration_segment(
        source_packet=_approved_source(),
        rolling_state={"narrator_posture": "continuous_cinematic_narrator"},
        scene_signal={"focus": "the current pressure", "stakes": "the tone needs repair"},
        render_audio=render_audio,
        generated_at="2026-06-19T12:00:00Z",
    )

    assert append["status"] == "blocked"
    assert append["rolling_state_after"] == append["rolling_state_before"]
    assert "provider_output_truth_claim_forbidden" in append["blocking_reasons"]
    assert "audio_quality_quiet_tail" in append["blocking_reasons"]
    assert append["segment"]["quality_gate"]["quiet_tail"] is True  # type: ignore[index]
    assert append["segment"]["next_action"] == "rerender_or_repair_segment"  # type: ignore[index]
