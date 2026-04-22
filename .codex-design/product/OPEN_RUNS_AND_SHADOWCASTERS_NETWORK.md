# Open runs and Shadowcasters Network

## Purpose

This file expands BLACK LEDGER from a world-state and mission-market model into a playable recruitment, scheduling, and closeout network.

The north-star is:

> A GM opens a run on the world map.
> Players see it, request to join with compatible runners, and get routed to the right session space.
> The table plays.
> The outcome changes the city.
> The newsreel talks back.

## Canonical rule

An `OpenRun` is Chummer-owned run-network truth.

That means:

- the listing is Chummer-owned
- join requests and accepted roster are Chummer-owned
- scheduling receipts are Chummer-owned
- meeting handoff policy is Chummer-owned
- observer consent is Chummer-owned
- world impact is Chummer-owned only after GM or organizer approval

Discord, Teams, calendar providers, and debrief tools may project or assist.
They must not become the authority for run existence, roster truth, consent truth, or world consequences.

## Core loop

`job packet -> open run -> join requests -> roster -> schedule -> meeting handoff -> play -> resolution -> world tick -> newsreel -> reputation event`

## Product move

BLACK LEDGER should not stop at “a job exists.”
It should be able to move the GM from job selection to table formation and back into world consequence.

The `Shadowcasters Network` is the governed discovery layer for that move.

It is not a random LFG board.
It is a Chummer-run mission network with:

- provenance on every run
- spoiler-safe listing surfaces
- runner-aware join requests
- configurable join policies
- Chummer-owned scheduling receipts
- policy-aware meeting handoff
- optional consent-gated observer and debrief assistance

## Practical focus

This lane should feel like a practical table-finding, prep, scheduling, and world-memory system before it ever feels like a prestige metagame.

The immediate user problems are:

- how to get into a game
- how to know which house rules or community rules apply
- how to join without a Windows-only setup
- how the GM gets quick opposition and prep help
- how the table gets into Discord, Teams, or a VTT without losing truth
- how the city remembers what happened afterward

If those are not solved, the living-world fantasy will not matter.

## Open run model

An `OpenRun` may originate from:

- a `JobPacket`
- a custom GM run
- a creator-published module
- a campaign-private prep item
- a season prompt
- a faction-seat generated mission seed

An `OpenRun` may be visible to:

- only the GM
- invited players
- one campaign group
- one organizer community
- the Shadowcasters Network
- a public preview cohort
- selected language or time-zone cohorts

## Join policy

Join policy should be composable, visible, and explainable to both GM and player.

```yaml
join_policy:
  admission:
    mode: request_to_join
    options:
      - open_auto_accept
      - request_to_join
      - invite_only
      - waitlist
      - organizer_curated
  roster:
    seats_total: 5
    seats_reserved:
      decker: 1
      face: 1
      magic: 1
  character:
    require_runner_dossier: true
    allow_quickstart_runner: true
    rule_environment_ref: sr6_shadowcasters_seattle
  schedule:
    scheduling_mode: lunacal_slots
    expected_duration_minutes: 240
  communication:
    platform: discord
    voice_required: true
  consent:
    safety_tool_ack_required: true
    god_observer:
      mode: opt_in_all_players
      fallback: manual_markers
```

Recommended presets:

- Beginner One-Shot
- Experienced Table
- Creator Playtest
- Season Canon Run
- Faction-Linked Run
- Streamer or Public Run
- Private Campaign Fill-In
- GM Training Table

Detailed presets live in `OPEN_RUN_POLICY_PRESETS.yaml`.

## Community rule environments

The biggest missing bridge between “cool world” and “usable community product” is the community-specific rule posture.

Every serious open-run lane needs a `CommunityRuleEnvironment` that can define:

- active base ruleset and package posture
- house-rule packs or amend packages
- banned or restricted content
- approval policy
- default join-policy posture
- allowed export targets

Detailed model: `COMMUNITY_RULE_ENVIRONMENTS_AND_APPROVAL.md`
Registry: `COMMUNITY_RULE_ENVIRONMENT_REGISTRY.yaml`

## Run application preflight

Joining a run should never be a blind “click and pray” flow.

Chummer should run an explainable preflight over:

- account claim
- runner dossier or quickstart selection
- legality under the active community rule environment
- role fit
- schedule overlap
- table-contract acknowledgement
- platform readiness
- conflicting run commitments

Detailed model: `RUN_APPLICATION_PREFLIGHT_MODEL.md`
Registry: `RUN_APPLICATION_PREFLIGHT_CHECKS.yaml`

## Quickstart runner path

Quickstart runners are a first-class participation path, especially for:

- new players
- mobile-only players
- beginner one-shots
- communities that require review before a full custom dossier can enter play

They must be governed, rule-environment aware, and convertible into living dossiers later.

Detailed model: `QUICKSTART_RUNNER_AND_PREGEN_FLOW.md`

