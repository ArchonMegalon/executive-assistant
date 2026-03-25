# External tools plane

## Purpose

Project Chummer has a meaningful owned external-tool inventory.
Those tools are now considered part of the program's integration capability set.

This document defines how Chummer may use those tools for:

* Hub orchestration
* help/docs
* approval routing
* ops dashboards
* user feedback loops
* research/evaluation
* post-session coaching
* media creation
* route visualization
* archive and retention support

without allowing any external tool to become canonical product truth.

## Core rule

External tools may assist, route, render, summarize, visualize, archive, notify, or project. They may not become the canonical source of rules truth, session truth, approval truth, registry truth, media truth, or canon truth.

Chummer-owned repos and Chummer-owned manifests/stores remain authoritative.
Owning an LTD does not obligate Chummer to integrate it.
A tool may be promoted, bounded, parked, or explicitly excluded.

## Tool inventory posture

Current known external-tool inventory includes:

* 1min.AI
* Prompting Systems
* ChatPlayground AI
* Soundmadeseen
* AI Magicx
* FastestVPN PRO
* OneAir
* Headway
* Internxt Cloud Storage
* ApiX-Drive
* ApproveThis
* AvoMap
* BrowserAct
* Browserly
* Crezlo Tours
* Documentation.AI
* First Book ai
* Invoiless
* MarkupGo
* MetaSurvey
* Mootion
* Nonverbia
* Paperguide
* PeekShot
* Teable
* Unmixr AI
* Vizologi

Current internal posture assumes every listed LTD is redeemed and activated.
Public inventory snapshots may lag that internal state, so activation verification still gates runtime approval.

## Workspace integration tiers versus vendor plan tiers

Product plan tier and Chummer workspace integration tier are not the same thing.

Important current distinctions:

* 1min.AI - workspace integration Tier 1
* BrowserAct - workspace integration Tier 1
* Teable - workspace integration Tier 2, vendor license plan Tier 4
* Paperguide - workspace integration Tier 3, vendor license plan Tier 4

Chummer routing, rollout, and architectural ownership should follow workspace integration tier and system-of-record safety rules, not marketing or license-plan tier labels.

## Horizon-facing bounded lanes

Horizons may consume owned LTDs only through bounded capability lanes.
The horizon docs decide whether a lane is active; this document decides which kinds of LTD use are architecturally allowed.

Current horizon-facing posture:

* `jackpoint` - narrated recap and briefing lanes may use `Soundmadeseen`; bounded candidate voice may use `Unmixr AI`; evidence/capture packets may use `Browserly`
* `runsite` - explorable location artifacts may use `Crezlo Tours`, `AvoMap`, and `PeekShot`; optional narration may use `Soundmadeseen`; bounded capture/reference packets may use `Browserly`
* `runbook-press` - long-form authoring and export may use `First Book ai`, `MarkupGo`, and `Documentation.AI`; narrated companion assets may use `Soundmadeseen`; bounded candidate voice or reference capture may use `Unmixr AI` and `Browserly`
* `table-pulse` - post-session coaching packets may use `Nonverbia` as the primary analysis lane, with bounded narrated/report outputs from `Soundmadeseen`, `Unmixr AI`, `MarkupGo`, and `PeekShot`

## Classification model

### Class A - Runtime-adjacent orchestration integrations

These may participate in hosted workflows, but only through controlled adapters and receipts.

Examples:

* reasoning provider routes
* approval bridges
* docs/help bridges
* automation bridges
* survey bridges
* route visualization orchestration
* media orchestration
* public-signal intake governance

### Class B - Runtime-adjacent media integrations

These may render or transform artifacts, but only behind media-factory adapters.

Examples:

* document render providers
* preview/thumbnail providers
* image/portrait providers
* narrated audio/video providers
* bounded video providers
* map/route visualization providers
* archive providers

### Class C - Human-ops / projection integrations

These support operators and curators off the hot path.

Examples:

* projection boards
* moderation boards
* support/help desks
* review inboxes
* release dashboards

### Class D - Research / eval / prompt-tooling integrations

These inform product quality, content quality, or design quality, but they do not directly own end-user truth.

Examples:

* evaluation labs
* prompt research
* cited synthesis
* product strategy ideation
* bounded coaching and social-dynamics analysis

### Class E - Non-product utilities

Useful to the team, but outside the product architecture.

## System-of-record rule

The following remain Chummer-owned:

* rules math
* runtime fingerprints
* explain provenance
* reducer truth
* session event truth
* approval state
* moderation state
* publication state
* install state
* support case state
* crash/bug/feedback intake state
* artifact manifests
* media lifecycle state
* delivery state
* memory/canon state

