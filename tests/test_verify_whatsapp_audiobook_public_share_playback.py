from __future__ import annotations

import pytest

from ea.scripts import verify_whatsapp_audiobook_public_share_playback as playback


def test_playback_probe_launches_the_resolved_installed_chromium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launched = object()

    class Chromium:
        def launch(self, **kwargs):  # type: ignore[no-untyped-def]
            assert kwargs == {
                "headless": True,
                "executable_path": "/usr/bin/chromium",
                "args": [
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--no-proxy-server",
                    "--autoplay-policy=no-user-gesture-required",
                    "--mute-audio",
                ],
            }
            return launched

    class Playwright:
        chromium = Chromium()

    monkeypatch.setattr(
        playback,
        "_resolve_chromium_executable",
        lambda _playwright: ("/usr/bin/chromium", "system:chromium"),
    )
    assert playback._launch_chromium(Playwright()) is launched


def test_playback_probe_fails_closed_without_a_chromium_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        playback,
        "_resolve_chromium_executable",
        lambda _playwright: (None, "unavailable"),
    )
    with pytest.raises(RuntimeError, match="playback_chromium_unavailable"):
        playback._launch_chromium(object())


def test_playback_probe_normalizes_chromium_launch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Chromium:
        def launch(self, **_kwargs):  # type: ignore[no-untyped-def]
            raise OSError("private host detail")

    class Playwright:
        chromium = Chromium()

    monkeypatch.setattr(
        playback,
        "_resolve_chromium_executable",
        lambda _playwright: ("/usr/bin/chromium", "system:chromium"),
    )
    with pytest.raises(RuntimeError, match="playback_chromium_launch_failed") as captured:
        playback._launch_chromium(Playwright())
    assert "private host detail" not in str(captured.value)
    assert captured.value.__cause__ is None
