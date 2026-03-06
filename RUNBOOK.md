# Runtime Runbook

All runtime scripts that call HTTP endpoints resolve host port in this order:
1. `EA_HOST_PORT` from current shell env
2. `EA_HOST_PORT` from `.env`
3. fallback `8090`

## API Contract Summary

| Method | Route | Success | Error contracts |
|---|---|---|---|
| GET | `/health` | `200` | n/a |
| GET | `/health/live` | `200` | n/a |
| GET | `/health/ready` | `200` | `503 not_ready:*` |
| GET | `/version` | `200` | n/a |
| POST | `/v1/rewrite/artifact` | `200`, `202 awaiting_approval`, `202 awaiting_human` | `400 text is required`, `403 policy_denied:*` (including `tool_not_allowed`) |
| GET | `/v1/rewrite/artifacts/{artifact_id}` | `200` | `404 artifact_not_found` |
| GET | `/v1/rewrite/receipts/{receipt_id}` | `200` | `404 receipt_not_found` |
| GET | `/v1/rewrite/run-costs/{cost_id}` | `200` | `404 run_cost_not_found` |
| GET | `/v1/rewrite/sessions/{session_id}` | `200` | `404 session not found` (returns events + steps + queue items + receipts + artifacts + costs + human task packets, inline human task assignment history, `plan_compiled` event, and computed reviewer routing hints) |
| POST | `/v1/human/tasks` | `200` | `400 step_id_required`, `404 session_not_found`, `404 step_not_found`, `403 principal_scope_mismatch` (supports `resume_session_on_return=true` to move a linked step into `waiting_human`) |
| GET | `/v1/human/tasks` | `200` | validation `422`, `403 principal_scope_mismatch` (supports `role_required`, `assigned_operator_id`, `assignment_state`, `overdue_only`, and `sort=created_desc|last_transition_desc|sla_due_at_asc`) |
| GET | `/v1/human/tasks/backlog` | `200` | validation `422` (supports `assignment_state` and `sort=created_desc|last_transition_desc|sla_due_at_asc`) |
| GET | `/v1/human/tasks/unassigned` | `200` | validation `422` (supports `sort=created_desc|last_transition_desc|sla_due_at_asc`) |
| GET | `/v1/human/tasks/mine` | `200` | validation `422` (supports `sort=created_desc|last_transition_desc|sla_due_at_asc`) |
| POST | `/v1/human/tasks/operators` | `200` | validation `422`, `403 principal_scope_mismatch` |
| GET | `/v1/human/tasks/operators` | `200` | validation `422`, `403 principal_scope_mismatch` |
| GET | `/v1/human/tasks/operators/{operator_id}` | `200` | `404 operator_profile_not_found` |
| POST | `/v1/human/tasks/{human_task_id}/assign` | `200` | `404 human_task_not_found`, `409 human_task_not_assignable` |
| GET | `/v1/human/tasks/{human_task_id}/assignment-history` | `200` | `404 human_task_not_found`, validation `422` (supports `event_name`, `assigned_operator_id`, and `assigned_by_actor_id`) |
| GET | `/v1/human/tasks/{human_task_id}` | `200` | `404 human_task_not_found` |
| POST | `/v1/human/tasks/{human_task_id}/claim` | `200` | `404 human_task_not_found`, `409 human_task_not_claimable` |
| POST | `/v1/human/tasks/{human_task_id}/return` | `200` | `404 human_task_not_found`, `409 human_task_not_returnable` |
| GET | `/v1/policy/decisions/recent` | `200` | n/a |
| POST | `/v1/policy/evaluate` | `200` | validation `422` |
| GET | `/v1/policy/approvals/pending` | `200` | n/a |
| GET | `/v1/policy/approvals/history` | `200` | n/a |
| POST | `/v1/policy/approvals/{approval_id}/approve` | `200` | `404 approval_not_found` |
| POST | `/v1/policy/approvals/{approval_id}/deny` | `200` | `404 approval_not_found` |
| POST | `/v1/policy/approvals/{approval_id}/expire` | `200` | `404 approval_not_found` |
| POST | `/v1/observations/ingest` | `200` | validation `422` (supports source/external/dedupe/auth/raw payload pointers) |
| GET | `/v1/observations/recent` | `200` | validation `422` |
| POST | `/v1/delivery/outbox` | `200` | validation `422` (supports idempotency keys) |
| GET | `/v1/delivery/outbox/pending` | `200` | validation `422` |
| POST | `/v1/delivery/outbox/{delivery_id}/sent` | `200` | `404 delivery_not_found` |
| POST | `/v1/delivery/outbox/{delivery_id}/failed` | `200` | `404 delivery_not_found` |
| POST | `/v1/channels/telegram/ingest` | `200` | validation `422` |
| POST | `/v1/tools/registry` | `200` | validation `422` |
| GET | `/v1/tools/registry` | `200` | validation `422` |
| GET | `/v1/tools/registry/{tool_name}` | `200` | `404 tool_not_found` |
| POST | `/v1/tools/execute` | `200` | `404 tool_not_registered:*`, `409 tool_execution_failed` |
| POST | `/v1/connectors/bindings` | `200` | validation `422` |
| GET | `/v1/connectors/bindings` | `200` | validation `422` |
| POST | `/v1/connectors/bindings/{binding_id}/status` | `200` | `404 binding_not_found` |
| POST | `/v1/tasks/contracts` | `200` | validation `422` |
| GET | `/v1/tasks/contracts` | `200` | validation `422` |
| GET | `/v1/tasks/contracts/{task_key}` | `200` | `404 task_contract_not_found` |
| POST | `/v1/plans/compile` | `200` | validation `422` |
| POST | `/v1/memory/candidates` | `200` | validation `422` |
| GET | `/v1/memory/candidates` | `200` | validation `422` |
| POST | `/v1/memory/candidates/{candidate_id}/promote` | `200` | `404 memory_candidate_not_found` |
| POST | `/v1/memory/candidates/{candidate_id}/reject` | `200` | `404 memory_candidate_not_found` |
| GET | `/v1/memory/items` | `200` | validation `422` |
| GET | `/v1/memory/items/{item_id}` | `200` | `404 memory_item_not_found` |
| POST | `/v1/memory/entities` | `200` | validation `422` |
| GET | `/v1/memory/entities` | `200` | validation `422` |
| GET | `/v1/memory/entities/{entity_id}` | `200` | `404 entity_not_found` |
| POST | `/v1/memory/relationships` | `200` | validation `422` |
| GET | `/v1/memory/relationships` | `200` | validation `422` |
| GET | `/v1/memory/relationships/{relationship_id}` | `200` | `404 relationship_not_found` |
| POST | `/v1/memory/commitments` | `200` | validation `422` |
| GET | `/v1/memory/commitments` | `200` | validation `422` |
| GET | `/v1/memory/commitments/{commitment_id}` | `200` | `404 commitment_not_found` |
| POST | `/v1/memory/authority-bindings` | `200` | validation `422` |
| GET | `/v1/memory/authority-bindings` | `200` | validation `422` |
| GET | `/v1/memory/authority-bindings/{binding_id}` | `200` | `404 authority_binding_not_found` |
| POST | `/v1/memory/delivery-preferences` | `200` | validation `422` |
| GET | `/v1/memory/delivery-preferences` | `200` | validation `422` |
| GET | `/v1/memory/delivery-preferences/{preference_id}` | `200` | `404 delivery_preference_not_found` |
| POST | `/v1/memory/follow-ups` | `200` | validation `422` |
| GET | `/v1/memory/follow-ups` | `200` | validation `422` |
| GET | `/v1/memory/follow-ups/{follow_up_id}` | `200` | `404 follow_up_not_found` |
| POST | `/v1/memory/deadline-windows` | `200` | validation `422` |
| GET | `/v1/memory/deadline-windows` | `200` | validation `422` |
| GET | `/v1/memory/deadline-windows/{window_id}` | `200` | `404 deadline_window_not_found` |
| POST | `/v1/memory/stakeholders` | `200` | validation `422` |
| GET | `/v1/memory/stakeholders` | `200` | validation `422` |
| GET | `/v1/memory/stakeholders/{stakeholder_id}` | `200` | `404 stakeholder_not_found` |
| POST | `/v1/memory/decision-windows` | `200` | validation `422` |
| GET | `/v1/memory/decision-windows` | `200` | validation `422` |
| GET | `/v1/memory/decision-windows/{decision_window_id}` | `200` | `404 decision_window_not_found` |
| POST | `/v1/memory/communication-policies` | `200` | validation `422` |
| GET | `/v1/memory/communication-policies` | `200` | validation `422` |
| GET | `/v1/memory/communication-policies/{policy_id}` | `200` | `404 communication_policy_not_found` |
| POST | `/v1/memory/follow-up-rules` | `200` | validation `422` |
| GET | `/v1/memory/follow-up-rules` | `200` | validation `422` |
| GET | `/v1/memory/follow-up-rules/{rule_id}` | `200` | `404 follow_up_rule_not_found` |
| POST | `/v1/memory/interruption-budgets` | `200` | validation `422` |
| GET | `/v1/memory/interruption-budgets` | `200` | validation `422` |
| GET | `/v1/memory/interruption-budgets/{budget_id}` | `200` | `404 interruption_budget_not_found` |

