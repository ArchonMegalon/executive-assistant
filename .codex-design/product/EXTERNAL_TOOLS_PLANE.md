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

`PROVIDER_AND_ROUTE_STEWARDSHIP.md` defines the standing review, canary, promotion, and rollback loop for provider and model defaults inside those bounded routes.

## Core rule

External tools may assist, route, render, summarize, visualize, archive, notify, project, interview, or schedule. They may not become the canonical source of rules truth, session truth, approval truth, registry truth, media truth, notification truth, roster truth, entitlement truth, analytics interpretation truth, or canon truth.

External workbenches may collect operator edits, assignments, review outcomes, and proposed status changes only as Chummer-owned `AdminIntent` inputs. Hub or the relevant canonical service must validate authority, visibility, invariants, and receipts before any canonical write.

Research and interview tools may collect interviews and produce synthesis outputs, but they may not become feature truth, implementation priority, or backlog ownership.

Chummer-owned repos and Chummer-owned manifests/stores remain authoritative.
Owning an LTD does not obligate Chummer to integrate it.
A tool may be promoted, bounded, parked, or explicitly excluded.

## Tool inventory posture

Current known external-tool inventory includes:

* 1min.AI
* Prompting Systems
* ChatPlayground AI
* Soundmadeseen
* vidBoard
* AI Magicx
* FastestVPN PRO
* OneAir
* Headway
* hedy.ai
* Internxt Cloud Storage
* ApiX-Drive
* ApproveThis
* AvoMap
* BrowserAct
* Browserly
* ClickRank
* Crezlo Tours
* Deftform
* Documentation.AI
* Emailit
* FacePop
* First Book ai
* Icanpreneur
* Katteb
* Invoiless
* Lunacal
* MarkupGo
* MetaSurvey
* Mootion
* NextStep
* Nonverbia
* Paperguide
* PeekShot
* ProductLift
* Signitic
* Taja
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
* Emailit - workspace integration Tier 3 until sender-domain, suppression, template, and delivery-receipt gates are complete
* Paperguide - workspace integration Tier 3, vendor license plan Tier 4

Chummer routing, rollout, and architectural ownership should follow workspace integration tier and system-of-record safety rules, not marketing or license-plan tier labels.

## Horizon-facing bounded lanes

Horizons may consume owned LTDs only through bounded capability lanes.
The horizon docs decide whether a lane is active; this document decides which kinds of LTD use are architecturally allowed.

Current horizon-facing posture:

* `jackpoint` - structured presenter-video and multilingual briefing lanes may use `vidBoard`; narrated recap and briefing lanes may use `Soundmadeseen`; bounded candidate voice may use `Unmixr AI`; evidence/capture packets may use `Browserly`
* `black-ledger` - world-tick and faction-war operations may use `Teable` for admin projection and AdminIntent entry, `NextStep` for SOP execution, `ApproveThis` for guest approvals, `Signitic` for passive signature campaigns, `Emailit` for Hub-owned digest and closeout mail, `vidBoard` / `Taja` / `PeekShot` / `MarkupGo` / `Soundmadeseen` for approved artifacts, and first-party map infrastructure for map truth
* `karma-forge` - governed house-rule discovery may use `Icanpreneur` for interviews and synthesis, `Deftform` for pre-screening, `Lunacal` for follow-up clinics, `MetaSurvey` for quant validation, `Teable` for candidate review boards and AdminIntent entry, `NextStep` for sprint/process execution, and bounded `FacePop` / `Signitic` / `Emailit` / `vidBoard` / `Taja` for recruitment, closeout, and approved discovery explainers
* `shadowcasters-network` - open-run discovery and scheduling may use `Lunacal`, `Deftform`, `FacePop`, `Teable`, `NextStep`, `MetaSurvey`, `Emailit`, and bounded `Signitic` / `vidBoard` / `Taja` for recruiting, application review, invite delivery, and recap projection; `hedy.ai` and `Nonverbia` may assist GM-private or consent-gated debrief flows only; Discord, Teams, generic meeting URLs, Foundry, Roll20, and comparable play surfaces remain projection-only handoff or export targets and may not own run, roster, consent, or resolution truth
* `runsite` - explorable location artifacts may use `Crezlo Tours`, `AvoMap`, and `PeekShot`; orientation-host clips may use `vidBoard`; optional narration may use `Soundmadeseen`; bounded capture/reference packets may use `Browserly`; route, map, and tour siblings stay first-party inspectable truth and the media layer may not become tactical authority
* `runbook-press` - long-form authoring and export may use `First Book ai`, `MarkupGo`, and `Documentation.AI`; campaign primer and module explainer videos may use `vidBoard`; narrated companion assets may use `Soundmadeseen`; bounded candidate voice or reference capture may use `Unmixr AI` and `Browserly`
* `table-pulse` - post-session coaching packets may use `Nonverbia` as the primary analysis lane, `hedy.ai` as the bounded session-structure and debrief helper lane, with later bounded player-safe recap / GM-private debrief video from `vidBoard`, plus bounded narrated/report outputs from `Soundmadeseen`, `Unmixr AI`, `MarkupGo`, and `PeekShot`

