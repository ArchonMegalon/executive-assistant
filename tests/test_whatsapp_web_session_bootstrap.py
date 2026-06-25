from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "bootstrap_whatsapp_web_session_account.py"


def _module():
    spec = importlib.util.spec_from_file_location("bootstrap_whatsapp_web_session_account", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(**overrides):
    values = {
        "tenant_id": "tenant-default",
        "tenant_name": "Default Tenant",
        "tenant_slug": "default",
        "principal_id": "principal-default",
        "display_name": "Executive Assistant Operator",
        "email": "operator@example.test",
        "phone_number": "+15555550100",
        "session_label": "Executive Assistant WhatsApp Web Session",
        "binding_id": "ea-whatsapp-web-session",
        "session_ref": "",
        "session_store_ref": "",
        "browser_profile_ref": "",
        "session_send_url_template": "",
        "session_status_url_template": "",
        "session_api_base_url": "",
        "session_api_token": "",
        "auth_header_name": "",
        "auth_header_prefix": "",
        "connector_status": "staged",
    }
    values.update(overrides)
    return Namespace(**values)


def _clear_principal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID",
        "EA_WHATSAPP_DEFAULT_PRINCIPAL_ID",
        "EA_DEFAULT_PRINCIPAL_ID",
    ):
        monkeypatch.delenv(name, raising=False)


def test_parse_args_uses_repo_wide_principal_before_literal_default(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    (tmp_path / ".env").write_text("EA_DEFAULT_PRINCIPAL_ID=repo-wide-principal\n", encoding="utf-8")
    _clear_principal_env(monkeypatch)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["bootstrap_whatsapp_web_session_account.py"])

    args = module.parse_args()

    assert args.principal_id == "repo-wide-principal"


def test_parse_args_prefers_whatsapp_principal_before_repo_wide_default(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "EA_WHATSAPP_DEFAULT_PRINCIPAL_ID=repo-whatsapp-principal",
                "EA_DEFAULT_PRINCIPAL_ID=repo-wide-principal",
            ]
        ),
        encoding="utf-8",
    )
    _clear_principal_env(monkeypatch)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["bootstrap_whatsapp_web_session_account.py"])

    args = module.parse_args()

    assert args.principal_id == "repo-whatsapp-principal"


def test_parse_args_prefers_web_principal_before_whatsapp_default(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID=repo-web-principal",
                "EA_WHATSAPP_DEFAULT_PRINCIPAL_ID=repo-whatsapp-principal",
                "EA_DEFAULT_PRINCIPAL_ID=repo-wide-principal",
            ]
        ),
        encoding="utf-8",
    )
    _clear_principal_env(monkeypatch)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["bootstrap_whatsapp_web_session_account.py"])

    args = module.parse_args()

    assert args.principal_id == "repo-web-principal"


def test_parse_args_uses_literal_principal_only_after_fallback_chain(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    (tmp_path / ".env").write_text("", encoding="utf-8")
    _clear_principal_env(monkeypatch)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["bootstrap_whatsapp_web_session_account.py"])

    args = module.parse_args()

    assert args.principal_id == "principal-default"


