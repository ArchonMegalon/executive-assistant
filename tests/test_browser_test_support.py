from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests import browser_test_support
from tests.browser_test_support import launch_installed_chromium


class _Chromium:
    def __init__(self, *, failures: tuple[Exception | None, ...] = ()) -> None:
        self.failures = list(failures)
        self.launch_calls: list[dict[str, object]] = []

    def launch(self, **kwargs):
        self.launch_calls.append(kwargs)
        failure = self.failures.pop(0) if self.failures else None
        if failure is not None:
            raise failure
        return "browser"


def test_launch_installed_chromium_prefers_playwright_pinned_runtime(monkeypatch) -> None:
    chromium = _Chromium()
    playwright = SimpleNamespace(chromium=chromium)
    monkeypatch.delenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", raising=False)
    monkeypatch.setattr(
        browser_test_support,
        "_dev_shm_can_host_chromium",
        lambda: False,
    )
    monkeypatch.setattr(
        browser_test_support,
        "_resolve_chromium_executable",
        lambda _playwright: pytest.fail("resolver should not run when Playwright's browser launches"),
    )

    result = launch_installed_chromium(playwright, args=("--no-sandbox",))

    assert result == "browser"
    assert chromium.launch_calls == [
        {
            "headless": True,
            "args": ["--no-sandbox"],
        }
    ]


def test_launch_installed_chromium_uses_resolved_fallback(monkeypatch) -> None:
    chromium = _Chromium(failures=(RuntimeError("missing pinned browser"), None))
    playwright = SimpleNamespace(chromium=chromium)
    monkeypatch.delenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", raising=False)
    monkeypatch.setattr(
        browser_test_support,
        "_dev_shm_can_host_chromium",
        lambda: False,
    )
    monkeypatch.setattr(
        browser_test_support,
        "_resolve_chromium_executable",
        lambda _playwright: ("/usr/bin/chromium", "system_path"),
    )

    result = launch_installed_chromium(playwright, args=("--no-sandbox",))

    assert result == "browser"
    assert chromium.launch_calls == [
        {"headless": True, "args": ["--no-sandbox"]},
        {
            "headless": True,
            "executable_path": "/usr/bin/chromium",
            "args": ["--no-sandbox"],
        },
    ]


def test_launch_installed_chromium_uses_large_shared_memory_for_both_launches(monkeypatch) -> None:
    chromium = _Chromium(failures=(RuntimeError("missing pinned browser"), None))
    playwright = SimpleNamespace(chromium=chromium)
    monkeypatch.delenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", raising=False)
    monkeypatch.delenv("EA_BROWSER_FORCE_DISABLE_DEV_SHM_USAGE", raising=False)
    monkeypatch.setattr(browser_test_support.os.path, "isdir", lambda path: path == "/dev/shm")
    monkeypatch.setattr(browser_test_support.os, "access", lambda path, _mode: path == "/dev/shm")
    monkeypatch.setattr(
        browser_test_support.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=512 * 1024 * 1024),
    )
    monkeypatch.setattr(
        browser_test_support,
        "_resolve_chromium_executable",
        lambda _playwright: ("/usr/bin/chromium", "system_path"),
    )

    result = launch_installed_chromium(
        playwright,
        args=("--first", "--disable-dev-shm-usage", "--last"),
    )

    assert result == "browser"
    assert chromium.launch_calls == [
        {
            "headless": True,
            "args": ["--first", "--last"],
            "ignore_default_args": ["--disable-dev-shm-usage"],
        },
        {
            "headless": True,
            "executable_path": "/usr/bin/chromium",
            "args": ["--first", "--last"],
            "ignore_default_args": ["--disable-dev-shm-usage"],
        },
    ]


def test_launch_installed_chromium_honors_explicit_executable_before_native(
    monkeypatch,
) -> None:
    chromium = _Chromium()
    playwright = SimpleNamespace(chromium=chromium)
    monkeypatch.setenv(
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
        "/opt/operator/chromium",
    )
    monkeypatch.setattr(
        browser_test_support,
        "_dev_shm_can_host_chromium",
        lambda: False,
    )
    monkeypatch.setattr(
        browser_test_support,
        "_resolve_chromium_executable",
        lambda _playwright: ("/opt/operator/chromium", "explicit_env"),
    )

    result = launch_installed_chromium(playwright, args=("--no-sandbox",))

    assert result == "browser"
    assert chromium.launch_calls == [
        {
            "headless": True,
            "args": ["--no-sandbox"],
            "executable_path": "/opt/operator/chromium",
        }
    ]


