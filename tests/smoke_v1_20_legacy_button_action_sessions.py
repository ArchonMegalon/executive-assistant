from __future__ import annotations

import asyncio
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _install_psycopg2_stub() -> None:
    if "psycopg2" in sys.modules:
        return
    fake_psycopg2 = types.ModuleType("psycopg2")
    fake_pool_mod = types.ModuleType("psycopg2.pool")
    fake_extras_mod = types.ModuleType("psycopg2.extras")

    class _ThreadedConnectionPool:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def getconn(self):
            raise RuntimeError("psycopg2 stub: no db connection available")

        def putconn(self, conn) -> None:
            return None

    fake_pool_mod.ThreadedConnectionPool = _ThreadedConnectionPool
    fake_psycopg2.pool = fake_pool_mod
    fake_extras_mod.RealDictCursor = object
    sys.modules["psycopg2"] = fake_psycopg2
    sys.modules["psycopg2.pool"] = fake_pool_mod
    sys.modules["psycopg2.extras"] = fake_extras_mod


def _install_httpx_stub() -> None:
    if "httpx" in sys.modules:
        return
    fake_httpx = types.ModuleType("httpx")

    class _AsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    fake_httpx.AsyncClient = _AsyncClient
    sys.modules["httpx"] = fake_httpx


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_legacy_button_context_action_is_sessionized() -> None:
    _install_psycopg2_stub()
    _install_httpx_stub()

    import app.callback_commands as cc

    captured: dict[str, object] = {
        "sessions": [],
        "steps": [],
        "finalized": [],
        "messages": [],
        "edits": [],
    }

    class _FakeTG:
        async def answer_callback_query(self, *args, **kwargs):
            return {"ok": True}

        async def edit_message_reply_markup(self, *args, **kwargs):
            return {"ok": True}

        async def send_message(self, chat_id: int, text: str, parse_mode: str | None = None, reply_markup=None):
            payload = {
                "chat_id": int(chat_id),
                "text": str(text),
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            }
            captured["messages"].append(payload)
            return {"ok": True, "message_id": 901}

        async def edit_message_text(self, chat_id: int, message_id: int, text: str, parse_mode: str | None = None, **kwargs):
            payload = {
                "chat_id": int(chat_id),
                "message_id": int(message_id),
                "text": str(text),
                "parse_mode": parse_mode,
                "kwargs": dict(kwargs),
            }
            captured["edits"].append(payload)
            return {"ok": True}

    orig_get_ctx = cc.get_button_context
    orig_gog = cc.gog_scout
    orig_build_ui = cc.build_dynamic_ui
    orig_humanize = cc.humanize_agent_report
    orig_clean = cc.clean_html_for_telegram

    orig_create = cc.create_execution_session
    orig_running = cc.mark_execution_session_running
    orig_step = cc.mark_execution_step_status
    orig_finalize = cc.finalize_execution_session
    orig_event = cc.append_execution_event

    try:
        cc.get_button_context = lambda action_id: "Open the latest project status and summarize action items."

        async def _fake_gog(*args, **kwargs):
            return "[report] Action completed successfully."

        cc.gog_scout = _fake_gog
        cc.build_dynamic_ui = lambda report, prompt, save_ctx=None: {"inline_keyboard": []}
        cc.humanize_agent_report = lambda report: str(report)
        cc.clean_html_for_telegram = lambda text: str(text)

        cc.create_execution_session = lambda **kwargs: captured["sessions"].append(dict(kwargs)) or "sess-btn-1"
        cc.mark_execution_session_running = lambda session_id: None
        cc.mark_execution_step_status = (
            lambda session_id, step_key, status, **kwargs: captured["steps"].append((step_key, status, dict(kwargs)))
        )
        cc.finalize_execution_session = (
            lambda session_id, status, outcome=None, last_error=None: captured["finalized"].append(
                {
                    "session_id": session_id,
                    "status": status,
                    "outcome": dict(outcome or {}),
                    "last_error": last_error,
                }
            )
        )
        cc.append_execution_event = lambda *args, **kwargs: None

        cb = {
            "id": "cb-1",
            "data": "act:legacy-77",
            "message": {
                "message_id": 501,
                "chat": {"id": 4242},
                "reply_markup": {
                    "inline_keyboard": [
                        [{"text": "⚙️ Run Planner", "callback_data": "act:legacy-77"}],
                    ]
                },
            },
        }

        async def _check_security(chat_id: int):
            return (
                "tenant_demo",
                {
                    "openclaw_container": "openclaw-demo",
                    "google_account": "principal@example.com",
                },
            )

        async def _trigger_auth_flow(*args, **kwargs):
            return None

        asyncio.run(
            cc.handle_callback_command(
                tg=_FakeTG(),
                cb=cb,
                check_security=_check_security,
                auth_sessions=types.SimpleNamespace(clear=lambda *_a, **_k: None),
                trigger_auth_flow=_trigger_auth_flow,
            )
        )

        assert captured["sessions"], "legacy button action should create execution session"
        sess = captured["sessions"][0]
        assert sess.get("source") == "button_context_action"
        assert captured["finalized"], "legacy button action should finalize execution session"
        fin = captured["finalized"][0]
        assert fin["status"] == "completed"
        assert fin["outcome"].get("action_type") == "legacy_button_context"
        step_pairs = {(step, status) for (step, status, _kwargs) in captured["steps"]}
        assert ("compile_intent", "completed") in step_pairs
        assert ("execute_intent", "running") in step_pairs
        assert ("execute_intent", "completed") in step_pairs
        assert ("render_reply", "completed") in step_pairs
        assert captured["messages"], "user should receive progress/result messages"
        assert captured["edits"], "result message should be edited in place"
        _pass("v1.20 legacy button action session lifecycle")
    finally:
        cc.get_button_context = orig_get_ctx
        cc.gog_scout = orig_gog
        cc.build_dynamic_ui = orig_build_ui
        cc.humanize_agent_report = orig_humanize
        cc.clean_html_for_telegram = orig_clean

        cc.create_execution_session = orig_create
        cc.mark_execution_session_running = orig_running
        cc.mark_execution_step_status = orig_step
        cc.finalize_execution_session = orig_finalize
        cc.append_execution_event = orig_event


if __name__ == "__main__":
    test_legacy_button_context_action_is_sessionized()
