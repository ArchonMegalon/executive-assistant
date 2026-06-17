from __future__ import annotations

from app.services import telegram_video_effects


def test_source_video_edit_supported_for_fire_request() -> None:
    assert telegram_video_effects.source_video_edit_supported(
        "Make the ring look like real flames and one shirt briefly catch fire."
    )


def test_source_video_edit_supported_rejects_plain_summary_request() -> None:
    assert not telegram_video_effects.source_video_edit_supported("Summarize this video for me.")