Error envelope for failures:
- `{ "error": { "code": "...", "message": "...", "details": ..., "correlation_id": "..." } }`

Auth:
- Set `EA_API_TOKEN=<token>` to require auth for all non-health routes.
- Use `Authorization: Bearer <token>` or `X-API-Token: <token>`.
- Use `X-EA-Principal-ID: <principal>` for principal-scoped connector, human-task, and memory routes; if omitted, `EA_DEFAULT_PRINCIPAL_ID` (default `local-user`) is used.
- On those routes, body/query `principal_id` remains a compatibility field only and mismatches fail with `403 principal_scope_mismatch`.

Runtime mode:
- Set `EA_RUNTIME_MODE=prod` for durable environments; the app will fail fast instead of falling back from `EA_STORAGE_BACKEND=auto` or `memory` to in-process storage.

Policy notes:
- Rewrite policy denies empty input, oversized input, and disallowed tool usage.
- Rewrite policy requires approval for explicit approval classes, long inputs, and high-risk/high-budget or external-send actions.
- `POST /v1/policy/evaluate` provides a direct HTTP path for previewing external-send approval requirements.
- Approving a paused rewrite resumes execution immediately on the current scaffold, so the session should move from `awaiting_approval` to `completed` with an artifact, receipt, and run-cost row.
- Approval-required rewrites now return `202` with `session_id`, `approval_id`, `status=awaiting_approval`, and `next_action=poll_or_subscribe` instead of a `409` error contract.
- Allowed and approved rewrites now pass through durable `execution_queue` rows first; the current API path drains that queue inline, while non-API runner roles can drain it as workers.
- The current rewrite scaffold now executes as three explicit queued steps: `step_input_prepare`, `step_policy_evaluate`, and `step_artifact_save`.
- `POST /v1/plans/compile` exposes `depends_on`, `input_keys`, and `output_keys` so plan projections show the same dependency graph the rewrite runtime now executes.
- Task-contract metadata can now add a projected `step_human_review` branch by setting `budget_policy_json.human_review_role`, `human_review_priority`, `human_review_sla_minutes`, `human_review_auto_assign_if_unique`, `human_review_desired_output_json`, `human_review_authority_required`, `human_review_why_human`, and `human_review_quality_rubric_json`; the rewrite runtime auto-creates the linked human task packet with those routing and review-contract fields when that step executes, auto-assigns a unique exact reviewer when the flag is enabled, and a returned `final_text` payload now overrides the downstream artifact-save input.
- Tool-call steps now flow through a registry-backed `ToolExecutionService`; the built-in `artifact_repository` handler emits normalized `tool.v1` receipt metadata and `tool_execution_completed` events.
- `POST /v1/tools/execute` now exposes the same execution plane directly for built-in handlers; `connector.dispatch` queues a delivery outbox row and returns normalized `tool.v1` receipt metadata.
- `connector.dispatch` execution now requires a real enabled connector binding in the caller's principal scope; foreign-principal or missing bindings fail before any outbox row is queued.
- Human review/work packets can now be attached to a session with `POST /v1/human/tasks`, claimed by an operator, and returned with structured payload/provenance while emitting `human_task_created`, `human_task_claimed`, and `human_task_returned` ledger events.
- If `resume_session_on_return=true` is set on human task creation, the linked step reopens into `waiting_human`, the session becomes `awaiting_human`, and returning the packet resumes the step back to `completed`.
- Operator queue views can filter pending human tasks by `role_required`, `assigned_operator_id`, and `overdue_only=true` so reviewers can work from targeted SLA backlogs.
- Operator queue views can also pass `sort=last_transition_desc` so the most recently reassigned, claimed, or returned ownership change surfaces first, or `sort=sla_due_at_asc` so the earliest pending SLA surfaces first in general list and backlog views.
- `POST /v1/human/tasks/operators` now persists reviewer specialization profiles (`roles`, `skill_tags`, `trust_tier`), and `GET /v1/human/tasks/backlog?operator_id=<id>` filters pending work against that metadata plus human-task review contracts.
- Human task/session payloads now compute `routing_hints_json` from active operator profiles, rubric-derived skill tags, and trust-tier requirements, including `suggested_operator_ids`, `recommended_operator_id`, and `auto_assign_operator_id` when a single exact reviewer match is available.
- `GET /v1/human/tasks/backlog` is the direct pending-queue view, while `GET /v1/human/tasks/mine?operator_id=<id>` exposes the current operator assignment queue without rebuilding filters manually.
- `POST /v1/human/tasks/{human_task_id}/assign` sets `assigned_operator_id` while the task remains `pending`, emits `human_task_assigned`, and lets operators be pre-assigned before `claim` moves the packet into active work; if the caller omits `operator_id`, the route now uses `routing_hints_json.auto_assign_operator_id` when a single exact reviewer match is available.
- `GET /v1/human/tasks/{human_task_id}/assignment-history` filters the linked execution ledger down to `human_task_created`, `human_task_assigned`, `human_task_claimed`, and `human_task_returned` transitions so reassignment provenance is queryable without scanning the entire session event list.
- `GET /v1/human/tasks/{human_task_id}/assignment-history` also accepts `event_name`, `assigned_operator_id`, and `assigned_by_actor_id` to narrow that transition chain to specific reassignment, claim, or return views for operator tooling.
- `GET /v1/rewrite/sessions/{session_id}` now also includes `human_task_assignment_history`, mirroring those task-scoped ownership transitions inline with the broader session detail payload for one-fetch operator views.
- `GET /v1/human/tasks/unassigned` and `assignment_state=assigned|unassigned` make pre-assigned pending work distinct from ownerless pending work in the backlog view.
- Human task payloads now expose `assignment_state` directly (`unassigned`, `assigned`, `claimed`, `returned`) so session projections and operator queues do not have to infer assignment from `status` plus `assigned_operator_id`.
- Human task payloads now also persist `assignment_source` so operators can tell whether ownership came from a manual choice, a route-level recommended assignment, or planner-time auto-preselection even after later claim/return transitions.
- Human task payloads now also persist `assigned_at` and `assigned_by_actor_id` so current reviewer ownership is timestamped and the last assigning actor remains visible across assignment, claim, return, and planner auto-preselection.
- Human task list/detail/session rows now also expose compact `last_transition_event_name`, `last_transition_at`, `last_transition_assignment_state`, `last_transition_operator_id`, `last_transition_assignment_source`, and `last_transition_by_actor_id` fields so operators can see the most recent ownership event (`created`, `assigned`, `claimed`, or `returned`) plus its actor/source metadata without fetching the full assignment-history chain first.

