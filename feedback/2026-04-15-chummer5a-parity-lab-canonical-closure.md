Title: Chummer5a parity-lab canonical closure

Package: next90-m103-ea-parity-lab
Milestone: 103
Owned surfaces: parity_lab:capture, veteran_compare_packs

What changed:
- Marked successor registry work task `103.1` complete with EA proof evidence.
- Marked queue package `next90-m103-ea-parity-lab` complete with concrete proof paths and the direct test command.
- Tightened `tests/test_chummer5a_parity_lab_pack.py` so the package fails if the canonical registry or queue reopens the EA-owned slice.
- Updated `docs/chummer5a_parity_lab/SUCCESSOR_HANDOFF_CLOSEOUT.yaml` with explicit canonical closure markers.

Proof:
- `python tests/test_chummer5a_parity_lab_pack.py` -> `ran=13 failed=0`
- `python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed

Remaining:
- No EA-owned parity-lab extraction work remains for this package.
- Promoted-head screenshot-backed veteran certification, parity-ladder policy, and readiness consumption remain with the non-EA packages named in the handoff closeout.
