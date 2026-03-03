from __future__ import annotations

import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "ea/app"

SETTINGS = APP / "settings.py"
MAIN = APP / "main.py"
RUNNER = APP / "runner.py"
DB = APP / "db.py"
SERVER = APP / "server.py"
OUTBOX_ROLE = APP / "roles/outbox.py"
QUEUE = APP / "queue.py"
EVENT_WORKER = APP / "workers/event_worker.py"
BROWSERACT = APP / "intake/browseract.py"
NORMALIZER = APP / "approvals/normalizer.py"
POLL_LISTENER = APP / "poll_listener.py"
TG_SAFETY = APP / "telegram/safety.py"
SCHEMA = ROOT / "ea/schema/20260303_v1_18_1_runtime_alignment.sql"

for path in (SETTINGS, MAIN, RUNNER, DB, SERVER, OUTBOX_ROLE, QUEUE, EVENT_WORKER, BROWSERACT, NORMALIZER, POLL_LISTENER, TG_SAFETY):
    ast.parse(path.read_text(encoding="utf-8"))
print("[SMOKE][HOST][PASS] v1.18.1 patched modules parse")

schema = SCHEMA.read_text(encoding="utf-8")
for table in (
    "tg_updates",
    "tg_outbox",
    "typed_actions",
    "template_registry",
    "external_approvals",
    "external_events",
    "delivery_sessions",
    "location_events",
    "location_cursors",
    "shopping_list",
    "location_notifications",
    "survey_blueprints",
    "survey_requests",
    "survey_instances",
    "survey_submissions",
    "intake_insights",
    "browser_jobs",
):
    assert f"CREATE TABLE IF NOT EXISTS {table}" in schema, table
assert "ALTER TABLE IF EXISTS tg_updates ADD COLUMN IF NOT EXISTS updated_at" in schema
assert "ALTER TABLE IF EXISTS tg_outbox ADD COLUMN IF NOT EXISTS updated_at" in schema
assert "ALTER TABLE IF EXISTS tg_outbox ALTER COLUMN id SET DEFAULT gen_random_uuid()" in schema
print("[SMOKE][HOST][PASS] v1.18.1 runtime schema tables present")

db_src = DB.read_text(encoding="utf-8")
for table in (
    "tg_updates",
    "tg_outbox",
    "typed_actions",
    "template_registry",
    "external_approvals",
    "location_events",
    "location_cursors",
    "shopping_list",
    "location_notifications",
    "survey_blueprints",
    "survey_requests",
    "survey_instances",
    "survey_submissions",
    "intake_insights",
    "browser_jobs",
):
    assert f"CREATE TABLE IF NOT EXISTS {table}" in db_src, table
assert "ALTER TABLE IF EXISTS tg_updates ADD COLUMN IF NOT EXISTS updated_at" in db_src
assert "ALTER TABLE IF EXISTS tg_outbox ADD COLUMN IF NOT EXISTS updated_at" in db_src
assert "ALTER TABLE IF EXISTS tg_outbox ALTER COLUMN id SET DEFAULT gen_random_uuid()" in db_src
assert "CREATE INDEX IF NOT EXISTS idx_ext_events_poll ON external_events(status, next_attempt_at)" in db_src
assert "CREATE INDEX IF NOT EXISTS idx_delivery_sessions_corr ON delivery_sessions(correlation_id)" in db_src
print("[SMOKE][HOST][PASS] init_db provisions runtime tables")

runner_src = RUNNER.read_text(encoding="utf-8")
assert 'uvicorn.run("app.main:app"' in runner_src
assert "runpy.run_module" not in runner_src
assert "Unknown EA_ROLE" in runner_src
print("[SMOKE][HOST][PASS] API role routed to app.main")

main_src = MAIN.read_text(encoding="utf-8")
assert "def _require_ingest_auth" in main_src
assert "metasurvey_webhook" in main_src and "authorization: str = Header(None)" in main_src
assert "browseract_webhook" in main_src and "authorization: str = Header(None)" in main_src
assert "detail=str(e)" not in main_src
assert 'detail="Internal server error"' in main_src
print("[SMOKE][HOST][PASS] webhook auth guard wired")

server_src = SERVER.read_text(encoding="utf-8")
assert "def _require_debug_auth" in server_src
assert "heartbeat_pinger" in server_src
assert "settings.ea_operator_token" in server_src
assert "debug_audit(limit: int = 50, authorization: str = Header(None))" in server_src
assert "trigger_briefing(tenant: str, authorization: str = Header(None))" in server_src
assert "calendar_token(tenant: str, authorization: str = Header(None))" in server_src
assert "debug_calendar(tenant: str, days: int = 7, authorization: str = Header(None))" in server_src
assert 'if role in ("", "monolith"):' in server_src and "asyncio.create_task(poll_loop())" in server_src
print("[SMOKE][HOST][PASS] debug auth + api poller gating wired")

event_worker_src = EVENT_WORKER.read_text(encoding="utf-8")
assert "to_jsonb(external_events)->>'id'" in event_worker_src
assert "to_jsonb(external_events)->>'event_id'" in event_worker_src

for p in (BROWSERACT, NORMALIZER):
    src = p.read_text(encoding="utf-8")
    assert "to_jsonb(external_events)->>'id'" in src and "to_jsonb(external_events)->>'event_id'" in src, str(p)
print("[SMOKE][HOST][PASS] external_events id/event_id compatibility present")

outbox_src = OUTBOX_ROLE.read_text(encoding="utf-8")
assert "interval '%s seconds'" not in outbox_src
assert "INTERVAL '1 second'" in outbox_src

queue_src = QUEUE.read_text(encoding="utf-8")
assert "interval '%s seconds'" not in queue_src
assert "INTERVAL '1 second'" in queue_src
print("[SMOKE][HOST][PASS] outbox retry SQL uses safe interval arithmetic")

poll_src = POLL_LISTENER.read_text(encoding="utf-8")
assert "cmd_aliases" in poll_src
assert "'/vrief': '/brief'" in poll_src
assert ".rstrip(':')" in poll_src
assert "Calendar Import Partial" in poll_src
assert "Calendar Import Failed" in poll_src
assert "_sentinel_enabled_for_role" in poll_src
assert "threading.Thread(target=_watchdog_loop, daemon=True).start()" in poll_src
print("[SMOKE][HOST][PASS] /vrief alias + ':' command normalization wired")

briefings_src = (APP / "briefings.py").read_text(encoding="utf-8")
assert "urllib.request.urlopen = _monkey_urlopen" not in briefings_src
print("[SMOKE][HOST][PASS] briefing module avoids global urllib monkey patching")

tg_safety_src = TG_SAFETY.read_text(encoding="utf-8")
assert "def sanitize_for_telegram" in tg_safety_src
print("[SMOKE][HOST][PASS] telegram safety compatibility shim present")

sys.path.insert(0, str(ROOT / "ea"))
from app.settings import settings  # noqa: E402

for attr in (
    "tz",
    "docker_sock",
    "llm_model",
    "ea_ingest_token",
    "ea_operator_token",
    "apixdrive_shared_secret",
    "calendar_ics_secret",
    "calendar_default_duration_min",
    "calendar_loop_interval_s",
    "calendar_remind_soon_min",
    "calendar_leave_buffer_min",
    "calendar_lookahead_hours",
    "location_poll_interval_s",
    "default_location_cooldown_min",
):
    assert hasattr(settings, attr), attr
print("[SMOKE][HOST][PASS] settings expose required runtime attributes")
