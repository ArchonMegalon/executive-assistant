# Black Ledger Stats Spec

## Public stat contract

Every public Black Ledger stat must provide:

- `id`
- `title`
- `value`
- `scope`
- `period`
- `sample_size`
- `confidence`
- `source`
- `privacy_note`
- `status`
- `route`

## Public safety rules

- Public stats are aggregate only.
- Public stats are opt-in only.
- Individual runner, support, and campaign-private state fail closed.
- Public labels must stay mechanical or fictional, never shaming.

## Seeded preview floor

Required preview-ready examples:

- MysAd density
- Debt Heat
- Package pressure
- Chaos index

The homepage and `/ledger` must read from the same governed model.
