# LTD capability map

This file maps owned LTD products to bounded architectural roles.
It does not imply that every owned tool must be integrated.

## States

* Promoted - product-relevant and accepted as an owned capability lane
* Bounded - accepted for narrow use with explicit limits
* Research / Parked - tracked and possibly useful, but not promoted into active product lanes
* Non-product - explicitly outside the product architecture

## Promoted

* `1min.AI` - low-cost governed reasoning fallback in `chummer6-hub`
* `AI Magicx` - structured AI provider and visual/media assistance lane
* `Prompting Systems` - prompt, style, and persona support for guide, horizon, and media workflows
* `BrowserAct` - no-API automation fallback, account verification, capture, and ops bridge
* `ApproveThis` - approval inbox bridge
* `ClickRank` - public site visibility, crawl-health, technical SEO, schema, metadata, and AI-search audit lane
* `Icanpreneur` - bounded discovery interview and validation lane
* `Katteb` - public-guide and public-content optimization lane downstream of approved source packets
* `MetaSurvey` - structured feedback and future-signal collection, not crash telemetry or ticket truth
* `NextStep` - operator process execution and governed checklist lane
* `ProductLift` - public feedback, voting, roadmap projection, changelog projection, and voter closeout lane
* `Soundmadeseen` - narrated media, recap, and briefing clips
* `Signitic` - passive outreach and signature-campaign projection lane
* `Emailit` - promoted outbound delivery provider for Hub-owned lifecycle, digest, and closeout mail
* `Taja` - approved media repurposing and distribution lane
* `Teable` - operator admin projection and AdminIntent workbench, never system of record
* `vidBoard` - structured presenter-video and multilingual walkthrough lane
* `Crezlo Tours` - explorable GM run-site artifacts
* `Deftform` - structured intake and concierge handoff lane
* `First Book ai` - long-form player, GM, and creator authoring lane
* `Lunacal` - booking and human-escalation lane
* `MarkupGo` - bounded document rendering and formatted artifact output
* `AvoMap` - route and location visualization lane
* `PeekShot` - preview/share-card adapter lane
* `Mootion` - bounded video generation lane
* `Documentation.AI` - docs/help projection surface downstream of canon, not first-line crash capture
* `Internxt Cloud Storage` - archive and retention support

## Bounded

* `Paperguide` - cited research and grounding helper
* `Vizologi` - product strategy and ideation support only
* `ApiX-Drive` - low-risk automation glue only, never truth
* `Browserly` - bounded browser capture and reference-pack helper
* `FacePop` - bounded public trust / concierge widget and moderated testimonial capture lane
* `hedy.ai` - bounded post-session transcript structure, highlight digest, and GM debrief helper for `TABLE PULSE`
* `Nonverbia` - post-session coaching and social-dynamics analysis lane
* `Unmixr AI` - candidate voice lane until proven

## Research / Parked

* `ChatPlayground AI` - provider comparison and evaluation lab only

## Non-product

* `FastestVPN PRO`
* `OneAir`
* `Headway`
* `Invoiless` - back-office billing utility only; not entitlement or premium truth

## Owner map

Default owner posture:

* `chummer6-hub` - orchestration, approvals, docs/help, surveys, and provider routing
* `chummer6-media-factory` - document, image, preview, audio, video, route, and archive adapters
* `chummer6-hub-registry` - publication references and compatibility metadata
* `chummer6-design` - policy, classification, and rollout authority

## Support plane posture

Current rule:

* Chummer does not need another AppSumo LTD to ship the core crash path.
* No AppSumo chat/support product is promoted as the first support feature.
* `MetaSurvey` and `Documentation.AI` are enough to start structured feedback and help projection behind Hub-owned adapters.
* The grounded support assistant is the phase-2 layer: Hub-owned, grounded on curated help/known-issue and signed-in case sources, and optional rather than gating crash or bug submission.
* Public concierge is a separate bounded lane: `FacePop` may help users choose a safe path on Hub-owned public surfaces, but it may not replace first-party support, install, auth, or case truth.

