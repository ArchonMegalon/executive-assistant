# World state and mission market model

## Purpose

This file defines the next major layer above the campaign spine: a persistent world-state and mission-market system that lets the city keep scheming between sessions without replacing the campaign workspace, deterministic rules truth, or GM authority.

The product promise is:

> Chummer should be able to remember not only one runner and one campaign, but the larger power struggle that generates pressure, opportunities, rewards, and consequences around them.

This layer is the path from **campaign OS** to **living Shadowrun world engine**.

Companion BLACK LEDGER files:

- `WORLD_MAP_AND_INTEL_ECONOMY_MODEL.md`
- `WORLD_CONTRACTS_RESERVED.md`
- `INTEL_REPORTING_AND_LORE_CONTRIBUTION_POLICY.md`
- `WORLD_INTEL_CONTRIBUTION_AND_REVIEW_POLICY.md`
- `WORLD_TICK_OPERATOR_PROCESS.md`
- `NEWSREEL_AND_CITY_TICKER_MODEL.md`
- `BLACK_LEDGER_MAP_AND_NEWSREEL_WORKFLOWS.yaml`
- `OPEN_RUNS_AND_COMMUNITY_HUB.md`
- `COMMUNITY_RULE_ENVIRONMENTS_AND_APPROVAL.md`
- `RUN_APPLICATION_PREFLIGHT_MODEL.md`
- `QUICKSTART_RUNNER_AND_PREGEN_FLOW.md`
- `GM_OPPOSITION_LIBRARY_AND_PACKET_MODEL.md`
- `VTT_HANDOFF_AND_PLAY_SURFACE_EXPORTS.md`
- `SESSION_ZERO_AND_TABLE_CONTRACT_MODEL.md`
- `BEGINNER_GM_AUTOPILOT.md`
- `SEATTLE_OPEN_RUN_001_VERTICAL_SLICE.md`
- `NETWORK_REPUTATION_AND_LEADERBOARDS_MODEL.md`
- `SEASONAL_HONORS_AND_REPUTATION_MODEL.md`
- `REPUTATION_EVENT_LEDGER_MODEL.md`
- `SEASONAL_HONORS_REGISTRY.yaml`
- `OPEN_RUNS_REPUTATION_AND_SEASONAL_HONORS.yaml`
- `OPEN_RUN_POLICY_PRESETS.yaml`
- `COMMUNITY_RULE_ENVIRONMENT_REGISTRY.yaml`
- `RUN_APPLICATION_PREFLIGHT_CHECKS.yaml`
- `OPPOSITION_PACKET_REGISTRY.yaml`
- `VTT_EXPORT_TARGETS.yaml`
- `INTEL_REPORT_REVIEW_STATES.yaml`

## Canonical principle

World state feeds campaigns. It does not replace campaigns.

The world layer must:

- generate pressure, conflict, and opportunity that campaigns can consume
- make corp, syndicate, cult, and district identity feel real over time
- surface consequences in run descriptions, rewards, opposition, and availability
- support later open-run recruitment, scheduling, and closeout loops without making third-party tools authoritative
- let organizers and later manager-players shape the city asynchronously
- preserve GM curation and campaign-local intent

The world layer must not:

- become a detached strategy minigame with no effect on active campaigns
- silently mutate rules truth outside explicit rule-environment or package receipts
- replace the GM as final owner of one campaign's actual run choice or outcome
- turn audio analysis, AI summaries, or operator speculation into canonical world truth
- require every table to participate in a shared global metagame

## Product move

Chummer adds a governed world-state plane that can:

- track factions, districts, projects, pressure, and strategic assets
- resolve a periodic world tick
- produce job seeds and curated GM-ready job packets
- attach practical prep hooks such as opposition packets, quickstart paths, and world-memory outputs
- accept GM-approved resolution reports after runs
- feed campaign workspaces, artifact generation, and creator publication
- later support open-run discovery, community rule environments, quickstart entry, roster fit, meeting handoff, and seasonal honors
- later support opt-in human faction seats and organizer-operated seasons

The public-facing fantasy is:

> The city keeps moving between sessions.  
> Megacorps, syndicates, cults, and other power blocs spend resources, launch projects, create pressure, and generate jobs.  
> GMs do not have to invent all tension from a blank page anymore — they curate it.

The loop should now be considered explicit:

`faction pressure -> intel reports -> world tick -> job seeds -> GM adoption -> scheduled run -> resolution report -> map consequence -> newsreel -> next tick`

## Why this belongs in Chummer

The current product already has the right lower layers:

