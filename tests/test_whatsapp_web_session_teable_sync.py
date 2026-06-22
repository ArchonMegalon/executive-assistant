from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "sync_whatsapp_web_session_to_teable.py"


def _module():
    spec = importlib.util.spec_from_file_location("sync_whatsapp_web_session_to_teable", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_teable_route_fields_include_old_lady_persona_and_supported_schema() -> None:
    module = _module()

    route_field_names = {field["name"] for field in module.ROUTE_FIELDS}
    message_field_names = {field["name"] for field in module.MESSAGE_FIELDS}
    persona_field_names = {field["name"] for field in module.PERSONA_FIELDS}

    assert "behavior_prompt" in route_field_names
    assert "memory_notes" in route_field_names
    assert "pacing_hint" in route_field_names
    assert "pre_reply_delay_min_seconds" in route_field_names
    assert "pre_reply_delay_max_seconds" in route_field_names
    assert "quiet_hours_start_hour" in route_field_names
    assert "quiet_hours_end_hour" in route_field_names
    assert "typing_delay_ms" in route_field_names
    assert "typing_delay_ms_per_character" in route_field_names
    assert "typing_status_enabled" in route_field_names
    assert "heyy_ai_name" in route_field_names
    assert "recipient_registered" in route_field_names
    assert "recipient_resolution_method" in route_field_names
    assert "recipient_chat_id_kind" in route_field_names
    assert "recipient_lid_chat_id_present" in route_field_names
    assert "recipient_phone_chat_id_present" in route_field_names
    assert "recipient_reachability_checked_at" in route_field_names
    assert "recipient_reachability_reason" in route_field_names
    assert "heyy_ai_name" in message_field_names
    assert "selected_button_kind" in message_field_names
    assert "selected_button_id_present" in message_field_names
    assert "selected_button_hash" in message_field_names
    assert "sample_questions" in persona_field_names
    assert "sample_answer_patterns" in persona_field_names
    assert "pre_reply_delay_min_seconds" in persona_field_names
    assert "pre_reply_delay_max_seconds" in persona_field_names
    assert "quiet_hours_start_hour" in persona_field_names
    assert "quiet_hours_end_hour" in persona_field_names
    assert "typing_delay_ms" in persona_field_names
    assert "typing_delay_ms_per_character" in persona_field_names
    assert "typing_status_enabled" in persona_field_names
    assert all("notNull" not in field and "unique" not in field for field in module.ROUTE_FIELDS)
    assert all("notNull" not in field and "unique" not in field for field in module.MESSAGE_FIELDS)
    assert all("notNull" not in field and "unique" not in field for field in module.PERSONA_FIELDS)


def test_teable_transient_http_statuses_include_request_timeout() -> None:
    module = _module()

    assert 408 in module.TRANSIENT_HTTP_STATUS_CODES
    assert 502 in module.TRANSIENT_HTTP_STATUS_CODES


def test_default_route_row_applies_slow_typing_old_lady_behavior() -> None:
    module = _module()

    row = module._default_route_row("principal-wa-web")

    assert row["heyy_ai_key"] == "empathetic_slow_typing_old_lady"
    assert row["heyy_ai_name"] == "Herta (Heyy Lady)"
    assert row["typing_status_enabled"] is True
    assert row["typing_delay_ms"] == 6500
    assert row["minimum_delay_seconds"] == 60
    assert row["pre_reply_delay_min_seconds"] == 60
    assert row["pre_reply_delay_max_seconds"] == 900
    assert row["quiet_hours_start_hour"] == 21
    assert row["quiet_hours_end_hour"] == 6
    assert row["typing_delay_ms_per_character"] == 4000
    assert "1-15 minutes" in str(row["pacing_hint"])
    assert "21:00 and 06:00" in str(row["pacing_hint"])
    assert "slow" in str(row["behavior_prompt"]).lower()
    assert "daß" in str(row["behavior_prompt"])
    assert "bißchen" in str(row["behavior_prompt"])
    assert "Sabine" in str(row["memory_notes"])
    assert "Marillenknödel" in str(row["memory_notes"])
    assert str(row["reply_text"]).startswith("Na geh")
    assert "zurück" in str(row["reply_text"])


def test_route_rows_from_teable_forward_persona_and_typing_fields(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "fields": {
                    "route_key": "default",
                    "inbound_number_digits": "*",
                    "heyy_ai_key": "empathetic_slow_typing_old_lady",
                    "heyy_ai_name": "Herta (Heyy Lady)",
                    "behavior_prompt": "be confused and type slowly",
                    "memory_notes": "remember the yellow raincoat",
                    "pacing_hint": "show typing first",
                    "minimum_delay_seconds": 240,
                    "pre_reply_delay_min_seconds": 60,
                    "pre_reply_delay_max_seconds": 900,
                    "quiet_hours_start_hour": 21,
                    "quiet_hours_end_hour": 6,
                    "typing_delay_ms": 7000,
                    "typing_delay_ms_per_character": 4000,
                    "typing_status_enabled": True,
                    "reply_text": "Na geh...",
                    "enabled": True,
                    "session_ref": "principal-wa-web",
                }
            }
        ],
    )

    rows = module._route_rows_from_teable(
        base_url="http://teable.test",
        api_key="token",
        route_table_id="tbl",
        session_ref="principal-wa-web",
    )

    assert rows == [
        {
            "route_key": "default",
            "inbound_number_digits": "*",
            "ai_key": "empathetic_slow_typing_old_lady",
            "ai_name": "Herta (Heyy Lady)",
            "behavior_prompt": "be confused and type slowly",
            "memory_notes": "remember the yellow raincoat",
            "pacing_hint": "show typing first",
            "minimum_delay_seconds": 240,
            "pre_reply_delay_min_seconds": 60,
            "pre_reply_delay_max_seconds": 900,
            "quiet_hours_start_hour": 21,
            "quiet_hours_end_hour": 6,
            "typing_delay_ms": 7000,
            "typing_delay_ms_per_character": 4000,
            "typing_status_enabled": True,
            "reply_text": "Na geh...",
        }
    ]


