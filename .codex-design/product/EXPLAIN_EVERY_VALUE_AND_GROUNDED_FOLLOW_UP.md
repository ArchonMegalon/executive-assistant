# Explain every value and grounded follow-up

## Purpose

This file turns "why is this number what it is?" from a useful feature into a flagship trust contract.

It absorbs the ambitious explain-every-value direction into Chummer's existing truth stack:

- `BUILD_LAB_PRODUCT_MODEL.md`
- `BUILD_EXPLAIN_ARTIFACT_TRUTH_POLICY.md`
- `SOURCE_AWARE_EXPLAIN_PUBLIC_TRUST_HOOK.md`
- `SOURCE_ANCHOR_AND_LOCAL_RULEBOOK_BINDING.md`
- `COMPANION_PERSONA_AND_INTERACTION_MODEL.md`
- `COMPANION_PACKET.md`
- `FLAGSHIP_RELEASE_ACCEPTANCE.yaml`

The goal is not a prettier tooltip.
The goal is that every important visible mechanical result can defend itself under pressure.

## Product promise

On promoted build, compare, import, and live-play routes, Chummer should let a user ask four concrete questions without leaving first-party truth:

1. Why is this value what it is?
2. Why did this modifier apply or not apply?
3. What changed between the before and after state?
4. What would happen if I remove, add, or toggle this bounded factor?

That promise applies to:

- computed values
- legality or validation results
- caps, floors, rounding, and override outcomes
- visible warnings and blocked states
- important before/after deltas
- import and migration outcomes where a user is expected to trust the result

Optional narration, voice, or presenter layers may make that answer friendlier.
They may not become the source of the answer.

## Truth order

Explain-every-value must follow this truth order:

1. engine-owned explanation packet
2. rule-environment identity and snapshot identity
3. source anchors, validation receipts, and import or support receipts where relevant
4. deterministic first-party renderer
5. optional companion wording or presenter compile
6. optional external speech, avatar, or video provider

If those layers disagree, the higher layer wins.
Provider output is always the lowest layer in the stack.

## Scope and non-goals

### In scope

- attributes, derived values, limits, condition tracks, and initiative state
- skill, quality, gear, cyberware, bioware, spell, adept-power, and effect-driven modifiers
- karma, nuyen, essence, capacity, availability, and rating-dependent cost outputs
- rule-environment, amend-package, and custom-data effects that materially change outcomes
- compare deltas, trap-choice warnings, and "why this variant" answers
- live-play values such as action-economy, active effects, and bounded state changes where the user is asked to trust the math
- import, migration, and bounded-loss outcomes when the product claims a result or asks for manual review

### Not in scope

- screenshot-driven arithmetic guesses
- freeform rules chat with no current packet or source anchor
- hidden AI legality decisions
- cloud rulebook upload
- mandatory voice mode
- invisible microphone capture
- provider-specific product truth

## Explain packet contract

Every promoted explain surface must consume a first-party `ExplanationPacket`.

Recommended minimum shape:

```yaml
ExplanationPacket:
  packet_id: opaque stable id
  value_ref: stable value identifier
  display_surface: where the user clicked or focused
  snapshot_ref: current character or live-state fingerprint
  rule_environment_ref: active ruleset, preset, source-pack, and amend-package fingerprint
  final_value: rendered result or bounded status
  unit: optional display unit
  arithmetic_verified: true|false
  steps: ordered arithmetic or decision steps
  modifiers_applied: named applied factors
  modifiers_skipped: named skipped factors with reason codes
  caps_and_rounding: min, max, floor, cap, round, override, or clamp operations
  warnings: active warnings or blocked-state labels
  rule_risk_annotations: must-mention rule-risk notes
  source_anchors: source book, page, section, and local-binding refs
  unsupported_factors: explicit gaps instead of hidden omission
  stale_if_snapshot_changes: snapshot token or digest
  counterfactual_actions: bounded supported what-if actions
  privacy_class: public_safe|signed_in|campaign_private|gm_private|support_private
```

Required packet rules:

- every applied factor appears exactly once in either `steps` or `modifiers_applied`
- skipped or suppressed factors stay visible when they matter to user trust
- caps, floors, rounding, and overrides are first-class operations, not narration side notes
- source anchors stay attached to the same packet that made the claim
- import or migration explanations cite the same bounded-loss or warning receipt the user can inspect elsewhere
- the packet must be strong enough to render a complete text explanation without any model call

## Coverage registry

Promoted surfaces must not rely on ad hoc explain affordances.

Chummer should maintain an `ExplanationCoverageRegistry` that maps:

- visible surface
- value or status ref
- required explanation class
- required source-anchor class
- required counterfactual support, if any
- release posture: flagship, bounded fallback, or out of scope

That registry is release truth, not a TODO list.
If a promoted surface adds a visible mechanical value and does not register explain coverage, the release gate must fail.

## Surface behavior

Every explainable value should support one or more first-party triggers:

