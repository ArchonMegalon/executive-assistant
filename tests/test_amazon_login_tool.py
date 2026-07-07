from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services import tool_execution_browseract_adapter as browseract_adapter
from app.services.provider_registry import ProviderRegistryService
from app.services.tool_execution_browseract_adapter import BrowserActToolAdapter
from tests.product_test_helpers import build_operator_product_client


def _operator_client(*, principal_id: str = "exec-amazon") -> TestClient:
    return build_operator_product_client(principal_id=principal_id, operator_id=f"{principal_id}-operator")


def test_provider_registry_routes_amazon_login_when_secret_file_is_configured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    password_file = tmp_path / "amazon_password"
    password_file.write_text("fixture-password\n", encoding="utf-8")
    monkeypatch.setenv("AMAZON_AUTH_MODE", "secret_file")
    monkeypatch.setenv("AMAZON_ACCOUNT_EMAIL", "amazon-user@example.test")
    monkeypatch.setenv("AMAZON_PASSWORD_FILE", str(password_file))

    registry = ProviderRegistryService()
    route = registry.route_tool_with_context("provider.amazon.login", principal_id="exec-amazon")

    assert route.provider_key == "amazon"
    assert route.capability_key == "amazon_login"
    assert route.tool_name == "provider.amazon.login"
    assert route.executable is True


def test_amazon_login_password_reads_fallback_secret_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fallback_root = tmp_path / "repo_root"
    fallback_file = fallback_root / "config" / "amazon_archon_password"
    fallback_file.parent.mkdir(parents=True)
    fallback_file.write_text("fallback-password\n", encoding="utf-8")

    monkeypatch.setattr(browseract_adapter, "_repo_root", lambda: fallback_root)
    monkeypatch.setenv("AMAZON_PASSWORD_FILE", "/run/secrets/amazon_archon_password")
    monkeypatch.setenv("AMAZON_PASSWORD", "")

    assert BrowserActToolAdapter._amazon_login_password() == "fallback-password"


