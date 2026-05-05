# BUILD GHOST MVP 001

**Product:** Chummer6 / SR Campaign OS
**Design area:** ALICE, build simulation, deterministic comparison
**Status:** Proposal / first proof slice

## Goal

Prove that Chummer can let a player compare alternate versions of the same runner without mutating the canonical build until the player explicitly applies a reviewed change set.

The first slice is:

```text
Build Ghost 001
```

## Loop

```text
user opens a runner
-> user spawns Ghost A and Ghost B from the current runner snapshot
-> user changes selected build inputs inside each ghost
-> Chummer computes receipt-backed deltas
-> compare view shows legal / illegal / weak-link / role-fit differences
-> user discards one ghost or applies one reviewed ghost delta
-> canonical runner changes only through the apply receipt
```

## Core objects

```yaml
RunnerSnapshot:
  runner_ref: runner_001
  ruleset: sr5
  environment_ref: campaign_alpha
  captured_at: 2026-05-03T00:00:00Z
  source_of_truth: engine_owned_runner_state
```

```yaml
BuildGhost:
  ghost_ref: build_ghost_a
  source_runner_ref: runner_001
  source_snapshot_ref: snapshot_runner_001
  branch_kind: comparison_variant
  visibility: local_workspace_only
  changes:
    - kind: gear_swap
      remove: armor_jacket_standard
      add: armor_jacket_custom_fit
    - kind: augmentation_add
      add: wired_reflexes_1
  canonical: false
```

```yaml
GhostComparison:
  comparison_ref: compare_runner_001_build_ghost_a_build_ghost_b
  source_runner_ref: runner_001
  ghost_refs:
    - build_ghost_a
    - build_ghost_b
  computed_deltas:
    nuyen_delta:
      build_ghost_a: -18000
      build_ghost_b: -24500
    legality_posture:
      build_ghost_a: legal
      build_ghost_b: exceeds_campaign_starting_gear
    weak_links:
      - build_ghost_b_low_body_for_role
  explain_refs:
    - receipt_compare_001
```

```yaml
ApplyReceipt:
  receipt_ref: apply_build_ghost_a_001
  source_runner_ref: runner_001
  applied_ghost_ref: build_ghost_a
  human_confirmed: true
  discarded_ghost_refs:
    - build_ghost_b
  undo_anchor_ref: snapshot_runner_001
```

## Rule

Ghosts are derived work copies, not new canonical runners.

All mechanics, legality, and budget checks come from Chummer-owned engine truth.
Any assistant, explainer, or drafting lane may only summarize a computed delta.
It does not compute or override build truth.

Facepop is out of scope.
It is a public concierge/testimonial tool, not a build-simulation dependency.

## First release gates

```text
spawn_build_ghosts_from_current_runner_snapshot
ghost_edits_never_mutate_canonical_runner_without_apply
compare_view_shows_nuyen_legality_role_fit_and_weak_link_deltas
discard_and_apply_paths_emit_receipts_and_undo_anchor
```

## First UI posture

The first good surface is a three-column compare bench:

* source runner
* Ghost A
* Ghost B

Each column should show:

* key build stats
* nuyen posture
* legality posture
* role-fit summary
* weak-link callouts
* changed items

The bottom rail should show:

* `Discard Ghost`
* `Apply Ghost`
* `Show math`
* `Show receipts`
* `Compare against campaign`

## Why this slice matters

If BUILD GHOST works, ALICE stops being vague "build advice" and becomes a concrete Chummer-native move:

* branch the runner
* inspect the tradeoff
* keep the source safe
* commit only when the user means it
