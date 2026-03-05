# Tasks Work Log

Use this file as the execution queue and progress ledger.

## Queue

| ID | Priority | Task | Owner | Status | Notes |
|---|---|---|---|---|---|
| Q-039 | P3 | Add support bundle filename prefix override env (`SUPPORT_BUNDLE_PREFIX`) | codex | queued | Easier incident grouping |

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
| D-012 | P2 | Add runnable HTTP examples for all runtime endpoints | codex | done | Added `HTTP_EXAMPLES.http` |
| D-013 | P2 | Add blocked-policy smoke coverage in tests + script + runbook | codex | done | Validates `403 policy_denied:input_too_large` |
| D-014 | P2 | Add rewrite-kernel changelog | codex | done | Added `CHANGELOG.md` with milestones |
| D-015 | P2 | Add error-contract HTTP examples (`403`/`404`) | codex | done | Updated `HTTP_EXAMPLES.http` |
| D-016 | P2 | Add environment/profile backend matrix | codex | done | Added `ENVIRONMENT_MATRIX.md` |
| D-017 | P2 | Add machine-readable milestone checkpoint file | codex | done | Added `MILESTONE.json` |
| D-018 | P2 | Add release checklist for baseline shipping | codex | done | Added `RELEASE_CHECKLIST.md` |
| D-019 | P2 | Add OpenAPI export script + make target | codex | done | Added `scripts/export_openapi.sh` and `make openapi-export` |
| D-020 | P2 | Add OpenAPI diff script + make target | codex | done | Added `scripts/diff_openapi.sh` and `make openapi-diff` |
| D-021 | P3 | Add OpenAPI snapshot prune script + make target | codex | done | Added `scripts/prune_openapi.sh` and `make openapi-prune` |
| D-022 | P3 | Add API contract summary table to runbook | codex | done | Method/route/success/error snapshot in `RUNBOOK.md` |
| D-023 | P3 | Add local memory-profile env template | codex | done | Added `.env.local.example` and README quick-start note |
| D-024 | P3 | Add compose memory override + deploy-memory path | codex | done | Added `docker-compose.memory.yml` and `EA_MEMORY_ONLY=1` flow |
| D-025 | P3 | Add pre-commit hook template for local checks | codex | done | Added `.githooks/pre-commit.example` and runbook setup |
| D-026 | P3 | Add endpoint inventory script + make target | codex | done | Added `scripts/list_endpoints.sh` and `make endpoints` |
| D-027 | P3 | Add version fingerprint script + make target | codex | done | Added `scripts/version_info.sh` and `make version-info` |
| D-028 | P3 | Add operator summary script + make target | codex | done | Added `scripts/operator_summary.sh` and `make operator-summary` |
| D-029 | P3 | Add support bundle script + make target | codex | done | Added `scripts/support_bundle.sh` and `make support-bundle` |
| D-030 | P3 | Add task archive rotation helper + make targets | codex | done | Added `scripts/archive_tasks.sh` with prune option |
| D-031 | P3 | Add dry-run preview mode for task archive rotation | codex | done | Added `--dry-run` and `make tasks-archive-dry-run` |
| D-032 | P3 | Add `make ci-local` preflight target | codex | done | Chains compile + test-module syntax checks |
| D-033 | P3 | Add release asset verification script + make target | codex | done | Added `scripts/verify_release_assets.sh` and `make verify-release-assets` |
| D-034 | P3 | Add `make all-local` aggregate readiness target | codex | done | Chains `ci-local` and `verify-release-assets` |
| D-035 | P3 | Add shellcheck baseline config | codex | done | Added `.shellcheckrc` |
| D-036 | P3 | Add smoke-script explicit exit codes and runbook matrix | codex | done | Added failure codes `11/12/13` docs |
| D-037 | P3 | Add baseline support-bundle redaction patterns | codex | done | Redacts common secret/password/token forms in captured logs |
| D-038 | P3 | Add optional DB-log exclusion in support bundles | codex | done | Added `SUPPORT_INCLUDE_DB=0` support |
| D-039 | P3 | Add optional API-log exclusion in support bundles | codex | done | Added `SUPPORT_INCLUDE_API=0` support |
| D-040 | P3 | Add optional queue-snapshot exclusion in support bundles | codex | done | Added `SUPPORT_INCLUDE_QUEUE=0` support |

## Intake Template

Copy this row into **Queue** when adding work:

`| Q-XXX | P1 | <task> | <owner> | queued | <notes> |`
