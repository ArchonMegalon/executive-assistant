from __future__ import annotations

import copy
import importlib.util
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = ROOT / "scripts"


def _load_script(name: str):
    path = SCRIPTS_ROOT / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _patch_source_state(monkeypatch, *modules) -> None:
    for module in modules:
        monkeypatch.setattr(module, "resolve_source_state_head", lambda _root: "source-head")
        monkeypatch.setattr(module, "resolve_source_worktree_fingerprint", lambda _root: "source-fingerprint")


def _valid_probe_report() -> dict[str, object]:
    return {
        "contract_name": "ea.operator_readiness.v1",
        "probe_ok": True,
        "ready": False,
        "status": "ready_with_actions",
        "component_count": 2,
        "attention_required_count": 1,
        "blocked_count": 1,
        "probe_failed_count": 0,
        "components": [
            {
                "key": "telegram",
                "label": "Telegram operator delivery",
                "probe_ok": True,
                "ready": True,
                "status": "ready",
                "reason": "",
                "next_action": "",
                "next_action_href": "",
                "next_action_label": "",
                "next_action_method": "",
                "observed_at": "2026-07-04T20:00:00Z",
                "source": "telegram_probe",
                "details": {
                    "principal_id": "principal-1",
                    "binding_id": "binding-1",
                    "chat_ref_present": True,
                    "bot_key": "default",
                    "bot_handle": "ea_concierge_bot",
                    "bot_token_present": True,
                    "runtime_container": "ea-api",
                },
            },
            {
                "key": "google_workspace_oauth",
                "label": "Google Workspace OAuth",
                "probe_ok": True,
                "ready": False,
                "status": "blocked_setup_required",
                "reason": "expected_google_email_missing",
                "next_action": "set_google_workspace_expected_email_and_refresh_receipt",
                "next_action_href": "/integrations/google",
                "next_action_label": "Configure Google auth",
                "next_action_method": "get",
                "observed_at": "2026-07-04T20:00:01Z",
                "source": "ea_live_ops.aggregate",
                "details": {
                    "scope_bundle": "full_workspace",
                    "expected_google_email_present": False,
                    "expected_google_domain": "gmail.com",
                    "observed_google_email_present": True,
                    "observed_google_domain": "gmail.com",
                    "observed_google_account_matches_expected": True,
                    "runtime_expected_google_email_present": False,
                    "console_deep_link": "https://console.cloud.google.com/auth/audience?project=propertyquarry-498318",
                    "next_action_href": "/integrations/google",
                    "next_action_label": "Configure Google auth",
                    "next_action_method": "get",
                    "last_receipt_status": "ready_retry_required",
                    "last_receipt_reason": "oauth_retry_or_account_selection_required",
                    "last_receipt_observed_at": "2026-07-04T15:23:32Z",
                    "last_receipt_source": (
                        "published_receipt:/docker/EA/.codex-studio/published/"
                        "ea_google_workspace_oauth_readiness.generated.json"
                    ),
                    "last_receipt_age_seconds": 12000,
                    "last_receipt_max_age_seconds": 7200,
                    "last_receipt_fresh": False,
                },
            },
        ],
        "next_actions": [
            {
                "component_key": "google_workspace_oauth",
                "component_label": "Google Workspace OAuth",
                "action": "set_google_workspace_expected_email_and_refresh_receipt",
                "reason": "expected_google_email_missing",
                "href": "/integrations/google",
                "label": "Configure Google auth",
                "method": "get",
            }
        ],
        "next_action_href": "/integrations/google",
        "next_action_label": "Configure Google auth",
        "next_action_method": "get",
        "observed_at": "2026-07-04T20:00:02Z",
        "source": "ea_live_ops.aggregate",
    }


