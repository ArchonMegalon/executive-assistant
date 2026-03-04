# EA OS Change Guide for Dev v1.12.7

Date: 2026-03-04
Baseline commit: 476141f

## Purpose
This guide starts from the post-ingress-fix runtime and captures the hardening patchset needed for guarded rollout.

## What changed in this wave

1. BrowserAct HTTP ingress hygiene
- `tests/e2e_browseract_http_ingress.py` now uses `browseract.http_ingress_test` only.
- This avoids synthetic AvoMap payloads being consumed as failed finalize jobs.

2. True full-chain E2E added
- New `tests/e2e_browseract_http_to_ready_asset.py` validates:
  - HTTP webhook acceptance
  - durable `external_events` persistence
  - event worker processing
  - AvoMap ready asset availability
- Wired into `scripts/run_v126_smoke.sh` and `scripts/docker_e2e_design_workflows.sh`.

3. Prewarm timezone window fix
- `ea/app/scheduler.py` now derives tomorrow from local timezone (`settings.tz`) and converts that local-day window to UTC for DB queries.
- This removes midnight-edge drift between local scheduler hour and UTC window boundaries.

4. Late-attach delivery mode option
- `ea/app/intake/browseract.py` supports `EA_AVOMAP_LATE_ATTACH_MODE`:
  - `link` (default): HTML link message
  - `video` / `sendvideo` / `native`: outbox sends Telegram `sendVideo`
- `ea/app/roles/outbox.py` now handles payload type `video`.

5. Detector/day-context quality improvement
- `ea/app/integrations/avomap/service.py` improves city extraction and travel signal detection:
  - avoids country-tail misclassification
  - strips travel prefixes like `Flight to ...`
  - avoids using non-travel generic titles as route stops
  - adds calendar-derived travel hints
- Added regression in `tests/smoke_v1_12_6.py::test_day_context_quality`.

6. Deterministic critical-commitment lane (must-never-miss)
- `ea/app/briefings.py` now runs a deterministic pre-LLM critical scan for:
  - high-value travel commitment signals,
  - route/layover risk keywords,
  - near-term travel windows.
- Briefings now render an **Immediate Action** block before normal summary content when critical signals are present.
- Added runtime confidence degradation notice when recent sentinel auto-recovery was observed.
- User-facing diagnostics are now hidden by default and only shown if `EA_BRIEFING_DIAGNOSTIC_TO_CHAT=true`.
- Added host smoke guard `tests/smoke_v1_12_6.py::test_critical_commitment_lane_wiring`.

## New/updated tests
- `tests/e2e_browseract_http_to_ready_asset.py` (new)
- `tests/e2e_browseract_http_ingress.py` (updated)
- `tests/smoke_v1_12_6_avomap.py` (new guards)
- `tests/smoke_v1_12_6.py` (new day-context quality test)
- `tests/smoke_outbox_entity_fallback.py` (sendVideo branch guard)

## Runtime notes
- If ingest token is missing, HTTP ingress E2Es will print `SKIP` by design.
- To enable native video late attach:
  - set `EA_AVOMAP_LATE_ATTACH_MODE=video`
- Default late-attach mode remains link-only for conservative rollout.
- New knobs for critical lane:
  - `EA_CRITICAL_TRAVEL_EUR_THRESHOLD` (default `5000`)
  - `EA_CRITICAL_TRAVEL_WINDOW_HOURS` (default `72`)
  - `EA_TRAVEL_RISK_KEYWORDS` (optional comma-separated override/extension)
  - `EA_BRIEFING_CONFIDENCE_DEGRADE_WINDOW_SEC` (default `21600`)
  - `EA_BRIEFING_DIAGNOSTIC_TO_CHAT` (default `false`)

## Guarded rollout checklist
1. Set ingest auth token in runtime (`EA_INGEST_TOKEN` or `APIXDRIVE_SHARED_SECRET`).
2. Keep `AVOMAP_ENABLED=true` only for pilot tenants.
3. Run:
   - `python3 tests/smoke_v1_12_6.py`
   - `python3 tests/smoke_v1_12_7_contract_freeze.py`
   - `bash scripts/run_v126_smoke.sh`
4. Confirm `e2e_browseract_http_to_ready_asset.py` is `PASS` (not `SKIP`) in staging/prod-like env.
