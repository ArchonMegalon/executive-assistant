# BLACK LEDGER

## Table Pain

Campaign worlds often feel sealed off from each other. The city rarely pushes back on its own, completed runs disappear into memory, and GMs have to invent heat, corp agendas, district pressure, opposition, rumors, and fresh jobs from nothing between sessions.

Living communities have the same pain at larger scale: many GMs, many tables, many unresolved consequences, and too little product structure for mission intake, scheduling, world ticks, player-safe news, faction pressure, and seasonal memory.

## Bounded Product Move

BLACK LEDGER is Chummer's living-world layer: a persistent Shadowrun power struggle where factions, GMs, players, runners, creators, and organizers all push on the same city, and the city pushes back.

It is not an AI GM, VTT replacement, passive surveillance lane, or detached strategy minigame. It is a governed world map, mission market, faction-pressure engine, intel network, newsreel lane, and campaign memory layer that feeds GMs useful opportunities while preserving GM authority.

The core loop is:

```text
faction pressure
-> intel reports
-> world tick
-> job seeds
-> GM adoption
-> scheduled run
-> resolution report
-> map consequence
-> newsreel
-> next tick
```

## Likely Owners

* `chummer6-hub`
* `chummer6-core`
* `chummer6-ui`
* `chummer6-mobile`
* `chummer6-media-factory`
* `chummer6-hub-registry`
* `executive-assistant`

## Foundations

* `C0` - campaign, run, and Hub-owned receipt boundaries
* `C1` - campaign authority and player-safe visibility gates
* `D0` - deterministic projections from Chummer-owned state
* `D1` - sync and restore behavior for world-linked state
* `D2` - portability, receipts, and missing-package warnings
* `E2b` - media artifact provenance and publication review
* `F1` - public-surface and community trust controls
* Product Governor review for world-tick, public-news, and artifact publication

## Why Still A Horizon

BLACK LEDGER only works if Chummer proves three things at once: campaigns stay the center of play, world-linked pressure stays inspectable through receipts and approvals, and organizer, GM, and future faction-seat authority stay cleanly separated.

The first proof should be deliberately small: one city, one tick, one adopted job, one scheduled session, one reported outcome, and one visible consequence. Until those authority seams are trustworthy, BLACK LEDGER stays a horizon rather than a shipment promise.

## Human Promise

**The city remembers what happened.**

A crew sabotages a Renraku shipment. Tacoma heat rises. A district marker changes. A faction newsletter goes out. A newsreel spins the story. A rival corp sees an opening. A GM gets new job seeds. A faction manager decides whether to retaliate, hide the damage, or sponsor a deniable counter-run.

That is BLACK LEDGER.

Every world tick turns player action, GM resolution, faction pressure, and community lore into new opportunities.

## How It Works

BLACK LEDGER runs on a simple loop:

```text
factions create pressure
players and GMs report intelligence
world ticks process the city state
GMs receive mission opportunities
runs are scheduled and played
results are reported
the map changes
newsreels and faction briefings publish the fallout
the next tick starts from the new reality
```

The result is a Shadowrun world that feels less like a static backdrop and more like a living machine.

## World Map

BLACK LEDGER gives each active Chummer world a source-aware map.

The map can show:

* planned runs
* completed runs
* district heat
* faction activity
* public rumors
* GM-only intel
* player-submitted leads
* news events
* unresolved consequences
* open opportunities
* world-tick changes

A marker is never just a pin. It points back to a source: a run, faction move, intel report, resolution report, world tick, news item, mission packet, or approved artifact.

Click a marker and Chummer should be able to answer:

* Why is this district hot?
* Which faction is involved?
* Is this public, GM-only, or faction-secret?
* Did this come from a completed run?
* Can this become a mission?
* Is there a briefing, recap, or newsreel attached?
* What happens if a GM adopts this job?

The map becomes a campaign memory board, mission marketplace, and living city dashboard at the same time.

## Mission Market

BLACK LEDGER gives GMs a better starting point than a blank page.

Instead of asking "what should I run tonight?", the GM can open the Mission Market and see jobs generated from the world itself:

* a corp feud
* a failed extraction
* a player-submitted rumor
* a faction research project
* rising district heat
* a rival operation
* an unresolved campaign consequence
* a public scandal
* an occult clock
* a black-market opportunity

Each mission seed can include:

* sponsor
* target
* district
* heat profile
* recommended runner roles
* reward hooks
* likely opposition
* success consequences
* failure consequences
* connected factions
* player-safe pitch
* GM-only notes
* optional briefing packet
* optional runsite packet
* optional generated news hook