def test_materialize_ea_operator_readiness_defaults_to_active_pairing_and_verifies(monkeypatch, tmp_path: Path) -> None:
    materializer = _load_script("materialize_ea_operator_readiness")
    verifier = _load_script("verify_ea_operator_readiness")
    _patch_source_state(monkeypatch, materializer, verifier)
    monkeypatch.setattr(materializer.ea_live_ops, "_default_proactive_principal_id", lambda: "principal-1")
    captured: dict[str, object] = {}

    def fake_probe_operator_readiness(**kwargs):
        captured.update(kwargs)
        return copy.deepcopy(_valid_probe_report())

    monkeypatch.setattr(materializer.ea_live_ops, "probe_operator_readiness", fake_probe_operator_readiness)

    receipt_path = tmp_path / "ea_operator_readiness.generated.json"
    receipt = materializer.build_receipt(output_path=receipt_path)

    assert captured["include_pairing"] is True
    assert captured["include_proactive"] is True
    assert captured["timeout_seconds"] == 30.0
    assert receipt["pairing_probe_mode"] == "active"
    assert receipt["component_keys"] == ["telegram", "google_workspace_oauth"]
    assert receipt["next_action"] == "set_google_workspace_expected_email_and_refresh_receipt"
    telegram_component = receipt["components"][0]
    assert telegram_component["details"]["principal_id_present"] is True
    assert telegram_component["details"]["binding_id_present"] is True
    assert "principal_id" not in telegram_component["details"]
    assert "binding_id" not in telegram_component["details"]
    assert "operator_readiness status=ready_with_actions" in receipt["summary"]
    assert verifier.verify_receipt_for_test(receipt) == []
    assert receipt_path.exists()


def test_materialize_ea_operator_readiness_forwards_optional_sonarr_target(monkeypatch, tmp_path: Path) -> None:
    materializer = _load_script("materialize_ea_operator_readiness")
    verifier = _load_script("verify_ea_operator_readiness")
    _patch_source_state(monkeypatch, materializer, verifier)
    monkeypatch.setattr(materializer.ea_live_ops, "_default_proactive_principal_id", lambda: "principal-1")
    captured: dict[str, object] = {}

    payload = copy.deepcopy(_valid_probe_report())
    payload["component_count"] = 3
    payload["components"] = list(payload["components"]) + [
        {
            "key": "sonarr_tv_season",
            "label": "Sonarr TV season import",
            "probe_ok": True,
            "ready": True,
            "status": "ready",
            "reason": "",
            "next_action": "",
            "next_action_href": "",
            "next_action_label": "",
            "next_action_method": "",
            "observed_at": "2026-07-05T15:07:30Z",
            "source": "sonarr.api+filesystem",
            "details": {
                "series_id": 36,
                "series_title": "LEGO Ninjago: Dragons Rising",
                "season_number": 2,
                "season_monitored": True,
                "series_monitored": True,
                "season_episode_count": 20,
                "season_episode_file_count": 20,
                "metadata_queue_count": 0,
                "stale_metadata_queue_count": 0,
                "staging_candidate_count": 1,
                "selected_staging_candidate_name": "LEGO.Ninjago.Dragons.Rising.S02.1080p.NF.WEB-DL.DDP5.1.H.264-STRiKES",
                "selected_staging_candidate_cover_count": 0,
            },
        }
    ]

    def fake_probe_operator_readiness(**kwargs):
        captured.update(kwargs)
        return copy.deepcopy(payload)

    monkeypatch.setattr(materializer.ea_live_ops, "probe_operator_readiness", fake_probe_operator_readiness)

    receipt = materializer.build_receipt(
        output_path=tmp_path / "ea_operator_readiness.generated.json",
        sonarr_series_id=36,
        sonarr_season_number=2,
    )

    assert captured["sonarr_series_id"] == 36
    assert captured["sonarr_series_title"] == ""
    assert captured["sonarr_season_number"] == 2
    assert receipt["include_sonarr"] is True
    assert receipt["sonarr_target_series_id"] == 36
    assert receipt["sonarr_target_series_title"] == ""
    assert receipt["sonarr_target_season_number"] == 2
    assert "sonarr_tv_season" in receipt["component_keys"]
    assert verifier.verify_receipt_for_test(receipt) == []


