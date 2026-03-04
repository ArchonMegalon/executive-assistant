# EA OS v1.19.1 Patch Memo

Date: 2026-03-04

## Purpose

Translate the v1.19 audit/design feedback into a concrete patch sequence against the
current repo with low-risk, test-backed increments.

This memo is intentionally implementation-led: each section maps to specific files,
expected SQL deltas, and gate coverage.

## Scope of this patch wave

1. Prevent duplicate `/brief` deliveries caused by near-simultaneous triggers.
2. Harden sentinel watchdog timing to reduce false deadlock restarts.
3. Expand future-intelligence beyond travel with project + finance commitment seams.
4. Keep runbook output operationally actionable (reduce expected-noise dominance).
5. Persist layered profile state and merge it into briefing intelligence context.
6. Strengthen the cloud LLM contract boundary from thin adapter to guarded gateway.
7. Shift user-facing compose behavior toward calm human-assistant mode.

## Implemented in this repo state

### A. `/brief` duplicate-request guard

Files:
- `ea/app/poll_listener.py`
- `tests/smoke_brief_dedupe_guard.py`
- `tests/smoke_v1_18_1_runtime_alignment.py`
- `scripts/docker_e2e.sh`

Behavior:
- in-flight per-chat lock (`_brief_enter/_brief_exit`)
- persisted short-window dedupe (`.brief_last_command.json`)
- configurable window: `EA_BRIEF_COMMAND_MIN_INTERVAL_SEC` (default `120`)

### B. Sentinel watchdog reliability hardening

Files:
- `ea/app/poll_listener.py`
- `tests/smoke_sentinel_user_message.py`
- `tests/smoke_v1_18_1_runtime_alignment.py`

Behavior:
- monotonic heartbeat source (`time.monotonic()`)
- startup grace to avoid boot false positives
- configurable timeout / exit behavior:
  - `EA_SENTINEL_HEARTBEAT_TIMEOUT_SEC`
  - `EA_SENTINEL_STARTUP_GRACE_SEC`
  - `EA_SENTINEL_EXIT_ON_STALL`

### C. Future-intelligence expansion (non-travel seams)

Files:
- `ea/app/intelligence/dossiers.py`
- `ea/app/intelligence/future_situations.py`
- `ea/app/intelligence/readiness.py`
- `ea/app/intelligence/critical_lane.py`
- `ea/app/intelligence/scores.py`
- `tests/smoke_v1_19_1_future_intelligence_expansion.py`
- `scripts/run_v119_smoke.sh`
- `scripts/docker_e2e.sh`
- `.github/workflows/release-gates.yml`

Behavior:
- added dossier builders:
  - `build_project_dossier`
  - `build_finance_commitment_dossier`
- new future situation kinds:
  - `meeting_prep_window`
  - `deadline_window`
- readiness and critical-lane now handle project/finance dossier signals
- score model expanded beyond trip-only branch

### D. Runbook output quality

Files:
- `scripts/runbook.sh`

Behavior:
- filtered DB-log mode by default (`EA_DB_LOG_MODE=filtered`)
- configurable DB log filter pattern / tail size
- expected idempotency duplicate noise no longer dominates the runbook output

### E. Profile persistence + learned merge

Files:
- `ea/app/intelligence/profile.py`
- `ea/app/db.py`
- `ea/schema/20260304_v1_19_1_profile_core.sql`
- `tests/smoke_v1_19_1_profile_persistence.py`
- `scripts/run_v119_smoke.sh`
- `scripts/docker_e2e.sh`
- `.github/workflows/release-gates.yml`

Behavior:
- `build_profile_context()` now merges persisted layers from `profile_context_state`:
  - `stable_json`
  - `situational_json`
  - `learned_json`
  - `confidence_json`
- learned profile enrichment now also derives from `user_interest_profiles`.
- runtime confidence note still takes precedence and forces degraded-confidence mode.
- best-effort load/save path:
- missing DB env/table safely falls back to defaults
- `save_profile_context(...)` provides contract-level persistence API.

### F. LLM gateway contract hardening

Files:
- `ea/app/contracts/llm_gateway.py`
- `tests/smoke_v1_19_1_llm_gateway_boundary.py`
- `scripts/run_v119_smoke.sh`
- `scripts/docker_e2e.sh`
- `.github/workflows/release-gates.yml`

Behavior:
- prompt sanitization and control-character stripping before provider calls.
- redaction of common token/secret shapes before prompt egress.
- bounded prompt/system sizes:
  - `EA_LLM_GATEWAY_MAX_PROMPT_CHARS`
  - `EA_LLM_GATEWAY_MAX_SYSTEM_PROMPT_CHARS`
- task policy by request type:
  - `briefing_compose`
  - `profile_summary`
  - `future_reasoning`
  - `operator_only`
- raw-document payload guard for user-facing tasks.
- task-type-aware output validation via trust-boundary contract.
- JSON-like response blocking for user-facing tasks unless allowlisted.
- internal diagnostics phrase blocking for user-facing tasks.
- egress audit metadata logs:
  - purpose
  - task_type
  - correlation_id
  - data_class
  - verdict