## Operator Script Help Index

Use `--help` (or `-h`) on key scripts to print usage contracts quickly:

| Script | Help Command | Purpose |
|---|---|---|
| `scripts/deploy.sh` | `bash scripts/deploy.sh --help` | Deploy runtime (standard or memory-only) |
| `scripts/db_bootstrap.sh` | `bash scripts/db_bootstrap.sh --help` | Apply kernel DB migrations |
| `scripts/db_status.sh` | `bash scripts/db_status.sh --help` | Check kernel table presence/counts |
| `scripts/db_size.sh` | `bash scripts/db_size.sh --help` | Inspect table/index/total DB size footprint |
| `scripts/db_retention.sh` | `bash scripts/db_retention.sh --help` | Dry-run/apply runtime retention pruning |
| `scripts/smoke_api.sh` | `bash scripts/smoke_api.sh --help` | Run API smoke contracts |
| `scripts/smoke_help.sh` | `bash scripts/smoke_help.sh --help` | Verify `--help` usage contracts for operator scripts |
| `scripts/smoke_postgres.sh` | `bash scripts/smoke_postgres.sh --help` | Run end-to-end Postgres-backed smoke contract |
| `scripts/test_postgres_contracts.sh` | `bash scripts/test_postgres_contracts.sh --help` | Run isolated Postgres-backed repository contract tests |
| `scripts/list_endpoints.sh` | `bash scripts/list_endpoints.sh --help` | Print live endpoint inventory from OpenAPI |
| `scripts/version_info.sh` | `bash scripts/version_info.sh --help` | Print git and milestone/version fingerprint |
| `scripts/export_openapi.sh` | `bash scripts/export_openapi.sh --help` | Export timestamped OpenAPI snapshot |
| `scripts/diff_openapi.sh` | `bash scripts/diff_openapi.sh --help` | Diff OpenAPI snapshots |
| `scripts/prune_openapi.sh` | `bash scripts/prune_openapi.sh --help` | Prune old OpenAPI snapshots |
| `scripts/operator_summary.sh` | `bash scripts/operator_summary.sh --help` | Print compact operator command inventory |
| `scripts/support_bundle.sh` | `bash scripts/support_bundle.sh --help` | Build operator support bundle |
| `scripts/archive_tasks.sh` | `bash scripts/archive_tasks.sh --help` | Archive/prune task log Done rows |
| `scripts/verify_release_assets.sh` | `bash scripts/verify_release_assets.sh --help` | Verify release artifact completeness |