def test_build_seed_uses_default_principal_chain_when_arg_is_empty(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    (tmp_path / ".env").write_text("EA_DEFAULT_PRINCIPAL_ID=repo-wide-principal\n", encoding="utf-8")
    _clear_principal_env(monkeypatch)
    monkeypatch.setattr(module, "ROOT", tmp_path)

    seed = module.build_seed(_args(principal_id=""))

    assert seed.principal_id == "repo-wide-principal"


def test_build_seed_records_whatsapp_web_transport_without_session_secret() -> None:
    module = _module()

    seed = module.build_seed(
        _args(
            session_ref="wa-web-session-1",
            session_store_ref="vault://ea/whatsapp-web/session-1",
            browser_profile_ref="browser-profile://ea/whatsapp-web/principal",
            session_send_url_template="https://wa-web.test/sessions/{session_ref}/messages",
            session_status_url_template="https://wa-web.test/sessions/{session_ref}/status",
            connector_status="enabled",
        )
    )

    assert seed.connector_name == "whatsapp_web_session"
    assert seed.delivery_channel == "whatsapp"
    assert seed.delivery_transport == "whatsapp_web_session"
    assert seed.session_status == "web_session_ready"
    assert seed.scope_json()["scopes"] == ["whatsapp.send"]
    assert seed.scope_json()["preferred_transport"] == "whatsapp_web_session"
    assert seed.scope_json()["service_routes"]["default_delivery_channel"] == "whatsapp"
    assert seed.scope_json()["service_routes"]["default_transport"] == "whatsapp_web_session"
    assert "executive_assistant_channel_send" in seed.scope_json()["service_routes"]["applies_to"]

    metadata = seed.auth_metadata_json()
    assert metadata["provider"] == "whatsapp_web"
    assert metadata["session_ref"] == "wa-web-session-1"
    assert metadata["session_send_url_template"] == "https://wa-web.test/sessions/{session_ref}/messages"
    assert metadata["session_status_url_template"] == "https://wa-web.test/sessions/{session_ref}/status"
    assert metadata["session_store_ref"] == "vault://ea/whatsapp-web/session-1"
    assert "session_api_token" not in metadata
    assert "access_token" not in metadata
    assert "phone_number_id" not in metadata


def test_build_seed_defaults_to_staged_when_session_is_missing() -> None:
    module = _module()

    seed = module.build_seed(_args())

    assert seed.connector_status == "staged"
    assert seed.session_status == "web_session_missing"
    assert seed.sanitized_summary()["session_ref_present"] is False
    assert seed.sanitized_summary()["session_store_ref_present"] is False


def test_build_seed_rejects_session_ref_without_store_ref() -> None:
    module = _module()

    with pytest.raises(ValueError, match="whatsapp_web_session_store_or_browser_profile_ref_required"):
        module.build_seed(_args(session_ref="wa-web-session-1", session_store_ref=""))


def test_build_seed_allows_browser_profile_ref_as_session_store_anchor() -> None:
    module = _module()

    seed = module.build_seed(
        _args(
            session_ref="wa-web-session-1",
            browser_profile_ref="browser-profile://ea/whatsapp-web/principal",
            session_api_base_url="http://ea-whatsapp-web-session:8098",
            connector_status="enabled",
        )
    )

    assert seed.session_status == "web_session_ready"
    metadata = seed.auth_metadata_json()
    assert metadata["browser_profile_ref"] == "browser-profile://ea/whatsapp-web/principal"
    assert metadata["session_api_base_url"] == "http://ea-whatsapp-web-session:8098"
    assert seed.sanitized_summary()["session_endpoint_present"] is True
    assert seed.sanitized_summary()["session_status_endpoint_present"] is True


def test_build_seed_rejects_enabled_binding_without_session_ref() -> None:
    module = _module()

    with pytest.raises(ValueError, match="whatsapp_web_session_ref_required_when_enabled"):
        module.build_seed(_args(connector_status="enabled"))


def test_build_seed_rejects_enabled_binding_without_send_endpoint() -> None:
    module = _module()

    with pytest.raises(ValueError, match="whatsapp_web_session_send_endpoint_required_when_enabled"):
        module.build_seed(
            _args(
                session_ref="wa-web-session-1",
                session_store_ref="vault://ea/whatsapp-web/session-1",
                connector_status="enabled",
            )
        )


def test_main_returns_sanitized_json_when_activation_config_is_invalid(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(module, "parse_args", lambda: _args(connector_status="enabled"))

    exit_code = module.main()
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert output["seeded"] is False
    assert output["reason"] == "whatsapp_web_session_ref_required_when_enabled"
    assert output["binding_id"] == "ea-whatsapp-web-session"
    assert output["principal_id"] == "principal-default"
