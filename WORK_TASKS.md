# EA Work Tasks (Unattended Chain Queue)

Last updated: 2026-03-05
Owner: Codex runtime worker

## Operating Rule
- If any task below is `PENDING` or `IN_PROGRESS`, continue by executing the first such task in order.
- Do not stop on local commits; commit and immediately continue with the next task.
- Do not push from assistant runtime; operator handles pushes.
- Prefer preapproved scripts and host-only gates when escalation is not available.

## Status Legend
- `DONE`: finished and validated.
- `IN_PROGRESS`: currently being executed.
- `PENDING`: queued and ready.
- `BLOCKED`: requires external dependency/approval.

## Active Queue

1. `DONE` - Establish persistent unattended queue contract.
   - Deliverables:
     - this file with ordered work queue.
     - smoke gate enforcing queue file presence/structure.

2. `DONE` - Persist provider outcome telemetry for broker scoring.
   - Deliverables:
     - `provider_outcomes` table bootstrap + migration.
     - helper(s) to write provider success/failure outcomes from runtime steps.
     - broker scoring consumes recent outcome quality (with safe fallback).
     - smoke coverage for persistence + score influence.

3. `DONE` - Planner step execution ownership in runtime.
   - Deliverables:
     - `intent_runtime` executes through planner step contract, not ad hoc branching.
     - explicit step handling for non-travel task templates.
     - step result payload contract for artifacts/evidence.

4. `DONE` - Upgrade `typed_actions` from generic blob queue to execution-resume queue.
   - Deliverables:
     - enforce references (`session_id`, `step_id`, `approval_gate_id`) for staged actions.
     - callback paths validate references before resume.
     - smoke coverage for missing/mismatched references.

5. `DONE` - Add commitment/artifact world-model seed.
   - Deliverables:
     - bootstrap tables: `commitments`, `artifacts`, `followups`, `decision_windows`.
     - helper module for linking execution sessions to commitments/artifacts.
     - smoke for table presence + minimal lifecycle.

6. `DONE` - Add memory-candidate promotion pipeline (local-first, Teable-curated).
   - Deliverables:
     - `memory_candidates` local table + promotion status.
     - runtime emit on session finalize (bounded, policy-safe).
     - sync worker ingests approved candidates only.
     - smoke for promotion + filtering rules.
   - Progress:
     - seed schema + planner memory-candidate module + smoke gates implemented.
     - finalize-session emission + approved-candidate Teable ingestion implemented.
     - added `smoke_v1_22_memory_promotion_pipeline.py` to host/docker/CI gates.

7. `DONE` - Synthetic-user eval harness container (qa profile only).
   - Deliverables:
     - `ea-sim-user` compose profile entry (non-prod by default).
     - scenario runner for cooperative/adversarial scripts.
     - smoke for container wiring and scenario contract.
   - Progress:
      - `ea-sim-user` service added with compose `qa` profile.
      - scenario runner added (`ea/app/sim_user/runner.py`) with contract validation.
      - seeded scenarios: cooperative + adversarial.
      - added `tests/smoke_v1_22_sim_user_harness.py` and wired host/docker/CI gates.

8. `DONE` - Continue poll/scheduler decomposition.
   - Deliverables:
      - isolate command guard + auth/session + router seams further.
      - keep behavior parity with existing v1.19.3 decomposition smokes.
   - Progress:
      - extracted OAuth step-1 auth orchestration into `ea/app/auth_runtime.py`.
      - `poll_listener.py` now delegates auth flow through `_trigger_auth_flow(...)`.
      - decomposition smoke updated and passing (`smoke_v1_19_3_control_plane_decomposition.py`).

9. `DONE` - Planner-owned free-text execution handoff.
   - Deliverables:
      - move free-text runtime to execute persisted plan steps through planner runtime.
      - keep `gog_scout` as provider-backed step, not top-level control flow.
      - persist per-step outputs with stable artifact metadata.
   - Progress:
      - `planner/step_executor.py` now owns pre-step execution and `execute_intent`
        metadata/result persistence (`run_pre_execution_steps`, `execute_planned_reasoning_step`).
      - `intent_runtime.py` now delegates free-text and approved-callback
        execute paths to planner-owned step executor helpers.
      - step results now include stable metadata (`task_type`,
        `output_artifact_type`, `provider_candidates`) on `execute_intent`.

10. `DONE` - Approval runtime hardening.
   - Deliverables:
      - add explicit approval gate expiry/deadline semantics.
      - persist approval decisions with richer provenance.
      - add smoke coverage for expired/replayed approval callbacks.
   - Progress:
      - approval gates now carry deadline/provenance columns.
      - callback path blocks expired and replayed approval callbacks.
      - added dedicated smoke coverage for expired/replayed callbacks.

11. `DONE` - Route-signal intelligence seed.
   - Deliverables:
      - attach deterministic route metadata before command/intent dispatch.
      - expose intent preview (`domain`, `task_type`) for downstream routing.
      - add smoke coverage for wiring and behavior.
   - Progress:
      - added `router_signals.py` and `_ea_route_signal` attachment in `update_router.py`.
      - route signal now includes deterministic intent preview fields.
      - added `smoke_v1_22_route_signal_router.py` and wired host/docker/CI gates.

