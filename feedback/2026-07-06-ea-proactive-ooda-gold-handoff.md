# EA Proactive OODA Gold Handoff

Date: 2026-07-06
Repo: `/docker/EA`
Workspace: `/docker/EA/ea`
Head observed: `4496e6a1`

## Executive summary

The important split is now explicit:

- the followthrough and dedupe code path is implemented and covered
- the published live receipts have not yet been brought forward to that new proof floor

Do not hand the next Codex the older story that gold is already sitting at `ready_for_approval_outcome_capture`. That was a prior verified slice. It is not the currently published runtime state.

## What landed

### Gold acceptance now understands duplicate-suppressed followthrough

File:

- `scripts/materialize_proactive_ooda_gold_acceptance.py`

Change:

- added `DEFAULT_OPERATOR_ACTION_REQUIRED_DEDUPE_PROOF`
- added dedupe-proof loading and parsing
- operator action-required digest evidence can now keep `approval_followthrough_prompt_sent = true` when the current digest suppresses as a duplicate and a prior sent digest already covered the current action set

### Gold verifier accepts dedupe-covered followthrough only with explicit proof

File:

- `scripts/verify_proactive_ooda_gold_acceptance.py`

Change:

- `approval_followthrough_notification` now passes under `notification_status = suppressed_duplicate` only when:
  - prior-send coverage is explicit
  - dedupe proof status is `pass`
  - current actions are covered by the prior send
  - the dedupe state still has message ids

### Runner followthrough now owns digest send, dedupe proof, and gold refresh

File:

- `scripts/run_proactive_ooda.py`

Change:

- `--armed-send` now actually flows through to the action-required digest builder
- followthrough now materializes `ea_operator_action_required_dedupe_proof.generated.json` when the digest suppresses as a duplicate
- followthrough refreshes gold acceptance after digest send or duplicate suppression

## Focused proof that passed

Passed:

- `pytest -q tests/test_proactive_ooda_gold_acceptance_materializer.py -k 'dedupe or falls_back_to_live_runtime_artifacts'`
- `pytest -q tests/test_proactive_ooda_gold_acceptance_verifier.py -k 'dedupe_covered_approval_followthrough_prompt or accepts_valid_receipt'`
- `pytest -q tests/test_proactive_ooda_env_loading.py -k 'followthrough_arms_digest_send_and_refreshes_gold_acceptance or followthrough_materializes_dedupe_proof_when_digest_is_suppressed_duplicate or materializes_followthrough_artifacts_with_default_published_paths'`

## Current published receipt truth

### Operator status

File:

- `/docker/EA/.codex-studio/published/ea_proactive_ooda_operator_status.generated.json`

Current fields:

- `generated_at = 2026-07-06T05:33:52Z`
- `status = ready_with_recovery_action`
- `reason = source_health_google_workspace:google_oauth_invalid_grant`
- `source_coverage.status = ready`
- `provider_cost_pressure.checked = false`
- `approval_capture.checked = false`

Interpretation:

- this receipt is partially refreshed and not strong enough to carry gold acceptance forward

### Gold acceptance

File:

- `/docker/EA/.codex-studio/published/ea_proactive_ooda_gold_acceptance.generated.json`

Current fields:

- `generated_at = 2026-07-06T05:34:39Z`
- `status = blocked_operator_runtime_posture`
- `next_action = repair_proactive_operator_runtime_posture`
- `approval_followthrough.notification_status = ready_to_send`
- `approval_followthrough.approval_followthrough_prompt_sent = false`
- `approval_outcome.status = stale_for_current_packet`

Interpretation:

- the published gold receipt is currently blocked before approval-outcome capture

### Goal posture

File:

- `/docker/EA/.codex-studio/published/ea_continuous_improvement_goal_posture.generated.json`

Current fields:

- `generated_at = 2026-07-06T05:23:51Z`
- `status = active_with_blockers`
- `next_action_key = proactive_ooda_packet_acceptance`

Interpretation:

- posture still points at the proactive approval outcome as the notification head
- it is older than the current gold and digest receipts

### Action-required digest

File:

- `/docker/EA/.codex-studio/published/ea_operator_action_required_digest.generated.json`

Current fields:

- `generated_at = 2026-07-06T05:34:48Z`
- `status = ready_to_send`
- `notification_status = ready_to_send`
- `notification_action_keys = ["proactive_ooda_packet_acceptance"]`
- `send_requested = false`
- `send_attempted = false`

Interpretation:

- the current proactive approval followthrough has not been sent yet in the published state

### Existing dedupe proof

File:

- `/docker/EA/.codex-studio/published/ea_operator_action_required_dedupe_proof.generated.json`

Current fields:

- `status = pass`
- `suppressed_duplicate_expected = true`
- `current_actions_covered_by_prior_state = true`
- `state.message_id_count = 1`

Critical caveat:

- the published dedupe proof does not cover `proactive_ooda_packet_acceptance`
- it is stale for the current proactive approval followthrough

## Live verifier state

This currently fails:

- `python3 scripts/verify_proactive_ooda_gold_acceptance.py --pretty`

Current issues:

- `receipt is stale relative to current source fingerprint`
- `linked operator_status is stale relative to gold receipt source fingerprint`

## Next move

The next Codex should do live refresh work, not more speculative patching:

1. rebuild operator status with the real probes enabled
2. run proactive followthrough with `--armed-send`
3. if the digest suppresses, materialize a fresh dedupe proof for the current action set
4. refresh gold acceptance after that digest outcome
5. refresh goal posture and digest
6. re-run the verifiers

## Read This To The Next Codex

The transfer line is simple:

- code path green
- focused tests green
- published receipts stale/misaligned
- live proactive digest still unsent for the current approval packet
- existing dedupe proof is not valid for the current proactive item
- next job is a clean live receipt refresh
