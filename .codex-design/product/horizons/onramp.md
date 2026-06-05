# ONRAMP

## The problem

New, rusty, or skeptical users can hit a wall of jargon and legality before they experience why Chummer is valuable.
If the path to competence is too steep, the product leaves power on the table even when the engine is correct.

## What it would do

ONRAMP would create a guided-mastery layer for Chummer:

* coached starter builds and edition-aware primers
* "why this next?" guidance grounded in actual rules and build state
* recovery suggestions when a build becomes illegal, weak, or contradictory
* progressive disclosure that teaches the mental model instead of only hiding complexity

It is a learning and confidence horizon, not an auto-build black box.

## Likely owners

* `chummer6-ui`
* `chummer6-core`
* `chummer6-hub`

## Tool posture

Assistive drafting tools may help with primer copy or example narration, but recommendations and legality guidance must stay grounded in deterministic engine truth and approved examples.

## What has to be true first

* explain receipts that ordinary users can follow
* starter-lane shells and sample builds
* bounded recommendation seams instead of implicit UI folklore
* reliable legality and conflict detection
* metrics that prove the primary build path is already stable

## Hard boundary

* not hidden automation that chooses for the user without explanation
* not advice that outruns canonical rules truth
* not tutorial theater that collapses under non-happy-path builds

## What is ready now

ONRAMP is now a shipped first-party starter and recovery lane.

The public rail exposes a named starter receipt plus public-safe starter and recovery packets:

* `/onramp`
* `/onramp/receipts/guided-starter.json`
* `/onramp/packets/starter_lane.md`
* `/onramp/packets/starter_lane.json`
* `/onramp/packets/recovery_lane.md`
* `/onramp/packets/recovery_lane.json`

The signed-in rail now has named starter aliases instead of relying on generic setup surfaces alone:

* `/account/onramp`
* `/account/onramp/open`
* `/account/onramp/starter`

Typed starter and recovery APIs are first-class too:

* `/api/v1/campaign-spine/me/onramp/dashboard`
* `/api/v1/campaign-spine/me/onramp/starter`
* `/api/v1/campaign-spine/me/onramp/recovery`

This shipped slice keeps guided starter workspace, first playable follow-through, and restore posture attached to the same first-party campaign spine without turning ONRAMP into an auto-build black box.