def test_launch_installed_chromium_redacts_explicit_executable_failure(
    monkeypatch,
) -> None:
    private_detail = "/home/operator/private/chromium: secret-token"
    chromium = _Chromium(failures=(RuntimeError(private_detail),))
    playwright = SimpleNamespace(chromium=chromium)
    monkeypatch.setenv(
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
        "/home/operator/private/chromium",
    )
    monkeypatch.setattr(
        browser_test_support,
        "_dev_shm_can_host_chromium",
        lambda: False,
    )
    monkeypatch.setattr(
        browser_test_support,
        "_resolve_chromium_executable",
        lambda _playwright: (
            "/home/operator/private/chromium",
            "explicit_env",
        ),
    )

    with pytest.raises(pytest.fail.Exception) as caught:
        launch_installed_chromium(playwright, args=())

    assert "resolver=explicit_env" in str(caught.value)
    assert "error_type=RuntimeError" in str(caught.value)
    assert private_detail not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    ("is_directory", "has_access", "available_bytes"),
    (
        (True, True, 512 * 1024 * 1024 - 1),
        (False, False, 0),
        (True, False, 1024 * 1024 * 1024),
    ),
    ids=("tiny", "missing", "unwritable"),
)
def test_launch_installed_chromium_retains_disk_fallback_when_shm_is_unsuitable(
    monkeypatch,
    is_directory: bool,
    has_access: bool,
    available_bytes: int,
) -> None:
    chromium = _Chromium()
    playwright = SimpleNamespace(chromium=chromium)
    monkeypatch.delenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", raising=False)
    monkeypatch.delenv("EA_BROWSER_FORCE_DISABLE_DEV_SHM_USAGE", raising=False)
    monkeypatch.setattr(browser_test_support.os.path, "isdir", lambda _path: is_directory)
    monkeypatch.setattr(browser_test_support.os, "access", lambda _path, _mode: has_access)
    monkeypatch.setattr(
        browser_test_support.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=available_bytes),
    )

    result = launch_installed_chromium(
        playwright,
        args=("--first", "--disable-dev-shm-usage", "--last"),
    )

    assert result == "browser"
    assert chromium.launch_calls == [
        {
            "headless": True,
            "args": ["--first", "--disable-dev-shm-usage", "--last"],
        }
    ]


def test_launch_installed_chromium_override_retains_disk_fallback(monkeypatch) -> None:
    chromium = _Chromium()
    playwright = SimpleNamespace(chromium=chromium)
    monkeypatch.delenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", raising=False)
    monkeypatch.setenv("EA_BROWSER_FORCE_DISABLE_DEV_SHM_USAGE", "true")
    monkeypatch.setattr(
        browser_test_support,
        "_dev_shm_can_host_chromium",
        lambda: pytest.fail("override should bypass shared-memory probing"),
    )

    result = launch_installed_chromium(
        playwright,
        args=("--first", "--disable-dev-shm-usage", "--last"),
    )

    assert result == "browser"
    assert chromium.launch_calls == [
        {
            "headless": True,
            "args": ["--first", "--disable-dev-shm-usage", "--last"],
        }
    ]


def test_browser_ephemeral_runtime_root_cleans_after_setup_failure(
    monkeypatch,
    tmp_path,
) -> None:
    shared_memory_root = tmp_path / "simulated-shared-memory"
    monkeypatch.setattr(
        browser_test_support,
        "browser_should_use_dev_shm",
        lambda: True,
    )

    def fake_mkdtemp(**_kwargs) -> str:
        shared_memory_root.mkdir()
        return str(shared_memory_root)

    monkeypatch.setattr(browser_test_support.tempfile, "mkdtemp", fake_mkdtemp)

    with pytest.raises(RuntimeError, match="forced fixture setup failure"):
        with browser_test_support.browser_ephemeral_runtime_root(
            tmp_path / "fallback"
        ) as runtime:
            assert runtime.path == shared_memory_root
            assert runtime.uses_dev_shm is True
            raise RuntimeError("forced fixture setup failure")

    assert not shared_memory_root.exists()