- optional DB-backed audit mirror:
  - `EA_LLM_GATEWAY_DB_AUDIT_ENABLED` (default on)
  - writes `llm_gateway/egress_audit` rows to `audit_log` for operator traceability.
- primary call sites now pass explicit task metadata:
  - briefing compose: `task_type=briefing_compose`
  - chat-assist in poll listener: `task_type=profile_summary`
  - coaching role resolver JSON path: `task_type=operator_only` + `allow_json=true`
- safe fallback copy on model call failures and blocked tool-like outputs.

### G. Human-assistant compose mode (minus drama)

Files:
- `ea/app/briefings.py`
- `ea/app/poll_listener.py`
- `tests/smoke_v1_19_2_human_assistant_mode.py`
- `tests/smoke_v1_12_6.py`
- `scripts/run_v119_smoke.sh`
- `scripts/docker_e2e.sh`
- `.github/workflows/release-gates.yml`

Behavior:
- main briefing compose now evaluates trip + project + finance dossiers together.
- critical/readiness/future/preparation/mode are fed from `dossiers`.
- removed user-facing diagnostics append from briefing output (logs only).
- calmer status text during compose and safer dict-shaped fallback payloads.
- user-facing urgency is now phrased as labels instead of raw telemetry:
  - `Risk urgency: High/Medium/Low`
  - `Decision window: Act now/Soon/Monitor`
- active epics now use follow-up wording instead of raw salience counters.
- hidden `/mumbrain` from user menu by default (operator command remains available).

### H. Missingness engine (v1.19.2)

Files:
- `ea/app/intelligence/missingness.py`
- `ea/app/intelligence/readiness.py`
- `tests/smoke_v1_19_2_missingness.py`
- `scripts/run_v119_smoke.sh`
- `scripts/docker_e2e.sh`
- `.github/workflows/release-gates.yml`

Behavior:
- new first-pass missingness signals for expected-but-missing support artifacts.
- readiness synthesis now includes missingness-derived blockers/watch items/actions.
- critical lane now consumes missingness signals and promotes critical gaps to
  deterministic immediate actions with upgraded decision-window scoring.

### I. Poll-listener control-plane split (v1.19.2)

Files:
- `ea/app/telegram_menu.py`
- `ea/app/auth_sessions.py`
- `ea/app/watchdog.py`
- `ea/app/brief_commands.py`
- `ea/app/update_router.py`
- `ea/app/offset_store.py`
- `ea/app/poll_listener.py`
- `ea/app/roles/worker.py`
- `ea/app/roles/poller.py`
- `tests/smoke_v1_19_2_human_assistant_mode.py`
 - `tests/smoke_sentinel_user_message.py`
 - `tests/smoke_v1_18_1_runtime_alignment.py`

Behavior:
- command menu and `/mumbrain` visibility policy moved into `telegram_menu.py`.
- auth session storage moved into `auth_sessions.py`.
- watchdog/sentinel lifecycle moved into `watchdog.py` with explicit heartbeat
  and alert-throttle contracts.
- `/brief` dedupe/in-flight guards moved into `brief_commands.py`.
- shared update routing moved into `update_router.py` and reused by poller and
  worker to avoid duplicated command/callback/intent dispatch logic.
- Telegram update offset read/write moved into `offset_store.py` so both poller
  paths use one atomic persistence implementation.
- `poll_listener.py` now consumes these modules instead of carrying that logic
  inline, reducing control-plane coupling without changing command semantics.

### J. Health dossier expansion (v1.19.2)

Files:
- `ea/app/intelligence/dossiers.py`
- `ea/app/intelligence/future_situations.py`
- `ea/app/intelligence/readiness.py`
- `ea/app/intelligence/critical_lane.py`
- `ea/app/briefings.py`
- `tests/smoke_v1_19_2_health_dossier.py`

Behavior:
- adds first-pass `health` dossier detection (mail + calendar).
- introduces `health_watch_window` future situation type.
- readiness and critical lane now promote urgent or near-term health follow-ups.
- briefing compose now includes health dossier alongside trip/project/finance.

### K. Intelligence snapshot persistence (v1.19.2)

Files:
- `ea/app/intelligence/snapshots.py`
- `ea/app/briefings.py`
- `ea/app/db.py`
- `ea/schema/20260304_v1_19_2_intelligence_snapshots.sql`
- `tests/smoke_v1_19_2_snapshot_persistence.py`
- `scripts/run_v119_smoke.sh`
- `scripts/docker_e2e.sh`
- `scripts/docker_e2e_design_workflows.sh`
- `.github/workflows/release-gates.yml`

Behavior:
- added best-effort persistence of compose-cycle intelligence snapshots:
  - profile
  - dossiers
  - future situations
  - readiness
  - critical lane
  - preparation plan
  - epics
  - compose mode
- snapshots are written to `intelligence_snapshots` and indexed by
  `(tenant, person_id, created_at desc)` plus source/time.
- compose path now records snapshots without blocking user delivery.

### L. Household-ops dossier expansion (v1.19.2)

