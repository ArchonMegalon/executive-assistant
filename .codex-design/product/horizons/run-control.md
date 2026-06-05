# RUN CONTROL

## The problem

Even with strong character tools, many GMs still need notebooks, chats, spreadsheets, memory, and ad hoc recaps to actually prep and run a campaign.
That means Chummer is adjacent to table control rather than indispensable for it.

## What it would do

RUN CONTROL would make Chummer a true GM operations surface:

* session prep, roster, agenda, scene, and recap state in one bounded workspace
* role-aware views for GM, player, and shared table posture
* live control surfaces that stay trustworthy during reconnects, device swaps, and partial offline play
* recap, dossier, and publication handoff that flows directly out of the campaign truth

This is the GM-control horizon, not a replacement for the rules engine or a generic collaboration suite.

## Likely owners

* `chummer6-hub`
* `chummer6-mobile`
* `chummer6-core`
* `chummer6-media-factory`

## Tool posture

Bounded summary and recap tooling may help with derivative outputs, but canonical control state stays in the campaign, roster, and session truth owned by Chummer.

## What has to be true first

* durable campaign and runner state
* device-role and entitlement posture
* reconnect-safe live continuity
* recap and dossier pipelines with receipts
* publication seams that can carry campaign outputs without losing provenance

## Hard boundary

* not a generic team-collaboration platform
* not hidden state that bypasses canonical campaign truth
* not a flashy control room built on unreliable session continuity

## What is ready now

RUN CONTROL is now a shipped first-party GM operations lane.

The public rail exposes a named control receipt plus public-safe session-board and continuity packets:

* `/run-control`
* `/run-control/receipts/control-network.json`
* `/run-control/packets/session_board.md`
* `/run-control/packets/session_board.json`
* `/run-control/packets/continuity_board.md`
* `/run-control/packets/continuity_board.json`

The signed-in rail is no longer implied through generic work routes alone; it now has named control aliases:

* `/account/run-control`
* `/account/run-control/open`
* `/account/run-control/{runId}`

Typed GM-control APIs are first-class too:

* `/api/v1/campaign-spine/me/run-control/dashboard`
* `/api/v1/campaign-spine/me/run-control/runs/{runId}`

This shipped slice keeps session board, active-scene continuity, reconnect-safe follow-through, and recap return attached to the same first-party campaign spine.