- direct click or tap
- context action such as `Explain this value`
- keyboard action
- screen-reader action label

The drawer or panel should be text-first and inspection-first:

1. value or status label
2. final result
3. short summary of the rule path
4. ordered steps
5. applied and skipped factors
6. caps, floors, rounding, or blocked-state decisions
7. source anchors and open-local-rulebook affordance when bound
8. rule-risk notes
9. warning or bounded-loss receipts when relevant
10. optional narration or presenter controls

If the underlying snapshot changes, the explanation must go stale visibly.
It must not keep speaking or rendering as if the old packet still matches the current state.

If a visible value is not yet explainable, the surface must show an explicit unavailable state with a reason.
Silent absence is not acceptable on promoted routes.

## Counterfactual and follow-up model

The strongest user questions are not only "why?" but also "why not?" and "what if?".
Those must stay deterministic too.

Allowed follow-up classes:

- why this result
- why this factor applied or did not apply
- what changed between two snapshots
- what if I remove, add, or toggle one bounded factor
- where did this come from in the rules or source pack

Counterfactual answers must not be improvised by narration.
They should come from a bounded re-run or deterministic diff packet against the same rule environment and snapshot family.

Recommended follow-up truth order:

1. `ExplanationPacket`
2. optional `CounterfactualPacket` or `ExplanationDiffPacket`
3. deterministic renderer
4. optional companion phrasing
5. optional presenter output

If Chummer cannot produce the required packet, it should say so plainly and fall back to text guidance instead of guessing.

## Source anchors and rules text

Explain-every-value is stronger when it stays source-aware.

When a relevant `SourceAnchor` exists, the drawer should show it and, when locally bound, offer:

`Open local rulebook`

The packet may name:

- source book
- section hint
- page
- rule or data identifier
- local-binding availability

It must not:

- upload local rulebooks
- log local file paths into shared telemetry
- quote large copyrighted rule passages as a substitute for explain truth

## Presenter and voice boundaries

Companion, TTS, avatar, or video modes are optional presentation layers for the same packet.

Rules:

- text explanation is always the first-party fallback
- presentation may restyle or narrate packet truth, but may not add factors or hidden certainty
- microphone use is opt-in and visibly active
- text follow-up remains first-class when microphone or speech services are unavailable
- provider adapters stay replaceable and downstream of packet approval
- no provider-specific brand becomes canonical product truth

If voice or presenter mode fails, the explanation drawer must still succeed.

## Performance, privacy, and offline posture

The user should get useful truth immediately.

Recommended engineering targets:

- drawer opens without blocking the main surface
- packet resolution targets p95 under 1.5 seconds
- deterministic text targets p95 under 3 seconds
- optional narration or presenter may be slower without blocking the packet view

Required privacy posture:

- external AI, speech, or video usage is opt-in
- only minimal packet context leaves the device
- unrelated notes, biography text, or full inventory do not leave the device just to explain one value
- raw microphone capture never starts invisibly
- text-only deterministic mode is always available

Offline or degraded mode may lose narration polish.
It may not lose explain truth.

## Release gate

Explain-every-value is release-bound when promoted routes claim it.

The gate should fail closed when any of the following are true:

- a promoted visible value or warning lacks a registered explanation contract
- the packet cannot reproduce the displayed result or bounded status
- applied, skipped, capped, or rounded factors are missing from the packet
- required source anchors or import receipts are stale, missing, or mismatched
- a counterfactual answer is presented without a deterministic packet
- narration mentions factors or rule text outside approved packet scope
- microphone-only interaction is required for a complete explain path
- new visible values land without coverage-registry updates

Required proof families:

- golden fixtures and parity fixtures
- UI trigger and drawer proof
- source-anchor and local-rulebook-open proof
- AI or presenter grounding rejection tests
- stale-snapshot and changed-character invalidation tests

## Ownership split

- `chummer6-core`: explanation packets, counterfactual packets, arithmetic verification, rule-risk metadata, source-anchor refs
- `chummer6-ui`: desktop drawer UX, text-first rendering, bounded follow-up, stale-state handling, local rulebook affordances
- `chummer6-mobile`: quick explain and bounded follow-up on mobile and live-play surfaces
- `executive-assistant`: optional packet-grounded narration or follow-up compile, with no trigger or arithmetic authority
- `chummer6-media-factory`: optional audio or video siblings, with no rules authority
- `fleet`: release gates, coverage verification, and proof fail-closed posture
- `chummer6-design`: product promise, truth order, scope, and guardrails

## Recommended milestone spine

1. Packet coverage and coverage-registry floor.
2. Desktop text-first explain drawer across promoted workbench surfaces.
3. Counterfactual and why-changed packets for bounded what-if questions.
4. Mobile and live-play explain surfaces.
5. Optional narration, TTS, or presenter layers that remain subordinate to packet truth.
6. Release-bound proof that no promoted visible value ships without coverage.

The critical win is not a talking avatar.
The critical win is that Chummer can defend every important visible result with inspectable, deterministic product truth.
