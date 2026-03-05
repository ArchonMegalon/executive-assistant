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
- Memory kernel:
  - `POST /v1/memory/candidates`
  - `GET /v1/memory/candidates`
  - `POST /v1/memory/candidates/{candidate_id}/promote`
  - `POST /v1/memory/candidates/{candidate_id}/reject`
  - `GET /v1/memory/items`
  - `GET /v1/memory/items/{item_id}`
  - `POST /v1/memory/entities`
  - `GET /v1/memory/entities`
  - `GET /v1/memory/entities/{entity_id}`
  - `POST /v1/memory/relationships`
  - `GET /v1/memory/relationships`
  - `GET /v1/memory/relationships/{relationship_id}`
  - `POST /v1/memory/commitments`
  - `GET /v1/memory/commitments`
  - `GET /v1/memory/commitments/{commitment_id}`
  - `POST /v1/memory/authority-bindings`
  - `GET /v1/memory/authority-bindings`
  - `GET /v1/memory/authority-bindings/{binding_id}`
  - `POST /v1/memory/delivery-preferences`
  - `GET /v1/memory/delivery-preferences`
  - `GET /v1/memory/delivery-preferences/{preference_id}`
  - `POST /v1/memory/follow-ups`
  - `GET /v1/memory/follow-ups`
  - `GET /v1/memory/follow-ups/{follow_up_id}`
  - `POST /v1/memory/deadline-windows`
  - `GET /v1/memory/deadline-windows`
  - `GET /v1/memory/deadline-windows/{window_id}`
  - (`ea/app/api/routes/memory.py`)
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
- Memory: `MemoryCandidate`, `MemoryItem`
- Semantic context: `Entity`, `RelationshipEdge`
- Commitment context: `Commitment`
- Governance context: `AuthorityBinding`
- Delivery context: `DeliveryPreference`
- Follow-up context: `FollowUp`
- Deadline context: `DeadlineWindow`
- Channel runtime: `ObservationEvent`, `DeliveryOutboxItem`
- File: `ea/app/domain/models.py`

## Services

- Orchestration + policy gating + ledger/policy backend selection:
  - `ea/app/services/orchestrator.py`
- Policy decision logic:
  - `ea/app/services/policy.py`
- Channel runtime (observations + outbox) + backend selection:
  - `ea/app/services/channel_runtime.py`
- Memory runtime (candidate staging + reviewed promotion) + backend selection:
  - `ea/app/services/memory_runtime.py`

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
- Memory candidates:
  - in-memory: `ea/app/repositories/memory_candidates.py`
  - postgres: `ea/app/repositories/memory_candidates_postgres.py`
- Memory items:
  - in-memory: `ea/app/repositories/memory_items.py`
  - postgres: `ea/app/repositories/memory_items_postgres.py`
- Entities:
  - in-memory: `ea/app/repositories/entities.py`
  - postgres: `ea/app/repositories/entities_postgres.py`
- Relationships:
  - in-memory: `ea/app/repositories/relationships.py`
  - postgres: `ea/app/repositories/relationships_postgres.py`
- Commitments:
  - in-memory: `ea/app/repositories/commitments.py`
  - postgres: `ea/app/repositories/commitments_postgres.py`
- Authority bindings:
  - in-memory: `ea/app/repositories/authority_bindings.py`
  - postgres: `ea/app/repositories/authority_bindings_postgres.py`
- Delivery preferences:
  - in-memory: `ea/app/repositories/delivery_preferences.py`
  - postgres: `ea/app/repositories/delivery_preferences_postgres.py`
- Follow-ups:
  - in-memory: `ea/app/repositories/follow_ups.py`
  - postgres: `ea/app/repositories/follow_ups_postgres.py`
- Deadline windows:
  - in-memory: `ea/app/repositories/deadline_windows.py`
  - postgres: `ea/app/repositories/deadline_windows_postgres.py`
- Delivery outbox:
  - in-memory: `ea/app/repositories/delivery_outbox.py`
  - postgres: `ea/app/repositories/delivery_outbox_postgres.py`

## Migrations (Kernel Baseline)

- `ea/schema/20260305_v0_2_execution_ledger_kernel.sql`
- `ea/schema/20260305_v0_3_channel_runtime_kernel.sql`
- `ea/schema/20260305_v0_4_policy_decisions_kernel.sql`
- `ea/schema/20260305_v0_5_artifacts_kernel.sql`
- `ea/schema/20260305_v0_6_execution_ledger_v2.sql`
- `ea/schema/20260305_v0_7_approvals_kernel.sql`
- `ea/schema/20260305_v0_8_channel_runtime_reliability.sql`
- `ea/schema/20260305_v0_9_tool_connector_kernel.sql`
- `ea/schema/20260305_v0_10_task_contracts_kernel.sql`
- `ea/schema/20260305_v0_11_memory_kernel.sql`
- `ea/schema/20260305_v0_12_entities_relationships_kernel.sql`
- `ea/schema/20260305_v0_13_commitments_kernel.sql`
- `ea/schema/20260305_v0_14_authority_bindings_kernel.sql`
- `ea/schema/20260305_v0_15_delivery_preferences_kernel.sql`
- `ea/schema/20260305_v0_16_follow_ups_kernel.sql`
- `ea/schema/20260305_v0_17_deadline_windows_kernel.sql`

## Operator Tooling

- Deploy: `scripts/deploy.sh` (`EA_BOOTSTRAP_DB=1` optionally chains bootstrap)
- Bootstrap migrations: `scripts/db_bootstrap.sh`
- DB status: `scripts/db_status.sh`
- Full API smoke: `scripts/smoke_api.sh`
- CI smoke workflow: `.github/workflows/smoke-runtime.yml`
- Shortcut targets: `Makefile`
