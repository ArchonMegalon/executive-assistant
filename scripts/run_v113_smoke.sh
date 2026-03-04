#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/docker/EA}"

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
else
  DC=(docker-compose)
fi

echo "[SMOKE][v1.13] Schema table presence"
docker exec -i ea-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT tablename FROM pg_tables WHERE schemaname='\''public'\'' AND tablename IN ('\''tenant_invites'\'','\''onboarding_sessions'\'','\''principals'\'','\''channel_bindings'\'','\''oauth_connections'\'','\''source_connections'\'','\''source_test_runs'\'','\''tenant_provision_jobs'\'','\''onboarding_audit_events'\'','\''connector_network_modes'\'') ORDER BY tablename"'

echo "[SMOKE][v1.13] Host compile"
python3 -m py_compile \
  "$ROOT/ea/app/net/egress_guard.py" \
  "$ROOT/ea/app/connectors/registry.py" \
  "$ROOT/ea/app/onboarding/service.py" \
  "$ROOT/ea/app/intelligence/future_situations.py" \
  "$ROOT/ea/app/intelligence/readiness.py" \
  "$ROOT/ea/app/intelligence/scores.py" \
  "$ROOT/ea/app/intelligence/preparation_planner.py"

echo "[SMOKE][v1.13] Future intelligence + regression contract smoke"
python3 "$ROOT/tests/smoke_v1_13.py"
python3 "$ROOT/tests/smoke_v1_13_future_intelligence_pack.py"

echo "[SMOKE][v1.13] Container onboarding flow smoke"
"${DC[@]}" exec -T ea-worker python - <<'PY'
from app.onboarding.service import OnboardingService

svc = OnboardingService()
inv = svc.create_invite(tenant_key="smoke_tenant", created_by="smoke")
session_id = svc.start_session_from_invite(invite_token=inv.token)
svc.bind_channel(
    session_id=session_id,
    channel_type="telegram",
    channel_user_id="smoke_user_1",
    chat_id="90001",
    display_name="Smoke User",
    locale="en",
    timezone_name="Europe/Vienna",
)
svc.set_google_oauth_scopes(
    session_id=session_id,
    provider="google",
    scopes=["calendar.readonly"],
    oauth_status="oauth_partial",
    secret_ref="secret://smoke/google/calendar",
)
svc.set_google_oauth_scopes(
    session_id=session_id,
    provider="google",
    scopes=["calendar.readonly", "gmail.readonly"],
    oauth_status="oauth_ready",
    secret_ref="secret://smoke/google/calendar_gmail",
)
blocked = svc.add_source_connection(
    session_id=session_id,
    connector_type="paperless",
    connector_name="Smoke Paperless",
    endpoint_url="http://127.0.0.1:8000",
    network_mode="hosted",
    allow_private_targets=False,
)
assert blocked["ok"] is False
svc.mark_syncing(session_id=session_id)
svc.mark_dry_run_ready(session_id=session_id)
svc.mark_ready(session_id=session_id)
print("[SMOKE][v1.13][PASS] onboarding session flow + hosted private URL blocked")
PY

echo "[SMOKE][v1.13] PASS"
