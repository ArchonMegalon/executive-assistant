# Memorial Avatar Provider Verification Runbook

## Purpose

Verify a named avatar-presenter provider without overstating readiness.

The runner:

- accepts a specific provider name
- emits a proof JSON
- returns `VERIFIED_PROVIDER` only when all required proof is real
- otherwise fails closed to `READY_VIA_FALLBACK` or `NOT_READY`

## Current supported providers

- `vidboard`
- `nonverbia`

## BrowserAct scaffold

Use the repo template at:

```text
/docker/EA/browseract_templates/vidboard_workspace_reader.workflow.json
```

This is the starting point for the authenticated VidBoard workspace read. It is not itself proof of production readiness; it only scaffolds the login and workspace extraction pass.

For a local capture + receipt-stub pass, use:

```bash
cd /docker/EA
python3 scripts/capture_vidboard_provider_receipts.py \
  --login-email "$VIDBOARD_LOGIN_EMAIL" \
  --login-password "$VIDBOARD_LOGIN_PASSWORD"
```

That command writes:

- `/docker/fleet/state/chummer6/avatar_presenter_provider/vidboard_workspace_capture.generated.json`
- `/docker/fleet/state/chummer6/avatar_presenter_provider/receipts/vidboard_*.json`
- `/docker/fleet/state/chummer6/avatar_presenter_provider/vidboard_operator_handoff.generated.json` when the capture fails or is blocked

It only auto-verifies `login_capture` when an authenticated workspace snapshot is actually detected. All other receipt files remain manual review stubs until a human confirms the proof.

Every generated receipt now carries:

- `capture_path`
- `capture_file_sha256`
- `source_capture_authenticated`

Manual review receipts also require these operator fields before the verifier will trust them:

- `reviewed_by`
- `reviewed_at`
- `evidence_ref`

## Operator handoff packet

When the capture runner exits non-zero, it now writes an operator handoff packet with:

- `failure_code`
- `recommended_action`
- `resume_command`
- `capture_path`
- `receipt_dir`
- preview artifact pointers such as `screenshot_path` and `html_path`

Use that file as the single resume surface for captcha/login blocks instead of reconstructing the failed attempt manually.

## Run

```bash
cd /docker/EA
python3 scripts/verify_avatar_presenter_provider.py --provider vidboard --allow-fallback
python3 scripts/verify_avatar_presenter_provider.py --provider nonverbia --allow-fallback
```

Outputs land under:

```text
/docker/fleet/state/chummer6/avatar_presenter_provider/
```

To consume real proof receipts, place receipt JSON files under:

```text
/docker/fleet/state/chummer6/avatar_presenter_provider/receipts/
```

Then rerun:

```bash
python3 scripts/verify_avatar_presenter_provider.py \
  --provider vidboard \
  --receipt-dir /docker/fleet/state/chummer6/avatar_presenter_provider/receipts
```

## Required proof

Before a provider can become `VERIFIED_PROVIDER`, capture:

- provider login/account receipt
- commercial-use terms receipt
- watermark-free export receipt
- lip-sync quality review
- viseme / mouth-shape quality review
- memorial-source-data boundary receipt

## VidBoard receipt contract

Each receipt should be a JSON file with this shape:

```json
{
  "provider_key": "vidboard",
  "receipt_type": "commercial_use_terms_receipt",
  "verified": true,
  "captured_at": "2026-06-07T12:00:00Z",
  "notes": "Commercial use allowed on exported talking-avatar clips.",
  "source_capture_authenticated": true,
  "capture_path": "/docker/fleet/state/chummer6/avatar_presenter_provider/vidboard_workspace_capture.generated.json",
  "capture_file_sha256": "abc123...",
  "reviewed_by": "operator-1",
  "reviewed_at": "2026-06-07T12:10:00Z",
  "evidence_ref": "https://evidence.example/vidboard/commercial-use"
}
```

Recognized `receipt_type` values:

- `login_capture`
- `commercial_use_terms_receipt`
- `watermark_export_receipt`
- `lip_sync_review_receipt`
- `viseme_quality_receipt`
- `privacy_terms_receipt`
- `source_data_boundary_receipt`

`VERIFIED_PROVIDER` is only allowed when:

- the login capture is `verified: true`
- the linked capture file still exists
- the capture file hash matches `capture_file_sha256`
- the linked capture proves an authenticated workspace snapshot
- every manual receipt is `verified: true`
- every manual receipt includes `reviewed_by`, `reviewed_at`, and `evidence_ref`

## Current truth

As of the current repo state, both supported providers remain unverified and must fall back to storyboard/static motion.
