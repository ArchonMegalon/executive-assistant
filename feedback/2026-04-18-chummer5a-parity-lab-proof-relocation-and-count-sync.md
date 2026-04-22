Package: `next90-m103-ea-parity-lab`
Frontier: `4287684466`
Milestone: `103`
Owned surfaces: `parity_lab:capture`, `veteran_compare_packs`

What changed:

- Updated the EA-side parity-lab direct guard to match the current canonical split: the design-owned queue still freezes the original `/docker/EA` closeout anchors, while the successor registry row and Fleet queue mirror now point at the relocated Fleet-owned oracle pack proof.
- Kept the local append-free closure contract intact by validating both proof shapes instead of trying to rewrite the closed EA receipt or recapture oracle artifacts.
- Recorded the current local direct-proof baseline as `python tests/test_chummer5a_parity_lab_pack.py -> ran=18 failed=0`, which is the live count after the newer worker-safe and queue-split guard coverage landed.

Boundary:

This is a proof-honesty and drift-alignment pass only. It does not reopen milestone 103, move canonical ownership back out of Fleet, or re-run the closed EA extraction slice.
