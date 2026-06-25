from __future__ import annotations

import importlib.util
import io
import json
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "ea_live_ops.py"


def _module():
    spec = importlib.util.spec_from_file_location("ea_live_ops", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "database_url": "postgresql://ea:test@localhost/ea",
        "binding_id": "ea-whatsapp-web-session",
        "principal_id": "principal-default",
        "session_api_base_url": "https://wa-web.test",
        "session_ref": "",
        "timeout_seconds": 5.0,
        "dry_run": False,
    }
    values.update(overrides)
    return Namespace(**values)


def test_probe_provider_unmixr_operator_format_uses_runtime_preflight(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_runtime_container_preflight", lambda: {})
    monkeypatch.setattr(
        module,
        "audiobook_runtime_preflight",
        lambda: {
            "contract_name": "ea.telegram_epub_audiobook_runtime_preflight.v1",
            "observed_at": "2026-06-23T10:00:00Z",
            "provider": {
                "api_key_slot_count": 3,
                "voice_catalog_count": 11,
                "voice_discovery_enabled": True,
                "unmixr_auto_render_enabled": True,
                "voice_audition_min_candidates": 3,
            },
            "status": "pass",
        },
    )
    monkeypatch.setattr(module, "_provider_display_name", lambda _provider_key: "Unmixr AI")

    report = module.probe_provider("unmixr", output_format="operator")

    assert report["provider_key"] == "unmixr"
    assert report["remaining"] == 3
    assert report["unit"] == "configured_api_key_slots"
    assert "remaining=3 configured_api_key_slots" in str(report["operator_text"])
    assert "observed_at=2026-06-23T10:00:00Z" in str(report["operator_text"])


def test_probe_provider_unmixr_treats_optional_preflight_warnings_as_operationally_pass(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_runtime_container_preflight", lambda: {})
    monkeypatch.setattr(
        module,
        "audiobook_runtime_preflight",
        lambda: {
            "contract_name": "ea.telegram_epub_audiobook_runtime_preflight.v1",
            "observed_at": "2026-06-23T10:00:00Z",
            "status": "warn",
            "failed_checks": [],
            "warned_checks": ["player_access_base_url_present", "unmixr_bulk_pacing_configured"],
            "checks": [
                {"key": "telegram_audiobook_enabled", "status": "pass"},
                {"key": "jobs_root_durable", "status": "pass"},
                {"key": "jobs_root_writable", "status": "pass"},
                {"key": "external_tts_enabled", "status": "pass"},
                {"key": "unmixr_auto_render_enabled", "status": "pass"},
                {"key": "voice_catalog_configured", "status": "pass"},
            ],
            "provider": {
                "api_key_slot_count": 3,
                "voice_catalog_count": 11,
                "voice_discovery_enabled": True,
                "unmixr_auto_render_enabled": True,
                "voice_audition_min_candidates": 3,
            },
        },
    )
    monkeypatch.setattr(module, "_provider_display_name", lambda _provider_key: "Unmixr AI")

    report = module.probe_provider("unmixr", output_format="json")

    assert report["status"] == "pass"
    assert report["raw"]["preflight_status"] == "warn"
    assert report["raw"]["preflight_warned_checks"] == [
        "player_access_base_url_present",
        "unmixr_bulk_pacing_configured",
    ]


def test_probe_provider_unmixr_prefers_runtime_container_preflight(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "_runtime_container_preflight",
        lambda: {
            "contract_name": "ea.telegram_epub_audiobook_runtime_preflight.v1",
            "observed_at": "2026-06-23T10:00:00Z",
            "status": "warn",
            "failed_checks": [],
            "warned_checks": ["player_access_base_url_present"],
            "checks": [
                {"key": "telegram_audiobook_enabled", "status": "pass"},
                {"key": "jobs_root_durable", "status": "pass"},
                {"key": "jobs_root_writable", "status": "pass"},
                {"key": "external_tts_enabled", "status": "pass"},
                {"key": "unmixr_auto_render_enabled", "status": "pass"},
                {"key": "voice_catalog_configured", "status": "pass"},
            ],
            "provider": {
                "api_key_slot_count": 3,
                "voice_catalog_count": 290,
                "voice_discovery_enabled": True,
                "unmixr_auto_render_enabled": True,
                "voice_audition_min_candidates": 3,
            },
        },
    )
    monkeypatch.setattr(module, "audiobook_runtime_preflight", lambda: {"status": "fail", "provider": {"api_key_slot_count": 0, "voice_catalog_count": 0}})
    monkeypatch.setattr(module, "_provider_display_name", lambda _provider_key: "Unmixr AI")
    monkeypatch.setattr(module, "_runtime_container_name", lambda: "ea-api")

    report = module.probe_provider("unmixr", output_format="json")

    assert report["status"] == "pass"
    assert report["remaining"] == 3
    assert report["raw"]["runtime_container"] == "ea-api"
    assert report["raw"]["preflight_status"] == "warn"


def test_resolve_whatsapp_matches_phone_hint_suffix_and_returns_chat_ref(monkeypatch) -> None:
    module = _module()
    binding = SimpleNamespace(
        binding_id="binding-1",
        principal_id="principal-1",
        auth_metadata_json={"session_ref": "tibor-wa-web", "session_send_url_template": "https://wa-web.test/sessions/{session_ref}/messages"},
    )
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: binding)
    monkeypatch.setattr(module, "_session_ref", lambda _binding, _explicit="": "tibor-wa-web")

    def _fake_sidecar_get(*, suffix: str, **_kwargs):
        if suffix == "heyy-ai-routes":
            return {
                "routes": [
                    {"route_key": "default", "inbound_number_digits": "*", "ai_key": "empathetic_slow_typing_old_lady", "ai_name": "Herta"},
                    {"route_key": "436647916419", "inbound_number_digits": "436647916419", "ai_key": "empathetic_slow_typing_old_lady", "ai_name": "Herta"},
                ]
            }
        if suffix.startswith("conversations?"):
            return {
                "conversations": [
                    {
                        "chat_ref": "chat-ref-1",
                        "updated_at": "2026-06-23T10:05:00Z",
                        "messages": [{"sender_digits": "436647916419"}],
                    }
                ]
            }
        if suffix.startswith("recipients/"):
            return {
                "registered": True,
                "resolution_method": "phone_chat_id",
                "chat_id_kind": "phone",
            }
        raise AssertionError(suffix)

    monkeypatch.setattr(module, "_sidecar_get", _fake_sidecar_get)

    report = module.resolve_whatsapp("*6419", args=_args())

    assert report["status"] == "resolved"
    assert report["recipient_digits"] == "436647916419"
    assert report["route_key"] == "436647916419"
    assert report["chat_ref"] == "chat-ref-1"
    assert report["registered"] is True
    assert report["resolution_method"] == "phone_chat_id"


def test_resolve_whatsapp_returns_blocked_report_when_sidecar_conversations_not_ready(monkeypatch) -> None:
    module = _module()
    binding = SimpleNamespace(
        binding_id="binding-1",
        principal_id="principal-1",
        auth_metadata_json={"session_ref": "tibor-wa-web", "session_send_url_template": "https://wa-web.test/sessions/{session_ref}/messages"},
    )
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: binding)
    monkeypatch.setattr(module, "_session_ref", lambda _binding, _explicit="": "tibor-wa-web")

    def _fake_sidecar_get(*, suffix: str, **_kwargs):
        if suffix == "heyy-ai-routes":
            return {
                "routes": [
                    {"route_key": "436647916419", "inbound_number_digits": "436647916419", "ai_key": "empathetic_slow_typing_old_lady", "ai_name": "Herta"}
                ]
            }
        if suffix.startswith("conversations?"):
            raise module.urllib.error.HTTPError(
                "https://wa-web.test/sessions/tibor-wa-web/conversations",
                409,
                "Conflict",
                {},
                io.BytesIO(b'{"ok":false,"reason":"session_not_ready","status":"qr_required"}'),
            )
        raise AssertionError(suffix)

    monkeypatch.setattr(module, "_sidecar_get", _fake_sidecar_get)

    report = module.resolve_whatsapp("*6419", args=_args())

    assert report["status"] == "resolved"
    assert report["recipient_digits"] == "436647916419"
    assert report["conversation_lookup_ready"] is False
    assert report["conversation_lookup_status"] == "qr_required"
    assert report["conversation_lookup_status_code"] == 409
    assert report["reason"] == "session_not_ready"


