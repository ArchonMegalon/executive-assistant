# Horizons

Horizons are the canonical registry for future-capability lanes in Project Chummer.

They exist so future product intent lives in `chummer6-design`, not only in downstream public storytelling.

## Rules

* Horizon docs are canon for future-capability posture, not promises of shipment.
* Horizon docs must stay consistent with `VISION.md`, `ARCHITECTURE.md`, `EXTERNAL_TOOLS_PLANE.md`, and `PROGRAM_MILESTONES.yaml`.
* The public `Chummer6` guide may explain Horizons in human language, but it may not outrun this directory.
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
Machine-readable dependency truth lives in `horizons/HORIZON_REGISTRY.yaml`.

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

Downstream generators must consume the registry.
They must not carry a private hardcoded horizon catalog.

## Registry

Read `horizons/README.md` first, then the relevant lane docs:

* `horizons/quicksilver.md`
* `horizons/edition-studio.md`
* `horizons/onramp.md`
* `horizons/run-control.md`
* `horizons/nexus-pan.md`
* `horizons/alice.md`
* `horizons/karma-forge.md`
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
* why it is still a horizon

## Working rule

Horizons are where Chummer names the future without letting the future silently widen the current release boundary.

They are also where Chummer records how a future lane could become bounded research and then real build work later, instead of existing only as public guide copy.
If a future lane matters enough to shape today's architecture, its required foundations must be visible now rather than rediscovered after the release surface hardens.
