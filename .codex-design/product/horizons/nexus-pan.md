# NEXUS-PAN

## Table pain

When phones, tablets, or laptops drift apart during play, the whole table stops trusting what is on screen.

## Bounded product move

Chummer would keep reconnects and shared session state steady enough that players can jump back in without the GM rebuilding context by hand.
It would extend the core rules and session record instead of inventing a second source of truth.

## Likely owners

* `chummer6-core`
* `chummer6-mobile`
* `chummer6-hub`

## Tool posture

No external tool is required for the canonical core of this horizon.
If projections or operator aids appear later, they remain downstream helpers only.

## Foundations

* durable session state
* reliable sync bundles
* visible reconnect explanations
* play-shell reliability

## Why still a horizon

The live release still needs boringly reliable session continuity.
Until reconnects and shared-state handoffs stay solid under stress, a richer PAN layer would add confusion instead of removing it.