Example:

```text
Extraction at the Black Clinic

District: Redmond
Sponsor: Evo deniable channel
Target: unaffiliated biotech lab
Heat: high occult, medium security, low public
Tags: extraction, biotech, moral pressure, black clinic

Reward hooks:
- restricted biotech access
- contact trust with an Evo researcher

Failure consequences:
- occult heat rises
- Aztechnology blood cell becomes active
- local clinic network goes underground

Origin:
This job emerged from a player intel report, an Evo research project, and a failed prior run.
```

The GM can adopt it, edit it, schedule it, fork it, reject it, or ask Chummer for variants.

BLACK LEDGER suggests. The GM decides.

## Open Runs And Community Hub

A GM can turn a mission into an `OpenRun`.

That run can appear on the world map or the Community Hub with a player-safe listing:

* title
* pitch
* expected tone
* required ruleset
* house rules
* needed roles
* beginner friendliness
* schedule options
* language
* voice, video, or text expectations
* content notes
* join policy
* Discord, Teams, or meeting handoff
* whether Table Pulse or GOD Observer is allowed

Players can request to join with runner dossiers.

Chummer can preflight the application:

* Is the runner legal for this rule environment?
* Does the schedule fit?
* Does the table need this role?
* Are there unresolved character conflicts?
* Is the player using a quickstart runner?
* Did they acknowledge the table contract?
* Does the GM require approval?

Chummer does not replace table tools. It makes the table flow structured, visible, and remembered.

## Scheduling With Lunacal

GMs can schedule sessions around a run. A GM adopts a job, selects schedule, and Chummer can hand the booking flow to Lunacal or another scheduling provider.

The scheduled session can appear in Chummer as:

* planned run marker
* player RSVP state
* roster status
* readiness checklist
* pre-session packet
* meeting handoff
* rule-environment warnings
* Table Pulse consent state
* post-session resolution reminder

The calendar owns the booking. Chummer owns the run.

If the session is rescheduled, Chummer updates the run marker. If it is cancelled, no world result is recorded. If it is played, the GM can file a resolution report and the city can change.

## Run Results Feed The World

After a run, the GM files a result:

* success
* failure
* mixed result
* collateral damage
* faction impact
* contacts gained or burned
* heat changes
* rewards unlocked
* unresolved consequences
* player-safe recap
* GM-only notes

A completed run might raise district heat, unlock a faction asset, damage a corp project, expose a secret, trigger a news story, create a revenge job, change a black-market channel, make a runner notorious, alter faction standings, or open and close future mission types.

The run does not disappear after the table ends. It becomes part of the world.

## Intelligence Reports

BLACK LEDGER lets users feed their own table lore into their Chummer world.

Players, GMs, creators, organizers, and faction managers can submit intelligence:

* rumors
* district lore
* suspicious faction activity
* unresolved NPC hooks
* black-market chatter
* contact reports
* campaign fallout
* failed-run consequences
* "we want more of this" signals
* local table legends
* faction secrets
* creator mission seeds

Example:

```text
Intel Report:
Our table has been treating the old arcade in Redmond as a drone chop shop.
We never resolved who owns it.

Tags:
Redmond, drones, black market, Renraku, street-level

Desired use:
job generation, district lore, rumor, future run hook
```

A curator, GM, organizer, or world operator reviews it. Intel can become a rumor, map marker, district pressure note, job seed, news item, faction clue, creator prompt, or private campaign-only hook.

It does not become canon automatically.

> User lore is fuel. Chummer still requires review before it becomes world truth.

## Factions And Megacorps

BLACK LEDGER can model factions as active powers.

A faction can have:

* resources
* goals
* heat
* assets
* research projects
* rivalries
* secrets
* public posture
* private operations
* district influence
* special rewards
* signature threats

Factions can include megacorps, syndicates, cults, governments, NGOs, gangs, magical societies, fixers' networks, AI entities, or original table factions.

They should not feel interchangeable. The job board should make you feel who is moving.

## Faction Managers

For advanced campaigns, seasons, or community play, BLACK LEDGER can let trusted users operate faction seats.

A faction manager might allocate resources:

* capital
* influence
* matrix
* security
* arcana
* research

They can submit operation intents:

* sponsor a run
* suppress heat
* target a rival
* advance research
* seed disinformation
* secure a district
* open a black-market channel
* unlock a special asset
* escalate occult pressure

Example:

