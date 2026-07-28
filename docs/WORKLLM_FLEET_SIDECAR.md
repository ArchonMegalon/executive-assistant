# WorkLLM fleet sidecar

Status: `candidate_only`

Workspace: `girschele-workspace.workllm.io`

Commercial posture: AppSumo Tier 4 / Pro, authenticated against the tenant on
`2026-07-28`, with `8,000` monthly AI credits and unlimited users observed.

Workspace integration posture: verified public-data manual workbench,
`candidate_only`, and currently fail-closed. The authenticated account review
and twenty-run provider canary passed, but the durable rollback control is
engaged and every execution lane is disabled after evidence capture.

Public deal-surface evidence checked on `2026-07-28`:

- source: `https://appsumo.com/products/workllm/`
- Tier 4 advertises `8,000` monthly AI credits and unlimited users
- the listing advertises more than 200 models, comparison of up to four
  models, chat, deep research, documents and multimedia, organization memory,
  agents, RBAC, audit logs, model/data controls, administration, and usage
  reporting

These are vendor/deal claims only. They do not prove that the provisioned
tenant exposes a feature, that a feature is safe to use, or that a machine API
exists.

The official public security and data pages were also checked on
`2026-07-28`. They advertise a dedicated tenant, encryption, RBAC, audit logs,
zero retention at the upstream LLM layer, no customer-data training, removable
knowledge sources, conversation deletion where supported, and account-deletion
requests. Those statements do not specify a workspace retention schedule and
do not prove that this Tier 4 tenant exposes the corresponding admin controls.

The support-document index links an OpenAPI file, but the linked file identifies
itself as the sample `OpenAPI Plant Store`, points to
`sandbox.mintlify.com`, and exposes plant-demo endpoints. It is not a WorkLLM
machine contract. No WorkLLM service authentication, model provenance, usage,
idempotency, or signed-webhook API contract was found in the public
documentation, so the API lane remains ineligible.

## Purpose

WorkLLM is a non-canonical multi-model research, critique, document-analysis,
and operator-drafting workbench for the Codex/EA fleet. It is not a Codex
worker, a repository agent, a production model router, or an organization
memory authority.

EA owns:

- task classification, minimization, redaction, prompt and source hashes
- credit authorization, kill switch, receipts, audit, and human review
- repository changes, provider routing, approvals, publication, and canonical
  memory

WorkLLM may:

- compare models over an approved source packet
- critique a design or candidate patch
- detect contradictions without resolving canon
- summarize supplied release evidence without granting release approval
- draft an SOP or operator checklist without executing it

WorkLLM may not:

- read a repository, `.env`, secret store, private memorial profile, raw
  Gmail/Calendar payload, people memory, customer PII, or private campaign data
- write a repository, send a message, publish, approve, or mutate canonical
  state
- become product, release, entitlement, decision, support, publication, model
  route, or organization-memory truth

## Architecture

```text
Fleet request
  -> EA WorkLLMTaskPacket builder
     -> data-class gate
     -> source-reference gate
     -> redaction/minimization
     -> prompt/source/request hashes
     -> per-task credit ceiling
  -> authorization gate
     -> kill switch
     -> monthly soft/hard credit limits
     -> manual or API proof gates
  -> governed WorkLLM operator/API boundary
  -> quarantined result
  -> local WorkLLMRunReceipt
  -> schema and safety validation
  -> human review
  -> candidate artifact only
```

The implementation lives in
`ea/app/services/workllm_sidecar.py`. It intentionally has no HTTP client and
no browser automation. Browser work follows the governed operator skill and is
recorded separately from the runtime contract.

## Data contract

`executive_assistant.workllm_task_packet.v1` contains:

- task and correlation identifiers
- approved lane and data classification
- minimized, redacted context
- source references and hashes
- prompt-template identity and prompt hash
- required output schema
- per-task credit limit
- an explicit no-authority envelope
- a canonical request hash

Only `public` and `internal_nonsecret` packets can be constructed. Initial
authorization is public-only: `internal_nonsecret` fails closed unless the
separate `EA_WORKLLM_INTERNAL_NONSECRET_ENABLED=1` gate is deliberately
released after stronger provider retention, deletion, and export evidence.
At least one source reference is required. Secret, credential, private-memory,
raw-mail, and traversal paths are rejected.

`executive_assistant.workllm_run_receipt.v1` contains:

