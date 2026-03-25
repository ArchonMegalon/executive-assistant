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
* `MetaSurvey` - structured feedback and future-signal collection, not crash telemetry or ticket truth
* `Soundmadeseen` - narrated media, recap, and briefing clips
* `Crezlo Tours` - explorable GM run-site artifacts
* `First Book ai` - long-form player, GM, and creator authoring lane
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
* Any later support assistant is phase 2, Hub-owned, grounded on curated help/known-issue sources, and optional rather than gating crash or bug submission.

## Bounded owner assignments

* `Paperguide` - `chummer6-design` for design research, `chummer6-hub` for operator help/research assist
* `Teable` - `chummer6-hub` for curation/projection workflows
* `ApiX-Drive` - `chummer6-hub` for low-risk automation glue
* `Browserly` - `chummer6-hub` for bounded capture/reference packets
* `Nonverbia` - `chummer6-hub` for coaching analysis and privacy gating, `chummer6-media-factory` for bounded rendered outputs
* `Unmixr AI` - `chummer6-media-factory` for bounded voice experiments

## Horizon capability map

* `jackpoint`
  `Soundmadeseen` is the promoted narration lane for recap and briefing media.
  `Unmixr AI` is bounded candidate voice only.
  `Browserly` is bounded evidence and reference capture only.
* `runsite`
  `Crezlo Tours`, `AvoMap`, and `PeekShot` are the promoted explorable/location lanes.
  `Soundmadeseen` is an optional narration layer.
  `Browserly` is bounded capture and reference support only.
* `runbook-press`
  `First Book ai`, `MarkupGo`, and `Documentation.AI` are the promoted authoring/export lanes.
  `Soundmadeseen` is the promoted narrated companion lane.
  `Unmixr AI` and `Browserly` remain bounded helper lanes only.

## Table coaching / social dynamics

Horizon fit:

* `TABLE PULSE`

Current cluster:

* `Nonverbia`
* bounded `Soundmadeseen`
* bounded `Unmixr AI`
* bounded `MarkupGo`
* bounded `PeekShot`

Working rule:
These tools may generate post-session coaching views and narrated guidance, but they do not become session truth, discipline systems, moderation truth, or player-scoring authority.
