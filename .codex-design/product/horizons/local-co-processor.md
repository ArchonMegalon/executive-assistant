# LOCAL CO-PROCESSOR

## What is ready now

LOCAL CO-PROCESSOR now ships a bounded first-party optional-acceleration lane.

The public capability route, policy receipt, packet rails, signed-in profile desk, and typed capability/policy APIs are real.

## The problem

Some explain, search, and media-assist workloads would be cheaper, faster, or more private with optional local acceleration, but the product cannot require every user to run local compute.

## What it does now

Chummer allows optional local acceleration or lightweight host strategies where they improve responsiveness, privacy, or cost.
The same workflows still function in hosted-only mode, and no canonical truth depends on local runtime availability.

It currently ships:

* a public route at `/local-co-processor`
* a named receipt at `/local-co-processor/receipts/optional-acceleration.json`
* packet rails for capability and policy posture
* a signed-in profile desk at `/account/local-co-processor`
* typed capability and policy APIs

The lane is hosted-first.
Optional local acceleration is a bounded profile choice, not a hidden dependency or a second product.

## Live routes

* `/local-co-processor`
* `/local-co-processor/receipts/optional-acceleration.json`
* `/local-co-processor/packets/capability_matrix.md`
* `/local-co-processor/packets/capability_matrix.json`
* `/local-co-processor/packets/policy_boundary.md`
* `/local-co-processor/packets/policy_boundary.json`
* `/account/local-co-processor`
* `/account/local-co-processor/open`
* `/account/local-co-processor/{profile}`
* `/api/v1/campaign-spine/me/local-co-processor/capabilities`
* `/api/v1/campaign-spine/me/local-co-processor/policy`

## Likely owners

* `chummer6-hub`
* `chummer6-core`
* `chummer6-ui`
* `chummer6-mobile`

## Key tool posture

* no mandatory external tool
* optional bounded use of `1min.AI`, `AI Magicx`, or similar helpers where local orchestration benefits from acceleration evidence

## What has to be true first

* portable deterministic engine host strategy
* hosted-first parity
* explicit non-mandatory local runtime policy
* disableable local acceleration paths

## Hard boundary

* not a hidden local-runtime requirement
* not a local truth owner
* not a provider-dependent black box
* not a product split where hosted users lose capability
