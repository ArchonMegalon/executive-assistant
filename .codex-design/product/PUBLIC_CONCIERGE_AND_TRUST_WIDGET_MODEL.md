# Public concierge and trust widget model

## Purpose

Project Chummer already has a strong first-party release, support, campaign, and publication model. It now also owns a stronger bounded external-tool stack that can humanize those surfaces without surrendering canonical truth.

This document defines the missing product layer between:

* first-party truth surfaces (`/downloads`, `/now`, `/contact`, artifact pages, campaign invite pages)
* bounded humanized guidance (`FacePop`)
* structured intake (`Deftform`)
* human booking or escalation (`Lunacal`)
* polished explainer and briefing artifacts (`vidBoard`, `Soundmadeseen`, `MarkupGo`, `PeekShot`)

The goal is not to turn Chummer into a vendor-widget collage. The goal is to create high-trust concierge experiences that make the product feel alive while keeping support, install, publication, and campaign truth first-party.

## Audit summary

What is already strong:

* Chummer already has `PUBLIC_VIDEO_BRIEFS.yaml` and `MEDIA_ARTIFACT_RECIPE_REGISTRY.yaml` for structured presenter-video and sibling artifact families.
* `vidBoard` is already promoted for release explainers, campaign primers, mission briefings, runsite orientation clips, support-closure videos, and creator promo videos.
* `table-pulse` already has a bounded post-session media and coaching lane.
* Hub already owns the public trust shelf, downloads, support intake, private case truth, human escalation, and publication shaping.

What this model closes:

* no first-class public concierge or trust-widget model
* no machine-readable workflow family for `FacePop -> Deftform -> Lunacal -> Hub` handoff
* no first-class testimonial or response-capture lane
* no policy exception for public, low-risk trust widgets on Hub-owned pages
* drift between the recently acquired tools (`FacePop`, `Lunacal`, `Deftform`) and the design or EA inventory

## Core product idea

Chummer should add a concierge layer on top of the first-party web surface.

A concierge flow is a humanized, branching, low-risk entrypoint that helps the user choose the next safe action quickly.

The concierge layer must:

* feel personal and high-trust
* work on public or invite-style pages first
* route into Chummer-owned truth paths
* degrade gracefully when the external widget is disabled
* never become the canonical owner of support, install, campaign, or publication state

## Truth and posture vocabulary

Public concierge surfaces must use one explicit posture vocabulary:

* fixed posture: the first-party route, release note, support article, status page, or intake path the user can rely on even when the widget is gone
* preview posture: the optional concierge overlay, explainer card, or branching helper that can make the entrypoint warmer without becoming the authority
* fallback posture: the visible secondary or manual path that still works when the recommended route is unavailable, gated, or support-directed
* recovery posture: the first-party article, intake, relinking, or human-escalation path that gets the user back to a safe next action without asking the widget to hold secrets or private truth

The widget may describe these paths.
The widget may not blur them.

## Posture rules

Every public concierge flow must keep the following distinctions visible:

* fixed routes stay first-party and must be reachable without opening the widget
* preview copy must say it is an optional guide, explainer, or concierge layer rather than the product authority
* fallback copy must explicitly say when a route is secondary, compatibility-only, manual, or support-directed
* recovery copy must name the real first-party help, relinking, or escalation path and must not imply the widget repaired anything itself

If public copy says a route is fixed, recommended, current, or available now, that claim must already be true in the first-party release, help, or status surface that owns it.

## Public recovery posture

Recovery is allowed on public concierge surfaces only as an orientation or routing layer.

Allowed recovery moves:

* open the first-party recovery article or install-help page
* route to Deftform pre-intake when structured details help support
* route to Lunacal when the documented escalation policy says a human help session is warranted
* route to first-party relinking, release, or status copy that explains what the user can safely do next

Forbidden recovery moves:

* collecting claim codes, auth secrets, or private case identifiers inside the widget
* presenting the widget as the recovery mechanism itself
* hiding the first-party fallback or recovery path behind the widget
* implying a fix is available for this user merely because code merged or a video exists
* turning a compatibility fallback, raw package, or manual route into the recommended path through concierge phrasing

## Surface classes

### Class P0 - Public trust surfaces

Allowed targets for concierge widgets:

* `/downloads`
* `/now`
* `/contact` or public support entry pages
* public guide or help entry pages
* public release pages
* artifact gallery and artifact detail pages
* creator landing pages
* campaign invite or join pages that do not expose private case, auth, or install truth

### Class P1 - Guided escalation surfaces

Allowed handoff destinations:

* first-party help articles or release pages
* Hub-owned support intake
* Deftform structured intake
* Lunacal booking pages
* approved artifact or media pages
* MetaSurvey post-flow usefulness capture

### Explicitly forbidden surfaces

No concierge widget on:

* desktop app surfaces
* mobile app surfaces
* authenticated campaign workspace
* signed-in home dashboard
* support case timelines
* crash or bug submission forms themselves
* account recovery forms that carry secrets
* install-linking or claim-code submission surfaces
* updater dialogs or install media
* admin or operator surfaces

## Tool roles

### FacePop

Primary role: public trust widget and branching concierge.

Allowed jobs:

