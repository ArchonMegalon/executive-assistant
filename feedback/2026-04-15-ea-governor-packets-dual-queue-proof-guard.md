Title: EA governor-packet dual queue proof guard

Package: next90-m106-ea-governor-packets
Frontier: 1758984842

What shipped:
- Tightened `tests/test_chummer_governor_packet_pack.py` so the Fleet-published successor queue and the design-owned successor queue must agree on the closed EA package proof row.
- The guard now fails closed when either queue row drifts on package status, repo, allowed paths, owned surfaces, or proof entries.
- Updated the handoff closeout manifest to name both queue authorities, so future shards do not redispatch the EA package from a stale generated queue copy.

What remains:
- No EA-owned work remains for `operator_packets:weekly_governor` or `reporter_followthrough:release_truth`.
- Fleet, Hub, Registry, and design sibling lanes still own the non-EA portions of milestone `106`.

Exact blocker:
- None inside the EA-owned package surfaces.