Files:
- `ea/app/intelligence/dossiers.py`
- `ea/app/intelligence/future_situations.py`
- `ea/app/intelligence/readiness.py`
- `ea/app/intelligence/critical_lane.py`
- `ea/app/briefings.py`
- `tests/smoke_v1_19_2_household_dossier.py`
- `scripts/run_v119_smoke.sh`
- `scripts/docker_e2e.sh`
- `.github/workflows/release-gates.yml`

Behavior:
- adds first-pass `household_ops` dossier detection (mail + calendar).
- introduces `household_ops_window` future situation type.
- readiness and critical lane now elevate household payment/service continuity
  risk and near-term household operations windows.
- briefing compose now includes household-ops dossier alongside trip/project/
  finance/health.

### M. Tenant-scoped LLM egress deny policies (v1.19.2)

Files:
- `ea/app/llm_gateway/policy.py`
- `ea/app/contracts/llm_gateway.py`
- `ea/app/db.py`
- `ea/schema/20260304_v1_19_2_llm_egress_policies.sql`
- `ea/app/briefings.py`
- `ea/app/poll_listener.py`
- `ea/app/coaching.py`
- `tests/smoke_v1_19_2_llm_egress_policy.py`
- `tests/smoke_v1_19_1_llm_gateway_boundary.py`
- `scripts/run_v119_smoke.sh`
- `scripts/docker_e2e.sh`
- `scripts/docker_e2e_design_workflows.sh`
- `.github/workflows/release-gates.yml`

Behavior:
- adds DB-backed `llm_egress_policies` rule evaluation with wildcard support
  across:
  - tenant
  - person
  - task_type
  - data_class
- gateway now blocks egress with `blocked_policy` verdict before provider call
  when matching deny rules are active.
- gateway audit metadata now records tenant/person context.
- briefing/chat/coaching call paths now pass tenant/person metadata into the
  gateway boundary.

## SQL additions landed in this patch

Migration file: `ea/schema/20260304_v1_19_1_profile_core.sql`

Table:

1. `profile_context_state`
- primary key `(tenant, person_id)`
- `stable_json jsonb`
- `situational_json jsonb`
- `learned_json jsonb`
- `confidence_json jsonb`
- `updated_at timestamptz`
- index `(tenant, person_id, updated_at desc)`

## Test mapping

### Host smokes

- `tests/smoke_sentinel_user_message.py`
  - sentinel user copy and throttle contracts
  - no internal deadlock phrasing leakage

- `tests/smoke_brief_dedupe_guard.py`
  - `/brief` in-flight + dedupe contract

- `tests/smoke_v1_18_1_runtime_alignment.py`
  - runtime alignment symbols + watchdog/brief dedupe knobs

- `tests/smoke_v1_19_future_intelligence_pack.py`
  - incoming v1.19 contract pack baseline

- `tests/smoke_v1_19_1_future_intelligence_expansion.py`
  - project/finance dossier + future/readiness/critical behavior

- `tests/smoke_v1_19_1_profile_persistence.py`
  - profile state persistence contracts
  - persisted-state merge behavior
  - runtime-confidence precedence over persisted confidence

- `tests/smoke_v1_19_1_llm_gateway_boundary.py`
  - prompt safety/redaction/length cap behavior
  - blocked output behavior for tool-like model responses
  - DB-audit write-path behavior (driver-free stubbed contract check)

- `tests/smoke_v1_19_2_human_assistant_mode.py`
  - diagnostics not appended to user chat
  - no raw score/salience phrasing in compose source

- `tests/smoke_v1_19_2_health_dossier.py`
  - health dossier detection/future/readiness/critical wiring

### End-to-end gates

- `scripts/docker_e2e.sh`
  - now includes the new v1.19.1 smoke step

- `tests/real_milestone_suite.py`
  - continues validating full staged milestone path through v1.19 + v1.12.6 chain

## Remaining gaps after v1.19.2

1. De-minify core control-plane files (`main.py`, `supervisor.py`, `briefings.py`, `scheduler.py`, `poll_listener.py`).
2. Expand dossier set with evidence-first dossier types.
3. Add policy lifecycle tooling for trust-boundary rules (authoring/review/audit UX).

## Release checklist

1. `python3 tests/smoke_v1_19_future_intelligence_pack.py`
2. `python3 tests/smoke_v1_19_1_future_intelligence_expansion.py`
3. `python3 tests/smoke_v1_19_1_profile_persistence.py`
4. `python3 tests/smoke_v1_19_1_llm_gateway_boundary.py`
5. `python3 tests/smoke_v1_19_2_human_assistant_mode.py`
6. `python3 tests/smoke_v1_19_2_missingness.py`
7. `python3 tests/smoke_v1_19_2_health_dossier.py`
8. `python3 tests/smoke_v1_19_2_snapshot_persistence.py`
9. `python3 tests/smoke_v1_19_2_household_dossier.py`
10. `python3 tests/smoke_v1_19_2_llm_egress_policy.py`
11. `python3 tests/smoke_v1_18_1_runtime_alignment.py`
12. `bash scripts/run_v119_smoke.sh /docker/EA`
13. `bash scripts/docker_e2e.sh`
