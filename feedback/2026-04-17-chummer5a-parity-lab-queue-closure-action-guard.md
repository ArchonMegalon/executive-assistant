Package: `next90-m103-ea-parity-lab`
Frontier: `4287684466`
Milestone: `103`
Owned surfaces: `parity_lab:capture`, `veteran_compare_packs`

Change:

- Added `completion_action: verify_closed_package_only` and a matching `do_not_reopen_reason` to both successor queue rows for the completed EA parity-lab package.
- Tightened `tests/test_chummer5a_parity_lab_pack.py` so the design queue and Fleet queue mirrors must agree on the closure-only action and Chummer5a oracle recapture ban.
- Left the frozen EA closeout receipt append-free because the explicit append conditions did not fail.

Proof:

- `python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed
- `python tests/test_chummer5a_parity_lab_pack.py` -> `ran=18 failed=0`

No operator telemetry, active-run helper commands, oracle recapture, or receipt timestamp refresh was used.
No EA-owned parity-lab extraction work remains.
