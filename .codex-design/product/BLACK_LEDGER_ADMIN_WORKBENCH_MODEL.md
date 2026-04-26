# BLACK LEDGER Admin Workbench Model

## Purpose

This file defines the operator-facing BLACK LEDGER control room.

The workbench is powered by first-party Hub state and may be projected into Teable for curation, triage, assignment, and review. It does not make Teable the BLACK LEDGER database.

## Core rule

> Hub owns world truth. Teable helps operators handle the queue. AdminIntent is the only write path back.

## First app: Seattle Tick Control Room

Initial tabs:

- pending intel
- faction moves
- job seeds
- GM adoption
- scheduled runs
- resolution reports
- newsreel candidates
- seasonal honors
- Signitic campaigns
- Emailit digests

## Workbench objects

```yaml
black_ledger_admin_workbench:
  canonical_owner: chummer6-hub
  projection_tool: Teable
  process_tool: NextStep
  external_approval_tool: ApproveThis
  passive_campaign_tool: Signitic
  outbound_delivery_tool: Emailit
  artifact_tools:
    - vidBoard
    - MarkupGo
    - PeekShot
    - Taja
  canonical_objects:
    - WorldFrame
    - District
    - DistrictPressure
    - Faction
    - FactionSeat
    - FactionResourcePool
    - OperationIntent
    - IntelReport
    - IntelReviewDecision
    - JobSeed
    - JobPacket
    - OpenRun
    - RunApplication
    - ResolutionReport
    - WorldTick
    - NewsReelCandidate
    - FactionNewsletter
    - ReputationEvent
    - SeasonalHonor
    - MediaBrief
    - SigniticCampaign
    - EmailDigest
```

## Operating loop

```text
Intel, run resolution, faction operation, or product signal arrives
  -> Hub stores pending canonical object or candidate
  -> Teable projection refreshes the operator workbench
  -> NextStep runs the relevant SOP
  -> operator edits assignment, proposed status, review note, or publication class
  -> Teable submits AdminIntent to Hub
  -> Hub validates authority, version, visibility, and invariants
  -> Hub writes canonical state
  -> Media Factory renders approved artifacts
  -> Signitic, Emailit, ProductLift, and public pages amplify approved outputs
```

## Approval posture

Use:

- Hub-owned approval UI for first-party operators
- NextStep for process discipline
- ApproveThis for external approvers who should not get full Hub admin accounts
- Teable only for projection, note, assignment, and intent entry

## Guardrails

The workbench must prevent:

- private runner consequences leaking into public ticker rows
- faction secrets appearing in public campaign tools
- raw intel becoming canon without review
- Signitic banners carrying personalized truth
- Emailit digests claiming unpublished ticks
- NewsReel assets shipping without publication approval
- ProductLift reactions becoming world truth

## Success criteria

The workbench is working when operators can review and close a world tick without using ad hoc spreadsheets, every accepted edit has an AdminIntentReceipt, public artifacts match Hub publication truth, and disabling Teable leaves Hub canonical state intact.
