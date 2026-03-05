# EA Execution Backlog

Last updated: 2026-03-05
Branch: `main`

## Definition Of Done (DoD)
- All backlog items are marked `DONE` or `BLOCKED` with reason.
- Latest full gate pass exists from `bash scripts/docker_e2e.sh`.
- Working tree is clean (`git status --short` has no changes).
- Local commits are present (no push required).

## Current Milestone: v1.20 Commitment OS Foundations
- [DONE] Capability registry baseline (`capability_registry.py` + smoke + gates).
- [DONE] Generic skill inventory baseline (`generic.py`, `registry.py`, `skill_inventory` smoke).
- [DONE] Capability planning router (`capability_router.py` + smoke + gates).
- [DONE] Human compose contract tightening and wording alignment.
- [DONE] Doc/code drift guard (`smoke_v1_19_4_doc_alignment.py` + gates).
- [DONE] Generic skill handlers return deterministic capability plan metadata.
- [DONE] Runtime skill-dispatch path:
  - `/skill` command stages typed actions with plan preview.
  - `act:` callback consumes typed actions and routes `skill:*` + payments actions.
- [DONE] Behavioral sidecar/skill orchestration coverage:
  - generic skills now emit deterministic orchestration outcomes (`planned`/`staged`)
    with capability plan metadata.
  - typed skill action rendering now surfaces selected primary/fallback capabilities.
  - `smoke_v1_19_4_sidecar_skill_orchestration.py` added and wired into all gates.
- [DONE] LLM gateway package/export convergence:
  - `app.llm_gateway.client.safe_llm_call` now delegates to
    `app.contracts.llm_gateway.ask_text`.
  - `app.llm_gateway` exports `ask_text` and `DEFAULT_SYSTEM_PROMPT` from the
    hardened contract boundary.
  - `smoke_v1_19_4_llm_gateway_convergence.py` added and wired into all gates.
- [DONE] Briefing diagnostics log hard-gate:
  - internal diagnostics logs are disabled by default and only emitted when
    `EA_BRIEFING_DIAGNOSTICS_LOG_ENABLED=1`.
  - `smoke_v1_19_4_briefing_diagnostics_log_gate.py` added and wired into
    all gates.
- [DONE] Skill planning consistency fixes:
  - `/skill` preview now uses each skill's `planning_task_type`, matching
    runtime dispatch behavior.
  - `trip_context_pack` capability priority is now explicit travel-first.
  - diagnostics log gate smoke now validates runtime behavior (with stubs),
    not only source text.
- [DONE] Auditor LTD inventory:
  - `LTD_INVENTORY.md` added at repo root with product/tier/capability mapping.
  - `smoke_v1_19_4_ltd_inventory_doc.py` added and wired into all gates.
- [DONE] Event-worker role-path alignment:
  - `runner.py` now supports `EA_ROLE=event_worker`.
  - compose event-worker now runs via `python -m app.runner` + role env.
  - `roles/event_worker.py` reduced to canonical shim over `workers/event_worker`.
  - `smoke_v1_19_4_event_worker_role_alignment.py` added and wired into all gates.
- [DONE] Full Docker E2E gate pass after each slice.
- [DONE] Execution-session runtime seed:
  - new `execution_sessions`, `execution_steps`, and `execution_events` tables.
  - `ea/app/execution/session_store.py` added for intent compile + step/session lifecycle logging.
  - free-text intent path now writes session + step progress (compile/evidence/execute/render/finalize).
  - `smoke_v1_20_execution_sessions.py` added and wired into host/docker/CI gates.
- [DONE] v1.20 docs and smoke entrypoint:
  - `docs/EA_OS_Change_Guide_for_Dev_v1_20_Commitment_OS.md` added.
  - `scripts/run_v120_smoke.sh` added.
  - `smoke_v1_20_doc_alignment.py` added and wired into host/docker/CI gates.
- [DONE] Typed-action sessionization:
  - `act:*` callback path now writes execution sessions and step transitions.
  - `smoke_v1_20_typed_action_sessions.py` added and wired into host/docker/CI gates.
- [DONE] BrowserAct event sessionization:
  - durable BrowserAct event processing now writes execution sessions.
  - event execution outcome (`processed`/`discarded`/`failed`) is persisted in session step results.
  - `smoke_v1_20_browseract_event_sessions.py` added and wired into host/docker/CI gates.
- [DONE] MetaSurvey + ApproveThis event sessionization:
  - durable MetaSurvey and ApproveThis event processors now write execution sessions.
  - `smoke_v1_20_external_event_sessions.py` added and wired into host/docker/CI gates.