## Public trust and concierge posture

Public trust surfaces may consume owned LTDs only through bounded public-concierge lanes that route into first-party Chummer truth.

Current public-surface posture:

* Hub-owned public trust surfaces such as `/downloads`, `/now`, public help entry pages, artifact pages, creator pages, and tokenized invite pages that expose no private truth may use `FacePop` as a bounded public concierge or trust-widget lane
* public intake or guided escalation may use `Deftform` for structured intake and `Lunacal` for human booking only when Chummer-owned fallback paths and receipt mirroring remain intact
* public or network-visible open-run discovery may use `FacePop`, `Deftform`, and `Lunacal` for first contact, application intake, and booking projection only when accepted-roster truth, meeting-handoff truth, and observer-consent truth remain first-party
* community-run play surfaces such as Discord, Teams, Foundry, Roll20, or generic meeting URLs may receive handoff and export packages only when Chummer remains the first-party authority for run, roster, rule-environment, and closeout truth
* passive outreach and recruitment projection may use `Signitic` only when the CTA lands on first-party Chummer pages and any resulting intake still lands in Chummer-owned receipts or routes
* outbound email may use `Emailit` only when Hub owns the notification event, template reference, suppression state, delivery receipt, unsubscribe posture, and user-visible closeout truth
* public concierge flows may use `vidBoard`, `MarkupGo`, `PeekShot`, and `Soundmadeseen` as sibling explainer and artifact lanes, but those companions remain downstream of Chummer-owned release, support, invite, and publication truth
* public feature ideas, votes, roadmap projection, changelog projection, and voter closeout may use `ProductLift` only as a projection of Chummer-owned design, milestone, release, and closeout truth
* public guide readability, SEO, AI-search visibility, and article-draft work may use `Katteb` only against approved source packets; accepted changes must flow upstream into `chummer6-design` or public-guide source registries before generated guide output changes
* public site crawl health, technical SEO, metadata/schema coverage, broken-link checks, internal-link suggestions, and AI-search visibility measurement may use `ClickRank` only as audit and recommendation output; accepted changes still patch Chummer-owned source first

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

### Class C1 - Public trust / concierge widgets

These are bounded public-surface widgets that humanize first contact and route visitors into Chummer-owned truth paths without becoming truth themselves.

Examples:

* optional concierge greetings on `/downloads` or `/now`
* public booking wrappers for setup or creator consult lanes
* moderated testimonial capture on public proof or follow-up pages

### Class C2 - Passive outreach projection integrations

These amplify public invitations or release campaigns, but only by routing people toward first-party Chummer destinations.

Examples:

* email-signature CTA campaigns
* passive recruitment banners
* release-campaign link rotations

### Class C3 - Operator process execution integrations

These execute runbooks, closeout loops, or checklist discipline for operators, but they do not become the canonical process truth.

Examples:

* discovery sprint SOP runners
* media publication checklists
* release closeout checklists
* localization or review gates

### Class C4 - Public feedback, roadmap, and changelog projection

These collect and project public demand, visible roadmap posture, changelog entries, and voter closeout notices without becoming roadmap, support, release, or priority truth.

Examples:

* public feature idea boards
* public voting and comments
* public roadmap projection
* changelog projection
* voter notifications backed by Chummer-owned closeout evidence

### Class C5 - Admin projection and intent-entry workbenches

These expose operator queues, dashboards, review boards, and editable projections, but every write-back is an `AdminIntent` that Chummer validates before state changes.

Examples:

* BLACK LEDGER tick control rooms
* intel review queues
* open-run application review boards
* KARMA FORGE candidate triage
* creator-publication queues
* companion line-pack review boards

### Class C6 - Outbound delivery providers

These deliver Chummer-owned lifecycle, digest, invite, and closeout messages. They do not own notification truth, support status, roadmap status, world truth, suppression policy, or analytics interpretation.

Examples:

* claim/install emails
* support closure mail
* open-run invitations and decisions
* BLACK LEDGER world-tick digests
* faction newsletters
* ProductLift voter closeout follow-ups

### Class D - Research / eval / prompt-tooling integrations

These inform product quality, content quality, or design quality, but they do not directly own end-user truth.

Examples:

* evaluation labs
* prompt research
* cited synthesis
* product strategy ideation
* bounded coaching and social-dynamics analysis

### Class D1 - Discovery / interview integrations

These collect adaptive interviews, research intake, or validation loops, but they do not directly own feature truth or implementation priority.

