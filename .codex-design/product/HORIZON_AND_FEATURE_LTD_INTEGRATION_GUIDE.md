# Horizon and feature LTD integration guide

## Purpose

This guide audits the canonical Chummer horizons and the active LTD-backed feature systems for profitable LTD leverage.

The goal is not "use every LTD everywhere."

The goal is:

* add LTDs where they make the horizon or feature materially stronger
* keep Chummer-owned truth, receipts, and approvals first-party
* make discovery, intake, projection, media, and delivery lanes explicit
* keep parked or non-canonical horizon drafts out of the hot path

## Scope

This audit covers:

* canonical horizons listed in `HORIZON_REGISTRY.yaml`
* active feature systems listed in `LTD_RUNTIME_AND_PROJECTION_REGISTRY.yaml`

This audit does not promote parked horizon drafts such as `edition-studio`, `onramp`, `quicksilver`, or `run-control`.
Those files stay out of scope until they return to the machine-readable horizon canon.

## Working rules

* Chummer owns rules truth, session truth, roster truth, world truth, approval truth, publication truth, support truth, and notification truth.
* Workspace integration posture matters more than vendor marketing tier.
* A horizon may benefit from discovery LTDs without accepting a runtime LTD dependency.
* A horizon may accept media, preview, scheduling, intake, or delivery LTDs without giving them authority over canon.
* If a horizon works better with no promoted LTD in the hot path, that is a valid result.

## Canonical coverage index

Every canonical horizon in `HORIZON_REGISTRY.yaml` is covered here:

* `nexus-pan` - continuity truth stays first-party; bounded delivery, help, preview, and operator-capture lanes only
* `alice` - engine-owned build truth with bounded explain and compare-artifact helpers
* `karma-forge` - strongest discovery, review, approval, and governed-process LTD fit
* `knowledge-fabric` - strongest explain, docs, capture, and citation LTD fit
* `jackpoint` - strongest artifact-factory, narration, preview, and explainer LTD fit
* `black-ledger` - strongest operator-ops plus downstream world-output LTD split
* `community-hub` - strongest intake, scheduling, review, and closeout LTD fit
* `runsite` - strongest spatial, explorable-tour, route, and orientation LTD fit
* `runbook-press` - strongest long-form authoring, render, and explainer LTD fit
* `ghostwire` - strongest replay-surface, report, and narrated after-action LTD fit
* `table-pulse` - strongest opt-in coaching and debrief LTD fit
* `local-co-processor` - strongest parity-helper and operator-guidance fit, with no external truth owner

## Horizon audit

### NEXUS-PAN

Profits from bounded helper lanes only.

* `Emailit` can handle reconnect or device-relink notices after Hub decides the message should exist.
* `Documentation.AI` can project continuity and recovery help from approved source truth.
* `PeekShot` can render share-safe continuity receipts or reconnect proof cards.
* `BrowserAct` can help operators capture broken reconnect flows or public auth/device drift repro steps.

Do not let any LTD own:

* session state
* reconnect truth
* conflict resolution
* cross-device authority

### ALICE / BUILD GHOST

Profits from bounded explain and artifact lanes around engine-owned compare truth.

* `AI Magicx` can summarize already-computed deltas and build-tradeoff briefs.
* `1min.AI` and `Prompting Systems` can help draft compare copy and user-facing explain language.
* `MarkupGo` and `PeekShot` can render compare packets, receipts, and share-safe ghost summaries.

Do not let any LTD own:

* build math
* legality
* campaign allowances
* apply/discard truth

`FacePop`, `ProductLift`, and other public concierge/signal tools are out of the runtime feature path.

### KARMA FORGE

Profits from the broadest LTD discovery and governance stack.

