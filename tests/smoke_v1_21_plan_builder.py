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


def _step_keys(plan: list[dict[str, object]]) -> list[str]:
    return [str(row.get("step_key") or "") for row in (plan or [])]


def _step_by_key(plan: list[dict[str, object]], step_key: str) -> dict[str, object]:
    for row in plan or []:
        if str((row or {}).get("step_key") or "") == str(step_key):
            return dict(row or {})
    return {}


def test_plan_builder_module_and_session_store_wiring() -> None:
    planner_src = (ROOT / "ea/app/planner/plan_builder.py").read_text(encoding="utf-8")
    store_src = (ROOT / "ea/app/execution/session_store.py").read_text(encoding="utf-8")
    assert "def build_task_plan_steps(" in planner_src
    assert "analyze_trip_commitment" in planner_src
    assert "verify_payment_context" in planner_src
    assert "gather_project_context" in planner_src
    assert "collect_intake_context" in planner_src
    assert "compile_prompt_pack" in planner_src
    assert "prepare_draft_context" in planner_src
    assert "provider_candidates" in planner_src
    assert "output_artifact_type" in planner_src
    assert "return build_task_plan_steps(intent_spec=dict(intent_spec or {}))" in store_src
    assert "meta_evidence[\"provider_candidates\"]" in store_src
    _pass("v1.21 plan builder module/wiring")


def test_task_aware_plan_steps() -> None:
    _install_psycopg2_stub()
    from app.execution.session_store import build_plan_steps, compile_intent_spec

    travel_spec = compile_intent_spec(
        text="Please book my trip to Zurich and review route options.",
        tenant="chat_100284",
        chat_id=123,
        has_url=False,
    )
    travel_keys = _step_keys(build_plan_steps(intent_spec=travel_spec))
    assert "compile_intent" in travel_keys
    assert "analyze_trip_commitment" in travel_keys
    assert "compare_travel_options" in travel_keys
    assert "safety_gate" in travel_keys
    travel_plan = build_plan_steps(intent_spec=travel_spec)
    exec_step = _step_by_key(travel_plan, "execute_intent")
    assert str(exec_step.get("task_type") or "") == "travel_rescue"
    assert list(exec_step.get("provider_candidates") or [])
    assert str(exec_step.get("output_artifact_type") or "") == "travel_decision_pack"
    assert str(exec_step.get("budget_policy") or "") == "travel_sidecar_daily"

    project_spec = compile_intent_spec(
        text="Summarize project deadline risk before tomorrow's meeting.",
        tenant="chat_100284",
        chat_id=123,
        has_url=False,
    )
    project_keys = _step_keys(build_plan_steps(intent_spec=project_spec))
    assert "gather_project_context" in project_keys
    assert "analyze_trip_commitment" not in project_keys

    finance_spec = compile_intent_spec(
        text="Check invoice due date and budget exposure.",
        tenant="chat_100284",
        chat_id=123,
        has_url=False,
    )
    finance_plan = build_plan_steps(intent_spec=finance_spec)
    finance_keys = _step_keys(finance_plan)
    assert "verify_payment_context" in finance_keys
    finance_exec = _step_by_key(finance_plan, "execute_intent")
    assert str(finance_exec.get("task_type") or "") == "typed_safe_action"

    polish_spec = compile_intent_spec(
        text="Please polish this draft so it sounds natural and concise.",
        tenant="chat_100284",
        chat_id=123,
        has_url=False,
    )
    polish_plan = build_plan_steps(intent_spec=polish_spec)
    polish_keys = _step_keys(polish_plan)
    assert "prepare_draft_context" in polish_keys
    polish_exec = _step_by_key(polish_plan, "execute_intent")
    assert str(polish_exec.get("task_type") or "") == "polish_human_tone"

    intake_spec = compile_intent_spec(
        text="Create an intake form questionnaire for new client onboarding.",
        tenant="chat_100284",
        chat_id=123,
        has_url=False,
    )
    intake_plan = build_plan_steps(intent_spec=intake_spec)
    intake_keys = _step_keys(intake_plan)
    assert "collect_intake_context" in intake_keys
    intake_exec = _step_by_key(intake_plan, "execute_intent")
    assert str(intake_exec.get("task_type") or "") == "collect_structured_intake"
    _pass("v1.21 task-aware plan builder behavior")


if __name__ == "__main__":
    test_plan_builder_module_and_session_store_wiring()
    test_task_aware_plan_steps()
