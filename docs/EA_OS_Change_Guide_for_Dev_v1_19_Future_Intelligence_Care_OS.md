# EA OS Change Guide for Dev v1.19 Future Intelligence Care OS

Date: 2026-03-04

## Purpose

This guide captures the v1.19 contract/gate rollout that lands profile-driven
future-intelligence care behavior as an enforced milestone instead of an
optional design direction.

## What changed

1. Incoming v1.19 contract pack is now mirrored and executed in-repo
- Added `tests/_incoming_v119/` with the dropped-in external test pack files.
- Added `tests/run_incoming_v119_pack.py` to execute the pack in host smoke
  flows without requiring `pytest` installation.
- Added optional dependency stubs (for `pytest`, `httpx`, `psycopg2`) in the
  runner so contract validation works in minimal CI/host environments.

2. New v1.19 host smoke gate
- Added `tests/smoke_v1_19_future_intelligence_pack.py`.
- This gate validates:
  - v1.19 module presence,
  - behavior contracts (high-value trip + layover risk + confidence mode),
  - full incoming-v119 contract pack pass.

3. Gate wiring / release scripts
- `scripts/docker_e2e.sh` now runs `smoke_v1_19_future_intelligence_pack`.
- Added `scripts/run_v119_smoke.sh`.
- Added `scripts/release_v119_future_intelligence_care_os.sh`.
- CI workflow `.github/workflows/release-gates.yml` now includes v1.19 host smoke.

4. Real milestone functional coverage extended
- `tests/real_milestone_suite.py` now includes `test_v119_future_intelligence_care`.
- The functional test asserts:
  - high-value travel exposure extraction (`EUR 15,000`),
  - route risk hit detection (Tel Aviv layover signal),
  - deterministic future/readiness/critical outputs,
  - bounded plan output.

5. Intelligence behavior fixes
- `ea/app/intelligence/dossiers.py`
  - fixed currency parsing for natural formats like `EUR 15,000`.
  - expanded risk lexicon with layover-relevant terms (`tel aviv`, `tehran`).
- `ea/app/intelligence/future_situations.py`
  - `travel_window` now triggers for high-exposure/risk trips even when
    near-term schedule metadata is partial.

6. Docs alignment
- Added design doc: `docs/EA_OS_Design_v1_19_Future_Intelligence_Care_OS.md`.
- Updated roadmap: `docs/ea_os_design_roadmap_v2026.md` now includes Phase 7 v1.19.
- Updated root README smoke/release/doc references for v1.19.

7. Sentinel watchdog resilience hardening
- `ea/app/poll_listener.py` watchdog now uses monotonic heartbeat timing.
- Added startup grace window (`EA_SENTINEL_STARTUP_GRACE_SEC`) to avoid false
  deadlock detection during boot churn.
- Added configurable heartbeat timeout (`EA_SENTINEL_HEARTBEAT_TIMEOUT_SEC`).
- Added diagnostics mode toggle (`EA_SENTINEL_EXIT_ON_STALL=false`) for
  observing stalls without forced process exit.
- Preserved throttled user-facing interruption copy contract and no-leak
  internal phrasing invariant.

8. /brief duplicate-request guard
- Added `/brief` dedupe + in-flight guard in `ea/app/poll_listener.py`.
- New env knob: `EA_BRIEF_COMMAND_MIN_INTERVAL_SEC` (default `120`).
- Prevents duplicate briefing deliveries when two near-identical `/brief`
  triggers arrive in a short window (for example user retry + delayed poll replay).
- Added host contract smoke: `tests/smoke_brief_dedupe_guard.py`.

9. v1.19.1 non-travel intelligence expansion
- Added dossier builders for:
  - project: `build_project_dossier`
  - finance commitments: `build_finance_commitment_dossier`
- Added future-situation kinds:
  - `meeting_prep_window`
  - `deadline_window`
- Updated readiness/critical/scoring logic to account for project and finance
  signals in addition to trip-only detection.
- Added host smoke: `tests/smoke_v1_19_1_future_intelligence_expansion.py`.

10. v1.19.1 profile persistence core
- Added persisted profile state load/save in `ea/app/intelligence/profile.py`.
- `build_profile_context()` now merges:
  - default profile layers,
  - persisted `profile_context_state` layer snapshots,
  - learned preference hints from `user_interest_profiles`,
  - runtime confidence downgrade note precedence.
