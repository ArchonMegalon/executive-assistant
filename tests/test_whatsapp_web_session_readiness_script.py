from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "check_whatsapp_web_session_readiness.py"


def _module():
    spec = importlib.util.spec_from_file_location("check_whatsapp_web_session_readiness", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _binding(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "binding_id": "wa-web-binding-1",
        "principal_id": "principal-wa-web-1",
        "connector_name": "whatsapp_web_session",
        "external_account_ref": "+15550101000",
        "scope_json": {
            "scopes": ["whatsapp.send"],
            "service_routes": {"applies_to": ["connector.dispatch", "executive_assistant_channel_send"]},
        },
        "auth_metadata_json": {
            "session_ref": "session-principal",
            "session_store_ref": "vault://ea/whatsapp-web/session-principal",
            "session_send_url_template": "https://wa-web.test/sessions/{session_ref}/messages",
            "session_api_token": "session-token",
        },
        "status": "enabled",
        "created_at": "2026-06-21T00:00:00Z",
        "updated_at": "2026-06-21T00:00:00Z",
    }
    values.update(overrides)
    return values


def test_parse_args_loads_repo_env_defaults_when_shell_env_is_empty(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://repo-env.invalid/ea",
                "EA_WHATSAPP_WEB_DEFAULT_BINDING_ID=repo-wa-binding",
                "EA_WHATSAPP_DEFAULT_PRINCIPAL_ID=repo-principal",
                "EA_DEFAULT_PRINCIPAL_ID=repo-wide-principal",
            ]
        ),
        encoding="utf-8",
    )
    for name in (
        "DATABASE_URL",
        "EA_WHATSAPP_WEB_DEFAULT_BINDING_ID",
        "EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID",
        "EA_WHATSAPP_DEFAULT_PRINCIPAL_ID",
        "EA_DEFAULT_PRINCIPAL_ID",
        "EA_WHATSAPP_WEB_READINESS_BINDING_JSON",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_whatsapp_web_session_readiness.py"])

    args = module.parse_args()

    assert args.database_url == "postgresql://repo-env.invalid/ea"
    assert args.binding_id == "repo-wa-binding"
    assert args.principal_id == "repo-principal"


def test_parse_args_uses_repo_wide_principal_before_literal_default(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://repo-env.invalid/ea",
                "EA_WHATSAPP_WEB_DEFAULT_BINDING_ID=repo-wa-binding",
                "EA_DEFAULT_PRINCIPAL_ID=repo-wide-principal",
            ]
        ),
        encoding="utf-8",
    )
    for name in (
        "DATABASE_URL",
        "EA_WHATSAPP_WEB_DEFAULT_BINDING_ID",
        "EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID",
        "EA_WHATSAPP_DEFAULT_PRINCIPAL_ID",
        "EA_DEFAULT_PRINCIPAL_ID",
        "EA_WHATSAPP_WEB_READINESS_BINDING_JSON",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_whatsapp_web_session_readiness.py"])

    args = module.parse_args()

    assert args.database_url == "postgresql://repo-env.invalid/ea"
    assert args.binding_id == "repo-wa-binding"
    assert args.principal_id == "repo-wide-principal"


def test_parse_args_uses_shell_repo_wide_principal_before_literal_default(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    (tmp_path / ".env").write_text("", encoding="utf-8")
    for name in (
        "EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID",
        "EA_WHATSAPP_DEFAULT_PRINCIPAL_ID",
        "EA_WHATSAPP_WEB_READINESS_BINDING_JSON",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EA_DEFAULT_PRINCIPAL_ID", "shell-wide-principal")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_whatsapp_web_session_readiness.py"])

    args = module.parse_args()

    assert args.principal_id == "shell-wide-principal"


def test_parse_args_uses_literal_principal_only_after_env_chain(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    (tmp_path / ".env").write_text("", encoding="utf-8")
    for name in (
        "EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID",
        "EA_WHATSAPP_DEFAULT_PRINCIPAL_ID",
        "EA_DEFAULT_PRINCIPAL_ID",
        "EA_WHATSAPP_WEB_READINESS_BINDING_JSON",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_whatsapp_web_session_readiness.py"])

    args = module.parse_args()

    assert args.principal_id == "principal-default"


def test_parse_args_prefers_shell_env_over_repo_env_defaults(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://repo-env.invalid/ea",
                "EA_WHATSAPP_WEB_DEFAULT_BINDING_ID=repo-wa-binding",
                "EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID=repo-principal",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://shell-env.invalid/ea")
    monkeypatch.setenv("EA_WHATSAPP_WEB_DEFAULT_BINDING_ID", "shell-wa-binding")
    monkeypatch.setenv("EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID", "shell-principal")
    monkeypatch.setattr(sys, "argv", ["check_whatsapp_web_session_readiness.py"])

    args = module.parse_args()

    assert args.database_url == "postgresql://shell-env.invalid/ea"
    assert args.binding_id == "shell-wa-binding"
    assert args.principal_id == "shell-principal"


def test_parse_args_cli_values_override_repo_env_defaults(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://repo-env.invalid/ea",
                "EA_WHATSAPP_WEB_DEFAULT_BINDING_ID=repo-wa-binding",
                "EA_WHATSAPP_DEFAULT_PRINCIPAL_ID=repo-principal",
            ]
        ),
        encoding="utf-8",
    )
    for name in (
        "DATABASE_URL",
        "EA_WHATSAPP_WEB_DEFAULT_BINDING_ID",
        "EA_WHATSAPP_WEB_DEFAULT_PRINCIPAL_ID",
        "EA_WHATSAPP_DEFAULT_PRINCIPAL_ID",
        "EA_DEFAULT_PRINCIPAL_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_whatsapp_web_session_readiness.py",
            "--database-url",
            "postgresql://cli.invalid/ea",
            "--binding-id",
            "cli-wa-binding",
            "--principal-id",
            "cli-principal",
        ],
    )

    args = module.parse_args()

    assert args.database_url == "postgresql://cli.invalid/ea"
    assert args.binding_id == "cli-wa-binding"
    assert args.principal_id == "cli-principal"


def test_build_report_returns_sanitized_ready_result(tmp_path: Path) -> None:
    module = _module()
    binding_file = tmp_path / "binding.json"
    binding_file.write_text(json.dumps(_binding()), encoding="utf-8")

    report = module.build_report(
        Namespace(
            binding_json=str(binding_file),
            binding_id="wa-web-binding-1",
            principal_id="principal-wa-web-1",
            probe_session=False,
        )
    )

    assert report["ready"] is True
    assert report["reason"] == "ready"
    assert report["token_present"] is True
    assert "session-token" not in json.dumps(report)
    assert report["service_routes"] == ["connector.dispatch", "executive_assistant_channel_send"]


def test_build_report_selects_binding_from_api_style_list(tmp_path: Path) -> None:
    module = _module()
    binding_file = tmp_path / "bindings.json"
    binding_file.write_text(
        json.dumps({"bindings": [_binding(binding_id="other", status="disabled"), _binding(binding_id="target")]}),
        encoding="utf-8",
    )

    report = module.build_report(
        Namespace(
            binding_json=str(binding_file),
            binding_id="target",
            principal_id="principal-wa-web-1",
            probe_session=False,
        )
    )

    assert report["ready"] is True
    assert report["binding_id"] == "target"


def test_build_report_requires_binding_json() -> None:
    module = _module()

    report = module.build_report(
        Namespace(
            binding_json="",
            database_url="",
            binding_id="wa-web-binding-1",
            principal_id="principal-wa-web-1",
            probe_session=False,
        )
    )

    assert report["ready"] is False
    assert report["reason"] == "binding_json_or_database_url_required"


def test_build_report_fails_closed_when_binding_json_is_missing(tmp_path: Path) -> None:
    module = _module()

    report = module.build_report(
        Namespace(
            binding_json=str(tmp_path / "missing.json"),
            database_url="",
            binding_id="wa-web-binding-1",
            principal_id="principal-wa-web-1",
            probe_session=False,
        )
    )

    assert report["ready"] is False
    assert report["reason"] == "binding_json_not_found"


def test_build_report_can_load_binding_from_database_url(monkeypatch) -> None:
    module = _module()
    calls: dict[str, object] = {}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params):
            calls["query"] = query
            calls["params"] = params

        def fetchone(self):
            return (
                "wa-web-binding-1",
                "principal-wa-web-1",
                "whatsapp_web_session",
                "+15550101000",
                {
                    "scopes": ["whatsapp.send"],
                    "service_routes": {"applies_to": ["connector.dispatch", "operator_summary"]},
                },
                {
                    "session_ref": "session-principal",
                    "session_store_ref": "vault://ea/whatsapp-web/session-principal",
                    "session_send_url_template": "https://wa-web.test/sessions/{session_ref}/messages",
                    "session_api_token": "session-token",
                },
                "enabled",
                "2026-06-21T00:00:00Z",
                "2026-06-21T00:00:00Z",
            )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    def connect(database_url):
        calls["database_url"] = database_url
        return FakeConnection()

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))

    report = module.build_report(
        Namespace(
            binding_json="",
            database_url="postgresql://example.invalid/ea",
            binding_id="wa-web-binding-1",
            principal_id="principal-wa-web-1",
            probe_session=False,
        )
    )

    assert report["ready"] is True
    assert report["binding_id"] == "wa-web-binding-1"
    assert report["token_present"] is True
    assert "session-token" not in json.dumps(report)
    assert calls["database_url"] == "postgresql://example.invalid/ea"
    assert calls["params"] == ("wa-web-binding-1",)