12. `DONE` - Artifact persistence for planner-owned execute_intent results.
   - Deliverables:
      - persist `chat_response` artifacts from free-text completion into `artifacts`.
      - link artifacts to execution sessions.
      - add smoke coverage for artifact creation path.
   - Progress:
      - free-text + approved-callback success paths now persist artifacts and attach
        `artifact_id` to `render_reply` step result.
      - artifact payload includes planner metadata (`task_type`,
        `output_artifact_type`, `provider_candidates`).
      - planner-step smoke expanded to assert artifact propagation.

13. `DONE` - Proactive role wiring seed.
   - Deliverables:
      - runner support for `EA_ROLE=proactive`.
      - compose service wiring for proactive lane.
      - smoke guard for role wiring.
   - Progress:
      - added `ea/app/roles/proactive.py` and runner dispatch branch.
      - added `ea-proactive` compose service behind `proactive` profile.
      - added `smoke_v1_22_proactive_role_wiring.py`.

14. `DONE` - v1.22 release/gate naming alignment.
   - Deliverables:
      - add `run_v122_smoke.sh` alias.
      - document v1.22 gate entrypoint in README/change guide.
      - keep existing v1.19/v1.20/v1.21 gates backward compatible.
   - Progress:
      - added executable alias script `scripts/run_v122_smoke.sh`.
      - updated README + change guide + gate-alias smoke to include v1.22 alias.
      - existing `run_v119_smoke.sh`/`run_v120_smoke.sh`/`run_v121_smoke.sh` remain unchanged.

15. `DONE` - Approval action pre-consume validation.
   - Deliverables:
      - validate approval-gate status before consuming typed action rows.
      - avoid consuming stale approval actions when gate already expired/decided.
      - add smoke coverage for pre-consume guard behavior.
   - Progress:
      - callback path now peeks typed action and validates gate before consume.
      - stale approval callbacks are blocked without consuming typed action rows.
      - guard smoke enforces no button-context fallback and zero consume calls for invalid gates.

16. `DONE` - Proactive runtime integration hardening.
   - Deliverables:
      - add deterministic smoke for proactive role loop tenant selection.
      - add docs/readme note for enabling `proactive` compose profile.
      - verify schema migration coverage includes proactive + approval deadline files.
   - Progress:
      - added `smoke_v1_22_proactive_runtime_integration.py`.
      - wired proactive integration smoke into host/docker/CI gates.
      - README + change guide now document proactive profile enablement.
      - docker e2e schema list includes approval deadline migration coverage.

17. `DONE` - Expand task-contract surface to full capability vocabulary.
   - Deliverables:
      - add task contracts for uncovered capability task types.
      - extend planner task templates for new task classes.
      - add smoke that enforces capability-task to task-contract coverage.
      - wire new smoke into host/docker/CI gates.
   - Progress:
      - expanded `task_registry.py` with missing task contracts.
      - extended `plan_builder.py` templates and intent task mapping.
      - added `smoke_v1_22_task_contract_surface.py`.
      - updated gate scripts/workflow + task/intent/plan smokes.

18. `DONE` - Schema manifest drift guard for Docker E2E.
   - Deliverables:
      - introduce explicit runtime schema manifest file.
      - make `docker_e2e.sh` apply schema via manifest order.
      - add smoke to enforce e2e script references manifest (not hardcoded partial list).
   - Progress:
      - added `ea/schema/runtime_manifest.txt`.
      - `scripts/docker_e2e.sh` now resolves schema files from `SCHEMA_MANIFEST`.
      - added and wired `tests/smoke_v1_22_schema_manifest_gate.py`.

19. `DONE` - Promote planner task/approval metadata to first-class execution ledger fields.
   - Deliverables:
      - add migration + bootstrap coverage for execution session/step fields.
      - persist `task_type`, `task_contract_key`, `approval_state`, `risk_class`, and budget/session metadata in `execution_sessions`.
      - persist deterministic `step_kind` and provider refs in `execution_steps`.
      - mirror approval gate decisions into `execution_sessions.approval_state`.
      - extend smoke coverage for execution store contracts/behavior.
   - Progress:
      - added migration `20260305_v1_22_execution_ledger_fields.sql` and manifest coverage.
      - bootstrap now includes new first-class execution session/step columns.
      - `create_execution_session(...)` persists task/approval/session metadata.
      - approval-gate decisions now mirror into `execution_sessions.approval_state`.
      - execution-store smokes updated for new ledger shape.

20. `DONE` - Generic skill provider-outcome source hygiene.
   - Deliverables:
      - mark deterministic preview runs as synthetic in provider outcomes.
      - avoid positive scoring drift from synthetic preview artifacts.
      - add smoke coverage for outcome source + delta.
   - Progress:
      - `skills/generic.py` now records synthetic preview outcomes with
        `source='synthetic_preview'` and `score_delta=0`.
      - added/wired `tests/smoke_v1_22_synthetic_preview_outcomes.py`.

