# Live Session Turn Companion

## Purpose

This file defines the playtime-only mobile/PWA use case for Chummer.

It is not a mini workbench.
It is not a full character builder.
It is the table-side turn companion that helps a player or GM resolve the next useful action quickly without losing trust when the network, attention span, or room gets messy.

## Core rule

The live-session turn companion exists to make one active turn easier to resolve.

At minimum it should answer:

* what state am I in right now
* what can I still do
* what modifiers are active
* what happens if I spend this now
* what changed after I committed the action

If a proposed mobile surface does not improve one of those answers during play, it is probably workbench scope instead.

## Primary users

### Player

The primary user is a player holding a phone during an active session with 5 to 15 seconds of attention.

### GM

The secondary user is a GM who needs a bounded, live-play-safe glance surface rather than a full prep or admin bench.

### Observer

The observer lane remains read-mostly and must not silently inherit player or GM authority.

## Product position

The turn companion is:

* one-handed
* phone-first
* local-first
* replay-safe
* explicit about stale or queued state

The turn companion is not:

* a full character authoring environment
* a shopping or stash-management surface
* a publication or moderation surface
* a VTT replacement
* a hidden second campaign authority

## Interaction budget

Every common action should be designed for short, interrupted use.

The target interaction shape is:

1. open the shell
2. see current state immediately
3. choose one action
4. review modifiers and quick odds
5. roll digitally or enter a physical result
6. commit the delta
7. put the phone away

If the user has to navigate a dense tree, open a generic inspector, or re-learn where the combat state lives, the surface has failed its job.

## Core surface set

### 1. Now

The first surface is a current-state HUD:

* physical and stun condition
* Edge and other spend-now currencies
* initiative or turn context
* current weapon or active action context
* ammo, charges, and key consumables
* active effects and temporary penalties
* sync, stale, or queued state

### 2. Act

The second surface is the next-action rail:

* attack
* defend
* soak
* reload
* use consumable
* cast, sustain, or drop a sustained effect
* apply or clear a condition

This rail should prioritize the top repeated table actions instead of acting like a general-purpose menu.

### 3. Adjust

The third surface is a bounded modifier stack:

* wound penalties
* recoil
* cover
* visibility
* temporary buffs or debuffs
* sustained effects
* situational toggles

The surface must show source-backed labels and not collapse into a hidden modifier editor.

### 4. Resolve

The fourth surface is the resolution step:

* show the current dice pool or equivalent action math
* show a quick explain path for where the value came from
* show fast odds such as chance of at least N hits or glitch risk
* allow digital roll
* allow manual roll entry for physical dice use
* apply the resulting state change

Manual entry is a first-class path, not a shameful fallback.

### 5. History

The fifth surface is a short action and delta history:

* last committed actions
* resource changes
* queued sync events
* undo-safe recent actions

This surface exists because table mistakes are normal and a trusted mobile companion must be auditable.

## In-scope state

The turn companion may track:

* current combat condition and damage state
* action-budget and turn-context state
* equipped weapon posture
* ammo and reload state
* active modifiers and timed effects
* Edge-like spend-now resources
* key consumables and mission-critical carried items
* player-safe continuity and return cues

Inventory here means the subset that matters on the current turn.
It does not mean full stash archaeology.

## Out of scope

The turn companion must not expand into:

* full character creation
* broad advancement and shopping flows
* deep inventory organization
* publication and moderation ownership
* full tactical-map or token-movement authority
* hidden GM-only state on player surfaces

Completion returns upward to the workbench, campaign workspace, or Hub-owned surfaces.

## Trust contract

The turn companion must make trust visible.

That means:

* local, synced, stale, and queued states are obvious
* users can see what changed after an action
* users can tell whether a result is grounded or deferred
* replay and reconnect do not silently rewrite the turn

Offline support without explicit trust-state posture is not good enough.

## RUNSITE and spatial context

RUNSITE may enrich the turn companion only as bounded orientation truth.

Allowed:

* named room, zone, or hotspot anchors
* adjacency and route cues
* ingress or fallback context
* scene orientation before and during play

Not allowed:

* exact tactical-token authority
* hidden live enemy state
* line-of-sight or cover truth that outranks core play state
* replacing VTT movement or map ownership

The clean contract is:

* RUNSITE defines inspectable spatial anchors
* the play shell may bind an actor to a selected anchor
* tactical truth still belongs to the live play lane, not the tour itself

## Repo ownership

### `chummer6-core`

Owns:

* rules math and conditional effect truth
* action-budget and turn-state rules
* probability and explain packet seams

### `chummer6-mobile`

Owns:

* the live-session turn companion shell
* local-first action logging and replay-safe state
* mobile interaction design for short table use
* bounded RUNSITE-anchor consumption on the shell side

### `chummer6-hub`

Owns:

* shared continuity
* signed-in campaign and session truth
* server-side orchestration and approval boundaries

### `chummer6-ui`

Owns:

* the heavy build and workbench surfaces before or after the session

## Success test

The turn companion is successful when a player can finish a live turn faster and with less argument than they could with a dense sheet, a PDF, or a half-remembered modifier stack.

If the product cannot make the next live turn clearer, faster, and more trustworthy, it has not earned the phone surface.
