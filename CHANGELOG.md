# Changelog

All notable changes to the rewrite-kernel baseline are documented here.

## 2026-03-05

### Added
- Execution-kernel primitives (`IntentSpecV3`, sessions/events, policy decisions, observations, delivery outbox).
- Channel-agnostic API surface:
  - rewrite/session audit
  - policy decision audit
  - observation intake/history
  - delivery outbox queue/sent/pending
  - Telegram adapter ingestion
- Milestone 0 hardening primitives:
  - app dependency container (`app.state.container`) with route-level dependency injection
  - global error envelope (`error.code/message/details/correlation_id`)
  - health split endpoints (`/health/live`, `/health/ready`) and `/version`
  - optional token auth gate for non-health routes (`EA_API_TOKEN`)
- Execution ledger v2 primitives:
  - `execution_steps` stateful step log
  - `tool_receipts` side-effect receipts
  - `run_costs` per-session cost telemetry
  - session detail projection now includes steps/receipts/artifacts/costs
- Approval workflow primitives:
  - `approval_requests` durable pending approvals
  - `approval_decisions` durable approval/deny/expire audit rows
  - policy API endpoints for pending/history + approve/deny/expire actions
- Postgres + in-memory repository backends for kernel stores.
- Kernel SQL migrations:
  - `v0_2` execution ledger
  - `v0_3` channel runtime
  - `v0_4` policy decisions
  - `v0_5` artifacts durability
  - `v0_6` execution ledger v2
  - `v0_7` approvals workflow
- Operator tooling:
  - `scripts/db_bootstrap.sh`
  - `scripts/db_status.sh`
  - `scripts/smoke_api.sh`
  - `scripts/smoke_help.sh`
  - `Makefile` shortcuts
  - `RUNBOOK.md`, `ARCHITECTURE_MAP.md`, `HTTP_EXAMPLES.http`
- CI/local gate bundle tooling and docs (`make ci-gates`, `make release-smoke`, `make release-preflight`, `make docs-verify`, `make release-docs`, script `--help` contracts).
- CI smoke workflow: `.github/workflows/smoke-runtime.yml`
- Runtime API smoke tests: `tests/smoke_runtime_api.py`

### Changed
- Container hardening: removed `docker.io` install from app images.
- Deploy flow can optionally chain DB bootstrap (`EA_BOOTSTRAP_DB=1`).
- Rewrite path now emits execution ledger events and policy audit records.
- Milestone metadata now includes CI/docs/release gate-bundle feature tags.
- Release checklist now includes explicit milestone gate-tag parity verification.
- Artifact persistence now supports durable Postgres metadata + file-backed content storage.
- Approval-required rewrite sessions now pause with `waiting_approval` steps and transition on approve/deny/expire decisions.

### Removed
- Legacy assistant runtime modules, legacy docs, and historical test packs from pre-rewrite codebase.