* `Icanpreneur`, `Deftform`, `Lunacal`, and `MetaSurvey` support demand discovery, pre-screening, follow-up, and quant validation.
* `Teable` supports review boards and AdminIntent capture.
* `NextStep` supports governed discovery and package-approval runbooks.
* `ApproveThis` supports external approval posture.
* `Emailit` supports closeout and participant followthrough.
* `FacePop`, `Signitic`, `vidBoard`, and `Taja` can support bounded recruitment, amplification, and approved explainers.

Do not let any LTD own:

* rule truth
* rule-pack publication truth
* compatibility truth
* rollback truth

### KNOWLEDGE FABRIC

Profits from explain, docs, capture, and citation lanes around core-owned source packs.

* `Prompting Systems`, `Documentation.AI`, and `AI Magicx` support grounded explain and docs projection.
* `1min.AI` supports bounded specialist synthesis against approved projections.
* `BrowserAct` supports operator capture and fallback workspace observation.
* `Paperguide` supports cited research and grounding.

Do not let any LTD own:

* mechanics answers
* citation truth
* source-pack truth
* rules authority

### JACKPOINT

Profits heavily from artifact-factory LTDs.

* `MarkupGo`, `vidBoard`, `Soundmadeseen`, `PeekShot`, and `Documentation.AI` make the core packet, video, narration, preview, and docs lanes stronger.
* `First Book ai` can absorb overflow when short-form artifact work needs longer carryover.
* `Paperguide`, `Mootion`, and `Unmixr AI` stay bounded helper lanes.

Do not let any LTD own:

* fact classification
* briefing truth
* evidence provenance
* publication approval

### BLACK LEDGER

Profits from a split between operator ops LTDs and downstream world-output LTDs.

* `Teable`, `NextStep`, `ApproveThis`, `Signitic`, and `Emailit` strengthen the operator, approval, projection, and digest loop.
* `vidBoard`, `MarkupGo`, `PeekShot`, `Soundmadeseen`, and `Taja` strengthen downstream world-output artifacts.
* `MetaSurvey`, `Deftform`, and `Lunacal` help only on adjacent discovery, intake, and session-closeout edges.
* `BrowserAct` and `Documentation.AI` remain bounded support lanes.

Do not let any LTD own:

* world truth
* campaign truth
* mission-market truth
* faction state
* operator authority

### COMMUNITY HUB

Profits from intake, scheduling, review, closeout, and optional public-entry LTDs.

* `Deftform`, `Lunacal`, `MetaSurvey`, `Teable`, `NextStep`, `ApproveThis`, and `Emailit` strengthen application intake, booking, review, operator discipline, decisions, and closeout.
* `FacePop` and `Signitic` help only as public-entry and passive recruitment projection.
* `vidBoard` and `Taja` help with approved onboarding, recap, and honors media.
* `hedy.ai`, `Nonverbia`, and `BrowserAct` remain bounded observer/debrief/capture helpers only.

Do not let any LTD own:

* open-run truth
* accepted roster
* consent truth
* meeting handoff truth
* reputation or honors truth

### RUNSITE

Profits from spatial and orientation LTDs.

* `Crezlo Tours`, `AvoMap`, and `PeekShot` are strong direct fits for explorable spatial packs.
* `vidBoard` and `Soundmadeseen` help with orientation-host and narrated walkthrough companions.
* `BrowserAct` and `Browserly` remain bounded capture/reference helpers.

Do not let any LTD own:

* tactical authority
* live combat truth
* permissions truth
* map canon

### RUNBOOK PRESS

Profits from long-form authoring, render, and explainer LTDs.

* `First Book ai`, `MarkupGo`, `Documentation.AI`, `vidBoard`, and `Soundmadeseen` materially improve long-form package creation, export, explainers, and companion assets.
* `Paperguide` and `Unmixr AI` remain bounded helper lanes.

Do not let any LTD own:

* publication truth
* compatibility truth
* source-pack truth
* editorial approval

### GHOSTWIRE

Profits from replay-safe output and recap LTDs after first-party reconstruction exists.

