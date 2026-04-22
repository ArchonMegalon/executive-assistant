from __future__ import annotations

from scripts import browseract_template_service_worker as worker


def test_template_node_script_supports_playwright_proxy_launch() -> None:
    script = worker._template_node_script()
    assert "browser_proxy_server" in script
    assert "launchOptions.proxy" in script
    assert "proxyUsername" in script
