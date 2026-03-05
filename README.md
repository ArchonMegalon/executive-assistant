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

# quick local memory profile
cp .env.local.example .env
EA_MEMORY_ONLY=1 bash scripts/deploy.sh
# or
make deploy-memory
```

Then open `http://localhost:8090/health`.

Operator commands are documented in `RUNBOOK.md`.
Shortcut targets are available in `Makefile` (`make deploy`, `make bootstrap`, `make db-status`, `make smoke-api`).
A compact runtime surface map is documented in `ARCHITECTURE_MAP.md`.
Runnable endpoint samples are in `HTTP_EXAMPLES.http`.
Release notes are tracked in `CHANGELOG.md`.
Environment/profile recommendations are in `ENVIRONMENT_MATRIX.md`.
Current machine-readable milestone checkpoint is `MILESTONE.json`.
Release operations checklist is `RELEASE_CHECKLIST.md`.
OpenAPI snapshot export is available via `scripts/export_openapi.sh` or `make openapi-export`.
Snapshot diff is available via `scripts/diff_openapi.sh` or `make openapi-diff`.
Snapshot pruning is available via `scripts/prune_openapi.sh` or `make openapi-prune`.
Endpoint inventory can be printed via `scripts/list_endpoints.sh` or `make endpoints`.
Version fingerprint can be printed via `scripts/version_info.sh` or `make version-info`.
Operator summary can be printed via `scripts/operator_summary.sh` or `make operator-summary`.
Support bundle export is available via `scripts/support_bundle.sh` or `make support-bundle`.
Support bundles apply baseline redaction for common secret/token/password patterns.
Set `SUPPORT_INCLUDE_DB=0` to skip DB logs in support bundle generation.
Set `SUPPORT_INCLUDE_API=0` to skip API logs in support bundle generation.
Set `SUPPORT_INCLUDE_QUEUE=0` to skip queued-task snapshot in support bundles.
Set `SUPPORT_BUNDLE_PREFIX=<tag>` to customize support bundle filenames.
Set `SUPPORT_BUNDLE_TIMESTAMP_FMT=<date format>` to customize bundle timestamp formatting.
Task archive rotation is available via `scripts/archive_tasks.sh` or `make tasks-archive`.
Local CI-parity compile checks can be run via `make ci-local`.
Release asset integrity can be checked via `scripts/verify_release_assets.sh` or `make verify-release-assets`.
One-command local readiness check: `make all-local`.
Shell script lint config is tracked in `.shellcheckrc`.
