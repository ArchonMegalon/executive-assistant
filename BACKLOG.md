# EA Execution Backlog

Last updated: 2026-03-04
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
- [DONE] Auditor LTD inventory hardening:
  - `LTD_INVENTORY.md` now explicitly separates capability-backed LTD tier declarations
    from non-tiered runtime dependencies.

## Blocked
- None.

## Next Queue (on new feedback)
- None.