- campaign spine truth for dossier, crew, campaign, run, scene, and objective
- rule-environment truth for package, preset, amend, and activation receipts
- campaign workspace projections for “what changed for me?” and “what is safe to do next?”
- creator/publication lanes for dossiers, briefings, recaps, primers, and artifacts
- organizer/community substrate for groups, capability flags, and season-style operations

The missing step is a world plane that can create pressure across campaigns instead of leaving every campaign isolated.

## Audience

### Runner players

Need a world that feels alive:
- corp feuds create better jobs
- district pressure changes what the crew walks into
- rewards and enemy posture feel like consequences, not random loot tables
- the campaign remembers who is hunting them

### GMs

Need a job board and consequence engine:
- sponsors
- targets
- pressure tags
- likely opposition
- district context
- reward posture
- “what changes on success / failure”
- quick prep packets instead of blank-page prep

### Organizers

Need a shared-city control layer:
- seasonal or community-wide world state
- campaign-local curation on top of shared tension
- district, faction, and event operations
- guardrails for fairness and continuity

### Manager players

Need a second game to identify with:
- one faction seat
- limited strategic resources
- projects and covert operations
- corp identity and special capabilities
- long-horizon influence without direct table railroading

## Canonical domain objects

This layer should become a new shared contract family:

**`Chummer.World.Contracts`**

It should not be folded into `Chummer.Campaign.Contracts` or `Chummer.Control.Contracts`.

The reserved first-wave object family now also explicitly includes:

- `Region`
- `WorldMapMarker`
- `HeatProfile`
- `IntelReport`
- `IntelReviewDecision`
- `RunPlan`
- `NewsReel`
- `NewsReelItem`
- `WorldContributionCredit`

Those reservations are expanded in `WORLD_CONTRACTS_RESERVED.md`.

Open-run and seasonal-honor objects may begin adjacent to this world family while BLACK LEDGER is still proving itself:

- `OpenRun`
- `JoinPolicy`
- `RunApplication`
- `RunApplicationPreflight`
- `MeetingHandoff`
- `ObserverConsent`
- `TableContract`
- `QuickstartRunnerPack`
- `OppositionPacket`
- `ReputationEvent`
- `SeasonalBoard`
- `BadgeAward`

If those lanes become large enough to deserve their own package families later, the likely pressure points are `Chummer.Network.Contracts` and `Chummer.Reputation.Contracts`.

### `WorldFrame`

The bounded world instance that one organizer, one city, or one season operates inside.

Carries:
- world identity
- fiction scope (city, season, edition, rules posture)
- active factions
- district map and pressure model
- tick cadence
- governance mode
- publication and visibility rules

### `Faction`

A persistent power bloc with identity, doctrine, and strategic posture.

Carries:
- display identity and art refs
- doctrine and flavor pack
- default resource mix
- corp or power-bloc capabilities
- legal / magical / matrix / public influence posture
- approved special asset catalog
- research tree refs

### `FactionSeat`

The controllable position inside one `WorldFrame`.

Carries:
- seat owner type (`system`, `organizer`, `human_manager`, `gm_proxy`)
- seat permissions
- faction budget
- current projects
- active operations
- cooldowns, debt, and risk posture

### `DistrictPressure`

The world-state summary for one district or region.

Carries:
- district identity
- security pressure
- public pressure
- matrix pressure
- occult pressure
- faction influence map
- opportunity tags
- instability / lockdown state

### `StrategicResourcePool`

The spendable strategic budget for a faction seat.

Minimum channels:
- capital
- influence
- matrix
- arcana
- security
- research

### `ResearchProject`

A long-lived project that can unlock:
- special assets
- scenario modifiers
- availability offers
- faction-specific response patterns
- campaign packages or world tags

### `SpecialAsset`

A faction capability that can appear in job packets or world resolution.

Examples:
- HTR team
- ritual cell
- PR black-site team
- prototype cyberware line
- awakened drone pack
- district surveillance sweep

### `OperationIntent`

A declared strategic move for one tick.

Examples:
- expand influence in district
- sabotage rival logistics
- accelerate ritual project
- buy legal cover
- harden host grid
- recruit black clinic network

### `JobSeed`

A machine-facing opportunity generated by world-state interaction.

Carries:
- sponsor candidate
- target candidate
- district
- trigger reason
- urgency
- reward class
- risk classes
- prerequisite pressure tags

### `JobPacket`

The GM-facing curated mission opportunity compiled from one or more `JobSeed`s.

Carries:
- sponsor
- target
- district
- pressure tags
- likely opposition
- urgency
- reward offer
- “what changes on success”
- “what changes on failure”
- artifact refs for briefing, host clip, and packet shelf
- campaign fit hints
- rule-environment and package implications

### `ResolutionReport`

The approved outcome of a run that feeds the world layer back.

