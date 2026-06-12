# Executive Assistant Flagship Closeout Plan

## Purpose

Turn the existing milestone guide into an execution-order closeout plan for Fleet.

This file is intentionally narrower than `EXECUTIVE_ASSISTANT_MILESTONE_DEV_GUIDE.md`.
It answers one question: what still has to become true before Executive Assistant is honestly flagship-grade for a paying executive office.

## Current verdict

Executive Assistant core is flagship-release eligible when the generated EA proof receipts are green.

The earlier closeout blockers are now bound to executable proof instead of prose:

- `.codex-studio/published/EA_BROWSER_WORKFLOW_PROOF.generated.json` proves seeded product-object workspace pages, approval, commitment closure, handoff, people memory, activation, memo, and draft workflows.
- `.codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json` proves the EA flagship truth plane, product canon, browser workflow proof, and release verification binding agree.
- `make ci-gates` proves the current release asset, LTD lane, generated-artifact, and flagship-readiness bundle.

This verdict covers the EA core workspace and release-control claim. It does not promote optional LTD/provider lanes, memorial avatar/video, sales operations, or external publication channels beyond their own receipts.

## Flagship blockers

### EA-FG-001 — workspace pages are product-object driven

Status: closed by browser workflow proof.

`/app/today`, `/app/briefing`, `/app/inbox`, `/app/follow-ups`, queue, handoff, and people-memory flows are covered by seeded browser journeys and real-browser E2E.

### EA-FG-002 — trust and operator posture are proof-bound

Status: closed for the EA core release claim.

Approvals, evidence, human-task routing, and admin/operator boundaries are covered by the current browser workflow proof, release asset verification, and policy/operator contract tests.

### EA-FG-003 — activation is first-value oriented

Status: closed for the EA core release claim.

The real-browser E2E proof covers activation and memo flow before advanced messaging-channel setup.

### EA-FG-004 — commercial and QA proof is release-gated

Status: closed for the EA core release claim while non-core commercial/provider lanes remain separately gated.

The release claim depends on `EA_FLAGSHIP_TRUTH_PLANE.md`, `EA_FLAGSHIP_RELEASE_GATE.json`, generated receipts, and CI gates. It promotes only lanes whose own receipts pass; it does not imply that Poppy, MagicFit, video/avatar providers, or commercial ops are production runtime lanes.

## Remaining Non-Core Gaps

- FlipLink Document Portal is now a verified runtime lane for approved public document presentation because `ea/_completion/fliplink/CHUMMER_FLIPLINK_PUBLICATION.generated.json` passes and the deployed container sees the receipt.
- Memorial video-call avatar remains optional and may warn on missing avatar manifest.
- MagicFit is a verified draft/operator candidate; additional accounts need account-use receipts before claiming they produced assets.
- Poppy remains blocked pending explicit privacy, export-semantics, tenant-isolation, and session proof receipts. Public signal intake, docs factory, prompt foundry, video bake-off, operator control plane, and commercial ops remain draft/operator lanes unless their lane receipts promote them.
- Scheduler logs can show `morning memo configured=0`; that is an activation/configuration state, not a failing release-control gate.

## Fleet execution order

1. Product object core
   - Make Milestone 1 real first.
   - Introduce product-level objects and a thin product API.
   - Do not spend time on broad landing or design polish until the workspace is object-driven.

2. Daily workflow utility
   - Complete Milestones 2 and 3 next.
   - Make Today, Briefing, Inbox, Follow-ups, commitments, and people graph useful on reload with durable product objects.

3. Trust plane and operator surface
   - Complete Milestone 4 next.
   - Approvals, evidence, and operator/admin views must read like a customer-safe control plane.

4. Activation compression
   - Complete Milestone 5 after the core workflow is real.
   - New workspaces must reach memo, queue, draft, follow-up, and trust receipt without channel-first friction.

5. Paying-customer and QA finish
   - Complete Milestones 6 and 7 last.
   - Commercial posture, reliability, release checks, and E2E proof must line up as one honest product story.

## Flagship release rule

Executive Assistant is not flagship-grade just because:

- `MILESTONE.json` is green
- release asset verification is green
- the landing surface looks polished

It is flagship-grade only when:

- `EA_FLAGSHIP_TRUTH_PLANE.md` and `EA_FLAGSHIP_RELEASE_GATE.json` are green
- the core workspace runs on durable product objects
- one real executive-office loop is faster and safer with the product than without it
- trust, approval, evidence, and handoff are legible in product terms
- activation, release, and support proof tell the same story

## Fleet notes

- Treat `EXECUTIVE_ASSISTANT_MILESTONE_DEV_GUIDE.md` as the broad canon.
- Treat `EA_FLAGSHIP_TRUTH_PLANE.md` as the release oracle for EA-specific flagship claims.
- Treat this file as the closeout order.
- Any “done” claim for Executive Assistant must cite both this file and `PRODUCT_RELEASE_CHECKLIST.md`, plus the EA flagship truth plane.