```text
Aztechnology faction manager:
- spends arcana on a ritual project
- spends influence to hide public attention
- targets a rival Evo clinic

World tick result:
- occult heat rises in Puyallup
- public heat stays low
- GM job seed generated: Sabotage the ritual supply chain
- failure consequence: blood-mage response cell unlocks
```

Faction managers are not there to "win Chummer." They are there to make the world more interesting.

The best faction move creates a run someone wants to play.

## Heat

Heat is the pressure system.

BLACK LEDGER can track:

* crew heat
* district heat
* sponsor heat
* public heat
* matrix heat
* security heat
* occult heat

High matrix heat might generate stronger hosts, counter-decker squads, IC escalation, Renraku response teams, or data-theft counter-runs.

High occult heat might generate ritual clocks, watcher spirits, blood-magic rumors, talismonger panic, astral hazards, or occult investigation jobs.

High public heat might generate news scandals, corporate denials, PR jobs, legal pressure, or media manipulation.

Heat makes the world react.

## Newsreels And City Tickers

The world should talk back.

After a world tick or completed run, BLACK LEDGER can generate public-safe news:

```text
Tacoma Port Authority denies drone lockdown rumors

Officials call the shutdown routine maintenance after witnesses report Renraku-marked security drones near a restricted warehouse.
```

Or:

```text
Horizon announces relief campaign after unexplained Redmond clinic fire

Local witnesses say armed responders arrived before emergency services. Horizon denies any corporate security involvement.
```

News can become:

* city ticker text
* campaign news feed
* faction newsletter
* GM-only briefing
* player-safe recap
* vidBoard news anchor reel
* Taja short
* PeekShot card
* MarkupGo bulletin
* Signitic email banner
* Emailit digest

The same event can have multiple versions:

* public rumor
* player-safe recap
* GM spoiler packet
* faction-secret briefing
* organizer summary

Chummer can show the world differently depending on who is looking.

## Faction Newsletters

Factions can publish internal or public-facing updates.

A faction newsletter might include:

* current objectives
* heat warnings
* active assets
* rival activity
* public narrative wins
* sponsored job outcomes
* available rewards
* research progress
* faction-seat orders
* propaganda lines

Examples:

```text
Renraku Internal Dispatch

Grid exposure in Tacoma exceeded tolerance.
Counter-intrusion audit authorized.
Runner involvement suspected.
Red Samurai deployment remains deniable.
```

```text
Horizon Public Bulletin

Horizon Community Forward announces emergency support in Redmond following infrastructure disruption.
Rumors of corporate activity remain unverified and irresponsible.
```

Faction newsletters give the world identity. They also make faction managers and players care about more than numbers.

## Table Pulse And GOD Observer

BLACK LEDGER can integrate with Table Pulse carefully.

Table Pulse is not live surveillance, player scoring, moderation truth, or automatic world truth.

With consent, Table Pulse or a GOD Observer lane can help after a session:

* summarize what happened
* identify unresolved objectives
* suggest recap points
* help draft a resolution report
* highlight pacing or spotlight notes
* prepare GM-private coaching
* generate a player-safe recap

Example:

```text
Suggested resolution notes:
- Team extracted the target.
- Public heat remained low.
- Matrix heat increased after failed host cleanup.
- Player intel about the black clinic should become corroborated.
- Evo sponsor trust +1.
- Aztechnology occult heat +1.
```

The GM still approves the result. The world changes only after an authorized human confirms it.

## Reputation And Seasonal Honors

BLACK LEDGER can make contribution visible without becoming a toxic permanent leaderboard.

Possible honors:

* Reliable Fixer
* Beginner Table Hero
* Best BLACK LEDGER Closeout
* Team Glue
* Good Debriefer
* Rookie Runner
* Heat Magnet
* Cleanest Ghost
* Corp Problem
* Fixer's Source
* District Chronicler
* Rumor Became Real
* Public Narrative Winner
* Best Heat Management
* Job Market Maker

The goal is not to rank everyone forever. The goal is that the world remembers who made things happen.

## Why GMs Care

GMs get mission seeds with context, world pressure they can use, a map of active consequences, player applications and join policies, scheduling support, run result reporting, newsreel generation, faction-driven plot hooks, player-submitted intel, ready-made escalation, and a reason for the next session to feel connected.

The GM remains the table's creative owner. BLACK LEDGER gives them a city that keeps offering trouble.

## Why Players Care

Players get runs they can discover and apply for, visible table rules before joining, runner dossiers tied to world outcomes, news about what their crew changed, reputation moments, intel submission, player-safe recaps, campaign continuity, and a sense that their character did something that mattered.

