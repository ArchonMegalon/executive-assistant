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
   - `ea/app/skills/capability_router.py` now delegates ranking to broker output and
     emits `ranking` details with reasons.

## Why this matters

This keeps provider contracts (`CapabilityContract`) but introduces a stable task layer the
planner can build on next:

- task contracts define planning intent and policy defaults,
- providers become swappable implementations,
- plan outputs carry explicit task metadata for downstream session/approval logic.

## Next expansion

1. Introduce `IntentSpecV2` compilation into task contracts.
2. Move fixed step planning to task-template planning.
3. Add broker scoring (fit/privacy/cost/latency/history) on top of task contract defaults.