- Added bootstrap + migration DDL for `profile_context_state`:
  - `ea/app/db.py` (`init_db_sync()`)
  - `ea/schema/20260304_v1_19_1_profile_core.sql`
- Added host smoke: `tests/smoke_v1_19_1_profile_persistence.py`.

11. v1.19.1 LLM gateway trust-boundary hardening
- Expanded `ea/app/contracts/llm_gateway.py` from thin pass-through to contract boundary:
  - prompt sanitization (control-char stripping),
  - secret redaction in prompt payloads,
  - prompt/system max-char enforcement via env knobs,
  - task-type policy mapping (`briefing_compose`, `profile_summary`, `future_reasoning`, `operator_only`),
  - raw-document payload blocking for user-surface tasks,
  - output validation via `validate_model_output(...)`:
    - blocks tool-like outputs
    - blocks JSON-like output on user-surface tasks unless explicitly allowlisted
    - blocks internal/diagnostic phrasing echoes on user-surface tasks
  - bounded output-size clamp,
  - egress audit metadata logging (purpose/task/correlation/data-class/verdict),
  - safe fallback copy on provider-call failures.
- Updated main gateway call sites to pass explicit policy metadata instead of
  relying on env defaults:
  - briefing compose calls use `task_type="briefing_compose"`
  - interactive chat-assist calls use `task_type="profile_summary"`
  - coaching JSON resolver uses `task_type="operator_only"` + `allow_json=True`
- New env knobs:
  - `EA_LLM_GATEWAY_MAX_PROMPT_CHARS`
  - `EA_LLM_GATEWAY_MAX_SYSTEM_PROMPT_CHARS`
  - `EA_LLM_GATEWAY_MAX_OUTPUT_CHARS`
  - `EA_LLM_GATEWAY_ALLOW_IMPLICIT_TASK_TYPE` (transition-only override)
  - `EA_LLM_GATEWAY_AUDIT_PATH`
- Added host smoke: `tests/smoke_v1_19_1_llm_gateway_boundary.py`.

12. v1.19.2 human-assistant compose wiring
- Briefing compose path now builds and consumes all currently-supported dossier types:
  - trip
  - project
  - finance commitment
- `critical/readiness/future/preparation/mode` evaluation now receives `dossiers`
  instead of a trip-only list.
- User-facing fallback wording changed from hard "no critical items" phrasing to:
  - `No immediate action blocks detected right now.`
- Low-confidence fallback wording now avoids "no urgent items" reassurance:
  - `Runtime confidence is reduced; urgent status may be incomplete. Please verify high-impact commitments.`
- Briefing diagnostics are now log-only; Telegram output no longer appends a
  diagnostics block.
- Bot command menu hides `/mumbrain` by default and supports optional exposure via:
  - `EA_EXPOSE_MUMBRAIN_MENU=true`
- Added host smoke: `tests/smoke_v1_19_2_human_assistant_mode.py`.

13. v1.19.2 missingness engine
- Added `ea/app/intelligence/missingness.py` with first missing-gap detections:
  - `travel_support_gap`
  - `prep_gap`
  - `decision_owner_missing`
  - `missing_dependency`
- Wired missingness signals into readiness synthesis:
  - missing critical gaps become blockers + suggested actions
  - missing watch gaps become watch items + suggested actions
- Wired missingness signals into critical lane:
  - critical gaps now promote deterministic `Immediate Action` items
  - critical gap types can raise decision-window and exposure scoring
- Added host smoke: `tests/smoke_v1_19_2_missingness.py`.

14. v1.19.2 control-plane decomposition (poll listener)
- Extracted Telegram menu surface logic into `ea/app/telegram_menu.py`:
  - `mumbrain_user_visible()`
  - `bot_commands()`
  - `menu_text()`
- Extracted auth session persistence into `ea/app/auth_sessions.py`:
  - `AuthSessionStore`
- Extracted watchdog/sentinel logic into `ea/app/watchdog.py`:
  - watchdog thread startup + heartbeat timeout policy
  - alert throttling state
  - shared `heartbeat_pinger()` + `mark_heartbeat()` contract
- Extracted brief-request dedupe/in-flight guard into `ea/app/brief_commands.py`:
  - brief throttling interval policy
  - persisted short-window dedupe state
  - in-flight command lock/guard
- Extracted shared Telegram update routing into `ea/app/update_router.py` and
  reused it in both poller and worker paths.