Carries:
- linked campaign and run refs
- outcome class (`success`, `failure`, `mixed`, `abort`, `unexpected`)
- collateral posture
- exposure / visibility
- casualties
- recovered or lost artifacts
- sponsor trust delta
- district impact delta
- optional operator or GM notes
- approval and publication posture

### `WorldTick`

One bounded resolution cycle for a `WorldFrame`.

Carries:
- tick identity and cadence
- participating seat states
- randomization or event-seed refs if used
- generated deltas
- generated `JobSeed`s
- resulting district pressure changes
- publication-safe ticker summary

### `HeatProfile`

The canonical pressure posture for one campaign, crew, district, or faction interaction.

This must not be one number.

Minimum channels:
- crew heat
- sponsor heat
- district heat
- public heat
- occult heat
- matrix heat

## Ownership split

### `chummer6-hub`
Owns:
- world frame truth
- faction, seat, district, tick, job seed, job packet, and resolution report truth
- organizer and seat permissions
- mission-market projections
- campaign-to-world linkage
- publication-safe world summaries

### `chummer6-core`
Owns:
- deterministic mechanics and explain receipts
- explicit runtime effect of world-linked packages, offers, or modifiers once activated

Must not own:
- faction identity or world governance
- district pressure truth
- manager-seat logic
- mission-market truth

### `chummer6-ui`
Owns:
- workbench and desktop projections of the board
- campaign workspace projections of world pressure
- GM packet curation and runboard integration
- player-facing view of what world state changes mean for this dossier or campaign

### `chummer6-mobile`
Owns:
- player/GM mobile projections
- lightweight “what changed” world state views
- explicit scene markers and later debrief-safe links
- campaign-safe world pressure and mission brief access

### `executive-assistant`
Owns:
- bounded job-packet compilation aids
- city ticker prose
- faction voice / tone packs
- briefing and media brief prep downstream of approved facts

Must not own:
- world truth
- campaign truth
- final outcome authority

### `chummer6-media-factory`
Owns:
- optional briefing reels
- district or faction host clips
- mission cards, ticker cards, and packet media receipts

## The game loop

### 1. Seat planning

Each seat spends a bounded strategic budget for a world tick.

Required choices:
- one public initiative
- one covert operation
- one research or asset posture
- one district or target focus

This must stay legible enough for a GM or organizer to reason about.

### 2. World tick resolution

The world engine resolves:
- project progress
- collisions between operations
- district pressure changes
- faction leverage changes
- new opportunity creation
- new threat or reward posture

### 3. Job market compilation

The system compiles `JobSeed`s into GM-facing `JobPacket`s.

A GM should never be forced to run them in raw generated form.

GM packet curation must stay first-class:
- choose
- reject
- combine
- soften
- escalate
- localize to campaign reality

### 4. Campaign run execution

The selected packet becomes a normal campaign run:
- linked to campaign, crew, run, and objectives
- surfaced in the campaign workspace and artifact pipeline
- compatible with runboard, recap, and dossier continuity

### 5. Resolution report

After the run, the GM files a `ResolutionReport`.

The report feeds:
- sponsor trust deltas
- district pressure changes
- faction project setbacks or gains
- unlocked or blocked future opportunities
- public-safe artifacts and ticker summaries where allowed

## Heat model

Heat is a first-class world mechanic because it is what makes the city push back.

### Why heat matters

Heat creates:
- stronger identity
- visible consequence
- faction asymmetry
- better mission variety
- continuity between jobs

### Minimum heat channels

#### `CrewHeat`
How visible and hunted the runners are.

May unlock:
- bounty attention
- extra checkpoints
- sponsor caution
- dossier warnings

#### `SponsorHeat`
How much attention the sponsor is drawing.

May unlock:
- sponsor deniability shifts
- underfunded reward offers
- scapegoat operations
- legal or PR blowback

#### `DistrictHeat`
How tense, militarized, unstable, or watched the area is.

May unlock:
- checkpoints
- lockdowns
- surveillance density
- route and extraction constraints

#### `PublicHeat`
How much media, politics, and public narrative attention is building.

May unlock:
- narrative spin
- legal pressure
- public rewards or penalties
- exposure-sensitive modifiers

#### `OccultHeat`
How much ritual, spirit, blood-magic, or astral pressure exists.

May unlock:
- ritual clocks
- watcher-spirit density
- awakened opposition
- weirdness tags in mission packets

#### `MatrixHeat`
How hard local hosts, IC, spider teams, and digital tracing are reacting.

May unlock:
- hostile host behavior
- matrix traps
- hardened access posture
- decker-targeted opposition

## Faction identity

Faction seats must not feel like generic resource boards wearing different logos.

Each faction should carry:
- doctrine
- resource strengths
- preferred operation patterns
- signature response assets
- signature reward offers
- signature complications