Examples:

* discovery interviews
* follow-up validation calls
* concept-sprint synthesis
* post-cluster ranking surveys

### Class D2 - Public content optimization and AI-search visibility

These audit or draft public-facing explanatory content against approved source packets, but accepted changes must return to Chummer-owned source before publication.

Examples:

* generated-guide readability audits
* public article drafts
* SEO and AI-search visibility recommendations
* title, description, FAQ, and metadata suggestions

### Class D3 - Public site visibility and crawl health

These audit crawlability, metadata, schema, internal links, broken links, search-console signals, and AI-search visibility for public surfaces. They do not own public copy, product claims, release status, roadmap status, support status, or generated-guide output.

Examples:

* technical SEO audits
* Google Search Console keyword opportunity review
* broken-link and duplicate-tag reports
* crawler-access checks
* schema and metadata recommendations
* AI-search visibility measurements

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

### Rule 5 - no client-side vendor coupling on authenticated or truth-bearing surfaces

No browser, mobile, or desktop repo may embed vendor credentials or rely on vendor SDKs on authenticated, truth-bearing, or runtime-critical surfaces.

This includes:

* signed-in home surfaces
* campaign workspace
* support case views
* install/update flows
* crash/bug submission forms
* desktop/mobile runtime UX
* admin/operator surfaces

### Rule 5a - public concierge widget exception

A bounded external widget may appear on a Hub-owned public surface only when all of the following are true:

* the surface is public, low-risk, and not the owner of canonical truth
* the widget is optional and removable via kill switch
* fixed first-party route truth stays visible without the widget
* preview language stays visibly secondary to the first-party route or status surface
* the widget has a graceful first-party fallback path
* recovery posture routes into first-party help, relinking, or escalation copy instead of treating the widget as the recovery mechanism
* no vendor secret or private access token is exposed client-side
* the widget does not become the system of record for support, install, auth, publication, or campaign truth
* every meaningful submission or route result is mirrored back into Chummer-owned receipts or first-party destinations
* accessibility and locale review are complete

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

### Rule 9a - concierge widgets may route to support; they may not replace support

A public concierge widget may:

* help the user choose between help paths
* route to Deftform or Hub support intake
* route to Lunacal for human escalation
* show a short human greeting or explainer

A public concierge widget may not:

* claim to resolve support cases itself
* become the support ticket or case record
* hide the first-party support path
* block access to first-party support when disabled
* present fallback or manual install routes as the recommended path through warmer copy
* claim that a fix is already available for this user when the first-party release or support receipt does not say so

## Allowed and forbidden public concierge surfaces

Allowed:

* public landing pages
* `/downloads`
* `/now`
* public help entry pages
* public artifact and creator pages
* tokenized invite pages that expose no private truth

Forbidden:

* desktop app
* mobile app
* signed-in home
* authenticated campaign workspace
* updater dialogs
* claim-code entry forms
* case timeline and support-thread views
* admin, governor, or operator surfaces

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

## Icanpreneur

### Role

Adaptive discovery interview and synthesis lane.

### Architectural use

* KARMA FORGE house-rule discovery
* GM Companion persona validation
* BLACK LEDGER discovery
* creator and onboarding message validation
* packet-oriented demand synthesis

### Owner

* lane policy: `chummer6-design`
* packet normalization and synthesis support: `executive-assistant`

### Hard boundary

* not canonical feature truth
* not canonical backlog ownership
* not direct implementation priority
* not a raw rulebook-text capture surface

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

## NextStep

### Role

Operator process execution layer.

### Architectural use

* discovery sprint SOPs
* world-tick and BLACK LEDGER procedures
* media publication checklists
* release closeout and verification steps
* localization and review gates

### Owner

* `fleet`

### Hard boundary

* not canonical process truth by itself
* not support, campaign, or world truth
* not design canon

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

Admin projection and intent-entry workbench.

### Architectural use

* BLACK LEDGER world-tick control rooms
* intel, job-seed, JobPacket, OpenRun, ResolutionReport, newsreel, and seasonal-honors queues
* KARMA FORGE candidate review boards
* creator-publication review queues
* support/content signal curation boards
* companion line-pack review boards
* operator assignments, notes, and proposed status changes emitted as `AdminIntent`

### Owner

* `chummer6-hub`

### Hard boundary

* not runtime database
* not world, campaign, roster, support, rules, registry, release, or entitlement truth
* not direct canonical write path
* not approval truth without Hub-side validation and receipting
* no private player, faction-secret, sourcebook, or support payload exposure unless a Hub-owned projection explicitly permits it

### Required receipt model

Teable projections must carry source object refs, projection version, editable-field allowlists, role scope, export time, expiry, and a Chummer correlation id. Teable write-backs must return as `AdminIntent` packets, not direct DB updates.

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

## FacePop