- Extracted Telegram update offset persistence into `ea/app/offset_store.py`
  and reused it in poller + poll_listener paths.
- `ea/app/poll_listener.py` now imports these modules instead of owning the
  command-menu/auth-session/watchdog/brief-guard/update-routing
  implementations inline.
- Host smoke updated to lock this decomposition contract:
  - `tests/smoke_v1_19_2_human_assistant_mode.py`.
  - `tests/smoke_sentinel_user_message.py`
  - `tests/smoke_v1_18_1_runtime_alignment.py`

15. v1.19.2 health dossier expansion
- Added `build_health_dossier(...)` in `ea/app/intelligence/dossiers.py`.
- Briefing compose now includes health dossier in the multi-dossier set.
- Future situations now include `health_watch_window`.
- Readiness + critical lane now promote near-term or urgent health signals.
- Added host smoke: `tests/smoke_v1_19_2_health_dossier.py`.

16. v1.19.2 LLM gateway DB-audit sink
- `ea/app/contracts/llm_gateway.py` now mirrors egress audit metadata to DB
  audit log records (`component=llm_gateway`, `event_type=egress_audit`) in
  addition to JSONL file logging.
- New env toggle:
  - `EA_LLM_GATEWAY_DB_AUDIT_ENABLED` (default enabled).
- Extended host smoke: `tests/smoke_v1_19_1_llm_gateway_boundary.py` verifies
  the DB-audit write path contract.

17. v1.19.2 calmer briefing presentation
- `ea/app/briefings.py` now renders human-readable urgency labels instead of raw
  numeric telemetry in user chat:
  - `Risk urgency: High/Medium/Low`
  - `Decision window: Act now/Soon/Monitor`
- Active epics now avoid raw `salience/open` counters in Telegram output and use
  follow-up wording (for example `2 open item(s) need follow-up`).
- Extended host smoke: `tests/smoke_v1_19_2_human_assistant_mode.py` enforces
  absence of `Exposure/Decision score` and `salience` phrasing in compose code.

18. v1.19.2 intelligence snapshot persistence
- Added `ea/app/intelligence/snapshots.py` with best-effort persistence API:
  - `save_intelligence_snapshot(...)`
- Briefing compose now persists a deterministic snapshot per compose cycle with:
  - profile context,
  - dossiers,
  - future situations,
  - readiness,
  - critical lane,
  - preparation plan,
  - compose mode.
- Added runtime/bootstrap DDL in `ea/app/db.py` for `intelligence_snapshots`.
- Added migration SQL:
  - `ea/schema/20260304_v1_19_2_intelligence_snapshots.sql`
- Wired smoke/gates:
  - `tests/smoke_v1_19_2_snapshot_persistence.py`
  - `scripts/run_v119_smoke.sh`
  - `scripts/docker_e2e.sh`
  - `scripts/docker_e2e_design_workflows.sh`
  - `.github/workflows/release-gates.yml`

19. v1.19.2 household-ops dossier expansion
- Added `build_household_ops_dossier(...)` in `ea/app/intelligence/dossiers.py`.
- Briefing compose now includes household-ops dossier in the multi-dossier set.
- Future situations now include `household_ops_window`.
- Readiness + critical lane now promote household payment/service continuity risk
  and near-term household operations follow-up windows.
- Added host smoke: `tests/smoke_v1_19_2_household_dossier.py`.
- Wired smoke/gates:
  - `scripts/run_v119_smoke.sh`
  - `scripts/docker_e2e.sh`
  - `.github/workflows/release-gates.yml`

20. v1.19.2 tenant-scoped LLM egress policy seam
- Added policy resolver:
  - `ea/app/llm_gateway/policy.py` (`is_egress_denied(...)`)
- Added DB contract for policy rules:
  - table `llm_egress_policies` in `ea/app/db.py`
  - migration SQL `ea/schema/20260304_v1_19_2_llm_egress_policies.sql`
- `ea/app/contracts/llm_gateway.py` now enforces tenant/person/task/data-class
  deny rules before provider egress and emits `blocked_policy` audit verdict.
- Gateway audit metadata now includes `tenant` and `person_id`.
- Main call paths now pass tenant/person context into gateway calls:
  - `ea/app/briefings.py`
  - `ea/app/poll_listener.py`
  - `ea/app/coaching.py`