- [DONE] Slash-command (`/skill`) sessionization:
  - slash command intake, validation, and action staging now write execution sessions.
  - `smoke_v1_20_slash_command_sessions.py` added and wired into host/docker/CI gates.
- [DONE] Teable curated-memory boundary hardening:
  - teable sync rewritten as curated-memory projection (operator-editable semantic memory).
  - default API base normalized to `https://app.teable.ai/api` (legacy `.io` normalized).
  - provenance fields + runtime-dump filtering added for sync payload safety.
  - `ea-teable-sync` now mounts `./attachments` in compose for local-first state files.
  - `smoke_v1_20_teable_memory_boundary.py` added and wired into host/docker/CI gates.
- [DONE] v1.20 runtime behavior smoke expansion:
  - added behavior tests for `/skill` command runtime flow and typed-action callback finalization.
  - validates planning-task consistency (`planning_task_type`) and session outcome logging at runtime.
  - `smoke_v1_20_slash_command_behavior.py` + `smoke_v1_20_typed_action_behavior.py` wired into host/docker/CI gates.
- [DONE] External-event behavior smoke expansion:
  - added runtime behavior tests for MetaSurvey, ApproveThis, and BrowserAct event handlers.
  - validates processed/discarded outcomes and execution-session finalization behavior with stubbed DB.
  - `smoke_v1_20_external_event_behavior.py` wired into host/docker/CI gates.
- [DONE] GOG execution session-id hardening:
  - removed fixed `--session-id ea-exec` usage from `gog_scout`.
  - added per-run unique/sanitized session-id generation to reduce concurrent execution collisions.
  - `smoke_v1_20_gog_session_id_uniqueness.py` wired into host/docker/CI gates.
- [DONE] Legacy callback action sessionization:
  - `act:*` legacy button-context execution path now writes execution session lifecycle
    (compile/execute/render/finalize), aligned with typed-action callbacks.
  - `smoke_v1_20_legacy_button_action_sessions.py` added and wired into host/docker/CI gates.
- [DONE] Brief command sessionization:
  - `/brief` runtime path now writes execution sessions with explicit step tracking
    (compile/build/render/persist) and deterministic completion/failure outcomes.
  - `smoke_v1_20_brief_command_sessions.py` added and wired into host/docker/CI gates.
- [DONE] High-risk free-text approval gate hardening:
  - free-text intents with `approval_required` autonomy are now blocked behind explicit callback approval.
  - staged typed action `intent:approval_execute` is required before execution can proceed.
  - parent session is finalized as `partial` while awaiting approval, then resumed on approval callback.
  - `smoke_v1_20_free_text_approval_gate_behavior.py` and
    `smoke_v1_20_typed_action_approval_resume.py` added and wired into host/docker/CI gates.
- [DONE] Task-first planner contract seed (v1.21):
  - added `TaskContract` registry at `ea/app/planner/task_registry.py`.
  - added task-aware provider broker seed (`ea/app/planner/provider_broker.py`) and
    routed capability planning through broker ranking output.
  - generic skill handlers now support deterministic `executed` outcomes for safe operations
    via `runtime_execution_ops` with lightweight artifact previews.
  - capability planning now reads task contract provider priority and emits task metadata
    (`task_contract_key`, approval default, artifact type, budget policy), plus broker `ranking`.
  - `compile_intent_spec(...)` now emits an `IntentSpecV2`-style shape with task/approval/risk/output fields
    (`deliverable_type`, `approval_class`, `risk_class`, `budget_class`, `evidence_requirements`,
    `source_refs`, `output_contract`, `commitment_key`).
  - `smoke_v1_21_task_contract_registry.py`, `smoke_v1_21_intent_spec_v2_shape.py`,
    `smoke_v1_21_provider_broker.py`, `smoke_v1_21_generic_skill_execution.py`,
    and `smoke_v1_21_doc_alignment.py`
    added and wired into host/docker/CI gates.
- [DONE] Task-aware plan-template routing (v1.21):
  - added `ea/app/planner/plan_builder.py` with deterministic task-aware plan-step templates.
  - `build_plan_steps(...)` in `ea/app/execution/session_store.py` now delegates to planner templates.
  - added `tests/smoke_v1_21_plan_builder.py` and wired it into host/docker/CI gates.
- [DONE] Planner provider-registry seed (v1.21):
  - added `ea/app/planner/provider_registry.py` with planner-facing `ProviderContract`
    wrappers over capability metadata (`providers_for_task`, `provider_or_raise`,
    `list_provider_contracts`).
  - broker/router now consume planner provider abstractions instead of direct
    capability-registry imports.
  - added `tests/smoke_v1_21_provider_registry.py` and wired it into host/docker/CI gates.
