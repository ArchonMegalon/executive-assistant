from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Any


EXPLICIT_CHROMIUM_EXECUTABLE_ENV = "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"


def resolve_chromium_executable(playwright: Any) -> tuple[str | None, str]:
    """Resolve an executable Chromium without depending on test-only helpers."""

    configured = str(os.getenv(EXPLICIT_CHROMIUM_EXECUTABLE_ENV) or "").strip()
    if configured:
        return configured, "explicit_env"

    default_path = Path(
        str(getattr(playwright.chromium, "executable_path", "") or "")
    ).expanduser()
    if default_path.is_file() and os.access(default_path, os.X_OK):
        return str(default_path), "playwright_default"

    cache_root = Path(
        str(os.getenv("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
        or (Path.home() / ".cache" / "ms-playwright")
    ).expanduser()
    if cache_root.is_dir():
        version_dirs = sorted(
            (
                item
                for item in cache_root.iterdir()
                if item.is_dir()
                and item.name.startswith(("chromium-", "chromium_headless_shell-"))
            ),
            key=lambda item: item.name,
            reverse=True,
        )
        for version_dir in version_dirs:
            for relative in (
                Path("chrome-linux64/chrome"),
                Path("chrome-linux/chrome"),
                Path("chrome-headless-shell-linux64/chrome-headless-shell"),
                Path("chrome-headless-shell-linux/chrome-headless-shell"),
            ):
                candidate = version_dir / relative
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return str(candidate), "playwright_cache"

    for command in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ):
        candidate = shutil.which(command)
        if candidate:
            return candidate, "system_path"
    return None, "playwright_unresolved"
