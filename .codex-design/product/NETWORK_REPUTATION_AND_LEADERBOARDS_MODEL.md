# Network reputation and leaderboards model

## Purpose

This file defines the gamified recognition layer for Open Runs, BLACK LEDGER, and the Shadowcasters Network.

The intended feeling is:

> The world remembers who made things happen.

## Design stance

Chummer should gamify contribution, reliability, and world impact.
It should not become a permanent popularity contest.

Preferred product language:

- seasonal honors
- reputation
- notoriety
- cred
- faction momentum
- intel value
- runner legend

Use `leaderboard` only for explicit seasonal views, not as the only framing.

## Canonical rule

Recognition must come from typed events and visible policies, not from opaque vibe scores.

The system must:

- separate human, runner, faction, and organizer identity
- prefer seasonal boards over permanent ladders
- explain why a subject appears on a board
- protect safety, moderation, and spoiler-sensitive data

## Reputation subjects

```yaml
reputation_subjects:
  gm_profile:
  player_profile:
  runner_dossier:
  faction:
  faction_seat:
  intel_contributor:
  creator_profile:
  organizer_profile:
```

No single universal score should collapse these into one number.

## Seasonal structure

Competitive views should be seasonal by default.

Why:

- lower intimidation for new users
- avoid permanent social hierarchy
- support organizer events and recap cycles
- make BLACK LEDGER feel alive instead of static

## Board families

Recommended board families:

- GM Honors
- Player Cred
- Runner Legends
- Faction Momentum
- Faction Manager Honors
- Intel Contributors
- Creator Spotlight

Each board should explain what it measures and which inputs count.

## Score model

Use multi-axis scorecards rather than one mysterious number.

Example axes:

- reliability
- table trust
- world impact
- onboarding
- creativity
- intel value
- public-safe legend

## Visibility model

```yaml
reputation_visibility:
  private:
  table_private:
  network_summary:
  public_safe:
  organizer_only:
```

Defaults:

- human-user scores start private or network-summary
- runner legend views are opt-in and spoiler-safe
- sensitive moderation or safety signals are never public

## Anti-toxicity rules

- no permanent global ladder at launch
- no public shame boards
- no single universal score
- no hidden punitive automation
- no pay-to-win boosts
- no direct Table Pulse or GOD public scoring
- no spoiler leakage
- no exploit farming through fake or trivial sessions

## Gamified loops

### GM loop

Open run -> recruit players -> run session -> close resolution -> earn trust and honors -> attract more players.

### Player loop

Join run -> show up prepared -> contribute -> debrief -> build cred -> qualify for better tables.

### Runner loop

Survive and affect the world -> appear in recap or news -> earn legend tags -> become part of Chummer world memory.

### Intel loop

Submit intel -> curator accepts it -> GM adopts it -> run happens -> contributor receives credit.

### Faction loop

Allocate resources -> generate tension -> sponsor jobs -> outcomes change the map -> faction momentum changes.

## First proof gate

**Seattle Season 001 Honors**

Includes:

1. private personal reputation page
2. GM honors categories
3. runner legend board
4. intel contributor board
5. faction momentum board
6. public-safe weekly recap

Success criterion:

> Users feel recognized for meaningful contribution without feeling ranked, exposed, or punished.
