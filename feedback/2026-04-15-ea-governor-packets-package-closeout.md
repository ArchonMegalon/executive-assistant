Title: EA governor-packet package proof for milestone 106

Package: next90-m106-ea-governor-packets
Milestone: 106 Product-governor weekly adoption and measured rollout loop

What shipped:
- Added `docs/chummer_governor_packets/CHUMMER_GOVERNOR_PACKET_PACK.yaml` as the EA-local synthesis contract for `operator_packets:weekly_governor` and `reporter_followthrough:release_truth`.
- Grounded the operator and reporter outputs in the same evidence anchors: weekly pulse, Chummer5a parity-lab pack, feedback release gate, and reporter progress email workflow.
- Kept reporter `fix_available` fail-closed on `released_to_reporter_channel` plus Registry truth, so EA cannot notify from reproduced bugs, drafted patches, merged PRs, or preview builds.
- Added package tests that verify the canonical successor registry, staging queue, source files, runtime-safety posture, and EA boundary rules.

What remains:
- Fleet still owns the landed weekly governor packet runtime and publication surface.
- Hub and Registry still own raw case truth, install/reporter linkage, release-channel truth, and reporter-channel availability.
- Design still owns successor registry meaning and milestone closeout language.

Exact blocker:
- None inside the EA-owned package surfaces. Sibling milestone 106 work remains in Fleet, Hub, Registry, and design-owned lanes.