Combined index:

```bash
make operator-help
```

`bash scripts/version_info.sh` now prints milestone capability-status counts and release tags in addition to git branch/revision metadata.

## CI Gate Summary

`smoke-runtime` workflow currently enforces:

- API gate bundle job:
  - `make smoke-help`
  - `make ci-local`
  - `make test-api`
  - `make verify-release-assets`
- Postgres smoke jobs:
  - `bash scripts/smoke_postgres.sh`
  - `bash scripts/test_postgres_contracts.sh`
  - `bash scripts/smoke_postgres.sh --legacy-fixture`

Milestone tracking linkage: `MILESTONE.json` maps capabilities to `planned|coded|wired|tested|released` and exposes release tags including `ci_gate_bundle`, `release_preflight_bundle`, and `docs_verify_alias`.

Local mirror command:

```bash
make ci-gates
```

Local mirror including Postgres smoke:

```bash
make ci-gates-postgres
```

Isolated Postgres repository-contract run:

```bash
make test-postgres-contracts
```

Current `scripts/test_postgres_contracts.sh` coverage includes artifacts, channel runtime, approvals, policy decisions, and task contracts.
The principal-scoped memory seed APIs are covered in-process by `tests/smoke_runtime_api.py` and over HTTP by the approved `scripts/smoke_api.sh` path that `scripts/smoke_postgres.sh` invokes.

