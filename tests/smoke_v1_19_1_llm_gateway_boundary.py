from __future__ import annotations

import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_llm_gateway_contract_symbols() -> None:
    src = (ROOT / "ea/app/contracts/llm_gateway.py").read_text(encoding="utf-8")
    assert "def _sanitize_prompt(" in src
    assert "class TaskPolicy" in src
    assert "def _audit_egress(" in src
    assert "EA_LLM_GATEWAY_AUDIT_PATH" in src
    assert "def ask_text(" in src
    assert "validate_model_output" in src
    assert "EA_LLM_GATEWAY_MAX_PROMPT_CHARS" in src
    assert "EA_LLM_GATEWAY_DB_AUDIT_ENABLED" in src
    assert "log_to_db(" in src
    _pass("v1.19.1 llm gateway boundary symbols")


def test_llm_gateway_redacts_and_clamps_prompt() -> None:
    import app.contracts.llm_gateway as gw

    old_max = os.environ.get("EA_LLM_GATEWAY_MAX_PROMPT_CHARS")
    old_system_max = os.environ.get("EA_LLM_GATEWAY_MAX_SYSTEM_PROMPT_CHARS")
    old_task = os.environ.get("EA_LLM_GATEWAY_TASK_TYPE")
    original_ask_llm = gw.ask_llm
    captured: dict[str, str] = {}
    try:
        os.environ["EA_LLM_GATEWAY_MAX_PROMPT_CHARS"] = "64"
        os.environ["EA_LLM_GATEWAY_MAX_SYSTEM_PROMPT_CHARS"] = "64"
        os.environ["EA_LLM_GATEWAY_TASK_TYPE"] = "briefing"

        def _fake_ask_llm(prompt: str, system_prompt: str):
            captured["prompt"] = prompt
            captured["system_prompt"] = system_prompt
            return "ok"

        gw.ask_llm = _fake_ask_llm
        out = gw.ask_text(
            "Token: sk-verysecrettoken1234567890 " + ("abc " * 400),
            system_prompt="SYSTEM " + ("x" * 200),
        )
        assert out == "ok"
        assert "sk-verysecrettoken" not in captured.get("prompt", "")
        assert "[redacted_secret]" in captured.get("prompt", "")
        assert "[truncated]" in captured.get("prompt", "")
        assert len(captured.get("prompt", "")) <= 530
        assert len(captured.get("system_prompt", "")) <= 140
    finally:
        gw.ask_llm = original_ask_llm
        if old_max is None:
            os.environ.pop("EA_LLM_GATEWAY_MAX_PROMPT_CHARS", None)
        else:
            os.environ["EA_LLM_GATEWAY_MAX_PROMPT_CHARS"] = old_max
        if old_system_max is None:
            os.environ.pop("EA_LLM_GATEWAY_MAX_SYSTEM_PROMPT_CHARS", None)
        else:
            os.environ["EA_LLM_GATEWAY_MAX_SYSTEM_PROMPT_CHARS"] = old_system_max
        if old_task is None:
            os.environ.pop("EA_LLM_GATEWAY_TASK_TYPE", None)
        else:
            os.environ["EA_LLM_GATEWAY_TASK_TYPE"] = old_task
    _pass("v1.19.1 llm gateway prompt safety")


def test_llm_gateway_blocks_tool_like_outputs() -> None:
    import app.contracts.llm_gateway as gw

    old_task = os.environ.get("EA_LLM_GATEWAY_TASK_TYPE")
    original_ask_llm = gw.ask_llm
    try:
        os.environ["EA_LLM_GATEWAY_TASK_TYPE"] = "briefing_compose"
        gw.ask_llm = lambda prompt, system_prompt: "Please run sql now and execute this tool."
        out = gw.ask_text("summarize today")
        assert "hidden tool/runtime instructions" in out.lower()
    finally:
        gw.ask_llm = original_ask_llm
        if old_task is None:
            os.environ.pop("EA_LLM_GATEWAY_TASK_TYPE", None)
        else:
            os.environ["EA_LLM_GATEWAY_TASK_TYPE"] = old_task
    _pass("v1.19.1 llm gateway output blocking")


def test_llm_gateway_blocks_json_for_user_surface_tasks() -> None:
    import app.contracts.llm_gateway as gw

    old_task = os.environ.get("EA_LLM_GATEWAY_TASK_TYPE")
    original_ask_llm = gw.ask_llm
    try:
        os.environ["EA_LLM_GATEWAY_TASK_TYPE"] = "briefing_compose"
        gw.ask_llm = lambda prompt, system_prompt: '{"debug":"raw response"}'
        out = gw.ask_text("brief me")
        assert "hidden tool/runtime instructions" in out.lower()
    finally:
        gw.ask_llm = original_ask_llm
        if old_task is None:
            os.environ.pop("EA_LLM_GATEWAY_TASK_TYPE", None)
        else:
            os.environ["EA_LLM_GATEWAY_TASK_TYPE"] = old_task
    _pass("v1.19.1 llm gateway json blocking")


def test_llm_gateway_blocks_raw_document_payload_by_default() -> None:
    import app.contracts.llm_gateway as gw

    old_task = os.environ.get("EA_LLM_GATEWAY_TASK_TYPE")
    original_ask_llm = gw.ask_llm
    try:
        os.environ["EA_LLM_GATEWAY_TASK_TYPE"] = "briefing_compose"
        called = {"n": 0}

        def _fake_ask_llm(prompt: str, system_prompt: str):
            called["n"] += 1
            return "ok"

        gw.ask_llm = _fake_ask_llm
        out = gw.ask_text("%PDF-1.7 raw payload with binary-like body")
        assert "raw document payloads" in out.lower()
        assert called["n"] == 0
    finally:
        gw.ask_llm = original_ask_llm
        if old_task is None:
            os.environ.pop("EA_LLM_GATEWAY_TASK_TYPE", None)
        else:
            os.environ["EA_LLM_GATEWAY_TASK_TYPE"] = old_task
    _pass("v1.19.1 llm gateway raw-doc block")