* `PeekShot`, `MarkupGo`, and `Soundmadeseen` are the strongest direct fits for replay surfaces, reports, and narrated after-action outputs.
* `Mootion` and `Paperguide` remain bounded replay-video and cited reconstruction helpers.

Do not let any LTD own:

* replay truth
* reducer history
* recovery truth
* forensics authority

### TABLE PULSE

Profits from opt-in coaching LTDs, but only after consent and privacy are stable.

* `Nonverbia` is the strongest primary analysis fit.
* `hedy.ai` is a bounded structure, digest, and GM debrief helper.
* `vidBoard`, `Soundmadeseen`, `Unmixr AI`, `MarkupGo`, and `PeekShot` support bounded recap, narration, render, and preview outputs.

Do not let any LTD own:

* moderation truth
* player scoring
* live surveillance
* canonical session truth

### LOCAL CO-PROCESSOR

Profits from benchmark and parity-helper lanes, not from new truth owners.

* `1min.AI` and `AI Magicx` can act as hosted parity and fallback comparison lanes while local acceleration remains optional.
* `BrowserAct` can support operator capture of hosted-versus-local proof and recovery paths.
* `Documentation.AI` can project operator docs and local-setup guidance once the path is stable.

Do not let any LTD own:

* local truth
* required runtime availability
* canonical explain outputs
* hosted/local parity decisions

## Cross-horizon discovery and signal rule

For any public-eligible horizon, the following may help discovery without becoming runtime truth:

* `ProductLift` for public ideas, votes, roadmap projection, and closeout
* `Icanpreneur` for adaptive interview and concept-validation synthesis
* `MetaSurvey` for quant follow-up
* `FacePop`, `Deftform`, and `Lunacal` for first-contact intake or guided follow-up
* `Signitic` and `Emailit` for passive amplification and closeout delivery

Those lanes may shape demand evidence.
They do not decide roadmap truth, priority truth, release truth, or feature authority.

## Feature-system audit

### continuity_recovery_system

Best fit:

* `Emailit`
* `Documentation.AI`
* `PeekShot`
* `BrowserAct`

Purpose:

* continuity notices
* recovery help projection
* reconnect proof cards
* operator repro capture

### build_ghost_lab

Best fit:

* `AI Magicx`
* `1min.AI`
* `Prompting Systems`
* `MarkupGo`
* `PeekShot`

Purpose:

* compare-brief drafting
* explain polishing
* compare packet rendering
* ghost receipt previews

### knowledge_projection_system

Best fit:

* `Prompting Systems`
* `Documentation.AI`
* `AI Magicx`
* `1min.AI`
* `BrowserAct`
* `Paperguide`

Purpose:

* derived explain surfaces
* docs/help projection
* capture and citation support

### community_hub_ops

Best fit:

* `Deftform`
* `Lunacal`
* `MetaSurvey`
* `Teable`
* `NextStep`
* `ApproveThis`
* `Emailit`
* `FacePop`
* `Signitic`

Purpose:

* intake
* booking
* review
* followthrough
* recruitment
* closeout

### runsite_spatial_factory

Best fit:

* `Crezlo Tours`
* `AvoMap`
* `PeekShot`
* `vidBoard`
* `Soundmadeseen`
* `BrowserAct`

Purpose:

* explorable tours
* route overlays
* preview cards
* orientation companions

### ghostwire_forensics_lab

Best fit:

* `PeekShot`
* `MarkupGo`
* `Soundmadeseen`
* `Mootion`
* `Paperguide`

Purpose:

* replay surfaces
* after-action packets
* narrated reconstructions
* bounded replay-video experiments

### local_acceleration_research

Best fit:

* `1min.AI`
* `AI Magicx`
* `BrowserAct`
* `Documentation.AI`

Purpose:

* hosted-local parity checks
* operator capture
* guidance projection

## Design result

The profitable LTD posture is now:

* explicit for every canonical horizon
* explicit for the missing feature systems that were not yet represented in the LTD runtime registry
* still fail-closed on Chummer-owned truth, approvals, and receipts