Local mirror including legacy migration-regression smoke:

```bash
make ci-gates-postgres-legacy
```

Release ops linkage: `RELEASE_CHECKLIST.md` includes `make ci-gates` and `make ci-gates-postgres-legacy` as optional local parity commands.

## 1) Start Services

```bash
bash scripts/deploy.sh
# or
make deploy
```

Memory-only local mode (API without DB dependency):

```bash
EA_MEMORY_ONLY=1 bash scripts/deploy.sh
# or
make deploy-memory
```

With schema bootstrap in one step:

```bash
EA_BOOTSTRAP_DB=1 bash scripts/deploy.sh
# or
make deploy-bootstrap
```

## 2) Apply Kernel Migrations Manually

```bash
bash scripts/db_bootstrap.sh
# or
make bootstrap
```

Applies:
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
- `ea/schema/20260305_v0_18_stakeholders_kernel.sql`
- `ea/schema/20260305_v0_19_decision_windows_kernel.sql`
- `ea/schema/20260305_v0_20_communication_policies_kernel.sql`
- `ea/schema/20260305_v0_21_follow_up_rules_kernel.sql`
- `ea/schema/20260305_v0_22_interruption_budgets_kernel.sql`
- `ea/schema/20260305_v0_23_execution_queue_kernel.sql`
- `ea/schema/20260305_v0_24_human_tasks_kernel.sql`
- `ea/schema/20260305_v0_25_human_task_resume_kernel.sql`
- `ea/schema/20260305_v0_26_human_task_assignment_state.sql`
- `ea/schema/20260305_v0_27_human_task_review_contract.sql`
- `ea/schema/20260305_v0_28_operator_profiles_kernel.sql`
- `ea/schema/20260305_v0_29_human_task_assignment_source.sql`
- `ea/schema/20260305_v0_30_human_task_assignment_provenance.sql`

Check table presence/counts:

```bash
bash scripts/db_status.sh
# or
make db-status
```

Check table/index size footprint:

```bash
bash scripts/db_size.sh
# or
make db-size

# optional table-prefix filter
EA_DB_SIZE_TABLE_PREFIX=execution_ bash scripts/db_size.sh

# optional schema filter
EA_DB_SIZE_SCHEMA=public bash scripts/db_size.sh

# optional sort key (total|table|index)
EA_DB_SIZE_SORT_KEY=index bash scripts/db_size.sh

# optional minimum table size filter (MB)
EA_DB_SIZE_MIN_MB=25 bash scripts/db_size.sh
```

