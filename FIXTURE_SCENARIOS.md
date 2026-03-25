# Executive Assistant Fixture Scenarios

## 1. Founder workspace

Use when validating the single-user proof loop.

### Shape

- one principal
- no operator handoff required
- Google connected
- messaging deferred

### Required seeded objects

- one urgent reply approval
- one open commitment due today
- one stakeholder with high importance
- one decision window
- one deadline window

### What this fixture should prove

- first memo is useful
- one draft can be approved
- one commitment can be closed
- one person detail page explains why the relationship matters

## 2. Executive plus operator workspace

Use when validating the paying-customer wedge.

### Shape

- one principal
- one operator
- Google connected
- approvals required
- operator context enabled

### Required seeded objects

- one principal approval
- one operator handoff task
- one commitment owned by the operator
- one board or investor stakeholder
- one audit-trail-worthy action

### What this fixture should prove

- operator queue is visible
- admin audit route is accessible in operator context
- handoff assignment and completion work
- approvals change queue state cleanly

## 3. Shared team workspace

Use when validating entitlement and admin boundaries.

### Shape

- one principal
- multiple operators
- wider plan entitlements
- optional messaging enabled

### Required seeded objects

- multiple operator profiles
- multiple open commitments with different owners
- multiple queue items across approvals, deadlines, and handoffs
- diagnostics payload with plan and usage state

### What this fixture should prove

- seat limits are enforced by plan
- wider plans allow operator-heavy workflows
- diagnostics and readiness remain legible
- browser surfaces still present one product, not multiple sidecars
