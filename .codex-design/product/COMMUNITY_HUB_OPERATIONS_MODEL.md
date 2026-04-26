# Community Hub Operations Model

## Purpose

Community Hub is not only a feature set. It is an operations model for running open tables, scheduling, approvals, closeout, and community trust.

## Core rule

> Hub owns run truth. NextStep runs SOPs. Teable shows queues. ApproveThis handles external approvals. Emailit and Signitic close the loop.

## Weekly operating questions

- Who reviews open-run applications?
- Who schedules GM clinics?
- Who reviews intel?
- Who closes resolution reports?
- Who approves newsreels?
- Who reviews seasonal honors and abuse reports?
- Who resolves roster or consent disputes?
- Who confirms voter or participant closeout happened?

## Operating stack

```yaml
community_hub_ops_stack:
  truth_owner: chummer6-hub
  process_runner: NextStep
  admin_projection: Teable
  external_approval: ApproveThis
  scheduling: Lunacal
  intake:
    - Deftform
    - FacePop
    - ProductLift
  delivery:
    - Emailit
    - Signitic
  media:
    - vidBoard
    - MarkupGo
    - PeekShot
    - Taja
```

## SOP families

- open-run publication
- application review
- roster lock
- scheduling and meeting handoff
- session-zero/table-contract closeout
- resolution report review
- world-tick candidate escalation
- seasonal honors review
- abuse or dispute escalation
- participant closeout

## Boundary

Operational convenience must not override:

- GM authority
- roster truth
- table-contract consent
- run resolution review
- public-safe visibility
- support and abuse escalation policy
