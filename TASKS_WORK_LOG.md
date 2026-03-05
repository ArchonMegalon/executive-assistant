# Tasks Work Log

Use this file as the execution queue and progress ledger.

## Queue

| ID | Priority | Task | Owner | Status | Notes |
|---|---|---|---|---|---|
| Q-010 | P2 | Add HTTP collection/examples for all runtime endpoints | codex | queued | Keep samples runnable with localhost defaults |

## In Progress

| ID | Priority | Task | Owner | Status | Notes |
|---|---|---|---|---|---|
| - | - | - | - | - | - |

## Done

| ID | Priority | Task | Owner | Status | Notes |
|---|---|---|---|---|---|
| D-001 | P0 | Create rewrite baseline skeleton and harden container privileges | codex | done | Removed docker runtime package from app image |
| D-002 | P0 | Add execution ledger + policy gating + channel runtime core | codex | done | Memory + postgres-capable backends with fallback |
| D-003 | P0 | Implement persistent `policy_decisions` repository wiring and API read endpoint | codex | done | Added `v0_4` migration and `/v1/policy/decisions/recent` |
| D-004 | P1 | Add API-level smoke tests for rewrite + observations + delivery routes | codex | done | Added `tests/smoke_runtime_api.py` |
| D-005 | P1 | Add DB bootstrap script for ordered kernel migrations | codex | done | Added `scripts/db_bootstrap.sh` |
| D-006 | P1 | Add optional bootstrap chaining to deploy flow | codex | done | `EA_BOOTSTRAP_DB=1 bash scripts/deploy.sh` |
| D-007 | P1 | Add lightweight runtime operator runbook | codex | done | Added `RUNBOOK.md` and linked from README |
| D-008 | P1 | Add CI smoke job for runtime API tests | codex | done | Added `.github/workflows/smoke-runtime.yml` |
| D-009 | P2 | Add Makefile shortcuts and a full smoke script | codex | done | Added `Makefile` + `scripts/smoke_api.sh` |
| D-010 | P2 | Add DB schema status script and make target | codex | done | Added `scripts/db_status.sh` + `make db-status` |
| D-011 | P2 | Add compact architecture map for kernel surfaces | codex | done | Added `ARCHITECTURE_MAP.md` |

## Intake Template

Copy this row into **Queue** when adding work:

`| Q-XXX | P1 | <task> | <owner> | queued | <notes> |`
