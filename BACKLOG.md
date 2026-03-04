# EA Execution Backlog

Last updated: 2026-03-04
Branch: `main`

## Definition Of Done (DoD)
- All backlog items are marked `DONE` or `BLOCKED` with reason.
- Latest full gate pass exists from `bash scripts/docker_e2e.sh`.
- Working tree is clean (`git status --short` has no changes).
- Local commits are present (no push required).

## Current Milestone: v1.19.4 Consolidation
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

## Blocked
- None.

## Next Queue (on new feedback)
- None.
