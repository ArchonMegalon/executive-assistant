# Executive Assistant Customer Diagnostics

## Purpose

This guide defines the minimum support view for a paying Executive Assistant workspace.

## What support should answer quickly

- which workspace is affected
- which plan and entitlements are active
- whether messaging is included
- whether the runtime is ready
- how many operators are active
- how many providers and lanes are bound
- how much work is currently visible:
  - memo items
  - queue items
  - commitments
  - people

## Current product surface

Use:

- `/admin/api`
- `/app/api/diagnostics`
- `/app/api/diagnostics/export`

The admin diagnostics page is the operator-friendly surface.
The diagnostics APIs are the machine-readable contracts.

## Minimum support workflow

1. open the admin diagnostics page
2. confirm workspace, mode, region, timezone, and selected channels
3. confirm plan and seat entitlements
4. confirm readiness and provider counts
5. confirm active operator count and current usage footprint
6. if runtime work is missing, inspect:
   - `/admin/audit-trail`
   - `/admin/providers`
   - `/admin/policies`
7. if support needs a portable bundle, export:
   - `/app/api/diagnostics/export`

## Do not require for first-line support

- raw database access
- reading internal code
- browsing internal implementation-only routes
