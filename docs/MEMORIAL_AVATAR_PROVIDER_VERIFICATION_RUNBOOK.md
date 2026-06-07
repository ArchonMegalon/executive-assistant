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
  "notes": "Commercial use allowed on exported talking-avatar clips."
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

`VERIFIED_PROVIDER` is only allowed when the login capture is present and all required proof receipts are `verified: true`.

## Current truth

As of the current repo state, both supported providers remain unverified and must fall back to storyboard/static motion.
