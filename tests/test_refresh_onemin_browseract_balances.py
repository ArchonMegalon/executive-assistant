from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_PATH = Path("/docker/EA/scripts/refresh_onemin_browseract_balances.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("refresh_onemin_browseract_balances", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_persist_snapshot_via_ea_api_posts_to_live_manager_route(monkeypatch):
    module = _load_module()
    monkeypatch.setenv("EA_API_TOKEN", "test-token")
    monkeypatch.setenv("EA_BASE_URL", "http://127.0.0.1:8090")
    monkeypatch.setenv("EA_PRINCIPAL_ID", "codex-fleet")

    captured = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "snapshot": {
                        "account_name": "ONEMIN_AI_API_KEY_FALLBACK_54",
                        "remaining_credits": 4280000.0,
                    }
                }
            ).encode("utf-8")

    class _FakeOpener:
        def open(self, request, timeout=0):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["headers"] = dict(request.header_items())
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _FakeResponse()

    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *args, **kwargs: _FakeOpener())

    record = module.AccountRecord(
        slot="fallback_54",
        account_label="ONEMIN_AI_API_KEY_FALLBACK_54",
        owner_email="Philomene.Goudreau@myexternalbrain.com",
        owner_name="Philomene Goudreau",
    )

    snapshot, error = module._persist_snapshot_via_ea_api(
        record,
        normalized={"remaining_credits": 4280000, "basis": "actual_billing_usage_page"},
    )

    assert error == ""
    assert snapshot == {
        "account_name": "ONEMIN_AI_API_KEY_FALLBACK_54",
        "remaining_credits": 4280000.0,
    }
    assert captured["url"] == "http://127.0.0.1:8090/v1/providers/onemin/billing-snapshots"
    assert captured["timeout"] == 30
    assert captured["headers"]["Authorization"] == "Bearer test-token"
    assert captured["headers"]["X-ea-principal-id"] == "codex-fleet"
    assert captured["body"]["account_label"] == "ONEMIN_AI_API_KEY_FALLBACK_54"
    assert captured["body"]["snapshot_json"]["remaining_credits"] == 4280000


def test_persist_snapshot_via_ea_api_reports_missing_token(monkeypatch):
    module = _load_module()
    monkeypatch.delenv("EA_API_TOKEN", raising=False)

    record = module.AccountRecord(
        slot="fallback_54",
        account_label="ONEMIN_AI_API_KEY_FALLBACK_54",
        owner_email="Philomene.Goudreau@myexternalbrain.com",
        owner_name="Philomene Goudreau",
    )

    snapshot, error = module._persist_snapshot_via_ea_api(
        record,
        normalized={"remaining_credits": 4280000},
    )

    assert snapshot is None
    assert error == "ea_api_token_missing"


def test_ea_api_base_url_adds_scheme_for_bare_host(monkeypatch):
    module = _load_module()
    monkeypatch.setenv("EA_HOST", "0.0.0.0:8090")
    monkeypatch.delenv("EA_BASE_URL", raising=False)
    monkeypatch.delenv("EA_MCP_BASE_URL", raising=False)

    assert module._ea_api_base_url() == "http://127.0.0.1:8090"


def test_run_account_marks_unparsed_billing_page_as_failure(monkeypatch, tmp_path):
    module = _load_module()
    monkeypatch.setenv("ONEMIN_DEFAULT_PASSWORD", "secret")
    monkeypatch.setattr(module, "_effective_proxy_settings", lambda: {})
    monkeypatch.setattr(module, "_effective_worker_env", lambda: {})
    monkeypatch.setattr(module, "_persist_snapshot_via_ea_api", lambda *args, **kwargs: ({"snapshot": "ok"}, ""))

    output_path = tmp_path / "output.json"

    def fake_tempdir(prefix=""):
        return str(tmp_path)

    class _Completed:
        returncode = 1
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        output_path.write_text(json.dumps({"asset_path": "/tmp/result.html", "warnings": []}), encoding="utf-8")
        return _Completed()

    monkeypatch.setattr(module.tempfile, "mkdtemp", fake_tempdir)
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        module.BrowserActToolAdapter,
        "_raise_for_ui_lane_failure",
        lambda payload, backend: None,
    )
    monkeypatch.setattr(
        module.BrowserActToolAdapter,
        "_normalize_onemin_billing_payload",
        lambda response, source_url, account_label: {
            "basis": "page_seen_but_unparsed",
            "remaining_credits": None,
            "max_credits": None,
            "daily_bonus_available": True,
            "daily_bonus_credits": 15000,
        },
    )

    record = module.AccountRecord(
        slot="fallback_58",
        account_label="ONEMIN_AI_API_KEY_FALLBACK_58",
        owner_email="Valmai.Johnston@myexternalbrain.com",
        owner_name="Valmai Johnston",
    )

    result = module._run_account(record, timeout_seconds=60)

    assert result["status"] == "ui_lane_failure"
    assert result["failure_code"] == "page_seen_but_unparsed"
    assert result["daily_bonus_available"] is True
    assert result["daily_bonus_credits"] == 15000


def test_run_account_reports_missing_playwright_image_before_normalization(monkeypatch, tmp_path):
    module = _load_module()
    monkeypatch.setenv("ONEMIN_DEFAULT_PASSWORD", "secret")
    monkeypatch.setattr(module, "_effective_proxy_settings", lambda: {})
    monkeypatch.setattr(module, "_effective_worker_env", lambda: {})

    output_path = tmp_path / "output.json"

    def fake_tempdir(prefix=""):
        return str(tmp_path)

    class _Completed:
        returncode = 1
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        output_path.write_text(
            json.dumps(
                {
                    "render_status": "failed",
                    "asset_path": "",
                    "error": (
                        "template_worker_empty_output:Unable to find image "
                        "'chummer-playwright:local' locally"
                    ),
                    "structured_output_json": {
                        "render_status": "failed",
                        "errors": [
                            "docker: Error response from daemon: pull access denied for chummer-playwright"
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )
        return _Completed()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("normalization should not run for failed workers")

    monkeypatch.setattr(module.tempfile, "mkdtemp", fake_tempdir)
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.BrowserActToolAdapter, "_raise_for_ui_lane_failure", fail_if_called)
    monkeypatch.setattr(module.BrowserActToolAdapter, "_normalize_onemin_billing_payload", fail_if_called)

    record = module.AccountRecord(
        slot="fallback_58",
        account_label="ONEMIN_AI_API_KEY_FALLBACK_58",
        owner_email="Valmai.Johnston@myexternalbrain.com",
        owner_name="Valmai Johnston",
    )

    result = module._run_account(record, timeout_seconds=60)

    assert result["status"] == "worker_failed"
    assert result["failure_code"] == "playwright_image_missing"
