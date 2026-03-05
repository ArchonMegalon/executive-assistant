# EA OS Change Guide for Dev v1.21 (Task-First Planner Contracts Seed)

## Goal
Start shifting planning from provider-first routing to task-first contracts without breaking
existing capability routing behavior.

## What changed

1. Added task-contract registry:
   - `ea/app/planner/task_registry.py`
   - Introduces `TaskContract` with:
     - `key`
     - `description`
     - `provider_priority`
     - `output_artifact_type`
     - `approval_default`
     - `budget_policy`
   - Initial contracts seeded for:
     - `travel_rescue`
     - `trip_context_pack`
     - `collect_structured_intake`
     - `guided_intake`
     - `compile_prompt_pack`
     - `polish_human_tone`
     - `generate_multimodal_support_asset`

2. Planner exports updated:
   - `ea/app/planner/__init__.py` now exports task-registry helpers:
     - `task_or_none`
     - `task_or_raise`
     - `list_task_contracts`

3. Capability routing now consumes task contracts:
   - `ea/app/skills/capability_router.py` now:
     - resolves optional `TaskContract`
     - uses task contract `provider_priority` as planning rank seed
     - emits task metadata on plan output:
       - `task_contract_key`
       - `task_contract_approval_default`
       - `task_contract_output_artifact_type`
       - `task_contract_budget_policy`

4. New smoke coverage:
   - `tests/smoke_v1_21_task_contract_registry.py`
   - `tests/smoke_v1_21_intent_spec_v2_shape.py`
   - `tests/smoke_v1_21_provider_broker.py`
   - `tests/smoke_v1_21_generic_skill_execution.py`
   - Validates module presence and task-contract-aware capability planning behavior.
   - Wired into:
      - `scripts/run_v120_smoke.sh`
      - `scripts/run_v119_smoke.sh`
      - `scripts/docker_e2e.sh`
      - `.github/workflows/release-gates.yml`

5. Intent compiler shape expansion (`IntentSpecV2`-style fields):
   - `ea/app/execution/session_store.py` now emits additional fields from `compile_intent_spec(...)`:
     - `deliverable_type`
     - `approval_class`
     - `risk_class`
     - `budget_class`
     - `evidence_requirements`
     - `source_refs`
     - `stakeholders`
     - `output_contract`
     - `commitment_key`

6. Provider broker scoring seed:
   - Added `ea/app/planner/provider_broker.py` with deterministic capability ranking:
     - task-priority weighting
     - preferred capability override
     - lightweight policy adjustment from capability metadata
   - `ea/app/planner/provider_registry.py` adds planner-facing provider contracts
     (`ProviderContract`) and provider lookup helpers (`providers_for_task`, `provider_or_raise`),
     decoupling planner/broker logic from direct `skills` registry imports.
   - `ea/app/skills/capability_router.py` now delegates ranking to broker output and
     emits `ranking` details with reasons.

7. Generic skill execution uplift:
   - `ea/app/skills/generic.py` now supports `runtime_execution_ops` for safe operations.
   - `draft_and_polish` (`polish`), `prompt_compiler` (`compile`), and `multimodal_burst`
     (`generate`) now return deterministic `executed` outcomes with lightweight artifacts.
   - `ea/app/skills/runtime_action_exec.py` now renders `executed` skill outcomes with artifact preview.

8. Task-aware session plan templates:
   - Added `ea/app/planner/plan_builder.py` with deterministic task-aware step construction.
   - `ea/app/execution/session_store.py::build_plan_steps(...)` now delegates to
     `build_task_plan_steps(...)` so free-text, slash-command, callback, and event sessionization
     paths share the same plan-template behavior.
   - Added smoke coverage:
     - `tests/smoke_v1_21_plan_builder.py`
     - `tests/smoke_v1_21_provider_registry.py`
   - v1.21 template behaviors include domain/task-specific enrichment steps:
     - travel: `analyze_trip_commitment`, `compare_travel_options`
     - finance: `verify_payment_context`
     - project: `gather_project_context`
     - health: `review_health_context`
     - gated autonomy: `safety_gate`

9. Runtime syntax safety hardening:
   - Added repository-wide compile smoke: `tests/smoke_python_compile_tree.py`
     and wired it into host/docker/CI gate paths to catch syntax regressions early.
   - Hardened invoice extraction interpolation in `ea/app/poll_listener.py` by
     precomputing nested values (`creditor`, `iban`, `reference`, `amount_value`)
     before caption formatting, reducing quote-fragility in f-string-heavy paths.

