# Design petition: WorkLLM fleet sidecar

Petition status: `proposed`

Owner requested: `chummer6-design`

Implementing repo: `executive-assistant`

## Missing seam

The mirrored external-tools canon allows bounded research/evaluation and
operator workbenches but does not name WorkLLM or define a reusable contract for
a multi-model organization-memory workbench used by Fleet.

## Requested canonical decision

Approve WorkLLM as:

- primary classification: Class D research/evaluation
- optional secondary classification: Class C3 operator process drafting
- system-of-record boundary: projection and candidate output only
- initial workspace integration tier: Tier 4
- initial route posture: verified manual candidate workbench, disabled between
  bounded operator runs

Explicitly reject:

- Class A runtime promotion based only on the commercial plan
- direct repository, queue, release, approval, or publication authority
- organization-memory authority
- unattended browser automation as a production machine contract
- model-route promotion without model provenance and usage telemetry

## Proposed contracts

- `executive_assistant.workllm_task_packet.v1`
- `executive_assistant.workllm_run_receipt.v1`

Both contracts are implemented locally as downstream runtime policy. Canon
should eventually define the vendor-neutral capability contract so EA does not
become the cross-repo product authority.

## Evidence required for acceptance

- authenticated workspace and plan receipt
- provider security, retention, deletion, and subprocessor review
- API/auth/webhook/idempotency evidence, if machine use is proposed
- model-provenance and credit-telemetry evidence
- a 20-run manual canary and a separate API canary if applicable
- verified kill switch, quota stop, redaction, review, and rollback behavior

## Current local posture

EA records ownership and credentials without exposing secrets and implements
fail-closed packet, quota, receipt, and review contracts. Authenticated Tier 4
account proof and a twenty-run public synthetic manual canary completed on
`2026-07-28`; all results remained human-reviewed candidates. The durable
rollback control is engaged and all lanes are disabled after the run. No
machine API, internal-data, organization-memory, autonomous runtime, or
canonical promotion is claimed by this petition.