External tools may receive a prepared request and may return a receipt-bearing result.
They do not become the owner of any of the truths above.

## Universal integration rules

### Rule 1 - adapter-only access

Every external tool sits behind a Chummer-owned adapter.

### Rule 2 - prepared payloads only

External tools receive prepared requests, not raw unrestricted database access.

### Rule 3 - receipt and provenance required

Anything that re-enters Chummer from an external tool must carry:

* provider identity
* route or adapter class
* request or plan hash
* created-at timestamp
* source refs where applicable
* moderation/safety result where applicable
* Chummer-side correlation id

### Rule 4 - kill switch required

Every integration must be disableable without corrupting product truth.

### Rule 5 - no client-side vendor coupling

No browser, mobile, or desktop repo may embed vendor credentials or call vendor SDKs directly.

### Rule 6 - archive is not canon

Vendor-hosted copies or vendor-side asset persistence are never the canonical archive.
Canonical manifests remain Chummer-owned.

### Rule 7 - activation is not trust

A redeemed or activated tool is merely eligible for integration.
It is not automatically approved for canonical runtime use.

### Rule 8 - coaching analysis is opt-in and post-session only

Any tool that analyzes human session behavior must stay opt-in, post-session, and clearly separate from canonical session truth, moderation truth, or player discipline.

### Rule 9 - support assistant is not phase 0

The first support plane must work without a chat assistant or support widget.

Crash reporting, structured bug reporting, and lightweight feedback must be first-class Chummer-owned flows before any support assistant becomes user-facing.
No new AppSumo LTD is required or assumed for the core crash path.

## Repo ownership

### `chummer6-design`

Owns:

* classification policy
* allowed-usage policy
* external-tools governance
* rollout sequencing
* blocker publication
* provenance requirements
* kill-switch requirements

Must not own:

* provider SDK code
* runtime keys
* implementation adapters

### `chummer6-hub`

Owns:

* orchestration-side integrations
* reasoning provider routing
* approval bridges
* docs/help bridges
* support/help-desk bridges
* survey bridges
* automation bridges
* research/eval toolchain integrations
* later grounded support-assistant or human-handoff layers
* user-facing projection shaping for external-tool outputs

Must not own:

* media rendering internals
* client-side provider access
* duplicate engine semantics
* canonical registry persistence
* canonical media lifecycle

### `chummer6-media-factory`

Owns:

* render/provider adapters
* preview/thumbnail adapters
* route-render adapters
* image and video adapters
* archive adapters
* media provider receipts
* media provenance capture
* media retention/archive execution

Must not own:

* campaign meaning
* approvals policy
* canon policy
* registry truth
* client UX
* general AI orchestration

### `chummer6-hub-registry`

May own:

* references to reusable template/style/help artifacts
* references to published previews
* compatibility metadata for reusable template/style packs

Must not own:

* provider execution
* media job orchestration
* reasoning provider routing

### `chummer6-ui` and `chummer6-mobile`

May render upstream projections that refer to external outputs.

Must not own:

* vendor keys
* vendor SDKs
* direct third-party orchestration

## Integration map by tool

## 1min.AI

### Role

Low-cost reasoning and multimodal provider route.

### Architectural use

* fallback reasoning provider in Hub/Coach routes
* multimodal summarization where policy allows
* optional low-cost assist route for structured drafting
* optional media prompt-assist upstream of media-factory

### Owner

* `chummer6-hub`
* optional media-prompt-assist only via `chummer6-hub`

### Hard boundary

* not canonical truth
* not direct-to-client
* not direct canon writer

## AI Magicx

### Role

Primary or alternate structured AI provider route.

### Architectural use

* governed Coach / Director / helper routes
* structured drafting
* composition assistance for media briefs
* operator-facing assistant routes

### Owner

* `chummer6-hub`

### Hard boundary

* no direct player/client access
* no storage truth
* no approval truth

## Prompting Systems

### Role

Prompt/style/persona authoring support.

### Architectural use

* prompt-template authoring
* style-template drafting
* reusable assistant instruction experimentation
* future publishable prompt/style artifacts after curation

### Owner

* `chummer6-hub` for orchestration-side prompt toolchain
* possible future publication via `chummer6-hub-registry`

### Hard boundary

* not runtime truth by itself
* not a substitute for Chummer prompt/version registry

## ChatPlayground AI

### Role

Evaluation lab only.

### Architectural use

