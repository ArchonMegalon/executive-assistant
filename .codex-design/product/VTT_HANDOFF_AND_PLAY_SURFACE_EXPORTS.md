# VTT handoff and play surface exports

## Purpose

This file defines how Chummer hands dossiers, opposition, and run packets off to play surfaces without surrendering truth.

## Canonical rule

Chummer is the truth.
Play surfaces are projections.

That means:

- Chummer owns rules, roster, run, approval, and consequence truth
- VTTs, Discord bots, and play surfaces receive prepared exports
- import or export failures must be visible rather than silently redefining the object

## Export targets

Current targets worth designing for:

- Foundry character handoff
- Roll20 sheet or handout handoff
- Discord dice-summary packet
- PDF table sheet
- opposition packet export
- run packet export
- player-safe handout export

## Export posture

```yaml
vtt_export_package:
  id: vtt_pkg_001
  target: foundry
  source_object:
    type: OpenRun
    ref: openrun_001
  included_assets:
    - runner_dossier_projection
    - opposition_packet_projection
    - player_safe_handout
  authority_rule:
    source_truth_owner: chummer6-hub
    target_is_projection_only: true
```

## Non-goals

- Chummer is not trying to replace VTTs.
- A VTT import does not become canonical run truth.
- Meeting or play-surface participation telemetry does not become automatic world truth.

## First proof gate

**Seattle Open Run 001**

Includes:

1. one player dossier export
2. one opposition packet export
3. one player-safe handout export
4. one visible export receipt or failure state

Success criterion:

> A GM can treat Chummer as source-of-truth and still move the table into its preferred play surface without hand-copying everything.
