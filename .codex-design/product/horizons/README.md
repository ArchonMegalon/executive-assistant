# Horizon registry

This directory holds the human-readable horizon canon for Project Chummer.

Each file defines a bounded future lane, the table pain it targets, the likely owners, and the architectural reasons it is still parked.

Before adding or changing a horizon, read `../HORIZON_DESIGN_INSTRUCTIONS.md`. Horizon docs must keep the human reader first, show the table scene, name the trust boundary, and avoid leaking implementation shorthand into public output.

## Current canonical horizon set

* `nexus-pan.md` - matrix, device, and shared-state continuity
* `alice.md` - build quality and comparative analysis
* `quicksilver.md` - expert-speed shell control for dense build and audit flows
* `karma-forge.md` - governed house-rule and alternate-ruleset evolution
* `edition-studio.md` - edition-specific authored heads and expression posture
* `black-ledger.md` - persistent campaign-adjacent world-state and mission-market effects
* `community-hub.md` - governed open-run recruitment, scheduling, and closeout over a living world map
* `knowledge-fabric.md` - build-time knowledge projections and grounded explainability
* `onramp.md` - guided first-build and recovery path for new/skeptical users
* `jackpoint.md` - grounded dossier, recap, narrated briefing, and artifact-studio lane
* `run-control.md` - GM campaign control, prep, roster, scene, and recap operations
* `runsite.md` - bounded explorable location packs for GM run sites
* `runbook-press.md` - long-form primers, handbooks, campaign books, and creator publishing support
* `ghostwire.md` - replay, after-action review, and forensics lane
* `table-pulse.md` - bounded GM coaching and table-dynamics analysis
* `local-co-processor.md` - optional local acceleration without mandatory local runtime

Cross-horizon foundation truth lives in `FOUNDATIONS.md`.
Machine-readable order, owners, and dependency truth live in the root `HORIZON_REGISTRY.yaml`.
The local `horizons/HORIZON_REGISTRY.yaml` file is a derived guide-routing index and must stay narrower than the root registry and preserve the root order exactly.

## Canon rule

If a future capability is important enough to appear in roadmaps, public guides, or tool-promotion decisions, it needs a file here first.
