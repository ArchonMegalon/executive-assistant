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
- Postgres + in-memory repository backends for kernel stores.
- Kernel SQL migrations:
  - `v0_2` execution ledger
  - `v0_3` channel runtime
  - `v0_4` policy decisions
- Operator tooling:
  - `scripts/db_bootstrap.sh`
  - `scripts/db_status.sh`
  - `scripts/smoke_api.sh`
  - `Makefile` shortcuts
  - `RUNBOOK.md`, `ARCHITECTURE_MAP.md`, `HTTP_EXAMPLES.http`
- CI smoke workflow: `.github/workflows/smoke-runtime.yml`
- Runtime API smoke tests: `tests/smoke_runtime_api.py`

### Changed
- Container hardening: removed `docker.io` install from app images.
- Deploy flow can optionally chain DB bootstrap (`EA_BOOTSTRAP_DB=1`).
- Rewrite path now emits execution ledger events and policy audit records.

### Removed
- Legacy assistant runtime modules, legacy docs, and historical test packs from pre-rewrite codebase.
