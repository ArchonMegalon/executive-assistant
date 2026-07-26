from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "probe_poppy_ai_provider.py"


def _module():
    spec = importlib.util.spec_from_file_location("probe_poppy_ai_provider", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_skips_password_probe_without_explicit_poppy_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    output_path = tmp_path / "poppy-provider-probe.json"
    observed_requests: list[dict[str, object]] = []

    def _fake_http_request(
        url: str,
        *,
        method: str = "GET",
        payload: dict[str, object] | None = None,
    ):
        observed_requests.append({"url": url, "method": method, "payload": payload})
        if url == module.LOGIN_URL:
            return 200, "", {}
        if url.endswith("/v1/client"):
            return 200, "{}", {}
        return 200, "", {}

    monkeypatch.setattr(module, "http_request", _fake_http_request)
    monkeypatch.setattr(module, "list_browseract_workflows", lambda: [])
    monkeypatch.setattr(module, "SESSION_PROBE_PATH", tmp_path / "missing-session.json")
    monkeypatch.setattr(
        module,
        "LOCAL_ENV",
        {
            "BROWSERACT_USERNAME": "browseract@example.test",
            "BROWSERACT_PASSWORD": "browseract-secret",
        },
    )
    monkeypatch.setattr("sys.argv", [str(SCRIPT_PATH), str(output_path)])

    assert module.main() == 0

    artifact_text = output_path.read_text(encoding="utf-8")
    artifact = json.loads(artifact_text)
    captured = capsys.readouterr().out
    assert artifact["sign_in_probe"]["credentials_configured"] is False
    assert artifact["sign_in_probe"]["status_code"] == 0
    assert artifact["verification_result"]["authenticated_session_proven"] is False
    assert "authenticated_session_unproven" in artifact["boundaries"]
    assert "authenticated_session_proven_host_headful_only" not in artifact["boundaries"]
    assert "no authenticated session receipt" in artifact["verification_result"]["reason"]
    assert not any(
        request["url"].endswith("/v1/client/sign_ins")
        for request in observed_requests
    )
    assert "browseract@example.test" not in artifact_text
    assert "browseract-secret" not in artifact_text
    assert "browseract@example.test" not in captured
    assert "browseract-secret" not in captured


def test_main_uses_only_explicit_poppy_password_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    output_path = tmp_path / "poppy-provider-probe.json"
    observed_payload: dict[str, object] = {}

    def _fake_http_request(
        url: str,
        *,
        method: str = "GET",
        payload: dict[str, object] | None = None,
    ):
        if url.endswith("/v1/client/sign_ins"):
            observed_payload.update(payload or {})
            return 200, "{}", {}
        return 200, "{}", {}

    monkeypatch.setattr(module, "http_request", _fake_http_request)
    monkeypatch.setattr(module, "list_browseract_workflows", lambda: [])
    monkeypatch.setattr(module, "SESSION_PROBE_PATH", tmp_path / "missing-session.json")
    monkeypatch.setattr(
        module,
        "LOCAL_ENV",
        {
            "POPPY_LOGIN_EMAIL": "poppy@example.test",
            "POPPY_LOGIN_PASSWORD": "poppy-secret",
            "BROWSERACT_USERNAME": "browseract@example.test",
            "BROWSERACT_PASSWORD": "browseract-secret",
        },
    )
    monkeypatch.setattr("sys.argv", [str(SCRIPT_PATH), str(output_path)])

    assert module.main() == 0

    artifact_text = output_path.read_text(encoding="utf-8")
    artifact = json.loads(artifact_text)
    assert artifact["sign_in_probe"]["credentials_configured"] is True
    assert observed_payload == {
        "strategy": "password",
        "identifier": "poppy@example.test",
        "password": "poppy-secret",
    }
    assert "poppy@example.test" not in artifact_text
    assert "poppy-secret" not in artifact_text
    assert "browseract@example.test" not in artifact_text
    assert "browseract-secret" not in artifact_text
