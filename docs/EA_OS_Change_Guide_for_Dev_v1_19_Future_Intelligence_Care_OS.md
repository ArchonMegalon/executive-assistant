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
- New env knobs:
  - `EA_LLM_GATEWAY_MAX_PROMPT_CHARS`
  - `EA_LLM_GATEWAY_MAX_SYSTEM_PROMPT_CHARS`
  - `EA_LLM_GATEWAY_MAX_OUTPUT_CHARS`
  - `EA_LLM_GATEWAY_TASK_TYPE`
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
- Added host smoke: `tests/smoke_v1_19_2_missingness.py`.

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