def test_browser_runtime_root_honors_forced_disk_fallback(
    monkeypatch,
    tmp_path,
) -> None:
    fallback_root = tmp_path / "fallback"
    monkeypatch.setenv("EA_BROWSER_FORCE_DISABLE_DEV_SHM_USAGE", "true")
    monkeypatch.setattr(
        browser_test_support,
        "_dev_shm_can_host_chromium",
        lambda: pytest.fail("operator override should bypass shared-memory probing"),
    )

    with browser_test_support.browser_ephemeral_runtime_root(
        fallback_root
    ) as runtime:
        assert runtime.path == fallback_root
        assert runtime.uses_dev_shm is False


def test_browser_ephemeral_runtime_root_retains_live_thread_diagnostics(
    monkeypatch,
    tmp_path,
) -> None:
    shared_memory_root = tmp_path / "retained-shared-memory"
    monkeypatch.setattr(
        browser_test_support,
        "browser_should_use_dev_shm",
        lambda: True,
    )

    def fake_mkdtemp(**_kwargs) -> str:
        shared_memory_root.mkdir()
        return str(shared_memory_root)

    monkeypatch.setattr(browser_test_support.tempfile, "mkdtemp", fake_mkdtemp)

    try:
        with browser_test_support.browser_ephemeral_runtime_root(
            tmp_path / "fallback"
        ) as runtime:
            runtime.retain = True
        assert shared_memory_root.is_dir()
    finally:
        browser_test_support.shutil.rmtree(
            shared_memory_root,
            ignore_errors=True,
        )


def test_launch_installed_chromium_fails_closed_without_runtime(monkeypatch) -> None:
    chromium = _Chromium(failures=(RuntimeError("missing pinned browser"),))
    playwright = SimpleNamespace(chromium=chromium)
    monkeypatch.delenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", raising=False)
    monkeypatch.setattr(
        browser_test_support,
        "_dev_shm_can_host_chromium",
        lambda: False,
    )
    monkeypatch.setattr(
        browser_test_support,
        "_resolve_chromium_executable",
        lambda _playwright: (None, "unavailable"),
    )

    with pytest.raises(pytest.fail.Exception, match="No executable Chromium runtime"):
        launch_installed_chromium(playwright, args=())

    assert chromium.launch_calls == [{"headless": True, "args": []}]


def test_launch_installed_chromium_redacts_launch_failure(monkeypatch) -> None:
    private_detail = "/home/operator/private/chromium: secret-token"
    chromium = _Chromium(
        failures=(
            RuntimeError(private_detail),
            ValueError(private_detail),
        )
    )
    playwright = SimpleNamespace(chromium=chromium)
    monkeypatch.delenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", raising=False)
    monkeypatch.setattr(
        browser_test_support,
        "_dev_shm_can_host_chromium",
        lambda: False,
    )
    monkeypatch.setattr(
        browser_test_support,
        "_resolve_chromium_executable",
        lambda _playwright: ("/usr/bin/chromium", "system_path"),
    )

    with pytest.raises(pytest.fail.Exception) as caught:
        launch_installed_chromium(playwright, args=())

    assert "native_error_type=RuntimeError" in str(caught.value)
    assert "fallback_error_type=ValueError" in str(caught.value)
    assert private_detail not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_launch_installed_chromium_effective_command_uses_verified_dev_shm(
    monkeypatch,
) -> None:
    if not browser_test_support._dev_shm_can_host_chromium():
        pytest.skip("host shared memory is not suitable for Chromium")
    sync_api = pytest.importorskip("playwright.sync_api")
    monkeypatch.delenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", raising=False)
    monkeypatch.delenv("EA_BROWSER_FORCE_DISABLE_DEV_SHM_USAGE", raising=False)

    with sync_api.sync_playwright() as playwright:
        browser = launch_installed_chromium(
            playwright,
            args=(
                "--no-sandbox",
                "--enable-automation",
                "--disable-dev-shm-usage",
            ),
        )
        try:
            session = browser.new_browser_cdp_session()
            command = session.send("Browser.getBrowserCommandLine")
        finally:
            browser.close()

    assert "--disable-dev-shm-usage" not in command["arguments"]
