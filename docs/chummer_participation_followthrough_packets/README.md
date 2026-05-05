# Chummer Participation Followthrough Packets

This package lands the EA-owned slice for milestone `129`:

- `CHUMMER_PARTICIPATION_FOLLOWTHROUGH_PACKET_PACK.yaml` defines the EA-local contract for contribution, participation, entitlement, channel, and reward followthrough without granting EA account, channel, or reward authority.
- `PARTICIPATION_FOLLOWTHROUGH_PACKET_SPECIMENS.yaml` captures the minimum packet shapes and the source links each packet family must preserve.
- `SUCCESSOR_HANDOFF_CLOSEOUT.yaml` records the active package boundary, canonical queue and registry authority, and the current upstream gaps that still belong to Hub, Fleet, and design.
- `scripts/materialize_next90_m129_ea_participation_followthrough_packets.py` and `scripts/verify_next90_m129_ea_participation_followthrough_packets.py` keep the generated proof machine-checkable.

The package is intentionally fail-closed. If Fleet participation proof stays blocked, if Hub reusable-account proof no longer carries the entitlement and reward rails, or if Hub/Fleet still do not project explicit channel and reward-publication refs, EA must hold followthrough packets instead of inventing state from local auth or Registry-only mirrors.
