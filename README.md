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
- `/v1/rewrite/artifacts/{artifact_id}` fetches persisted artifact content directly from the durable artifact store
- `/v1/rewrite/receipts/{receipt_id}` and `/v1/rewrite/run-costs/{cost_id}` expose direct execution proof records without requiring full session expansion
- `/v1/rewrite/sessions/{session_id}` exposes execution ledger detail (events, steps, queue items, receipts, artifacts, costs)
- `/v1/observations/ingest` and `/v1/observations/recent` provide channel-agnostic observation intake
- `/v1/delivery/outbox` endpoints provide channel-agnostic queued delivery tracking
- `/v1/delivery/outbox/{delivery_id}/failed` marks retry/dead-letter transitions with error context
- `/v1/tools/registry*` manages typed tool contracts (`tool_name`, schemas, policy metadata)
- `/v1/tools/execute` runs built-in tool handlers through the shared execution plane
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
- the principal-scoped memory seed surface is explicitly covered by both `tests/smoke_runtime_api.py` and the approved host smoke path (`scripts/smoke_api.sh` via `scripts/smoke_postgres.sh`)
- principal-scoped connector and memory routes now derive their effective principal from `X-EA-Principal-ID` or `EA_DEFAULT_PRINCIPAL_ID` instead of trusting caller-supplied body/query IDs
- rewrite execution now records `plan_compiled`, runs a typed two-step queue path (`step_input_prepare` -> `step_artifact_save`) through the execution ledger, and dispatches tool steps through a registry-backed `ToolExecutionService`
- rewrite tool receipts now carry a normalized `tool.v1` invocation contract for the built-in `artifact_repository` handler
- the built-in `connector.dispatch` handler now also runs through `ToolExecutionService` and queues durable delivery outbox rows
- `connector.dispatch` now requires an enabled connector binding that matches the request principal before `/v1/tools/execute` can queue delivery
- observation intake supports `source_id`/`external_id`/`dedupe_key` attribution and auth/raw-payload pointers
- delivery outbox supports idempotency keys plus retry/dead-letter state fields
- `/v1/channels/telegram/ingest` maps raw Telegram updates into normalized observation events
- `/v1/policy/decisions/recent` exposes persisted policy decision audit records
- `/v1/policy/evaluate` exposes direct policy checks for tool/action/channel combinations, including external-send approval branches
- `/v1/policy/approvals/*` exposes pending/history plus approve/deny/expire decision endpoints
- approving a paused rewrite now resumes execution inline and completes the artifact/ledger flow instead of stopping at a dead intermediate status
- rewrite execution now persists durable `execution_queue` rows and drains them inline for API requests before returning
- `app.runner` supports role-based startup (`EA_ROLE=api` or queue-draining worker roles)
- `app.domain.IntentSpecV3` and execution session/event models provide a typed kernel scaffold
- rewrite execution is gated by a centralized policy decision service (`policy_decision` event)

## Hardening Baseline

- app images no longer install `docker.io`
- runtime data/secrets are excluded from version control via a narrowed `.gitignore`

## Storage Backends

- `EA_RUNTIME_MODE=dev|test|prod` controls whether automatic memory fallback is allowed; `prod` fails fast instead
- `EA_STORAGE_BACKEND=postgres` forces Postgres-backed repositories (`DATABASE_URL` required)
- `EA_STORAGE_BACKEND=memory` keeps repositories in-process (dev/test convenience)
- `EA_STORAGE_BACKEND=auto` (default) attempts Postgres first, then falls back to memory in `dev`/`test`
- `EA_LEDGER_BACKEND` is still accepted as a temporary backward-compatible alias, but it is deprecated in favor of `EA_STORAGE_BACKEND`
- `EA_RUNTIME_MODE=prod` requires durable Postgres boot and rejects `memory` or `auto` degradation paths
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
- execution queue kernel migration: `ea/schema/20260305_v0_23_execution_queue_kernel.sql`

## Auth

- Set `EA_API_TOKEN=<token>` to require bearer auth on all non-health routes.
- Set `EA_DEFAULT_PRINCIPAL_ID=<principal>` to define the fallback request principal when `X-EA-Principal-ID` is omitted (default `local-user`).
- Principal-scoped connector and memory routes treat body/query `principal_id` as compatibility input only; mismatches against the request principal fail with `403 principal_scope_mismatch`.

## Policy Tuning