def test_amazon_login_password_prefers_secret_file_when_secret_file_auth_mode_is_set(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    password_file = tmp_path / "amazon_password"
    password_file.write_text("file-password\n", encoding="utf-8")

    monkeypatch.setenv("AMAZON_AUTH_MODE", "secret_file")
    monkeypatch.setenv("AMAZON_PASSWORD", "inline-password")
    monkeypatch.setenv("AMAZON_PASSWORD_FILE", str(password_file))

    assert BrowserActToolAdapter._amazon_login_password() == "file-password"


def test_amazon_login_password_uses_default_secret_file_when_env_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fallback_root = tmp_path / "repo_root"
    fallback_file = fallback_root / "config" / "amazon_archon_password"
    fallback_file.parent.mkdir(parents=True)
    fallback_file.write_text("defaulted-password\n", encoding="utf-8")

    monkeypatch.delenv("AMAZON_PASSWORD_FILE", raising=False)
    monkeypatch.delenv("AMAZON_PASSWORD", raising=False)
    monkeypatch.setattr(browseract_adapter, "_repo_root", lambda: fallback_root)

    assert BrowserActToolAdapter._amazon_login_password() == "defaulted-password"


def test_amazon_login_password_uses_default_file_when_password_file_is_relative_parent_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fallback_root = tmp_path / "repo_root"
    fallback_file = fallback_root / "config" / "amazon_archon_password"
    fallback_file.parent.mkdir(parents=True)
    fallback_file.write_text("parented-password\n", encoding="utf-8")

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    monkeypatch.chdir(run_dir)
    monkeypatch.delenv("AMAZON_PASSWORD_FILE", raising=False)
    monkeypatch.delenv("AMAZON_PASSWORD", raising=False)
    monkeypatch.setenv("AMAZON_PASSWORD_FILE", "../config/amazon_archon_password")
    monkeypatch.setattr(browseract_adapter, "_repo_root", lambda: fallback_root)

    assert BrowserActToolAdapter._amazon_login_password() == "parented-password"


def test_amazon_login_tool_exposes_two_step_signin_workflow() -> None:
    spec = BrowserActToolAdapter._amazon_login_workflow_spec(
        login_url="https://www.amazon.de/ap/signin",
        account_url="https://www.amazon.de/gp/css/homepage.html",
    )

    nodes = {str(node["id"]): dict(node) for node in spec["nodes"]}

    assert nodes["continue"]["type"] == "click"
    assert "input#continue" in nodes["continue"]["config"]["selector"]
    assert nodes["submit"]["type"] == "submit_login_form"
    assert "input#signInSubmit" in nodes["submit"]["config"]["selector"]
    assert "input#ap_password" in nodes["submit"]["config"]["password_selector"]
    assert "incorrect" in nodes["submit"]["config"]["auth_failure_text_markers"]
    assert nodes["open_account"]["type"] == "visit_page"


def test_amazon_login_tool_executes_via_tools_api_with_secret_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    password_file = tmp_path / "amazon_password"
    password_file.write_text("fixture-password\n", encoding="utf-8")
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_ENABLE_LEGACY_RUNTIME_SURFACES", "1")
    monkeypatch.setenv("AMAZON_AUTH_MODE", "secret_file")
    monkeypatch.setenv("AMAZON_ACCOUNT_EMAIL", "amazon-user@example.test")
    monkeypatch.setenv("AMAZON_PASSWORD_FILE", str(password_file))

    captured: dict[str, object] = {}

    def _fake_worker(cls, *, service_key: str, packet: dict[str, object], timeout_seconds: int) -> dict[str, object]:
        captured["service_key"] = service_key
        captured["packet"] = dict(packet)
        captured["timeout_seconds"] = timeout_seconds
        return {
            "render_status": "completed",
            "requested_url": "browseract-template://amazon_login_live",
            "title": "Amazon.de - Mein Konto",
            "url": "https://www.amazon.de/gp/css/homepage.html",
            "bodyText": "Mein Konto Bestellungen Prime",
            "labels": ["Mein Konto", "Bestellungen"],
            "buttons": ["Prime"],
            "links": [{"text": "Bestellungen", "href": "https://www.amazon.de/gp/your-account/order-history"}],
            "extracts": {"account_page": "Mein Konto Bestellungen Prime"},
        }

    monkeypatch.setattr(BrowserActToolAdapter, "_run_ui_service_worker", classmethod(_fake_worker))

    client = _operator_client()
    response = client.post(
        "/v1/tools/execute",
        json={
            "tool_name": "provider.amazon.login",
            "action_kind": "account.login",
            "payload_json": {
                "login_url": "https://www.amazon.de/ap/signin",
                "account_url": "https://www.amazon.de/gp/css/homepage.html",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_name"] == "provider.amazon.login"
    assert payload["action_kind"] == "account.login"
    assert payload["output_json"]["provider_backend"] == "amazon_browseract_template"
    assert payload["output_json"]["login_state"] == "authenticated"
    assert payload["output_json"]["title"] == "Amazon.de - Mein Konto"
    assert payload["receipt_json"]["provider_key"] == "amazon"
    assert payload["receipt_json"]["auth_mode"] == "secret_file_or_inline"
    assert captured["service_key"] == "amazon_login"
    assert captured["timeout_seconds"] == 360
    packet = dict(captured["packet"])
    assert packet["browseract_username"] == "amazon-user@example.test"
    assert packet["browseract_password"] == "fixture-password"
    assert packet["template_key"] == "amazon_login_live"
    assert packet["proxy_result"] is False
    workflow_spec = dict(packet["workflow_spec_json"])
    assert workflow_spec["meta"]["slug"] == "amazon_login_live"
    assert any(str(node.get("id")) == "continue" for node in workflow_spec["nodes"])


def test_amazon_login_tool_reports_mfa_handoff_instead_of_authenticated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    password_file = tmp_path / "amazon_password"
    password_file.write_text("fixture-password\n", encoding="utf-8")
    monkeypatch.setenv("EA_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("EA_ENABLE_LEGACY_RUNTIME_SURFACES", "1")
    monkeypatch.setenv("AMAZON_AUTH_MODE", "secret_file")
    monkeypatch.setenv("AMAZON_ACCOUNT_EMAIL", "amazon-user@example.test")
    monkeypatch.setenv("AMAZON_PASSWORD_FILE", str(password_file))

    def _fake_worker(cls, *, service_key: str, packet: dict[str, object], timeout_seconds: int) -> dict[str, object]:
        return {
            "render_status": "completed",
            "requested_url": "browseract-template://amazon_login_live",
            "title": "Amazon.de Anmeldung",
            "url": "https://www.amazon.de/ap/mfa?ie=UTF8&arb=fixture",
            "bodyText": (
                "Schau auf WhatsApp nach einer Nachricht mit deinem Sicherheitscode. "
                "Zwei-Schritt-Verifizierung Code eingeben"
            ),
            "labels": ["Zwei-Schritt-Verifizierung"],
            "buttons": ["Anmelden"],
            "links": [],
            "extracts": {"account_page": "Zwei-Schritt-Verifizierung"},
        }

    monkeypatch.setattr(BrowserActToolAdapter, "_run_ui_service_worker", classmethod(_fake_worker))

    client = _operator_client()
    response = client.post(
        "/v1/tools/execute",
        json={
            "tool_name": "provider.amazon.login",
            "action_kind": "account.login",
            "payload_json": {
                "login_url": "https://www.amazon.de/ap/signin",
                "account_url": "https://www.amazon.de/gp/css/homepage.html",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["output_json"]["login_state"] == "mfa_required"
    assert payload["output_json"]["user_action_required"] is True
    assert payload["output_json"]["blocker_code"] == "mfa_code_required"
    assert payload["receipt_json"]["login_state"] == "mfa_required"
    assert payload["receipt_json"]["user_action_required"] is True
    assert payload["receipt_json"]["blocker_code"] == "mfa_code_required"