def test_llm_gateway_writes_egress_audit_metadata() -> None:
    import app.contracts.llm_gateway as gw

    original_ask_llm = gw.ask_llm
    old_audit_path = os.environ.get("EA_LLM_GATEWAY_AUDIT_PATH")
    old_task = os.environ.get("EA_LLM_GATEWAY_TASK_TYPE")
    with tempfile.TemporaryDirectory() as td:
        audit_path = pathlib.Path(td) / "egress.jsonl"
        try:
            os.environ["EA_LLM_GATEWAY_AUDIT_PATH"] = str(audit_path)
            os.environ["EA_LLM_GATEWAY_TASK_TYPE"] = "future_reasoning"
            gw.ask_llm = lambda prompt, system_prompt: "Safe grounded summary"
            out = gw.ask_text(
                "Summarize tomorrow prep",
                purpose="briefing_compose",
                correlation_id="cid-123",
                data_class="derived_summary",
            )
            assert "Safe grounded summary" == out
            lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
            assert lines, "expected at least one egress audit row"
            assert '"purpose": "briefing_compose"' in lines[-1]
            assert '"task_type": "future_reasoning"' in lines[-1]
            assert '"correlation_id": "cid-123"' in lines[-1]
            assert '"data_class": "derived_summary"' in lines[-1]
        finally:
            gw.ask_llm = original_ask_llm
            if old_audit_path is None:
                os.environ.pop("EA_LLM_GATEWAY_AUDIT_PATH", None)
            else:
                os.environ["EA_LLM_GATEWAY_AUDIT_PATH"] = old_audit_path
            if old_task is None:
                os.environ.pop("EA_LLM_GATEWAY_TASK_TYPE", None)
            else:
                os.environ["EA_LLM_GATEWAY_TASK_TYPE"] = old_task
    _pass("v1.19.1 llm gateway egress audit")


def test_llm_gateway_writes_db_audit_metadata_when_enabled() -> None:
    import app.contracts.llm_gateway as gw
    import types

    original_ask_llm = gw.ask_llm
    old_db_toggle = os.environ.get("EA_LLM_GATEWAY_DB_AUDIT_ENABLED")
    old_task = os.environ.get("EA_LLM_GATEWAY_TASK_TYPE")
    original_db_module = sys.modules.get("app.db")
    captured: list[dict] = []
    try:
        os.environ["EA_LLM_GATEWAY_DB_AUDIT_ENABLED"] = "1"
        os.environ["EA_LLM_GATEWAY_TASK_TYPE"] = "future_reasoning"
        gw.ask_llm = lambda prompt, system_prompt: "Safe response"

        def _capture_log_to_db(tenant=None, component=None, event_type=None, message=None, payload=None):
            captured.append(
                {
                    "tenant": tenant,
                    "component": component,
                    "event_type": event_type,
                    "message": message,
                    "payload": payload or {},
                }
            )

        sys.modules["app.db"] = types.SimpleNamespace(log_to_db=_capture_log_to_db)
        out = gw.ask_text(
            "Summarize tomorrow",
            purpose="briefing_compose",
            correlation_id="cid-db-audit",
            data_class="derived_summary",
        )
        assert out == "Safe response"
        assert captured, "expected DB audit row"
        row = captured[-1]
        assert row["component"] == "llm_gateway"
        assert row["event_type"] == "egress_audit"
        assert "future_reasoning:ok" in str(row["message"] or "")
        assert row["payload"].get("correlation_id") == "cid-db-audit"
    finally:
        gw.ask_llm = original_ask_llm
        if original_db_module is None:
            sys.modules.pop("app.db", None)
        else:
            sys.modules["app.db"] = original_db_module
        if old_db_toggle is None:
            os.environ.pop("EA_LLM_GATEWAY_DB_AUDIT_ENABLED", None)
        else:
            os.environ["EA_LLM_GATEWAY_DB_AUDIT_ENABLED"] = old_db_toggle
        if old_task is None:
            os.environ.pop("EA_LLM_GATEWAY_TASK_TYPE", None)
        else:
            os.environ["EA_LLM_GATEWAY_TASK_TYPE"] = old_task
    _pass("v1.19.1 llm gateway db audit")


def test_llm_gateway_callsite_task_type_wiring() -> None:
    brief_src = (ROOT / "ea/app/briefings.py").read_text(encoding="utf-8")
    poll_src = (ROOT / "ea/app/poll_listener.py").read_text(encoding="utf-8")
    coaching_src = (ROOT / "ea/app/coaching.py").read_text(encoding="utf-8")

    assert 'task_type="briefing_compose"' in brief_src
    assert 'purpose="briefing_compose"' in brief_src
    assert 'task_type="profile_summary"' in poll_src
    assert 'purpose="chat_assist"' in poll_src
    assert 'task_type="operator_only"' in coaching_src
    assert "allow_json=True" in coaching_src
    _pass("v1.19.1 llm gateway callsite policy wiring")


if __name__ == "__main__":
    test_llm_gateway_contract_symbols()
    test_llm_gateway_redacts_and_clamps_prompt()
    test_llm_gateway_blocks_tool_like_outputs()
    test_llm_gateway_blocks_json_for_user_surface_tasks()
    test_llm_gateway_blocks_raw_document_payload_by_default()
    test_llm_gateway_writes_egress_audit_metadata()
    test_llm_gateway_writes_db_audit_metadata_when_enabled()
    test_llm_gateway_callsite_task_type_wiring()