- `EA_APPROVAL_THRESHOLD_CHARS` sets rewrite input length requiring approval (default `5000`).
- `EA_APPROVAL_TTL_MINUTES` sets default approval request expiration window (default `120`).
- Policy decisions also consider declared tool/action metadata plus task risk and budget classes; disallowed tools fail closed with `policy_denied:tool_not_allowed`.
- `POST /v1/policy/evaluate` can dry-run external-send approval checks over HTTP without going through rewrite artifact creation.

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
Shortcut targets are available in `Makefile` (`make deploy`, `make bootstrap`, `make db-status`, `make db-size`, `make db-retention`, `make operator-summary`, `make smoke-api`, `make smoke-postgres`, `make smoke-postgres-legacy`, `make release-smoke`, `make ci-gates-postgres`, `make ci-gates-postgres-legacy`, `make all-local`, `make verify-release-assets`, `make release-docs`, `make release-preflight`).
A compact runtime surface map is documented in `ARCHITECTURE_MAP.md`.
Runnable endpoint samples are in `HTTP_EXAMPLES.http`.
Release notes are tracked in `CHANGELOG.md`.
Environment/profile recommendations are in `ENVIRONMENT_MATRIX.md`.
Current machine-readable milestone checkpoint is `MILESTONE.json`, which tracks capabilities by `planned|coded|wired|tested|released` plus separate release tags.
Gate-bundle hardening flags are tracked in `MILESTONE.json` release tags (`ci_gate_bundle`, `release_preflight_bundle`, `docs_verify_alias`).
Release preflight checklist includes milestone release-tag parity verification in `RELEASE_CHECKLIST.md`.
Release operations checklist is `RELEASE_CHECKLIST.md`.
OpenAPI snapshot export is available via `scripts/export_openapi.sh` or `make openapi-export`.
Snapshot diff is available via `scripts/diff_openapi.sh` or `make openapi-diff`.
Snapshot pruning is available via `scripts/prune_openapi.sh` or `make openapi-prune`.
Endpoint inventory can be printed via `scripts/list_endpoints.sh` or `make endpoints`.
Version fingerprint can be printed via `scripts/version_info.sh` or `make version-info`.
`scripts/version_info.sh` now also prints milestone capability-status counts and release tags from `MILESTONE.json`.
Operator summary can be printed via `scripts/operator_summary.sh` or `make operator-summary`.
The operator summary includes smoke, readiness, CI parity, release/support, and task-archive shortcuts.
`bash scripts/operator_summary.sh --help` prints the usage contract and is included in `make operator-help`.
Operator script usage index can be printed via `make operator-help`.
Endpoint/version/OpenAPI helper scripts also expose `--help` and are included in `make operator-help`.
Support bundle export is available via `scripts/support_bundle.sh` or `make support-bundle`.
Support bundles apply baseline redaction for common secret/token/password patterns.
Set `SUPPORT_INCLUDE_DB=0` to skip DB logs in support bundle generation.
Set `SUPPORT_INCLUDE_API=0` to skip API logs in support bundle generation.
Set `SUPPORT_INCLUDE_DB_VOLUME=0` to skip ea-db mount/volume attribution in support bundles.
Set `SUPPORT_INCLUDE_DB_SIZE=0` to skip DB size snapshots in support bundle generation.
Set `SUPPORT_DB_SIZE_LIMIT=<n>` to control top-table count in DB size snapshots.
Set `SUPPORT_INCLUDE_QUEUE=0` to skip queued-task snapshot in support bundles.
Set `SUPPORT_BUNDLE_PREFIX=<tag>` to customize support bundle filenames.
Set `SUPPORT_BUNDLE_TIMESTAMP_FMT=<date format>` to customize bundle timestamp formatting.
HTTP script host-port resolution details are documented at the top of `RUNBOOK.md`.
Task archive rotation is available via `scripts/archive_tasks.sh` or `make tasks-archive`.
Retention pruning dry-runs are available via `scripts/db_retention.sh` or `make db-retention` (`EA_RETENTION_PROFILE=aggressive|standard|conservative`, optional `EA_RETENTION_TABLES`/`EA_RETENTION_SKIP_TABLES` filters).
DB size inspection supports optional schema/sort/prefix/size scoping via `EA_DB_SIZE_SCHEMA=<schema>`, `EA_DB_SIZE_SORT_KEY=total|table|index`, `EA_DB_SIZE_TABLE_PREFIX=<prefix>`, and `EA_DB_SIZE_MIN_MB=<n>`.
The Compose Postgres volume is `ea_pgdata`, mounted at `/var/lib/postgresql/data` in `ea-db`; large host paths under `/var/lib/docker/volumes/.../ea_pgdata` are on-disk Postgres state, not RAM.
Support bundles now include the expected volume name/mount plus live `ea-db` mount inspection output by default, so host-disk investigations start from captured evidence instead of guesswork.
Script help contract smoke is available via `scripts/smoke_help.sh` or `make smoke-help`.
`bash scripts/smoke_help.sh --help` is included in `make operator-help`.
Release smoke aggregate is available via `make release-smoke`.
Postgres-backed smoke run is available via `scripts/smoke_postgres.sh` or `make smoke-postgres`.
Postgres-backed repository contract tests are available via `scripts/test_postgres_contracts.sh` or `make test-postgres-contracts`; the current matrix covers artifacts, channel runtime, approvals, policy decisions, and task contracts.
Legacy migration-regression smoke is available via `bash scripts/smoke_postgres.sh --legacy-fixture` or `make smoke-postgres-legacy`.
The script targets an isolated smoke database (`EA_SMOKE_DB`, default `ea_smoke_runtime`) and restores local `.env` state after the run.
Local CI-parity compile checks can be run via `make ci-local`.
One-command local CI gate bundle is available via `make ci-gates`.
Combined local API+Postgres parity run is available via `make ci-gates-postgres`.
Combined local API+Postgres legacy-migration parity run is available via `make ci-gates-postgres-legacy`.
Release asset integrity can be checked via `scripts/verify_release_assets.sh` or `make verify-release-assets`.
Docs-focused alias for the same check: `make docs-verify`.
Docs + operator help aggregate: `make release-docs`.
Release preflight aggregate is available via `make release-preflight`.
Recommended sequencing: run `make release-docs` before `make release-preflight`.
One-command local readiness check: `make all-local`.
`make all-local` is a lighter local readiness pass; use `make release-preflight` for release-stage smoke + operator checks.
CI gate sequence is documented in `RUNBOOK.md` and includes the API gate bundle (`smoke-help`, `ci-local`, `test-api`, release-asset verification), Postgres-backed smoke and repository-contract jobs (`scripts/smoke_postgres.sh`, `scripts/test_postgres_contracts.sh`), and a legacy migration-regression job (`bash scripts/smoke_postgres.sh --legacy-fixture`).
Shell script lint config is tracked in `.shellcheckrc`.
