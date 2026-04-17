Package: `next90-m103-ea-parity-lab`
Frontier: `4287684466`
Milestone: `103`
Owned surfaces: `parity_lab:capture`, `veteran_compare_packs`

What changed:

- Fixed the repeat-prevention guard so current focus-owner proof is read from task-local telemetry and active assignment prompt context, not from a handoff field that is not guaranteed to be present.
- Tightened `tests/test_chummer5a_parity_lab_pack.py` to assert the active prompt still lists every required direct-read file, including the roadmap, successor registry, queue staging packet, and task-local telemetry file.
- Kept `SUCCESSOR_HANDOFF_CLOSEOUT.yaml`, the published receipt, and Chummer5a oracle artifacts append-free because the completed package evidence still holds.

Proof:

- `python tests/test_chummer5a_parity_lab_pack.py` -> `ran=18 failed=0`

Boundary:

No EA-owned parity-lab extraction work remains. This pass did not invoke operator telemetry, active-run helper commands, helper-output proof, Chummer5a oracle recapture, or flagship-wave reopening.
