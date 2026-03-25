# Executive Assistant Product Release Checklist

Use this in addition to the runtime release checklist.

## Activation

- `/get-started` reaches Google-first activation without forcing messaging setup
- the first memo preview is visible before advanced channel setup
- sign-in and callback flows land on the correct product domain

## Core daily loop

- `/app/today` renders real memo items
- `/app/briefing` renders real queue items
- `/app/inbox` renders commitments and draft approvals
- `/app/follow-ups` renders handoffs and open follow-up work

## Product APIs

- `/app/api/brief`
- `/app/api/queue`
- `/app/api/commitments`
- `/app/api/drafts`
- `/app/api/people`
- `/app/api/handoffs`
- `/app/api/diagnostics`

All return contract-valid payloads for seeded fixture workspaces.

## Approvals and commitments

- one approval can be completed through the product API
- one commitment can be closed through the product API
- the browser pages re-render the changed state

## Admin

- `/admin/providers` shows live provider registry state
- `/admin/audit-trail` shows approval/delivery posture
- `/admin/operators` shows operator and task pressure

## Browser QA

- browser contract tests pass
- product browser journey tests pass
- public routes and app routes return `200`

## Runtime

- `bash scripts/smoke_api.sh` returns `smoke complete`
- deployment health and OpenAPI checks are green