## Session zero and table contract

Every open run needs a visible `TableContract` before roster lock.

That contract should make tone, safety, playstyle, logistics, and observer policy explicit enough that the player knows what they are joining.

Detailed model: `SESSION_ZERO_AND_TABLE_CONTRACT_MODEL.md`

## Meeting handoff

Meeting tools are projection lanes, not truth owners.

Supported posture:

- Discord channel or scheduled event
- Microsoft Teams meeting
- generic meeting URL
- deferred handoff after roster lock
- Foundry, Roll20, or another play surface as projection-only export targets

Chummer-owned truth:

- who was accepted
- which run they joined
- what access policy applies
- when the handoff should expire

Detailed export posture: `VTT_HANDOFF_AND_PLAY_SURFACE_EXPORTS.md`

## GOD observer policy

`G.O.D. Observer` is an optional assistant lane.
Product language may render the acronym as `Grid Observation Daemon` or `Game Operations Debrief` depending on tone.

Allowed modes:

- none
- manual markers
- post-session upload
- transcript assist
- live debrief assist

Hard rule:

> No observer joins or records unless the GM and all required accepted players explicitly consent for that run.

Allowed outputs:

- GM-private debrief
- player-safe recap
- unresolved objective list
- pacing notes
- `ResolutionReport` draft

Forbidden outputs:

- player scoring
- moderation verdicts
- automatic world truth
- automatic public recording

## GM prep and opposition

If SHADOWCASTERS NETWORK is useful, a GM should be able to move from listing to prep without opening a second planning system.

That means:

- quick opposition packets
- faction or heat-aware enemy bundles
- export-ready prep for play surfaces
- a beginner-GM-friendly prep path

Detailed model: `GM_OPPOSITION_LIBRARY_AND_PACKET_MODEL.md`
Registry: `OPPOSITION_PACKET_REGISTRY.yaml`

## Data model candidates

```yaml
open_run:
  id: openrun_001
  source:
    type: job_packet
    ref: job_azt_ritual_017
  visibility:
    audience: shadowcasters_network
    spoiler_class: player_safe
  community_rule_environment_ref: cre_shadowcasters_seattle_01
  join_policy_ref: jp_001
  table_contract_ref: tc_shadowcasters_beginner_001
  schedule:
    state: collecting_availability
    provider: lunacal
  meeting:
    handoff_state: hidden_until_acceptance
    provider: discord
  observer:
    policy: opt_in_all_players
  exports:
    - foundry
    - roll20
  quickstart_runner_refs:
    - qrp_shadowcasters_starter_decker
  lifecycle_state: published
```

```yaml
run_application:
  id: app_001
  open_run_ref: openrun_001
  applicant_ref: user_456
  runner_dossier_ref: dossier_789
  preflight_ref: rap_001
  state: pending_gm_review
```

```yaml
run_application_preflight:
  id: rap_001
  open_run_ref: openrun_001
  applicant_ref: user_456
  result: warn
  checks:
    community_rule_legality: pass
    roster_role_fit: warn
    table_contract_ack: pass
```

```yaml
meeting_handoff:
  id: mh_001
  open_run_ref: openrun_001
  provider: discord
  target_kind: guild_channel
  chummer_truth_owner: chummer6-hub
```

## Authority and contract posture

Initial posture:

- semantic owner: `chummer6-hub`
- primary consumers: `chummer6-ui`, `chummer6-mobile`, `executive-assistant`, `fleet`, `chummer6-media-factory`

These objects may begin adjacent to `Chummer.World.Contracts` while the BLACK LEDGER lane is still proving itself.
If the network layer grows into a durable product boundary, it is a legitimate candidate for a later split into `Chummer.Network.Contracts`.

## First proof gate

**Shadowcasters Open Run 001**

Includes:

1. one BLACK LEDGER job packet
2. one published open run on the map
3. one `CommunityRuleEnvironment`
4. player join requests tied to runner dossiers or quickstart runners
5. explainable join-policy and legality preflight
6. one table contract
7. roster acceptance and waitlist
8. one scheduling receipt
9. one meeting handoff receipt
10. one opposition packet
11. one resolution report
12. one world consequence
13. one player-safe recap
14. one first-time-GM-capable path

Success criterion:

> A GM can go from a world-linked job to a real, scheduled, staffed table and close it back into BLACK LEDGER without juggling disconnected rule, roster, prep, and scheduling systems.

The concrete vertical-slice definition lives in `SEATTLE_OPEN_RUN_001_VERTICAL_SLICE.md`.

> A GM can go from job seed to recruited table to scheduled session to world consequence without leaving Chummer as the organizing truth.

## Hard boundaries

- not a generic LFG board
- not calendar-owned run truth
- not meeting-platform-owned roster truth
- not default-on recording
- not Table Pulse or GOD scoring players
- not public shame or spoiler leakage