def test_build_report_preserves_requested_binding_when_database_row_is_missing(monkeypatch) -> None:
    module = _module()

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params):
            pass

        def fetchone(self):
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda database_url: FakeConnection()))

    report = module.build_report(
        Namespace(
            binding_json="",
            database_url="postgresql://example.invalid/ea",
            binding_id="wa-web-binding-1",
            principal_id="principal-wa-web-1",
            probe_session=False,
        )
    )

    assert report["ready"] is False
    assert report["reason"] == "binding_not_found"
    assert report["binding_id"] == "wa-web-binding-1"
    assert report["principal_id"] == "principal-wa-web-1"


def test_build_report_falls_back_to_latest_enabled_binding_for_default_placeholders(monkeypatch) -> None:
    module = _module()

    class FakeCursor:
        def __init__(self):
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params=None):
            self.calls += 1

        def fetchone(self):
            if self.calls == 1:
                return None
            return (
                "fixture-whatsapp-web-session",
                "exec-1",
                "whatsapp_web_session",
                "+15550101000",
                {
                    "scopes": ["whatsapp.send"],
                    "service_routes": {"applies_to": ["connector.dispatch"]},
                },
                {
                    "session_ref": "fixture-wa-web",
                    "session_store_ref": "vault://ea/whatsapp-web/fixture-wa-web",
                    "session_send_url_template": "https://wa-web.test/sessions/{session_ref}/messages",
                    "session_api_token": "session-token",
                },
                "enabled",
                "2026-06-21T00:00:00Z",
                "2026-06-22T00:00:00Z",
            )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda database_url: FakeConnection()))

    report = module.build_report(
        Namespace(
            binding_json="",
            database_url="postgresql://example.invalid/ea",
            binding_id="ea-whatsapp-web-session",
            principal_id="principal-default",
            probe_session=False,
        )
    )

    assert report["ready"] is True
    assert report["binding_id"] == "fixture-whatsapp-web-session"
    assert report["principal_id"] == "exec-1"
