# LTD Integration Map

## Emailit

Use for:

- morning memo delivery
- registration links
- workspace invites
- approval links
- delivery receipts

## Documentation.AI

Use for:

- customer docs
- operator docs
- API docs
- `llms.txt`

## MarkupGo

Use for:

- memo PDFs
- audit receipts
- board-prep packs
- support bundles

## FlipLink.me

Use for:

- redacted PropertyQuarry review-packet flipbooks
- shareable property shortlist packets
- customer-facing packet presentation downstream of PropertyQuarry facts

Do not use for:

- listing truth
- ranking truth
- entitlement truth
- public-tour asset truth

## Hedy

Use for:

- meeting capture
- transcript-backed evidence
- commitment extraction
- decision proposals
- people-memory enrichment

## Poppy AI

Use for:

- public video transcript repurposing drafts
- public PDF summary drafts
- manually approved operator-note drafts
- public release-copy variants

Do not use for:

- live assistant runtime
- product truth
- release truth
- support truth
- private campaign data
- sourcebook copied text
- memorial-private material

Operator proof:

- `python3 scripts/verify_poppy_session.py`
- `python3 scripts/materialize_poppy_draft_packet.py --source-packet <packet.json> --draft-output <draft.txt>`

The source packet and human review own truth. Poppy output is only draft text until reviewed and copied into EA/Chummer-owned source material.