* provider comparison
* regression evaluation
* output-shape evaluation
* cost/quality route testing

### Owner

* `chummer6-hub`

### Hard boundary

* not production runtime
* not canonical prompt home

## BrowserAct

### Role

Automation fallback and account-fact discovery.

### Architectural use

* external account verification
* no-API automation fallback
* tool inventory refresh
* operational bridge where no first-class API exists

### Owner

* `chummer6-hub`

### Hard boundary

* never a critical hot-path requirement
* never a canonical runtime store
* never direct user-facing truth

## Browserly

### Role

Bounded browser capture and reference-pack helper.

### Architectural use

* bounded page capture for horizon evidence packs
* reference snapshots for run-site, guide, and recap research
* structured crawl support where BrowserAct is too workflow-heavy

### Owner

* `chummer6-hub`

### Hard boundary

* not a live product runtime dependency
* not a canonical archive or registry surface
* not user-facing truth by itself

## ApproveThis

### Role

Approval inbox bridge.

### Architectural use

* review inbox forwarding
* publication approval bridge
* media approval bridge
* canon-write approval bridge
* recap approval bridge

### Owner

* `chummer6-hub`

### Hard boundary

* Chummer approval state remains canonical
* ApproveThis is a notification / inbox surface, not approval truth

## Documentation.AI

### Role

Docs/help plane.

### Architectural use

* public docs/help center
* API docs
* cited help assistant
* operator and publisher documentation
* onboarding docs
* knowledge-base projection after Chummer-owned curation

### Owner

* integration/orchestration: `chummer6-hub`
* canonical source material: `chummer6-design`, `chummer6-hub-registry`, approved docs exports

### Hard boundary

* not the canonical architecture repo
* not the only docs store
* not an unreviewed source of policy
* not the required crash-report path

## MetaSurvey

### Role

Feedback loop.

### Architectural use

* player/GM feedback
* creator/publisher feedback
* Coach usefulness ratings
* recap/video quality ratings
* moderation/registry quality surveys
* lightweight product-feedback intake

### Owner

* `chummer6-hub`

### Hard boundary

* not canonical analytics warehouse
* not canonical moderation state
* not canonical bug, crash, or support-ticket truth

## Nonverbia

### Role

Post-session coaching and social-dynamics analysis adapter.

### Architectural use

* spotlight balance diagnostics
* pacing and engagement review
* interruption or talk-balance review
* GM coaching packets
* optional narrated coaching overlays

### Owner

* orchestration, privacy gating, and policy framing: `chummer6-hub`
* rendered coaching artifacts: `chummer6-media-factory`

### Hard boundary

* not canonical session truth
* not player surveillance
* not moderation truth
* not discipline automation
* not live-session monitoring

## Teable

### Role

Curated projection surface.

### Architectural use

* moderation projection board
* curation board
* campaign-ops board
* release-status or triage board
* back-office operator surface

### Owner

* `chummer6-hub`

### Hard boundary

* not runtime DB
* not session truth
* not registry truth
* not approval truth

## ApiX-Drive

### Role

Automation bridge.

### Architectural use

* low-risk outbound automations
* mirrored notifications to ops systems
* non-critical workflow glue
* integration experiments before first-party adapters exist

### Owner

* `chummer6-hub`

### Hard boundary

* not a required hop for session relay
* not a required hop for approval truth
* not a required hop for media truth

## Paperguide

### Role

Cited research and synthesis support.

### Architectural use

* internal research
* design-research support
* authoring support for docs/help
* lore/reference curation support for human operators

### Owner

* `chummer6-design` for design research
* `chummer6-hub` for internal operator help/research assist

### Hard boundary

* not live rules truth
* not canon writer

## Vizologi

### Role

Strategy and ideation tool.

### Architectural use

* product strategy
* packaging/channel strategy
* creator-program ideation
* roadmap research

### Owner

* `chummer6-design`

### Hard boundary

* not runtime
* not product truth
* not session/path logic

## MarkupGo

### Role

Document-render adapter.

### Architectural use

* packets
* briefs
* dossiers
* invoices/manifests
* bulletins
* PDF/image document outputs

### Owner

* `chummer6-media-factory`

### Hard boundary

* not content author
* not manifest owner
* not archive truth

## Soundmadeseen

### Role

Narrated media and explainer adapter.

### Architectural use

* narrated recap clips
* release videos
* mission brief videos
* dossier videos
* voiced explainer artifacts

### Owner

* execution: `chummer6-media-factory`
* orchestration and link shaping: `chummer6-hub`

### Hard boundary

* not canon writer
* not source of briefing truth
* not archive truth

