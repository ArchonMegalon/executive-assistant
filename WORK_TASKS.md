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

18. `IN_PROGRESS` - Schema manifest drift guard for Docker E2E.
   - Deliverables:
      - introduce explicit runtime schema manifest file.
      - make `docker_e2e.sh` apply schema via manifest order.
      - add smoke to enforce e2e script references manifest (not hardcoded partial list).

## Validation Command
- Host gate: `EA_SKIP_FULL_GATES=1 bash scripts/run_v120_smoke.sh`
- Broad host gate: `EA_SKIP_FULL_GATES=1 bash scripts/run_v119_smoke.sh`
