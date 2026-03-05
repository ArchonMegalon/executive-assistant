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
- `/health`, `/health/live`, `/health/ready`, `/version` provide liveness/readiness/version probes
- `/v1/rewrite/artifact` creates an artifact and an execution session
- `/v1/rewrite/sessions/{session_id}` exposes execution ledger detail (events, steps, receipts, artifacts, costs)
- `/v1/observations/ingest` and `/v1/observations/recent` provide channel-agnostic observation intake
- `/v1/delivery/outbox` endpoints provide channel-agnostic queued delivery tracking
- `/v1/delivery/outbox/{delivery_id}/failed` marks retry/dead-letter transitions with error context
- `/v1/tools/registry*` manages typed tool contracts (`tool_name`, schemas, policy metadata)
- `/v1/connectors/bindings*` manages external connector bindings and status transitions
- `/v1/tasks/contracts*` manages typed task contracts used by intent compilation
- `/v1/plans/compile` emits a typed plan DSL projection from task contracts
- `/v1/memory/candidates*` stages reviewable memory candidates from runtime signals
- `/v1/memory/items*` lists promoted long-term memory items with provenance
- `/v1/memory/entities*` upserts/list/gets semantic entities for people/projects/objects
- `/v1/memory/relationships*` upserts/list/gets relationship edges between entities
- `/v1/memory/commitments*` upserts/list/gets principal-scoped commitments
- `/v1/memory/authority-bindings*` upserts/list/gets principal-scoped authority bindings
- `/v1/memory/delivery-preferences*` upserts/list/gets principal-scoped delivery preferences
- `/v1/memory/follow-ups*` upserts/list/gets principal-scoped follow-up records
- `/v1/memory/deadline-windows*` upserts/list/gets principal-scoped deadline windows
- `/v1/memory/stakeholders*` upserts/list/gets principal-scoped stakeholder profiles
- `/v1/memory/decision-windows*` upserts/list/gets principal-scoped decision windows
- `/v1/memory/communication-policies*` upserts/list/gets principal-scoped communication policies
- `/v1/memory/follow-up-rules*` upserts/list/gets principal-scoped follow-up automation rules
- `/v1/memory/interruption-budgets*` upserts/list/gets principal-scoped interruption budgets
- rewrite execution now records `plan_compiled` and executes the primary typed plan step in the ledger
- observation intake supports `source_id`/`external_id`/`dedupe_key` attribution and auth/raw-payload pointers
- delivery outbox supports idempotency keys plus retry/dead-letter state fields
- `/v1/channels/telegram/ingest` maps raw Telegram updates into normalized observation events
- `/v1/policy/decisions/recent` exposes persisted policy decision audit records
- `/v1/policy/approvals/*` exposes pending/history plus approve/deny/expire decision endpoints
- `app.runner` supports role-based startup (`EA_ROLE=api` or idle worker roles)
- `app.domain.IntentSpecV3` and execution session/event models provide a typed kernel scaffold
- rewrite execution is gated by a centralized policy decision service (`policy_decision` event)

## Hardening Baseline

- app images no longer install `docker.io`
- runtime data/secrets are excluded from version control via a narrowed `.gitignore`

## Storage Backends

- `EA_STORAGE_BACKEND=postgres` forces Postgres-backed repositories (`DATABASE_URL` required)
- `EA_STORAGE_BACKEND=memory` keeps repositories in-process (dev/test convenience)
- `EA_STORAGE_BACKEND=auto` (default) attempts Postgres first, then falls back to memory
- `EA_LEDGER_BACKEND` is still accepted as a backward-compatible alias
- baseline schema migration: `ea/schema/20260305_v0_2_execution_ledger_kernel.sql`
- channel runtime migration: `ea/schema/20260305_v0_3_channel_runtime_kernel.sql`
- policy audit migration: `ea/schema/20260305_v0_4_policy_decisions_kernel.sql`
- artifact durability migration: `ea/schema/20260305_v0_5_artifacts_kernel.sql`
- execution-ledger v2 migration: `ea/schema/20260305_v0_6_execution_ledger_v2.sql`
- approvals workflow migration: `ea/schema/20260305_v0_7_approvals_kernel.sql`
- channel runtime reliability migration: `ea/schema/20260305_v0_8_channel_runtime_reliability.sql`
- tool/connector kernel migration: `ea/schema/20260305_v0_9_tool_connector_kernel.sql`
- task-contract kernel migration: `ea/schema/20260305_v0_10_task_contracts_kernel.sql`
- memory kernel migration: `ea/schema/20260305_v0_11_memory_kernel.sql`
- entities/relationships kernel migration: `ea/schema/20260305_v0_12_entities_relationships_kernel.sql`
- commitments kernel migration: `ea/schema/20260305_v0_13_commitments_kernel.sql`
- authority bindings kernel migration: `ea/schema/20260305_v0_14_authority_bindings_kernel.sql`
- delivery preferences kernel migration: `ea/schema/20260305_v0_15_delivery_preferences_kernel.sql`
- follow-ups kernel migration: `ea/schema/20260305_v0_16_follow_ups_kernel.sql`
- deadline windows kernel migration: `ea/schema/20260305_v0_17_deadline_windows_kernel.sql`
- stakeholders kernel migration: `ea/schema/20260305_v0_18_stakeholders_kernel.sql`
- decision windows kernel migration: `ea/schema/20260305_v0_19_decision_windows_kernel.sql`
- communication policies kernel migration: `ea/schema/20260305_v0_20_communication_policies_kernel.sql`
- follow-up rules kernel migration: `ea/schema/20260305_v0_21_follow_up_rules_kernel.sql`
- interruption budgets kernel migration: `ea/schema/20260305_v0_22_interruption_budgets_kernel.sql`