- Added host smoke: `tests/smoke_v1_19_2_llm_egress_policy.py`.
- Wired smoke/gates:
  - `tests/smoke_v1_19_1_llm_gateway_boundary.py` callsite assertions
  - `scripts/run_v119_smoke.sh`
  - `scripts/docker_e2e.sh`
  - `scripts/docker_e2e_design_workflows.sh`
  - `.github/workflows/release-gates.yml`

21. v1.19.2 poll-listener chat-assist extraction
- Added `ea/app/chat_assist.py`:
  - `ask_llm_text(...)`
  - `humanize_agent_report(...)`
- `ea/app/poll_listener.py` now imports chat-assist helpers instead of owning
  LLM-assist glue and provider-error humanization inline.
- Updated contract smokes to reflect extracted ownership while preserving
  contract invariants:
  - `tests/smoke_v1_12_7_contract_freeze.py`
  - `tests/smoke_v1_19_1_llm_gateway_boundary.py`
  - `tests/smoke_v1_19_2_human_assistant_mode.py`

22. v1.19.3 Telegram hard-boundary + poller split continuation
- Enforced a hard no-diagnostics-to-chat boundary for render fallback:
  - `ea/app/poll_listener.py` no longer appends renderer diagnostics based on
    env toggles; it always emits safe simplified user copy.
- Tightened briefing diagnostics behavior:
  - `ea/app/briefings.py` keeps diagnostics log-only and treats user-surface
    diagnostics exposure as permanently disabled.
- Continued poll-listener responsibility split:
  - Added `ea/app/briefing_delivery_sessions.py`
    (`create_briefing_delivery_session`, `activate_briefing_delivery_session`)
  - `ea/app/poll_listener.py` now imports these helpers instead of owning DB
    delivery-session helpers inline.
- Updated host smokes:
  - `tests/smoke_v1_12_6.py`
  - `tests/smoke_v1_12_7_contract_freeze.py`
  - `tests/smoke_v1_19_2_human_assistant_mode.py`

23. v1.19.3 newspaper PDF quality gate extraction
- Added `ea/app/newspaper/pdf_quality_gate.py`:
  - `_count_pdf_images(...)`
  - `validate_newspaper_pdf_bytes(...)`
- `ea/app/poll_listener.py` now imports the quality-gate function instead of
  keeping PDF validation internals inline.
- Updated wiring smoke:
  - `tests/smoke_newspaper_pdf_gate_wiring.py`

24. v1.19.3 human composer + source-acquisition split
- Added `ea/app/intelligence/human_compose.py` and moved user-facing section
  assembly there (`compose_briefing_html(...)`).
- Added `ea/app/intelligence/source_acquisition.py` and moved OpenClaw
  source-fetching + filtering there (`collect_briefing_sources(...)`).
- `ea/app/briefings.py` now orchestrates intelligence assembly and delegates:
  - acquisition to source-acquisition module
  - final user-surface compose to human composer module
- Added behavioral host smokes:
  - `tests/smoke_v1_19_3_human_compose_behavior.py`
  - `tests/smoke_v1_19_3_source_acquisition_split.py`
- Wired these into:
  - `scripts/run_v119_smoke.sh`
  - `scripts/docker_e2e.sh`
  - `.github/workflows/release-gates.yml`

25. v1.19.3 LLM gateway explicit task typing
- `ea/app/contracts/llm_gateway.py` now requires explicit `task_type` by
  default and blocks implicit calls with verdict `blocked_missing_task_type`.
- Added transitional override env only:
  - `EA_LLM_GATEWAY_ALLOW_IMPLICIT_TASK_TYPE=true`
- Updated gateway boundary smoke coverage:
  - `tests/smoke_v1_19_1_llm_gateway_boundary.py`
  - explicit task-type checks
  - missing-task-type blocking behavior

## Rollout checklist

1. Host gate:
- `EA_SKIP_FULL_GATES=1 bash scripts/run_v119_smoke.sh /docker/EA`

2. Full gate:
- `bash scripts/docker_e2e.sh`

3. Release wrapper:
- `bash scripts/release_v119_future_intelligence_care_os.sh /docker/EA`

## Expected outcomes

- Incoming v1.19 contract pack passes in host and CI gates.
- Real milestone suite includes explicit v1.19 care-intelligence functional pass.
- High-value/risky trip signals are deterministically promoted into readiness
  and critical-action outputs instead of getting suppressed by generic summarization.
