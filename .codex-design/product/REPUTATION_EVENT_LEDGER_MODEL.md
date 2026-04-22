# Reputation event ledger model

## Purpose

This file defines the typed event ledger behind Open Run reputation, seasonal honors, and public-safe recognition.

## Canonical rule

Reputation must come from typed, receipt-bearing events.

It must not come from:

- raw popularity
- hidden moderator vibes
- direct transcript scoring
- ad hoc manual boosts with no source object

## Typed source objects

Allowed source families:

- `OpenRun`
- `RunApplication`
- `RunRoster`
- `SchedulingReceipt`
- `ResolutionReport`
- `IntelReport`
- `WorldTick`
- `NewsReel`
- `FactionOperation`
- `ArtifactPublication`
- manual organizer award with receipt

## Event model

```yaml
reputation_event:
  id: rep_evt_0001
  subject_type: gm_profile
  subject_ref: user_gm_123
  category: closeout_timeliness
  season_ref: season_seattle_001
  source_type: resolution_report
  source_ref: rr_0001
  points: 3
  visibility: network_summary
```

## Seasonal board model

```yaml
seasonal_board:
  id: board_gm_honors_seattle_001
  subject_type: gm_profile
  ranking_policy: weighted_axes
  public_visibility: network_summary
```

## Badge model

```yaml
badge_award:
  id: badge_award_001
  badge_key: reliable_closeout
  subject_type: gm_profile
  subject_ref: user_gm_123
  visibility: public_safe
```

## Visibility and safety

Public reputation views must never expose:

- private GM notes
- raw rejection history
- safety reports
- hidden moderation context
- unreviewed player-lore spoilers

Table Pulse or GOD observer outputs may help draft private debriefs.
They must not directly assign public reputation events.

## Contract posture

Initial semantic owner:

- `chummer6-hub`

Near-term placement:

- adjacent to `Chummer.World.Contracts`

Potential later split:

- `Chummer.Reputation.Contracts`

That split is justified only if the seasonal-honors and network-recognition lane becomes large enough to deserve its own package family.
