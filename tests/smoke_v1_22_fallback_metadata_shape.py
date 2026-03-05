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


def test_fallback_metadata_shape_for_no_session_execution() -> None:
    _install_psycopg2_stub()
    _install_optional_runtime_stubs()
    import app.intent_runtime as runtime

    original_reasoning = runtime.run_reasoning_step
    try:
        async def _fake_reasoning(**kwargs):
            return "fallback-report"

        runtime.run_reasoning_step = _fake_reasoning

        async def _ui(_msg: str) -> None:
            return None

        report, meta = asyncio.run(
            runtime._execute_reasoning_with_planner_fallback(
                session_id="",
                plan_steps=[],
                intent_spec={},
                prompt="EXECUTE",
                container="openclaw",
                google_account="user@example.com",
                ui_updater=_ui,
                task_name="Intent: Free Text",
            )
        )
    finally:
        runtime.run_reasoning_step = original_reasoning

    assert report == "fallback-report"
    assert str(meta.get("task_type") or "") == "free_text_response"
    assert str(meta.get("output_artifact_type") or "") == "chat_response"
    providers = list(meta.get("provider_candidates") or [])
    assert providers == []
    _pass("v1.22 fallback metadata shape for no-session execution")


if __name__ == "__main__":
    test_fallback_metadata_shape_for_no_session_execution()
