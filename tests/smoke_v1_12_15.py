from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLL = ROOT / "ea/app/poll_listener.py"
HOUSEHOLD = ROOT / "ea/app/policy/household.py"
sys.path.insert(0, str(ROOT / "ea"))

poll_src = POLL.read_text(encoding="utf-8")
ast.parse(poll_src)
assert "from app.policy.household import gate_household_document_action" in poll_src
assert "pipeline_stage='intent.image_calendar'" in poll_src
assert "pipeline_stage='intent.invoice'" in poll_src
print("[SMOKE][HOST][PASS] household gate wired in poll_listener")

spec = importlib.util.spec_from_file_location("ea_household_policy_host", HOUSEHOLD)
household = importlib.util.module_from_spec(spec)
fake_app_db = types.ModuleType("app.db")
fake_app_db.get_db = lambda: None
sys.modules["app.db"] = fake_app_db
spec.loader.exec_module(household)

class FakeDB:
    def __init__(self):
        self.calls = []

    def execute(self, query, vars=None):
        self.calls.append((query, vars))

fake_db = FakeDB()
household.get_db = lambda: fake_db

ok = household.gate_household_document_action(
    document_id="doc-allow",
    user_id="123",
    confidence_score=0.99,
    raw_document_ref="telegram:chat:123:message:1:file:abc",
    pipeline_stage="intent.invoice",
    correlation_id="hh-allow",
)
assert ok["action_allowed"] is True

blocked = household.gate_household_document_action(
    document_id="doc-block",
    user_id="123",
    confidence_score=0.40,
    raw_document_ref="telegram:chat:123:message:2:file:def",
    pipeline_stage="intent.image_calendar",
    correlation_id="hh-block",
)
assert blocked["action_allowed"] is False
assert blocked["reason"] == "low_confidence_ownership"
assert blocked["triage_queued"] is True
assert blocked["replay_recorded"] is True
assert len(fake_db.calls) == 2
print("[SMOKE][HOST][PASS] household triage + replay persistence path")