The Compose Postgres volume is `ea_pgdata`, mounted at `/var/lib/postgresql/data` inside `ea-db`.
If `/var/lib/docker/volumes/.../ea_pgdata` is large on the host, that is on-disk Postgres runtime state
(ledger, outbox, observations, memory tables, indexes), not RAM. Use `bash scripts/db_size.sh`
to attribute the footprint by table/index size before pruning or moving data.
`bash scripts/support_bundle.sh` now captures the expected volume name/mount and live `ea-db` mount inspection
by default, so support bundles can answer which host path backs `/var/lib/postgresql/data`.

Retention dry-run (default) and apply mode:

```bash
bash scripts/db_retention.sh
# or
make db-retention

# optional retention profile
EA_RETENTION_PROFILE=aggressive bash scripts/db_retention.sh

# optional per-table override
EA_RETENTION_DELIVERY_SENT_DAYS=14 bash scripts/db_retention.sh

# optional table allowlist (CSV)
EA_RETENTION_TABLES=execution_events,delivery_outbox bash scripts/db_retention.sh

# optional table skip list (CSV)
EA_RETENTION_SKIP_TABLES=observation_events,policy_decisions bash scripts/db_retention.sh

# apply deletions
bash scripts/db_retention.sh --apply
```

## 3) Health Check

```bash
curl -fsS http://localhost:${EA_HOST_PORT:-8090}/health
curl -fsS http://localhost:${EA_HOST_PORT:-8090}/health/live
curl -fsS http://localhost:${EA_HOST_PORT:-8090}/health/ready
curl -fsS http://localhost:${EA_HOST_PORT:-8090}/version
```

## 4) Rewrite + Session Audit Smoke

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/rewrite/artifact \
  -H 'content-type: application/json' \
  -d '{"text":"runbook smoke"}'
```

Use returned `artifact_id` and `execution_session_id`:

```bash
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/rewrite/artifacts/<artifact_id>"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/rewrite/receipts/<receipt_id>"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/rewrite/run-costs/<cost_id>"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/rewrite/sessions/<session_id>"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/policy/decisions/recent?session_id=<session_id>&limit=5"
```

External-send policy preview:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/policy/evaluate \
  -H 'content-type: application/json' \
  -d '{"content":"Send the board update to the distribution list.","tool_name":"connector.dispatch","action_kind":"delivery.send","channel":"email"}'
```

## 5) Observation + Delivery Smoke

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/observations/ingest \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","channel":"email","event_type":"thread.opened","payload":{"subject":"Board prep"}}'
```

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/delivery/outbox \
  -H 'content-type: application/json' \
  -d '{"channel":"slack","recipient":"U1","content":"Draft ready","metadata":{"priority":"high"}}'
```

```bash
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/observations/recent?limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/delivery/outbox/pending?limit=10"
```

## 6) Telegram Adapter Smoke

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/channels/telegram/ingest \
  -H 'content-type: application/json' \
  -d '{"update":{"message":{"chat":{"id":42},"text":"hello","message_id":7,"date":123}}}'
```

## 7) Full Smoke Script

```bash
bash scripts/smoke_api.sh
# or
make smoke-api
# or (includes help-smoke + API smoke)
make release-smoke
# postgres-backed smoke path
bash scripts/smoke_postgres.sh
# or
make smoke-postgres
# optional isolated DB name override
EA_SMOKE_DB=ea_smoke_runtime bash scripts/smoke_postgres.sh
# legacy migration-regression mode (skips API smoke)
bash scripts/smoke_postgres.sh --legacy-fixture
# or
make smoke-postgres-legacy
```

The smoke script now includes external-send policy evaluation plus a blocked-policy assertion (`403` on oversized rewrite input) and runs against an isolated smoke DB so legacy runtime data is not mutated.

## 8) Memory Candidate Promotion Smoke

For every principal-scoped connector or memory example below, send `X-EA-Principal-ID: exec-1` (or your chosen principal). If you also pass `principal_id`, it must match that request header or the runtime will return `403 principal_scope_mismatch`.

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/candidates \
  -H "X-EA-Principal-ID: exec-1" \
  -H 'content-type: application/json' \
  -d '{"category":"stakeholder_pref","summary":"CEO prefers concise updates","fact_json":{"tone":"concise"}}'
```

Promote using the returned `candidate_id`:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/candidates/<candidate_id>/promote \
  -H "X-EA-Principal-ID: exec-1" \
  -H 'content-type: application/json' \
  -d '{"reviewer":"operator","sharing_policy":"private"}'