def test_route_rows_from_teable_repairs_stale_zero_delay_for_herta(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "fields": {
                    "route_key": "default",
                    "inbound_number_digits": "*",
                    "heyy_ai_key": "empathetic_slow_typing_old_lady",
                    "heyy_ai_name": "Herta (Heyy Lady)",
                    "minimum_delay_seconds": 0,
                    "pre_reply_delay_min_seconds": 0,
                    "pre_reply_delay_max_seconds": 0,
                    "typing_delay_ms": 6500,
                    "typing_delay_ms_per_character": 4000,
                    "typing_status_enabled": True,
                    "enabled": True,
                    "session_ref": "principal-wa-web",
                }
            }
        ],
    )

    rows = module._route_rows_from_teable(
        base_url="http://teable.test",
        api_key="token",
        route_table_id="tbl",
        session_ref="principal-wa-web",
    )

    assert rows[0]["minimum_delay_seconds"] == 60
    assert rows[0]["pre_reply_delay_min_seconds"] == 60
    assert rows[0]["pre_reply_delay_max_seconds"] == 900
    assert rows[0]["quiet_hours_start_hour"] == 21
    assert rows[0]["quiet_hours_end_hour"] == 6
    assert rows[0]["typing_delay_ms_per_character"] == 4000


def test_route_reachability_rows_probe_private_routes_without_raw_chat_ids(monkeypatch) -> None:
    module = _module()
    calls: list[str] = []

    def _fake_session_get(_args, suffix: str) -> dict[str, object]:
        calls.append(suffix)
        return {
            "chat_id_kind": "lid",
            "chat_id_present": True,
            "lid_chat_id_present": True,
            "phone_chat_id_present": False,
            "registered": True,
            "resolution_method": "lid_phone_lid",
        }

    monkeypatch.setattr(module, "_session_get", _fake_session_get)
    monkeypatch.setattr(module, "_now_iso", lambda: "2026-06-21T08:30:00Z")

    rows = module._route_reachability_rows_from_sidecar(
        object(),
        [
            {"inbound_number_digits": "*", "ai_key": "empathetic_slow_typing_old_lady"},
            {"route_key": "inbound_hash1", "inbound_number_digits": "436812345678", "ai_key": "executive_assistant"},
        ],
    )

    assert calls == ["recipients/436812345678"]
    assert rows == [
        {
            "route_key": "inbound_hash1",
            "recipient_registered": True,
            "recipient_resolution_method": "lid_phone_lid",
            "recipient_chat_id_kind": "lid",
            "recipient_lid_chat_id_present": True,
            "recipient_phone_chat_id_present": False,
            "recipient_reachability_checked_at": "2026-06-21T08:30:00Z",
            "recipient_reachability_reason": "registered",
        }
    ]
    assert "@" not in str(rows)


def test_route_reachability_rows_record_unreachable_route_without_throwing(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "_session_get",
        lambda _args, suffix: {
            "chat_id_kind": "",
            "lid_chat_id_present": False,
            "phone_chat_id_present": False,
            "registered": False,
            "resolution_method": "",
        },
    )
    monkeypatch.setattr(module, "_now_iso", lambda: "2026-06-21T08:31:00Z")

    rows = module._route_reachability_rows_from_sidecar(
        type("Args", (), {"session_ref": "principal-wa-web"})(),
        [{"route_key": "inbound_hash1", "inbound_number_digits": "436812345678", "ai_key": "executive_assistant"}],
    )

    assert rows[0]["recipient_registered"] is False
    assert rows[0]["recipient_reachability_reason"] == "recipient_not_registered"
    assert rows[0]["recipient_resolution_method"] == ""


def test_route_rows_from_teable_skip_reachability_only_raw_digit_route_keys(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "fields": {
                    "route_key": "436812345678",
                    "recipient_registered": False,
                    "session_ref": "principal-wa-web",
                }
            },
            {
                "fields": {
                    "route_key": "disabled_reachability_abc123",
                    "recipient_registered": False,
                    "session_ref": "principal-wa-web",
                }
            },
            {
                "fields": {
                    "route_key": "inbound_hash1",
                    "inbound_number_digits": "436812345678",
                    "heyy_ai_key": "executive_assistant",
                    "heyy_ai_name": "Executive Assistant",
                    "enabled": True,
                    "session_ref": "principal-wa-web",
                }
            },
        ],
    )

    rows = module._route_rows_from_teable(
        base_url="http://teable.test",
        api_key="token",
        route_table_id="tbl",
        session_ref="principal-wa-web",
    )

    assert len(rows) == 1
    assert rows[0]["route_key"] == "inbound_hash1"
    assert rows[0]["ai_key"] == "executive_assistant"


def test_cleanup_reachability_only_route_rows_disables_raw_digit_metadata_rows(monkeypatch) -> None:
    module = _module()
    disabled: list[str] = []

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "id": "rec-bad",
                "fields": {
                    "route_key": "436812345678",
                    "recipient_registered": False,
                    "recipient_reachability_reason": "recipient_not_registered",
                    "session_ref": "principal-wa-web",
                },
            },
            {
                "id": "rec-good",
                "fields": {
                    "route_key": "inbound_hash1",
                    "inbound_number_digits": "436812345678",
                    "heyy_ai_key": "executive_assistant",
                    "recipient_registered": False,
                    "session_ref": "principal-wa-web",
                },
            },
            {
                "id": "rec-already-disabled",
                "fields": {
                    "route_key": "436812345679",
                    "enabled": False,
                    "recipient_registered": False,
                    "session_ref": "principal-wa-web",
                },
            },
            {
                "id": "rec-other-session",
                "fields": {
                    "route_key": "15550101000",
                    "recipient_registered": False,
                    "session_ref": "other-session",
                },
            },
        ],
    )
    monkeypatch.setattr(module, "_disable_route_record", lambda **kwargs: disabled.append(kwargs["record_id"]))

    result = module._cleanup_reachability_only_route_rows(
        base_url="http://teable.test",
        api_key="token",
        route_table_id="tbl",
        session_ref="principal-wa-web",
    )

    assert disabled == ["rec-bad"]
    assert result == {"disabled": 1, "failed": 0, "total": 1}


