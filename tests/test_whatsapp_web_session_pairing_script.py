from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "check_whatsapp_web_session_pairing.py"


def _module():
    spec = importlib.util.spec_from_file_location("check_whatsapp_web_session_pairing", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "auth_header_name": "Authorization",
        "auth_header_prefix": "Bearer ",
        "include_qr": False,
        "session_api_base_url": "http://127.0.0.1:8098",
        "session_api_token": "",
        "session_ref": "default-wa-web",
        "timeout_seconds": 5,
    }
    values.update(overrides)
    return Namespace(**values)


def test_build_report_returns_pairing_metadata_without_qr_by_default(monkeypatch) -> None:
    module = _module()
    calls: list[str] = []

    def _fake_request_json(url, args):
        calls.append(url)
        if url.endswith("/status"):
            return 200, {
                "last_qr_at": "2026-06-21T01:10:25Z",
                "qr_required": True,
                "ready": False,
                "status": "qr_required",
            }
        return 200, {
            "last_qr_at": "2026-06-21T01:10:25Z",
            "qr": "secret-qr-payload",
            "qr_present": True,
            "qr_required": True,
            "status": "qr_required",
        }

    monkeypatch.setattr(module, "_request_json", _fake_request_json)

    report = module.build_report(_args())

    assert report["ok"] is True
    assert report["qr_present"] is True
    assert report["qr_required"] is True
    assert report["ready"] is False
    assert report["qr_last_seen_at"] == "2026-06-21T01:10:25Z"
    assert "qr" not in report
    assert calls[-1] == "http://127.0.0.1:8098/sessions/default-wa-web/qr"


def test_build_report_can_include_raw_qr_only_when_requested(monkeypatch) -> None:
    module = _module()
    calls: list[str] = []

    def _fake_request_json(url, args):
        calls.append(url)
        if url.endswith("/status"):
            return 200, {"ready": False, "status": "qr_required"}
        return 200, {
            "last_qr_at": "2026-06-21T01:10:25Z",
            "qr": "secret-qr-payload",
            "qr_present": True,
            "qr_required": True,
            "status": "qr_required",
        }

    monkeypatch.setattr(module, "_request_json", _fake_request_json)

    report = module.build_report(_args(include_qr=True))

    assert report["qr"] == "secret-qr-payload"
    assert calls[-1] == "http://127.0.0.1:8098/sessions/default-wa-web/qr?include=1"


def test_build_report_requires_session_ref() -> None:
    module = _module()

    report = module.build_report(_args(session_ref=""))

    assert report["ok"] is False
    assert report["reason"] == "session_ref_required"


def test_main_returns_zero_for_reachable_sidecar(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(module, "parse_args", lambda: _args())
    monkeypatch.setattr(
        module,
        "_request_json",
        lambda url, args: (200, {"ready": False, "qr_present": True, "qr_required": True, "status": "qr_required"}),
    )

    exit_code = module.main()
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["ok"] is True
