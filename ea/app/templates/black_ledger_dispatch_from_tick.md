# Dispatch Draft From Tick

Build a draft from bounded facts only.

Required inputs:

- `world_id`
- `turn`
- `source_receipt_ids`
- `facts`
- `allowed_factions`
- `allowed_districts`
- `forbidden_claims`

Required output:

- `draft_id`
- `title`
- `body_markdown`
- `highlights`

Rules:

- preserve source facts
- no unsupported claims
- no private data
- no provider names
- draft only, never direct publication
