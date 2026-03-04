from __future__ import annotations

import asyncio
import importlib.util
import os
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLL = ROOT / "ea/app/poll_listener.py"
REPAIR = ROOT / "ea/app/renderer_repair.py"

poll_src = POLL.read_text(encoding="utf-8")
assert "log_render_guard(" in poll_src
assert "renderer_text_only" in poll_src
assert "trigger_mum_brain(" in poll_src
print("[SMOKE][HOST][PASS] poll_listener renderer guard wiring")

spec = importlib.util.spec_from_file_location("ea_renderer_repair_host", REPAIR)
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)

assert rr.classify_renderer_failure("MarkupGo API HTTP 400. source/data/id: Invalid template id") == "invalid_template_id"
payload = {
    "source": {"data": {"id": "bad-template"}},
    "text": "This is a long safe plain text fallback body that should survive renderer failure cleanly in the current session."
}
patched, changed = rr.rewrite_template_ids(payload, "good-template-id")
assert changed and patched["source"]["data"]["id"] == "good-template-id"
assert "safe plain text fallback body" in rr.extract_text_fallback(payload)
print("[SMOKE][HOST][PASS] helper classification + payload rewrite")

dummy = types.SimpleNamespace()
async def call_markupgo(payload):
    if payload["source"]["data"]["id"] == "good-template-id":
        return "FORMATTED_OK"
    raise RuntimeError("MarkupGo API HTTP 400. source/data/id: Invalid template id")
dummy.call_markupgo = call_markupgo

os.environ["EA_MARKUPGO_TEMPLATE_ID_SAFE"] = "good-template-id"
wrapped = rr.patch_renderer_module(dummy)
assert "call_markupgo" in wrapped
res = asyncio.run(dummy.call_markupgo(payload))
assert res == "FORMATTED_OK"
os.environ.pop("EA_MARKUPGO_TEMPLATE_ID_SAFE", None)

dummy2 = types.SimpleNamespace()
async def render_markupgo(payload):
    raise RuntimeError("MarkupGo API HTTP 400. source/data/id: Invalid template id")
dummy2.render_markupgo = render_markupgo
rr.patch_renderer_module(dummy2)
res2 = asyncio.run(dummy2.render_markupgo(payload))
assert "safe plain text fallback body" in res2
print("[SMOKE][HOST][PASS] template swap + text-only fallback")