* greet the visitor
* ask one or two routing questions
* branch to safe next actions
* collect lightweight opt-in lead, support, or testimonial data
* collect video or audio responses for moderated testimonial intake
* wrap a booking or intake call to action with human context

Must not:

* answer support questions as truth
* become support ticket truth
* become install or update truth
* become auth or account truth
* appear as the desktop or mobile support brain

### Lunacal

Primary role: human escalation and scheduling backend.

Allowed jobs:

* onboarding calls
* GM office hours
* creator consults
* migration or setup clinics
* premium or publisher review sessions

Must not:

* own support case truth
* own campaign or install truth
* be the only route to help

### Deftform

Primary role: structured intake backend.

Allowed jobs:

* install-help pre-intake
* campaign join or application forms
* creator submission intake
* support enrichment forms
* feature-interest or migration forms

Must not:

* become support case truth
* become account truth
* become the only submission path for crash or bug reporting

### vidBoard and sibling media tools

Primary role: polished explainer and companion artifact lane.

Pattern:

* FacePop = short human concierge layer
* vidBoard = polished long-form explainer or primer
* MarkupGo = detailed packet
* PeekShot = preview or share card
* Soundmadeseen = narrated companion fallback

## Canonical workflow families

### 1. Download and setup concierge

Entry:

* public `/downloads`

Flow:

1. FacePop host greets the visitor.
2. Visitor chooses one of:
   * Download now
   * Which platform should I pick?
   * I need setup help
3. `Download now` routes to first-party download truth.
4. `Which platform should I pick?` routes to a short vidBoard explainer or first-party support article.
5. `I need setup help` opens a Deftform support-enrichment form.
6. If the form signals a human-help case, route to Lunacal for a short setup clinic.
7. Hub records the pre-intake, booking receipt, and final support-case linkage.

### 2. Campaign invite concierge

Entry:

* invite landing page or campaign join page

Flow:

1. FacePop greets the invited player or GM.
2. Branches:
   * Watch campaign primer
   * Open primer packet
   * Book a session-zero or onboarding call
   * Submit a concept or questions form
3. vidBoard provides the primer video.
4. MarkupGo provides the detailed primer packet.
5. Lunacal handles session-zero booking.
6. Deftform handles structured concept or question intake.
7. Hub writes the real invite, campaign, and follow-up truth.

### 3. Creator consult and launch funnel

Entry:

* public creator or artifact page

Flow:

1. FacePop asks what the creator needs:
   * How publishing works
   * Book a consult
   * Submit interest or details
   * Watch a creator promo explainer
2. vidBoard provides the creator explainer.
3. Lunacal handles consult booking.
4. Deftform handles structured submission or intake.
5. MetaSurvey optionally captures usefulness after the flow.

### 4. Release concierge and fix confirmation

Entry:

* `/now`, public release pages, public help entry pages

Flow:

1. FacePop host summarizes the current release in one short greeting.
2. Branches:
   * Watch what changed
   * Read release notes
   * Need help updating?
3. vidBoard provides the localized release explainer.
4. MarkupGo and Documentation.AI provide the text siblings.
5. Setup or update difficulty routes to Deftform and, if needed, Lunacal.
6. Hub remains the owner of the case, release truth, and closure status.

### 5. Testimonial and proof shelf

Entry:

* after successful onboarding, support closure, campaign primer completion, or creator publication

Flow:

1. Chummer sends the user to a FacePop review-capture page.
2. FacePop captures video or audio response.
3. Hub receives webhook receipts and creates a moderated testimonial intake item.
4. ApproveThis or a Hub-owned moderation UI approves publication.
5. Media Factory renders safe derivatives if needed.
6. PeekShot builds preview cards; Registry stores publication references.

### 6. Runsite orientation funnel

Entry:

* runsite or location artifact page

Flow:

1. FacePop host asks whether the visitor wants:
   * quick orientation
   * route-first view
   * explorable tour
2. vidBoard provides a short host-led orientation clip.
3. AvoMap and Crezlo Tours provide route or explorable modes.
4. PeekShot provides teasers and preview cards.

## Data and receipt model

Concierge flows must produce Chummer-owned receipts such as:

* `concierge_flow_id`
* `concierge_entry_surface`
* `concierge_posture_label`
* `concierge_variant_id`
* `concierge_route_choice`
* `linked_help_article_ref`
* `linked_form_submission_ref`
* `linked_booking_ref`
* `linked_support_case_ref`
* `linked_testimonial_intake_ref`
* `provider_receipt`
* `locale`
* `captions_policy_state` when video is involved

## Approval and moderation

Any concierge flow that can publish or capture public assets must require:

* Chummer-owned approval state
* kill switch
* fallback first-party path
* fixed/fallback/preview/recovery copy review
* explicit moderation for public testimonial publication
* accessibility and locale review

## Integration posture

* `chummer6-hub` owns orchestration, intake routing, booking linkage, and publication shaping
* `chummer6-media-factory` owns render and preview adapters
* `chummer6-hub-registry` owns published references and reusable artifact metadata
* `chummer6-design` owns policy, classification, and rollout sequencing

## What success looks like

The user sees a calm, human, useful entrypoint.
The system still stores truth in Chummer-owned repos.
The widget can disappear tomorrow and the product still functions.
