# BLACK LEDGER

## The problem

Campaigns can feel sealed off from each other, the city rarely pushes back on its own, and GMs often have to invent heat, corp agendas, district pressure, opposition, and fresh jobs from nothing between sessions.

## What it would do

BLACK LEDGER would add a governed world map and mission-market layer above the campaign spine. District pressure, reviewed intel, faction projects, and completed runs would feed a living GM job board, planned and completed run markers, practical prep hooks, and player-safe city news without taking campaign authority away from the GM.

The public fantasy is:

> The city keeps scheming between sessions, and every run changes who owns tomorrow.

## Expansion shape

BLACK LEDGER should grow as a world-state and mission-market layer, not as a detached strategy minigame.

The core loop is:

`faction pressure -> intel reports -> world tick -> job seeds -> GM adoption -> scheduled run -> resolution report -> map consequence -> newsreel -> next tick`

The first proof should stay narrow:

- one world frame
- a governed world map
- reviewed intel intake
- one world tick
- a GM mission market
- opposition and prep hooks tied to world pressure
- scheduling projection tied to a Chummer-owned `RunPlan`
- at least one player-safe city ticker output

## Product surfaces

The horizon now explicitly targets:

- a layered world map with source-aware markers
- a GM-facing mission market
- reviewed intelligence reporting
- practical world-memory surfaces that show what changed after a run
- prep-oriented outputs such as likely opposition and district-pressure hooks
- world-tick operator workflows
- public-safe, campaign-safe, and GM-rich newsreel variants
- later faction-seat play only after GM value is proven

## Hard boundaries

- not a VTT replacement
- not passive table surveillance
- not automatic lore canonization
- not calendar-owned run truth
- not pay-to-win faction control
- not external-tool-owned world state

## Companion design files

- `products/chummer/WORLD_STATE_AND_MISSION_MARKET_MODEL.md`
- `products/chummer/WORLD_MAP_AND_INTEL_ECONOMY_MODEL.md`
- `products/chummer/WORLD_CONTRACTS_RESERVED.md`
- `products/chummer/INTEL_REPORTING_AND_LORE_CONTRIBUTION_POLICY.md`
- `products/chummer/WORLD_TICK_OPERATOR_PROCESS.md`
- `products/chummer/NEWSREEL_AND_CITY_TICKER_MODEL.md`
- `products/chummer/BLACK_LEDGER_MAP_AND_NEWSREEL_WORKFLOWS.yaml`

## Likely owners

* `chummer6-hub`
* `chummer6-ui`
* `chummer6-mobile`
* `executive-assistant`
* `chummer6-media-factory`

## Key tool posture

* `vidBoard` - faction host, ticker, and mission-brief video lane
* `MarkupGo` - world packet and mission dossier render support
* `PeekShot` - city ticker card and mission preview support
* `Soundmadeseen` - optional narration lane
* `Unmixr AI` - bounded candidate voice lane until proven
* `MetaSurvey` - organizer and GM balancing feedback lane
* `ApproveThis` - bounded approval gate for public-safe season and artifact publication

Additional bounded lanes this horizon can use once the first operator slice exists:

* `Lunacal` - scheduling projection for planned runs, never run truth
* `Deftform` - structured intel intake
* `FacePop` - public-safe concierge entry into intel and pilot-world onboarding
* `NextStep` - world-tick operator process runner
* `Taja` - approved short-form repurposing after publication approval
* `Signitic` - bounded outbound CTA amplification to first-party world pages
* `Icanpreneur` - discovery and validation for world/operator demand, never runtime truth

## What has to be true first

* campaign truth and world truth stay separate, with the GM still deciding what becomes real for one table
* world-linked offers, pressure, and consequences stay receipt-backed instead of becoming invisible simulation drift
* organizer, GM, curator, and later faction-seat authority are clearly separated
* scheduling, resolution, and publication outputs never outrank run truth or leak private state
* player-safe city news can be published without letting synthesis or media lanes become canonical truth

## Hard boundary

* not a detached 4X that ignores campaigns
* not a forced global metagame for every table
* not automatic world truth from audio, summaries, or surveillance
* not hidden rules mutation outside explicit packages, offers, or receipts
* not a loophole for AI to become campaign or rules authority

## Why it is not ready yet

This only works if Chummer can prove three things at once:
1. campaigns stay the center of play instead of becoming subordinate to a metagame,
2. world-linked pressure, jobs, prep hooks, and rewards stay inspectable through receipts and approvals,
3. organizer, GM, and future manager-player authority are separated cleanly enough that the city feels alive without becoming arbitrary.

The first proof gate should be a deliberately small vertical slice rather than a full simulation:

> A GM can open the map, understand why a job exists, get usable prep from it, schedule it, report the result, and watch the world change.

That first proof is not a giant faction simulator.
It is one city, one tick, one adopted job, one scheduled session, one reported outcome, and one visible consequence.

Until those seams are trustworthy, BLACK LEDGER should stay a horizon rather than a shipment promise.