def test_cleanup_reachability_only_route_rows_preserves_intentional_raw_digit_route_with_ai(monkeypatch) -> None:
    module = _module()
    disabled: list[str] = []

    monkeypatch.setattr(
        module,
        "_list_records",
        lambda **_: [
            {
                "id": "rec-legacy",
                "fields": {
                    "route_key": "436812345678",
                    "heyy_ai_key": "executive_assistant",
                    "recipient_registered": False,
                    "session_ref": "principal-wa-web",
                },
            }
        ],
    )
    monkeypatch.setattr(module, "_disable_route_record", lambda **kwargs: disabled.append(kwargs["record_id"]))

    result = module._cleanup_reachability_only_route_rows(
        base_url="http://teable.test",
        api_key="token",
        route_table_id="tbl",
        session_ref="principal-wa-web",
    )

    assert disabled == []
    assert result == {"disabled": 0, "failed": 0, "total": 0}


def test_disable_route_record_rewrites_stale_route_key_without_raw_digits(monkeypatch) -> None:
    module = _module()
    captured: dict[str, object] = {}

    def _fake_teable_request(**kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(module, "_teable_request", _fake_teable_request)

    module._disable_route_record(
        base_url="http://teable.test",
        api_key="token",
        table_id="tbl",
        record_id="rec-bad",
    )

    fields = captured["body"]["record"]["fields"]
    assert captured["method"] == "PATCH"
    assert fields["enabled"] is False
    assert str(fields["route_key"]).startswith("disabled_reachability_")
    assert not str(fields["route_key"]).isdigit()


def test_message_rows_hash_selected_button_callback_without_raw_callback(monkeypatch) -> None:
    module = _module()
    requested_paths: list[str] = []

    def _fake_session_get(args, path: str):
        requested_paths.append(path)
        return {
            "conversations": [
                {
                    "chat_ref": "chat-ref-1",
                    "chat_id_kind": "c.us",
                    "messages": [
                        {
                            "id": "wamid.button.1",
                            "direction": "inbound",
                            "sender_digits": "4368120864006",
                            "heyy_ai_key": "executive_assistant",
                            "heyy_ai_name": "Executive Assistant",
                            "body_text": "1",
                            "body_present": True,
                            "type": "chat",
                            "message_timestamp": "2026-06-21T05:00:00Z",
                            "selected_button_kind": "audiobook_voice",
                            "selected_button_id_present": True,
                            "selected_button_id": "ab|u|voice-token-secret|zz|sig",
                            "from_me": False,
                            "ack_label": "unknown",
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(module, "_session_get", _fake_session_get)

    rows = module._message_rows_from_sidecar(
        type(
            "Args",
            (),
            {
                "conversation_take": 10,
                "conversation_skip": 5,
                "conversation_fetch_concurrency": 4,
                "conversation_fetch_timeout_ms": 12000,
                "disable_conversation_page_state": True,
                "message_limit": 10,
                "session_ref": "principal-wa-web",
            },
        )()
    )

    assert requested_paths == ["conversations?take=10&skip=5&messages=10&fetch_timeout_ms=12000&fetch_concurrency=4"]
    assert rows[0]["selected_button_kind"] == "audiobook_voice"
    assert rows[0]["selected_button_id_present"] is True
    assert rows[0]["selected_button_hash"]
    assert "voice-token-secret" not in str(rows[0])


def test_message_rows_from_sidecar_skip_synthetic_notification_messages(monkeypatch) -> None:
    module = _module()

    def _fake_session_get(args, path: str):
        return {
            "conversations": [
                {
                    "chat_ref": "chat-ref-1",
                    "chat_id_kind": "c.us",
                    "messages": [
                        {
                            "id": "wamid.notification.1",
                            "direction": "outbound",
                            "from_me": True,
                            "type": "e2e_notification",
                            "sender_digits": "4368120864006",
                            "body_text": "27371826634995@lid",
                        },
                        {
                            "id": "wamid.chat.1",
                            "direction": "inbound",
                            "sender_digits": "4368120864006",
                            "body_text": "Hallo",
                            "body_present": True,
                            "type": "chat",
                        },
                    ],
                }
            ]
        }

    monkeypatch.setattr(module, "_session_get", _fake_session_get)

    rows = module._message_rows_from_sidecar(
        type(
            "Args",
            (),
            {
                "conversation_take": 10,
                "conversation_skip": 0,
                "conversation_fetch_concurrency": 4,
                "conversation_fetch_timeout_ms": 12000,
                "disable_conversation_page_state": True,
                "message_limit": 10,
                "session_ref": "principal-wa-web",
            },
        )()
    )

    assert len(rows) == 1
    assert rows[0]["message_id"] == "wamid.chat.1"
    assert rows[0]["message_type"] == "chat"


def test_message_batches_from_sidecar_syncs_all_conversation_pages(monkeypatch) -> None:
    module = _module()
    requested_paths: list[str] = []

    def _fake_session_get(_args, path: str):
        requested_paths.append(path)
        if "skip=0" in path:
            return {
                "conversation_count": 2,
                "conversation_page_complete": False,
                "conversation_skip": 0,
                "conversation_total": 3,
                "next_conversation_skip": 2,
                "conversations": [
                    {
                        "chat_ref": "chat-1",
                        "chat_id_kind": "c.us",
                        "messages": [{"id": "wamid.1", "direction": "inbound", "sender_digits": "1111111"}],
                    },
                    {
                        "chat_ref": "chat-2",
                        "chat_id_kind": "lid",
                        "messages": [{"id": "wamid.2", "direction": "inbound", "sender_digits": "2222222"}],
                    },
                ],
            }
        return {
            "conversation_count": 1,
            "conversation_page_complete": True,
            "conversation_skip": 2,
            "conversation_total": 3,
            "next_conversation_skip": 0,
            "conversations": [
                {
                    "chat_ref": "chat-3",
                    "chat_id_kind": "c.us",
                    "messages": [{"id": "wamid.3", "direction": "outbound", "from_me": True}],
                }
            ],
        }

    monkeypatch.setattr(module, "_session_get", _fake_session_get)

    args = type(
        "Args",
        (),
        {
            "conversation_take": 2,
            "conversation_skip": None,
            "conversation_fetch_concurrency": 3,
            "conversation_fetch_timeout_ms": 12000,
            "conversation_max_pages": 5,
            "conversation_page_state_file": "",
            "disable_conversation_page_state": False,
            "message_limit": 100,
            "session_ref": "principal-wa-web",
            "sync_all_conversations": True,
        },
    )()

    rows, payload = module._message_batches_from_sidecar(args)

    assert requested_paths == [
        "conversations?take=2&skip=0&messages=100&fetch_timeout_ms=12000&fetch_concurrency=3",
        "conversations?take=2&skip=2&messages=100&fetch_timeout_ms=12000&fetch_concurrency=3",
    ]
    assert [row["message_id"] for row in rows] == ["wamid.1", "wamid.2", "wamid.3"]
    assert payload["conversation_count"] == 3
    assert payload["conversation_pages"] == 2
    assert payload["conversation_total"] == 3
    assert payload["conversation_page_complete"] is True
    assert payload["next_conversation_skip"] == 0


def test_load_env_file_ignores_unreadable_env_file(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    env_file = tmp_path / ".env"
    env_file.write_text("IGNORED=value\n", encoding="utf-8")
    calls: list[Path] = []

    def _failing_read_text(self: Path, *args: object, **kwargs: object) -> str:
        calls.append(self)
        raise PermissionError("denied")

    monkeypatch.setattr(type(env_file), "read_text", _failing_read_text)

    module._load_env_file(env_file)

    assert calls == [env_file]


def test_conversation_skip_uses_state_file_when_no_explicit_skip(tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "state.json"
    state_file.write_text('{"next_conversation_skip": 15}\n', encoding="utf-8")

    args = type(
        "Args",
        (),
        {
            "conversation_page_state_file": str(state_file),
            "conversation_skip": None,
            "disable_conversation_page_state": False,
        },
    )()

    assert module._conversation_skip_from_args(args) == 15


def test_sync_all_conversation_start_skip_uses_state_file_when_resuming(tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "state.json"
    state_file.write_text('{"next_conversation_skip": 75}\n', encoding="utf-8")

    args = type(
        "Args",
        (),
        {
            "conversation_page_state_file": str(state_file),
            "conversation_skip": None,
            "disable_conversation_page_state": False,
            "sync_all_conversations": True,
        },
    )()

    assert module._conversation_start_skip_from_args(args) == 75


def test_completed_sync_all_refresh_uses_small_first_page_without_advancing_state(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "state.json"
    state_file.write_text(
        '{"conversation_scan_completed": true, "conversation_scan_completed_count": 1, "next_conversation_skip": 0}\n',
        encoding="utf-8",
    )
    requested_paths: list[str] = []

    def _fake_session_get(_args, path: str):
        requested_paths.append(path)
        return {
            "conversation_count": 5,
            "conversation_page_complete": False,
            "conversation_skip": 0,
            "conversation_total": 160,
            "next_conversation_skip": 5,
            "conversations": [
                {
                    "chat_ref": "chat-1",
                    "chat_id_kind": "c.us",
                    "messages": [{"id": "wamid.1", "direction": "inbound"}],
                }
            ],
        }

    monkeypatch.setattr(module, "_session_get", _fake_session_get)
    args = type(
        "Args",
        (),
        {
            "conversation_take": 25,
            "conversation_skip": None,
            "conversation_fetch_concurrency": 3,
            "conversation_fetch_timeout_ms": 12000,
            "conversation_max_pages": 50,
            "conversation_page_state_file": str(state_file),
            "disable_conversation_page_state": False,
            "message_limit": 50,
            "session_ref": "principal-wa-web",
            "sync_all_conversations": True,
        },
    )()

    rows, payload = module._message_batches_from_sidecar(args)
    state = module._update_conversation_page_state(
        args=args,
        payload=payload,
        message_upsert={"created": 0, "updated": len(rows), "total": len(rows)},
    )

    assert requested_paths == ["conversations?take=5&skip=0&messages=50&fetch_timeout_ms=12000&fetch_concurrency=3"]
    assert payload["completed_refresh"] is True
    assert state["completed_refresh"] is True
    assert state["conversation_scan_completed"] is True
    assert state["conversation_scan_completed_count"] == 1
    assert state["next_conversation_skip"] == 5


def test_explicit_skip_bypasses_completed_refresh(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "state.json"
    state_file.write_text('{"conversation_scan_completed": true, "next_conversation_skip": 0}\n', encoding="utf-8")
    requested_paths: list[str] = []

    monkeypatch.setattr(
        module,
        "_session_get",
        lambda _args, path: requested_paths.append(path)
        or {
            "conversation_count": 1,
            "conversation_page_complete": True,
            "conversation_skip": 30,
            "conversation_total": 31,
            "next_conversation_skip": 0,
            "conversations": [],
        },
    )

    args = type(
        "Args",
        (),
        {
            "conversation_take": 25,
            "conversation_skip": 30,
            "conversation_fetch_concurrency": 3,
            "conversation_fetch_timeout_ms": 12000,
            "conversation_max_pages": 50,
            "conversation_page_state_file": str(state_file),
            "disable_conversation_page_state": False,
            "message_limit": 50,
            "session_ref": "principal-wa-web",
            "sync_all_conversations": True,
        },
    )()

    _rows, payload = module._message_batches_from_sidecar(args)

    assert requested_paths == ["conversations?take=25&skip=30&messages=50&fetch_timeout_ms=12000&fetch_concurrency=3"]
    assert payload["completed_refresh"] is False


def test_conversation_page_state_advances_after_message_upsert(tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "state.json"
    args = type(
        "Args",
        (),
        {
            "conversation_page_state_file": str(state_file),
            "disable_conversation_page_state": False,
            "session_ref": "principal-wa-web",
        },
    )()

    state = module._update_conversation_page_state(
        args=args,
        payload={
            "conversation_count": 5,
            "conversation_page_complete": False,
            "conversation_skip": 10,
            "conversation_total": 42,
            "next_conversation_skip": 15,
        },
        message_upsert={"created": 1, "updated": 2, "total": 3},
    )

    loaded = state_file.read_text(encoding="utf-8")
    assert state["next_conversation_skip"] == 15
    assert state["conversation_scan_completed"] is False
    assert state["conversation_scan_completed_count"] == 0
    assert '"conversation_skip": 10' in loaded
    assert '"next_conversation_skip": 15' in loaded
    assert '"total": 3' in loaded


def test_conversation_page_state_records_completed_full_scan(tmp_path: Path) -> None:
    module = _module()
    state_file = tmp_path / "state.json"
    state_file.write_text(
        '{"conversation_scan_completed": true, "conversation_scan_completed_count": 2}\n',
        encoding="utf-8",
    )
    args = type(
        "Args",
        (),
        {
            "conversation_page_state_file": str(state_file),
            "disable_conversation_page_state": False,
            "session_ref": "principal-wa-web",
        },
    )()

    state = module._update_conversation_page_state(
        args=args,
        payload={
            "conversation_count": 4,
            "conversation_page_complete": True,
            "conversation_skip": 155,
            "conversation_total": 159,
            "next_conversation_skip": 0,
        },
        message_upsert={"created": 0, "updated": 7, "total": 7},
    )

    assert state["conversation_page_complete"] is True
    assert state["conversation_scan_completed"] is True
    assert state["conversation_scan_completed_at"]
    assert state["conversation_scan_completed_count"] == 3
    assert state["conversation_scan_completed_total"] == 159
    assert state["next_conversation_skip"] == 0


def test_heyy_ai_persona_rows_include_propertyquarry_and_chummer_run_examples() -> None:
    module = _module()

    rows = {row["persona_key"]: row for row in module._persona_rows("principal-wa-web")}

    propertyquarry = rows["propertyquarry_mira"]
    chummer = rows["chummer_run_casey"]
    executive_assistant = rows["executive_assistant"]

    assert propertyquarry["heyy_ai_name"] == "Mira from PropertyQuarry"
    assert propertyquarry["typing_status_enabled"] is True
    assert propertyquarry["typing_delay_ms"] == 4200
    assert propertyquarry["pre_reply_delay_min_seconds"] == 0
    assert propertyquarry["typing_delay_ms_per_character"] == 0
    assert "How is the score calculated?" in str(propertyquarry["sample_questions"])
    assert "How do you know which school is good?" in str(propertyquarry["sample_questions"])
    assert "weighted fit score" in str(propertyquarry["sample_answer_patterns"])
    assert "school quality is inferred from explicit evidence" in str(propertyquarry["sample_answer_patterns"])
    assert "source-bound" in str(propertyquarry["memory_notes"])

    assert chummer["heyy_ai_name"] == "Casey from Chummer.run"
    assert chummer["typing_status_enabled"] is True
    assert chummer["typing_delay_ms"] == 5200
    assert chummer["pre_reply_delay_min_seconds"] == 0
    assert chummer["typing_delay_ms_per_character"] == 0
    assert "Which ruleset are you using?" in str(chummer["sample_questions"])
    assert "Is Chummer.run production ready?" in str(chummer["sample_questions"])
    assert "Do not assume" in str(chummer["sample_answer_patterns"])
    assert "what is verified" in str(chummer["sample_answer_patterns"])

    assert executive_assistant["heyy_ai_name"] == "Executive Assistant"
    assert executive_assistant["typing_status_enabled"] is True
    assert executive_assistant["typing_delay_ms"] == 2800
    assert executive_assistant["pre_reply_delay_min_seconds"] == 0
    assert executive_assistant["typing_delay_ms_per_character"] == 0
    assert "WhatsApp Web session" in str(executive_assistant["behavior_prompt"])
    assert "raw private phone numbers" in str(executive_assistant["safety_notes"])


def test_explicit_route_row_maps_private_number_to_executive_assistant_without_raw_route_key() -> None:
    module = _module()

    row = module._explicit_route_row(
        session_ref="principal-wa-web",
        inbound_number_digits="+43 681 208 640 06",
        heyy_ai_key="executive_assistant",
        heyy_ai_name="Executive Assistant",
    )

    assert row["inbound_number_digits"] == "4368120864006"
    assert row["route_key"].startswith("inbound_")
    assert "4368120864006" not in str(row["route_key"])
    assert row["heyy_ai_key"] == "executive_assistant"
    assert row["heyy_ai_name"] == "Executive Assistant"
    assert row["typing_status_enabled"] is True
    assert row["typing_delay_ms"] == 2800
    assert row["minimum_delay_seconds"] == 0
    assert row["pre_reply_delay_min_seconds"] == 0
    assert row["pre_reply_delay_max_seconds"] == 0
    assert row["quiet_hours_start_hour"] == 0
    assert row["quiet_hours_end_hour"] == 0
    assert row["typing_delay_ms_per_character"] == 0


def test_route_seed_rows_map_product_numbers_to_named_personas_without_raw_route_keys() -> None:
    module = _module()

    rows = module._route_seed_rows(
        session_ref="principal-wa-web",
        raw_json="""
        [
          {"phone": "+1 555 010 1000", "heyy_ai_key": "propertyquarry_mira", "product_key": "propertyquarry"},
          {"inbound_number": "+1 555 010 2000", "persona_key": "chummer_run_casey", "source": "chummer_run"}
        ]
        """,
    )

    assert len(rows) == 2
    by_ai = {str(row["heyy_ai_key"]): row for row in rows}

    propertyquarry = by_ai["propertyquarry_mira"]
    assert propertyquarry["inbound_number_digits"] == "15550101000"
    assert propertyquarry["route_key"].startswith("inbound_")
    assert "15550101000" not in str(propertyquarry["route_key"])
    assert propertyquarry["heyy_ai_name"] == "Mira from PropertyQuarry"
    assert "fit scores are calculated" in str(propertyquarry["behavior_prompt"])
    assert "Seed source: propertyquarry." in str(propertyquarry["notes"])

    chummer = by_ai["chummer_run_casey"]
    assert chummer["inbound_number_digits"] == "15550102000"
    assert chummer["route_key"].startswith("inbound_")
    assert "15550102000" not in str(chummer["route_key"])
    assert chummer["heyy_ai_name"] == "Casey from Chummer.run"
    assert "ruleset" in str(chummer["behavior_prompt"]).lower()
    assert "Seed source: chummer_run." in str(chummer["notes"])


def test_route_seed_rows_accept_mapping_json_and_dedupe_numbers() -> None:
    module = _module()

    rows = module._route_seed_rows(
        session_ref="principal-wa-web",
        raw_json="""
        {
          "+1 555 010 3000": "propertyquarry_mira",
          "15550103000": {"heyy_ai_key": "chummer_run_casey"}
        }
        """,
    )

    assert len(rows) == 1
    assert rows[0]["inbound_number_digits"] == "15550103000"
    assert rows[0]["heyy_ai_key"] == "propertyquarry_mira"
    assert rows[0]["heyy_ai_name"] == "Mira from PropertyQuarry"


def test_route_import_source_rows_map_teable_support_tables_to_product_personas(monkeypatch) -> None:
    module = _module()
    records_by_table = {
        "tbl-propertyquarry": [
            {
                "fields": {
                    "whatsapp_ai_support_phone": "+1 555 010 4000",
                    "whatsapp_ai_support_enabled": True,
                    "whatsapp_ai_support_purpose": "ai_support_only",
                }
            },
            {
                "fields": {
                    "whatsapp_ai_support_phone": "+1 555 010 4001",
                    "whatsapp_ai_support_enabled": True,
                    "whatsapp_ai_support_purpose": "marketing",
                }
            },
            {
                "fields": {
                    "whatsapp_ai_support_phone": "+1 555 010 4002",
                    "whatsapp_ai_support_purpose": "ai_support_only",
                }
            },
        ],
        "tbl-chummer": [
            {
                "fields": {
                    "WhatsApp AI Support Phone": "+1 555 010 5000",
                    "WhatsApp AI Support Enabled": True,
                    "WhatsApp AI Support Purpose": "ai_support_only",
                }
            },
            {
                "fields": {
                    "WhatsApp AI Support Phone": "+1 555 010 5001",
                    "WhatsApp AI Support Enabled": False,
                    "WhatsApp AI Support Purpose": "ai_support_only",
                }
            },
            {
                "fields": {
                    "WhatsApp AI Support Phone": "+1 555 010 5002",
                    "WhatsApp AI Support Purpose": "ai_support_only",
                }
            },
        ],
    }

    def _fake_discover_table_id(**kwargs):
        assert kwargs["base_id"] == "base-property"
        if kwargs["table_name"] == "propertyquarry_delivery_settings":
            return "tbl-propertyquarry"
        return ""

    monkeypatch.setattr(module, "_discover_table_id", _fake_discover_table_id)
    monkeypatch.setattr(module, "_list_records", lambda **kwargs: records_by_table[kwargs["table_id"]])

    rows = module._route_import_source_rows(
        base_url="http://teable.test",
        api_key="token",
        base_id="base-1",
        session_ref="principal-wa-web",
        raw_json="""
        [
          {
            "base_id": "base-property",
            "table_name": "propertyquarry_delivery_settings",
            "source": "propertyquarry",
            "phone_field": "whatsapp_ai_support_phone",
            "enabled_field": "whatsapp_ai_support_enabled",
            "purpose_field": "whatsapp_ai_support_purpose",
            "required_purpose": "ai_support_only",
            "heyy_ai_key": "propertyquarry_mira"
          },
          {
            "table_id": "tbl-chummer",
            "source": "chummer_run",
            "phone_field": "WhatsApp AI Support Phone",
            "enabled_field": "WhatsApp AI Support Enabled",
            "purpose_field": "WhatsApp AI Support Purpose",
            "required_purpose": "ai_support_only",
            "heyy_ai_key": "chummer_run_casey"
          }
        ]
        """,
    )

    assert len(rows) == 2
    by_ai = {str(row["heyy_ai_key"]): row for row in rows}

    propertyquarry = by_ai["propertyquarry_mira"]
    assert propertyquarry["inbound_number_digits"] == "15550104000"
    assert propertyquarry["route_key"].startswith("inbound_")
    assert "15550104000" not in str(propertyquarry["route_key"])
    assert propertyquarry["heyy_ai_name"] == "Mira from PropertyQuarry"
    assert "Imported Teable route source: propertyquarry." in str(propertyquarry["notes"])

    chummer = by_ai["chummer_run_casey"]
    assert chummer["inbound_number_digits"] == "15550105000"
    assert "15550105002" not in {str(row["inbound_number_digits"]) for row in rows}
    assert chummer["route_key"].startswith("inbound_")
    assert "15550105000" not in str(chummer["route_key"])
    assert chummer["heyy_ai_name"] == "Casey from Chummer.run"
    assert "Imported Teable route source: chummer_run." in str(chummer["notes"])


def test_dedupe_route_rows_keeps_first_private_mapping() -> None:
    module = _module()
    executive = module._explicit_route_row(
        session_ref="principal-wa-web",
        inbound_number_digits="+1 555 010 6000",
        heyy_ai_key="executive_assistant",
        heyy_ai_name="Executive Assistant",
    )
    product = module._explicit_route_row(
        session_ref="principal-wa-web",
        inbound_number_digits="+1 555 010 6000",
        heyy_ai_key="propertyquarry_mira",
        heyy_ai_name="Mira from PropertyQuarry",
    )

    rows = module._dedupe_route_rows([executive, product])

    assert len(rows) == 1
    assert rows[0]["heyy_ai_key"] == "executive_assistant"
    assert rows[0]["heyy_ai_name"] == "Executive Assistant"


def test_sidecar_live_route_rows_preserve_live_sender_route(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_now_iso", lambda: "2026-06-22T08:00:00Z")

    row = module._route_row_for_sidecar_public_route(
        session_ref="principal-wa-web",
        route={
            "route_key": "40424366432273",
            "ai_key": "empathetic_slow_typing_old_lady",
            "ai_name": "Herta (Heyy Lady)",
            "pre_reply_delay_min_seconds": 0,
            "pre_reply_delay_max_seconds": 0,
            "quiet_hours_start_hour": 0,
            "quiet_hours_end_hour": 0,
            "typing_delay_ms": 6500,
            "typing_delay_ms_per_character": 0,
            "typing_status_enabled": True,
        },
    )

    assert row["inbound_number_digits"] == "40424366432273"
    assert row["route_key"].startswith("inbound_")
    assert "40424366432273" not in str(row["route_key"])
    assert row["ai_key"] == "empathetic_slow_typing_old_lady"
    assert row["ai_name"] == "Herta (Heyy Lady)"
    assert row["quiet_hours_start_hour"] == 0
    assert row["quiet_hours_end_hour"] == 0
    assert row["pre_reply_delay_min_seconds"] == 0
    assert row["pre_reply_delay_max_seconds"] == 0
    assert row["typing_delay_ms"] == 6500
    assert row["typing_delay_ms_per_character"] == 0
    assert "Preserved live sidecar route" in str(row["notes"])


def test_sidecar_live_test_route_clamps_per_character_delay(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_now_iso", lambda: "2026-06-22T08:00:00Z")

    row = module._route_row_for_sidecar_public_route(
        session_ref="principal-wa-web",
        route={
            "route_key": "40424366432273",
            "ai_key": "empathetic_slow_typing_old_lady",
            "ai_name": "Herta (Heyy Lady)",
            "pre_reply_delay_min_seconds": 10,
            "pre_reply_delay_max_seconds": 30,
            "quiet_hours_start_hour": 0,
            "quiet_hours_end_hour": 0,
            "typing_delay_ms": 6500,
            "typing_delay_ms_per_character": 4000,
            "typing_status_enabled": True,
        },
    )

    assert row["pre_reply_delay_min_seconds"] == 10
    assert row["pre_reply_delay_max_seconds"] == 30
    assert row["typing_delay_ms"] == 6500
    assert row["typing_delay_ms_per_character"] == 0


def test_apply_routes_to_sidecar_keeps_live_override_over_teable_ea(monkeypatch) -> None:
    module = _module()
    args = type("Args", (), {"session_ref": "principal-wa-web", "preserve_sidecar_live_routes": True})()
    sent: dict[str, object] = {}
    teable_ea_route = module._explicit_route_row(
        session_ref="principal-wa-web",
        inbound_number_digits="40424366432273",
        heyy_ai_key="executive_assistant",
        heyy_ai_name="Executive Assistant",
    )

    def _fake_session_get(_args, suffix: str) -> dict[str, object]:
        assert suffix == "heyy-ai-routes"
        return {
            "routes": [
                {
                    "route_key": "40424366432273",
                    "ai_key": "empathetic_slow_typing_old_lady",
                    "ai_name": "Herta (Heyy Lady)",
                    "pre_reply_delay_min_seconds": 0,
                    "pre_reply_delay_max_seconds": 0,
                    "quiet_hours_start_hour": 0,
                    "quiet_hours_end_hour": 0,
                    "typing_delay_ms": 6500,
                    "typing_delay_ms_per_character": 0,
                    "typing_status_enabled": True,
                }
            ]
        }

    def _fake_session_put(_args, suffix: str, body: dict[str, object]) -> dict[str, object]:
        sent["suffix"] = suffix
        sent["body"] = body
        return {"ok": True, "route_count": len(body.get("routes") or [])}

    monkeypatch.setattr(module, "_session_get", _fake_session_get)
    monkeypatch.setattr(module, "_session_put", _fake_session_put)

    result = module._apply_routes_to_sidecar(args, [teable_ea_route])

    assert result["ok"] is True
    assert sent["suffix"] == "heyy-ai-routes"
    routes = sent["body"]["routes"]  # type: ignore[index]
    assert len(routes) == 1
    assert routes[0]["inbound_number_digits"] == "40424366432273"
    assert routes[0]["ai_key"] == "empathetic_slow_typing_old_lady"
    assert routes[0]["ai_name"] == "Herta (Heyy Lady)"
    assert routes[0]["quiet_hours_start_hour"] == 0
    assert routes[0]["quiet_hours_end_hour"] == 0


def test_ensure_table_discovers_existing_table_from_supplied_base(monkeypatch) -> None:
    module = _module()
    calls: list[str] = []

    def _fake_teable_request(**kwargs):
        calls.append(kwargs["path"])
        assert kwargs["path"] == "/api/base/base-1/table"
        return {"tables": [{"id": "tbl-existing", "name": "ea_heyy_ai_personas"}]}

    monkeypatch.setattr(module, "_teable_request", _fake_teable_request)

    table_id, created = module._ensure_table(
        base_url="http://teable.test",
        api_key="token",
        base_id="base-1",
        table_id="",
        table_name="ea_heyy_ai_personas",
        fields=module.PERSONA_FIELDS,
        create_missing=True,
    )

    assert table_id == "tbl-existing"
    assert created is False
    assert calls == ["/api/base/base-1/table"]


def test_ensure_fields_adds_missing_teable_fields(monkeypatch) -> None:
    module = _module()
    calls: list[dict[str, object]] = []

    def _fake_teable_request(**kwargs):
        calls.append(kwargs)
        if kwargs["method"] == "GET":
            return [{"name": "projection_id", "type": "singleLineText"}]
        return {"id": "fld-created"}

    monkeypatch.setattr(module, "_teable_request", _fake_teable_request)

    created = module._ensure_fields(
        base_url="http://teable.test",
        api_key="token",
        table_id="tbl-messages",
        fields=[
            {"name": "projection_id", "type": "singleLineText"},
            {"name": "selected_button_hash", "type": "singleLineText"},
        ],
    )

    assert created == 1
    assert calls[0]["path"] == "/api/table/tbl-messages/field"
    assert calls[1]["method"] == "POST"
    assert calls[1]["path"] == "/api/table/tbl-messages/field"
    assert calls[1]["body"] == {"name": "selected_button_hash", "type": "singleLineText"}


def test_upsert_rows_skips_teable_record_scan_for_empty_batches(monkeypatch) -> None:
    module = _module()

    monkeypatch.setattr(
        module,
        "_existing_record_ids",
        lambda **_: (_ for _ in ()).throw(AssertionError("should not scan records for empty upsert")),
    )

    assert module._upsert_rows(
        base_url="http://teable.test",
        api_key="token",
        table_id="tbl",
        key_field="projection_id",
        rows=[],
    ) == {"created": 0, "updated": 0, "total": 0}


def test_existing_record_ids_scans_only_key_field_projection(monkeypatch) -> None:
    module = _module()
    calls: list[str] = []

    def _fake_teable_request(**kwargs):
        calls.append(kwargs["path"])
        return {
            "records": [
                {
                    "id": "rec-1",
                    "fields": {"projection_id": "principal-wa-web:wa-message:abc"},
                }
            ]
        }

    monkeypatch.setattr(module, "_teable_request", _fake_teable_request)

    ids = module._existing_record_ids(
        base_url="http://teable.test",
        api_key="token",
        table_id="tbl-messages",
        key_field="projection_id",
    )

    assert ids == {"principal-wa-web:wa-message:abc": "rec-1"}
    assert calls == [
        "/api/table/tbl-messages/record?fieldKeyType=name&cellFormat=json&take=1000&skip=0&projection=projection_id"
    ]


def test_upsert_rows_can_lookup_existing_records_by_current_keys(monkeypatch) -> None:
    module = _module()
    calls: list[dict[str, object]] = []

    def _fake_teable_request(**kwargs):
        calls.append(kwargs)
        if kwargs["method"] == "GET":
            return {
                "records": [
                    {
                        "id": "rec-existing",
                        "fields": {"projection_id": "msg-existing"},
                    }
                ]
            }
        if kwargs["method"] == "PATCH":
            return {"id": "rec-existing"}
        return {"records": [{"id": "rec-created"}]}

    monkeypatch.setattr(module, "_teable_request", _fake_teable_request)

    result = module._upsert_rows(
        base_url="http://teable.test",
        api_key="token",
        table_id="tbl-messages",
        key_field="projection_id",
        rows=[
            {"projection_id": "msg-existing", "body_present": True},
            {"projection_id": "msg-new", "body_present": True},
        ],
        lookup_existing_by_keys=True,
    )

    assert result == {"created": 1, "updated": 1, "total": 2}
    assert "filterByTql=" in calls[0]["path"]
    assert "projection=projection_id" in calls[0]["path"]
    assert calls[1]["method"] == "PATCH"
    assert calls[2]["method"] == "POST"


def test_upsert_rows_skips_noop_updates_when_lookup_existing_by_keys(monkeypatch) -> None:
    module = _module()
    calls: list[dict[str, object]] = []

    def _fake_teable_request(**kwargs):
        calls.append(kwargs)
        if kwargs["method"] == "GET":
            return {
                "records": [
                    {
                        "id": "rec-existing",
                        "fields": {"projection_id": "msg-existing", "body_present": True, "ack_label": "read"},
                    }
                ]
            }
        raise AssertionError("PATCH/POST should not be called for unchanged rows")

    monkeypatch.setattr(module, "_teable_request", _fake_teable_request)

    result = module._upsert_rows(
        base_url="http://teable.test",
        api_key="token",
        table_id="tbl-messages",
        key_field="projection_id",
        rows=[
            {"projection_id": "msg-existing", "body_present": True, "ack_label": "read"},
        ],
        lookup_existing_by_keys=True,
    )

    assert result == {"created": 0, "updated": 0, "total": 1}
    assert len(calls) == 1
    assert calls[0]["method"] == "GET"


def test_upsert_rows_ignores_volatile_timestamps_for_noop_detection(monkeypatch) -> None:
    module = _module()
    calls: list[dict[str, object]] = []

    def _fake_teable_request(**kwargs):
        calls.append(kwargs)
        if kwargs["method"] == "GET":
            return {
                "records": [
                    {
                        "id": "rec-existing",
                        "fields": {
                            "projection_id": "msg-existing",
                            "body_present": True,
                            "ack_label": "read",
                            "synced_at": "2026-06-22T14:00:00Z",
                        },
                    }
                ]
            }
        raise AssertionError("PATCH/POST should not be called for timestamp-only changes")

    monkeypatch.setattr(module, "_teable_request", _fake_teable_request)

    result = module._upsert_rows(
        base_url="http://teable.test",
        api_key="token",
        table_id="tbl-messages",
        key_field="projection_id",
        rows=[
            {
                "projection_id": "msg-existing",
                "body_present": True,
                "ack_label": "read",
                "synced_at": "2026-06-22T16:00:00Z",
            },
        ],
        lookup_existing_by_keys=True,
    )

    assert result == {"created": 0, "updated": 0, "total": 1}
    assert len(calls) == 1
