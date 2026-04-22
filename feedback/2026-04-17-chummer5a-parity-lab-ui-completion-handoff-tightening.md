Package: `next90-m103-ea-parity-lab`
Frontier: `4287684466`
Milestone: `103`
Owned surfaces: `parity_lab:capture`, `veteran_compare_packs`

What changed:

- Tightened the EA closeout handoff now that the canonical M103 registry reports `103.2` as complete for the UI veteran-certification package.
- Moved `next90-m103-ui-veteran-certification` out of remaining allowed next work and recorded it as completed non-EA work.
- Kept the EA oracle baselines, veteran workflow pack, compare packs, fixture inventory, and append-free repeat rows unchanged.

Proof:

- `python tests/test_chummer5a_parity_lab_pack.py` -> `ran=18 failed=0`
- `python -m py_compile tests/test_chummer5a_parity_lab_pack.py` -> passed

Boundary:

No EA-owned parity-lab extraction work remains. This pass did not invoke operator telemetry, active-run helper commands, helper-output proof, Chummer5a oracle recapture, or flagship-wave reopening.