- tenant, request, provider-job, and output hashes
- observed model labels, if the provider exposes them
- consumed credits, if visible
- source binding
- validation and human-review state
- export, deletion, and organization-memory observations
- an explicit no-authority envelope

The receipt never contains credentials, the raw provider job identifier, the
tenant URL, or the provider output itself.

## Credit posture

The provisional Tier 4 envelope is:

- monthly advertised capacity: `8000`
- soft limit: `6400`
- hard limit: `7200`
- maximum single task: `250`
- unallocated reserve above the hard limit: `800`

The soft limit warns. The hard limit fails closed. Auto-top-up is forbidden.
The account capacity is authenticated. During the bounded canary, the provider
usage report reached `66.942` cumulative credits while the local governance
ledger conservatively charged `80` integer credits by rounding each submitted
case or shared-batch observation up. Per-model burn remains observational and
does not relax any local quota.

## Persistent governance

The manual lane uses `ea/app/services/workllm_governance.py` for state that
must survive an operator process:

- `credit_ledger.json` reserves the full per-task ceiling before a browser
  handoff, consumes the observed amount after capture, releases cancelled
  reservations, rejects conflicting retries, and archives completed months
- `audit.jsonl` is an append-only hash chain covering packet staging,
  authorization, result capture, review, cancellation, and rollback
- every actor reference is hashed and every audit detail passes through the
  WorkLLM redactor
- task, output, provider-job, receipt, ledger, audit-head, and control-state
  hashes bind the evidence without storing credentials or raw provider output

All governance directories use mode `0700`; state and receipt files use mode
`0600`. A result cannot be captured without a matching active credit
reservation.

The operator sequence is:

1. prepare and stage a source-bound task packet
2. authorize the manual run and reserve its maximum credit exposure
3. submit only the prepared packet through the governed browser session
4. capture and redact the result, then consume observed credits
5. validate schema and safety
6. record a human review decision
7. evaluate the accumulated canary receipts without granting route authority

## Rollback

`GovernedWorkLLMManualLane.engage_rollback()` writes a protected local control
override and a rollback receipt. The override is checked on every submission,
including by an already-constructed sidecar object, so changing an environment
variable is not required to stop new work.

The control file can only force the kill switch on. It cannot release the kill
switch. Recovery requires deliberate removal of the local control file plus
review of these fail-closed environment values:

- `EA_WORKLLM_KILL_SWITCH=1`
- `EA_WORKLLM_MANUAL_LANE_ENABLED=0`
- `EA_WORKLLM_INTERNAL_NONSECRET_ENABLED=0`
- `WORKLLM_RUNTIME_ENABLED=0`
- `EA_WORKLLM_API_LANE_ENABLED=0`

The rollback receipt and audit head prove that the stop was engaged, but they
do not grant authority to restore or promote a route.

## Promotion states

### State 0: catalog only

- `EA_WORKLLM_KILL_SWITCH=1`
- all verification and execution flags are `0`
- provider registry entry is non-executable
- packet construction and local contract tests are allowed

### State 1: verified manual workbench

Requires:

- authenticated tenant identity and plan/capacity receipt
- honest RBAC, audit, usage, export/delete, retention, and
  organization-memory observations, including explicit `false` values when
  surfaces are absent
- an isolated or explicitly selected browser profile
- `EA_WORKLLM_ACCOUNT_VERIFIED=1`
- `EA_WORKLLM_MANUAL_LANE_ENABLED=1`
- `EA_WORKLLM_INTERNAL_NONSECRET_ENABLED=0`
- an intentionally released kill switch for a bounded run

State 1 is public-only. Every submission remains operator-reviewed and
receives a local receipt. Provider admin controls are recorded honestly but
their absence does not turn a public synthetic canary into an API or
internal-data lane.

The authenticated browser review is first captured as
`executive_assistant.workllm_browser_account_review.v1`. The redacted evidence
must include:

- an account-reference hash and an explicit tenant-account match
- the observed commercial tier, user allocation, and monthly credits
- observed chat, research, document, multimedia, memory, and agent surfaces
- observed RBAC, audit, usage, export, deletion, and retention controls
- an explicit API/auth/usage/webhook/idempotency/model observation matrix
- a final tenant URL plus protected screenshot artifact paths and hashes
- `data_uploaded=false` and an empty irreversible-action list

