# Memorial Live Avatar Integration Plan

## Product decision

The public Manfred surface should evolve like this:

1. keep the current minimal memorial landing
2. keep the existing voice memorial as the safe fallback
3. upgrade the `Video Call mit Manfred Hoza` CTA into a real live avatar session
4. use:
   - `Tavus` first
   - `D-ID` second
   - `Nonverbia` only as owned-LTD backup
   - `VidBoard` only for special pre-rendered clips

## UX rules

- no camera prompt on page load
- no camera prompt before the user explicitly chooses video call
- avatar should appear before asking for the user camera whenever possible
- `Ohne Kamera fortfahren` must remain valid
- if live avatar bootstrap fails, the experience must fall back to portrait + voice, not to a dead UI

## Runtime shape

Server-owned truth:

- memorial guardrails
- provider selection
- session creation
- failure classification
- fallback decision

Provider-owned runtime:

- WebRTC/media session
- avatar transport
- join/reconnect media state

## Required new API surface

- `/memorials/{slug}/video-meeting/session`
- `/memorials/{slug}/video-meeting/status`

## Next implementation slice

Build the provider-neutral bootstrap endpoint first.

That is the clean seam where the current memorial page can ask:

- `give me a live video meeting session if one is available`
- otherwise `tell me to stay on portrait + voice fallback`

## Generated artifact

```bash
cd "$EA_REPO_ROOT"
python3 scripts/plan_memorial_live_avatar_integration.py
```

Default output:

- `.codex-studio/published/avatar_presenter_provider/memorial_live_avatar_integration_plan.generated.json`
