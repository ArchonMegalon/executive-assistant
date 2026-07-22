from __future__ import annotations

from scripts import browseract_template_service_worker as worker


def test_template_node_script_supports_playwright_proxy_launch() -> None:
    script = worker._template_node_script()
    assert "browser_proxy_server" in script
    assert "launchOptions.proxy" in script
    assert "proxyUsername" in script


def test_template_node_script_persists_progress_receipts() -> None:
    script = worker._template_node_script()
    assert "async function persistProgress" in script
    assert "render_status: 'running'" in script
    assert "await persistProgress(`node:" in script


def test_best_screenshot_path_falls_back_to_latest_trace(tmp_path) -> None:
    first_trace = tmp_path / "01-login.png"
    second_trace = tmp_path / "02-billing.png"
    first_trace.write_bytes(b"first")
    second_trace.write_bytes(b"second")

    resolved = worker._best_screenshot_path(
        preferred=tmp_path / "preview.png",
        output_dir=tmp_path,
    )

    assert resolved == str(second_trace)
