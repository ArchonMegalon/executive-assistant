# ALICE

## Explanation video

[Watch the ALICE 90-second deep dive](https://chummer.run/media/horizons/alice-90s-deepdive.mp4). [Captions](https://chummer.run/media/horizons/alice-90s-deepdive.vtt).

## The problem

Players often discover bad builds, illegal interactions, or weak upgrade paths only after the run has already gone sideways.

## What it would do

Chummer would compare builds, catch trouble before play, and explain tradeoffs without making up rules or legality.

## What is live now

The shipped ALICE slice is now broader than the first compare bench:

* a public-safe ALICE route that explains the boundary and routes users into first-party compare work
* signed-in build handoffs that keep tradeoffs, progression outcomes, runtime compatibility, source hints, and apply or discard follow-through on one governed rail
* first-party compare artifacts such as compare briefs, what-if packets, and apply or discard receipts
* a desktop ALICE workbench with explicit modes for `Build help`, `Rules coach`, and `Origin Dossier`
* blank-state build help with a visible `Draft from scratch` affordance that can draft a full starting runner without requiring an already-open character
* rules-coach prompts that explain selectable build options without claiming rule authority beyond cited Chummer mechanics context
* GM allowance and requirement notes that can seed ALICE guidance with bounded exceptions or constraints such as extra ware, availability, nuyen, gear, qualities, required magical activity, illegal-addiction requirements, or minimum mental-attribute requirements without mutating build truth
* an origin-dossier lane that can generate a grounded origin draft from blank-state or active-runner context, freeze approved canon, and seed later ALICE suggestions from that canon
* origin-dossier bundle outputs that can branch into dossier PDF, portrait candidates, scene candidates, Subscribr narration and video-script packets, approved-story audiobook requests, local media-factory render requests, and optional First Book ai premium dossier-book packets
* voice-selection controls that let the player choose between at least a default and alternate narration posture before the audiobook packet is rendered
* player-scoped audiobook handoffs that let the desktop open the approved origin-story audio without receiving global Audiobookshelf credentials
* GM-steered origin context that can shape the dossier tone, faction hooks, and campaign constraints before or after sheet creation without pretending that story output is mechanical truth

This is still not an assistant-side build oracle.
The shipped lane is a Chummer-owned compare, coach, and origin-handoff surface with bounded public framing.

## Current desktop boundary

Desktop ALICE may:

* explain current build tradeoffs
* explain selectable options in plain language
* explain legality, complexity, and ware posture directly inside the desktop workbench before the user asks a free-form question
* draft a complete scratch runner from a blank or new-character state when the user chooses `Draft from scratch`
* use an approved origin draft or origin-dossier canon as suggestion context
* respect GM allowances and hard GM requirements as advisory context
* generate downstream dossier media packets
* hand approved origin canon to Subscribr for bounded narration and video-script drafting and to First Book ai for premium long-form packaging after separate approval
* let the player choose a narration posture before generating dossier audiobook packets
* open an EA-issued player/runner-scoped origin-story audiobook reference when the approved dossier has one
* keep origin-dossier generation additive for finished runners instead of treating story output as a forced rebuild lane
* accept campaign or GM steer as bounded context for origin-dossier generation

Desktop ALICE must not:

* silently rewrite the character sheet
* auto-apply GM allowances to mechanics
* invent rule legality
* treat dossier prose as canonical build truth
* treat Subscribr or First Book ai output as canonical build truth
* let a downstream media provider become rules or character authority
* hold an Audiobookshelf admin token, global library token, provider secret, or raw pCloud media path
* silently turn GM narrative steer into applied mechanics on an already-established sheet

## Likely owners

* `chummer6-core`
* `chummer6-ui`
* `chummer6-hub`

## Tool posture

Research and assistive drafting tools may support operator-facing explanations, but analysis outcomes stay grounded in engine-owned semantics.

## What has to be true first

* explain views that show their work
* deterministic runtime data
* strong comparison flows

## Current boundary

The live ALICE lane still does not mean Chummer can invent mechanics, override legality, or turn a public explainer into runtime truth.
The public entry, the signed-in compare bench, the desktop coach modes, the blank-state starter flow, the origin-dossier seed lane, the GM-allowance context rail, and the first-party receipts are live now; deeper simulation and autonomous build mutation can widen later only if engine-owned authority grows first.

## Naming and flow rules

User-facing naming should stay stable:

* `Build help`
* `Rules coach`
* `Origin Dossier`

Do not drift back into mixed labels like `origin draft packet`, `story packet`, or `narration kit`
on the primary desktop controls.

The intended flow is:

1. optional blank-state concept or active-runner context
2. optional GM steer, allowance notes, or hard narrative/mechanical requirements
3. origin draft
4. approve canon
5. choose voice posture for narration lanes when desired
6. request an approved-story audiobook when desired
7. render the origin dossier bundle
8. let later ALICE suggestions read that canon without mutating established build truth
