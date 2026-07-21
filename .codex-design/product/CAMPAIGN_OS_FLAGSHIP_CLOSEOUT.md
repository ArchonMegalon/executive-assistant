# Campaign OS Flagship Closeout

## Purpose

Give Fleet one explicit closeout order for finishing Chummer6 as a flagship Campaign OS, including horizon posture.

This file is narrower than the full product canon.
It exists to stop the loop from scattering effort across desktop polish, localization, public copy, and future horizons without closing the two real red blockers first.

## Current verdict

Current promoted-scope verdict: `GOLD_READY`.

The current public-stable Chummer release clears the flagship closeout bar for the promoted Avalonia desktop scope. This is a bounded release claim, not a claim that every future horizon or additive product lane is finished.

The remaining blocker truth is already explicit:

- `BLK-009` flagship localization proof is cleared
- `BLK-010` campaign-OS lived-system proof is cleared

There are no current red blockers in `GROUP_BLOCKERS.md`.
This file now exists to preserve the closeout order that was required to reach that state, and to stop future release summaries from skipping the same sequence when similar blockers reappear.

## Closeout order

### 1. Preserve the promoted Windows desktop tuple

This was the first required closeout lane before `BLK-010` could clear and remains a regression gate.

That means:

- keep the promoted Avalonia Windows installer and payload bound to matching startup-smoke receipts
- republish the release channel, executable gate, and journey receipts when those bytes change
- do not imply that a second desktop head is shipped; Avalonia is the only current public-shelf desktop head

### 2. Keep the lived Campaign OS truth aligned

This was the second required closeout lane before whole-product completion claims were honest.

That means the product story, install/claim/restore path, campaign continuity, publication, closure, and public/support posture must line up as one lived system instead of one coherent architecture plus partial receipts.

The golden-journey layer is the real bar here.

### 3. Keep horizons contingent until they earn promotion

Horizons are allowed to stay exciting.
They are not allowed to dilute release truth.

No horizon may be treated as near-term flagship scope unless:

- its `build_path.current_state` has advanced beyond `horizon`
- its `owner_handoff_gate` is materially satisfied
- the owning repos can cite executable proof instead of public-guide ambition
- its release posture stops reading like contingent research

### 4. Keep the widened claim bounded

Desktop polish, horizon storytelling, and adjacent wow lanes matter.
They do not outrank executable Windows proof or lived-system proof.

The current widened claim covers the promoted Avalonia Linux x64 and Windows x64 artifacts. macOS and any future second desktop head remain outside the current public-shelf promise until independently proven and promoted.

## Fleet execution rule

Whenever a future blocker reopens:

- do not claim Chummer6 is finished
- do not let horizons read like shipment promises
- do not let isolated green local gates outrun the whole-product release posture
