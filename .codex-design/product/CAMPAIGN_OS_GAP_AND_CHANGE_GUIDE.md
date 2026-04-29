# Chummer Campaign-OS gap and change guide

## Purpose

This is a remediation guide for the active post-foundation product wave.

It does not replace the machine-readable milestone registry in
`NEXT_12_BIGGEST_WINS_REGISTRY.yaml`.

Its job is to state the current product risk clearly:

* the repos now describe the SR campaign OS coherently
* the remaining risk is that the product does not yet feel inevitable, simple, and proven across the main lived journeys

## Current framing

The platform is no longer missing its architectural center.

It now has:

* deterministic engine truth
* a campaign and control middle plane
* account-aware installs and roaming workspace
* a governed support and control loop
* registry-owned install and update truth
* Fleet and EA operator infrastructure

The current product problem is not "missing architecture."

The current product problem is proving the campaign OS as a lived system across install, play, continuity, publication, and closure.

## Main gaps and risks

### 1. Journey proof is weaker than design proof

The repos verify canon breadth, generated guide output, milestone registries, and pulse artifacts, but the journey acceptance harness is not yet consistently wired to all primary campaigns flows:

* install -> claim -> restore -> continue
* build -> explain -> publish
* join campaign -> run session -> recover -> recap
* report issue -> cluster -> release fix -> notify reporter

### 2. Surface focus is still fragmented

Desktop and workbench still carry multiple heads and significant legacy cargo.
Core still carries large compatibility and historical surface area.
That slows flagship delivery and blurs the main product surface.

### 3. Hub is at risk of becoming the smart super-repo

Hub now owns accounts, groups, campaigns, control and support truth, public home and downloads, orchestration, and assistant adapters.
That remains workable only if bounded contexts stay explicit, independently testable, and governed by clear retention and projection rules.

### 4. Campaign OS is canonized but not yet embodied evenly

The campaign spine, living dossier, roaming workspace, device roles, and home cockpit are now central design truth.
The remaining risk is uneven embodiment across desktop, mobile, and hosted surfaces.
The specific lived-system bar is now explicit: downtime, aftermath, heat, faction posture, contact truth, reputation, and next-session return must read like one governed campaign-memory lane instead of recap prose plus local reminders.

### 5. Build and Explain still need flagship compression

Build Lab exists in canon and in the product story.
It still needs a clearer executable spine across core, UI, and hub so users feel it as one product surface rather than a named lane.

### 6. Portability and migration are strategically important but easy to under-ship

The design now makes dossier and campaign portability first-class.
If the user experience lands as advanced export cargo, or if rule environments and amend packages still feel like hidden custom-data cargo, Chummer will still feel like a tool instead of a campaign OS.

### 7. Creator, publication, and organizer layers can outrun trust

Creator publication, artifacts, community ledgers, group-owned rights, and operator surfaces are all powerful.
Without moderation, lineage, compatibility clarity, and public trust framing, they can create noise faster than value.

### 8. Model-route and media-adapter hygiene can silently rot

EA now exposes multiple model lanes and route health views, while Media Factory still depends on a narrow EA-backed media bridge for current image execution.
Without a formal stewardship loop, provider defaults, fallbacks, and media execution quality will drift.

### 9. Localization is now product-critical

The shipping locale set is defined, but campaign-OS value also lives in support, update, explain, rule-environment, and artifact surfaces.
Partial localization in those trust-critical seams will feel worse than a clearly scoped English-only preview.

### 10. Promotion and adoption proof are still early

The public guide and weekly pulse are real, but measured history is still shallow.
The product needs stronger evidence that users can install, claim, sync, recover, update, publish, and get closure successfully.

### 11. No-step-back parity can still be lost behind modernization language

It is now valid to modernize away from old window names, MDI posture, and one-form-per-job cargo.
It is not valid to quietly drop serious user jobs just because the new shell is cleaner.
The parity registry now closes the in-scope non-plugin feature families through proof-backed successor routes.
The remaining flagship risk is keeping installer/platform proof, localization proof, and lived-system journey proof from lagging that now-closed parity surface.

## Team change guide

## A. chummer6-design plus Product Governor

### Goal

Turn the design repo from canonical map into canonical map plus journey-based operating contract.

### Required changes

1. Add a Golden Journey Release Gate layer.
   Canonize six system journeys that every release wave must prove end to end.
   Tie them directly into `METRICS_AND_SLOS.yaml`, `PRODUCT_HEALTH_SCORECARD.yaml`, and Fleet publish readiness.

2. Expand middle-plane docs into executable acceptance specs.
   Prioritize `BUILD_LAB_PRODUCT_MODEL.md`, `PRODUCT_CONTROL_AND_GOVERNOR_LOOP.md`,
   `EXPERIENCE_SUCCESS_METRICS.md`, `RULE_ENVIRONMENT_AND_AMEND_SYSTEM.md`, and campaign workspace/device-role interaction states.

3. Add a privacy and retention canon.
   Cover support-case retention, crash-envelope retention, claim/install linkage retention,
   survey result retention, provider trace retention, and redaction rules per surface.

4. Define campaign-OS maturity explicitly.
   The maturity bar is not just repo completion; it is that a campaign can live here,
   survive here, and close the loop here.
   That includes first-class campaign-memory truth for downtime, aftermath, heat,
   faction posture, contact truth, reputation, and return-loop actions.
5. Keep no-step-back parity machine-readable.
   The legacy and adjacent client parity registry must stay aligned with the active flagship wave and blocker register so modernization cannot silently strand real user jobs.

### Exit criteria

* journey gates are canonical and verified
* the weekly pulse includes journey-health and user-outcome signals, not only repo and promise signals

## B. chummer6-core

### Goal

Make core unmistakably the truth engine and compatibility oracle, not a half-modernized app trunk.