## Discovery, outreach, and validation posture

Working rule:

* `Icanpreneur` may collect adaptive interviews and synthesis, but Chummer-owned packets and Product Governor decisions remain canonical.
* `NextStep` may execute governed discovery, world-tick, media, release, and closeout checklists, but mirrored registries and canon remain the process truth.
* `Signitic` may amplify recruitment, release, BLACK LEDGER world-tick, and faction-war CTAs only as passive projection into first-party destinations.
* `Emailit` may deliver lifecycle and digest email only from Hub-owned notification truth, template refs, delivery receipts, and opt-out posture.
* `Teable` may expose operator workbenches and collect admin intent, but Hub validates authority, visibility, and invariants before any canonical write.
* `Taja` may repurpose approved media only after claim and publication approval; it does not become artifact truth.
* `ProductLift` may collect public ideas, votes, and reactions, but Chummer-owned packets and Product Governor decisions remain canonical.
* `Katteb` may draft or optimize public content only from approved source packets; accepted changes return to Chummer-owned source before publication.
* `ClickRank` may audit public crawl health, metadata, schema, internal links, and AI-search visibility, but Chummer-owned source and Product Governor/content-owner review remain canonical.

## Public concierge / trust posture

Working rule:

* `FacePop` is bounded to public, low-risk trust surfaces with a kill switch and first-party fallback.
* `Lunacal` may provide human escalation and booking, but it may not become support-case or campaign truth.
* `Deftform` may provide structured intake, but Hub-owned receipts and first-party followthrough remain canonical.
* `Signitic` may amplify public recruitment, release, world-tick, or faction-war campaigns, but those campaigns remain projections into first-party pages rather than notification truth, world truth, or authorization truth.
* `Emailit` may send claim/install mail, support closure, open-run invitations, world-tick digests, faction newsletters, creator-program mail, and ProductLift closeout only when Hub owns the notification event and suppression state.
* `ProductLift` may project `/feedback`, `/roadmap`, and `/changelog`, but it may not replace support, release, roadmap, or design truth.
* `Katteb` may improve public guide/article clarity, but it may not edit generated guide output directly or invent rules, support, campaign, or availability claims.
* `ClickRank` may recommend search and crawl improvements for public pages, but it may not mutate generated guide output, roadmap status, release status, support claims, or unshipped feature claims.
* Desktop, mobile, updater, claim-code, signed-in workspace, and support-thread surfaces remain first-party only.

## Bounded owner assignments

* `Paperguide` - `chummer6-design` for design research, `chummer6-hub` for operator help/research assist
* `Teable` - `chummer6-hub` for admin projections, curation queues, review boards, and AdminIntent receipt routing
* `Emailit` - `chummer6-hub` for outbound template selection, suppression, delivery receipts, and lifecycle notification closeout
* `ApiX-Drive` - `chummer6-hub` for low-risk automation glue
* `Browserly` - `chummer6-hub` for bounded capture/reference packets
* `Icanpreneur` - `chummer6-design` for discovery-interview posture and validation policy, `executive-assistant` for synthesis and packet normalization
* `ProductLift` - `chummer6-hub` for public routes and fallback behavior, `chummer6-design` for taxonomy and truth boundaries, `fleet` for digest and closeout evidence synthesis
* `Katteb` - `chummer6-hub` for public content destinations, `executive-assistant` for source briefs and synthesis, `chummer6-design` for allowed claims and upstream source truth
* `ClickRank` - `chummer6-hub` for public site crawl and metadata remediation, `chummer6-design` for search-visibility policy and source-truth boundaries, `executive-assistant` for findings normalization, `fleet` for weekly pulse evidence synthesis
* `FacePop` - `chummer6-hub` for public-surface routing, consent, fallback, and intake receipt mirroring; `chummer6-media-factory` for moderated testimonial derivative support
* `Deftform` - `chummer6-hub` for structured intake routing and receipt mirroring
* `Lunacal` - `chummer6-hub` for booking linkage and escalation routing
* `NextStep` - `fleet` for governed process execution and mirrored operator runbooks
* `Signitic` - `chummer6-hub` for destination shaping, segment routing, UTM naming, and public recruitment/release/world-tick campaign routing; `chummer6-design` for public-safe claim boundaries; `fleet` for bounded measurement review
* `Taja` - `chummer6-media-factory` for approved media repurposing and distribution only
* `hedy.ai` - `chummer6-hub` for consent-gated coaching packet orchestration, `chummer6-media-factory` for transcript prep and rendered recap packet support
* `Nonverbia` - `chummer6-hub` for coaching analysis and privacy gating, `chummer6-media-factory` for bounded rendered outputs
* `Unmixr AI` - `chummer6-media-factory` for bounded voice experiments

