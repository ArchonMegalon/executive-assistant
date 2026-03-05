# EA OS Change Guide for Dev v1.20 (Commitment OS Foundations)

## Goal
Bridge the intent-to-execution gap by introducing a persistent execution-session runtime seed.

This slice does not replace existing contracts. It adds auditable session state under the
free-text path so intent compilation, evidence gathering, execution, and reply rendering can
be tracked as deterministic steps.

## What changed

1. New execution-session module:
   - `ea/app/execution/session_store.py`
   - Exposes:
     - `compile_intent_spec(...)`
     - `build_plan_steps(...)`
     - `create_execution_session(...)`
     - `mark_execution_session_running(...)`
     - `mark_execution_step_status(...)`
     - `append_execution_event(...)`
     - `finalize_execution_session(...)`

2. New persistent tables:
   - `execution_sessions`
   - `execution_steps`
   - `execution_events`
   - Added in:
     - `ea/app/db.py` bootstrap path
     - `ea/schema/20260304_v1_20_execution_sessions.sql`

3. Free-text intent runtime wiring:
   - `ea/app/intent_runtime.py` now:
     - compiles `IntentSpec`
     - builds deterministic plan steps
     - creates and runs an execution session
     - records step states for:
       - `compile_intent`
       - `gather_evidence` (when URL scrape is used)
       - `safety_gate` (passive marker for approval-required intents)
       - `execute_intent`
       - `render_reply`
     - finalizes session with `completed` / `failed` outcome

4. Poller callsite alignment:
   - `ea/app/poll_listener.py` passes `tenant_name` into free-text handler for session attribution.

5. Typed-action callback sessionization:
   - `ea/app/callback_commands.py` now applies the same execution-session lifecycle to `act:*` typed actions.
   - `/skill` queued actions executed through callback now persist compile/execute/render status in the same ledger.

6. BrowserAct event sessionization:
   - `ea/app/intake/browseract.py` now wraps durable event processing in execution sessions.
   - Session source: `external_event_browseract`.
   - Step tracking added for event execution and persistence outcome (`processed` / `discarded` / `failed`).

7. MetaSurvey + ApproveThis event sessionization:
   - `ea/app/intake/metasurvey_feedback.py` now wraps webhook processing with execution sessions.
   - `ea/app/approvals/normalizer.py` now wraps ApproveThis event normalization with execution sessions.
   - Session sources:
     - `external_event_metasurvey`
     - `external_event_approvethis`

8. Slash-command sessionization (`/skill`):
   - `ea/app/skill_commands.py` now wraps `/skill` intake + validation + staging in execution sessions.
   - Session source: `slash_command_skill`.
   - This closes the command-side gap between slash intake and typed-action execution telemetry.

9. Teable memory boundary hardening:
   - `ea/app/integrations/teable/sync_worker.py` was rewritten as a curated-memory projector:
     - default API base normalized to `https://app.teable.ai/api`
     - legacy `app.teable.io` auto-normalized
     - runtime-dump filtering for unsafe memory payloads
     - provenance fields (`Source`, `Confidence`, `Last Verified`, `Sensitivity`, `Sharing Policy`, `Reviewer`)
     - local-first state persistence in attachments (`teable_sync_state.json`)
   - `docker-compose.yml` now mounts `./attachments` for `ea-teable-sync`.
   - Added model doc: `docs/EA_OS_Teable_Memory_Model.md`.

10. Gate coverage:
   - `tests/smoke_v1_20_execution_sessions.py`
   - `tests/smoke_v1_20_typed_action_sessions.py`
   - `tests/smoke_v1_20_browseract_event_sessions.py`
   - `tests/smoke_v1_20_external_event_sessions.py`
   - `tests/smoke_v1_20_external_event_behavior.py`
   - `tests/smoke_v1_20_slash_command_sessions.py`
   - `tests/smoke_v1_20_teable_memory_boundary.py`
   - `tests/smoke_v1_20_slash_command_behavior.py`
   - `tests/smoke_v1_20_typed_action_behavior.py`
   - `tests/smoke_v1_20_gog_session_id_uniqueness.py`
   - `tests/smoke_v1_20_legacy_button_action_sessions.py`
   - wired into:
     - `scripts/run_v119_smoke.sh`
     - `scripts/run_v120_smoke.sh`
     - `scripts/docker_e2e.sh`
     - `.github/workflows/release-gates.yml`
   - behavior-level contract checks now validate:
     - external-event session outcomes across MetaSurvey/ApproveThis/BrowserAct,
     - slash-command planning-task consistency,
     - typed-action callback session finalization.

## Why this matters

Before this patch, free-text execution was mostly prompt-forwarding with no persistent step ledger.
Now each request gets a durable execution session with auditable lifecycle transitions. This is the
foundation for broader v1.20 planner/session unification across slash commands, skills, and webhook flows.

## Next suggested expansion

1. Reuse execution sessions for typed skill actions and webhook workflows.
2. Add explicit approval-step objects for irreversible actions.
3. Persist per-step budgets, deadlines, and retry policies.
4. Add session replay tooling for operator audit.

## Additional hardening in this slice

- `ea/app/gog.py` now generates a unique execution session id per run (no fixed `ea-exec` id),
  reducing collision risk under concurrent free-text/agent runs.
- `ea/app/callback_commands.py` now sessionizes legacy `act:*` button-context execution
  (the `gog_scout` runtime path), not just typed actions.