### Role

Public trust widget, concierge, and recruitment lane.

### Architectural use

* public recruitment prompts
* low-risk branching CTAs
* moderated testimonial capture
* routing to Deftform, Lunacal, Hub pages, or approved artifact pages

### Owner

* `chummer6-hub`

### Hard boundary

* not support-case truth
* not install or account truth
* not campaign truth
* not desktop or mobile runtime UX

## Deftform

### Role

Structured prescreen and intake lane.

### Architectural use

* role and edition classification
* rule-category intake
* consent capture
* support or discovery enrichment
* safe follow-up routing

### Owner

* `chummer6-hub`

### Hard boundary

* not canonical backlog truth
* not support-case truth
* not rules truth

## Lunacal

### Role

Follow-up booking and human-escalation lane.

### Architectural use

* GM follow-up calls
* creator clinics
* setup or onboarding calls
* organizer or BLACK LEDGER pilot sessions

### Owner

* `chummer6-hub`

### Hard boundary

* not support-case truth
* not campaign truth
* not final approval truth

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

## Signitic

### Role

Passive outreach and signature-campaign projection lane.

### Architectural use

* public recruitment CTAs
* release or launch campaign amplification
* KARMA FORGE, BLACK LEDGER, or companion discovery campaigns
* BLACK LEDGER world-tick and faction-war signature campaigns after source approval
* Shadowcasters open-run, GM recruitment, and creator-program CTA rotation
* creator-program CTA rotation

### Owner

* destination shaping: `chummer6-hub`
* campaign packet, segment, and UTM routing: `chummer6-hub`
* public-safe claim approval: `chummer6-design` Product Governor or approved world operator
* bounded measurement review: `fleet`

### Hard boundary

* not notification truth
* not support-case notification truth
* not analytics interpretation truth
* not campaign or world truth
* not private player, runner, faction-secret, account, security, or entitlement state
* not individual authorization or delivery guarantees

### Campaign packet requirements

Every BLACK LEDGER or Shadowcasters Signitic campaign must carry approved source receipts, first-party destination URLs, UTM campaign naming, segment scope, expiry or review date, rollback owner, and a kill-switch path.

Signitic metrics are campaign telemetry only. Hub and Fleet may review clickthrough, landing conversion, support confusion, and world-effect receipts, but Product Governor interpretation remains Chummer-owned.

## Emailit

### Role

Outbound delivery provider candidate for Hub-owned lifecycle, digest, invite, and closeout mail.

### Architectural use

* claim/install emails
* support closure and fix-available notices
* ProductLift voter closeout follow-ups
* Shadowcasters open-run invitations, acceptance, waitlist, and reminder mail
* Lunacal companion confirmations when Hub needs a first-party mail receipt
* BLACK LEDGER world-tick digests and faction newsletters
* creator-program updates
* KARMA FORGE discovery invitations

### Owner

* notification truth, template refs, suppression, opt-out posture, and delivery receipts: `chummer6-hub`
* release/install availability facts used in mail: `chummer6-hub-registry`
* public-safe claim and campaign boundaries: `chummer6-design`

### Hard boundary

* not notification truth
* not support status truth
* not roadmap or changelog truth
* not world, campaign, roster, entitlement, security, or authorization truth
* not analytics interpretation truth
* no raw secret, sourcebook, support-note, or private campaign payloads in templates

### Promotion gates

Emailit is not production-approved until sender-domain authentication, suppression and unsubscribe policy, bounce handling, template registry, `EmailDeliveryReceipt`, kill switch, and provider-secret handling are implemented.

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

## Taja

### Role

Approved media repurposing and distribution adapter.

### Architectural use

* approved short-form clip repurposing
* discovery and launch snippet extraction
* creator/publisher promo derivative drafts
* first-party distribution copy support

### Owner

* `chummer6-media-factory`

### Hard boundary

* not source of media truth
* not an approval bypass
* not allowed to mint unapproved product claims

## vidBoard

### Role

Structured presenter-video and multilingual walkthrough adapter.

### Architectural use

* public release explainers
* campaign primer videos
* mission briefing videos
* runsite orientation clips
* support closure videos
* creator promo videos
* later bounded player-safe recap or GM-private debrief videos

### Owner

* execution: `chummer6-media-factory`
* orchestration, approvals, locale routing, and publication shaping: `chummer6-hub`

### Hard boundary

* not canonical rules truth
* not canonical support truth
* not canonical session truth
* not canonical route, map, or tour truth
* not direct-to-client vendor coupling
* not unapproved public publication

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
* `NotificationTemplateRef`
* `EmailDeliveryReceipt`

### In `Chummer.Control.Contracts`

Add:

* `AdminProjectionReceipt`
* `AdminIntent`
* `AdminIntentReceipt`
* `JourneyProofEventRef`

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
