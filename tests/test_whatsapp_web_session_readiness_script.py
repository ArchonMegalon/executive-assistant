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
