# Vision

## North star

Chummer becomes the explainable Shadowrun campaign OS.

The product wedge is still character building, but the finished product is not merely a next character builder.
The finished product is the system players and GMs trust when Shadowrun gets complicated:

* build and advance a character without mistrusting the math
* inspect every important number, legality result, and state change with readable provenance
* run sessions and campaigns without losing context, continuity, or table flow
* recover calmly when devices, imports, updates, or rules disputes go sideways
* carry long campaigns forward with receipts instead of memory

## Center of gravity

The emotional center of Chummer is trust under complexity.

For players:

* I can build and advance my character without mistrusting the math.

For GMs:

* I can run the campaign without losing state, context, or table flow.

For groups:

* When something goes wrong, we recover calmly with receipts.

## Three rings

### Ring 1 — Must be excellent first

This is the product users judge immediately:

* build
* explain
* validate
* import and migrate
* save and sync
* install and update
* support and diagnostic export

### Ring 2 — The campaign OS

This is the durable differentiation:

* campaign ledger
* GM session console
* player mobile and session shell
* roster and advancement continuity
* downtime, travel, and state history
* replay and recovery
* cross-device continuation
* conflict resolution with receipts

### Ring 3 — Horizons and extensions

These remain valuable, but they must not blur the core product promise before the trust loops are boring:

* runsite explorer
* artifact studio and JACKPOINT
* creator press and RUNBOOK PRESS
* table pulse
* media factory and video
* local co-processor lanes
* hosted assistant extensions

## Product promises

### 1. Engine truth is deterministic

No repo other than `chummer6-core` computes canonical rules math.

### 2. Explain Everywhere is real

Every important derived value, legality outcome, or state transition can be explained with structured provenance.

### 3. Campaign continuity is first-class

The character builder is the acquisition wedge.
The campaign ledger is the retention engine.
Roster, runs, scenes, objectives, debts, downtime, advancement, rules environment, session receipts, and recovery state are product surfaces, not side notes.

### 4. Workbench and play are different products

`chummer6-ui` is the builder/workbench/admin surface.
`chummer6-mobile` is the live session shell.

### 5. AI is subordinate to deterministic truth

AI may summarize, suggest, coach, draft, and explain.
It must not become rules truth, campaign truth, or release truth.

### 6. Hosted orchestration is not rules truth

`chummer6-hub` coordinates identity, relay, memory, approvals, and assistants, but it does not own duplicate mechanics.

### 7. Shared UI is a package, not a rumor

`chummer6-ui-kit` becomes the only reusable cross-head UI boundary.

### 8. Registry and media are real services

Publication/catalog concerns and render/media concerns do not remain hidden inside run-services forever.

### 9. Legacy is an oracle, not a shadow product

`chummer5a` exists to support migration and regression confidence, not to compete with vNext architecture.

### 10. Flagship-grade craft is part of done

Chummer is not finished when the code merely works.
It is finished when the whole product feels deliberate, trustworthy, fast under real use, honest on the public shelf, and authored enough that SR4, SR5, and SR6 do not collapse into one generic lowest-common-denominator experience.

## Finished-state experience

### Player

A player can build, inspect, advance, sync, and play from a modern shell that works across devices, survives intermittent connectivity, and never hides why the number changed.

### GM

A GM can run live sessions and long campaigns from a reliable campaign ledger and session console: roster, runs, scenes, objectives, contacts, debts, downtime, advancement, rules environment, session receipts, and recap history stay coherent enough that the table does not need to rebuild context from memory.

### Group

A group can survive disconnects, imports, updates, house-rule drift, and disputed modifiers without panic because the recovery path is receipt-backed, inspectable, and calm.

### Creator / publisher

A creator can prepare artifacts, publish content, manage installs, review compatibility, and work through governed publication flows.

### Operator / maintainer

A maintainer can tell:

* which repo owns what
* which package owns which DTO
* which milestone is blocking release
* which mirror is stale
* which design change became canonical and why

## Finished-state capability layers

### Truth Engine

Every canonical number, legality outcome, and reducer transition is deterministic, explainable, and grounded in Chummer-owned receipts.

### Campaign OS

Reconnect, replay, resume, campaign continuity, and the campaign ledger are first-class.
The shell should let the table recover state without panic, settle disputes with receipts instead of memory, and carry campaign context forward across sessions and devices.

### Knowledge Fabric

Rules understanding becomes cheaper and more trustworthy through build-time knowledge projections derived from core-owned truth.
Those projections support cited help, explain, and assistant lanes without becoming a second source of truth.

### Runsite Explorer

GMs can prepare or publish bounded explorable mission-space packs with floor plans, hotspots, route overlays, optional narration, and previews.
This lane supports briefing and spatial understanding; it is not live combat truth and not a VTT replacement.

### Artifact Studio

JACKPOINT becomes the short-to-medium-form studio for dossiers, recaps, narrated briefings, evidence rooms, share cards, and creator-facing artifact packets tied back to Chummer-owned manifests.

### Creator Press

RUNBOOK PRESS becomes the long-form publishing lane for primers, handbooks, district guides, campaign books, and convention modules governed by publication manifests rather than vendor dashboards.

### Replay / Forensics

Replay and after-action review become explicit end-state capabilities so Chummer can reconstruct what happened, show receipts over time, and support bounded what-if comparison without forking session truth.

### Table Pulse

Chummer can optionally turn recorded or uploaded session media into bounded, opt-in GM coaching: spotlight balance, pacing drift, engagement anomalies, interruption patterns, and narrated after-action guidance without becoming live surveillance or canonical session truth.

### Optional Local Co-Processor

Local compute is allowed where it improves privacy, responsiveness, or cost, but it remains optional acceleration rather than a product requirement.

## Sequencing rule

End-state wow is allowed to outrun the current release scope, but it must not overrule foundation sequencing.

## Anti-vision

Chummer is not:

* one repo pretending to be many
* a rules engine hidden in UI code
* an AI-first product with fuzzy authority
* a giant Shadowrun everything-suite with no center of gravity
* a design system copied into each frontend
* a media generator welded directly to play or workbench
* a registry buried inside orchestration services
* a design repo that only contains slogans
