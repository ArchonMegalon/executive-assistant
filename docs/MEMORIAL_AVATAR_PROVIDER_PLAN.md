# Memorial Avatar Provider Plan

## Goal

Evaluate whether one of the owned LTDs can render a speaking avatar for Manfred with believable lip sync.

This repo now treats that as a bounded provider-verification problem, not as an assumed available feature.

## Current posture

The local verification source is:

- `scripts/avatar_presenter_provider_check.py`

It fails closed by default to:

- `fallback_static_storyboard`

until a provider proves all of the following:

- commercial use allowed
- watermark-free export
- privacy terms reviewed
- source memorial data allowed
- believable lip sync verified
- viseme / mouth-shape quality verified

## Current candidates

- `VidBoard.ai`
  Best current photoreal avatar candidate, but still unverified.
- `Nonverbia`
  Secondary presenter candidate, still unverified.
- `Mootion`
  Motion/video candidate, weaker for direct speaking-avatar use.
- `MagicFit`
  Better as B-roll/video scene support than primary avatar lane.
- `Unmixr AI`
  Audio only, useful as a voice companion lane.

## Verification order

1. `VidBoard.ai`
2. `Nonverbia`
3. `Mootion`
4. Optional `MagicFit` comparison for non-avatar motion support

## Required proof receipts

For any provider to become real:

- one local provider-verification packet
- one rendered sample using approved memorial-safe script
- one exported sample proving watermark status
- one lip-sync review receipt
- one privacy/source-data boundary receipt
- one fail-closed fallback statement if any gate is unproven

## Runtime posture

Even if a provider passes, the architecture stays:

1. text answer
2. approved TTS/audio generation
3. avatar render from still image/portrait plus audio
4. rendered video returned as asset output only

The avatar lane must never become canon, memory truth, or explain authority.
