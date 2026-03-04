from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "ea/app"
CONTRACTS = APP / "contracts"
DOCS = ROOT / "docs"

BRIEFINGS = APP / "briefings.py"
POLL_LISTENER = APP / "poll_listener.py"
COACHING = APP / "coaching.py"
VISION = APP / "vision.py"
CHAT_ASSIST = APP / "chat_assist.py"
BRIEFING_DELIVERY = APP / "briefing_delivery_sessions.py"
LLM_CONTRACT = CONTRACTS / "llm_gateway.py"
REPAIR_CONTRACT = CONTRACTS / "repair.py"
TELEGRAM_CONTRACT = CONTRACTS / "telegram.py"
VISION_CONTRACT = CONTRACTS / "vision_gateway.py"
FREEZE_DOC = DOCS / "v1_12_7_contract_freeze.md"
ROADMAP_DOC = DOCS / "ea_os_design_roadmap_v2026.md"


for path in (
    BRIEFINGS,
    POLL_LISTENER,
    COACHING,
    VISION,
    CHAT_ASSIST,
    BRIEFING_DELIVERY,
    LLM_CONTRACT,
    REPAIR_CONTRACT,
    TELEGRAM_CONTRACT,
    VISION_CONTRACT,
):
    ast.parse(path.read_text(encoding="utf-8"))
print("[SMOKE][HOST][PASS] v1.12.7 contract modules parse")

llm_src = LLM_CONTRACT.read_text(encoding="utf-8")
repair_src = REPAIR_CONTRACT.read_text(encoding="utf-8")
tg_src = TELEGRAM_CONTRACT.read_text(encoding="utf-8")
vision_contract_src = VISION_CONTRACT.read_text(encoding="utf-8")
assert "def ask_text(" in llm_src
assert "def open_repair_incident(" in repair_src
assert "def sanitize_incident_copy(" in tg_src
assert "def extract_calendar_events_from_image(" in vision_contract_src
print("[SMOKE][HOST][PASS] v1.12.7 contract symbols present")

brief_src = BRIEFINGS.read_text(encoding="utf-8")
assert "from app.contracts.llm_gateway import ask_text as gateway_ask_text" in brief_src
assert "from app.contracts.repair import open_repair_incident" in brief_src
assert "from app.contracts.telegram import sanitize_incident_copy" in brief_src
assert "from app.llm import ask_llm" not in brief_src
assert "from app.supervisor import trigger_mum_brain" not in brief_src
assert "generativelanguage.googleapis.com" not in brief_src
print("[SMOKE][HOST][PASS] briefings uses frozen contracts")

poll_src = POLL_LISTENER.read_text(encoding="utf-8")
assist_src = CHAT_ASSIST.read_text(encoding="utf-8")
delivery_src = BRIEFING_DELIVERY.read_text(encoding="utf-8")
assert "from app.chat_assist import ask_llm_text as _ask_llm_text" in poll_src
assert "from app.briefing_delivery_sessions import create_briefing_delivery_session, activate_briefing_delivery_session" in poll_src
assert "from app.contracts.llm_gateway import ask_text as gateway_ask_text" in assist_src
assert "def create_briefing_delivery_session(" in delivery_src
assert "from app.contracts.repair import open_repair_incident" in poll_src
assert "from app.briefings import build_briefing_for_tenant, get_val, call_llm, call_powerful_llm" not in poll_src
assert "trigger_mum_brain(" not in poll_src
print("[SMOKE][HOST][PASS] poll_listener uses llm+repair contracts")

coach_src = COACHING.read_text(encoding="utf-8")
assert "from app.contracts.llm_gateway import ask_text as gateway_ask_text" in coach_src
assert "from app.llm import ask_llm" not in coach_src
print("[SMOKE][HOST][PASS] coaching uses llm contract")

vision_src = VISION.read_text(encoding="utf-8")
assert "from app.contracts.vision_gateway import extract_calendar_events_from_image" in vision_src
assert "generativelanguage.googleapis.com" not in vision_src
print("[SMOKE][HOST][PASS] vision uses vision contract")

assert FREEZE_DOC.exists(), FREEZE_DOC
assert ROADMAP_DOC.exists(), ROADMAP_DOC
print("[SMOKE][HOST][PASS] roadmap and contract-freeze docs present")
