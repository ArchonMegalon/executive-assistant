Package: `next90-m103-ea-parity-lab`
Frontier: `4287684466`
Owned surfaces: `parity_lab:capture`, `veteran_compare_packs`

What changed:
- Tightened `tests/test_chummer5a_parity_lab_pack.py` so the worker prompt's required startup block must contain exactly four numbered commands in order before broader context reads.
- Kept task-local command context separate from the required startup block, so broader historical context cannot silently expand the implementation-only first step.

Verification:
- `python tests/test_chummer5a_parity_lab_pack.py` -> `ran=18 failed=0`
- `python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed

Result:
- No EA-owned parity-lab extraction work remains.
- No operator telemetry, active-run helper commands, oracle recapture, receipt refresh, or repeat-row append was needed for this pass.
