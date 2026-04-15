# Chummer5a parity lab repeat verification

Package: `next90-m103-ea-parity-lab`
Milestone: `103`
Owned surfaces: `parity_lab:capture`, `veteran_compare_packs`

What changed:

- Added a `repeat_verifications` entry to `docs/chummer5a_parity_lab/SUCCESSOR_HANDOFF_CLOSEOUT.yaml` for the successor-wave handoff generated at `2026-04-15T10:45:43Z`.
- Tightened `tests/test_chummer5a_parity_lab_pack.py` so the latest repeat-verification marker must be no newer than the active handoff timestamp and must match frontier id `4287684466`, package id, complete registry/queue posture, and direct proof result.

Proof:

- `python tests/test_chummer5a_parity_lab_pack.py` -> `ran=14 failed=0`

Boundary:

- The EA-owned extraction package remains closed.
- Do not reopen the closed flagship wave.
- Promoted-head screenshot-backed veteran certification remains delegated to `next90-m103-ui-veteran-certification`.
