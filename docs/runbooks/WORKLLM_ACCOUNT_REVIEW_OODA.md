# WorkLLM account-review OODA runbook

Artifact type: agent-reusable governed browser workflow.

This is not unattended automation. Every element operation must use a fresh
browser state, identify the target by visible meaning, and use only the current
state index.

## Observe

- target: `https://girschele-workspace.workllm.io`
- expected work type: `account_review`
- expected outcome: redacted account/capability evidence only
- credential source: protected EA local environment
- allowed data: login credentials for this tenant only
- forbidden data: repository content, documents, prompts, Gmail, Calendar,
  people memory, customer data, private campaigns, memorial data, and secrets

## Orient

- verify the visible account context before inspecting tenant capabilities
- hash the visible account identifier; do not store the raw value
- treat commercial Tier 4 as a claim until the authenticated tenant shows it
- observe controls without changing settings
- do not create agents, threads, memories, integrations, API credentials,
  webhooks, users, roles, or documents
- do not start a model run during account verification

## Decide

Success requires enough visible evidence to populate
`config/workllm_account_review.example.json`:

1. authenticated tenant identity and account match
2. plan/tier, user allocation, and current/monthly credit figures
3. chat, deep-research, document, multimedia, memory, and agent surfaces
4. RBAC, audit-log, and usage-reporting surfaces
5. export, deletion, retention, and organization-memory controls
6. developer/API, service-auth, webhook, usage-endpoint, idempotency, and
   model-identity observations
7. final URL plus protected paths and hashes for useful screenshots

At least one screenshot artifact is mandatory. Capture it only after leaving
the credential form, store it in protected runtime storage with mode `0600`,
and record its path and SHA-256 digest in `screenshot_artifacts`. The
materializer verifies the file itself rather than trusting a supplied hash.

Stop immediately on:

- account mismatch
- MFA, CAPTCHA, device verification, or other human challenge
- any screen that requires a setting change to reveal information
- any request to upload data or create content
- any security, billing, purchase, invite, send, or publish boundary

## Act

For each operation:

1. run `state`
2. identify the intended control by accessible name and visible page context
3. use the current index once
4. wait for stability
5. run `state` again before another element operation
6. capture only non-secret visible facts or a protected screenshot artifact

Recommended read-only route:

1. sign-in surface
2. workspace/home surface
3. account or workspace-plan surface
4. usage or credits surface
5. member/role surface
6. audit-log surface
7. data/privacy/retention surface
8. model selector or model catalogue surface
9. agents surface
10. integrations/developer/API surface

If a recommended surface is absent, record `false`; do not infer capability
from marketing or navigation labels. Missing provider admin controls do not
invalidate the public-only manual workbench by themselves; they keep
`internal_nonsecret`, uploads, organization memory, and unattended routing
disabled.

## Receipt

Write redacted evidence matching
`executive_assistant.workllm_browser_account_review.v1`, then run:

```bash
.venv/bin/python scripts/materialize_workllm_account_verification.py \
  --evidence /protected/path/workllm-account-review.json
```

The validator must pass before account-verification flags or a manual canary
are considered.

The browser receipt must report:

- site and account-reference hash
- authenticated/account-match booleans
- requested and completed read-only actions
- plan and capability observations
- final review URL
- stop condition and blockers
- empty irreversible-action list
- `data_uploaded=false`
- protected screenshot artifact paths and hashes, never screenshots containing
  credentials

For each later canary run, also hash a screenshot or browser-state artifact
that visibly contains the matching WorkLLM output surface and store that
digest as `provider_output_surface_sha256` in the browser run receipt.

## Notification policy

`action_required_only`

Notify the operator only for browser choice, MFA/challenge handoff, account
mismatch, an irreversible boundary, or completed account-review evidence.
