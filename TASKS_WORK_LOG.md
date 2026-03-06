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
| Q-179 | P1 | Add a real connector/tool handler path beyond `artifact_repository`, starting with a registry-backed `connector.dispatch` execution slice | codex | queued | The runtime now has a reusable tool execution plane, but only the built-in artifact persistence handler is wired into it |

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
| D-178 | P1 | Promote the rewrite step-handler scaffold into a reusable tool-execution service with registry-backed handlers and normalized invocation contracts | codex | done | Rewrite tool-call steps now execute through `ToolExecutionService`, the built-in `artifact_repository` handler is registry-backed, and receipts expose a normalized `tool.v1` invocation contract |
| D-177 | P1 | Replace hardcoded `artifact_repository`-only execution with a typed step-handler/tool-execution gateway | codex | done | Rewrite planning/execution now uses `step_input_prepare` and `step_artifact_save` handlers with sequential queue execution instead of a single hardcoded artifact-save step |
| D-176 | P1 | Derive principal context from auth/middleware instead of caller-supplied fields on normal user routes | codex | done | Principal-scoped connector and memory routes now derive request scope from `X-EA-Principal-ID`/`EA_DEFAULT_PRINCIPAL_ID`, reject mismatched caller-supplied principal IDs with `403 principal_scope_mismatch`, and hide foreign connector status updates |
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
| D-135 | P0 | Continue Milestone 5 memory layer (`interruption_budgets` seed table + API stubs + principal scoping) | codex | done | Added `v0_22`, interruption-budget repositories + API stubs, and principal-scoped list/get behavior with test coverage |
| D-136 | P0 | Continue kernel operations hardening (`db_size.sh` table/index size visibility + docs/runbook linkage) | codex | done | Added `scripts/db_size.sh`, `make db-size`, script-help/asset coverage, and runbook/readme/operator linkage |
| D-137 | P0 | Continue kernel operations hardening (`db_retention.sh` archival/prune baseline for runtime tables) | codex | done | Added dry-run/apply retention script, `make db-retention`, and operator docs/help/asset verification wiring |
| D-138 | P0 | Continue kernel operations hardening (support-bundle optional DB-size snapshot hook + docs linkage) | codex | done | Added support-bundle DB-size snapshot toggles/limits and updated operator docs + milestone/task tracking |
| D-139 | P0 | Continue kernel operations hardening (`db_retention.sh` table policy profile presets + docs contract) | codex | done | Added retention profile presets (`aggressive|standard|conservative`) with per-table day-window overrides and docs/milestone linkage |
| D-140 | P1 | Continue kernel ops hardening (`db_retention.sh` table whitelist/skip list controls + docs contract) | codex | done | Added retention table allowlist/skip-list filters and documented scoped retention runs in README/RUNBOOK/changelog |
| D-141 | P1 | Continue kernel ops hardening (`db_size.sh` table prefix filter + docs contract) | codex | done | Added optional `EA_DB_SIZE_TABLE_PREFIX` filter with validation and docs/milestone/task-log updates |
| D-142 | P1 | Continue kernel ops hardening (`db_size.sh` min-size threshold filter + docs contract) | codex | done | Added optional `EA_DB_SIZE_MIN_MB` filter and documented threshold-based DB size views in README/RUNBOOK/changelog |
| D-143 | P1 | Continue kernel ops hardening (`db_size.sh` schema filter + docs contract) | codex | done | Added optional `EA_DB_SIZE_SCHEMA` filter for scoped DB-size diagnostics and updated docs/milestone/task-log tracking |
| D-144 | P1 | Continue kernel ops hardening (`db_size.sh` sort-key selector + docs contract) | codex | done | Added optional `EA_DB_SIZE_SORT_KEY` selector (`total|table|index`) with validation and docs/milestone tracking updates |
| D-145 | P1 | Add local Postgres-backed smoke contract script + docs wiring | codex | done | Added `scripts/smoke_postgres.sh`, make target/operator linkage, and docs/milestone references for Postgres e2e smoke path |
| D-146 | P1 | Add CI job for Postgres-backed smoke script (`make smoke-postgres`) | codex | done | Workflow now runs `scripts/smoke_postgres.sh` in dedicated `smoke-runtime-postgres` job and docs track the expanded CI gate path |
| D-147 | P1 | Add local parity aggregate target for API+Postgres smoke (`make ci-gates-postgres`) | codex | done | Added combined local gate target, checklist/docs references, and release-asset guard for `ci-gates-postgres` parity line |
| D-148 | P0 | Harden Postgres smoke compatibility against legacy host volumes | codex | done | `v0_6` supports UUID/TEXT FK compatibility; `v0_7` upgrades legacy approval table variants in place; `scripts/smoke_postgres.sh` uses isolated smoke DB + env-template fallback + readiness retries |
| D-149 | P1 | Add legacy migration-regression Postgres smoke mode and CI/local parity wiring | codex | done | Added `--legacy-fixture` validation mode, `smoke-runtime-postgres-legacy` workflow job, `make smoke-postgres-legacy`/`make ci-gates-postgres-legacy`, and release-asset/doc tracking |
| D-150 | P1 | Add migration-regression contract coverage for legacy UUID/approval schema upgrades | codex | done | Added contract tests for legacy fixture smoke wiring, CI job presence, and `v0_6`/`v0_7` compatibility logic; verified legacy smoke upgrades cleanly |
| D-151 | P3 | Add operator-summary visibility for legacy Postgres smoke/parity commands | codex | done | Updated operator summary output, README/RUNBOOK references, release-asset guards, and script contract coverage for legacy smoke shortcuts |
| D-152 | P3 | Add release/support command visibility to operator summary | codex | done | Operator summary now includes release verification, preflight, operator-help, and support-bundle shortcuts with docs/guard/test coverage |
| D-153 | P3 | Add release-smoke and all-local visibility to operator summary | codex | done | Operator summary now includes readiness/release aggregate shortcuts with docs, release-asset guards, and contract coverage |
| D-154 | P3 | Add operator-summary help contract and include it in help-smoke/operator-help | codex | done | Added `--help` to `scripts/operator_summary.sh`, wired it into `make operator-help` and `scripts/smoke_help.sh`, and extended docs/guards/contracts |
| D-155 | P3 | Add help contracts for endpoint/version/OpenAPI helper scripts | codex | done | Added `--help` to endpoint/version/OpenAPI scripts, wired them into `make operator-help` + `scripts/smoke_help.sh`, and extended docs/guards/contracts |
| D-156 | P3 | Add smoke-help help contract and include it in operator-help | codex | done | Added `--help` to `scripts/smoke_help.sh`, included it in `make operator-help`, and extended docs/guards/contracts |
| D-157 | P3 | Add task-archive shortcut visibility to operator summary | codex | done | Operator summary now includes archive/prune/dry-run commands with docs, release-asset guards, and contract coverage |
| D-158 | P1 | Canonicalize storage backend env contract and deprecate `EA_LEDGER_BACKEND` explicitly | codex | done | Added explicit deprecation warnings in settings, moved docs/env matrix to `EA_STORAGE_BACKEND`, removed alias use from smoke tests, and added release-asset coverage |
| D-159 | P1 | Deepen policy decision inputs beyond rewrite-length guardrails | codex | done | Policy now considers tool/action/channel/risk/budget metadata, denies disallowed tools, and aligns rewrite contracts/examples/tests on `artifact_repository` |
| D-160 | P1 | Add stronger Postgres-backed CI/test coverage beyond smoke-only flows | codex | done | Added isolated Postgres repository contract tests, `scripts/test_postgres_contracts.sh`, `make test-postgres-contracts`, and a matching GitHub Actions job |
| D-161 | P2 | Add operator-facing DB size/pgdata explanation tests and docs parity | codex | done | `db_size.sh`, README, and RUNBOOK now explain that `ea_pgdata` is the on-disk Postgres volume at `/var/lib/postgresql/data`, not RAM, with verifier/test coverage |
| D-162 | P2 | Rework milestone state semantics from flat features to implementation status | codex | done | `MILESTONE.json` now uses planned/coded/wired/tested/released capability statuses plus separate release tags, and docs/checks now point to release-tag parity instead of flat feature bags |
| D-163 | P2 | Add focused rewrite API coverage for the disallowed-tool policy branch | codex | done | Added a dedicated rewrite-route test asserting `policy_denied:tool_not_allowed` when task contracts exclude the executing tool |
| D-164 | P2 | Add script-backed Docker-volume attribution checks for `ea_pgdata` support bundles | codex | done | Support bundles now capture expected pgdata volume/mount details plus live `ea-db` mount inspection output, with docs and verifier coverage |
| D-165 | P2 | Surface milestone capability-status summary in `version_info.sh` for quick operator truth checks | codex | done | `version_info.sh` now prints milestone status counts and release tags from `MILESTONE.json`, with docs and operator-contract coverage |
| D-166 | P2 | Remove remaining default env-template/checklist drift toward deprecated `EA_LEDGER_BACKEND` | codex | done | Updated env templates, release checklist, and smoke-postgres env rewriting to prefer `EA_STORAGE_BACKEND` while keeping runtime alias compatibility in code |
| D-167 | P2 | Expose an HTTP path that exercises policy approval for external-send actions | codex | done | Added `POST /v1/policy/evaluate` plus API/docs/milestone coverage so external-send approval logic is reachable without rewrite artifact execution |
| D-168 | P2 | Extend approved smoke-script coverage to assert external-send policy evaluation | codex | done | `scripts/smoke_api.sh` now validates `/v1/policy/evaluate`, and the preapproved `scripts/smoke_postgres.sh` host path inherits that check automatically |
| D-169 | P1 | Expand Postgres repository contract matrix beyond artifact/channel runtime surfaces | codex | done | Added approvals/policy-decisions/task-contracts Postgres integration tests, wired them into `scripts/test_postgres_contracts.sh`, updated milestone/docs, and queued the next verification slice |
| D-170 | P1 | Promote principal-scoped memory seed APIs from wired to tested with explicit CI/assertion coverage | codex | done | Tightened milestone/release-asset/operator-contract checks around the existing memory smoke surface, promoted the milestone capability to `tested`, and queued direct artifact lookup as the next slice |
| D-171 | P1 | Expose direct artifact lookup over the durable artifact repository with API/docs/smoke coverage | codex | done | Added `GET /v1/rewrite/artifacts/{artifact_id}`, extended API/docs/release-asset coverage, and folded the fetch path into the approved host smoke run |
| D-172 | P1 | Expose direct tool-receipt and run-cost lookup APIs with docs/smoke coverage | codex | done | Added direct rewrite receipt/run-cost fetch routes, extended smoke/docs/milestone coverage, and queued approval-request lookup as the next slice |
| D-173 | P1 | Make approval decisions resume rewrite execution to completion | codex | done | Persisted resumable rewrite input on the waiting step, resumed approved rewrites inline to artifact/receipt/run-cost completion, extended host smoke coverage, and queued the durable execution-queue slice next |
| D-174 | P1 | Introduce a durable execution queue and inline worker path for resumable step execution | codex | done | Added execution-queue schema/repository support, routed rewrite execution through leased queue rows, exposed queue state in session projections, taught non-API runner roles to drain queued work, and queued runtime-mode hardening next |
| D-175 | P1 | Enforce explicit runtime-mode storage policy so production cannot silently fall back to memory | codex | done | Added `EA_RUNTIME_MODE=prod` fail-fast storage guards across runtime bootstrap paths, exposed the contract in docs/env guidance, extended the approved Postgres smoke path with a prod misconfiguration failure check, and queued principal-context hardening next |

## Intake Template

Copy this row into **Queue** when adding work:

`| Q-XXX | P1 | <task> | <owner> | queued | <notes> |`
