# World map and intel economy model

## Purpose

This document expands BLACK LEDGER from a generic world-state idea into a concrete world map, intelligence, and mission-market product model.

The north-star is:

> The city remembers.
> Factions push.
> GMs choose from a living job board.
> Players can feed table lore into a governed world without losing trust.

This file is intentionally adjacent to `WORLD_STATE_AND_MISSION_MARKET_MODEL.md`.
That file defines the broader bounded context and contract family.
This file defines the map-facing, intel-facing, and user-facing loop.

## Canonical rule

BLACK LEDGER is a governed world-state and mission-market layer.
It is not a detached strategy game, not automatic canonization of player lore, and not calendar-owned run truth.

Every meaningful state change must stay:

- receipt-bearing
- visibility-scoped
- attributable to an authority path
- explainable to a GM, organizer, or later world operator

## Core loop

The operating loop is:

`faction pressure -> intel reports -> world tick -> job seeds -> GM adoption -> scheduled run -> resolution report -> map consequence -> newsreel -> next tick`

This is the product loop to validate before BLACK LEDGER expands into season-scale or faction-seat play.

## Practical rule

BLACK LEDGER should first prove that it is useful to a GM and player in the week before and after a session.

That means it should help with:

- finding a table
- understanding community rules
- staffing missing roles
- preparing opposition
- scheduling and handoff
- remembering consequences after the run

If it only produces abstract pressure and cool lore, it has not earned the right to widen.

## Product layers

### World map

The world map is the primary operational surface.
It must distinguish source class and truth grade instead of flattening everything into generic pins.

Map levels:

1. Global or metroplex layer
2. City layer
3. District layer
4. Runsite layer for adopted or published packets only

Marker classes:

```yaml
world_map_markers:
  planned_run:
    visibility: gm_or_campaign
    source: JobPacket
  completed_run:
    visibility: campaign_or_public_if_published
    source: ResolutionReport
  unresolved_intel:
    visibility: owner_or_reviewer
    source: IntelReport
  faction_operation:
    visibility: faction_seat_or_organizer
    source: OperationIntent
  public_news:
    visibility: public_or_campaign
    source: NewsReel
  world_pressure:
    visibility: campaign_or_public_summary
    source: DistrictPressure
  job_opportunity:
    visibility: gm
    source: JobSeed
  open_run_recruiting:
    visibility: audience_scoped
    source: OpenRun
  open_run_scheduled:
    visibility: accepted_players_or_allowed_audience
    source: OpenRun
  live_run:
    visibility: roster_or_operator
    source: OpenRun
```

Hard rule:
No map marker may exist as a dumb UI pin with no source object.

### Mission market

The mission market is the GM-facing layer generated from the world-state.

Inputs:

- faction resource allocation
- faction projects and special assets
- district pressure and heat
- adopted or reviewed intel
- previous run outcomes
- campaign needs
- organizer season goals
- creator or published packets

Outputs:

- `JobSeed`
- `JobPacket`
- `MissionMarketSummary`
- optional `BriefingBundle`
- optional `RunsitePacket`
- optional `NewsReel`

GM control remains central:

- adopt
- edit
- reject
- fork privately
- publish later through creator lanes

### Session calendar

Lunacal is the bounded human scheduling lane around a Chummer-owned `RunPlan`.

Lunacal may project:

- booking created
- booking rescheduled
- booking cancelled

Lunacal must not decide:

- whether a run exists
- whether a mission was adopted
- whether a world consequence fired
- whether a run succeeded

### Open runs and Community Hub

BLACK LEDGER can widen into a governed run-network layer.

That layer should let a GM:

- publish an `OpenRun` from a `JobPacket`, custom run, or creator module
- accept player join requests tied to runner dossiers
- apply explicit join-policy and rule-environment preflight
- hand accepted players off to Discord, Teams, or another meeting space
- close the run back into `ResolutionReport`, world-tick input, and newsreel candidates

The `Community Hub` is the discoverability and recruiting layer for those open runs.
It is not a generic public LFG board.

Practical bridges that make this lane usable:

- `CommunityRuleEnvironment` for community-specific legality and approval
- run-application preflight for explainable roster checks
- quickstart runner packs for beginner and mobile-first entry
- visible table contracts before roster lock
- opposition packets and prep bundles
- VTT and play-surface exports that remain projection-only

### Intelligence reports

Player and GM-submitted intelligence is the engagement engine.
It lets the table tell the city what it knows without turning raw submissions into canon.

