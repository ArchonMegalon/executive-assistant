from __future__ import annotations

from app.services import telegram_video_effects


def test_source_video_edit_supported_for_fire_request() -> None:
    assert telegram_video_effects.source_video_edit_supported(
        "Make the ring look like real flames and one shirt briefly catch fire."
    )


def test_source_video_edit_supported_rejects_plain_summary_request() -> None:
    assert not telegram_video_effects.source_video_edit_supported("Summarize this video for me.")


def test_parse_source_video_edit_plan_supports_combined_speed_and_audio_request() -> None:
    plan = telegram_video_effects.parse_source_video_edit_plan(
        "Make it faster and louder, but keep the same video."
    )
    assert plan["speed_factor"] > 1.0
    assert plan["audio_gain_db"] > 0.0


def test_supported_source_video_edit_summary_mentions_current_capabilities() -> None:
    summary = telegram_video_effects.supported_source_video_edit_summary()
    assert "flame" in summary
    assert "speed" in summary
    assert "audio" in summary