Example posture:
- Renraku: matrix pressure, lockdowns, drones
- Aztechnology: ritual pressure, sacrificial plots, occult escalation
- Horizon: public narrative, social cover, PR blowback
- Saeder-Krupp: capital, elite assets, legal intimidation
- Evo: biotech, transhuman projects, black-clinic access
- Mitsuhama: hybrid tech-magic projects, covert labs
- Wuxing: logistics, trade lanes, elemental and feng-shui posture
- Shiawase: infrastructure, energy, utility leverage

## Interaction with rule environments

World state must never silently mutate the meaning of a build.

The rule-environment system remains the only path for package, preset, amend, and activation truth.

World-state outcomes may unlock or influence:
- availability offers
- scenario modifiers
- campaign packages
- threat tags
- district package overlays
- faction-themed reward packages

But every such effect must surface as:
- an explicit package, modifier, or offer
- a visible rule-environment or activation receipt change
- a visible mission or campaign note about what changed and why

Examples:
- “Prototype cranial deck line available through Renraku black channel”
- “Aztechnology blood rite active: ritual countdown modifier applied”
- “Mitsuhama awakened drone field-test package available in this district”
- “Horizon PR shield lowers immediate public heat but increases narrative blowback later”

## GM job board

The board is the main projection surface.

A GM should see jobs like:
- sponsor
- target
- district
- urgency
- likely opposition
- heat posture
- reward offer
- special faction twist
- what changes on success
- what changes on failure
- campaign fit
- artifact availability (briefing, host clip, packet)

The board must help, not railroad.

The rule is:

> The world engine creates tension.  
> The GM still curates the actual story entry point.

## Organizer and manager-player modes

### Phase 1: GM-only world engine
- no human faction seats
- one GM or organizer can run the world privately
- mission board feeds campaigns

### Phase 2: shared-city organizer mode
- multiple campaigns share one city frame
- one organizer manages world ticks
- GMs pull from shared tension

### Phase 3: human faction seats
- selected users control factions asynchronously
- seat permissions remain bounded
- no direct campaign override

### Phase 4: season and public media layer
- city ticker
- corp propaganda
- season summaries
- artifact shelves
- public-safe recap and league outputs

## EA and companion integration

EA should help with:
- city ticker prose
- GM packet variants
- faction voice packs
- “what changed” summaries
- media brief generation
- workload balancing suggestions for organizers

The Chummer companion should be able to react to:
- new job packet availability
- district pressure spikes
- faction project completion
- new reward / threat offers
- post-run world consequences

But all meaningful facts still come from Hub-owned world truth.

## Publication and wow factor

This layer becomes much more compelling when it emits artifacts.

High-value artifact families:
- city ticker cards
- district heat snapshots
- mission briefing packets
- faction propaganda clips
- runsite host overlays
- season recap reels
- reward unlock explainers
- “what changed in the city?” companion cards

These should remain receipt-backed, campaign-safe, and approval-aware.

## Table Pulse and Ghostwire boundary

`TABLE PULSE` and `GHOSTWIRE` may support debrief, replay, and packet quality.

They must not directly decide world-state truth.

Allowed:
- suggestion packets
- debrief summaries
- evidence references
- recap support

Forbidden:
- automatic world-state mutation from session audio
- live surveillance as world authority
- manager-seat scoring from passive observation
- moderation or discipline automation

GM or organizer approval remains required for world-impacting resolution.

## Non-goals

This layer is not:
- a VTT replacement
- a fully detached 4X strategy game
- a stealth moderation engine
- a universal global metagame all users must join
- a loophole to bypass rule-environment receipts

## Why it is still a horizon

This is a major widening move.

It depends on:
- trustworthy campaign spine truth
- clear GM and organizer authority
- rule-environment package visibility
- mission packet and artifact workflows
- release-proof campaign workspace surfaces

Until those are strong enough, BLACK LEDGER should remain a future-capability lane with bounded research steps.

## Eventual build path

- `horizon`
- `bounded_research`
- `gm_only_world_engine`
- `shared_city_pilot`
- `human_faction_seats`
- `season_ops`
- `public_media_and_creator_integration`

## Success signals

- GMs can choose from world-generated jobs without feeling railroaded
- campaigns feel like they live inside a changing city
- faction identity affects tension, rewards, and opposition in recognizable ways
- success and failure of runs change future opportunity shape
- world-linked rewards and threats surface through explicit receipts and packages
- organizers can operate a season without inventing every pressure beat by hand

## Why this matters

This is how Chummer stops being only the place where a runner is built or a run is tracked.

It becomes the place where the city remembers who pushed it, who profited, who panicked, and what that means next.
