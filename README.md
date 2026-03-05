# EA Rewrite Baseline

This repository has been reset for a clean rewrite.

Kept:
- core application scaffold in `ea/app`
- deployment baseline (`ea/Dockerfile`, `docker-compose.yml`, `scripts/deploy.sh`)
- environment/config templates (`.env.example`, `config/`)

Removed:
- legacy rollout docs, milestone scripts, and historical test packs
- legacy process/task-tracking artifacts
- legacy sidecar/runtime-specific operational clutter

## Runtime Spine (Rewrite Seed)

- `app.main` exposes a FastAPI app
- `/health` provides a baseline readiness endpoint
- `/v1/rewrite/artifact` creates an artifact and an execution session
- `/v1/rewrite/sessions/{session_id}` exposes the execution ledger for that run
- `/v1/observations/ingest` and `/v1/observations/recent` provide channel-agnostic observation intake
- `/v1/delivery/outbox` endpoints provide channel-agnostic queued delivery tracking
- `/v1/channels/telegram/ingest` maps raw Telegram updates into normalized observation events
- `/v1/policy/decisions/recent` exposes persisted policy decision audit records
- `app.runner` supports role-based startup (`EA_ROLE=api` or idle worker roles)
- `app.domain.IntentSpecV3` and execution session/event models provide a typed kernel scaffold
- rewrite execution is gated by a centralized policy decision service (`policy_decision` event)

## Hardening Baseline

- app images no longer install `docker.io`
- runtime data/secrets are excluded from version control via a narrowed `.gitignore`

## Ledger Backends

- `EA_LEDGER_BACKEND=postgres` forces Postgres-backed execution ledger storage (`DATABASE_URL` required)
- `EA_LEDGER_BACKEND=memory` keeps the ledger in-process (dev/test convenience)
- `EA_LEDGER_BACKEND=auto` (default) attempts Postgres first, then falls back to memory
- baseline schema migration: `ea/schema/20260305_v0_2_execution_ledger_kernel.sql`
- channel runtime migration: `ea/schema/20260305_v0_3_channel_runtime_kernel.sql`
- policy audit migration: `ea/schema/20260305_v0_4_policy_decisions_kernel.sql`

## Quick Start

```bash
cp .env.example .env
# edit .env values
bash scripts/deploy.sh
bash scripts/db_bootstrap.sh

# or do both in one step
EA_BOOTSTRAP_DB=1 bash scripts/deploy.sh
```

Then open `http://localhost:8090/health`.

Operator commands are documented in `RUNBOOK.md`.
