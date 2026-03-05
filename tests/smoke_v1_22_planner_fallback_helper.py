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


def _install_optional_runtime_stubs() -> None:
    if "httpx" not in sys.modules:
        fake_httpx = types.ModuleType("httpx")

        class _DummyAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        fake_httpx.AsyncClient = _DummyAsyncClient
        sys.modules["httpx"] = fake_httpx


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_planner_fallback_helper_wiring() -> None:
    src = (ROOT / "ea/app/intent_runtime.py").read_text(encoding="utf-8")
    assert "async def _execute_reasoning_with_planner_fallback(" in src
    assert src.count("_execute_reasoning_with_planner_fallback(") >= 3
    _pass("v1.22 planner fallback helper wiring")


def test_planner_fallback_helper_behavior() -> None:
    _install_psycopg2_stub()
    _install_optional_runtime_stubs()
    import app.intent_runtime as runtime

    calls = {"planned": 0, "fallback": 0}
    original_planned = runtime.execute_planned_reasoning_step
    original_fallback = runtime.run_reasoning_step
    try:
        async def _fake_planned(**kwargs):
            calls["planned"] += 1
            return {
                "report": "planned-report",
                "task_type": "strategy_pack",
                "output_artifact_type": "strategy_pack",
                "provider_candidates": ["paperguide"],
            }

        async def _fake_fallback(**kwargs):
            calls["fallback"] += 1
            return "fallback-report"

        runtime.execute_planned_reasoning_step = _fake_planned
        runtime.run_reasoning_step = _fake_fallback

        async def _ui(_msg: str) -> None:
            return None

        report1, meta1 = asyncio.run(
            runtime._execute_reasoning_with_planner_fallback(
                session_id="sess-123",
                plan_steps=[{"step_key": "execute_intent"}],
                intent_spec={"task_type": "strategy_pack"},
                prompt="EXECUTE",
                container="openclaw",
                google_account="user@example.com",
                ui_updater=_ui,
                task_name="Intent: Free Text",
            )
        )
        report2, meta2 = asyncio.run(
            runtime._execute_reasoning_with_planner_fallback(
                session_id="",
                plan_steps=[],
                intent_spec={"task_type": "free_text_response"},
                prompt="EXECUTE",
                container="openclaw",
                google_account="user@example.com",
                ui_updater=_ui,
                task_name="Intent: Free Text",
            )
        )
    finally:
        runtime.execute_planned_reasoning_step = original_planned
        runtime.run_reasoning_step = original_fallback

    assert calls["planned"] == 1
    assert calls["fallback"] == 1
    assert report1 == "planned-report"
    assert str(meta1.get("task_type") or "") == "strategy_pack"
    assert report2 == "fallback-report"
    assert str(meta2.get("task_type") or "") == "free_text_response"
    _pass("v1.22 planner fallback helper behavior")


if __name__ == "__main__":
    test_planner_fallback_helper_wiring()
    test_planner_fallback_helper_behavior()