- [DONE] Runtime syntax safety hardening:
  - added `tests/smoke_python_compile_tree.py` and wired it into host/docker/CI gates
    for whole-tree Python parse checks.
  - hardened invoice extraction interpolation in `ea/app/poll_listener.py` by
    precomputing nested values before caption interpolation.
- [DONE] Proactive planner bootstrap/schema drift fix:
  - `ea/app/db.py::init_db_sync()` now bootstraps planner/proactive tables and indexes
    used by `ea/app/planner/proactive.py` (including `send_budgets`,
    `planner_candidates`, `proactive_items`, and `planner_dedupe_keys`).
  - `tests/smoke_v1_18.py` now asserts planner table presence in db bootstrap in
    addition to schema-file contracts.
- [DONE] Gate naming drift cleanup:
  - added `scripts/run_v121_smoke.sh` as a v1.21 alias over the existing gate runner.
  - added `tests/smoke_v1_21_gate_alias.py` and wired it into host/docker/CI gates.
  - README smoke command list now includes `run_v121_smoke.sh`.
- [DONE] Formal approval-gate ledger seed:
  - added approval-gate helpers in `ea/app/execution/session_store.py` and exported via
    `ea/app/execution/__init__.py`.
  - `ea/app/intent_runtime.py` now writes/links approval-gate rows for high-risk free-text,
    and marks gate decision approved on callback resume.
  - extended `typed_actions` persistence references (`session_id`, `step_id`,
    `approval_gate_id`) in `ea/app/actions.py` and bootstrap schema.
  - added migration `ea/schema/20260305_v1_21_approval_gates.sql`.
  - added `tests/smoke_v1_21_approval_gate_store.py` and expanded approval behavior smokes.
- [DONE] Planner intent compiler shim:
  - added `ea/app/planner/intent_compiler.py` with `compile_intent_spec_v2(...)`.
  - `ea/app/execution/session_store.py::compile_intent_spec(...)` now delegates to
    planner intent compiler as a compatibility shim.
  - `tests/smoke_v1_21_intent_spec_v2_shape.py` expanded with shim wiring checks.
- [DONE] Step-executor seam for reasoning path:
  - added `ea/app/planner/step_executor.py` with `run_reasoning_step(...)`.
  - `ea/app/intent_runtime.py` now routes provider-backed reasoning execution through
    planner step executor for free-text and approved-callback paths.
  - added `tests/smoke_v1_21_step_executor_path.py` and wired it into host/docker/CI gates.
- [DONE] Task-type metadata propagation into execution ledger:
  - `ea/app/planner/intent_compiler.py` now emits deterministic `task_type` values
    for travel, finance, intake, prompt-pack, and tone-polish intents.
  - `ea/app/planner/plan_builder.py` now annotates plan steps with
    `task_type`, `provider_candidates`, `output_artifact_type`, and budget/approval metadata.
  - `ea/app/execution/session_store.py::create_execution_session(...)` now persists
    planner step metadata into execution-step preconditions/evidence payloads.
  - expanded plan/intent/execution smokes to assert metadata shape + persistence.
- [DONE] Slash `/skill` planner-session uplift:
  - `ea/app/skill_commands.py` now seeds slash sessions with task-aware plan steps
    via `build_plan_steps(...)` when a skill contract is known.
  - staged skill typed-actions now persist `session_id` for execution-ledger linkage.
  - slash-session and slash-runtime smokes updated for planner/session linkage.
- [DONE] Non-travel task template expansion:
  - plan builder now emits deterministic pre-exec steps for:
    - `collect_structured_intake`
    - `compile_prompt_pack`
    - `polish_human_tone`
    - `generate_multimodal_support_asset`
  - `tests/smoke_v1_21_plan_builder.py` expanded to validate new template paths.
- [DONE] Provider broker history-adjustment lane:
  - `ea/app/planner/provider_broker.py` now supports deterministic
    `EA_PROVIDER_HISTORY_SCORE_JSON` score adjustments per provider key.
  - ranking reasons now emit explicit `history_adjustment:+N/-N` markers.
  - `tests/smoke_v1_21_provider_broker.py` expanded with env-driven ranking override checks.
- [DONE] Provider outcome telemetry + broker outcome scoring:
  - added `provider_outcomes` schema in bootstrap and migration
    (`ea/schema/20260305_v1_21_provider_outcomes.sql`).
  - added `ea/app/planner/provider_outcomes.py` with persistence + recent adjustment aggregation.
  - `provider_broker.py` now consumes recent outcome adjustments and emits
    `recent_outcome:+N/-N` scoring reasons.
  - `ea/app/skills/generic.py` now records provider outcomes on runtime success/failure.
  - added `tests/smoke_v1_21_provider_outcomes.py` and wired it into host/docker/CI gates.