## PeekShot

### Role

Preview/thumbnail/share-card adapter.

### Architectural use

* previews
* thumbnails
* share cards
* preview derivatives for docs, portraits, and video

### Owner

* `chummer6-media-factory`

### Hard boundary

* not canonical parent asset
* not canonical manifest

## Crezlo Tours

### Role

Explorable location and tour adapter.

### Architectural use

* run-site packs
* GM walkthroughs
* floor-plan briefings
* safehouse and facility tours
* hub-published location artifacts

### Owner

* execution: `chummer6-media-factory`
* orchestration, permissions, and link shaping: `chummer6-hub`

### Hard boundary

* not live session truth
* not campaign geography canon
* not permission truth

## Mootion

### Role

Bounded video-render adapter.

### Architectural use

* NPC message videos
* recap/news videos
* route explainer clips
* short ambient or briefing clips

### Owner

* `chummer6-media-factory`

### Hard boundary

* no unbounded long-form runtime dependency
* no bypass of preview-first or approval policy
* no canonical archive ownership

## First Book ai

### Role

Long-form authoring and blueprint support.

### Architectural use

* player primers
* faction handbooks
* campaign bibles
* convention module drafts
* district guides
* season recap books

### Owner

* orchestration and source-pack shaping: `chummer6-hub`
* downstream publication refs where needed: `chummer6-hub-registry`

### Hard boundary

* not source-of-truth for canon
* not approval truth
* not publication truth by itself

## AvoMap

### Role

Route visualization / route-render adapter.

### Architectural use

* route previews
* travel/exfil visualizations
* movement recap assets
* map-backed route clips

### Owner

* orchestration-side route semantics: `chummer6-hub`
* render-side output execution: `chummer6-media-factory`

### Hard boundary

* not source of route truth
* not source of campaign geography semantics

## Unmixr AI

### Role

Candidate voice and audio adapter.

### Architectural use

* bounded TTS support
* dubbing or narrated artifact experiments
* future companion audio for briefings and primers

### Owner

* `chummer6-media-factory`

### Hard boundary

* candidate only until proven
* not canon writer
* not approval or archive truth

## Internxt Cloud Storage

### Role

Cold archive adapter.

### Architectural use

* cold archive for media artifacts
* deep retention storage
* non-hot restore source

### Owner

* `chummer6-media-factory`

### Hard boundary

* not hot asset serving
* not canonical manifest source

## Invoiless

### Role

Back-office only.

### Architectural use

* future vendor/admin invoicing
* possible future creator-marketplace back-office

### Owner

* future `chummer6-hub` back-office scope only if needed

### Hard boundary

* not current product dependency
* not monetization truth today

## FastestVPN PRO

### Role

Ops utility only.

Out of core product architecture.

## OneAir

### Role

Out of product architecture.

## Headway

### Role

Out of core runtime architecture.
May be used as a team knowledge utility only.

## Activation verification rule

Because these tools are owned and assumed available, the gating rule changes from redemption gating to activation verification gating.

A tool may be architecturally planned, but it is not runtime-approved until:

* the owning repo is assigned
* the adapter boundary is defined
* the Chummer receipt model exists
* the kill switch exists
* the provenance model exists
* fallback behavior exists
* secrets handling is defined
* the integration is reflected in milestones

## Contract additions

### In `Chummer.Run.Contracts`

Add:

* `ProviderRouteReceipt`
* `ProviderRouteRef`
* `ApprovalBridgeReceipt`
* `DocsHelpRef`
* `SurveyRef`
* `AutomationBridgeReceipt`
* `ResearchAssistReceipt`
* `PromptTemplateRef`
* `PromptRouteRef`

### In `Chummer.Media.Contracts`

Add:

* `MediaProviderReceipt`
* `MediaProviderRef`
* `MediaPlanHash`
* `MediaInputRef`
* `MediaSafetyResult`
* `MediaPreviewRef`
* `MediaArchiveRef`
* `MediaRetentionOverrideRef`
* `MediaRouteVisualizationRef`

### In `Chummer.Hub.Registry.Contracts`

Add only when promoted into reusable registry truth:

* `TemplatePackRef`
* `StylePackRef`
* `PublishedHelpRef`
* `ArtifactExternalPreviewRef`

## Release-gate rule

No external integration reaches production use until:

* adapter exists
* Chummer receipt exists
* Chummer kill switch exists
* Chummer provenance rules exist
* system-of-record rule is preserved
* owning repo is explicit
* milestone rollout is published
* client-side secret exposure is impossible