Allowed submission classes:

- rumor
- field report
- district lore
- faction intel
- after-action consequence
- creator seed

Confidence ladder:

```yaml
intel_confidence:
  unverified:
    meaning: submitted but not reviewed
  reviewed:
    meaning: usable as fiction input
  corroborated:
    meaning: supported by more than one source or receipt
  adopted:
    meaning: accepted into a campaign or world frame
  canonized:
    meaning: official truth for a Chummer-operated world frame
  false_flag:
    meaning: intentionally used as misinformation or propaganda
```

Hard rule:
Intelligence is not world truth until an authorized GM, organizer, curator, or world operator adopts it through a governed path.

Detailed contribution loop: `WORLD_INTEL_CONTRIBUTION_AND_REVIEW_POLICY.md`
Detailed state registry: `INTEL_REPORT_REVIEW_STATES.yaml`

### World tick

The world tick is the recurring resolution cycle that advances the world frame.

Inputs:

- `OperationIntent`
- faction resource allocation
- research progress
- district heat and pressure
- adopted intel
- completed run outcomes
- scheduled runs
- unresolved clocks
- organizer season goals

Outputs:

- district pressure changes
- new job seeds
- faction resource updates
- research progress
- special asset availability
- newsreel candidates
- campaign workspace cues

Cadence options:

- weekly for living-world seasons
- per-session for private campaigns
- monthly for low-maintenance worlds
- manual for GM-only mode

### Newsreels and city ticker

The world needs to talk back.
Each approved tick can produce:

- short city headlines
- faction propaganda
- public rumors
- corp denials
- emergency alerts
- player-safe recaps
- GM-only incident summaries
- short host videos
- ticker cards
- printable city bulletins

All news items must carry an approved visibility grade and a truth link back to their source object.

## World memory

The practical promise is not just that the city moves.
It is that the city remembers in visible, usable ways:

- completed run markers
- changed district pressure
- player-safe recap artifacts
- adopted intel contributions
- city-ticker outputs that point back to governed source objects

### Seasonal honors and runner legends

An optional recognition layer may sit on top of the network:

- GM honors
- player cred
- runner legends
- faction momentum
- intel contributor honors

That layer must stay seasonal, typed-event-based, and public-safe.
It must not become a permanent global popularity ladder.

## Heat and pressure

Heat is the pressure engine that keeps the city feeling reactive instead of static.

Minimum heat tracks:

```yaml
heat_profile:
  crew_heat:
    meaning: how visible one runner crew is
  sponsor_heat:
    meaning: how much scrutiny a sponsor or faction is drawing
  district_heat:
    meaning: how tense a region is
  public_heat:
    meaning: media and legal attention
  matrix_heat:
    meaning: data or host escalation
  occult_heat:
    meaning: ritual or astral escalation
  security_heat:
    meaning: physical security escalation
```

Heat may produce:

- new job seeds
- enemy asset deployment
- reward restrictions
- player-safe warnings
- city ticker headlines
- faction vulnerabilities
- campaign consequences

## Authority and ownership

`chummer6-hub` owns the bounded context first:

- world-state truth
- map projections
- mission market projections
- intel intake
- run scheduling receipts
- world tick state
- organizer and faction-seat access

`fleet` may automate tick packets, evidence, and validation, but it does not own world truth.

`executive-assistant` may synthesize headlines, packet variants, and voice packs, but it does not own mission or world truth.

`chummer6-media-factory` renders outputs, but it does not own world or intel truth.

`chummer6-ui` and `chummer6-mobile` own the user-facing map, job-board, reporting, and companion surfaces.

## First proof gate

The first implementation package should stay deliberately narrow:

**Seattle Tick 001**

Includes:

1. one world frame
2. five districts
3. three factions
4. ten manual pressure markers
5. five user-submitted intel reports
6. one world tick
7. six generated job seeds
8. three adopted GM jobs
9. one Lunacal scheduled session
10. one resolution report
11. one public-safe ticker
12. one short city update
13. one share card

Success criterion:

> A GM can open the map, understand why a job exists, schedule it, report the result, and watch the world change.

## Non-goals before proof

Do not front-load these before the vertical slice proves value:

- faction-seat monetization
- overbuilt strategic simulation
- passive surveillance
- automatic player-lore canonization
- public spoiler-rich city news
- calendar-owned run truth

BLACK LEDGER should first prove that GMs get better prep, players care that the city remembers, and the world loop remains governed.