def test_verify_ea_operator_readiness_rejects_forbidden_detail_key(monkeypatch) -> None:
    materializer = _load_script("materialize_ea_operator_readiness")
    verifier = _load_script("verify_ea_operator_readiness")
    _patch_source_state(monkeypatch, materializer, verifier)
    monkeypatch.setattr(materializer.ea_live_ops, "_default_proactive_principal_id", lambda: "principal-1")
    monkeypatch.setattr(materializer.ea_live_ops, "probe_operator_readiness", lambda **_kwargs: copy.deepcopy(_valid_probe_report()))

    receipt = materializer.build_receipt(output_path=Path("/tmp/ea_operator_readiness.generated.json"))
    receipt["components"][0]["details"]["raw_bot_token"] = "secret"

    issues = verifier.verify_receipt_for_test(receipt)

    assert any("unexpected detail keys" in issue for issue in issues)
    assert any("must not expose raw detail key" in issue for issue in issues)


def test_main_materialize_ea_operator_readiness_prints_json(monkeypatch, capsys) -> None:
    materializer = _load_script("materialize_ea_operator_readiness")
    monkeypatch.setattr(
        materializer,
        "parse_args",
        lambda _argv=None: materializer.argparse.Namespace(
            output=Path("/tmp/ea_operator_readiness.generated.json"),
            generated_at="",
            telegram_principal_id="principal-1",
            proactive_principal_id="principal-1",
            compose_file="/docker/EA/docker-compose.yml",
            runtime_service="ea-proactive-ooda",
            receipt_path="/data/provider-ledger/proactive_ooda_latest_run.generated.json",
            timeout_seconds=30.0,
            include_proactive=True,
            include_pairing=True,
            sonarr_series_id=0,
            sonarr_series_title="",
            sonarr_season_number=0,
            pretty=False,
        ),
    )
    monkeypatch.setattr(
        materializer,
        "build_receipt",
        lambda **_kwargs: {"contract_name": "ea.operator_readiness.v1", "status": "ready", "component_count": 0},
    )

    assert materializer.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["contract_name"] == "ea.operator_readiness.v1"
    assert payload["status"] == "ready"


def test_materialize_ea_operator_readiness_can_disable_pairing(monkeypatch, tmp_path: Path) -> None:
    materializer = _load_script("materialize_ea_operator_readiness")
    verifier = _load_script("verify_ea_operator_readiness")
    _patch_source_state(monkeypatch, materializer, verifier)
    monkeypatch.setattr(materializer.ea_live_ops, "_default_proactive_principal_id", lambda: "principal-1")
    captured: dict[str, object] = {}

    def fake_probe_operator_readiness(**kwargs):
        captured.update(kwargs)
        return copy.deepcopy(_valid_probe_report())

    monkeypatch.setattr(materializer.ea_live_ops, "probe_operator_readiness", fake_probe_operator_readiness)

    receipt = materializer.build_receipt(
        output_path=tmp_path / "ea_operator_readiness.generated.json",
        include_pairing=False,
    )

    assert captured["include_pairing"] is False
    assert receipt["pairing_probe_mode"] == "passive"
    assert verifier.verify_receipt_for_test(receipt) == []


