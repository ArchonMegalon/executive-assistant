# Vision

## North star

Chummer becomes a complete digital Shadowrun operating environment built on hard architectural boundaries.

The finished product is:

* a deterministic character and rules engine
* a workbench for building, inspecting, comparing, publishing, and moderating
* a session OS for players and GMs across desktop, web, and mobile
* a build-time knowledge fabric for grounded, cited rules understanding
* a hosted campaign and assistant orchestration plane
* a runsite explorer for bounded mission-space artifacts
* an artifact studio for dossiers, recaps, narrated briefings, and evidence-bearing outputs
* a creator press for primers, handbooks, district guides, campaign books, and modules
* a reusable registry/publication ecosystem
* a bounded media studio for artifacts, portraits, and video
* an explainable replay ecosystem for receipts, reconstruction, and after-action review
* a fully explainable system where derived values can always be grounded
* a GM coaching and table-pulse lane for bounded post-session spotlight, pacing, and engagement guidance
* an optional local co-processor lane where local acceleration helps without becoming mandatory

## Product promises

### 1. Engine truth is deterministic

No repo other than `chummer6-core` computes canonical rules math.

### 2. Explain Everywhere is real

Every important derived value, legality outcome, or state transition can be explained with structured provenance.

### 3. Workbench and play are different products

`chummer6-ui` is the builder/workbench/admin surface.
`chummer6-mobile` is the live session shell.

### 4. Hosted orchestration is not rules truth

`chummer6-hub` coordinates identity, relay, memory, approvals, and assistants, but it does not own duplicate mechanics.

### 5. Shared UI is a package, not a rumor

`chummer6-ui-kit` becomes the only reusable cross-head UI boundary.

### 6. Registry and media are real services

Publication/catalog concerns and render/media concerns do not remain hidden inside run-services forever.

### 7. Legacy is an oracle, not a shadow product

`chummer5a` exists to support migration and regression confidence, not to compete with vNext architecture.

## Finished-state experience

### Player

A player can build, sync, inspect, and play from a modern shell that works across devices and survives intermittent connectivity.

### GM

A GM can run live sessions, inspect grounded state, receive Spider/Coach support, review generated assets, manage play flow without juggling unrelated tools, and optionally receive post-session coaching about pacing, spotlight balance, and engagement drift without confusing that analysis for session truth.

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

### Session OS

Reconnect, replay, resume, and table continuity are first-class.
The shell should let the table recover state without panic and settle disputes with receipts instead of memory.

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
* a design system copied into each frontend
* a media generator welded directly to play or workbench
* a registry buried inside orchestration services
* a design repo that only contains slogans
