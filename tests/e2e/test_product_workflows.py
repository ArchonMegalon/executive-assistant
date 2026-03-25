from __future__ import annotations

import os
import socket
import threading
import time
import urllib.request
import zlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from uvicorn import Config, Server

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from app.api.app import create_app
from tests.product_test_helpers import seed_founder_fixture, seed_product_state, seed_team_fixture


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _wait_for_http(base_url: str, *, timeout_seconds: float = 15.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/", timeout=2.0) as response:
                if int(getattr(response, "status", 0) or 0) == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise AssertionError(f"server at {base_url} did not become ready in time")


def _truthy_env(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _png_visual_bytes(value: bytes) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    if not value.startswith(signature):
        return value
    cursor = len(signature)
    ihdr = b""
    idat_parts: list[bytes] = []
    while cursor + 8 <= len(value):
        length = int.from_bytes(value[cursor : cursor + 4], "big")
        chunk_type = value[cursor + 4 : cursor + 8]
        data_start = cursor + 8
        data_end = data_start + length
        chunk_data = value[data_start:data_end]
        cursor = data_end + 4
        if chunk_type == b"IHDR":
            ihdr = chunk_data
        elif chunk_type == b"IDAT":
            idat_parts.append(chunk_data)
        elif chunk_type == b"IEND":
            break
    if not ihdr or not idat_parts:
        return value
    return ihdr + zlib.decompress(b"".join(idat_parts))


def _assert_visual_baseline(page: Page, snapshot_name: str) -> None:
    baseline_dir = Path(__file__).resolve().with_name("visual_baselines")
    baseline_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = baseline_dir / snapshot_name
    actual = page.screenshot(full_page=True, animations="disabled", caret="hide")
    if _truthy_env("EA_UPDATE_VISUAL_BASELINES") or not baseline_path.exists():
        baseline_path.write_bytes(actual)
    expected = baseline_path.read_bytes()
    actual_visual = _png_visual_bytes(actual)
    expected_visual = _png_visual_bytes(expected)
    if actual_visual == expected_visual:
        return
    overlap = min(len(actual_visual), len(expected_visual))
    diff = abs(len(actual_visual) - len(expected_visual))
    diff += sum(1 for index in range(overlap) if actual_visual[index] != expected_visual[index])
    allowed = max(4096, int(max(len(actual_visual), len(expected_visual)) * 0.002))
    assert diff <= allowed


def _start_browser_server(client: TestClient, *, seeded: dict[str, object]) -> Iterator[dict[str, object]]:
    app = client.app
    port = _free_port()
    config = Config(app=app, host="127.0.0.1", port=port, log_level="warning")
    server = Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    _wait_for_http(base_url)
    try:
        yield {
            "base_url": base_url,
            "seeded": seeded,
        }
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)


@pytest.fixture()
def product_browser_server() -> Iterator[dict[str, object]]:
    os.environ["EA_STORAGE_BACKEND"] = "memory"
    os.environ.pop("EA_LEDGER_BACKEND", None)
    os.environ["EA_API_TOKEN"] = ""
    os.environ["EA_DEFAULT_PRINCIPAL_ID"] = "local-user"
    os.environ["EA_ALLOW_LOOPBACK_NO_AUTH"] = "1"
    os.environ["EA_ENABLE_PUBLIC_SIDE_SURFACES"] = "0"
    os.environ["EA_ENABLE_PUBLIC_RESULTS"] = "0"
    os.environ["EA_ENABLE_PUBLIC_TOURS"] = "0"

    app = create_app()
    client = TestClient(app)
    client.headers.update({"X-EA-Principal-ID": "local-user"})
    seeded = seed_product_state(client, principal_id="local-user")
    started = client.post(
        "/v1/onboarding/start",
        json={
            "workspace_name": "Executive Assistant",
            "mode": "executive_ops",
            "workspace_mode": "executive_ops",
            "timezone": "Europe/Vienna",
            "region": "AT",
            "language": "en",
            "selected_channels": ["google"],
        },
    )
    assert started.status_code == 200

    yield from _start_browser_server(client, seeded=seeded)


@pytest.fixture()
def founder_browser_server() -> Iterator[dict[str, object]]:
    os.environ["EA_ALLOW_LOOPBACK_NO_AUTH"] = "1"
    os.environ["EA_DEFAULT_PRINCIPAL_ID"] = "fixture-founder-browser"
    os.environ["EA_ENABLE_PUBLIC_SIDE_SURFACES"] = "0"
    os.environ["EA_ENABLE_PUBLIC_RESULTS"] = "0"
    os.environ["EA_ENABLE_PUBLIC_TOURS"] = "0"
    client, seeded = seed_founder_fixture(principal_id="fixture-founder-browser")
    yield from _start_browser_server(client, seeded=seeded)


@pytest.fixture()
def team_browser_server() -> Iterator[dict[str, object]]:
    os.environ["EA_ALLOW_LOOPBACK_NO_AUTH"] = "1"
    os.environ["EA_DEFAULT_PRINCIPAL_ID"] = "fixture-team-browser"
    os.environ["EA_ENABLE_PUBLIC_SIDE_SURFACES"] = "0"
    os.environ["EA_ENABLE_PUBLIC_RESULTS"] = "0"
    os.environ["EA_ENABLE_PUBLIC_TOURS"] = "0"
    client, seeded = seed_team_fixture(principal_id="fixture-team-browser")
    yield from _start_browser_server(client, seeded=seeded)


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture()
def page(browser: Browser, product_browser_server: dict[str, object]) -> Iterator[Page]:
    context: BrowserContext = browser.new_context()
    page = context.new_page()
    try:
        yield page
    finally:
        context.close()


def test_activation_and_memo_flow_in_real_browser(page: Page, product_browser_server: dict[str, object]) -> None:
    base_url = str(product_browser_server["base_url"])

    response = page.goto(f"{base_url}/get-started", wait_until="networkidle")
    assert response is not None and response.ok
    assert "Connect Google" in page.content()
    assert "Add channels later" in page.content()
    assert "Rules after first value" in page.content()
    assert "Current plan posture" in page.content()
    assert "Open workspace diagnostics" in page.content()

    response = page.goto(f"{base_url}/app/today", wait_until="networkidle")
    assert response is not None and response.ok
    assert "Morning Memo" in page.content()
    assert "Send board materials" in page.content()
    assert "Approve reply to Sofia N." in page.content()

    page.get_by_role("link", name="Sofia N.").first.click()
    page.wait_for_load_state("networkidle")
    assert "/app/people/" in page.url
    assert "Open commitments" in page.content()
    assert "Why the product surfaced this person" in page.content()

    response = page.goto(f"{base_url}/app/activity", wait_until="networkidle")
    assert response is not None and response.ok
    assert "Operator Queue" in page.content()
    assert "Prepare board follow-up handoff" in page.content()

    response = page.goto(f"{base_url}/app/settings", wait_until="networkidle")
    assert response is not None and response.ok
    assert "Rules" in page.content()
    assert "Workspace diagnostics bundle" in page.content()
    assert "Messaging scope" in page.content()
    assert "Draft approval" in page.content()
    assert "Google-first activation" in page.content()


def test_draft_and_commitment_workflows_in_real_browser(page: Page, product_browser_server: dict[str, object]) -> None:
    base_url = str(product_browser_server["base_url"])

    response = page.goto(f"{base_url}/app/inbox", wait_until="networkidle")
    assert response is not None and response.ok
    assert "sofia@example.com" in page.content()
    with page.expect_response(lambda value: "/app/actions/drafts/" in value.url) as approval_response:
        page.locator(".console-row", has_text="sofia@example.com").get_by_role("button", name="Approve").click()
    assert approval_response.value.status == 303
    page.wait_for_url(f"{base_url}/app/inbox")
    page.wait_for_load_state("networkidle")

    response = page.goto(f"{base_url}/app/briefing", wait_until="networkidle")
    assert response is not None and response.ok
    assert "Approve reply to Sofia N." not in page.content()
    assert "Choose board memo owner" in page.content()

    response = page.goto(f"{base_url}/app/inbox", wait_until="networkidle")
    assert response is not None and response.ok
    with page.expect_response(lambda value: "/app/actions/queue/" in value.url) as close_response:
        page.locator(".console-row", has_text="Send board materials").get_by_role("button", name="Close").first.click()
    assert close_response.value.status == 303
    page.wait_for_url(f"{base_url}/app/inbox")
    page.wait_for_load_state("networkidle")
    assert "Send board materials" not in page.content()

    page.locator("#extract_source_text").fill("Please send the revised board packet to Sofia tomorrow morning.")
    page.locator("#extract_counterparty").fill("Sofia N.")
    with page.expect_response(lambda value: "/app/actions/commitments/extract" in value.url and value.request.method == "POST") as extract_response:
        page.get_by_role("button", name="Capture item").click()
    assert extract_response.value.status == 303
    page.wait_for_url(f"{base_url}/app/inbox")
    page.wait_for_load_state("networkidle")
    assert "revised board packet" in page.content().lower()
    with page.expect_response(lambda value: "/app/actions/commitments/candidates/" in value.url and value.request.method == "POST") as accept_response:
        page.locator(".console-row", has_text="revised board packet").get_by_role("button", name="Accept").first.click()
    assert accept_response.value.status == 303
    page.wait_for_url(f"{base_url}/app/inbox")
    page.wait_for_load_state("networkidle")
    assert "revised board packet" in page.content().lower()

    response = page.goto(f"{base_url}/app/contacts", wait_until="networkidle")
    assert response is not None and response.ok
    assert "Evidence" in page.content()
    assert "Decision window" in page.content() or "Commitment" in page.content()


def test_draft_rejection_in_real_browser(page: Page, product_browser_server: dict[str, object]) -> None:
    base_url = str(product_browser_server["base_url"])

    response = page.goto(f"{base_url}/app/inbox", wait_until="networkidle")
    assert response is not None and response.ok
    assert "sofia@example.com" in page.content()
    with page.expect_response(lambda value: "/app/actions/drafts/" in value.url and value.request.method == "POST") as reject_response:
        page.locator(".console-row", has_text="sofia@example.com").get_by_role("button", name="Reject").click()
    assert reject_response.value.status == 303
    page.wait_for_url(f"{base_url}/app/inbox")
    page.wait_for_load_state("networkidle")
    assert "sofia@example.com" not in page.content()


def test_follow_up_drop_in_real_browser(page: Page, product_browser_server: dict[str, object]) -> None:
    base_url = str(product_browser_server["base_url"])

    response = page.goto(f"{base_url}/app/follow-ups", wait_until="networkidle")
    assert response is not None and response.ok
    assert "Confirm investor meeting time" in page.content()
    with page.expect_response(lambda value: "/app/actions/queue/follow_up:" in value.url and value.request.method == "POST") as drop_response:
        page.locator(".console-row", has_text="Confirm investor meeting time").get_by_role("button", name="Drop").first.click()
    assert drop_response.value.status == 303
    page.wait_for_url(f"{base_url}/app/follow-ups")
    page.wait_for_load_state("networkidle")
    assert "Confirm investor meeting time" not in page.content()


def test_admin_audit_surface_renders_in_real_browser(page: Page, product_browser_server: dict[str, object]) -> None:
    base_url = str(product_browser_server["base_url"])

    response = page.goto(f"{base_url}/admin/audit-trail", wait_until="networkidle")
    assert response is not None and response.ok
    assert "Audit Trail" in page.content()
    assert "Operator Control Plane" in page.content()


def test_admin_operator_queue_actions_in_real_browser(page: Page, product_browser_server: dict[str, object]) -> None:
    base_url = str(product_browser_server["base_url"])

    response = page.goto(f"{base_url}/admin/operators", wait_until="networkidle")
    assert response is not None and response.ok
    assert "Team / Operators" in page.content()

    with page.expect_response(lambda value: "/app/actions/handoffs/" in value.url and value.request.method == "POST") as claim_response:
        page.locator(".console-row", has_text="Prepare board follow-up handoff").get_by_role("button", name="Claim").first.click()
    assert claim_response.value.status == 303

    with page.expect_response(lambda value: "/app/actions/handoffs/" in value.url and value.request.method == "POST") as complete_response:
        page.locator(".console-row", has_text="Prepare board follow-up handoff").get_by_role("button", name="Complete").first.click()
    assert complete_response.value.status == 303
    page.goto(f"{base_url}/app/activity", wait_until="networkidle")
    assert "Recently completed" in page.content()
    assert "Prepare board follow-up handoff" in page.content()


def test_admin_diagnostics_bundle_in_real_browser(page: Page, product_browser_server: dict[str, object]) -> None:
    base_url = str(product_browser_server["base_url"])

    response = page.goto(f"{base_url}/admin/api", wait_until="networkidle")
    assert response is not None and response.ok
    assert "Diagnostics" in page.content()
    assert "Billing state" in page.content()
    assert "Support tier" in page.content()
    assert "Open bundle" in page.content()
    assert "Recent product events" in page.content()

    page.get_by_role("link", name="Open bundle").first.click()
    page.wait_for_load_state("networkidle")
    assert "/app/api/diagnostics/export" in page.url
    body_text = page.locator("body").inner_text()
    assert '"billing"' in body_text
    assert '"support_tier"' in body_text
    assert '"renewal_owner_role"' in body_text


def test_people_memory_correction_and_handoff_actions_in_real_browser(page: Page, product_browser_server: dict[str, object]) -> None:
    base_url = str(product_browser_server["base_url"])
    stakeholder_id = str(product_browser_server["seeded"]["stakeholder_id"])

    response = page.goto(f"{base_url}/app/people/{stakeholder_id}", wait_until="networkidle")
    assert response is not None and response.ok
    page.locator("#preferred_tone").fill("warm")
    page.locator("#add_theme").fill("board packet")
    page.locator("#add_risk").fill("travel coordination")
    with page.expect_response(lambda value: f"/app/actions/people/{stakeholder_id}/correct" in value.url) as correct_response:
        page.get_by_role("button", name="Update relationship memory").click()
    assert correct_response.value.status == 303
    page.wait_for_url(f"{base_url}/app/people/{stakeholder_id}")
    page.wait_for_load_state("networkidle")
    assert "warm" in page.content()
    assert "board packet" in page.content()
    assert "travel coordination" in page.content()
    assert "Recent relationship history" in page.content()
    assert "Memory Corrected" in page.content()

    response = page.goto(f"{base_url}/app/follow-ups", wait_until="networkidle")
    assert response is not None and response.ok
    page.locator("#create_followup_title").fill("Confirm board dinner date")
    page.locator("#create_followup_details").fill("Manual follow-up from the browser surface.")
    page.locator("#create_followup_counterparty").fill("Sofia N.")
    page.locator("#create_followup_stakeholder_id").fill(stakeholder_id)
    with page.expect_response(lambda value: "/app/actions/commitments/create" in value.url and value.request.method == "POST") as create_response:
        page.get_by_role("button", name="Create follow-up").click()
    assert create_response.value.status == 303
    page.wait_for_url(f"{base_url}/app/follow-ups")
    page.wait_for_load_state("networkidle")
    assert "Confirm board dinner date" in page.content()


def test_founder_fixture_in_real_browser(browser: Browser, founder_browser_server: dict[str, object]) -> None:
    context = browser.new_context()
    page = context.new_page()
    try:
        base_url = str(founder_browser_server["base_url"])

        response = page.goto(f"{base_url}/app/settings", wait_until="networkidle")
        assert response is not None and response.ok
        assert "Rules" in page.content()
        assert "Pilot" in page.content()
        assert "trial" in page.content()
        assert "guided" in page.content()
    finally:
        context.close()


def test_team_fixture_in_real_browser(browser: Browser, team_browser_server: dict[str, object]) -> None:
    context = browser.new_context()
    page = context.new_page()
    try:
        base_url = str(team_browser_server["base_url"])

        response = page.goto(f"{base_url}/app/settings", wait_until="networkidle")
        assert response is not None and response.ok
        assert "Rules" in page.content()
        assert "Core" in page.content()
        assert "telegram" in page.content().lower()

        response = page.goto(f"{base_url}/admin/operators", wait_until="networkidle")
        assert response is not None and response.ok
        assert "Team / Operators" in page.content()
        assert "Team Operator" in page.content()

        response = page.goto(f"{base_url}/app/follow-ups", wait_until="networkidle")
        assert response is not None and response.ok
        with page.expect_response(lambda value: "/app/actions/handoffs/" in value.url and value.request.method == "POST") as handoff_response:
            page.locator(".console-row", has_text="Prepare board follow-up handoff").get_by_role("button", name="Claim").click()
        assert handoff_response.value.status == 303
    finally:
        context.close()


def test_operator_scoped_browser_queue_hides_other_operator_work(browser: Browser, team_browser_server: dict[str, object]) -> None:
    context = browser.new_context(
        extra_http_headers={
            "Authorization": "Bearer test-token",
            "X-EA-Principal-ID": "fixture-team-browser",
            "X-EA-Operator-ID": "operator-office",
        }
    )
    page = context.new_page()
    try:
        base_url = str(team_browser_server["base_url"])

        response = page.goto(f"{base_url}/app/activity", wait_until="networkidle")
        assert response is not None and response.ok
        assert "Prepare board follow-up handoff" in page.content()
        assert "Coordinate shared follow-up queue" not in page.content()

        response = page.goto(f"{base_url}/app/briefing", wait_until="networkidle")
        assert response is not None and response.ok
        assert "Prepare board follow-up handoff" in page.content()
        assert "Coordinate shared follow-up queue" not in page.content()
    finally:
        context.close()


def test_core_surface_visual_regression(page: Page, product_browser_server: dict[str, object]) -> None:
    base_url = str(product_browser_server["base_url"])
    page.set_viewport_size({"width": 1440, "height": 1100})
    cases = (
        ("/", "landing-page.png"),
        ("/get-started", "get-started-page.png"),
        ("/app/today", "today-page.png"),
        ("/app/briefing", "briefing-page.png"),
        ("/app/inbox", "inbox-page.png"),
        ("/app/follow-ups", "followups-page.png"),
        ("/admin/audit-trail", "admin-audit-page.png"),
    )
    for path, snapshot_name in cases:
        response = page.goto(f"{base_url}{path}", wait_until="networkidle")
        assert response is not None and response.ok
        _assert_visual_baseline(page, snapshot_name)


def test_people_correction_and_support_bundle_in_real_browser(page: Page, product_browser_server: dict[str, object]) -> None:
    base_url = str(product_browser_server["base_url"])
    seeded = dict(product_browser_server["seeded"])
    person_id = str(seeded["stakeholder_id"])

    response = page.goto(f"{base_url}/app/people/{person_id}", wait_until="networkidle")
    assert response is not None and response.ok
    assert "Why this person matters now" in page.content()

    page.locator("#preferred_tone").fill("warmer")
    page.locator("#add_theme").fill("board packet")
    page.locator("#add_risk").fill("travel coordination")
    with page.expect_response(lambda value: f"/app/actions/people/{person_id}/correct" in value.url) as correction_response:
        page.get_by_role("button", name="Update relationship memory").click()
    assert correction_response.value.status == 303
    page.wait_for_url(f"{base_url}/app/people/{person_id}")
    page.wait_for_load_state("networkidle")
    assert "board packet" in page.content()
    assert "travel coordination" in page.content()

    response = page.goto(f"{base_url}/app/api/people/{person_id}/detail/history", wait_until="networkidle")
    assert response is not None and response.ok
    assert "memory_corrected" in page.content()

    response = page.goto(f"{base_url}/app/settings", wait_until="networkidle")
    assert response is not None and response.ok
    with page.expect_response(lambda value: value.url.endswith("/app/api/diagnostics/export") and value.request.method == "GET") as export_response:
        page.get_by_role("link", name="Open bundle").click()
    assert export_response.value.status == 200
    page.wait_for_load_state("networkidle")
    assert '"billing"' in page.content()
    assert '"analytics"' in page.content()
    assert '"support_bundle_opened"' in page.content()


def test_commitment_candidate_can_be_edited_before_accept_in_real_browser(page: Page, product_browser_server: dict[str, object]) -> None:
    base_url = str(product_browser_server["base_url"])

    response = page.goto(f"{base_url}/app/inbox", wait_until="networkidle")
    assert response is not None and response.ok

    page.locator("#extract_source_text").fill("Please send the revised board packet to Sofia tomorrow morning.")
    page.locator("#extract_counterparty").fill("Sofia N.")
    with page.expect_response(lambda value: "/app/actions/commitments/extract" in value.url and value.request.method == "POST") as extract_response:
        page.get_by_role("button", name="Capture item").click()
    assert extract_response.value.status == 303
    page.wait_for_url(f"{base_url}/app/inbox")
    page.wait_for_load_state("networkidle")

    page.get_by_role("link", name="send the revised board packet to sofia tomorrow morning", exact=False).click()
    page.wait_for_load_state("networkidle")
    assert "/app/commitments/candidates/" in page.url

    page.locator("#candidate_title").fill("Send revised board packet")
    page.locator("#candidate_details").fill("Send the revised board packet to Sofia before the morning prep window.")
    page.locator("#candidate_due_at").fill("2026-03-26T09:00:00+00:00")
    with page.expect_response(lambda value: "/app/actions/commitments/candidates/" in value.url and value.request.method == "POST") as accept_response:
        page.get_by_role("button", name="Accept into commitment ledger").click()
    assert accept_response.value.status == 303
    page.wait_for_url(f"{base_url}/app/follow-ups")
    page.wait_for_load_state("networkidle")
    assert "Send revised board packet" in page.content()


@pytest.fixture()
def operator_browser_server() -> Iterator[dict[str, object]]:
    os.environ.pop("EA_ALLOW_LOOPBACK_NO_AUTH", None)
    from tests.product_test_helpers import seed_executive_operator_fixture

    principal_id = "fixture-operator-browser"
    client, seeded = seed_executive_operator_fixture(principal_id=principal_id)
    seeded_with_auth = {
        **seeded,
        "principal_id": principal_id,
        "operator_id": "operator-office",
        "auth_token": "test-token",
    }
    yield from _start_browser_server(client, seeded=seeded_with_auth)


def test_operator_queue_and_admin_audit_in_real_browser(browser: Browser, operator_browser_server: dict[str, object]) -> None:
    base_url = str(operator_browser_server["base_url"])
    seeded = dict(operator_browser_server["seeded"])
    context = browser.new_context(
        extra_http_headers={
            "Authorization": f"Bearer {seeded['auth_token']}",
            "X-EA-Principal-ID": str(seeded["principal_id"]),
            "X-EA-Operator-ID": str(seeded["operator_id"]),
        }
    )
    page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/activity", wait_until="networkidle")
        assert response is not None and response.ok
        assert "Operator Queue" in page.content()
        assert "Queue health" in page.content()
        assert "Suggested next claims" in page.content()
        assert "Prepare board follow-up handoff" in page.content()

        response = page.goto(f"{base_url}/admin/audit-trail", wait_until="networkidle")
        assert response is not None and response.ok
        assert "Audit Trail" in page.content()
        assert "Recent approval decisions" in page.content()
        assert "Current deployment state" in page.content()
        _assert_visual_baseline(page, "admin-audit-trail-page.png")

        response = page.goto(f"{base_url}/admin/api", wait_until="networkidle")
        assert response is not None and response.ok
        assert "Diagnostics" in page.content()
        assert "Commercial boundary" in page.content()
        assert "Workspace diagnostics bundle" in page.content()
        assert "SLA breaches" in page.content()
    finally:
        context.close()


def test_operator_queue_claim_and_complete_stays_in_operator_lane(browser: Browser, operator_browser_server: dict[str, object]) -> None:
    base_url = str(operator_browser_server["base_url"])
    seeded = dict(operator_browser_server["seeded"])
    context = browser.new_context(
        extra_http_headers={
            "Authorization": f"Bearer {seeded['auth_token']}",
            "X-EA-Principal-ID": str(seeded["principal_id"]),
            "X-EA-Operator-ID": str(seeded["operator_id"]),
        }
    )
    page = context.new_page()
    try:
        response = page.goto(f"{base_url}/app/activity", wait_until="networkidle")
        assert response is not None and response.ok
        row = page.locator(".console-row", has_text="Prepare board follow-up handoff")
        with page.expect_response(lambda value: "/app/actions/handoffs/" in value.url and value.request.method == "POST") as claim_response:
            row.get_by_role("button", name="Claim").click()
        assert claim_response.value.status == 303
        page.wait_for_url(f"{base_url}/app/activity")
        page.wait_for_load_state("networkidle")

        row = page.locator(".console-row", has_text="Prepare board follow-up handoff")
        with page.expect_response(lambda value: "/app/actions/handoffs/" in value.url and value.request.method == "POST") as complete_response:
            row.get_by_role("button", name="Complete").click()
        assert complete_response.value.status == 303
        page.wait_for_url(f"{base_url}/app/activity")
        page.wait_for_load_state("networkidle")
        assert "What just moved through the operator lane" in page.content()
    finally:
        context.close()