def test_materialize_ea_operator_readiness_suppresses_duplicate_whatsapp_qr_blocker(monkeypatch, tmp_path: Path) -> None:
    materializer = _load_script("materialize_ea_operator_readiness")
    verifier = _load_script("verify_ea_operator_readiness")
    _patch_source_state(monkeypatch, materializer, verifier)
    monkeypatch.setattr(materializer.ea_live_ops, "_default_proactive_principal_id", lambda: "principal-1")

    payload = {
        "contract_name": "ea.operator_readiness.v1",
        "probe_ok": True,
        "ready": False,
        "status": "ready_with_actions",
        "component_count": 3,
        "attention_required_count": 1,
        "blocked_count": 1,
        "probe_failed_count": 0,
        "components": [
            {
                "key": "whatsapp",
                "label": "WhatsApp Web action processor",
                "probe_ok": True,
                "ready": False,
                "status": "blocked",
                "reason": "sidecar_not_ready",
                "next_action": "scan_whatsapp_web_qr",
                "next_action_href": "",
                "next_action_label": "",
                "next_action_method": "",
                "observed_at": "2026-07-04T20:00:00Z",
                "source": "whatsapp_probe",
                "details": {},
            },
            {
                "key": "whatsapp_pairing",
                "label": "WhatsApp Web pairing recovery",
                "probe_ok": True,
                "ready": False,
                "status": "available",
                "reason": "",
                "next_action": "scan_whatsapp_web_qr",
                "next_action_href": "",
                "next_action_label": "",
                "next_action_method": "",
                "observed_at": "2026-07-04T20:00:01Z",
                "source": "whatsapp_pairing_probe",
                "details": {},
            },
            {
                "key": "telegram",
                "label": "Telegram operator delivery",
                "probe_ok": True,
                "ready": True,
                "status": "ready",
                "reason": "",
                "next_action": "",
                "next_action_href": "",
                "next_action_label": "",
                "next_action_method": "",
                "observed_at": "2026-07-04T20:00:02Z",
                "source": "telegram_probe",
                "details": {
                    "principal_id": "principal-1",
                    "binding_id": "binding-1",
                    "chat_ref_present": True,
                    "bot_key": "default",
                    "bot_handle": "ea_concierge_bot",
                    "bot_token_present": True,
                    "runtime_container": "ea-api",
                },
            },
        ],
        "next_actions": [
            {
                "component_key": "whatsapp_pairing",
                "component_label": "WhatsApp Web pairing recovery",
                "action": "scan_whatsapp_web_qr",
                "reason": "",
                "href": "",
                "label": "",
                "method": "",
            }
        ],
        "next_action_href": "",
        "next_action_label": "",
        "next_action_method": "",
        "observed_at": "2026-07-04T20:00:03Z",
        "source": "ea_live_ops.aggregate",
    }
    monkeypatch.setattr(materializer.ea_live_ops, "probe_operator_readiness", lambda **_kwargs: copy.deepcopy(payload))

    receipt = materializer.build_receipt(output_path=tmp_path / "ea_operator_readiness.generated.json", include_pairing=True)

    assert receipt["component_keys"] == ["whatsapp", "whatsapp_pairing", "telegram"]
    assert receipt["blocked_count"] == 1
    assert receipt["attention_required_count"] == 1
    assert receipt["blocked_component_keys"] == ["whatsapp_pairing"]
    assert receipt["attention_component_keys"] == ["whatsapp_pairing"]
    assert receipt["next_action"] == "scan_whatsapp_web_qr"
    assert verifier.verify_receipt_for_test(receipt) == []