`scripts/materialize_workllm_account_verification.py` rejects raw email
addresses, credentials, account mismatches, uploads, or irreversible actions.
It also re-opens each mode-`0600` screenshot artifact and rejects missing,
symlinked, permissive, or digest-mismatched evidence. It may verify the manual
workbench while still keeping internal-nonsecret data, API, and organization
memory ineligible.

### State 2: bounded API challenger

Requires all State 1 evidence plus:

- genuine vendor API and authentication contract
- pinned or observable model provenance
- usage/credit telemetry
- idempotency and replay behavior
- retention/deletion controls
- signed webhook controls if workflows are enabled
- canary, timeout, retry, circuit-breaker, and rollback evidence

Only then may the API flags become true. WorkLLM remains a challenger route,
not a default.

The current public-docs verdict is
`NO_WORKLLM_MACHINE_CONTRACT_OBSERVED`; a Mintlify sample OpenAPI document is
explicitly insufficient evidence.

## Canary acceptance

The first promotion canary must contain at least 20 bounded runs and prove:

- 100 percent local task and run receipts
- zero forbidden data disclosures
- zero repository writes, sends, publications, approvals, or canonical writes
- at least 95 percent output-schema validity
- working credit stop and kill switch
- captured quality, latency, credit, and model-provenance observations
- review decisions for every candidate
- export/delete evidence before organization memory is permitted

Each real run binds two receipts:

- the local `executive_assistant.workllm_run_receipt.v1`
- a redacted `executive_assistant.workllm_browser_run_receipt.v1` proving the
  matching account, request hash, prepared-packet-only boundary, captured
  output, and empty irreversible-action list

The local run receipt stores the browser-surface receipt hash. Synthetic or
unverified results use `evidence_kind=synthetic_or_unverified` and cannot
satisfy the real-canary gate.

The browser receipt must also bind a `provider_output_surface_sha256` from a
local screenshot or captured browser-state artifact that visibly proves the
matching WorkLLM result surface. The raw artifact stays in protected runtime
storage. The explicit canary manifest carries its protected local path, and
the evaluator re-opens that file and verifies the digest. A self-asserted JSON
receipt or hash without the matching file is rejected.

`scripts/evaluate_workllm_manual_canary.py` accepts only an explicit manifest;
it does not discover receipts. It verifies all account, request, task-packet,
redacted-result, browser-artifact, and file hashes before applying the 20-run
evaluation. The same manifest names the protected audit and credit ledgers;
every qualifying run must have an ordered prepare/authorize/capture/review
audit lifecycle, a final-review receipt binding, and a matching consumed-credit
reservation.

Organization memory stays disabled until a separate projection contract proves
that its contents are approved, rebuildable, source-hashed, refreshable, and
deletable.

## Current verified posture

The authenticated browser review completed on `2026-07-28` through the
persistent no-proxy stealth profile. It matched the intended tenant and
observed AppSumo Tier 4, `8,000` monthly credits, unlimited users, usage
reporting, RBAC, export, and deletion controls. It did not observe an audit-log
surface or a workspace retention control. No data was uploaded and no
irreversible action was attempted.

The twenty-case public synthetic canary then completed with:

- `20/20` provider-observed, source-bound runs
- `20/20` schema and safety passes with completed human review
- `20/20` accepted as quarantined candidates
- explicit model and credit observations for every case
- `80` conservatively consumed local ledger credits
- an intact `87`-event audit chain, including the final rollback

The authoritative receipts are:

- `ea/_completion/workllm/WORKLLM_ACCOUNT_VERIFICATION.generated.json`
- `ea/_completion/workllm/WORKLLM_MANUAL_CANARY.generated.json`

The canary verdict is promotion-eligible only for the bounded manual candidate
workbench; `canonical_promotion_authority=false`. The provider did not prove a
machine API, service authentication, model-provenance endpoint, usage endpoint,
idempotency contract, retention control, or signed webhooks. Consequently the
API, runtime, internal-nonsecret, upload, organization-memory, and unattended
automation lanes remain ineligible.

After finalization, EA wrote a protected rollback receipt, engaged the durable
control-state kill switch, restored `EA_WORKLLM_KILL_SWITCH=1`, and disabled
the manual lane. A future manual batch requires a new deliberate, bounded
release and fresh review; the completed canary does not leave WorkLLM running.
