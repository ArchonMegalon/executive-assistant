from __future__ import annotations

import json

from tests.smoke_runtime_api_support import build_client as _client


def _assert_public_surface_flags(body: dict[str, object]) -> None:
    flags = body["public_surface_flags"]
    assert isinstance(flags, dict)
    assert set(flags) == {
        "public_memorials_enabled",
        "public_tours_enabled",
        "public_results_enabled",
        "legacy_runtime_surfaces_enabled",
    }
    for value in flags.values():
        assert value in {"true", "false"}


def _assert_memorial_runtime(body: dict[str, object]) -> None:
    runtime = body["memorial_runtime"]
    assert isinstance(runtime, dict)
    assert runtime["state"] in {"disabled", "enabled_unmounted", "mounted_without_flag", "mounted"}
    assert isinstance(runtime["configured_enabled"], bool)
    assert isinstance(runtime["route_mounted"], bool)
    assert runtime["route_path"] == "/memorials/{slug}"
    assert isinstance(runtime["healthcheck_slug"], str)
    assert isinstance(runtime["next_action"], str)


def _assert_whatsapp_runtime(body: dict[str, object]) -> None:
    runtime = body["whatsapp_runtime"]
    assert isinstance(runtime, dict)
    assert runtime["state"] in {"ready", "blocked", "unknown"}
    assert isinstance(runtime["receipt_present"], bool)
    assert isinstance(runtime["next_action"], str)
    assert runtime["operator_action_state"] in {"action_required", "pairing_required", "refresh_recommended", "clear"}
    assert isinstance(runtime["operator_recheck_after_seconds"], int)
    if runtime["receipt_present"]:
        assert isinstance(runtime["receipt_fresh"], bool)
        assert isinstance(runtime["receipt_fresh_seconds"], int)
        assert runtime["receipt_age_seconds"] is None or isinstance(runtime["receipt_age_seconds"], int)
    container_health = runtime["container_health"]
    assert isinstance(container_health, dict)
    assert isinstance(container_health["source"], str)
    assert isinstance(container_health["containers"], list)


def test_health_live_stays_simple_without_memorial_probe(monkeypatch) -> None:
    monkeypatch.delenv("EA_HEALTHCHECK_MEMORIAL_SLUG", raising=False)
    client = _client(storage_backend="memory")
    response = client.get("/health/live")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "live"
    assert "public_surface_flags" in payload
    _assert_public_surface_flags(payload)
    assert "memorial_runtime" in payload
    _assert_memorial_runtime(payload)
    assert "whatsapp_runtime" in payload
    _assert_whatsapp_runtime(payload)
    assert payload["memorial_runtime"]["state"] == "disabled"
    assert payload["memorial_runtime"]["route_mounted"] is False


def test_health_live_includes_memorial_probe_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("EA_HEALTHCHECK_MEMORIAL_SLUG", "manfred")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_SIDE_SURFACES", "1")
    from app.api.routes import health

    monkeypatch.setattr(
        health,
        "_probe_public_memorial_surface",
        lambda slug: {"slug": slug, "voice_plugin": "unmixr_clone", "audio_clip_count": 3, "elapsed_ms": 8.4},
    )
    client = _client(storage_backend="memory")
    response = client.get("/health/live")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "live"
    assert payload["memorial_slug"] == "manfred"
    assert payload["memorial_voice_plugin"] == "unmixr_clone"
    assert payload["memorial_audio_clip_count"] == "3"
    assert payload["memorial_elapsed_ms"] == "8.4"
    assert payload["memorial_latency_tier"] == "premium"
    assert payload["memorial_latency_budget_ms"] == "750"
    assert payload["memorial_operator_action_state"] == "clear"
    assert payload["memorial_latency_next_action"] == "maintain_memorial_voice_runtime"
    assert "public_surface_flags" in payload
    _assert_public_surface_flags(payload)
    assert "memorial_runtime" in payload
    _assert_memorial_runtime(payload)
    assert "whatsapp_runtime" in payload
    _assert_whatsapp_runtime(payload)
    assert payload["memorial_runtime"]["state"] == "mounted"
    assert payload["memorial_runtime"]["route_mounted"] is True
    assert payload["memorial_runtime"]["healthcheck_slug"] == "manfred"