def test_materialize_ea_operator_readiness_keeps_backup_channels_supplemental_when_proactive_route_uses_telegram(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_ea_operator_readiness")
    verifier = _load_script("verify_ea_operator_readiness")
    _patch_source_state(monkeypatch, materializer, verifier)
    monkeypatch.setattr(materializer.ea_live_ops, "_default_proactive_principal_id", lambda: "principal-1")

    payload = {
        "contract_name": "ea.operator_readiness.v1",
        "probe_ok": True,
        "ready": False,
        "status": "ready_with_actions",
        "component_count": 5,
        "attention_required_count": 2,
        "blocked_count": 1,
        "probe_failed_count": 0,
        "components": [
            {
                "key": "telegram",
                "label": "Telegram operator delivery",
                "probe_ok": True,
                "ready": True,
                "status": "ready",
                "reason": "",
                "next_action": "",
                "next_action_href": "",
                "next_action_label": "",
                "next_action_method": "",
                "observed_at": "2026-07-05T16:00:00Z",
                "source": "telegram_probe",
                "details": {
                    "principal_id": "principal-1",
                    "binding_id": "binding-1",
                    "chat_ref_present": True,
                    "bot_key": "default",
                    "bot_handle": "ea_concierge_bot",
                    "bot_token_present": True,
                    "runtime_container": "ea-api",
                },
            },
            {
                "key": "pushbullet",
                "label": "Pushbullet operator delivery",
                "probe_ok": True,
                "ready": False,
                "status": "blocked_setup_required",
                "reason": "pushbullet_token_missing:elisabeth",
                "next_action": "create_missing_pushbullet_access_tokens",
                "next_action_href": "https://www.pushbullet.com/#settings/account",
                "next_action_label": "Open Pushbullet account settings",
                "next_action_method": "get",
                "observed_at": "2026-07-05T16:00:01Z",
                "source": "pushbullet_probe",
                "details": {},
            },
            {
                "key": "whatsapp",
                "label": "WhatsApp Web action processor",
                "probe_ok": True,
                "ready": False,
                "status": "blocked",
                "reason": "sidecar_not_ready",
                "next_action": "scan_whatsapp_web_qr",
                "next_action_href": "",
                "next_action_label": "",
                "next_action_method": "",
                "observed_at": "2026-07-05T16:00:02Z",
                "source": "whatsapp_probe",
                "details": {},
            },
            {
                "key": "whatsapp_pairing",
                "label": "WhatsApp Web pairing recovery",
                "probe_ok": True,
                "ready": False,
                "status": "available",
                "reason": "",
                "next_action": "scan_whatsapp_web_qr",
                "next_action_href": "http://127.0.0.1:8098/sessions/tibor-wa-web/pair",
                "next_action_label": "Open WhatsApp pairing",
                "next_action_method": "get",
                "observed_at": "2026-07-05T16:00:03Z",
                "source": "whatsapp_pairing_probe",
                "details": {},
            },
            {
                "key": "proactive_route",
                "label": "Proactive OODA delivery route",
                "probe_ok": True,
                "ready": True,
                "status": "ready",
                "reason": "",
                "next_action": "",
                "next_action_href": "",
                "next_action_label": "",
                "next_action_method": "",
                "observed_at": "2026-07-05T16:00:04Z",
                "source": "proactive_route_probe",
                "details": {
                    "principal_id": "principal-1",
                    "runtime_service": "ea-proactive-ooda",
                    "delivery_route_ready": True,
                    "selected_channel": "telegram",
                    "selected_transport": "telegram_business",
                    "selected_by": "delivery_registry",
                    "available_channels": ["telegram", "whatsapp"],
                    "blocking_reason": "",
                    "approval_capture_surface_ready": True,
                    "approval_capture_surface_pending_count": 0,
                },
            },
        ],
        "next_actions": [],
        "observed_at": "2026-07-05T16:00:05Z",
        "source": "ea_live_ops.aggregate",
    }
    monkeypatch.setattr(materializer.ea_live_ops, "probe_operator_readiness", lambda **_kwargs: copy.deepcopy(payload))

    receipt = materializer.build_receipt(output_path=tmp_path / "ea_operator_readiness.generated.json", include_pairing=True)

    assert receipt["status"] == "ready"
    assert receipt["ready"] is True
    assert receipt["attention_required_count"] == 0
    assert receipt["blocked_count"] == 0
    assert receipt["next_action"] == ""
    assert receipt["supplemental_attention_component_keys"] == ["pushbullet", "whatsapp_pairing"]
    assert [row["component_key"] for row in receipt["supplemental_next_actions"]] == ["pushbullet", "whatsapp_pairing"]
    assert receipt["supplemental_next_actions"][0]["reason"] == "pushbullet_token_missing"
    assert receipt["supplemental_next_actions"][1]["href"] == "https://myexternalbrain.com/integrations/whatsapp"
    telegram_component = receipt["components"][0]
    assert "principal_id" not in telegram_component["details"]
    assert telegram_component["details"]["principal_id_present"] is True
    assert "supplemental_attention=2" in receipt["summary"]
    assert "states=telegram:ready,proactive_route:ready" in receipt["summary"]
    assert "supplemental_states=pushbullet:blocked_setup_required,whatsapp_pairing:available" in receipt["summary"]
    assert verifier.verify_receipt_for_test(receipt) == []


def test_materialize_ea_operator_readiness_lets_whatsapp_pairing_steer_when_proactive_route_uses_whatsapp(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materializer = _load_script("materialize_ea_operator_readiness")
    verifier = _load_script("verify_ea_operator_readiness")
    _patch_source_state(monkeypatch, materializer, verifier)
    monkeypatch.setattr(materializer.ea_live_ops, "_default_proactive_principal_id", lambda: "principal-1")

    payload = {
        "contract_name": "ea.operator_readiness.v1",
        "probe_ok": True,
        "ready": False,
        "status": "ready_with_actions",
        "component_count": 3,
        "attention_required_count": 1,
        "blocked_count": 1,
        "probe_failed_count": 0,
        "components": [
            {
                "key": "telegram",
                "label": "Telegram operator delivery",
                "probe_ok": True,
                "ready": True,
                "status": "ready",
                "reason": "",
                "next_action": "",
                "next_action_href": "",
                "next_action_label": "",
                "next_action_method": "",
                "observed_at": "2026-07-05T16:00:00Z",
                "source": "telegram_probe",
                "details": {
                    "principal_id": "principal-1",
                    "binding_id": "binding-1",
                    "chat_ref_present": True,
                    "bot_key": "default",
                    "bot_handle": "ea_concierge_bot",
                    "bot_token_present": True,
                    "runtime_container": "ea-api",
                },
            },
            {
                "key": "whatsapp_pairing",
                "label": "WhatsApp Web pairing recovery",
                "probe_ok": True,
                "ready": False,
                "status": "available",
                "reason": "",
                "next_action": "scan_whatsapp_web_qr",
                "next_action_href": "http://127.0.0.1:8098/sessions/tibor-wa-web/pair",
                "next_action_label": "Open WhatsApp pairing",
                "next_action_method": "get",
                "observed_at": "2026-07-05T16:00:01Z",
                "source": "whatsapp_pairing_probe",
                "details": {},
            },
            {
                "key": "proactive_route",
                "label": "Proactive OODA delivery route",
                "probe_ok": True,
                "ready": True,
                "status": "ready",
                "reason": "",
                "next_action": "",
                "next_action_href": "",
                "next_action_label": "",
                "next_action_method": "",
                "observed_at": "2026-07-05T16:00:02Z",
                "source": "proactive_route_probe",
                "details": {
                    "principal_id": "principal-1",
                    "runtime_service": "ea-proactive-ooda",
                    "delivery_route_ready": True,
                    "selected_channel": "whatsapp",
                    "selected_transport": "whatsapp_web",
                    "selected_by": "delivery_registry",
                    "available_channels": ["telegram", "whatsapp"],
                    "blocking_reason": "",
                    "approval_capture_surface_ready": True,
                    "approval_capture_surface_pending_count": 0,
                },
            },
        ],
        "next_actions": [],
        "observed_at": "2026-07-05T16:00:03Z",
        "source": "ea_live_ops.aggregate",
    }
    monkeypatch.setattr(materializer.ea_live_ops, "probe_operator_readiness", lambda **_kwargs: copy.deepcopy(payload))

    receipt = materializer.build_receipt(output_path=tmp_path / "ea_operator_readiness.generated.json", include_pairing=True)

    assert receipt["status"] == "ready_with_actions"
    assert receipt["ready"] is False
    assert receipt["attention_component_keys"] == ["whatsapp_pairing"]
    assert receipt["next_action"] == "scan_whatsapp_web_qr"
    assert receipt["next_action_href"] == "https://myexternalbrain.com/integrations/whatsapp"
    assert receipt["supplemental_attention_component_keys"] == []
    assert verifier.verify_receipt_for_test(receipt) == []


def test_collect_operator_readiness_components_times_out_slow_probe() -> None:
    live_ops = _load_script("ea_live_ops")

    started = time.monotonic()
    components, results = live_ops._collect_operator_readiness_components(  # noqa: SLF001
        [
            ("slow_probe", "Slow probe", lambda: (time.sleep(0.25), {"status": "ready"})[1]),
            ("fast_probe", "Fast probe", lambda: {"status": "ready", "ready": True, "probe_ok": True}),
        ],
        per_component_timeout_seconds=0.05,
    )
    elapsed = time.monotonic() - started

    assert elapsed < 0.2
    assert [component["key"] for component in components] == ["slow_probe", "fast_probe"]
    assert components[0]["status"] == "probe_failed"
    assert components[0]["reason"] == "probe_timeout"
    assert components[1]["status"] == "ready"
    assert results["slow_probe"]["component"]["reason"] == "probe_timeout"
