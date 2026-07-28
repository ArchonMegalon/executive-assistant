# WorkLLM manual canary

Status: completed on `2026-07-28`; fail-closed controls restored.

This runbook operates the twenty public synthetic cases in
`config/workllm_manual_canary_corpus.json`. Preparation does not contact
WorkLLM, reserve credits, or authorize a submission.

The first governed run completed `20/20` provider-observed cases with full
schema, safety, and human-review coverage. Every result remains a quarantined
candidate. The final evaluator recorded `80` conservatively charged local
credits, an intact `87`-event audit chain, and
`promotion_eligible_candidate=true` with
`canonical_promotion_authority=false`. The durable rollback control and local
kill switch are engaged; manual, internal, runtime, and API execution are
disabled.

## Preconditions

- A verified account receipt exists at
  `ea/_completion/workllm/WORKLLM_ACCOUNT_VERIFICATION.generated.json`.
- `.env` is mode `0600`.
- `EA_WORKLLM_ACCOUNT_VERIFIED=1` and
  `EA_WORKLLM_MANUAL_LANE_ENABLED=1` are set only for the bounded manual run.
- `EA_WORKLLM_INTERNAL_NONSECRET_ENABLED=0` remains set: this canary is public.
- `EA_WORKLLM_KILL_SWITCH=0` is a deliberate temporary operator decision.
- Runtime and API flags remain `0`.
- The browser profile is authenticated to
  `girschele-workspace.workllm.io` and organization memory, uploads, web
  search, repository access, and external actions remain off.

## Prepare

```bash
./scripts/prepare_workllm_manual_canary.py
```

The generated plan contains exactly twenty source-bound packets and a total
maximum exposure of 136 credits. Its initial state is
`prepared_not_authorized`.

## Operate one case

Authorize and reserve the case ceiling:

```bash
./scripts/operate_workllm_manual_canary.py authorize \
  --case-id 01 \
  --actor-ref operator-reference
```

Submit only the plan's `operator_payload` through the governed browser. The
payload contains the minimized synthetic context, prompt, requested model
count, and exact output schema bound into the local task packet. Do not omit or
rewrite the schema, upload a file, or enable provider memory. Save these
mode-`0600` artifacts at the exact paths named in the plan:

- captured provider output
- redacted browser-surface receipt
- screenshot or browser-state artifact visibly proving the matching output

The browser receipt must match
`config/workllm_browser_run_receipt.example.json`. Record model labels and
credits only when they are visible on the provider surface. When WorkLLM
reports fractional credits but the local ledger requires an integer, preserve
the exact visible decimal in the browser receipt and charge its mathematical
ceiling locally so quota accounting never understates provider usage.

Capture the bounded result:

```bash
./scripts/operate_workllm_manual_canary.py capture \
  --case-id 01 \
  --actor-ref operator-reference \
  --provider-output /exact/plan/provider_output.txt \
  --provider-surface-receipt /exact/plan/provider_surface_receipt.json \
  --provider-output-surface-artifact /exact/plan/provider_output_surface.png \
  --observed-model observed-model-label \
  --credits-consumed 1
```

After independent schema, safety, and human review:

```bash
./scripts/operate_workllm_manual_canary.py review \
  --case-id 01 \
  --actor-ref reviewer-reference \
  --decision accepted_candidate \
  --schema-status passed \
  --safety-status passed
```

Repeat for all twenty cases. A rejected, unreviewed, model-unidentified,
credit-unbound, or artifact-unbound result cannot qualify.

## Cancel or stop

Release an unused reservation:

```bash
./scripts/operate_workllm_manual_canary.py cancel \
  --case-id 01 \
  --actor-ref operator-reference \
  --reason "Unused reservation cancelled."
```

Engage the durable kill switch:

```bash
./scripts/operate_workllm_manual_canary.py rollback \
  --actor-ref operator-reference \
  --reason "Provider or evidence anomaly."
```

Rollback writes a protected control override checked by already-running
sidecar objects. Removing that override is a separate deliberate recovery
decision.

## Finalize

```bash
./scripts/operate_workllm_manual_canary.py finalize
```

Finalization re-opens every protected account, packet, result, browser,
credit-ledger, and audit-ledger artifact. Each run must have the ordered
prepare, authorize, capture, and review lifecycle, a consumed reservation, and
an audit receipt hash bound to the reviewed result.

The resulting verdict is only a manual-lane promotion candidate. It grants no
repository, routing, approval, publication, external-send, or canonical-memory
authority.

After the bounded run, restore the fail-closed flags:

```text
EA_WORKLLM_KILL_SWITCH=1
EA_WORKLLM_MANUAL_LANE_ENABLED=0
EA_WORKLLM_INTERNAL_NONSECRET_ENABLED=0
WORKLLM_RUNTIME_ENABLED=0
EA_WORKLLM_API_LANE_ENABLED=0
```
