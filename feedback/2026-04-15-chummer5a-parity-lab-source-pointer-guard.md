Title: Chummer5a parity-lab source pointer guard

Package: next90-m103-ea-parity-lab
Milestone: 103
Owned surfaces: parity_lab:capture, veteran_compare_packs

What changed:
- Tightened `tests/test_chummer5a_parity_lab_pack.py` so the `task_proven` parity-lab pack now fails closed when the manifest, oracle baseline, veteran workflow pack, compare pack, or import/export inventory points at missing repo-local evidence.
- Kept the package scoped to EA-owned proof surfaces and allowed paths; this does not reopen the closed flagship wave.

Verification:
- `python tests/test_chummer5a_parity_lab_pack.py` -> `ran=11 failed=0`

Remaining boundary:
- No EA-owned parity-lab extraction work remains for `next90-m103-ea-parity-lab`.
- Promoted-head screenshot-backed veteran certification remains delegated to `next90-m103-ui-veteran-certification`.
