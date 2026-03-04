# EA OS v1.13 Design: Profile Intelligence Core

Date: 2026-03-04  
Status: Draft -> Implementation Started

## Design Sentence
EA OS evolves from source summarization into a profile-driven intelligence system
that maintains commitments, risks, dossiers, and decision windows per person.

## Problem
Raw source summaries (`recent mail + calendar`) are not sufficient to protect
high-impact commitments. Noise suppression can hide expensive or time-sensitive
exposure if no deterministic critical lane exists.

## Core Model

### 1) Layered Person Profile
- Stable profile: tone, urgency tolerance, noise mode, spending sensitivity.
- Situational profile: current mode, timezone, location hints.
- Learned profile: source and domain preferences (future expansion).
- Confidence profile: runtime/data confidence and degraded-state note.

### 2) Dossiers
- Domain objects that aggregate multi-source evidence before composition.
- Initial implemented dossier type: `Trip Dossier`.
- Future dossier types: health, finance commitment, project, household ops.

### 3) Critical Action Lane
- Deterministic pass that runs before normal briefing composition.
- Inputs: profile context + dossiers.
- Outputs: immediate actions, evidence, exposure score, decision-window score.
- This lane is independent from LLM ranking taste.

## Contracts Added (v1.13 core)
- `app/intelligence/profile.py`
  - `PersonProfileContext`
  - `build_profile_context(...)`
- `app/intelligence/dossiers.py`
  - `Dossier`
  - `build_trip_dossier(...)`
- `app/intelligence/critical_lane.py`
  - `CriticalLaneResult`
  - `build_critical_actions(...)`
- `app/intelligence/household_graph.py`
  - `HouseholdGraph`
  - `build_household_graph(...)`
  - `ensure_profile_isolation(...)`
- `app/intelligence/modes.py`
  - `select_briefing_mode(...)`
  - `mode_label(...)`
- `app/intelligence/future_situations.py`
  - `FutureSituation`
  - `build_future_situations(...)`
- `app/intelligence/readiness.py`
  - `ReadinessDossier`
  - `build_readiness_dossier(...)`
- `app/intelligence/scores.py`
  - `exposure_score(...)`
  - `decision_window_score(...)`
  - `readiness_score(...)`
  - `priority_score(...)`
- `app/intelligence/preparation_planner.py`
  - `PreparationPlan`
  - `build_preparation_plan(...)`

## Runtime Integration (implemented)
- `app/briefings.py` now:
  - builds profile context,
  - builds household graph and validates profile isolation invariant,
  - builds trip dossier,
  - builds future situations and readiness dossier,
  - builds deterministic preparation plan,
  - runs critical lane,
  - selects compose mode (`standard`, `travel_mode`, `risk_mode`, `low_confidence`),
  - renders `Immediate Action` and preparation/readiness blocks before normal summary blocks.
- User-facing diagnostics remain hidden by default unless
  `EA_BRIEFING_DIAGNOSTIC_TO_CHAT=true`.

## Guardrails / Invariants
1. No “nothing urgent” certainty when confidence is degraded.
2. Critical lane must run before LLM-composed summary.
3. Person profiles remain person-scoped; household sharing is explicit.
4. Critical lane remains deterministic and transparent.
5. Raw internal diagnostics are not shown in normal user copy.

## Config Knobs
- `EA_CRITICAL_TRAVEL_EUR_THRESHOLD` (default `5000`)
- `EA_CRITICAL_TRAVEL_WINDOW_HOURS` (default `72`)
- `EA_TRAVEL_RISK_KEYWORDS` (optional comma-separated extension)
- `EA_BRIEFING_CONFIDENCE_DEGRADE_WINDOW_SEC` (default `21600`)
- `EA_BRIEFING_DIAGNOSTIC_TO_CHAT` (default `false`)

## Next Steps
1. Add household graph contract and ownership resolution boundaries.
2. Add dossier registry (trip/health/finance/project) with typed builders.
3. Add epic-link contract so dossiers feed long-running narrative threads. (Delivered in v1.14 contract layer.)
4. Add action typing layer on top of critical lane outputs.
