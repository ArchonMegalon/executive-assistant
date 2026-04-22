# External tools blocking policy rework

## Why a rework is needed

The external-tools plane was correctly strict, but one rule was too blunt for the stack Chummer now owns.

The previous Rule 5 forbade client-side vendor coupling in browser, mobile, or desktop repos. That protects Chummer from leaking vendor truth into product clients.

However, Chummer now owns bounded public-trust tools (`FacePop`) and bounded booking or intake tools (`Lunacal`, `Deftform`) that are useful precisely on public, low-risk, first-contact web surfaces. Treating those surfaces the same as authenticated workspaces, desktop clients, or support-truth views blocks legitimate high-trust experiences.

The policy should become narrower and smarter, not weaker.

## Keep these protections unchanged

Do not relax these boundaries:

* no vendor secrets in clients
* no vendor SDKs in desktop or mobile clients
* no vendor truth for support cases, install state, campaign truth, publication truth, rules truth, or session truth
* no live-surveillance or live-coaching exception for `TABLE PULSE`
* no chat or support widget as the phase-0 support system

## Replace current Rule 5 with this

### New Rule 5 - No client-side vendor coupling on authenticated or truth-bearing surfaces

No browser, mobile, or desktop repo may embed vendor credentials or rely on vendor SDKs on authenticated, truth-bearing, or runtime-critical surfaces.

This includes:

* signed-in home surfaces
* campaign workspace
* support case views
* install or update flows
* crash or bug feedback submission forms
* desktop or mobile runtime UX
* admin or operator surfaces

### New Rule 5a - Public concierge widget exception

A bounded external widget may appear on a Hub-owned public surface only when all of the following are true:

* the surface is public, low-risk, and not the owner of canonical truth
* the widget is optional and removable via kill switch
* the widget has a graceful first-party fallback path
* no vendor secret or private access token is exposed client-side
* the widget does not become the system of record for support, install, auth, publication, or campaign truth
* every meaningful submission or branch result is mirrored back into Chummer-owned receipts or first-party destinations
* accessibility and locale review are completed

## Add a new classification subclass

### Class C1 - Public trust / concierge widgets

These are humanized public-surface widgets used to guide a visitor into a first-party path.

Allowed examples:

* FacePop greeting on `/downloads`
* FacePop release concierge on `/now`
* FacePop booking wrapper for a Lunacal clinic
* FacePop testimonial capture page for later moderation

Forbidden examples:

* FacePop inside the desktop app
* FacePop inside signed-in campaign workspace
* FacePop as support case truth
* FacePop AI chat answering product issues as authoritative truth

## Rework current Rule 9 into two parts

### Rule 9 - Support assistant is not phase 0

The first support plane must still work without a chat assistant or support widget.
Crash reporting, structured bug reporting, lightweight feedback, and support intake remain first-class Chummer-owned flows.

### Rule 9a - Concierge widgets may route to support; they may not replace support

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

## Allowed and forbidden surface matrix

### Allowed

* public landing pages
* `/downloads`
* `/now`
* public help entry pages
* public artifact and creator pages
* public or tokenized invite pages with no sensitive truth shown

### Forbidden

* desktop app
* mobile app
* signed-in home
* authenticated campaign workspace
* updater dialogs
* claim-code entry forms
* case timeline and support-thread views
* admin, governor, or operator surfaces

## Data minimization rules

Public concierge widgets may collect only what the specific branch requires.

Preferred order:

1. no data capture
2. lightweight route choice only
3. email or name plus intent
4. richer intake only through a Chummer-controlled Deftform or Hub flow

Never collect through a concierge widget when the same step requires:

* account secrets
* claim codes
* install secrets
* payment truth
* moderation decisions
* private case details

## Embedding rules

Preferred order:

1. linked first-party page
2. iframe or embed with allowlist and kill switch
3. direct script or widget only when the first two are not viable

Any embedded or scripted widget must have:

* CSP allowlist entry or isolated embedding route
* route-level feature flag
* locale fallback
* disabled-state fallback content
* receipt correlation id on downstream submissions when possible

## Tool-specific posture

### FacePop

Posture: bounded Class C1 public trust or concierge widget

Allowed:

* public greetings
* branching route selection
* testimonial capture
* booking wrapper to Lunacal
* redirect or embed to first-party help or Deftform

Blocked:

* desktop or mobile embedding
* signed-in campaign workspace use
* support truth ownership
* install or auth truth ownership
* AI support truth role

### Lunacal

Posture: promoted human booking backend

Allowed:

* onboarding clinics
* setup calls
* creator consults
* GM office hours

Blocked:

* support truth ownership
* hidden mandatory gate before first-party help

### Deftform

Posture: promoted structured intake backend

Allowed:

* support pre-intake
* campaign invite forms
* creator consult intake
* artifact submission interest forms

Blocked:

* canonical support-case truth
* claim-code truth
* crash or bug path replacement

## Required implementation controls

Every public concierge widget integration must have:

* Hub-owned wrapper component or route-level embed policy
* kill switch
* first-party fallback link set
* event logging to Chummer-owned telemetry
* privacy notice when data capture occurs
* moderation path for testimonials or user-submitted media
* explicit owner in `projects/hub.md` and `EXTERNAL_TOOLS_PLANE.md`

## Result

This rework keeps the original safety goal, but stops blocking legitimate wow-factor and humanized guidance on public Chummer surfaces.
