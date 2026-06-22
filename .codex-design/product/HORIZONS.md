# Horizons

Horizons are the canonical registry for campaign-adjacent expansion bets and deeper design lanes in Project Chummer.

They exist so public storytelling, deeper guide pages, and future product intent stay tied to `chummer6-design` instead of becoming a separate marketing shelf.

For the writing, public-guide, and media standard, use `HORIZON_DESIGN_INSTRUCTIONS.md` before changing any horizon doc or generator.

## Rules

* Horizon docs are canon for lane posture, not promises of shipment.
* Mature base-client areas belong in `PUBLIC_FEATURE_REGISTRY.yaml` and `features/*.md`, not in the Horizon registry.
* Horizon docs must stay consistent with `VISION.md`, `ARCHITECTURE.md`, `EXTERNAL_TOOLS_PLANE.md`, and `PROGRAM_MILESTONES.yaml`.
* The public `Chummer6` guide may explain Horizons in human language, but it may not outrun this directory.
* Public horizon output must satisfy `HORIZON_DESIGN_INSTRUCTIONS.md`: human value first, no repo-speak, no foundation-code checklists, no unsupported shipment claims, and no decorative AR that does not fit the scene.
* When a horizon already has first-party preview artifacts or detail routes in the public registry, downstream public surfaces should point at that proof instead of presenting the horizon as an empty teaser.
* Public votes, surveys, Discord chatter, and guide feedback are advisory inputs only.
* A lane becomes implementation work only when the owning repos, bounded tool posture, milestone ties, and build path are explicit.
* Horizons that analyze human session behavior must define consent, privacy, and non-truth boundaries explicitly.

## Foundation rule

Horizons are allowed to widen the future only when the present-tense product lays strong enough foundations to support them later.

That means:

* future speed lanes must name the current latency, keyboard, bulk-edit, and dense-state seams they depend on
* future ruleset-expression lanes must name the current edition-specific UI and semantic seams they depend on
* future coaching lanes must name the current explain, legality, sample-build, and recommendation seams they depend on; first-run help itself belongs in `ONRAMP_STARTER_LANE.md`, not in Horizons
* future GM-control lanes must name the current campaign-state, device-role, roster, recap, and publication seams they depend on
* future continuity lanes must name the current offline, receipt, replay, and conflict-resolution seams they depend on

Cross-horizon foundation expectations live in `horizons/FOUNDATIONS.md`.
Machine-readable dependency truth lives in `HORIZON_REGISTRY.yaml`.
The subdirectory `horizons/HORIZON_REGISTRY.yaml` is a derived guide-routing index only; it must never widen horizon eligibility, order, or public-guide visibility beyond the root registry, and it must preserve root order exactly.

## Horizon families

Horizons should group into stable capability families rather than reading like an unstructured idea list. Public guide output should keep them separate from normal product features.

Current families are:

* guided mastery and teaching
* build and simulation
* governed rules evolution
* knowledge fabric and explainability
* campaign-world-state and mission market
* artifact studio
* creator press
* spatial exploration
* replay and forensics
* table coaching and social dynamics
* community signal

## Canon layers

There are two canonical layers for Horizons:

1. `HORIZON_REGISTRY.yaml` — the machine-readable source of truth for horizon existence, order, public-guide eligibility, and eventual build path.
2. `horizons/*.md` — the human-readable long-form canon for each horizon lane.
3. `HORIZON_DESIGN_INSTRUCTIONS.md` — the design standard for horizon writing, public guide generation, and horizon media.

Downstream generators must consume the registry.
They must not carry a private hardcoded horizon catalog.

## Registry

Read `horizons/README.md` first, then the relevant lane docs. Base product features such as NEXUS-PAN, Run Control, Edition Studio, Community Hub, Ghostwire, Local Co-Processor, and Quicksilver live under `features/*.md`.

* `horizons/alice.md`
* `horizons/karma-forge.md`
* `horizons/black-ledger.md`
* `horizons/knowledge-fabric.md`
* `horizons/jackpoint.md`
* `horizons/runsite.md`
* `horizons/runbook-press.md`
* `horizons/table-pulse.md`

## Required fields for every horizon

Every horizon must define, either in its long-form doc or in `HORIZON_REGISTRY.yaml`:

* the table pain
* the bounded product move
* the likely owning repos
* the LTD/tool posture
* the dependency foundations
* the current horizon state
* why it is still a horizon

## Working rule

Horizons are where Chummer names the future without letting the future silently widen the current release boundary.

They are also where Chummer records how a future lane could become bounded research and then real build work later, instead of existing only as public guide copy.
If a future lane matters enough to shape today's architecture, its required foundations must be visible now rather than rediscovered after the release surface hardens.