curl -fsS -H "X-EA-Principal-ID: exec-1" "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/items?limit=10"
```

Seed semantic entities/relationships:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/entities \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","entity_type":"person","canonical_name":"Alex Executive","attributes_json":{"role":"executive"}}'
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/relationships \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","from_entity_id":"<entity_a>","to_entity_id":"<entity_b>","relationship_type":"reports_to"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/entities?limit=10&principal_id=exec-1"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/relationships?limit=10&principal_id=exec-1"
```

Principal-scoped commitments:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/commitments \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","title":"Send board follow-up","details":"Draft by Friday","status":"open","priority":"high"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/commitments?principal_id=exec-1&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/commitments/<commitment_id>?principal_id=exec-1"
```

Principal-scoped authority bindings:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/authority-bindings \
  -H "X-EA-Principal-ID: exec-1" \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","subject_ref":"assistant","action_scope":"calendar.write","approval_level":"manager","channel_scope":["email","slack"],"policy_json":{"quiet_hours_enforced":true},"status":"active"}'
curl -fsS -H "X-EA-Principal-ID: exec-1" "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/authority-bindings?principal_id=exec-1&limit=10"
curl -fsS -H "X-EA-Principal-ID: exec-1" "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/authority-bindings/<binding_id>?principal_id=exec-1"
```

If the request principal and a supplied `principal_id` disagree, the runtime now returns `403 principal_scope_mismatch` instead of silently reading another principal scope.

Principal-scoped delivery preferences:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/delivery-preferences \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","channel":"email","recipient_ref":"ceo@example.com","cadence":"urgent_only","quiet_hours_json":{"start":"22:00","end":"07:00"},"format_json":{"style":"concise"},"status":"active"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/delivery-preferences?principal_id=exec-1&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/delivery-preferences/<preference_id>?principal_id=exec-1"
```

Principal-scoped follow-ups:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/follow-ups \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","stakeholder_ref":"ceo@example.com","topic":"Board follow-up","status":"open","due_at":"2026-03-07T09:00:00+00:00","channel_hint":"email","notes":"Send summary after prep call","source_json":{"source":"manual"}}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/follow-ups?principal_id=exec-1&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/follow-ups/<follow_up_id>?principal_id=exec-1"
```

Principal-scoped deadline windows:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/deadline-windows \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","title":"Board prep delivery window","start_at":"2026-03-07T08:30:00+00:00","end_at":"2026-03-07T10:00:00+00:00","status":"open","priority":"high","notes":"Draft must be ready before board sync","source_json":{"source":"manual"}}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/deadline-windows?principal_id=exec-1&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/deadline-windows/<window_id>?principal_id=exec-1"
```

Principal-scoped stakeholders:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/stakeholders \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","display_name":"Sam Stakeholder","channel_ref":"email:sam@example.com","authority_level":"approver","importance":"high","response_cadence":"fast","tone_pref":"diplomatic","sensitivity":"confidential","escalation_policy":"notify_exec","open_loops_json":{"board_follow_up":"open"},"friction_points_json":{"scheduling":"tight"},"last_interaction_at":"2026-03-06T15:30:00+00:00","status":"active","notes":"Needs concise summaries"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/stakeholders?principal_id=exec-1&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/stakeholders/<stakeholder_id>?principal_id=exec-1"
```

Principal-scoped decision windows:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/decision-windows \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","title":"Board response decision","context":"Choose timing and channel for reply","opens_at":"2026-03-06T08:00:00+00:00","closes_at":"2026-03-06T12:00:00+00:00","urgency":"high","authority_required":"exec","status":"open","notes":"Needs decision before board prep","source_json":{"source":"manual"}}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/decision-windows?principal_id=exec-1&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/decision-windows/<decision_window_id>?principal_id=exec-1"
```

Principal-scoped communication policies:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/communication-policies \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","scope":"board_threads","preferred_channel":"email","tone":"concise_diplomatic","max_length":1200,"quiet_hours_json":{"start":"22:00","end":"07:00"},"escalation_json":{"on_high_urgency":"notify_exec"},"status":"active","notes":"Board-facing communication defaults"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/communication-policies?principal_id=exec-1&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/communication-policies/<policy_id>?principal_id=exec-1"
```

