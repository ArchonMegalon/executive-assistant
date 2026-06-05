# QUICKSILVER

## What is ready now

QUICKSILVER now ships a bounded first-party command deck.

The public command route, receipt route, packet rails, signed-in bench, and typed jump-target APIs are real.

## The problem

Chummer can become powerful without ever feeling elite.
If expert users still wait on screens, fight click friction, or lose flow during dense edits, the product remains capable but not flagship-fast.

## What it does now

QUICKSILVER turns the workbench into a named expert-speed surface:

* command-surface and shortcut-first flows for common build and inspect tasks
* near-instant search, compare, and jump behavior
* batch-safe edit patterns for repetitive mechanical work
* split and pinned inspection surfaces that preserve context under pressure

It is not a different rules engine.
It is the speed and command lane for the same trusted product truth.

## Live routes

* `/quicksilver`
* `/quicksilver/receipts/command-network.json`
* `/quicksilver/packets/command_deck.md`
* `/quicksilver/packets/command_deck.json`
* `/quicksilver/packets/jump_targets.md`
* `/quicksilver/packets/jump_targets.json`
* `/account/quicksilver`
* `/account/quicksilver/open`
* `/account/quicksilver/{focus}`
* `/api/v1/campaign-spine/me/quicksilver/command-deck`
* `/api/v1/campaign-spine/me/quicksilver/jump-targets`

## Likely owners

* `chummer6-ui`
* `chummer6-ui-kit`
* `chummer6-core`

## Tool posture

No external tool is required for the canonical core of this horizon.
Instrumentation or profiling helpers may support tuning, but the product-facing speed model remains owned by the app itself.

## What has to be true first

* explicit interaction latency budgets
* dense-state virtualization
* keyboard and command seams in the workbench shell
* batch-safe editing, undo, and cancel-safe transactions
* ruleset-specific composition seams so speed features do not flatten meaning

## Hard boundary

* not a command surface that hides legality or explainability
* not speed theater built from unsafe caching or stale state
* not keyboard-only elitism that breaks the primary guided path
