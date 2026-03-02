from __future__ import annotations

import ast
import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIEF = ROOT / "ea/app/briefings.py"
TG_INIT = ROOT / "ea/app/telegram/__init__.py"
TG_SAFE = ROOT / "ea/app/telegram/safety.py"

brief_src = BRIEF.read_text(encoding="utf-8")
ast.parse(brief_src)
assert "orig_build_briefing_for_tenant = build_briefing_for_tenant" not in brief_src
assert "orig_build_briefing_for_tenant = _raw_build_briefing_for_tenant" in brief_src
print("[SMOKE][HOST][PASS] briefings alias repaired")

spec = importlib.util.spec_from_file_location("ea_tg_safety_host", TG_SAFE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert mod.sanitize_telegram_text('{"error": {"message": "template_id invalid"}}') == mod.SAFE_SIMPLIFIED_COPY
assert "EA v1.12.10 telegram legacy bridge" in TG_INIT.read_text(encoding="utf-8")
print("[SMOKE][HOST][PASS] telegram safety regression")
print("briefings_sha=" + hashlib.sha256(BRIEF.read_bytes()).hexdigest())
print("telegram_init_sha=" + hashlib.sha256(TG_INIT.read_bytes()).hexdigest())
print("telegram_safety_sha=" + hashlib.sha256(TG_SAFE.read_bytes()).hexdigest())
