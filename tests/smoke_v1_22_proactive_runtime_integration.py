from __future__ import annotations

import os
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


def test_proactive_tenant_selection_and_schema_coverage() -> None:
    _install_psycopg2_stub()
    import app.roles.proactive as pr

    orig_env = os.environ.get("EA_PROACTIVE_TENANTS")
    orig_load_tenants = pr.load_tenants
    try:
        os.environ["EA_PROACTIVE_TENANTS"] = "chat_alpha, chat_beta"
        assert pr._tenant_keys() == ["chat_alpha", "chat_beta"]
        os.environ.pop("EA_PROACTIVE_TENANTS", None)
        pr.load_tenants = lambda: ({"zeta": {}, "alpha": {}}, {}, {})
        assert pr._tenant_keys() == ["alpha", "zeta"]
    finally:
        if orig_env is None:
            os.environ.pop("EA_PROACTIVE_TENANTS", None)
        else:
            os.environ["EA_PROACTIVE_TENANTS"] = orig_env
        pr.load_tenants = orig_load_tenants

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    docker_e2e = (ROOT / "scripts/docker_e2e.sh").read_text(encoding="utf-8")
    assert "--profile proactive up -d ea-proactive" in readme
    assert "20260305_v1_22_approval_gate_deadlines.sql" in docker_e2e
    assert "20260303_v1_18_1_runtime_alignment.sql" in docker_e2e
    _pass("v1.22 proactive runtime integration")


if __name__ == "__main__":
    test_proactive_tenant_selection_and_schema_coverage()
