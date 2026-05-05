# Chummer Organizer Packets

This package lands the EA-owned slice for milestone `118`:

- `CHUMMER_ORGANIZER_PACKET_PACK.yaml` defines the EA-local contract for organizer followthrough and event-prep packets without granting EA organizer, publication, or support authority.
- `ORGANIZER_PACKET_SPECIMENS.yaml` captures the packet shape and the minimum source links each packet family must preserve.
- `SUCCESSOR_HANDOFF_CLOSEOUT.yaml` records the active package boundary, canonical queue and registry authority, and the current follow-on work that still belongs to Hub, UI, and Fleet.
- `scripts/materialize_next90_m118_ea_organizer_packets.py` and `scripts/verify_next90_m118_ea_organizer_packets.py` keep the generated proof and package guard machine-checkable.

The package is intentionally fail-closed. If Hub organizer proof, creator-publication proof, Fleet support gates, the weekly governor action window, or the underlying `CommunityScaleAuditPacket` links drift, EA must block organizer followthrough and event-prep copy instead of improvising a summary.
