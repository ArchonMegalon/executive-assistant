from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


_DISABLE_DEV_SHM_USAGE_ARG = "--disable-dev-shm-usage"
_FORCE_DEV_SHM_DISK_FALLBACK_ENV = "EA_BROWSER_FORCE_DISABLE_DEV_SHM_USAGE"
_EXPLICIT_CHROMIUM_EXECUTABLE_ENV = "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"
_MIN_DEV_SHM_AVAILABLE_BYTES = 512 * 1024 * 1024


def _env_flag_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _dev_shm_can_host_chromium() -> bool:
    path = "/dev/shm"
    try:
        return (
            os.path.isdir(path)
            and os.access(path, os.W_OK | os.X_OK)
            and shutil.disk_usage(path).free >= _MIN_DEV_SHM_AVAILABLE_BYTES
        )
    except OSError:
        return False


def browser_should_use_dev_shm() -> bool:
    """Apply the operator override and the host probe as one shared policy."""
    return not _env_flag_enabled(
        _FORCE_DEV_SHM_DISK_FALLBACK_ENV
    ) and _dev_shm_can_host_chromium()


@dataclass(slots=True)
class BrowserRuntimeRoot:
    path: Path
    uses_dev_shm: bool = False
    retain: bool = False


@contextmanager
def browser_ephemeral_runtime_root(
    fallback_root: Path,
) -> Iterator[BrowserRuntimeRoot]:
    """Yield disposable browser-test storage with deterministic cleanup."""
    runtime = BrowserRuntimeRoot(path=fallback_root)
    shared_memory_root: Path | None = None
    try:
        if browser_should_use_dev_shm():
            try:
                shared_memory_root = Path(
                    tempfile.mkdtemp(
                        prefix="ea-memorial-browser-",
                        dir="/dev/shm",
                    )
                )
            except OSError:
                pass
            else:
                runtime.path = shared_memory_root
                runtime.uses_dev_shm = True
        yield runtime
    finally:
        if shared_memory_root is not None and not runtime.retain:
            shutil.rmtree(shared_memory_root, ignore_errors=True)


def _chromium_launch_kwargs(args: Sequence[str]) -> dict[str, object]:
    normalized = list(args)
    use_dev_shm = browser_should_use_dev_shm()
    if use_dev_shm:
        normalized = [
            arg for arg in normalized if arg != _DISABLE_DEV_SHM_USAGE_ARG
        ]
    launch_kwargs: dict[str, object] = {
        "headless": True,
        "args": normalized,
    }
    if use_dev_shm:
        # Playwright adds this switch itself. Ignoring that exact default is
        # what moves Chromium IPC back to the verified shared-memory mount.
        launch_kwargs["ignore_default_args"] = [_DISABLE_DEV_SHM_USAGE_ARG]
    return launch_kwargs


def launch_installed_chromium(playwright: Any, *, args: Sequence[str]) -> Any:
    """Honor an explicit browser, else use Playwright then a resolved fallback."""
    from scripts.measure_memorial_live_browser import _resolve_chromium_executable

    launch_kwargs = _chromium_launch_kwargs(args)
    if str(os.getenv(_EXPLICIT_CHROMIUM_EXECUTABLE_ENV) or "").strip():
        executable_path, executable_source = _resolve_chromium_executable(playwright)
        if not executable_path:
            pytest.fail(
                "The explicitly configured Chromium runtime is unavailable "
                f"(resolver={executable_source})",
                pytrace=False,
            )
        explicit_error_type = ""
        try:
            return playwright.chromium.launch(
                **launch_kwargs,
                executable_path=executable_path,
            )
        except Exception as exc:
            explicit_error_type = type(exc).__name__
        pytest.fail(
            "The explicitly configured Chromium runtime could not be launched "
            f"(resolver={executable_source}, error_type={explicit_error_type})",
            pytrace=False,
        )

    native_error_type = ""
    try:
        return playwright.chromium.launch(**launch_kwargs)
    except Exception as exc:
        native_error_type = type(exc).__name__

    executable_path, executable_source = _resolve_chromium_executable(playwright)
    if not executable_path:
        pytest.fail(
            "No executable Chromium runtime is available for browser E2E tests "
            f"(native_error_type={native_error_type}, resolver={executable_source})",
            pytrace=False,
        )
    fallback_error_type = ""
    try:
        return playwright.chromium.launch(
            **launch_kwargs,
            executable_path=executable_path,
        )
    except Exception as exc:
        fallback_error_type = type(exc).__name__
    pytest.fail(
        "The resolved Chromium runtime could not be launched for browser E2E tests "
        f"(native_error_type={native_error_type}, resolver={executable_source}, "
        f"fallback_error_type={fallback_error_type})",
        pytrace=False,
    )
