# GHOSTWIRE

## Table pain

We know something went wrong, but we cannot reconstruct what actually happened once the moment has passed.

## Bounded product move

Chummer would support replay, after-action review, and forensics packets built from receipts over time.
This lane is about what happened mechanically, what can be reconstructed safely, and how to compare or explain it after the fact without mutating canonical session truth.
It also gives premium recovery a memory: when something goes wrong, the product should be able to show what happened, what is still trustworthy, and what the next safe move is.

## Likely owners

* `chummer6-core`
* `chummer6-mobile`
* `chummer6-hub`
* `chummer6-media-factory`

## Key tool posture

* `PeekShot` - preview/share-safe replay surfaces
* `Soundmadeseen` - narrated after-action recap support
* `MarkupGo` - bounded report rendering
* `Mootion` - bounded replay/video experiments
* `Paperguide` - cited reconstruction helper

## Foundations

* append-only reducer-safe ledger truth
* explain provenance canon
* runtime bundle receipts
* media-side receipt capture for after-action outputs
* degraded-state receipts that survive crash, reconnect, and restore paths

## Build path

* intent: eventual product lane
* current state: horizon
* next state: bounded research

## Owner handoff gate

Replay must prove reducer-safe, receipt-backed reconstruction before it can leave horizon status.

## Why still a horizon

Replay is only safe when reconstruction is receipt-backed and reducer-safe.
Until Chummer can prove that after-action views stay grounded in canonical truth rather than retrospective invention, GHOSTWIRE remains a horizon instead of product truth.
