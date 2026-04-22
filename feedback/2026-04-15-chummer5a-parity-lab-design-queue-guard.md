Title: Chummer5a parity lab design queue guard

Package: `next90-m103-ea-parity-lab`
Milestone: `103`
Frontier: `4287684466`
Owned surfaces: `parity_lab:capture`, `veteran_compare_packs`

What changed:
- Revalidated the already-complete EA package against the canonical successor registry, the design-owned queue staging assignment, the Fleet completed queue mirror, and the active-run handoff generated at `2026-04-15T12:07:24Z`.
- Tightened `tests/test_chummer5a_parity_lab_pack.py` so Fleet completed queue proof must point back to the design-owned queue source and both queue rows must agree on repo, frontier, milestone, wave, allowed paths, and owned surfaces.
- Refreshed `docs/chummer5a_parity_lab/SUCCESSOR_HANDOFF_CLOSEOUT.yaml` with the latest repeat-verification marker and explicit design-queue closure anchor.

Proof:
- `python tests/test_chummer5a_parity_lab_pack.py` exits with `ran=15 failed=0`.

No operator telemetry or active-run helper commands were invoked. No EA-owned parity-lab extraction work remains for this package; remaining milestone `103` work belongs to the sibling UI, design, and Fleet lanes named in the handoff closeout.
