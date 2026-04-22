Package: `next90-m103-ea-parity-lab`
Frontier: `4287684466`

What changed:

- Tightened `tests/test_chummer5a_parity_lab_pack.py` so every verifier subprocess proof call must be `subprocess.run` with literal command review, `check=True`, captured stdout/stderr, and `text=True`.
- Kept the closed EA package append-free: no parity-lab docs, generated receipts, queue rows, or oracle artifacts were refreshed.

Verification:

- `python tests/test_chummer5a_parity_lab_pack.py` -> `ran=18 failed=0`

Remaining:

- No EA-owned parity-lab extraction work remains. The only remaining M103 work is already delegated to the non-EA follow-up packages named in `SUCCESSOR_HANDOFF_CLOSEOUT.yaml`.
