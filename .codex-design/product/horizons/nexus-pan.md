# NEXUS-PAN

## Explanation videos

* [Watch the NEXUS-PAN 90-second deep dive](https://chummer.run/media/horizons/nexus-pan-90s-deepdive.mp4) - MP4 with AAC audio. [Captions](https://chummer.run/media/horizons/nexus-pan-90s-deepdive.vtt).
* [Watch the NEXUS-PAN epic reel](https://chummer.run/media/horizons/nexus-pan-epic-90s.mp4) - MP4 with AAC audio. [Captions](https://chummer.run/media/horizons/nexus-pan-epic-90s.vtt).

## The problem

When phones, tablets, or laptops drift apart during play, the whole table stops trusting what is on screen.

## What it does now

Chummer keeps reconnects and shared session state steady enough that players can jump back in without the GM rebuilding context by hand.
It builds on the existing session record instead of creating a separate version of events.
It also handles bad signals and device handoffs honestly: clear offline status, safe local continuity, and visible conflict recovery when reconnecting goes wrong.

## Likely owners

* `chummer6-core`
* `chummer6-mobile`
* `chummer6-hub`

## Tool posture

No external tool is required for the canonical core of this horizon.
If projections or operator aids appear later, they remain downstream helpers only.

## What has to be true first

* durable session state
* reliable sync bundles
* visible reconnect explanations
* in-session reliability
* offline-capable local state
* explicit stale, pending, and conflicted state

## Current shipped posture

NEXUS-PAN is shipped as the first-party continuity lane for reconnects, shared state, and device handoff recovery.

## Current boundary

This lane only stays shipped-grade while session continuity remains boringly reliable under stress.
Richer PAN behaviors can grow from that base, but they cannot outrun continuity, offline honesty, or visible conflict recovery.
