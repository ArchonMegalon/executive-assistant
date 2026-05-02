# Executive Assistant Product Release Checklist

## Flagship closeout rule

This checklist is not enough by itself.

A flagship claim must also satisfy `.codex-design/ea/START_HERE.md`, `FLAGSHIP_CLOSEOUT_PLAN.md`, `EA_FLAGSHIP_TRUTH_PLANE.md`, `EA_FLAGSHIP_RELEASE_GATE.json`, and the generated `EA_FLAGSHIP_RELEASE_GATE.generated.json` receipt.
`MILESTONE.json` is supporting delivery history, not the release oracle.

The critical test is whether the shipped workspace behaves like a real executive-office work system rather than a polished shell.

## Activation

- `/` renders the current product promise without legacy or side-brand drift.
- `/get-started` leads with Google-first activation.
- a new workspace can reach first value without configuring messaging channels.
- the first useful loop is visible:
  - memo
  - one draft
  - one follow-up
  - one trust receipt

## Core workspace

- `/app/today` renders real memo, queue, commitment, and people objects.
- `/app/briefing` renders the decision queue and memo context from product objects.
- `/app/inbox` renders reviewable drafts and open commitments, not placeholder cards.
- `/app/follow-ups` renders open handoffs and unresolved commitments.
- `/app/people/{id}` renders relationship context, open loops, drafts, and evidence.

## Workflows

- one draft can be approved from the browser.
- one commitment can be closed from the browser.
- one handoff can be assigned and completed through product routes.
- one commitment candidate can be extracted from raw text and converted into a saved item.
- one people-graph correction can be applied and reflected on reload.

## Trust and operations

- approvals remain explainable through evidence and rule posture.
- admin audit surface renders without leaking internal implementation vocabulary.
- operator-only admin surfaces remain unavailable outside operator context.
- diagnostics and entitlements return stable product contracts.

## Boundary

- public tours are off in product mode.
- public results are off in product mode.
- no public nav item links to experimental or legacy surfaces.
- browser contract tests fail if `chummer`, `gm_creator_ops`, `principal_id`, or `operator_id` leak into rendered product pages.

## Automated gates

- browser surface contracts pass.
- product API contracts pass.
- product entitlement contracts pass.
- real browser E2E passes.
- runtime smoke passes.
- the EA flagship receipt is materialized and current.
- the flagship closeout blockers in `FLAGSHIP_CLOSEOUT_PLAN.md` are all materially closed.
