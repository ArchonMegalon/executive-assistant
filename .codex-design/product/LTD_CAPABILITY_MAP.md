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
* `Icanpreneur` - bounded discovery interview and validation lane
* `MetaSurvey` - structured feedback and future-signal collection, not crash telemetry or ticket truth
* `NextStep` - operator process execution and governed checklist lane
* `Soundmadeseen` - narrated media, recap, and briefing clips
* `Signitic` - passive outreach and signature-campaign projection lane
* `Taja` - approved media repurposing and distribution lane
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
* `Teable` - curation and projection board only, never system of record
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
* `Invoiless`

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
* `Signitic` may amplify recruitment and release CTAs only as passive projection into first-party destinations.
* `Taja` may repurpose approved media only after claim and publication approval; it does not become artifact truth.

## Public concierge / trust posture

Working rule:

* `FacePop` is bounded to public, low-risk trust surfaces with a kill switch and first-party fallback.
* `Lunacal` may provide human escalation and booking, but it may not become support-case or campaign truth.
* `Deftform` may provide structured intake, but Hub-owned receipts and first-party followthrough remain canonical.
* `Signitic` may amplify public recruitment or release campaigns, but those campaigns remain projections into first-party pages rather than notification truth.
* Desktop, mobile, updater, claim-code, signed-in workspace, and support-thread surfaces remain first-party only.

## Bounded owner assignments

* `Paperguide` - `chummer6-design` for design research, `chummer6-hub` for operator help/research assist
* `Teable` - `chummer6-hub` for curation/projection workflows
* `ApiX-Drive` - `chummer6-hub` for low-risk automation glue
* `Browserly` - `chummer6-hub` for bounded capture/reference packets
* `Icanpreneur` - `chummer6-design` for discovery-interview posture and validation policy, `executive-assistant` for synthesis and packet normalization
* `FacePop` - `chummer6-hub` for public-surface routing, consent, fallback, and intake receipt mirroring; `chummer6-media-factory` for moderated testimonial derivative support
* `Deftform` - `chummer6-hub` for structured intake routing and receipt mirroring
* `Lunacal` - `chummer6-hub` for booking linkage and escalation routing
* `NextStep` - `fleet` for governed process execution and mirrored operator runbooks
* `Signitic` - `chummer6-hub` for destination shaping and public recruitment/release campaign routing; `fleet` for bounded measurement review
* `Taja` - `chummer6-media-factory` for approved media repurposing and distribution only
* `hedy.ai` - `chummer6-hub` for consent-gated coaching packet orchestration, `chummer6-media-factory` for transcript prep and rendered recap packet support
* `Nonverbia` - `chummer6-hub` for coaching analysis and privacy gating, `chummer6-media-factory` for bounded rendered outputs
* `Unmixr AI` - `chummer6-media-factory` for bounded voice experiments

## Horizon capability map

* `jackpoint`
  `vidBoard` is the promoted structured presenter-video lane for dossiers, briefings, explainers, and creator promo clips.
  `Soundmadeseen` is the promoted narration lane for recap and briefing media.
  `Unmixr AI` is bounded candidate voice only.
  `Browserly` is bounded evidence and reference capture only.
* `runsite`
  `vidBoard` is the promoted orientation-host clip lane.
  `Crezlo Tours`, `AvoMap`, and `PeekShot` are the promoted explorable/location lanes.
  `Soundmadeseen` is an optional narration layer.
  `Browserly` is bounded capture and reference support only.
* `runbook-press`
  `vidBoard` is the promoted campaign primer and module explainer video lane.
  `First Book ai`, `MarkupGo`, and `Documentation.AI` are the promoted authoring/export lanes.
  `Soundmadeseen` is the promoted narrated companion lane.
  `Unmixr AI` and `Browserly` remain bounded helper lanes only.
* `karma-forge`
  `Icanpreneur` is the promoted discovery interview and synthesis lane for house-rule demand.
  `Deftform`, `Lunacal`, and `MetaSurvey` are the promoted pre-screen, follow-up, and quant-validation lanes.
  `NextStep` is the promoted governed process runner for discovery sprints and prototype approvals.
  `FacePop` and `Signitic` are bounded recruitment-entry and passive amplification lanes only.
  `Taja` and `vidBoard` are bounded approved-media lanes for discovery explainers only.

## Table coaching / social dynamics

Horizon fit:

* `TABLE PULSE`

Current cluster:

* `Nonverbia`
* `hedy.ai`
* bounded `vidBoard`
* bounded `Soundmadeseen`
* bounded `Unmixr AI`
* bounded `MarkupGo`
* bounded `PeekShot`

Working rule:
These tools may generate post-session coaching views and narrated guidance, but they do not become session truth, discipline systems, moderation truth, or player-scoring authority.