## Composed product systems

The owned LTD stack should be evaluated as governed product loops, not isolated vendor notes.

* Public Growth System - `ClickRank`, `Katteb`, `ProductLift`, `Signitic`, `Emailit`, `Taja`, and `vidBoard` route public discovery into first-party pages, changelog proof, and closeout.
* Discovery System - `ProductLift`, `Deftform`, `Icanpreneur`, `MetaSurvey`, `Lunacal`, `Teable`, and Product Governor convert public demand into Chummer-owned packets and decisions.
* Artifact Factory - `vidBoard`, `MarkupGo`, `PeekShot`, `Taja`, `Soundmadeseen`, `Unmixr AI`, and `First Book ai` render approved source packets into repeatable media, document, and share artifacts.
* BLACK LEDGER Ops - Hub, `Teable`, `NextStep`, `ApproveThis`, `Signitic`, `Emailit`, and first-party map infrastructure run world ticks, faction operations, open-run closeout, and operator review.
* Table Pulse / Companion Lab - `hedy.ai`, `Nonverbia`, `Unmixr AI`, `Soundmadeseen`, `MarkupGo`, `PeekShot`, `Prompting Systems`, `ChatPlayground AI`, and `Teable` support consent-gated debriefs and reviewed line packs.
* Trust / Closure System - Hub, Registry, Fleet, Product Governor, `ProductLift`, `Emailit`, and first-party analytics/observability prove that install, support, roadmap, and release promises actually closed.

Non-LTD production infrastructure candidates such as PostHog, Sentry, MapLibre, and LiveKit may be designed as first-party infrastructure lanes when needed. They are not substitutes for Chummer-owned truth.

## Optional purchase watchlist

The current leverage is wiring, governance, and receipts, not another generic AI tool. Optional buys are only justified when they fill a concrete operating gap:

* `SendFox` - public newsletter and digest list if Emailit stays primarily transactional.
* `Flonnect` - bounded QA, bug reproduction, support evidence, tutorial, and operator-training capture.
* `CutMe Short` - branded links, UTM discipline, expiry, rotators, and campaign-link analytics if Signitic/Taja/vidBoard/FacePop links get hard to govern.
* `Backona AI` - operator question layer over GA4/Search Console only if ClickRank, PostHog, and GSC dashboards are not getting used.
* `Visby` - optional AI-answer visibility and competitor/gap monitoring after ClickRank and Katteb are already in use.

Do not chase more generic AI writers, support widgets, no-code databases, meeting recorders, project-management apps, or video generators until the composed product systems above produce receipts.

## Horizon capability map

Any public-eligible horizon may additionally use `ProductLift`, `Icanpreneur`, `MetaSurvey`, `FacePop`, `Deftform`, `Lunacal`, `Signitic`, and `Emailit` as discovery, intake, amplification, or closeout lanes only. Those systems may shape demand evidence and user followthrough, but they do not become runtime or canon truth.

* `nexus-pan`
  No promoted LTD should own continuity truth.
  `Emailit`, `Documentation.AI`, `PeekShot`, and `BrowserAct` stay bounded helper lanes for reconnect notices, recovery help, continuity receipts, and operator capture only.