### Required changes

1. Finish the legacy cargo burn-down plan.
2. Strengthen rule-environment, amend-package, and migration receipts.
3. Promote team- and campaign-facing explain APIs, including compatibility and environment-fit explanations.

### Exit criteria

* core reads like engine truth plus migration oracle
* no active product flow depends on legacy cargo semantics

## C. chummer6-ui

### Goal

Ship one flagship desktop and workbench experience that feels like the main door into the campaign OS.

### Required changes

1. Enforce the single flagship head rule.
   `Chummer.Avalonia` is the hero.
   `Chummer.Blazor.Desktop` is the bounded fallback.

2. Burn down UI-side legacy cargo.
3. Deliver home cockpit and campaign workspace as real top-level surfaces.
4. Surface one obvious rule-environment workbench with package preview, activation proof, and mismatch recovery instead of hidden custom-data state.
5. Make localization complete enough to trust across chrome, install/update/support, explain, rules/data names, and generated artifacts.
6. Close platform honesty gaps by either finishing macOS promotion/signing/notarization or keeping macOS explicitly gated.
7. Close the no-step-back parity families that still sit outside the promoted desktop shell, especially sourcebook/reference, utility/operator, settings/data-authoring, and export/viewer lanes.

### Exit criteria

* one obvious desktop experience
* one obvious first-launch, update, support, and campaign-cockpit flow

## D. chummer6-mobile

### Goal

Make mobile the table-safe half of the campaign OS, not just a session shell.

### Required changes

1. Add campaign workspace lite.
2. Implement claimed-device restore semantics in the mobile shell.
3. Add device-role-aware user experience.
4. Tie mobile directly into support and update truth.

### Exit criteria

* mobile feels like the table companion for the same living campaign, not a separate app universe

## E. chummer6-hub

### Goal

Keep Hub powerful without letting it become an unbounded super-repo.

### Required changes

1. Make bounded contexts explicit:
   Accounts and Community, Campaign Spine, Control and Support, Public Guide/Home/Downloads, and Orchestration/Assistant adapters.
2. Give each bounded context owned APIs, read models, retention rules, projections, and tests.
3. Finish the campaign workspace server plane.
4. Finish the support closure plane.
5. Add a privacy and redaction boundary for assistant, help, survey, and provider integrations.

### Exit criteria

* Hub remains the relationship, campaign, and control host without becoming a hidden semantics catch-all

## F. chummer6-hub-registry

### Goal

Make Registry the boring truth that every other surface can safely lean on.

### Required changes

1. Deepen release/install/update projections.
2. Add richer artifact and compatibility projections for dossier and campaign publication.
3. Support rule-environment and package compatibility lookups for import and restore flows.
4. Add public trust projections that can feed guide, help, home, and download surfaces without ad hoc joins.

### Exit criteria

* Registry is the one boring place that answers what is real for this install, channel, artifact, and package

## G. chummer6-media-factory

### Goal

Own media execution fully enough that creator and publication quality is not secretly tied to EA internals.

### Required changes

1. Remove the narrow dependency on EA's current image bridge as the long-term execution seam.
2. Own adapter evaluation, backend selection, and receipts inside Media Factory.
3. Add artifact and render provenance that public trust surfaces can expose.
4. Add failure-mode contracts for partial renders, stale previews, and revoked media artifacts.

### Exit criteria

* Media Factory is truly the render plant, not a thin wrapper over another runtime

## H. fleet

### Goal

Stop proving only compile readiness and start proving campaign-OS reality.

### Required changes

1. Add golden-path end-to-end orchestration for the four main journeys.
2. Make the new dashboard and cockpit the real operator surface.
3. Tie publish readiness to journey gates, support fallout, provider-route health, and public-guide freshness.
4. Keep Fleet publishing operator-friendly truth without becoming semantic owner truth.

### Exit criteria

* Fleet can answer "is the campaign OS safe to advance?" with journey evidence, not only repo status

## I. executive-assistant

### Goal

Keep EA as the synthesis and runtime substrate without letting it become hidden policy.

### Required changes

1. Formalize lane review cadence.
2. Separate easy, hard coder, groundwork, audit/jury, and support/help expectations explicitly.
3. Add governed grounding packs for public help, support assistant, and operator memos.
4. Keep all output connected back to canonical Hub, Design, and Fleet truth surfaces.

### Exit criteria

* EA makes the system sharper and cheaper, but never becomes a silent second canon

## J. Public Guide and promotion surface

### Goal

Make the outside story match the inside product.

### Required changes

1. Recut the public story around Build, Explain, Run, Publish, and Improve.
2. Make campaign-OS value visible as living dossier, campaign continuity, support closure, and grounded outputs.
3. Add clearer public trust content for what is supported, preview, gated, changed this week, and how fixes reach channels.
4. Stop letting the progress number carry too much meaning by itself.

### Exit criteria

* the public guide makes the product feel alive and trustworthy, not merely architecturally ambitious

## Priority order

### Phase 1 - make the product feel coherent

* UI flagship cut and cockpit
* Hub bounded contexts and campaign workspace APIs
* cross-repo journey gates
* localization completion on trust-critical surfaces
* Fleet journey orchestration

### Phase 2 - make the product feel indispensable

* rule-environment lifecycle and campaign compatibility
* Build Lab deepening
* mobile campaign-workspace lite
* portable dossier and campaign package UX
* support closure everywhere

### Phase 3 - widen the moat

* creator publication v2
* organizer and community operator surfaces
* Media Factory independence
* provider-route stewardship automation
* stronger public trust and launch story

## One-sentence instruction to every team

Stop optimizing for repo completion and optimize for the moment when a Shadowrun group can actually live inside Chummer for build, play, continuity, publication, and closure without feeling the seams.
