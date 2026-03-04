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
