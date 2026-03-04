from __future__ import annotations

import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
EA_DIR = ROOT / "ea"
for path in (str(ROOT), str(EA_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _pass(name: str) -> None:
    print(f"[SMOKE][HOST][PASS] {name}")


def test_llm_egress_policy_module_and_wiring_presence() -> None:
    policy_src = (ROOT / "ea/app/llm_gateway/policy.py").read_text(encoding="utf-8")
    gateway_src = (ROOT / "ea/app/contracts/llm_gateway.py").read_text(encoding="utf-8")
    db_src = (ROOT / "ea/app/db.py").read_text(encoding="utf-8")
    schema_sql = ROOT / "ea/schema/20260304_v1_19_2_llm_egress_policies.sql"

    assert "def is_egress_denied(" in policy_src
    assert "llm_egress_policies" in policy_src
    assert "is_egress_denied" in gateway_src
    assert "blocked_policy" in gateway_src
    assert "tenant: str = \"\"" in gateway_src
    assert "person_id: str = \"\"" in gateway_src
    assert "CREATE TABLE IF NOT EXISTS llm_egress_policies" in db_src
    assert schema_sql.exists()
    _pass("v1.19.2 llm egress policy module+wiring presence")


def test_llm_egress_policy_denies_by_db_rule() -> None:
    import app.contracts.llm_gateway as gw

    class _FakeDB:
        def __init__(self):
            self.queries = []

        def fetchone(self, query, params):
            self.queries.append((str(query), params))
            return {"action": "deny"}

    fake_db = _FakeDB()
    original_app_db = sys.modules.get("app.db")
    original_ask_llm = gw.ask_llm
    try:
        sys.modules["app.db"] = types.SimpleNamespace(get_db=lambda: fake_db)
        gw.ask_llm = lambda prompt, system_prompt: "Safe response"
        out = gw.ask_text(
            "Summarize this",
            task_type="profile_summary",
            purpose="chat_assist",
            correlation_id="cid-policy-deny",
            data_class="derived_summary",
            tenant="chat_123",
            person_id="user_1",
        )
        assert "hidden tool/runtime instructions" in out.lower()
        assert fake_db.queries, "expected policy lookup query"
        assert "llm_egress_policies" in fake_db.queries[-1][0]
    finally:
        gw.ask_llm = original_ask_llm
        if original_app_db is None:
            sys.modules.pop("app.db", None)
        else:
            sys.modules["app.db"] = original_app_db
    _pass("v1.19.2 llm egress policy deny behavior")


if __name__ == "__main__":
    test_llm_egress_policy_module_and_wiring_presence()
    test_llm_egress_policy_denies_by_db_rule()
