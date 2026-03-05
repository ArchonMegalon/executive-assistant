from __future__ import annotations

import json
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


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_step_output_refs_persistence_wiring() -> None:
    src = (ROOT / "ea/app/execution/session_store.py").read_text(encoding="utf-8")
    assert "output_refs: list[str] | None = None" in src
    assert "output_refs_json = CASE WHEN %s THEN %s::jsonb ELSE output_refs_json END" in src
    _pass("v1.22 step output_refs persistence wiring")


def test_step_output_refs_persistence_behavior() -> None:
    _install_psycopg2_stub()
    import app.execution.session_store as store

    calls: list[tuple[str, object]] = []

    class _FakeDB:
        def execute(self, query: str, vars=None) -> None:
            calls.append((str(query), vars))

    original_get_db = store.get_db
    store.get_db = lambda: _FakeDB()
    try:
        ref = "planner_context:2:gather_project_context"
        store.mark_execution_step_status(
            "sess-refs",
            "gather_project_context",
            "completed",
            result={"status": "deterministic_context_ready"},
            output_refs=[ref],
            provider_key="deterministic_planner",
            step_kind="context",
        )
    finally:
        store.get_db = original_get_db

    updates = [(q, v) for (q, v) in calls if "UPDATE execution_steps" in q]
    assert updates, "expected execution_steps update"
    query, vars = updates[-1]
    assert "output_refs_json = CASE WHEN" in query
    assert isinstance(vars, tuple)
    assert json.dumps(["planner_context:2:gather_project_context"]) in [str(v) for v in vars]
    assert "deterministic_planner" in [str(v) for v in vars]
    assert "context" in [str(v) for v in vars]
    _pass("v1.22 step output_refs persistence behavior")


if __name__ == "__main__":
    test_step_output_refs_persistence_wiring()
    test_step_output_refs_persistence_behavior()