## Auth

- Set `EA_API_TOKEN=<token>` to require bearer auth on all non-health routes.

## Policy Tuning

- `EA_APPROVAL_THRESHOLD_CHARS` sets rewrite input length requiring approval (default `5000`).
- `EA_APPROVAL_TTL_MINUTES` sets default approval request expiration window (default `120`).

## Quick Start

```bash
cp .env.example .env
# edit .env values
bash scripts/deploy.sh
bash scripts/db_bootstrap.sh

# or do both in one step
EA_BOOTSTRAP_DB=1 bash scripts/deploy.sh

# quick local memory profile
cp .env.local.example .env
EA_MEMORY_ONLY=1 bash scripts/deploy.sh
# or
make deploy-memory
```

Then open `http://localhost:8090/health`.

Operator commands are documented in `RUNBOOK.md`.
Shortcut targets are available in `Makefile` (`make deploy`, `make bootstrap`, `make db-status`, `make db-size`, `make db-retention`, `make smoke-api`).
A compact runtime surface map is documented in `ARCHITECTURE_MAP.md`.
Runnable endpoint samples are in `HTTP_EXAMPLES.http`.
Release notes are tracked in `CHANGELOG.md`.
Environment/profile recommendations are in `ENVIRONMENT_MATRIX.md`.
Current machine-readable milestone checkpoint is `MILESTONE.json`.
Gate-bundle hardening flags are tracked in `MILESTONE.json` feature tags (`ci_gate_bundle`, `release_preflight_bundle`, `docs_verify_alias`).
Release preflight checklist includes milestone gate-tag parity verification in `RELEASE_CHECKLIST.md`.
Release operations checklist is `RELEASE_CHECKLIST.md`.
OpenAPI snapshot export is available via `scripts/export_openapi.sh` or `make openapi-export`.
Snapshot diff is available via `scripts/diff_openapi.sh` or `make openapi-diff`.
Snapshot pruning is available via `scripts/prune_openapi.sh` or `make openapi-prune`.
Endpoint inventory can be printed via `scripts/list_endpoints.sh` or `make endpoints`.
Version fingerprint can be printed via `scripts/version_info.sh` or `make version-info`.
Operator summary can be printed via `scripts/operator_summary.sh` or `make operator-summary`.
Operator script usage index can be printed via `make operator-help`.
Support bundle export is available via `scripts/support_bundle.sh` or `make support-bundle`.
Support bundles apply baseline redaction for common secret/token/password patterns.
Set `SUPPORT_INCLUDE_DB=0` to skip DB logs in support bundle generation.
Set `SUPPORT_INCLUDE_API=0` to skip API logs in support bundle generation.
Set `SUPPORT_INCLUDE_DB_SIZE=0` to skip DB size snapshots in support bundle generation.
Set `SUPPORT_DB_SIZE_LIMIT=<n>` to control top-table count in DB size snapshots.
Set `SUPPORT_INCLUDE_QUEUE=0` to skip queued-task snapshot in support bundles.
Set `SUPPORT_BUNDLE_PREFIX=<tag>` to customize support bundle filenames.
Set `SUPPORT_BUNDLE_TIMESTAMP_FMT=<date format>` to customize bundle timestamp formatting.
HTTP script host-port resolution details are documented at the top of `RUNBOOK.md`.
Task archive rotation is available via `scripts/archive_tasks.sh` or `make tasks-archive`.
Retention pruning dry-runs are available via `scripts/db_retention.sh` or `make db-retention` (`EA_RETENTION_PROFILE=aggressive|standard|conservative`, optional `EA_RETENTION_TABLES`/`EA_RETENTION_SKIP_TABLES` filters).
DB size inspection supports optional prefix scoping via `EA_DB_SIZE_TABLE_PREFIX=<prefix>`.
Script help contract smoke is available via `scripts/smoke_help.sh` or `make smoke-help`.
Release smoke aggregate is available via `make release-smoke`.
Local CI-parity compile checks can be run via `make ci-local`.
One-command local CI gate bundle is available via `make ci-gates`.
Release asset integrity can be checked via `scripts/verify_release_assets.sh` or `make verify-release-assets`.
Docs-focused alias for the same check: `make docs-verify`.
Docs + operator help aggregate: `make release-docs`.
Release preflight aggregate is available via `make release-preflight`.
Recommended sequencing: run `make release-docs` before `make release-preflight`.
One-command local readiness check: `make all-local`.
`make all-local` is a lighter local readiness pass; use `make release-preflight` for release-stage smoke + operator checks.
CI gate sequence is documented in `RUNBOOK.md` and currently runs `smoke-help`, `ci-local`, `test-api`, and release-asset verification.
Shell script lint config is tracked in `.shellcheckrc`.