def test_whatsapp_runtime_status_reports_readiness_receipt_without_secrets(monkeypatch, tmp_path) -> None:
    from app.api.routes import health

    receipt_path = tmp_path / "whatsapp_web_action_processor_readiness.generated.json"
    receipt_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.whatsapp_web_action_processor_readiness.v1",
                "generated_at": "2026-06-23T12:00:00Z",
                "ready": False,
                "status": "blocked",
                "reason": "sidecar_not_ready",
                "sidecar_ready": False,
                "sidecar_status": "qr_required",
                "sidecar_health_status": "qr_required",
                "effective_session_ref": "tibor-wa-web",
                "sidecar_last_qr_at": "2026-06-25T09:00:00Z",
                "sidecar_qr_age_seconds": 31,
                "sidecar_qr_fresh": True,
                "sidecar_qr_fresh_seconds": 120,
                "sidecar_qr_present": True,
                "sidecar_qr_required": True,
                "state_age_seconds": 17,
                "next_action": "scan_whatsapp_web_qr",
                "secret": "must-not-leak",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(health, "_WHATSAPP_ACTION_PROCESSOR_READINESS_PATH", receipt_path)
    monkeypatch.setattr(
        health,
        "_docker_container_health",
        lambda names: {
            "source": "docker_inspect",
            "containers": [
                {"name": name, "status": "running", "health": "healthy"}
                for name in names
            ],
        },
    )

    payload = health._whatsapp_runtime_status()

    assert payload["state"] == "blocked"
    assert payload["receipt_present"] is True
    assert payload["receipt_fresh"] is False
    assert isinstance(payload["receipt_age_seconds"], int)
    assert payload["receipt_fresh_seconds"] == 900
    assert payload["next_action"] == "refresh_whatsapp_web_action_processor_readiness_receipt"
    assert payload["receipt_next_action"] == "scan_whatsapp_web_qr"
    assert payload["operator_action_state"] == "refresh_recommended"
    assert payload["operator_recheck_after_seconds"] == 30
    assert payload["contract_name"] == "ea.whatsapp_web_action_processor_readiness.v1"
    assert payload["reason"] == "sidecar_not_ready"
    assert payload["sidecar_status"] == "qr_required"
    assert payload["sidecar_last_qr_at"] == "2026-06-25T09:00:00Z"
    assert payload["sidecar_qr_age_seconds"] == 31
    assert payload["sidecar_qr_fresh"] is True
    assert payload["sidecar_qr_fresh_seconds"] == 120
    assert payload["sidecar_qr_present"] is True
    assert payload["sidecar_qr_required"] is True
    assert payload["operator_pairing_url"] == "http://127.0.0.1:8098/sessions/tibor-wa-web/pair"
    assert payload["operator_pairing_note"] == "Open this local pairing page and scan the WhatsApp Web QR code."
    assert "/qr" not in payload["operator_pairing_url"]
    assert payload["state_age_seconds"] == 17
    assert payload["container_health"]["source"] == "docker_inspect"
    assert len(payload["container_health"]["containers"]) == 3
    assert "secret" not in payload


def test_whatsapp_runtime_status_reports_fresh_receipt(monkeypatch, tmp_path) -> None:
    from app.api.routes import health

    receipt_path = tmp_path / "whatsapp_web_action_processor_readiness.generated.json"
    receipt_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.whatsapp_web_action_processor_readiness.v1",
                "generated_at": "2026-06-25T12:00:00Z",
                "ready": True,
                "status": "ready",
                "reason": "",
                "next_action": "send_epub_over_whatsapp_to_start_or_refresh_live_audiobook_flow",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(health, "_WHATSAPP_ACTION_PROCESSOR_READINESS_PATH", receipt_path)
    monkeypatch.setattr(health, "_docker_container_health", lambda names: {"source": "test", "containers": []})
    monkeypatch.setattr(health, "_age_seconds_since", lambda value: 42)

    payload = health._whatsapp_runtime_status()

    assert payload["state"] == "ready"
    assert payload["receipt_present"] is True
    assert payload["receipt_fresh"] is True
    assert payload["receipt_age_seconds"] == 42
    assert payload["next_action"] == "send_epub_over_whatsapp_to_start_or_refresh_live_audiobook_flow"
    assert payload["receipt_next_action"] == "send_epub_over_whatsapp_to_start_or_refresh_live_audiobook_flow"
    assert payload["operator_action_state"] == "clear"
    assert payload["operator_recheck_after_seconds"] == 120
    assert payload["operator_pairing_url"] == ""
    assert payload["operator_pairing_note"] == ""


def test_whatsapp_pairing_url_encodes_session_ref_and_uses_configured_base(monkeypatch) -> None:
    from app.api.routes import health

    monkeypatch.setenv("EA_WHATSAPP_WEB_SESSION_API_BASE_URL", "http://wa-sidecar.local:8098/")

    payload = {
        "sidecar_status": "qr_required",
        "effective_session_ref": "operator session/one",
    }

    assert (
        health._whatsapp_pairing_url(payload)
        == "http://wa-sidecar.local:8098/sessions/operator%20session%2Fone/pair"
    )
    assert health._whatsapp_pairing_url({"sidecar_status": "ready", "effective_session_ref": "session"}) == ""