- [DONE] Planner pre-execution ownership in free-text runtime:
  - `ea/app/intent_runtime.py` now executes deterministic planner pre-steps
    through `_run_planner_pre_execution_steps(...)` before `execute_intent`.
  - planner pre-step completion now emits `planner_context_step_completed` events.
  - added `tests/smoke_v1_21_intent_runtime_planner_steps.py` and wired it into
    host/docker/CI gates.
- [DONE] Typed-action reference enforcement:
  - `ea/app/actions.py::create_action(...)` now enforces ledger references for
    execution-resume action types:
    - `skill:*` requires `session_id`
    - `intent:approval_execute` requires `session_id` + `approval_gate_id`
  - added `tests/smoke_v1_21_typed_action_reference_enforcement.py` and wired it into
    host/docker/CI gates.
- [DONE] Commitment/artifact world-model seed:
  - added bootstrap + migration schema for `commitments`, `artifacts`, `followups`,
    and `decision_windows` (`ea/schema/20260305_v1_22_commitment_runtime_seed.sql`).
  - added `ea/app/planner/world_model.py` with seed helpers:
    - `upsert_commitment(...)`
    - `create_artifact(...)`
    - `create_followup(...)`
    - `create_decision_window(...)`
  - exported world-model helpers via `ea/app/planner/__init__.py`.
  - added `tests/smoke_v1_22_world_model_seed.py` and wired it into host/docker/CI gates.
- [DONE] Memory-candidate promotion seed:
  - added bootstrap + migration schema for `memory_candidates`
    (`ea/schema/20260305_v1_22_memory_candidates.sql`).
  - added `ea/app/planner/memory_candidates.py`:
    - `emit_memory_candidate(...)`
    - `mark_memory_candidate_review(...)`
    - `list_memory_candidates(...)`
  - exported memory-candidate helpers via `ea/app/planner/__init__.py`.
  - added `tests/smoke_v1_22_memory_candidates.py` and wired it into host/docker/CI gates.
- [DONE] Memory-candidate promotion pipeline completion:
  - `execution/session_store.py::finalize_execution_session(...)` now emits bounded
    memory candidates for completed/partial sessions with source provenance.
  - failed/error session finalize paths are excluded from automatic memory promotion.
  - `integrations/teable/sync_worker.py` now ingests only `approved` rows from
    local `memory_candidates` and tracks candidate-id sync state in
    `/attachments/teable_sync_state.json`.
  - added `list_memory_candidates_for_sync(...)` in `planner/memory_candidates.py`.
  - added `tests/smoke_v1_22_memory_promotion_pipeline.py` and wired it into
    host/docker/CI gates.
- [DONE] Synthetic-user eval harness seed (qa profile):
  - added `ea-sim-user` service to `docker-compose.yml` under `profiles: [qa]`
    so it stays non-prod by default.
  - added scenario runner `ea/app/sim_user/runner.py` plus package exports.
  - added seeded scenario contracts:
    - `qa/scenarios/cooperative_user.json`
    - `qa/scenarios/adversarial_confused_user.json`
  - added helper launcher `scripts/run_sim_user_eval.sh`.
  - added `tests/smoke_v1_22_sim_user_harness.py` and wired it into
    host/docker/CI gates.
- [DONE] Event-worker role-path convergence:
  - `EA_ROLE=event_worker` now dispatches through `app.roles.event_worker.run_event_worker`
    from `runner.py` (canonical role shim path), not direct worker import.
- [DONE] Auditor inventory guard strengthening:
  - `smoke_v1_19_4_ltd_inventory_doc.py` now enforces both sections:
    - capability-backed LTD tiers
    - runtime dependencies not tiered as LTD
- [DONE] Auditor LTD inventory hardening:
  - `LTD_INVENTORY.md` now explicitly separates capability-backed LTD tier declarations
    from non-tiered runtime dependencies.
- [DONE] Unattended work-queue contract:
  - Added root `WORK_TASKS.md` with ordered `DONE/IN_PROGRESS/PENDING/BLOCKED` queue and
    explicit operating rule: always chain the next pending item.
  - Added `tests/smoke_work_tasks_contract.py` and wired it into host/docker/CI gates.

## Blocked
- None.

## Next Queue (on new feedback)
- [IN_PROGRESS] Continue poll/scheduler decomposition