21. `DONE` - Extract task-matcher module from intent compiler.
   - Deliverables:
      - create deterministic matcher module for domain/task/high-risk routing.
      - wire `intent_compiler.py` to call matcher module.
      - add smoke coverage for matcher behavior and compiler wiring.
   - Progress:
      - added `ea/app/planner/task_matcher.py`.
      - `intent_compiler.py` now delegates deterministic matching to task matcher.
      - added/wired `tests/smoke_v1_22_task_matcher.py`.

22. `DONE` - Planner step-graph execution seed from persisted session steps.
   - Deliverables:
      - add planner helper to read queued steps from execution ledger in order.
      - execute deterministic non-reasoning steps through step executor by ledger rows.
      - add smoke coverage for queued-step selection and deterministic execution handoff.
   - Progress:
      - added `list_queued_pre_execution_steps(...)` and
        `run_pre_execution_steps_from_ledger(...)` in `planner/step_executor.py`.
      - `intent_runtime` now prefers ledger-driven pre-step execution with
        in-memory plan fallback.
      - added/wired `tests/smoke_v1_22_step_executor_ledger_seed.py`.

23. `DONE` - Planner plan-store seed for persisted step graph access.
   - Deliverables:
      - add planner module to fetch plan steps for session ids from execution ledger.
      - expose helper for execute-step metadata resolution from persisted rows.
      - add smoke coverage for plan-store retrieval and metadata extraction behavior.
   - Progress:
      - added `ea/app/planner/plan_store.py`.
      - `step_executor` now falls back to persisted execute-step metadata.
      - added/wired `tests/smoke_v1_22_plan_store_seed.py`.

24. `DONE` - Expand step-executor pre-step coverage for remaining task templates.
   - Deliverables:
      - ensure all deterministic pre-step keys in plan templates are covered by
        step-executor pre-step set.
      - add smoke coverage for step-template/pre-step-set parity.
   - Progress:
      - expanded `_PLANNER_PRE_EXEC_STEPS` coverage for new task-template keys.
      - added/wired `tests/smoke_v1_22_pre_step_parity.py`.

25. `DONE` - Broker/runtime claim guard for provider-outcome integration.
   - Deliverables:
      - add smoke that verifies broker imports outcome-adjustment path and emits
        `recent_outcome` reason tags when adjustments are present.
      - add smoke that verifies deterministic preview execution does not emit
        positive provider score deltas.
   - Progress:
      - provider broker smoke already verifies `recent_outcome:+N` reason tags.
      - synthetic preview outcome smoke now enforces non-positive synthetic scoring.

26. `DONE` - Planner integration export surface consolidation.
   - Deliverables:
      - export matcher, plan-store, and ledger pre-step helpers from `app.planner`.
      - add smoke guard for planner package integration surface.
   - Progress:
      - expanded `ea/app/planner/__init__.py` exports for matcher/plan-store/ledger helpers.
      - added/wired `tests/smoke_v1_22_planner_exports.py`.

27. `DONE` - Planner/runtime contract drift guard expansion.
   - Deliverables:
      - add smoke asserting runtime uses ledger-first pre-step execution and
        plan-store fallback metadata path.
      - keep host gates aligned with new planner modules/functions.
   - Progress:
      - added/wired `tests/smoke_v1_22_planner_runtime_contracts.py`.
      - host/docker/CI gates now enforce planner-runtime contract wiring.

28. `DONE` - Planner metadata retrieval consolidation follow-up.
   - Deliverables:
      - standardize execute-step metadata lookup through plan-store helper paths.
      - add smoke asserting metadata fallback remains deterministic when provider
        list is absent and only provider_key is present.
   - Progress:
      - extended `smoke_v1_22_plan_store_seed.py` with provider-key-only fallback case.
      - verified deterministic metadata fallback behavior in host gates.

29. `DONE` - Execute full docker E2E gate on current queue state.
   - Deliverables:
      - run `bash scripts/docker_e2e.sh`.
      - resolve failures if runtime-safe and rerun to pass.
   - Progress:
      - fixed legacy world-model migration compatibility for preexisting
        `artifacts` table shapes (`tenant` -> `tenant_key` and required columns).
      - reran `bash scripts/docker_e2e.sh` to PASS including design/e2e/real-milestone suites.

30. `DONE` - Broad host gate verification after docker E2E pass.
   - Deliverables:
      - run `EA_SKIP_FULL_GATES=1 bash scripts/run_v119_smoke.sh`.
      - keep queue/gate/docs alignment passing after latest planner/runtime additions.
   - Progress:
      - `EA_SKIP_FULL_GATES=1 bash scripts/run_v119_smoke.sh` passed.
      - queue/gate/docs alignment remained green after planner/runtime additions.

31. `IN_PROGRESS` - Local commit + queue continuation checkpoint.
   - Deliverables:
      - commit current queue slice locally.
      - keep next queued architectural hardening item open for continued chaining.

## Validation Command
- Host gate: `EA_SKIP_FULL_GATES=1 bash scripts/run_v120_smoke.sh`
- Broad host gate: `EA_SKIP_FULL_GATES=1 bash scripts/run_v119_smoke.sh`
