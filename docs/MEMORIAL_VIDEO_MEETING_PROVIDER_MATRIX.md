# Memorial Video Meeting Provider Matrix

## Answer first

For a real `Video Call mit Manfred` product surface:

- `VidBoard` is **not** the best primary runtime lane.
- The current captcha/login posture makes it an **ongoing operational risk**, not just a one-time setup annoyance.
- The stronger live-meeting candidates are:
  - `Tavus`
  - `D-ID`
- The best owned-LTD backup candidate is:
  - `Nonverbia`
- `VidBoard` should currently be treated as:
  - `batch/special-clip lane`

## Why

`Tavus` and `D-ID` both document real-time avatar conversations over WebRTC with meeting/session flows. That is much closer to the product you asked for than a batch avatar generator with fragile browser login.

`VidBoard` may still be useful for a wow-effect clip, but its current local posture is not good enough for the main lane.

## VidBoard captcha question

Current EA conclusion:

- this is **not** safely treated as a one-time hurdle
- it behaves like an auth/session gate
- if the runtime depends on logging in again later, the blocker can return

So for ongoing operation, the captcha risk remains live until a durable non-captcha integration path is proven.

## Sources used

- Tavus CVI overview:
  - https://docs.tavus.io/sections/conversational-video-interface
- Tavus conversation overview:
  - https://docs.tavus.io/sections/conversational-video-interface/conversation/overview
- Tavus conversation component:
  - https://docs.tavus.io/sections/conversational-video-interface/component-library/blocks
- D-ID realtime overview:
  - https://docs.d-id.com/docs/realtime-overview
- HeyGen docs:
  - https://docs.heygen.com/
  - https://docs.heygen.com/reference/heygen-interactive-avatar-realtime-api

## Repo artifact

Generate the current matrix with:

```bash
cd /docker/EA
python3 scripts/compare_memorial_video_meeting_providers.py
```

Default output:

- `/docker/fleet/state/chummer6/avatar_presenter_provider/memorial_video_meeting_provider_matrix.generated.json`
