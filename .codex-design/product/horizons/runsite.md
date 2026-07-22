# RUNSITE

## The problem

GMs spend too long describing spaces, and players still misread compounds, clubs, hotels, museums, arcologies, and safehouses once the action starts.

## What it would do

Chummer would publish explorable location packs linked to mission briefings.
They could include floor plans, hotspots, route overlays, optional narration, and static map context, but they stay focused on helping you understand the space before the run starts, not on replacing live combat tools or a VTT.
RUNSITE is for briefing, planning, and spatial understanding before things go loud.

## Likely owners

* `chummer6-hub`
* `chummer6-media-factory`

## Key tool posture

* `Crezlo Tours` - primary explorable-tour lane
* `AvoMap` - route and location visualization support
* `PeekShot` - preview/share-card adapter
* `vidBoard` - bounded orientation-host and walkthrough clip lane
* `Soundmadeseen` - optional narration layer
* `BrowserAct` - bounded operator automation and capture fallback

## What has to be true first

* clean media manifests
* permissioned publication links
* preview and embed receipts
* reliable map and render adapters

## Current proof posture

RUNSITE has first-party preview proof in the public artifact registry through runsite-pack framing and route-oriented artifact language.
The spatial lane should now read as an inspectable preview path, not a blank future tease.
Route overlays, pack inspection, and explorable tours remain the first-party truth surfaces; host clips stay secondary orientation siblings rather than tactical authority.
The live play shell may consume named room, zone, or hotspot anchors from a runsite pack, but the tour itself must not become exact tactical-position truth.

## Current product boundary

Chummer can present RUNSITE as a preview-backed spatial briefing lane when every pack has a reliable permission model, clear evidence links, and a first-party fallback if a hosted tour is unavailable.

That public meaning remains spatial orientation only.
RUNSITE does not claim combat, tactical authority, exact live positioning, initiative or action handling, VTT replacement, or mechanics mutation.
The pending governed spatial-render amendment does not change RUNSITE's shipped-MVP status, public claim, or release scope, and no provider is made ready by its prose.

## Governed recipe split

`runsite_continuous_walkthrough` is the spatial-orientation recipe.
It consumes an approved runsite source packet with immutable room, walkable-mesh, portal, required-room, route, style/license, permission, and provenance refs.
It must remain valid when every encounter or combat field is absent.
Its result is one continuous orientation path with all required rooms covered, no cuts or teleports, and inspectable route overlay, approved pack, and accepted tour or static siblings.
If build, provider, continuity, browser, accessibility, privacy, or provenance evidence fails, RUNSITE falls back to those non-combat inspection surfaces rather than inventing readiness.

`runsite_private_encounter_preview` is a separate private companion recipe, not an extension of the public RUNSITE promise.
It requires an explicit campaign-private audience allowlist plus immutable Core mechanics-receipt refs and Hub-owned encounter, run, scene, actor, equipment, and provided-outcome refs.
The renderer may depict bounded fictional, non-graphic choreography around the stable route, but it may not calculate, infer, reinterpret, or mutate initiative, actions, damage, effects, outcomes, campaign truth, or permissions.
Real-person likeness, graphic injury, minor combatants, public resharing, and audience-by-obscure-link are forbidden.

The private recipe is outside:

* PropertyQuarry input and product meaning
* public RUNSITE artifact types and public-signal eligibility
* live-session, exact-position, or tactical truth
* combat resolution and VTT authority

The verified PropertyQuarry authority record is external evidence, not RUNSITE or Chummer authority:

* decision: `/docker/property/PROPERTYQUARRY_GOVERNED_SPATIAL_RENDER_AUTHORITY_DECISION.md`, SHA-256 `401fe42211e2d8283ea9ca2a7cfc1a1eaffc80ff13c63fdf9e6158a116eff50a`
* product bridge: repo `/docker/property`, package `app.product`, module `app.product.property_tour_hosting`
* privacy lifecycle, intake, and closeout: repo `/docker/property`, package `app.api.routes`, module `app.api.routes.landing`
* minimization/redaction enforcement dependency: `public_tour_payloads`
* revocation and deletion execution dependency: `property_tour_hosting`

Chummer records but cannot assign, implement, authorize, operate, restore, revoke, delete, or close work for those external owners.
PropertyQuarry implementation remains blocked pending its numeric product policy and independent re-review.

Hub owns the Chummer bridge, private audience, consumer authorization, product presentation, takedown intake, and closeout.
Media-factory owns `governed_spatial_render_v1`, authoritative zero-burn compose receipts, authorized build/provider execution, jobs, idempotency and quota accounting, immutable output manifests, lifecycle/deletion, and encrypted private execution receipts.
Registry owns public publication and revocation; EA is limited to provider-redacted derived telemetry and synthetic zero-burn compose assistance.

Both recipes remain `blocked` and `proposed_for_independent_re_review` until the coherent canon, governed mirrors, executable contract/privacy/provenance/quality/browser/accessibility evidence, exact-family capability freshness, clean 48-hour canary, rollback, closeout, and explicit promotion authorities pass independently.
