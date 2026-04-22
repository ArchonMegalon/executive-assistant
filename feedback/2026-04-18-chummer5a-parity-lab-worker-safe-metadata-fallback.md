Package: `next90-m103-ea-parity-lab`
Frontier: `4287684466`
Milestone: `103`
Owned surfaces: `parity_lab:capture`, `veteran_compare_packs`

What changed:

- Tightened `feedback/chummer5a_parity_lab_worker_safe_context_check.py` so the worker-safe context checker now accepts either `- Prompt path:` or the `State root` plus `Run id` fallback already supported by the direct M103 proof.
- Kept the handoff lookup worker-safe across both live runtime aliases, so the checker can resolve the same worker-safe prompt from either `/var/lib/codex-fleet/.../ACTIVE_RUN_HANDOFF.generated.md` or `/docker/fleet/state/.../ACTIVE_RUN_HANDOFF.generated.md`.
- Kept the M103 closure guard consistent across both proof entrypoints, so a newer active handoff cannot force receipt churn just because the prompt path line is omitted while the run metadata still resolves the same worker-safe prompt.
- Left the frozen EA parity-lab receipt, closeout, queue proof, and artifact packs append-free because the direct package proof stayed green and no canonical closure anchor failed.

Proof:

- `python tests/test_chummer5a_parity_lab_pack.py` -> `ran=18 failed=0`
- `python feedback/chummer5a_parity_lab_worker_safe_context_check.py` -> `ran=3 failed=0`

Boundary:

No EA-owned parity-lab extraction work remains. This pass only hardened the worker-safe resume-context guard and did not invoke operator telemetry, active-run helper commands, or reopen flagship closeout or recapture oracle artifacts.
