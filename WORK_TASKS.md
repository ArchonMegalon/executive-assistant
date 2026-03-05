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

4. `IN_PROGRESS` - Upgrade `typed_actions` from generic blob queue to execution-resume queue.
   - Deliverables:
     - enforce references (`session_id`, `step_id`, `approval_gate_id`) for staged actions.
     - callback paths validate references before resume.
     - smoke coverage for missing/mismatched references.

5. `PENDING` - Add commitment/artifact world-model seed.
   - Deliverables:
     - bootstrap tables: `commitments`, `artifacts`, `followups`, `decision_windows`.
     - helper module for linking execution sessions to commitments/artifacts.
     - smoke for table presence + minimal lifecycle.

6. `PENDING` - Add memory-candidate promotion pipeline (local-first, Teable-curated).
   - Deliverables:
     - `memory_candidates` local table + promotion status.
     - runtime emit on session finalize (bounded, policy-safe).
     - sync worker ingests approved candidates only.
     - smoke for promotion + filtering rules.

7. `PENDING` - Synthetic-user eval harness container (qa profile only).
   - Deliverables:
     - `ea-sim-user` compose profile entry (non-prod by default).
     - scenario runner for cooperative/adversarial scripts.
     - smoke for container wiring and scenario contract.

8. `PENDING` - Continue poll/scheduler decomposition.
   - Deliverables:
     - isolate command guard + auth/session + router seams further.
     - keep behavior parity with existing v1.19.3 decomposition smokes.

## Validation Command
- Host gate: `EA_SKIP_FULL_GATES=1 bash scripts/run_v120_smoke.sh`
- Broad host gate: `EA_SKIP_FULL_GATES=1 bash scripts/run_v119_smoke.sh`
