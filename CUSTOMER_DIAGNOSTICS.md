# Executive Assistant Customer Diagnostics

Use this when a customer says the product is not behaving as expected.

## Questions to answer first

1. Did the workspace connect Google successfully?
2. Did the workspace produce memo items, queue items, and commitments?
3. Is the issue in product state, provider state, or delivery state?

## Product checks

- `GET /app/api/brief`
- `GET /app/api/queue`
- `GET /app/api/commitments`
- `GET /app/api/drafts`
- `GET /app/api/people`
- `GET /app/api/handoffs`
- `GET /app/api/diagnostics`

These should explain what the browser is rendering.

## Runtime checks

- `/v1/providers/states/*`
- `/v1/human/tasks`
- `/v1/delivery/outbox/pending`
- `/v1/runtime/health`

## Symptoms and likely causes

### No memo items

- no connected Google account
- no seeded commitments or decision windows
- product projections are returning empty source objects

### Draft queue empty

- no pending approval requests
- no approval-backed draft-producing steps

### Commitments missing

- no open commitments or follow-ups in memory
- commitment status already completed or cancelled

### Admin providers look empty

- no provider bindings for the current principal
- binding health degraded or unavailable

## Support bundle

When escalating internally, capture:

- current principal/workspace
- memo payload
- queue payload
- commitments payload
- provider registry read model
- pending human tasks
- pending delivery