def test_send_whatsapp_dry_run_avoids_delivery(monkeypatch) -> None:
    module = _module()
    binding = SimpleNamespace(binding_id="binding-1", principal_id="principal-1")
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: binding)
    monkeypatch.setattr(
        module,
        "resolve_whatsapp",
        lambda _phone_hint, args: {
            "status": "resolved",
            "recipient_digits": "436647916419",
            "route_key": "436647916419",
        },
    )

    def _unexpected_post(**_kwargs):
        raise AssertionError("send should not run during dry-run")

    monkeypatch.setattr(module, "_sidecar_post", _unexpected_post)

    report = module.send_whatsapp(phone_hint="*6419", text="status update", args=_args(dry_run=True))

    assert report["sent"] is False
    assert report["reason"] == "dry_run"
    assert report["recipient_digits"] == "436647916419"
    assert report["binding_id"] == "binding-1"


def test_session_ref_falls_back_to_readiness_receipt_when_binding_and_env_are_missing(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    receipt_path = tmp_path / "readiness.json"
    receipt_path.write_text(json.dumps({"effective_session_ref": "tibor-wa-web"}), encoding="utf-8")
    monkeypatch.setattr(module, "DEFAULT_READINESS_RECEIPT_PATH", receipt_path)
    monkeypatch.delenv("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF", raising=False)

    assert module._session_ref(None) == "tibor-wa-web"


def test_session_ref_falls_back_to_readiness_receipt_when_binding_session_ref_is_blank(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    receipt_path = tmp_path / "readiness.json"
    receipt_path.write_text(json.dumps({"effective_session_ref": "tibor-wa-web"}), encoding="utf-8")
    monkeypatch.setattr(module, "DEFAULT_READINESS_RECEIPT_PATH", receipt_path)
    monkeypatch.delenv("EA_WHATSAPP_WEB_DEFAULT_SESSION_REF", raising=False)
    binding = SimpleNamespace(
        auth_metadata_json={"session_ref": "", "session_send_url_template": "https://wa-web.test/sessions/{session_ref}/messages"}
    )

    assert module._session_ref(binding) == "tibor-wa-web"


def test_resolve_whatsapp_without_binding_uses_recent_sender_to_narrow_routes(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: None)
    monkeypatch.setattr(module, "_session_ref", lambda _binding, _explicit="": "tibor-wa-web")

    def _fake_sidecar_get(*, suffix: str, **_kwargs):
        if suffix == "heyy-ai-routes":
            return {
                "routes": [
                    {"route_key": "436647016419", "ai_key": "chummer_run_casey", "ai_name": "Casey from Chummer.run"},
                    {"route_key": "436647916419", "ai_key": "empathetic_slow_typing_old_lady", "ai_name": "Herta (Heyy Lady)"},
                ]
            }
        if suffix.startswith("conversations?"):
            return {
                "conversations": [
                    {
                        "chat_ref": "chat-ref-1",
                        "updated_at": "2026-06-23T10:05:00Z",
                        "messages": [{"sender_digits": "436647916419"}],
                    }
                ]
            }
        if suffix.startswith("recipients/"):
            return {
                "registered": True,
                "resolution_method": "number_id",
                "chat_id_kind": "lid",
            }
        raise AssertionError(suffix)

    monkeypatch.setattr(module, "_sidecar_get", _fake_sidecar_get)

    report = module.resolve_whatsapp("*6419", args=_args(database_url=""))

    assert report["status"] == "resolved"
    assert report["candidate_count"] == 1
    assert report["route_key"] == "436647916419"
    assert report["recipient_digits"] == "436647916419"
    assert report["chat_ref"] == "chat-ref-1"
    assert report["registered"] is True
    assert report["chat_id_kind"] == "lid"


def test_resolve_whatsapp_uses_recipient_chat_ref_when_conversation_match_is_unavailable(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: None)
    monkeypatch.setattr(module, "_session_ref", lambda _binding, _explicit="": "tibor-wa-web")

    def _fake_sidecar_get(*, suffix: str, **_kwargs):
        if suffix == "heyy-ai-routes":
            return {
                "routes": [
                    {"route_key": "436647916419", "ai_key": "empathetic_slow_typing_old_lady", "ai_name": "Herta (Heyy Lady)"},
                ]
            }
        if suffix.startswith("conversations?"):
            return {
                "conversations": [
                    {
                        "chat_ref": "stale-self-message-only",
                        "timestamp": "2026-06-23T10:22:10.000Z",
                        "messages": [
                            {"sender_digits": "233385066778814", "direction": "outbound", "from_me": True, "message_timestamp": "2026-06-23T10:22:10.000Z"},
                        ],
                    }
                ]
            }
        if suffix.startswith("recipients/"):
            return {
                "registered": True,
                "resolution_method": "number_id",
                "chat_id_kind": "lid",
                "chat_ref": "chat-ref-1",
            }
        raise AssertionError(suffix)

    monkeypatch.setattr(module, "_sidecar_get", _fake_sidecar_get)

    report = module.resolve_whatsapp("*6419", args=_args(database_url=""))

    assert report["status"] == "resolved"
    assert report["recipient_digits"] == "436647916419"
    assert report["chat_ref"] == "chat-ref-1"
    assert report["resolution_method"] == "number_id"


def test_resolve_whatsapp_does_not_probe_partial_recipient_digits_when_no_real_match(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: None)
    monkeypatch.setattr(module, "_session_ref", lambda _binding, _explicit="": "tibor-wa-web")
    sidecar_calls: list[str] = []

    def _fake_sidecar_get(*, suffix: str, **_kwargs):
        sidecar_calls.append(suffix)
        if suffix == "heyy-ai-routes":
            return {"routes": []}
        if suffix.startswith("conversations?"):
            return {
                "conversations": [
                    {
                        "chat_ref": "chat-ref-1",
                        "updated_at": "2026-06-23T10:05:00Z",
                        "messages": [{"sender_digits": "6419", "direction": "inbound", "from_me": False}],
                    }
                ]
            }
        if suffix.startswith("recipients/"):
            raise AssertionError("partial recipient probe should not run")
        raise AssertionError(suffix)

    monkeypatch.setattr(module, "_sidecar_get", _fake_sidecar_get)

    report = module.resolve_whatsapp("*6419", args=_args(database_url=""))

    assert report["status"] == "unresolved"
    assert report["recipient_digits"] == ""
    assert report["registered"] is False
    assert sidecar_calls == [
        "heyy-ai-routes",
        "conversations?take=50&messages=1&fetch_timeout_ms=5000",
    ]


def test_resolve_whatsapp_ignores_outbound_sender_digit_pollution_and_uses_conversation_timestamp(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: None)
    monkeypatch.setattr(module, "_session_ref", lambda _binding, _explicit="": "tibor-wa-web")

    def _fake_sidecar_get(*, suffix: str, **_kwargs):
        if suffix == "heyy-ai-routes":
            return {
                "routes": [
                    {"route_key": "436647916419", "ai_key": "empathetic_slow_typing_old_lady", "ai_name": "Herta (Heyy Lady)"},
                ]
            }
        if suffix.startswith("conversations?"):
            return {
                "conversations": [
                    {
                        "chat_ref": "older-real-match",
                        "timestamp": "2026-06-23T09:43:25.000Z",
                        "messages": [
                            {"sender_digits": "4369919226996", "direction": "inbound", "from_me": False, "message_timestamp": "2026-05-26T06:50:17.000Z"},
                            {"sender_digits": "436647916419", "direction": "outbound", "from_me": True, "message_timestamp": "2026-05-26T07:53:36.000Z"},
                        ],
                    },
                    {
                        "chat_ref": "stale-self-message-only",
                        "timestamp": "2026-06-08T14:18:13.000Z",
                        "messages": [
                            {"sender_digits": "436647916419", "direction": "outbound", "from_me": True, "message_timestamp": "2026-06-08T14:18:13.000Z"},
                        ],
                    },
                ]
            }
        if suffix.startswith("recipients/"):
            return {
                "registered": True,
                "resolution_method": "number_id",
                "chat_id_kind": "lid",
            }
        raise AssertionError(suffix)

    monkeypatch.setattr(module, "_sidecar_get", _fake_sidecar_get)

    report = module.resolve_whatsapp("*6419", args=_args(database_url=""))

    assert report["status"] == "resolved"
    assert report["chat_ref"] == ""
    assert report["route_key"] == "436647916419"
    assert report["recipient_digits"] == "436647916419"
    assert report["registered"] is True


def test_recent_conversation_match_uses_timestamp_when_updated_at_is_missing() -> None:
    module = _module()

    report = module._recent_conversation_match(
        {
            "conversations": [
                {
                    "chat_ref": "older",
                    "timestamp": "2026-06-23T09:14:23.000Z",
                    "messages": [
                        {"sender_digits": "436647916419", "direction": "inbound", "from_me": False, "message_timestamp": "2026-06-23T09:14:23.000Z"},
                    ],
                },
                {
                    "chat_ref": "newer",
                    "timestamp": "2026-06-23T09:43:25.000Z",
                    "messages": [
                        {"sender_digits": "436647916419", "direction": "inbound", "from_me": False, "message_timestamp": "2026-06-23T09:43:25.000Z"},
                    ],
                },
            ]
        },
        "*6419",
    )

    assert report == {"chat_ref": "newer", "sender_digits": "436647916419"}


def test_resolve_whatsapp_ambiguous_routes_do_not_probe_partial_phone_hint(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: None)
    monkeypatch.setattr(module, "_session_ref", lambda _binding, _explicit="": "tibor-wa-web")
    sidecar_calls: list[str] = []

    def _fake_sidecar_get(*, suffix: str, **_kwargs):
        sidecar_calls.append(suffix)
        if suffix == "heyy-ai-routes":
            return {
                "routes": [
                    {"route_key": "436647016419", "ai_key": "chummer_run_casey", "ai_name": "Casey from Chummer.run"},
                    {"route_key": "436647916419", "ai_key": "empathetic_slow_typing_old_lady", "ai_name": "Herta (Heyy Lady)"},
                ]
            }
        if suffix.startswith("conversations?"):
            return {"conversations": []}
        if suffix.startswith("recipients/"):
            raise AssertionError("recipient probe should not run for an ambiguous partial hint")
        raise AssertionError(suffix)

    monkeypatch.setattr(module, "_sidecar_get", _fake_sidecar_get)

    report = module.resolve_whatsapp("*6419", args=_args(database_url=""))

    assert report["status"] == "ambiguous"
    assert report["recipient_digits"] == ""
    assert report["registered"] is False
    assert sidecar_calls == [
        "heyy-ai-routes",
        "conversations?take=50&messages=1&fetch_timeout_ms=5000",
    ]


def test_send_whatsapp_without_binding_posts_to_sidecar(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: None)
    monkeypatch.setattr(
        module,
        "resolve_whatsapp",
        lambda _phone_hint, args: {
            "status": "resolved",
            "recipient_digits": "436647916419",
            "route_key": "436647916419",
            "session_ref": "tibor-wa-web",
            "chat_ref": "chat-ref-1",
        },
    )
    captured: dict[str, object] = {}

    def _fake_sidecar_post(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "message_ids": ["wamid.1"]}

    monkeypatch.setattr(module, "_sidecar_post", _fake_sidecar_post)

    report = module.send_whatsapp(phone_hint="*6419", text="status update", args=_args(database_url=""))

    assert report["sent"] is True
    assert report["delivery_transport"] == "whatsapp_web_session_sidecar"
    assert report["message_ids"] == ["wamid.1"]
    assert captured["suffix"] == "messages"
    assert captured["body"] == {
        "chat_ref": "chat-ref-1",
        "text": "status update",
        "pre_reply_delay_min_seconds": 0,
        "pre_reply_delay_max_seconds": 0,
        "typing_delay_ms": 0,
        "typing_delay_ms_per_character": 0,
        "typing_status_enabled": False,
    }


def test_send_whatsapp_with_binding_uses_sidecar_chat_ref_first(monkeypatch) -> None:
    module = _module()
    binding = SimpleNamespace(binding_id="binding-1", principal_id="principal-1")
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: binding)
    monkeypatch.setattr(
        module,
        "resolve_whatsapp",
        lambda _phone_hint, args: {
            "status": "resolved",
            "recipient_digits": "436647916419",
            "route_key": "436647916419",
            "chat_ref": "chat-ref-1",
            "session_ref": "tibor-wa-web",
        },
    )
    captured: list[dict[str, object]] = []

    def _fake_sidecar_post(**kwargs):
        captured.append(kwargs)
        return {"ok": True, "message_ids": ["wamid.1"]}

    monkeypatch.setattr(module, "_sidecar_post", _fake_sidecar_post)

    report = module.send_whatsapp(phone_hint="*6419", text="status update", args=_args())

    assert report["sent"] is True
    assert report["binding_id"] == "binding-1"
    assert report["principal_id"] == "principal-1"
    assert report["chat_ref_used"] is True
    assert len(captured) == 1
    assert captured[0]["body"] == {
        "chat_ref": "chat-ref-1",
        "text": "status update",
        "pre_reply_delay_min_seconds": 0,
        "pre_reply_delay_max_seconds": 0,
        "typing_delay_ms": 0,
        "typing_delay_ms_per_character": 0,
        "typing_status_enabled": False,
    }


def test_send_whatsapp_retries_with_recipient_when_chat_ref_is_stale(monkeypatch) -> None:
    module = _module()
    binding = SimpleNamespace(binding_id="binding-1", principal_id="principal-1")
    monkeypatch.setattr(module, "_load_whatsapp_binding", lambda _args: binding)
    monkeypatch.setattr(
        module,
        "resolve_whatsapp",
        lambda _phone_hint, args: {
            "status": "resolved",
            "recipient_digits": "436647916419",
            "route_key": "436647916419",
            "chat_ref": "chat-ref-1",
            "session_ref": "tibor-wa-web",
        },
    )
    captured: list[dict[str, object]] = []

    def _fake_sidecar_post(**kwargs):
        captured.append(kwargs)
        if len(captured) == 1:
            return {"ok": False, "reason": "chat_ref_not_found"}
        return {"ok": True, "message_ids": ["wamid.2"]}

    monkeypatch.setattr(module, "_sidecar_post", _fake_sidecar_post)

    report = module.send_whatsapp(phone_hint="*6419", text="status update", args=_args())

    assert report["sent"] is True
    assert len(captured) == 2
    assert captured[0]["body"]["chat_ref"] == "chat-ref-1"
    assert captured[1]["body"]["to"] == "436647916419"
    assert "chat_ref" not in captured[1]["body"]
    assert report["message_ids"] == ["wamid.2"]


def test_main_probe_provider_operator_prints_plain_text(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(module, "parse_args", lambda: Namespace(command="probe-provider", provider="unmixr", format="operator"))
    monkeypatch.setattr(module, "probe_provider", lambda provider, output_format="json": {"operator_text": f"{provider}:{output_format}"})

    exit_code = module.main()

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "unmixr:operator"
