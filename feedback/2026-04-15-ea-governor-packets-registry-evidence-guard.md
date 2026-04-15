Title: EA governor-packet registry evidence guard

Package: next90-m106-ea-governor-packets
Frontier: 1758984842

What shipped:
- Tightened `tests/test_chummer_governor_packet_pack.py` so milestone `106` work task `106.2` must keep its `/docker/EA/...` registry evidence paths live.
- The new guard also verifies each registry-cited EA file remains under the allowed package roots: `docs`, `tests`, `feedback`, or `skills`.
- The guard keeps the direct proof command pinned to `python tests/test_chummer_governor_packet_pack.py exits 0 with ran=16 failed=0.` so registry evidence cannot drift into stale prose.

What remains:
- No EA-owned work remains for `operator_packets:weekly_governor` or `reporter_followthrough:release_truth`.
- Fleet, Hub, Registry, and design sibling lanes still own the non-EA portions of milestone `106`.

Exact blocker:
- None inside the EA-owned package surfaces.