* `alice`
  `AI Magicx` is the promoted compare-brief and explain-helper lane around engine-owned build truth.
  `1min.AI` and `Prompting Systems` are bounded draft and style helpers.
  `MarkupGo` and `PeekShot` are bounded compare-packet and receipt-preview lanes.
  `FacePop` and other public concierge tools remain outside the runtime feature path.
* `knowledge-fabric`
  `Prompting Systems`, `Documentation.AI`, and `AI Magicx` are the promoted explain/docs projection lanes.
  `1min.AI`, `BrowserAct`, and `Paperguide` remain bounded specialist, capture, and citation helpers only.
* `jackpoint`
  `vidBoard`, `MarkupGo`, `Soundmadeseen`, `PeekShot`, and `Documentation.AI` are the promoted packet, video, narration, preview, and docs lanes.
  `Unmixr AI`, `Mootion`, `Paperguide`, and `First Book ai` remain bounded helper lanes only.
* `black-ledger`
  `Teable`, `NextStep`, `ApproveThis`, `Signitic`, and `Emailit` are the promoted world-ops, approval, projection, and digest lanes.
  `vidBoard`, `MarkupGo`, `PeekShot`, `Soundmadeseen`, and `Taja` are bounded downstream world-output lanes only.
  `MetaSurvey`, `Deftform`, `Lunacal`, `BrowserAct`, and `Documentation.AI` remain bounded discovery, intake, capture, and support helpers.
* `community-hub`
  `Deftform`, `Lunacal`, `MetaSurvey`, `Teable`, `NextStep`, `ApproveThis`, and `Emailit` are the promoted intake, scheduling, review, operator, and closeout lanes.
  `FacePop`, `Signitic`, `vidBoard`, `Taja`, `hedy.ai`, `Nonverbia`, and `BrowserAct` remain bounded public-entry, debrief, and recap helpers only.
* `runsite`
  `Crezlo Tours`, `AvoMap`, and `PeekShot` are the promoted explorable/location lanes.
  `vidBoard` and `Soundmadeseen` are bounded orientation and narration layers.
  `BrowserAct` and `Browserly` are bounded capture and reference support only.
* `runbook-press`
  `First Book ai`, `MarkupGo`, `Documentation.AI`, `vidBoard`, and `Soundmadeseen` are the promoted authoring, export, explainer, and narrated companion lanes.
  `Paperguide` and `Unmixr AI` remain bounded helper lanes only.
* `karma-forge`
  `Icanpreneur`, `Deftform`, `Lunacal`, `MetaSurvey`, `Teable`, `NextStep`, and `ApproveThis` are the promoted discovery, triage, and governed process lanes.
  `FacePop`, `Signitic`, `Emailit`, `Taja`, `vidBoard`, `Prompting Systems`, and `AI Magicx` are bounded recruitment, closeout, and approved explainer lanes only.
* `ghostwire`
  `PeekShot`, `MarkupGo`, and `Soundmadeseen` are the promoted replay-surface, report, and narrated recap lanes.
  `Mootion` and `Paperguide` remain bounded replay-video and cited reconstruction helpers only.
* `table-pulse`
  `Nonverbia` is the promoted primary coaching and social-dynamics lane.
  `hedy.ai`, `vidBoard`, `Soundmadeseen`, `Unmixr AI`, `MarkupGo`, and `PeekShot` remain bounded debrief, recap, narration, render, and preview helpers only.
  These tools may generate post-session coaching views and narrated guidance, but they do not become session truth, discipline systems, moderation truth, or player-scoring authority.
* `local-co-processor`
  No promoted external tool should own local acceleration truth.
  `1min.AI`, `AI Magicx`, `BrowserAct`, and `Documentation.AI` remain bounded hosted-local parity, operator capture, and guidance helpers only.
  These tools may help benchmark or explain hosted-local parity, but they do not become the owner of local acceleration truth or required runtime availability.
