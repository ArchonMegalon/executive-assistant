Package: `next90-m103-ea-parity-lab`
Frontier: `4287684466`
Milestone: `103`
Owned surfaces: `parity_lab:capture`, `veteran_compare_packs`

What changed:

- Tightened `tests/test_chummer5a_parity_lab_pack.py` so the active worker prompt must preserve the four exact implementation-only start commands before any broader context reads.
- Kept the closed parity-lab receipt, generated receipt, oracle baselines, workflow pack, compare pack, and fixture inventory append-free because the canonical anchors and direct proof command still agree.

Proof:

- `python tests/test_chummer5a_parity_lab_pack.py` -> `ran=18 failed=0`
- `python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed

Boundary:

No EA-owned parity-lab extraction work remains. This pass used no operator telemetry, active-run helper commands, helper-output proof, Chummer5a oracle recapture, or flagship-wave reopening.
