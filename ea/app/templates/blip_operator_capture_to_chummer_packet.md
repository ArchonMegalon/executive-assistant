# Operator Capture To Chummer Packet

Source: voice capture

Required output:

- `packet_id`
- `source`
- `capture_type`
- `redacted_transcript`
- `structured_summary`
- `risk_flags`
- `target_repo`
- `recommended_next_action`

Rules:

- redact secrets and tokens
- redact direct emails unless operator-owned and explicitly required
- do not include sourcebook text
- keep the result as an EA packet, not a publishable product artifact
