# LTD stack wow-factor change guide

## Executive summary

Chummer already owns enough bounded external tools to ship a memorable, differentiated concierge plus artifact-factory experience.

The immediate problem is not missing tools.
The immediate problem was that the design and inventory had drifted:

* `FacePop`, `Lunacal`, and `Deftform` needed first-class representation in the design inventory.
* the old blocking rule was too blunt for low-risk public trust widgets.
* the media and support stacks were strong, but there was no first-class public concierge layer that turned those tools into obvious workflows.

## What to change in `chummer6-design`

### 1. Update the tool inventory and capability map

Add:

* `FacePop` as bounded public trust or concierge widget lane
* `Lunacal` as promoted booking and human-escalation lane
* `Deftform` as promoted structured intake lane

Also update the EA-side inventory to include:

* `FacePop` Tier 5
* `Lunacal` highest tier
* `Deftform`
* `hedy.ai` if activated and intended to stay

### 2. Rework the blocking policy

Adopt the policy in `EXTERNAL_TOOLS_BLOCKING_POLICY_REWORK.md`.

The important behavior change is:

* keep public trust widgets blocked on authenticated or truth-bearing surfaces
* allow them on Hub-owned public surfaces behind a narrow exception

### 3. Add the concierge model and registry

Land:

* `PUBLIC_CONCIERGE_AND_TRUST_WIDGET_MODEL.md`
* `PUBLIC_CONCIERGE_WORKFLOWS.yaml`

These become the canonical place for:

* routing flows
* allowed surfaces
* handoff lanes
* receipt expectations
* proof anchors

### 4. Expand current wow-factor workflows

Wire these first:

1. `downloads_concierge`
2. `campaign_invite_concierge`
3. `creator_consult_concierge`
4. `release_concierge`
5. `testimonial_capture`
6. `runsite_host_choice`

## Concrete integration designs

## Design A - Download and setup concierge

Goal:
Reduce install friction and make the public product feel human.

Surface:
`/downloads`

Recipe:

* FacePop short host clip
* CTA 1: download now -> first-party downloads truth
* CTA 2: which platform should I use? -> vidBoard explainer plus article fallback
* CTA 3: I need setup help -> Deftform support-enrichment form
* CTA 4: book a setup clinic -> Lunacal booking
* Email or confirmation -> Hub plus optional Emailit

Owners:

* Hub orchestrates
* Media Factory renders the long-form explainer siblings
* Registry owns download truth

## Design B - Campaign invite cold-open

Goal:
Turn campaign join pages into a polished onboarding moment.

Surface:
invite or join page

Recipe:

* FacePop campaign guide clip
* watch primer -> vidBoard primer
* read the packet -> MarkupGo primer packet
* book session zero -> Lunacal
* submit concept or questions -> Deftform
* collect usefulness after primer -> MetaSurvey

Why it matters:
This makes the campaign OS feel real before the user ever reaches the heavier workspace.

## Design C - Creator and publishing concierge

Goal:
Make creator publication feel premium and approachable.

Surface:
creator page, artifact page, runbook-press landing page

Recipe:

* FacePop creator host clip
* how publishing works -> vidBoard explainer
* open creator packet -> MarkupGo
* book a consult -> Lunacal
* submit interest or publish request -> Deftform
* capture testimonial after launch -> FacePop video review or MetaSurvey

## Design D - Release concierge and support closure

Goal:
Make updates and fixes feel human and trustworthy.

Surface:
`/now`, release pages, public help entry pages

Recipe:

* FacePop release host clip
* watch what changed -> vidBoard release explainer
* read notes -> first-party release notes
* need help updating -> Deftform support pre-intake
* book help -> Lunacal
* after successful fix or use -> FacePop testimonial capture

Important:
Do not place FacePop inside the actual support case timeline.
That surface stays first-party only.

## Design E - Runsite orientation host

Goal:
Give runsite or location artifacts a premium guided feel.

Surface:
runsite page or artifact page

Recipe:

* FacePop host asks how the user wants to explore
* host clip -> vidBoard
* route-first -> AvoMap
* explore -> Crezlo Tours
* preview or share -> PeekShot

## Design F - Table Pulse reaction booth (future, bounded)

Goal:
Add human texture to post-session feedback without violating the no-live-surveillance rule.

Surface:
post-session private follow-up link

Recipe:

* optional FacePop response capture asking what landed, what dragged, and what should continue
* Hedy and Nonverbia remain the structured or debrief analysis lanes
* FacePop responses are bounded qualitative inputs only
* Hub controls consent, retention, and moderation

This is future-bounded and must stay strictly separate from canonical session truth.

## Promotion plan for owned tools

### Promote now

* `Lunacal`
* `Deftform`

### Bounded but approved for pilot

* `FacePop`
* `hedy.ai`
* `Nonverbia`
* `Unmixr AI`

### Move toward active runtime adapters next

* `MarkupGo`
* `PeekShot`
* `Documentation.AI`
* `Soundmadeseen`
* `First Book ai`

### Keep as secondary support lanes

* `Mootion`
* `AvoMap`
* `Crezlo Tours`

## Required code or repo work

### `chummer6-design`

* update `EXTERNAL_TOOLS_PLANE.md`
* update `LTD_CAPABILITY_MAP.md`
* add concierge model and workflow registry
* add blocking-policy rewrite
* add `FacePop`, `Lunacal`, and `Deftform` references to public trust and guide policy where appropriate

### `chummer6-hub`

* implement public concierge wrapper routes
* implement webhook receipt ingestion for FacePop, Lunacal, and Deftform
* add first-party fallback states
* add telemetry events for concierge route choices

### `chummer6-media-factory`

* support vidBoard sibling artifacts for public concierge flows
* render preview cards and packet siblings
* store media provider receipts

### `chummer6-hub-registry`

* store publication references for approved testimonial or public proof artifacts
* store reusable concierge asset references where needed

### `executive-assistant`

* refresh `LTDs.md`
* verify account details for FacePop, Lunacal, Deftform, and vidBoard
* move tier posture upward only after real runtime use exists

## Release order

1. Download and setup concierge
2. Release concierge
3. Campaign invite cold-open
4. Creator consult funnel
5. Runsite host choice
6. Testimonial capture
7. Future Table Pulse reaction booth

## The wow factor

The wow factor is not one more AI toy.
It is the feeling that Chummer knows how to:

* greet me
* explain itself
* guide me to the right path
* give me a human option when I need it
* turn campaign truth into premium artifacts
* close the loop after something changes or is fixed

That feeling is now buildable with the LTDs already owned.
