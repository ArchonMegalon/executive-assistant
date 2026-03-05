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


def test_intent_compiler_module_and_shim_wiring() -> None:
    planner_src = (ROOT / "ea/app/planner/intent_compiler.py").read_text(encoding="utf-8")
    store_src = (ROOT / "ea/app/execution/session_store.py").read_text(encoding="utf-8")
    assert "def compile_intent_spec_v2(" in planner_src
    assert "def _task_type_from_text(" in planner_src
    assert "from app.planner.intent_compiler import compile_intent_spec_v2" in store_src
    assert "return compile_intent_spec_v2(" in store_src
    _pass("v1.21 intent compiler module + shim wiring")


def test_intent_spec_v2_shape_for_high_risk_finance() -> None:
    _install_psycopg2_stub()
    from app.execution.session_store import compile_intent_spec

    spec = compile_intent_spec(
        text="Please pay invoice #123 today and confirm transfer.",
        tenant="chat_100284",
        chat_id=1234,
        has_url=False,
    )
    assert spec.get("domain") == "finance"
    assert spec.get("autonomy_level") == "approval_required"
    assert spec.get("approval_class") == "explicit_callback_required"
    assert spec.get("risk_class") == "high_impact_action"
    assert spec.get("budget_class") == "high_guardrail"
    assert spec.get("task_type") == "approval_router"
    assert "payment_context" in list(spec.get("evidence_requirements") or [])
    assert isinstance(spec.get("output_contract"), dict)
    assert str(spec.get("commitment_key")).startswith("finance:chat_100284:")
    _pass("v1.21 intent spec v2 shape (high-risk)")


def test_intent_spec_v2_shape_for_url_analysis() -> None:
    _install_psycopg2_stub()
    from app.execution.session_store import compile_intent_spec

    spec = compile_intent_spec(
        text="Can you summarize this article? https://example.com/post",
        tenant="chat_100284",
        chat_id=1234,
        has_url=True,
    )
    assert spec.get("intent_type") == "url_analysis"
    assert spec.get("deliverable_type") == "answer_now"
    assert spec.get("approval_class") == "none"
    assert spec.get("task_type") == "run_secondary_research_pass"
    assert "url_evidence" in list(spec.get("evidence_requirements") or [])
    refs = list(spec.get("source_refs") or [])
    assert refs and "https://example.com/post" in refs[0]
    _pass("v1.21 intent spec v2 shape (url-analysis)")


if __name__ == "__main__":
    test_intent_compiler_module_and_shim_wiring()
    test_intent_spec_v2_shape_for_high_risk_finance()
    test_intent_spec_v2_shape_for_url_analysis()
