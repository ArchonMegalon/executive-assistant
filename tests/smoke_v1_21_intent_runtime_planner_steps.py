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


def test_intent_runtime_planner_step_wiring() -> None:
    src = (ROOT / "ea/app/intent_runtime.py").read_text(encoding="utf-8")
    assert "def _run_planner_pre_execution_steps(" in src
    assert "planner_context_step_completed" in src
    _pass("v1.21 intent-runtime planner-step wiring")


def test_intent_runtime_executes_pre_steps_before_execute_intent() -> None:
    _install_psycopg2_stub()
    _install_httpx_stub()
    import app.intent_runtime as ir

    captured: dict[str, object] = {
        "steps": [],
        "finalized": [],
        "messages": [],
    }

    class _FakeTG:
        async def send_message(self, chat_id: int, text: str, parse_mode: str | None = None, reply_markup=None):
            captured["messages"].append({"kind": "send", "text": str(text)})
            return {"ok": True, "message_id": 333}

        async def edit_message_text(
            self,
            chat_id: int,
            message_id: int,
            text: str,
            parse_mode: str | None = None,
            reply_markup=None,
            **kwargs,
        ):
            captured["messages"].append({"kind": "edit", "text": str(text), "parse_mode": parse_mode})
            return {"ok": True}

    orig_create_session = ir.create_execution_session
    orig_mark_running = ir.mark_execution_session_running
    orig_mark_step = ir.mark_execution_step_status
    orig_finalize = ir.finalize_execution_session
    orig_append = ir.append_execution_event
    orig_run_reasoning = ir.run_reasoning_step
    orig_build_ui = ir.build_dynamic_ui

    try:
        ir.create_execution_session = lambda **kwargs: "sess-planner-1"
        ir.mark_execution_session_running = lambda session_id: None
        ir.mark_execution_step_status = (
            lambda session_id, step_key, status, **kwargs: captured["steps"].append((step_key, status, dict(kwargs)))
        )
        ir.finalize_execution_session = (
            lambda session_id, status, outcome=None, last_error=None: captured["finalized"].append(
                {"session_id": session_id, "status": status, "outcome": dict(outcome or {}), "last_error": last_error}
            )
        )
        ir.append_execution_event = lambda *args, **kwargs: None
        ir.build_dynamic_ui = lambda report, prompt, save_ctx=None: {"inline_keyboard": []}

        async def _fake_reasoning_step(**kwargs):
            return "Polish complete."

        ir.run_reasoning_step = _fake_reasoning_step

        async def _run() -> None:
            await ir.handle_free_text_intent(
                tg=_FakeTG(),
                chat_id=44,
                tenant_name="tenant_demo",
                text="Please polish this draft so it sounds natural and concise.",
                tenant_cfg={},
                safe_err=lambda e: str(e),
            )

        asyncio.run(_run())

        step_pairs = [(step, status) for (step, status, _kwargs) in captured["steps"]]
        assert ("prepare_draft_context", "running") in step_pairs
        assert ("prepare_draft_context", "completed") in step_pairs
        assert ("execute_intent", "completed") in step_pairs
        assert ("render_reply", "completed") in step_pairs
        assert captured["finalized"], "session should finalize after response render"
        assert captured["finalized"][0]["status"] == "completed"
        _pass("v1.21 intent-runtime planner-step behavior")
    finally:
        ir.create_execution_session = orig_create_session
        ir.mark_execution_session_running = orig_mark_running
        ir.mark_execution_step_status = orig_mark_step
        ir.finalize_execution_session = orig_finalize
        ir.append_execution_event = orig_append
        ir.run_reasoning_step = orig_run_reasoning
        ir.build_dynamic_ui = orig_build_ui


if __name__ == "__main__":
    test_intent_runtime_planner_step_wiring()
    test_intent_runtime_executes_pre_steps_before_execute_intent()
