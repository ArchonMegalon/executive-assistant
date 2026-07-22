# What Is Still Below Gold

Last reviewed: 2026-07-11

This file exists to stop structural closure from masquerading as flagship replacement truth.

## Current whole-product blockers

No current whole-product blockers are keeping the promoted desktop release lane below gold.

- Current public shelf platform ids: `linux`, `windows`.
- Current public shelf head ids: `avalonia`.
- Public-stable release truth carries promoted Avalonia Linux x64 and Windows x64 installers with matching startup-smoke and executable-exit proof.
- macOS is not on the current public shelf and is not part of this promoted-scope gold claim.
- The flagship UI release gate, desktop executable exit gate, desktop workflow execution gate, and desktop visual familiarity gate are all current and passing against the same promoted desktop bytes.
- Keep this file fail-closed: reopen it only if public-stable tuple coverage, startup-smoke truth, or packaged desktop proof drifts below the current release wave.

## Families below gold

No in-scope flagship parity family is currently below `gold_ready`.

`FLAGSHIP_PARITY_REGISTRY.yaml` is now allowed to mark every in-scope family `gold_ready` because the promoted public-stable desktop lane, packaged-head receipts, and release-bound readiness proof now agree.

## Regression watch

Keep this file as the fail-closed place to record future regressions if the published readiness proof reopens a coverage lane or if any family in `FLAGSHIP_PARITY_REGISTRY.yaml` falls below its currently justified state.

Do not reintroduce a public or operator flagship claim if the promoted Avalonia route loses workbench-first startup or restore continuation, the real `File` menu, first-class master index, first-class character roster, in-app claim/restore/recovery, dense-workbench budget proof, or honest support/crash routing.