def test_whatsapp_runtime_status_reports_pairing_required_for_fresh_qr(monkeypatch, tmp_path) -> None:
    from app.api.routes import health

    receipt_path = tmp_path / "whatsapp_web_action_processor_readiness.generated.json"
    receipt_path.write_text(
        json.dumps(
            {
                "contract_name": "ea.whatsapp_web_action_processor_readiness.v1",
                "generated_at": "2026-06-25T12:00:00Z",
                "ready": False,
                "status": "blocked",
                "reason": "sidecar_not_ready",
                "sidecar_status": "qr_required",
                "effective_session_ref": "tibor-wa-web",
                "sidecar_qr_required": True,
                "sidecar_qr_present": True,
                "sidecar_qr_fresh": True,
                "sidecar_qr_fresh_seconds": 120,
                "sidecar_qr_age_seconds": 8,
                "next_action": "scan_whatsapp_web_qr",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(health, "_WHATSAPP_ACTION_PROCESSOR_READINESS_PATH", receipt_path)
    monkeypatch.setattr(health, "_docker_container_health", lambda names: {"source": "test", "containers": []})
    monkeypatch.setattr(health, "_age_seconds_since", lambda value: 42)

    payload = health._whatsapp_runtime_status()

    assert payload["operator_action_state"] == "pairing_required"
    assert payload["operator_recheck_after_seconds"] == 15
    assert payload["next_action"] == "scan_whatsapp_web_qr"


def test_whatsapp_runtime_status_reports_action_required_when_receipt_missing(monkeypatch, tmp_path) -> None:
    from app.api.routes import health

    monkeypatch.setattr(health, "_WHATSAPP_ACTION_PROCESSOR_READINESS_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(health, "_docker_container_health", lambda names: {"source": "test", "containers": []})

    payload = health._whatsapp_runtime_status()

    assert payload["state"] == "unknown"
    assert payload["receipt_present"] is False
    assert payload["operator_action_state"] == "action_required"
    assert payload["operator_recheck_after_seconds"] == 0


def test_whatsapp_runtime_status_prefers_runtime_receipt_over_stale_published_receipt(monkeypatch, tmp_path) -> None:
    from app.api.routes import health

    runtime_dir = tmp_path / "provider-ledger"
    runtime_receipt = runtime_dir / "provider-health-cache" / "whatsapp_web_action_processor_readiness.generated.json"
    runtime_receipt.parent.mkdir(parents=True, exist_ok=True)
    runtime_receipt.write_text(
        json.dumps(
            {
                "contract_name": "ea.whatsapp_web_action_processor_readiness.v1",
                "generated_at": "2026-06-29T06:40:00Z",
                "ready": True,
                "status": "ready",
                "reason": "",
                "next_action": "send_epub_over_whatsapp_to_start_or_refresh_live_audiobook_flow",
            }
        ),
        encoding="utf-8",
    )
    published_receipt = tmp_path / "published-stale.json"
    published_receipt.write_text(
        json.dumps(
            {
                "contract_name": "ea.whatsapp_web_action_processor_readiness.v1",
                "generated_at": "2026-06-28T01:00:00Z",
                "ready": False,
                "status": "blocked",
                "reason": "sidecar_not_ready",
                "next_action": "restore_whatsapp_web_session_sidecar_readiness",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EA_RESPONSES_PROVIDER_LEDGER_DIR", str(runtime_dir))
    monkeypatch.setattr(health, "_WHATSAPP_ACTION_PROCESSOR_READINESS_PATH", published_receipt)
    monkeypatch.setattr(health, "_docker_container_health", lambda names: {"source": "test", "containers": []})
    monkeypatch.setattr(health, "_age_seconds_since", lambda value: 42)

    payload = health._whatsapp_runtime_status()

    assert payload["state"] == "ready"
    assert payload["receipt_present"] is True
    assert payload["receipt_path"] == str(runtime_receipt)
    assert payload["receipt_fresh"] is True


def test_health_live_marks_slow_memorial_probe_as_degraded_for_loopback(monkeypatch) -> None:
    monkeypatch.setenv("EA_HEALTHCHECK_MEMORIAL_SLUG", "manfred")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_MEMORIALS", "1")
    monkeypatch.setenv("EA_ENABLE_PUBLIC_SIDE_SURFACES", "1")
    from app.api.routes import health

    monkeypatch.setattr(
        health,
        "_probe_public_memorial_surface",
        lambda slug: {"slug": slug, "voice_plugin": "unmixr_clone", "audio_clip_count": 3, "elapsed_ms": 2100.0},
    )
    client = _client(storage_backend="memory")
    response = client.get("/health/live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "live"
    assert payload["memorial_latency_tier"] == "degraded"
    assert payload["memorial_operator_action_state"] == "action_required"
    assert payload["memorial_latency_next_action"] == "optimize_memorial_voice_runtime_latency"
