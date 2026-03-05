# Tasks Work Log

Use this file as the active queue and progress ledger for rewrite slices.

## Usage

1. Add all new work to **Queue** with the next `Q-XXX` ID.
2. Move an item to **In Progress** when execution starts.
3. Move blocked work to **Blocked** with a concrete blocker in `Notes`.
4. Move completed work to **Done** and convert the ID to `D-XXX`.

## Queue

| ID | Priority | Task | Owner | Status | Notes |
|---|---|---|---|---|---|
| Q-044 | P2 | Keep queue log current as slices are added/closed | codex | queued | Use this file as the default intake point for new tasks |
| Q-135 | P0 | Continue Milestone 5 memory layer (`interruption_budgets` seed table + API stubs + principal scoping) | codex | queued | Chain after follow-up-rules slice commit |

## In Progress

| ID | Priority | Task | Owner | Status | Notes |
|---|---|---|---|---|---|
| - | - | - | - | - | - |

## Blocked

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
| D-041 | P3 | Add support bundle filename prefix override | codex | done | Added `SUPPORT_BUNDLE_PREFIX` support |
| D-042 | P3 | Add support bundle timestamp-format override | codex | done | Added `SUPPORT_BUNDLE_TIMESTAMP_FMT` support |
| D-043 | P3 | Document host-port resolution for runtime scripts | codex | done | Added ordering note to top of `RUNBOOK.md` |
| D-044 | P2 | Create queue-first work-log format for rewrite slices | codex | done | Added usage rules + blocked lane + queue intake emphasis |
| D-045 | P3 | Add script-level help output for `support_bundle.sh` | codex | done | Added `--help` with env var contract |
| D-046 | P3 | Add script-level help output for archive/verify script pair | codex | done | Added `--help` to `archive_tasks.sh` and `verify_release_assets.sh` |
| D-047 | P3 | Add runbook script-help index section | codex | done | Added quick `--help` command table for key operator scripts |
| D-048 | P3 | Add aggregate operator-help make target | codex | done | Added `make operator-help` to print key script help outputs |
| D-049 | P3 | Add README entry for operator-help index | codex | done | Documented `make operator-help` in quick operator references |
| D-050 | P3 | Add release-asset docs linkage checks for operator-help index | codex | done | Verifies README and RUNBOOK contain help-index references |
| D-051 | P3 | Add runbook quick command for `make operator-help` | codex | done | Added combined index command under script-help section |
| D-052 | P3 | Add script-help smoke checker and local make target | codex | done | Added `scripts/smoke_help.sh`, `make smoke-help`, and `ci-local` hook |
| D-053 | P3 | Run script-help smoke in CI workflow | codex | done | Added `make smoke-help` step to `smoke-runtime` workflow |
| D-054 | P3 | Add release checklist step for script-help smoke | codex | done | Added `make smoke-help` to release smoke checklist |
| D-055 | P3 | Add release checklist operator-help spot-check | codex | done | Added `make operator-help` spot-check line to smoke checklist |
| D-056 | P3 | Add release-smoke make target and docs references | codex | done | Added `make release-smoke` and linked in README/RUNBOOK/checklist |
| D-057 | P3 | Add release-asset check for runbook smoke-help reference | codex | done | Verifies RUNBOOK includes `scripts/smoke_help.sh` usage path |
| D-058 | P3 | Add release-asset check for README release-smoke reference | codex | done | Verifies README includes `make release-smoke` usage path |
| D-059 | P3 | Add CI release-asset verification step | codex | done | Workflow now runs `make verify-release-assets` after runtime tests |
| D-060 | P3 | Add CI ci-local parity gate | codex | done | Workflow now runs `make ci-local` after dependency install |
| D-061 | P3 | Add runbook CI gate summary | codex | done | Documented smoke-runtime workflow gate sequence in RUNBOOK |
| D-062 | P3 | Add README CI gate sequence note | codex | done | Added concise gate summary to entrypoint documentation |
| D-063 | P3 | Add release checklist CI gate bundle preflight line | codex | done | Added explicit CI gate bundle requirement in preflight section |
| D-064 | P3 | Add release-asset guard for checklist CI gate bundle line | codex | done | Verifies `RELEASE_CHECKLIST.md` keeps CI gate bundle preflight note |
| D-065 | P3 | Add local CI gate aggregator target and docs | codex | done | Added `make ci-gates` and linked it in README/RUNBOOK |
| D-066 | P3 | Refactor CI workflow to use ci-gates target | codex | done | Workflow now runs `make ci-gates` as a single gate bundle step |
| D-067 | P3 | Add release checklist ci-gates parity line | codex | done | Added optional local `make ci-gates` preflight check |
| D-068 | P3 | Add release-asset guard for checklist ci-gates line | codex | done | Verifies `RELEASE_CHECKLIST.md` includes `make ci-gates` guidance |
| D-069 | P3 | Add ci-gates and help-smoke visibility to changelog | codex | done | Captured new gate bundle/tooling in release history notes |
| D-070 | P3 | Add ci-gates mention to release checklist smoke section | codex | done | Added optional `make ci-gates` line beside smoke checklist commands |
| D-071 | P3 | Add release-asset guard for changelog ci-gates note | codex | done | Verifies `CHANGELOG.md` retains ci-gates visibility entry |
| D-072 | P3 | Add runbook release checklist ci-gates linkage note | codex | done | Added explicit runbook cross-link to checklist `make ci-gates` guidance |
| D-073 | P3 | Add release-asset guard for runbook release linkage note | codex | done | Verifies RUNBOOK keeps release-ops cross-link wording |
| D-074 | P3 | Add release-asset guard for CI ci-gates usage | codex | done | Verifies workflow keeps `make ci-gates` as gate bundle command |
| D-075 | P3 | Add Makefile comment for ci-gates purpose | codex | done | Clarified local/CI gate parity intent near target definition |
| D-076 | P3 | Add release-preflight aggregate target and docs linkage | codex | done | Added `make release-preflight` and linked in README/RUNBOOK/checklist |
| D-077 | P3 | Add release-asset guards for release-preflight doc references | codex | done | Verifies README/RUNBOOK/RELEASE_CHECKLIST retain `make release-preflight` |
| D-078 | P3 | Add changelog mention for release-preflight command | codex | done | Captured new aggregate release command in history notes |
| D-079 | P3 | Add release-asset guard for changelog release-preflight note | codex | done | Verifies release notes keep `make release-preflight` visibility |
| D-080 | P3 | Add README note differentiating all-local vs release-preflight | codex | done | Clarified lighter readiness pass vs release-stage preflight bundle |
| D-081 | P3 | Add release-asset guard for README all-local/release-preflight note | codex | done | Verifies command-scope differentiation remains documented |
| D-082 | P3 | Add RUNBOOK note differentiating all-local vs release-preflight | codex | done | Clarified lightweight readiness vs release-stage aggregate in runbook |
| D-083 | P3 | Add release-asset guard for RUNBOOK all-local/release-preflight note | codex | done | Verifies runbook keeps command-scope differentiation wording |
| D-084 | P3 | Add docs-verify make alias and README mention | codex | done | Added `make docs-verify` alias for release asset/doc verification |
| D-085 | P3 | Add release-asset guard for README docs-verify alias | codex | done | Verifies entry docs retain `make docs-verify` alias reference |
| D-086 | P3 | Add RUNBOOK mention for docs-verify alias | codex | done | Added docs-focused alias line in verification command section |
| D-087 | P3 | Add release-asset guard for RUNBOOK docs-verify alias | codex | done | Verifies runbook retains `make docs-verify` reference |
| D-088 | P3 | Add changelog mention for docs-verify alias | codex | done | Captured docs verification alias in gate tooling notes |
| D-089 | P3 | Add release-asset guard for changelog docs-verify note | codex | done | Verifies release notes retain `make docs-verify` alias visibility |
| D-090 | P3 | Add release checklist docs-verify parity line | codex | done | Added optional `make docs-verify` preflight line |
| D-091 | P3 | Add release-asset guard for checklist docs-verify line | codex | done | Verifies `RELEASE_CHECKLIST.md` retains docs-verify parity guidance |
| D-092 | P3 | Add release-docs aggregate target and docs references | codex | done | Added `make release-docs` and linked in README/RUNBOOK/checklist |
| D-093 | P3 | Add release-asset guards for release-docs references | codex | done | Verifies README/RUNBOOK/RELEASE_CHECKLIST retain `make release-docs` |
| D-094 | P3 | Add changelog mention for release-docs bundle | codex | done | Captured docs+usage parity bundle in gate tooling notes |
| D-095 | P3 | Add release-asset guard for changelog release-docs note | codex | done | Verifies release notes retain `make release-docs` alias visibility |
| D-096 | P3 | Add RUNBOOK pre-smoke guidance for release-docs | codex | done | Added sequencing note: `release-docs` before `release-preflight` |
| D-097 | P3 | Add release-asset guard for runbook release-docs sequencing note | codex | done | Verifies runbook retains pre-smoke sequencing guidance |
| D-098 | P3 | Add README sequencing note for release-docs then release-preflight | codex | done | Entry docs now mirror runbook pre-smoke sequencing guidance |
| D-099 | P3 | Add release-asset guard for README release-docs sequencing note | codex | done | Verifies entry docs retain release-docs sequencing guidance |
| D-100 | P3 | Add milestone metadata for gate-bundle hardening | codex | done | Added ci/docs/release gate feature tags to `MILESTONE.json` |
| D-101 | P3 | Add release-asset guard for milestone gate feature tags | codex | done | Verifies `MILESTONE.json` retains gate-bundle feature annotations |
| D-102 | P3 | Add changelog note for milestone gate-bundle tags | codex | done | Recorded milestone metadata expansion in changelog `Changed` section |
| D-103 | P3 | Add release-asset guard for changelog milestone-tag note | codex | done | Verifies changelog keeps milestone gate-tag visibility line |
| D-104 | P3 | Add README pointer for milestone gate-bundle tags | codex | done | Added feature-tag pointer near `MILESTONE.json` entry doc reference |
| D-105 | P3 | Add release-asset guard for README milestone gate-tag pointer | codex | done | Verifies entry docs retain milestone gate-bundle feature pointer |
| D-106 | P3 | Add RUNBOOK milestone gate-tag linkage note | codex | done | Linked CI gate summary section to `MILESTONE.json` feature tags |
| D-107 | P3 | Add release-asset guard for RUNBOOK milestone gate-tag linkage | codex | done | Verifies runbook retains milestone feature-tag linkage guidance |
| D-108 | P3 | Add release checklist milestone gate-tag parity line | codex | done | Added explicit milestone tag verification note in preflight checklist |
| D-109 | P3 | Add release-asset guard for checklist milestone gate-tag line | codex | done | Verifies checklist keeps milestone tag parity guidance |
| D-110 | P3 | Add changelog line for checklist milestone gate-tag verification | codex | done | Recorded checklist milestone parity update in changelog `Changed` section |
| D-111 | P3 | Add release-asset guard for changelog checklist milestone-tag line | codex | done | Verifies changelog keeps checklist milestone parity visibility |
| D-112 | P3 | Add README note for checklist milestone parity verification | codex | done | Entry docs now highlight checklist milestone gate-tag verification |
| D-113 | P3 | Add release-asset guard for README checklist milestone parity note | codex | done | Verifies entry docs keep checklist milestone parity guidance visible |
| D-114 | P3 | Add RUNBOOK note for checklist milestone parity preflight line | codex | done | Added runbook linkage to checklist milestone-tag preflight validation |
| D-115 | P3 | Add release-asset guard for runbook checklist milestone parity note | codex | done | Verifies runbook/checklist milestone parity linkage remains documented |
| D-116 | P0 | Complete Milestone 0 kernel hardening pass | codex | done | Added DI container, error envelope, auth gate, liveness/readiness/version, durable artifact repo + `v0_5`, and expanded test scaffolding |
| D-117 | P0 | Complete Milestone 1 ledger v2 foundation | codex | done | Added steps/receipts/costs repositories + `v0_6` migration + session projection updates |
| D-118 | P0 | Complete Milestone 2 approval workflow and decision API | codex | done | Added `approval_requests`/`approval_decisions` repositories + `v0_7`, approval endpoints, session transition wiring, and approval smoke coverage |
| D-119 | P0 | Complete Milestone 3 reliability primitives for observations/outbox | codex | done | Added `v0_8`, observation dedupe/attribution fields, delivery idempotency/retry/dead-letter fields, and API route/test updates |
| D-120 | P0 | Complete Milestone 3 tool/connector kernel slice | codex | done | Added `v0_9`, tool registry + connector binding repositories/services/routes, and smoke/unit coverage |
| D-121 | P0 | Complete Milestone 4 task-contract kernel slice | codex | done | Added `v0_10`, task-contract repositories/service/routes, rewrite intent compilation via contracts, and coverage |
| D-122 | P0 | Complete Milestone 4 planner DSL compile slice | codex | done | Added planner service, `/v1/plans/compile`, typed plan step models, and contract-driven plan test coverage |
| D-123 | P0 | Complete Milestone 4 plan-step execution integration slice | codex | done | Orchestrator now executes with compiled plan metadata, emits `plan_compiled`, and persists plan-step context in steps/receipts |
| D-124 | P0 | Start Milestone 5 memory kernel (`memory_candidates` + `memory_items` + promotion endpoint seed) | codex | done | Added `v0_11`, memory runtime repositories/services/routes, smoke + unit coverage, and operator/docs updates |
| D-125 | P0 | Continue Milestone 5 memory layer (`entities` + `relationships` seed tables and API stubs) | codex | done | Added `v0_12`, semantic entity/relationship repositories + API stubs, and smoke/unit coverage updates |
| D-126 | P0 | Continue Milestone 5 memory layer (`commitments` seed table + API stubs + principal scoping) | codex | done | Added `v0_13`, commitment repositories + API stubs, and principal-scoped list/get behavior with test coverage |
| D-127 | P0 | Continue Milestone 5 memory layer (`authority_bindings` seed table + API stubs + principal scoping) | codex | done | Added `v0_14`, authority-binding repositories + API stubs, and principal-scoped list/get behavior with test coverage |
| D-128 | P0 | Continue Milestone 5 memory layer (`delivery_preferences` seed table + API stubs + principal scoping) | codex | done | Added `v0_15`, delivery-preference repositories + API stubs, and principal-scoped list/get behavior with test coverage |
| D-129 | P0 | Continue Milestone 5 memory layer (`follow_ups` seed table + API stubs + principal scoping) | codex | done | Added `v0_16`, follow-up repositories + API stubs, and principal-scoped list/get behavior with test coverage |
| D-130 | P0 | Continue Milestone 5 memory layer (`deadline_windows` seed table + API stubs + principal scoping) | codex | done | Added `v0_17`, deadline-window repositories + API stubs, and principal-scoped list/get behavior with test coverage |
| D-131 | P0 | Continue Milestone 5 memory layer (`stakeholders` seed table + API stubs + principal scoping) | codex | done | Added `v0_18`, stakeholder repositories + API stubs, and principal-scoped list/get behavior with test coverage |
| D-132 | P0 | Continue Milestone 5 memory layer (`decision_windows` seed table + API stubs + principal scoping) | codex | done | Added `v0_19`, decision-window repositories + API stubs, and principal-scoped list/get behavior with test coverage |
| D-133 | P0 | Continue Milestone 5 memory layer (`communication_policies` seed table + API stubs + principal scoping) | codex | done | Added `v0_20`, communication-policy repositories + API stubs, and principal-scoped list/get behavior with test coverage |
| D-134 | P0 | Continue Milestone 5 memory layer (`follow_up_rules` seed table + API stubs + principal scoping) | codex | done | Added `v0_21`, follow-up-rule repositories + API stubs, and principal-scoped list/get behavior with test coverage |

## Intake Template

Copy this row into **Queue** when adding work:

`| Q-XXX | P1 | <task> | <owner> | queued | <notes> |`
