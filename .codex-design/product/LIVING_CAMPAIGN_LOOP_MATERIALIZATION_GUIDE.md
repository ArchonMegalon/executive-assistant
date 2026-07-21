# Living Campaign Loop Materialization

**Product:** Chummer6 / SR Campaign OS
**Status:** Active overlay
**Purpose:** Turn the newer living-world and campaign-memory ideas into small, release-gated loops that users can feel in one session.

## Core rule

Chummer6 keeps Shadowrun understandable when the game gets complicated.

At campaign scale, that promise becomes:

> The world remembers what the runners did, and talks back through receipts.

This overlay does not replace the confidence/readiness/continuity center of gravity.
It makes that center of gravity playable across the campaign layer.

## Product discipline

Do not ship a broad "living sandbox" before the table can feel one tight loop.

Every living-world addition must answer:

1. What can a user do in 90 seconds?
2. What receipt proves it happened?
3. What changes in the next session?
4. What screen makes them want to come back?

## The prioritized loops

### 1. Live SR6 action economy and turn assist

The first lovable table loop is not social or media-heavy.
It is the moment Chummer tells a player or GM what that actor can still do right now.

See:

* `LIVE_ACTION_ECONOMY_AND_TURN_ASSIST.md`
* `LIVE_SESSION_TURN_COMPANION.md`
* `GM_RUNBOARD_LIVE_OPERATIONS.md`

### 2. Source anchors and local rulebook binding

Explain Everywhere should not stop at formulas.
Users should be able to open the cited local rulebook page from the explain drawer without cloud PDF upload or copyright blur.

See:

* `SOURCE_ANCHOR_AND_LOCAL_RULEBOOK_BINDING.md`

### 3. Campaign adoption wizard

Existing tables should not be forced to rebuild history before Chummer becomes useful.
Adoption must preserve unknowns explicitly and allow the ledger to start from today.

See:

* `CAMPAIGN_ADOPTION_WIZARD.md`

### 4. Runner resume and goal pins

The good kind of retention is identity, anticipation, and continuity.
Runner Resume and Goal Pins make a character's future visible without manipulative product mechanics.

See:

* `RUNNER_RESUME_AND_GOAL_PINS.md`

### 5. GM Runboard

Campaign Workspace is the long-lived lane.
GM Runboard is the live-play lane.
It exists to keep the next five minutes of play moving.

See:

* `GM_RUNBOARD_LIVE_OPERATIONS.md`

### 6. Prep Packet Factory

Procedural generation only matters if it becomes playable prep.
The first slice is one usable job packet, one legwork board, one opposition packet, one complication, and one resolution flow.

See:

* `PREP_PACKET_FACTORY_AND_PROCEDURAL_TABLES.md`

### 7. BLACK LEDGER MVP 001

BLACK LEDGER should first prove GM-approved consequence, not autonomous world simulation.
One run should be able to close, update pressure, and emit one player-safe news item.

See:

* `BLACK_LEDGER_MVP_001.md`

### 8. Crew fit and mission fit

Shadowrun is team-based.
The product should help tables understand strengths, gaps, and prep options without ranking or shaming builds.

See:

* `CREW_AND_MISSION_FIT_MODEL.md`

## Release-gated journeys

The next living-campaign proof should be release-gated as concrete journeys:

* player completes one SR6 combat round with action budget truth
* user opens a local rulebook page from the explain drawer
* existing campaign is adopted without rebuilding full historical provenance
* player pins an upgrade and sees progress after one reward event
* GM creates a playable prep packet
* GM closes a run with `ResolutionReport`
* approved resolution emits a `WorldTick`
* `WorldTick` emits one player-safe news item

## Repo posture

### `chummer6-core`

Own deterministic action budgets, source anchors, goal projections, crew fit vectors, mission fit checks, and world-linked deltas.

### `chummer6-ui`

Own desktop Explain Drawer, GM Runboard, Campaign Adoption Wizard, Runner Resume, Goal Pin workbench, and Prep Packet surfaces.

### `chummer6-mobile`

Own action cards, between-turn sheets, quick explain, goal progress cards, recap prompts, and the at-table heartbeat.

### `chummer6-hub`

Own shared campaign continuity, `ResolutionReport`, `WorldTick`, `JobPacket`, `OpenRun`, reputation events, and player-safe world feedback.

### `chummer6-hub-registry`

Own package and compatibility metadata, including source-anchor maps and governed prep/world overlay artifacts.

### `chummer6-media-factory`

Render recap cards, news cards, runner resume cards, and prep packet PDFs.
Rendered outputs never become truth.

### `fleet`

Turn the loops above into release-gated smoke and journey evidence.

## Rule

The living campaign layer is successful when it makes the table feel:

* confident in the current turn
* ready for the next session
* remembered after the run

If a proposed feature cannot be traced back to one of those outcomes, it is ahead of the product center of gravity.
