from __future__ import annotations

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


def test_planner_exports_surface() -> None:
    _install_psycopg2_stub()
    import app.planner as planner

    for name in (
        "run_pre_execution_steps_from_ledger",
        "list_queued_pre_execution_steps",
        "fetch_session_plan_steps",
        "resolve_execute_step_metadata",
        "infer_domain",
        "detect_high_risk_action",
        "match_task_type",
        "ProactivePlanner",
    ):
        assert hasattr(planner, name), f"missing_export:{name}"
    _pass("v1.22 planner exports surface")


if __name__ == "__main__":
    test_planner_exports_surface()
