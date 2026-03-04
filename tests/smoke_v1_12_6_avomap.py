from __future__ import annotations

import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "ea/app"

SETTINGS = APP / "settings.py"
MAIN = APP / "main.py"
BROWSERACT = APP / "intake/browseract.py"
EVENT_WORKER = APP / "workers/event_worker.py"
BRIEFINGS = APP / "briefings.py"
SCHEDULER = APP / "scheduler.py"
DB = APP / "db.py"
ROUTING = APP / "integrations/routing/service.py"
SANITIZER = APP / "integrations/avomap/sanitizer.py"
AVOMAP_SECURITY = APP / "integrations/avomap/security.py"
TG_MEDIA = APP / "telegram/media.py"
RUNNER = APP / "runner.py"
SCHEMA = ROOT / "ea/schema/v1_12_6_avomap.sql"
E2E_SCRIPT = ROOT / "tests/e2e_v1_12_6_avomap.py"
DESIGN_E2E_SCRIPT = ROOT / "scripts/docker_e2e_design_workflows.sh"

AVOMAP_FILES = [
    APP / "integrations/avomap/__init__.py",
    APP / "integrations/avomap/specs.py",
    APP / "integrations/avomap/detector.py",
    APP / "integrations/avomap/service.py",
    APP / "integrations/avomap/sanitizer.py",
    APP / "integrations/avomap/security.py",
    APP / "integrations/avomap/browseract_payloads.py",
    APP / "integrations/avomap/finalize.py",
    APP / "integrations/routing/service.py",
    APP / "telegram/media.py",
]

for path in [SETTINGS, MAIN, BROWSERACT, EVENT_WORKER, BRIEFINGS, SCHEDULER, DB, ROUTING, SANITIZER, AVOMAP_SECURITY, TG_MEDIA, RUNNER, E2E_SCRIPT, *AVOMAP_FILES]:
    ast.parse(path.read_text(encoding="utf-8"))
print("[SMOKE][HOST][PASS] v1.12.6 modules parse")

schema = SCHEMA.read_text(encoding="utf-8")
for table in (
    "travel_place_history",
    "travel_video_specs",
    "avomap_jobs",
    "avomap_assets",
    "avomap_credit_ledger",
):
    assert f"CREATE TABLE IF NOT EXISTS {table}" in schema, table
print("[SMOKE][HOST][PASS] v1.12.6 schema tables present")

db_src = DB.read_text(encoding="utf-8")
for table in (
    "travel_place_history",
    "travel_video_specs",
    "avomap_jobs",
    "avomap_assets",
    "avomap_credit_ledger",
):
    assert f"CREATE TABLE IF NOT EXISTS {table}" in db_src, table
print("[SMOKE][HOST][PASS] init_db provisions v1.12.6 tables")

settings_src = SETTINGS.read_text(encoding="utf-8")
for key in (
    "avomap_enabled",
    "avomap_browseract_workflow",
    "avomap_recent_place_days",
    "avomap_max_per_person_per_day",
    "avomap_daily_render_budget",
    "avomap_default_orientation",
    "avomap_duration_target_sec",
    "avomap_late_attach_window_sec",
    "avomap_webhook_secret",
    "avomap_browseract_timeout_sec",
):
    assert key in settings_src, key
print("[SMOKE][HOST][PASS] AVOMAP_* settings wired")

browseract_src = BROWSERACT.read_text(encoding="utf-8")
assert "finalize_avomap_render_event" in browseract_src
assert "startswith(\"avomap.\")" in browseract_src
assert "status IN ('new', 'queued', 'retry', 'failed')" in browseract_src
event_worker_src = EVENT_WORKER.read_text(encoding="utf-8")
assert "status IN ('new', 'queued')" in event_worker_src
print("[SMOKE][HOST][PASS] browseract finalize path wired")

main_src = MAIN.read_text(encoding="utf-8")
assert "/webhooks/browseract/{tenant}/{workflow}" in main_src
assert "x-webhook-signature" in main_src
assert "verify_webhook_signature" in main_src
print("[SMOKE][HOST][PASS] avomap webhook signature gate wired")

runner_src = RUNNER.read_text(encoding="utf-8")
assert 'if r == "api":' in runner_src
assert 'uvicorn.run("app.main:app"' in runner_src
print("[SMOKE][HOST][PASS] api role serves BrowserAct ingress app")

brief_src = BRIEFINGS.read_text(encoding="utf-8")
assert "_avomap_prepare_card" in brief_src
assert "AvoMapService" in brief_src
assert "svc.get_ready_asset" in brief_src
assert "svc.plan_for_briefing" not in brief_src
print("[SMOKE][HOST][PASS] briefing integration wired")

scheduler_src = SCHEDULER.read_text(encoding="utf-8")
assert "_maybe_avomap_prewarm" in scheduler_src
assert "plan_for_briefing" in scheduler_src
print("[SMOKE][HOST][PASS] scheduler prewarm wiring")

design_script = DESIGN_E2E_SCRIPT.read_text(encoding="utf-8")
assert "v1_12_6_avomap.sql" in design_script
assert "e2e_v1_12_6_avomap.py" in design_script
print("[SMOKE][HOST][PASS] design E2E script includes v1.12.6 flow")

sys.path.insert(0, str(ROOT / "ea"))
from app.settings import settings  # noqa: E402

assert hasattr(settings, "avomap_enabled")
assert hasattr(settings, "avomap_browseract_workflow")
assert settings.avomap_browseract_workflow
print("[SMOKE][HOST][PASS] runtime settings expose v1.12.6 attributes")