A player can look at the map and say: that marker exists because of our run.

## Why Organizers Care

Organizers can run shared city campaigns, open-run networks, public seasons, faction events, living-community arcs, creator playtests, seasonal honors, world tick schedules, and GM onboarding programs.

Discord can host the conversation. Foundry or Roll20 can host the table. Lunacal can schedule the time. Chummer owns the world memory.

## Why Creators Care

Creators can publish mission packets, faction arcs, runsite packs, campaign primers, newsreel kits, rule-environment packs, faction newsletters, season modules, and BLACK LEDGER-ready adventures.

A creator's module can become part of the mission market, be adopted by GMs, played by tables, resolved into world state, and surfaced in recaps and seasonal honors.

## What BLACK LEDGER Is Not

BLACK LEDGER is not a VTT replacement. VTTs can keep moving tokens, rolling dice, and rendering tactical maps.

BLACK LEDGER is not an AI GM. It gives GMs structured world pressure, mission ideas, and consequences.

BLACK LEDGER is not passive surveillance. Table Pulse and GOD Observer require consent and do not automatically create world truth.

BLACK LEDGER is not pay-to-win. Premium tools may help create, publish, or organize. They must not buy faction victory or leaderboard rank.

BLACK LEDGER is not automatic canon. User-submitted lore, faction moves, and session summaries need review before they become world state.

## User Questions

Can I use BLACK LEDGER for a private home campaign?

Yes. A GM can run a private world, mission market, and map without joining a public season.

Can I use it for a living community?

Yes. That is one of the strongest use cases: multiple GMs, shared city state, open runs, approved rule environments, seasonal honors, and public-safe news.

Can players submit their own lore?

Yes, with review. Players can submit intel, rumors, district lore, and unresolved hooks. GMs or world operators decide what becomes real.

Can I control a megacorp?

In advanced or seasonal modes, yes. Faction seats can let trusted users operate corps or factions and generate pressure for GMs.

Does the GM lose control?

No. BLACK LEDGER suggests missions and consequences. GMs adopt, edit, reject, and resolve.

Can it schedule sessions?

Yes. Runs can connect to scheduling tools such as Lunacal, then hand off to Discord, Teams, or another meeting surface.

Does it record sessions?

Not by default. Any Table Pulse or GOD Observer integration is opt-in, consent-gated, and review-based.

Do run results affect future missions?

Yes. Completed runs feed world ticks, which update heat, districts, factions, mission seeds, news, and future opportunities.

Can BLACK LEDGER generate news?

Yes. Approved world events can become news tickers, faction newsletters, public recaps, video newsreels, and campaign bulletins.

Can I opt out of public exposure?

Yes. Worlds, campaigns, runners, intel, and recaps need visibility controls: private, campaign-only, GM-only, faction-secret, network-visible, or public-safe.

## First Version

The first public proof should be Seattle Tick 001:

* one city map
* five districts
* three factions
* one GM-only mission market
* a handful of intel reports
* a few planned runs
* one scheduled open run
* one completed run
* one world tick
* one newsreel
* one faction newsletter
* one runner legend moment

Success looks like this:

> A GM opens the map, adopts a job, schedules a session, runs it, reports the result, and sees the world change.

That is the minimum magic.

## Vision

BLACK LEDGER is the leap from campaign manager to living Shadowrun world.

It makes Chummer more than the place where your runner sheet lives.

It becomes the place where factions scheme, GMs find jobs, players join runs, runners become legends, intel becomes opportunity, sessions become consequences, news tells the story, and the city changes.

**BLACK LEDGER is where the shadows remember.**

## Canon Links

* `products/chummer/WORLD_STATE_AND_MISSION_MARKET_MODEL.md`
* `products/chummer/WORLD_MAP_AND_INTEL_ECONOMY_MODEL.md`
* `products/chummer/WORLD_TICK_OPERATOR_PROCESS.md`
* `products/chummer/NEWSREEL_AND_CITY_TICKER_MODEL.md`
* `products/chummer/BLACK_LEDGER_MAP_AND_NEWSREEL_WORKFLOWS.yaml`
* `products/chummer/BLACK_LEDGER_ADMIN_WORKBENCH_MODEL.md`
* `products/chummer/BLACK_LEDGER_SEASON_OPERATOR_PLAYBOOK.md`
* `products/chummer/SIGNITIC_FACTION_WAR_AND_WORLD_TICK_CAMPAIGNS.md`
* `products/chummer/COMMUNITY_HUB_OPERATIONS_MODEL.md`
