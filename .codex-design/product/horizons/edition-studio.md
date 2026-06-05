# EDITION STUDIO

## The problem

One generic shell can technically support SR4, SR5, and SR6 while still making all three feel flattened.
That loses comprehension, atmosphere, and confidence exactly where the editions most need authored help.

## What it would do

EDITION STUDIO would give each promoted ruleset a deliberately authored head:

* distinct terminology, prompts, and inspector posture where semantics diverge
* ruleset-specific interaction patterns where a shared workflow becomes confusing or lossy
* visual language, motion, density, and emphasis that reflect each edition's mental model without fragmenting the product into separate apps

This horizon is not about skinning for its own sake.
It is about preserving meaning through authored product expression.

## Likely owners

* `chummer6-ui`
* `chummer6-ui-kit`
* `chummer6-core`

## Tool posture

AI design aids may support exploration, but canonical edition posture stays authored in the design system and product heads.
Rules truth remains downstream of core semantics, never of styling.

## What has to be true first

* edition-specific semantic seams in core and explain
* shared primitives that can host ruleset-specific composition without forked chaos
* theming, typography, and motion tokens with explicit ownership
* acceptance proof that the release shell already preserves the important edition differences

## Hard boundary

* not three disconnected apps
* not decorative theming without semantic payoff
* not ruleset flavor that contradicts engine truth

## What is ready now

EDITION STUDIO is now a shipped first-party ruleset-head lane.

The public rail exposes a named ruleset-head receipt plus SR4, SR5, and SR6 head packets:

* `/edition-studio`
* `/edition-studio/receipts/ruleset-heads.json`
* `/edition-studio/packets/sr4_head.md`
* `/edition-studio/packets/sr4_head.json`
* `/edition-studio/packets/sr5_head.md`
* `/edition-studio/packets/sr5_head.json`
* `/edition-studio/packets/sr6_head.md`
* `/edition-studio/packets/sr6_head.json`

The signed-in rail now has named edition-focus aliases:

* `/account/edition-studio`
* `/account/edition-studio/open`
* `/account/edition-studio/{edition}`

Typed edition-head APIs are first-class too:

* `/api/v1/campaign-spine/me/edition-studio/heads`
* `/api/v1/campaign-spine/me/edition-studio/heads/{edition}`

This shipped slice keeps authored SR4, SR5, and SR6 posture readable without turning styling into truth authority or splitting the product into disconnected apps.
