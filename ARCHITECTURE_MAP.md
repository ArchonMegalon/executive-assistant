# Architecture Map

## Runtime Entry Points

- API app factory: `ea/app/api/app.py`
- ASGI app export: `ea/app/main.py`
- Process runner / role switch: `ea/app/runner.py`

## API Surface

- Health: `GET /health` (`ea/app/api/routes/health.py`)
- Rewrite kernel:
  - `POST /v1/rewrite/artifact`
  - `GET /v1/rewrite/sessions/{session_id}`
  - (`ea/app/api/routes/rewrite.py`)
- Policy audit:
  - `GET /v1/policy/decisions/recent`
  - (`ea/app/api/routes/policy.py`)
- Observation runtime:
  - `POST /v1/observations/ingest`
  - `GET /v1/observations/recent`
  - (`ea/app/api/routes/observations.py`)
- Delivery runtime:
  - `POST /v1/delivery/outbox`
  - `POST /v1/delivery/outbox/{delivery_id}/sent`
  - `GET /v1/delivery/outbox/pending`
  - (`ea/app/api/routes/delivery.py`)
- Telegram adapter:
  - `POST /v1/channels/telegram/ingest`
  - (`ea/app/api/routes/channels.py`)

## Core Domain Models

- Intent + execution: `IntentSpecV3`, `ExecutionSession`, `ExecutionEvent`
- Policy: `PolicyDecision`, `PolicyDecisionRecord`
- Channel runtime: `ObservationEvent`, `DeliveryOutboxItem`
- File: `ea/app/domain/models.py`

## Services

- Orchestration + policy gating + ledger/policy backend selection:
  - `ea/app/services/orchestrator.py`
- Policy decision logic:
  - `ea/app/services/policy.py`
- Channel runtime (observations + outbox) + backend selection:
  - `ea/app/services/channel_runtime.py`

## Repositories

- Execution ledger:
  - in-memory: `ea/app/repositories/ledger.py`
  - postgres: `ea/app/repositories/ledger_postgres.py`
- Policy decisions:
  - in-memory: `ea/app/repositories/policy_decisions.py`
  - postgres: `ea/app/repositories/policy_decisions_postgres.py`
- Observation events:
  - in-memory: `ea/app/repositories/observation.py`
  - postgres: `ea/app/repositories/observation_postgres.py`
- Delivery outbox:
  - in-memory: `ea/app/repositories/delivery_outbox.py`
  - postgres: `ea/app/repositories/delivery_outbox_postgres.py`

## Migrations (Kernel Baseline)

- `ea/schema/20260305_v0_2_execution_ledger_kernel.sql`
- `ea/schema/20260305_v0_3_channel_runtime_kernel.sql`
- `ea/schema/20260305_v0_4_policy_decisions_kernel.sql`

## Operator Tooling

- Deploy: `scripts/deploy.sh` (`EA_BOOTSTRAP_DB=1` optionally chains bootstrap)
- Bootstrap migrations: `scripts/db_bootstrap.sh`
- DB status: `scripts/db_status.sh`
- Full API smoke: `scripts/smoke_api.sh`
- CI smoke workflow: `.github/workflows/smoke-runtime.yml`
- Shortcut targets: `Makefile`
