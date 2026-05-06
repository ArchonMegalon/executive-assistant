# Horizons

Horizons are the canonical registry for future-capability lanes in Project Chummer.

They exist so future product intent lives in `chummer6-design`, not only in downstream public storytelling.

For the writing, public-guide, and media standard, use `HORIZON_DESIGN_INSTRUCTIONS.md` before changing any horizon doc or generator.

## Rules

* Horizon docs are canon for future-capability posture, not promises of shipment.
* Horizon docs must stay consistent with `VISION.md`, `ARCHITECTURE.md`, `EXTERNAL_TOOLS_PLANE.md`, and `PROGRAM_MILESTONES.yaml`.
* The public `Chummer6` guide may explain Horizons in human language, but it may not outrun this directory.
* Public horizon output must satisfy `HORIZON_DESIGN_INSTRUCTIONS.md`: human value first, no repo-speak, no foundation-code checklists, no unsupported shipment claims, and no decorative AR that does not fit the scene.
* When a horizon already has first-party preview artifacts or detail routes in the public registry, downstream public surfaces should point at that proof instead of presenting the horizon as an empty teaser.
* Public votes, surveys, Discord chatter, and guide feedback are advisory inputs only.
* A horizon becomes implementation work only when the owning repos, bounded tool posture, milestone ties, and build path are explicit.
* Horizons that analyze human session behavior must define consent, privacy, and non-truth boundaries explicitly.

## Foundation rule

Horizons are allowed to widen the future only when the present-tense product lays strong enough foundations to support them later.

That means:

* future speed lanes must name the current latency, keyboard, bulk-edit, and dense-state seams they depend on
* future ruleset-expression lanes must name the current edition-specific UI and semantic seams they depend on
* future coaching or primer lanes must name the current explain, legality, sample-build, and recommendation seams they depend on
* future GM-control lanes must name the current campaign-state, device-role, roster, recap, and publication seams they depend on
* future continuity lanes must name the current offline, receipt, replay, and conflict-resolution seams they depend on

Cross-horizon foundation expectations live in `horizons/FOUNDATIONS.md`.
Machine-readable dependency truth lives in `HORIZON_REGISTRY.yaml`.
The subdirectory `horizons/HORIZON_REGISTRY.yaml` is a derived guide-routing index only; it must never widen horizon eligibility, order, or public-guide visibility beyond the root registry, and it must preserve root order exactly.

## Horizon families

Horizons should group into stable capability families rather than reading like an unstructured idea list.

Current families are:

* expert-speed and command surfaces
* ruleset-specific authored heads
* guided mastery and teaching
* GM operations and campaign control
* session continuity
* build and simulation
* governed rules evolution
* knowledge fabric and explainability
* campaign-world-state and mission market
* artifact studio
* creator press
* spatial exploration
* replay and forensics
* table coaching and social dynamics
* optional local acceleration
* community signal

## Canon layers

There are two canonical layers for Horizons:

1. `HORIZON_REGISTRY.yaml` — the machine-readable source of truth for horizon existence, order, public-guide eligibility, and eventual build path.
2. `horizons/*.md` — the human-readable long-form canon for each horizon lane.
3. `HORIZON_DESIGN_INSTRUCTIONS.md` — the design standard for horizon writing, public guide generation, and horizon media.

Downstream generators must consume the registry.
They must not carry a private hardcoded horizon catalog.
Public horizon detail export must also be able to read the long-form docs without guessing section names.
For every horizon that is public-guide eligible, the long-form canon should keep these headings explicit:

* `Table pain`
* `Bounded product move`
* `Likely owners`
* `Foundations`
* `Build path`
* `Owner handoff gate`
* `Why still a horizon`

Horizons that touch public media, community, replay, or coaching lanes should also keep their surface limits and proof posture explicit in canon, even when the exact values live in the registry:

* allowed surfaces
* proof gate
* public claim posture
* stop condition

## Operational contract

Horizons only stay trustworthy when the long-form docs, the root registry, the derived guide-routing index, and downstream public-guide exports all describe the same lane.

That means:

* the root `HORIZON_REGISTRY.yaml` is where existence, ordering, public-guide eligibility, build-path state, owner handoff gate, and any public-proof guardrails become machine-readable truth
* `horizons/*.md` must restate the table pain, bounded product move, foundations, build path, handoff gate, and horizon wait in stable headings instead of making downstream readers infer them from prose
* the derived `horizons/HORIZON_REGISTRY.yaml` may only project the root registry into guide-routing fields; it must not widen scope, reorder lanes, or invent its own public posture
* public-guide exports may retell the horizon in human language, but they must not skip the build-path and handoff limits that keep the lane honest
* if a horizon changes build-path state, owner handoff gate, public eligibility, or surface/proof guardrails, the same change must update the root registry, the long-form doc, and any affected public-guide routing metadata together

## Registry

Read `horizons/README.md` first, then the relevant lane docs:

* `horizons/quicksilver.md`
* `horizons/edition-studio.md`
* `horizons/onramp.md`
* `horizons/run-control.md`
* `horizons/nexus-pan.md`
* `horizons/alice.md`
* `horizons/karma-forge.md`
* `horizons/black-ledger.md`
* `horizons/community-hub.md`
* `horizons/knowledge-fabric.md`
* `horizons/jackpoint.md`
* `horizons/runsite.md`
* `horizons/runbook-press.md`
* `horizons/ghostwire.md`
* `horizons/table-pulse.md`
* `horizons/local-co-processor.md`

## Required fields for every horizon

Every horizon must define, either in its long-form doc or in `HORIZON_REGISTRY.yaml`:

* the table pain
* the bounded product move
* the likely owning repos
* the LTD/tool posture
* the dependency foundations
* the current horizon state
* the eventual build path
* the allowed surfaces when the lane can reach public, guided-preview, operator-review, or artifact outputs
* the proof gate when the lane depends on provenance, consent, replay, publication, or other non-negotiable truth rails
* the public claim posture that limits what downstream public surfaces are allowed to imply
* the stop condition that fail-closes public or guided-preview posture when the truth rail breaks
* why it is still a horizon

For public-guide-eligible horizons, the long-form doc should also be readable as a downstream export source:

* the `Table pain` section should restate the table problem in human language
* the `Bounded product move` section should name the first product-shaped move without reading like a shipment promise
* the `Build path` section should mirror the registry state transition (`current_state`, `next_state`, and intent) without widening it
* the `Owner handoff gate` section should restate the promotion boundary the owning repos must satisfy before the horizon leaves horizon status

The safest default is stronger than "either/or":

* keep the root registry authoritative for machine-readable values
* keep the long-form doc explicit enough that downstream public-guide generation, review, and proof reads can recover the same truth without guessing

## Working rule

Horizons are where Chummer names the future without letting the future silently widen the current release boundary.

They are also where Chummer records how a future lane could become bounded research and then real build work later, instead of existing only as public guide copy.
If a future lane matters enough to shape today's architecture, its required foundations must be visible now rather than rediscovered after the release surface hardens.
