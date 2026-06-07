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

## Required proof

Before a provider can become `VERIFIED_PROVIDER`, capture:

- provider login/account receipt
- commercial-use terms receipt
- watermark-free export receipt
- lip-sync quality review
- viseme / mouth-shape quality review
- memorial-source-data boundary receipt

## Current truth

As of the current repo state, both supported providers remain unverified and must fall back to storyboard/static motion.