10. Proactive planner bootstrap/schema alignment:
   - Added planner/proactive runtime tables to `ea/app/db.py::init_db_sync()`:
     `planner_jobs`, `planner_candidates`, `proactive_items`,
     `proactive_muted_classes`, `send_budgets`, `planner_dedupe_keys`,
     and related indexes.
   - Extended `tests/smoke_v1_18.py` to assert planner table presence in db bootstrap,
     reducing migration/bootstrap drift between planner runtime code and startup schema.

11. Gate naming drift cleanup (v1.21 alias):
   - Added `scripts/run_v121_smoke.sh` as an explicit v1.21 alias over
     `scripts/run_v120_smoke.sh` for operational readability.
   - Added `tests/smoke_v1_21_gate_alias.py` and wired it into host/docker/CI gates.
   - Updated README smoke command list to include `run_v121_smoke.sh`.

12. Formal approval-gate ledger seed:
   - Added approval-gate store helpers in `ea/app/execution/session_store.py`:
     - `create_approval_gate(...)`
     - `attach_approval_gate_action(...)`
     - `mark_approval_gate_decision(...)`
   - Extended typed action persistence with ledger references in `ea/app/actions.py`:
     - `session_id`
     - `step_id`
     - `approval_gate_id`
   - Added `approval_gates` + typed-action reference columns to db bootstrap in `ea/app/db.py`,
     plus migration file `ea/schema/20260305_v1_21_approval_gates.sql`.
   - Free-text high-risk runtime now creates approval-gate rows and links them to staged typed actions
     in `ea/app/intent_runtime.py`; approval callback resume marks gate decision `approved`.
   - Added `tests/smoke_v1_21_approval_gate_store.py` and updated approval-behavior smokes.

13. Planner intent-compiler shim:
   - Added planner module `ea/app/planner/intent_compiler.py` with `compile_intent_spec_v2(...)`.
   - `ea/app/execution/session_store.py::compile_intent_spec(...)` now acts as a
     compatibility shim delegating to planner intent compilation.
   - `tests/smoke_v1_21_intent_spec_v2_shape.py` now also validates module + shim wiring.

14. Step-executor seam for reasoning pass:
   - Added `ea/app/planner/step_executor.py` with `run_reasoning_step(...)`
     to encapsulate provider-backed reasoning execution behind a planner path.
   - `ea/app/intent_runtime.py` now calls `run_reasoning_step(...)` for both:
     - free-text execute path
     - approved-callback execute path
   - `tests/smoke_v1_21_step_executor_path.py` added and wired into host/docker/CI gates.

15. Task-type metadata propagation into step graph + ledger:
   - `ea/app/planner/intent_compiler.py` now emits deterministic `task_type` values for:
     - travel rescue / trip context
     - finance typed-safe-action
     - guided intake
     - prompt-pack compile
     - tone polish
   - `ea/app/planner/plan_builder.py` now annotates step rows with:
     - `task_type`
     - `provider_candidates`
     - `output_artifact_type`
     - `budget_policy`
     - `approval_default`
   - `ea/app/execution/session_store.py::create_execution_session(...)` now persists
     those planner metadata fields into execution-step JSON payloads
     (preconditions/evidence), keeping plan intent visible in the execution ledger.
   - Expanded smokes:
     - `tests/smoke_v1_21_intent_spec_v2_shape.py`
     - `tests/smoke_v1_21_plan_builder.py`
     - `tests/smoke_v1_20_execution_sessions.py`

16. Slash `/skill` planner-session uplift:
   - `ea/app/skill_commands.py` now seeds slash command sessions with
     `build_plan_steps(intent_spec=...)` when a skill contract/task type is known.
   - staged skill typed-actions now include `session_id`, linking action callbacks back
     to the execution ledger.
   - Updated smokes:
     - `tests/smoke_v1_20_slash_command_sessions.py`
     - `tests/smoke_v1_20_slash_command_behavior.py`

17. Non-travel task-template expansion:
   - Added deterministic pre-exec step templates in `plan_builder.py` for:
     - `collect_structured_intake`
     - `compile_prompt_pack`
     - `polish_human_tone`
     - `generate_multimodal_support_asset`
   - plan-builder smoke now asserts these task-template paths and metadata.

## Why this matters

This keeps provider contracts (`CapabilityContract`) but introduces a stable task layer the
planner can build on next:

- task contracts define planning intent and policy defaults,
- providers become swappable implementations,
- plan outputs carry explicit task metadata for downstream session/approval logic.

## Next expansion

1. Introduce `IntentSpecV2` compilation into task contracts.
2. Add broker scoring (fit/privacy/cost/latency/history) on top of task contract defaults.
3. Persist task-template step metadata (budget/evidence/approval class) in richer execution ledgers.
