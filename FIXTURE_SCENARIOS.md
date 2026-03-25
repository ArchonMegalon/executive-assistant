# Executive Assistant Fixture Scenarios

Maintain these scenarios for product and browser tests.

## 1. Founder workspace

- one principal
- Gmail + Calendar
- one investor follow-up
- one vendor deadline
- one approval-backed reply

## 2. Executive + operator workspace

- one principal
- one operator
- one open handoff task
- one board-facing commitment
- one stakeholder with open loops
- one approval waiting on the principal

## 3. Shared team workspace

- shared queue
- multiple open commitments
- mixed approvals and human tasks
- one provider binding with degraded health

## Minimum fixture expectations

Each fixture should be able to power:

- `/app/today`
- `/app/briefing`
- `/app/inbox`
- `/app/follow-ups`
- `/admin/providers`
- `/admin/audit-trail`

And each fixture should include:

- commitments
- follow-ups
- stakeholders
- decision windows
- deadline windows
- at least one approval or human task
