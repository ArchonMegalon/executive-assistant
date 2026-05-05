# NEXUS-PAN

## Table pain

When phones, tablets, or laptops drift apart during play, the whole table stops trusting what is on screen.

## Bounded product move

Chummer would keep reconnects and shared session state steady enough that players can jump back in without the GM rebuilding context by hand.
It would build on the existing session record instead of creating a separate version of events.
It would also handle bad signals and device handoffs honestly: clear offline status, safe local continuity, and visible conflict recovery when reconnecting goes wrong.

## Likely owners

* `chummer6-core`
* `chummer6-mobile`
* `chummer6-hub`

## Tool posture

No external tool is required for the canonical core of this horizon.
If bounded helper lanes appear later, they remain downstream only.

* `Emailit` - reconnect, relink, or continuity notices after Hub decides they should exist
* `Documentation.AI` - recovery, relink, and continuity help projection from approved source truth
* `PeekShot` - share-safe continuity receipts and reconnect proof cards
* `BrowserAct` - operator capture and repro support for broken reconnect or device-handoff flows

None of those tools may own session state, reconnect authority, or conflict resolution truth.

## Foundations

* durable session state
* reliable sync bundles
* visible reconnect explanations
* in-session reliability
* offline-capable local state
* explicit stale, pending, and conflicted state

## Build path

* intent: eventual product lane
* current state: horizon
* next state: bounded research

## Owner handoff gate

Session continuity proof must exist across core, mobile, and hub without second semantic families.

## Why still a horizon

The live release still needs boringly reliable session continuity.
Until reconnects and shared-state handoffs stay solid under stress, a richer PAN layer would add confusion instead of removing it.
