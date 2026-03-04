from __future__ import annotations

import contextlib
import io
import os
import pathlib
import sys
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def _ensure_runtime_stubs() -> None:
    if "httpx" not in sys.modules:
        class _DummyResponse:
            def __init__(self):
                self.text = ""
                self.content = b""

            def json(self):
                return {"ok": True, "result": {}}

        class _DummyAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def post(self, *args, **kwargs):
                return _DummyResponse()

            async def get(self, *args, **kwargs):
                return _DummyResponse()

        sys.modules["httpx"] = SimpleNamespace(AsyncClient=_DummyAsyncClient)

    if "psycopg2" not in sys.modules:
        class _DummyCursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

            def execute(self, *args, **kwargs):
                return None

            def fetchone(self):
                return None

            def fetchall(self):
                return []

        class _DummyConnection:
            def cursor(self, *args, **kwargs):
                return _DummyCursor()

            def commit(self):
                return None

        class _DummyThreadedConnectionPool:
            def __init__(self, *args, **kwargs):
                pass

            def getconn(self):
                return _DummyConnection()

            def putconn(self, conn):
                return None

        pool_mod = SimpleNamespace(ThreadedConnectionPool=_DummyThreadedConnectionPool)
        extras_mod = SimpleNamespace(RealDictCursor=object)
        psycopg2_mod = SimpleNamespace(pool=pool_mod, extras=extras_mod)
        sys.modules["psycopg2"] = psycopg2_mod
        sys.modules["psycopg2.pool"] = pool_mod
        sys.modules["psycopg2.extras"] = extras_mod


def test_briefing_diagnostics_log_disabled_by_default() -> None:
    _ensure_runtime_stubs()
    import app.briefings as brief

    old = os.environ.pop("EA_BRIEFING_DIAGNOSTICS_LOG_ENABLED", None)
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            brief._emit_internal_diagnostics(["diag-line"])
        assert buf.getvalue() == ""
    finally:
        if old is not None:
            os.environ["EA_BRIEFING_DIAGNOSTICS_LOG_ENABLED"] = old
        else:
            os.environ.pop("EA_BRIEFING_DIAGNOSTICS_LOG_ENABLED", None)
    _pass("v1.19.4 briefing diagnostics log disabled by default")


def test_briefing_diagnostics_log_enabled_with_flag() -> None:
    _ensure_runtime_stubs()
    import app.briefings as brief

    old = os.environ.get("EA_BRIEFING_DIAGNOSTICS_LOG_ENABLED")
    os.environ["EA_BRIEFING_DIAGNOSTICS_LOG_ENABLED"] = "1"
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            brief._emit_internal_diagnostics(["diag-line"])
        out = buf.getvalue()
        assert "[BRIEFING][DIAGNOSTICS]" in out
        assert "diag-line" in out
    finally:
        if old is not None:
            os.environ["EA_BRIEFING_DIAGNOSTICS_LOG_ENABLED"] = old
        else:
            os.environ.pop("EA_BRIEFING_DIAGNOSTICS_LOG_ENABLED", None)
    _pass("v1.19.4 briefing diagnostics log enabled by flag")


if __name__ == "__main__":
    test_briefing_diagnostics_log_disabled_by_default()
    test_briefing_diagnostics_log_enabled_with_flag()
