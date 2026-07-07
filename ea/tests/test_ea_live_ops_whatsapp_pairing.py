from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EA_LIVE_OPS_PATH = ROOT / "scripts" / "ea_live_ops.py"


def _load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_probe_whatsapp_pairing_exposes_local_action_surface_when_qr_is_available(monkeypatch) -> None:
    module = _load_script(EA_LIVE_OPS_PATH, "ea_live_ops_whatsapp_pairing_probe_test")
    output_dir = ROOT / ".runtime-test" / "whatsapp-pairing"

    monkeypatch.setattr(module, "_safe_load_whatsapp_binding", lambda args: ({}, ""))
    monkeypatch.setattr(module, "_session_api_base_url", lambda binding, configured: "http://127.0.0.1:8098")
    monkeypatch.setattr(module, "_session_ref", lambda binding, configured: "tibor-wa-web")
    monkeypatch.setattr(
        module,
        "_sidecar_pairing_url",
        lambda **kwargs: (
            "http://127.0.0.1:8098/sessions/tibor-wa-web/pair"
            if kwargs.get("suffix") == "pair"
            else "http://127.0.0.1:8098/sessions/tibor-wa-web/qr.svg"
        ),
    )
    monkeypatch.setattr(
        module,
        "_sidecar_get",
        lambda **kwargs: {
            "ok": True,
            "ready": False,
            "qr_present": True,
            "qr_required": True,
            "status": "qr_required",
            "last_qr_at": "2026-07-02T18:07:27.192Z",
        },
    )
    monkeypatch.setattr(
        module,
        "_sidecar_bytes",
        lambda **kwargs: (b"<svg>qr</svg>", "image/svg+xml; charset=utf-8", {}),
    )
    monkeypatch.setattr(module, "_write_pairing_qr_svg", lambda path, payload: None)

    report = module.probe_whatsapp_pairing(
        args=argparse.Namespace(timeout_seconds=5.0, session_api_base_url="", session_ref=""),
        output_format="json",
        dry_run=True,
        write_qr_svg=True,
        output_dir=str(output_dir),
    )

    assert report["status"] == "available"
    assert report["qr_svg_written"] is True
    assert report["next_action"] == "scan_whatsapp_web_qr"
    assert report["next_action_href"] == "http://127.0.0.1:8098/sessions/tibor-wa-web/pair"
    assert report["next_action_label"] == "Open WhatsApp pairing"
    assert report["next_action_method"] == "get"


def test_probe_operator_readiness_preserves_whatsapp_pairing_action_surface(monkeypatch) -> None:
    module = _load_script(EA_LIVE_OPS_PATH, "ea_live_ops_operator_readiness_pairing_test")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        module,
        "probe_telegram_readiness",
        lambda **kwargs: {"probe_ok": True, "ready": True, "status": "ready", "observed_at": "2026-07-02T18:00:00Z"},
    )
    monkeypatch.setattr(
        module,
        "probe_whatsapp_readiness",
        lambda **kwargs: {
            "probe_ok": True,
            "ready": False,
            "status": "blocked",
            "next_action": "scan_whatsapp_web_qr",
            "sidecar_qr_required": True,
            "sidecar_qr_present": True,
            "observed_at": "2026-07-02T18:00:00Z",
        },
    )

    def _pairing(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return {
            "probe_ok": True,
            "ready": False,
            "status": "available",
            "next_action": "scan_whatsapp_web_qr",
            "next_action_href": "http://127.0.0.1:8098/sessions/tibor-wa-web/pair",
            "next_action_label": "Open WhatsApp pairing",
            "next_action_method": "get",
            "qr_svg_written": True,
            "qr_svg_path": "/docker/EA/.runtime/whatsapp-pairing/tibor-wa-web.svg",
            "pair_url_scope": "host_local",
            "pair_url_actionable_from_telegram": False,
            "observed_at": "2026-07-02T18:00:00Z",
        }

    monkeypatch.setattr(module, "probe_whatsapp_pairing", _pairing)
    monkeypatch.setattr(
        module,
        "probe_teable_recovery",
        lambda **kwargs: {"probe_ok": True, "ready": True, "status": "ready", "observed_at": "2026-07-02T18:00:00Z"},
    )

    report = module.probe_operator_readiness(
        args=argparse.Namespace(),
        telegram_principal_id="principal",
        proactive_principal_id="principal",
        include_proactive=False,
        include_pairing=True,
        output_format="json",
    )

    assert captured["write_qr_svg"] is True
    assert report["status"] == "ready_with_actions"
    pairing = next(item for item in report["components"] if item["key"] == "whatsapp_pairing")
    assert str(pairing["next_action_href"]).endswith("/integrations/whatsapp")
    assert pairing["next_action_label"] == "Open WhatsApp pairing"
    assert pairing["next_action_method"] == "get"
    assert pairing["details"]["qr_svg_written"] is True
    assert pairing["details"]["qr_svg_path"] == "host-local-file:redacted"
    assert any(
        item["component_key"] == "whatsapp_pairing"
        and item["action"] == "scan_whatsapp_web_qr"
        and str(item["href"]).endswith("/integrations/whatsapp")
        for item in report["next_actions"] + report["supplemental_next_actions"]
    )
