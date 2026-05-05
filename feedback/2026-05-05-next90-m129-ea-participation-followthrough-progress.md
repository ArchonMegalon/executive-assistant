# Next90 M129.5 EA participation followthrough packets

## What landed

- added an EA packet contract for contribution, participation, entitlement, channel, and reward followthrough under `docs/chummer_participation_followthrough_packets`
- added a materializer and verifier for the generated proof contract
- kept the package fail-closed against the live Hub and Fleet M129 receipt window

## Governed source window

- Hub reusable-account receipt: `/docker/chummercomplete/chummer6-hub-m112/.codex-studio/published/NEXT90_M129_HUB_REUSABLE_ACCOUNT_FLOWS.generated.json`
- Fleet participation receipt: `/docker/fleet/.codex-studio/published/NEXT90_M129_FLEET_PARTICIPATION_LANE_RECEIPTS.generated.json`

## Active holds surfaced by this package

- Fleet participation proof is still blocked, so contribution and participation followthrough remain on hold.
- The current Hub/Fleet receipt window does not yet project explicit channel refs.
- The current Hub/Fleet receipt window does not yet project explicit reward-publication refs.

## Proof commands

- `python3 scripts/materialize_next90_m129_ea_participation_followthrough_packets.py`
- `python3 scripts/verify_next90_m129_ea_participation_followthrough_packets.py`