Principal-scoped follow-up rules:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/follow-up-rules \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","name":"Board reminder escalation","trigger_kind":"deadline_risk","channel_scope":["email","slack"],"delay_minutes":120,"max_attempts":3,"escalation_policy":"notify_exec","conditions_json":{"priority":"high"},"action_json":{"action":"draft_follow_up"},"status":"active","notes":"Escalate if follow-up is late"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/follow-up-rules?principal_id=exec-1&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/follow-up-rules/<rule_id>?principal_id=exec-1"
```
## 9) Script Help Smoke

```bash
bash scripts/smoke_help.sh
# or
make smoke-help
```

## 10) Export OpenAPI Snapshot

```bash
bash scripts/export_openapi.sh
# or
make openapi-export
```

Compare the latest two snapshots:

```bash
bash scripts/diff_openapi.sh
# or
make openapi-diff
```

Prune old snapshots (default keep=20):

```bash
bash scripts/prune_openapi.sh
# keep 50
bash scripts/prune_openapi.sh 50
# or
make openapi-prune
```

## 11) Optional Local Pre-Commit Hook

```bash
mkdir -p .githooks
cp .githooks/pre-commit.example .githooks/pre-commit
chmod +x .githooks/pre-commit
git config core.hooksPath .githooks
```

## 12) Print Endpoint Inventory

```bash
bash scripts/list_endpoints.sh
# or
make endpoints
```

## 13) Print Version Fingerprint

```bash
bash scripts/version_info.sh
# or
make version-info
```

## 14) Print Operator Summary

```bash
bash scripts/operator_summary.sh
# or
make operator-summary
```

The operator summary includes release smoke/readiness commands plus legacy smoke/parity shortcuts, release/support commands such as `make release-preflight` and `make support-bundle`, and task-archive shortcuts.

## 15) Generate Support Bundle

```bash
bash scripts/support_bundle.sh
# optional log tail length
SUPPORT_LOG_TAIL_LINES=500 bash scripts/support_bundle.sh
# optional: skip DB logs
SUPPORT_INCLUDE_DB=0 bash scripts/support_bundle.sh
# optional: skip API logs
SUPPORT_INCLUDE_API=0 bash scripts/support_bundle.sh
# optional: skip DB volume attribution
SUPPORT_INCLUDE_DB_VOLUME=0 bash scripts/support_bundle.sh
# optional: skip DB size snapshot
SUPPORT_INCLUDE_DB_SIZE=0 bash scripts/support_bundle.sh
# optional: DB size snapshot top-table limit
SUPPORT_DB_SIZE_LIMIT=15 bash scripts/support_bundle.sh
# optional: skip queue snapshot
SUPPORT_INCLUDE_QUEUE=0 bash scripts/support_bundle.sh
# optional: custom filename prefix
SUPPORT_BUNDLE_PREFIX=incident_42 bash scripts/support_bundle.sh
# optional: custom timestamp format
SUPPORT_BUNDLE_TIMESTAMP_FMT=%Y-%m-%dT%H%M%SZ bash scripts/support_bundle.sh
# or
make support-bundle
```

`support_bundle.sh` applies baseline redaction patterns for common secret/token/password forms.

## 16) Archive Completed Task Rows

```bash
# append Done rows to TASKS_ARCHIVE.md
bash scripts/archive_tasks.sh
# preview archive rows only
bash scripts/archive_tasks.sh --dry-run
# append + prune Done rows in TASKS_WORK_LOG.md
bash scripts/archive_tasks.sh --prune-done
# or
make tasks-archive
make tasks-archive-dry-run
make tasks-archive-prune
```

## 17) Verify Release Assets

```bash
bash scripts/verify_release_assets.sh
# or
make verify-release-assets
# docs-focused alias
make docs-verify
# docs + operator-help bundle
make release-docs
```

Use `make release-docs` as a pre-smoke documentation/usage pass before running `make release-preflight`.

Combined local readiness check:

```bash
make all-local
```

`make all-local` is a lightweight readiness pass. Use `make release-preflight` for release-stage smoke and operator checks.

Release preflight aggregate (asset checks + operator help + release smoke):

```bash
make release-preflight
```

`RELEASE_CHECKLIST.md` now includes an explicit milestone release-tag parity preflight line to validate `MILESTONE.json` release tags.

## Smoke Exit Codes

`scripts/smoke_api.sh` uses these explicit non-zero codes for contract failures:

- `11`: rewrite response missing `execution_session_id`
- `12`: policy contract mismatch (`/v1/policy/evaluate` or blocked-policy assertion)
- `13`: runtime response missing an expected resource id (delivery or memory flow)

Other transport failures (for example `curl`) return their native non-zero exit codes.
