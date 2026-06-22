# EA Cinematic Narration and Promo Pipeline

## Status

This is an EA-local implementation packet, not Chummer product canon.

It exists to make the audiobook, scene-audio, Manfred, and promo-video lanes buildable without letting EA or a media provider become the source of product, campaign, memorial, or publication truth.

Canonical product truth remains in the mirrored product design files and Chummer-owned manifests. EA may render, audition, verify, and receipt downstream media only from approved source packets.

## Goal

Produce audio and promo media that feels fitted to the current scene while remaining continuous, cinematic, and governed.

The narration must not be a hard scene-to-clip binding. It should behave like a narrator who understands the current scene, remembers the previous arc, and shifts tone smoothly as the situation changes.

## Core Model

The runtime should maintain three state layers:

1. Source truth
   - approved EPUB chapter text
   - approved origin-dossier story text
   - approved campaign, mission, runsite, recap, or memorial packet
   - approved public promo script or storyboard packet

2. Rolling narration state
   - narrator identity and selected voice
   - language, topic, genre, and audience posture
   - recent narration summary
   - unresolved motifs and callback phrases
   - intensity curve, pacing target, and silence budget
   - last rendered segment hash and loudness receipt

3. Current scene signal
   - current location or context label
   - present characters or subject focus
   - mood, stakes, pressure, and recent event deltas
   - user-visible spoiler class
   - audience safety class
   - allowed source anchors

The scene signal conditions the next narration window. It does not replace the rolling narration state and it does not become canon.

## Pipeline

```text
Approved source packet
  -> language, topic, audience, and rights profiler
  -> narrator/voice audition or confirmed voice posture
  -> rolling narration state
  -> scene signal conditioner
  -> cinematic arc planner
  -> short window script generator
  -> provider render candidate
  -> audio quality gates
  -> continuity gates
  -> assembly or streaming append
  -> sanitized receipt
```

For EPUB audiobooks the assembly target is chaptered M4B with embedded chapter metadata and cover art. The EA-local proof includes an M4B structure probe that materializes a tiny covered, chaptered M4B and verifies the result with `ffprobe` before the receipt can pass.

For live scene narration the assembly target is a rolling audio stream or cached segment chain with crossfades.

For promo videos the assembly target is `fallback_static_storyboard` until a named video provider has real provider proof, captions, safety receipt, and public route proof.

## Voice Audition

When the source is an EPUB or long-form text packet, EA should:

- detect language and topic before selecting a voice;
- rank configured and generically discovered voices by language, topic tags, genre, dialogue ratio, and user blocklist;
- deprioritize voices that the operator has rejected, including Alice by default;
- render the first few sentences with the best three voices;
- send each sample with inline `Use this` and `Dismiss` controls;
- render the next three samples if the user dismisses the whole batch;
- store raw provider voice IDs only in private job-local state;
- expose only labels, tags, hashes, scores, and callback tokens in public job receipts.

## Ongoing Cinematic Narration

The cinematic planner should produce windows, not scene-bound clips.

Each window should target 8 to 20 seconds of narration and carry:

- `window_id`
- `source_anchor_ids`
- `scene_signal_digest`
- `previous_window_digest`
- `narrator_posture`
- `intensity_target`
- `tempo_target`
- `continuity_callbacks`
- `script_text`
- `expected_duration_seconds`

The next window may respond to a scene change, but it must also preserve continuity with the prior window. Abrupt voice, tense, language, or emotional changes require an explicit transition sentence or a fade boundary.

The planner should avoid:

- repeated summaries of the same event;
- overexplaining rules or product controls;
- stating hidden GM-only material on player-safe surfaces;
- turning atmosphere into tactical authority;
- inventing memorial memory or campaign canon;
- claiming a media provider as the truth source.

## Segment Chain Rendering

After a narration window is planned, EA should render it as an appendable segment instead of treating it as a finished scene clip.

The segment append contract should:

- call a provider render adapter only after the window has approved source anchors;
- keep the render adapter behind a callback or provider boundary;
- record the selected `window_digest`, `previous_window_digest`, and `previous_segment_digest`;
- hash the rendered audio artifact while exposing only the basename in receipts;
- preserve `audio_path_exposed=false` and `raw_provider_voice_id_exposed=false`;
- reject provider output that claims product, campaign, memorial, or scene truth;
- reject quiet-tail, trailing-silence, missing-speech-energy, clipped-ending, and duration-mismatch reports;
- advance rolling narration state only when the segment is ready;
- carry a planned crossfade for cached stream assembly.

The current implementation lives beside the planner in `app/services/cinematic_narration_pipeline.py` as `append_cinematic_narration_segment` and `build_cinematic_narration_segment_receipt`.

The local materialization proof lives in `scripts/materialize_cinematic_narration_segment_chain.py`. It can render a public-safe spoken segment chain with ffmpeg/flite into `narration-audio/` and write `narration_segments.generated.json`. This is a local speech fixture for review and continuity proof, not a verified external provider claim. `scripts/verify_cinematic_narration_segment_chain.py` checks audio hashes, segment continuity, quality blockers, sanitized file exposure, and provider-truth boundaries.

The standalone continuity proof lives in `scripts/materialize_cinematic_narration_continuity_demo.py`. It renders a three-scene proof chain outside the promo bundle and writes `cinematic_narration_continuity_demo.generated.json`. That packet demonstrates the intended design directly: approved source packet, rolling narration state, current scene signal, scene-conditioned windows, appendable segment audio, crossfade continuity, scene-fit checks, and stable narrator posture. `scripts/verify_cinematic_narration_continuity_demo.py` rejects scene-bound overclaims, provider-truth overclaims, broken previous-window or previous-segment continuity, missing scene fit, missing audio hashes, and raw path exposure.

The local fallback video proof lives in `scripts/materialize_ea_fallback_promo_video.py`. It renders the storyboard as static cinematic cards, combines those cards with the spoken narration segments, muxes `promo.vtt` captions when available, and writes `promo_fallback_video.generated.json`. It also extracts `poster.jpg` and `contact-sheet.jpg` review assets, records hashes, stores luma nonblank probes, and writes `watch.html` so reviewers can inspect the MP4, poster, captions, transcript, contact sheet, and receipt links without opening every artifact manually. This output uses `render_mode=local_ffmpeg_static_card_video`; it may prove a local review MP4 exists, but it must keep `provider_ready=false`, `verified_provider_claim_allowed=false`, `provider_output_truth_allowed=false`, `route_deployment_verified=false`, and `public_route_claim_allowed=false`.

The local review bundle proof lives in `scripts/materialize_ea_promo_review_bundle.py`. It runs the storyboard, narration-segment, standalone continuity-demo, and fallback-video materializers in order, then runs all lower verifiers plus the contract verifier and writes `promo_review_bundle.generated.json`. The bundle receipt is the operator handoff surface for local review: it lists the watch page, MP4, captions, poster, contact sheet, narration receipts, the continuity-demo receipt, hashes, render modes, and any verification issues. The verifier `scripts/verify_ea_promo_review_bundle.py` must fail if any lower verifier fails, if required files are missing or hash-mismatched, if the continuity-demo proof is missing or tampered, or if provider or route readiness is overclaimed.

The promo quality rubric lives in `scripts/materialize_ea_promo_quality_rubric.py` and `scripts/verify_ea_promo_quality_rubric.py`. It is the "make this actually good" gate for local fallback promo assets: it scores story arc clarity, distinct scene beats, rolling narration continuity, standalone continuity-demo readiness, caption reviewability, MP4 audio/video/captions, nonblank poster/contact sheet, watch-page wiring, public-safe source boundaries, and segment-chain audio continuity. A passing rubric can say `LOCAL_PROMO_QUALITY_PASS`, but it must still keep `not_provider_proof=true`, `not_public_route_proof=true`, `provider_ready=false`, `live_provider_runtime_verified=false`, and `route_deployment_verified=false`.

## Audio Quality Gates

Every rendered sample, segment, chapter, or promo narration track should pass these checks before it is treated as usable:

- target integrated loudness around -16 LUFS for spoken audio;
- true peak below -1.5 dBTP;
- no long unintended trailing silence;
- no clipped ending or swallowed final word;
- no near-silent final 1.5 seconds unless it is an intentional fade;
- speech energy present after provider conversion;
- language matches the source profile;
- voice matches selected user choice or approved narrator posture;
- segment duration is within the expected range;
- failure reason is operator-grade if the gate cannot pass.

The current EPUB path uses ffmpeg normalization and should keep adding tail and speech-energy checks as the next quality layer.
EA records a bounded WAV quality report for rendered samples and chapters. The report checks head/tail speech energy, quiet final-window RMS, and trailing silence without reading entire long audiobook chapters into memory. Public receipts expose only aggregate counts such as quiet-tail and trailing-silence issues, not raw audio paths.

## Promo Video Contract

Promo videos must follow provider-proof-first behavior.

The public-safe fallback state is:

```text
render_mode = fallback_static_storyboard
verdict = READY_VIA_FALLBACK
```

Only claim `VERIFIED_PROVIDER` when all of these are true:

- named provider account capability is verified;
- commercial-use and export behavior are recorded;
- generated candidate has safety scan proof;
- `promo.json` reports the honest render mode;
- `promo.vtt` exists and is valid `WEBVTT`;
- public route shows the same honest posture;
- human review approved the exact script, captions, and rendered artifact.

If any provider proof is missing, EA may still generate a high-quality storyboard, poster, captions, and receipt. It must not claim the provider is live.

Fallback promo materialization should also write a local HTML preview. The preview exists for human review of storyboard timing, caption copy, and ongoing narration continuity. It must show fallback posture, provider proof pending, and public deployment proof pending; it must not name or imply a verified provider. When the same artifact is served through the EA app route, the route may mark itself as an in-app fallback route, while still keeping external public deployment proof separate.

## Receipts

Every media job should write a sanitized receipt with:

- contract name;
- source packet digest;
- language and topic profile;
- rights basis;
- selected voice label or narrator posture;
- raw provider IDs exposed: false;
- raw private context allowed: false;
- render mode;
- quality gate results;
- continuity gate results;
- caption path for video;
- cover art embedded status for M4B;
- chapter metadata embedded status for M4B;
- public route or scoped playback route, when available;
- next action when blocked.

The receipt must not contain:

- provider API keys;
- Telegram file URLs;
- raw pCloud paths in public receipts;
- global Audiobookshelf tokens;
- raw provider voice IDs in public receipts;
- raw private memorial memory;
- sourcebook copied text;
- unapproved campaign spoilers.

## Implementation Slices

1. EPUB voice quality
   - voice audition batches;
   - Alice blocklist default;
   - ffmpeg loudness normalization;
   - M4B cover and chapter embedding.

2. Rolling narration state
   - state schema;
   - segment-chain receipts;
   - continuity callbacks;
   - tail and speech-energy gates.

The EA-local planner lives in `app/services/cinematic_narration_pipeline.py`. It builds one narration window at a time from an approved source packet, current scene signal, and previous rolling state. It fails closed when the source is not approved, marks each window as scene-conditioned but not scene-bound, and emits receipts that keep `scene_signal_is_canon=false`, `provider_output_truth_allowed=false`, and `ea_is_product_truth=false`.

3. Promo-video fallback rail
   - storyboard packet;
   - poster frame;
   - `promo.json`;
   - `promo.vtt`;
   - local `promo.html` review preview;
   - public route proof;
   - provider verification gate.

EA-local fallback artifacts can be materialized and verified with:

```bash
python3 scripts/materialize_ea_promo_video_fallback.py --faction-id ashline-circle --requested-provider Advertisemind
python3 scripts/verify_ea_promo_video_fallback.py --artifact-dir ../.codex-studio/published/ea_promo_video_fallback/ashline-circle
python3 scripts/materialize_cinematic_narration_segment_chain.py --artifact-dir ../.codex-studio/published/ea_promo_video_fallback/ashline-circle
python3 scripts/verify_cinematic_narration_segment_chain.py --artifact-dir ../.codex-studio/published/ea_promo_video_fallback/ashline-circle
python3 scripts/materialize_cinematic_narration_continuity_demo.py
python3 scripts/verify_cinematic_narration_continuity_demo.py
python3 scripts/materialize_ea_fallback_promo_video.py --artifact-dir ../.codex-studio/published/ea_promo_video_fallback/ashline-circle
python3 scripts/verify_ea_fallback_promo_video.py --artifact-dir ../.codex-studio/published/ea_promo_video_fallback/ashline-circle
python3 scripts/materialize_ea_promo_review_bundle.py --faction-id ashline-circle --requested-provider Advertisemind
python3 scripts/verify_ea_promo_review_bundle.py --artifact-dir ../.codex-studio/published/ea_promo_video_fallback/ashline-circle
python3 scripts/materialize_ea_promo_quality_rubric.py --artifact-dir ../.codex-studio/published/ea_promo_video_fallback/ashline-circle
python3 scripts/verify_ea_promo_quality_rubric.py --artifact-dir ../.codex-studio/published/ea_promo_video_fallback/ashline-circle
```

The materializer writes `promo.json`, `promo.vtt`, a local `promo.html` storyboard preview, a poster-frame storyboard packet, and a fallback receipt. The verifier rejects provider-ready, live-provider, preview-copy, or `VERIFIED_PROVIDER` overclaims unless a separate provider-proof lane has actually produced proof. Default artifacts are local fallback proof only; public route deployment and browser proof remain the next action.
The segment-chain materializer writes `narration_segments.generated.json` and spoken WAV segments under `narration-audio/`. Those artifacts can prove local continuity and audio hygiene, but they do not change `promo.json` into a provider-video or provider-audio claim.
The fallback-video materializer writes `promo-video/promo-fallback.mp4`, `promo-video/poster.jpg`, `promo-video/contact-sheet.jpg`, `promo-video/watch.html`, and a receipt. The verifier checks video streams, captions, asset hashes, nonblank visual probes, watch-page wiring, and provider/route boundary flags. That MP4 can be reviewed as a local fallback video, but it still does not prove a named provider, deployed public route, or product release claim.
The review-bundle materializer writes `promo_review_bundle.generated.json` after it has regenerated the full local artifact set, including `cinematic_narration_continuity_demo.generated.json`, and rerun all verifiers. That bundle is the single command output to hand to a reviewer.
The quality-rubric materializer writes `promo_quality_rubric.generated.json` after the bundle exists. That receipt is the local creative-quality gate; it proves the promo is reviewable and coherent, not that a named provider or deployed public route is verified.

## Active Evidence Bundle

When the audiobook, Manfred ChatLab, cinematic narration, and promo lanes need one current local proof packet, use:

```bash
python3 scripts/materialize_active_media_ltd_goal_bundle.py --pretty
python3 scripts/verify_active_media_ltd_goal_bundle.py --pretty
```

This writes `../.codex-studio/published/active_media_ltd_goal_bundle.generated.json`. The receipt aggregates the lower audiobook quality, M4B structure, ChatLab contract/preflight/route, Manfred realtime readiness, cinematic media, continuity-demo, promo-review, and promo-quality verifiers.

The bundle is allowed to say `ready_local_evidence` only. It is not allowed to claim goal completion, live ChatLab runtime, verified promo provider output, deployed public route, provider truth, product truth, memory truth, or gold readiness. It must keep the remaining external proofs visible until a human/operator can attach real provider, route, playback, and spoken-conversation evidence.

The `manfred_realtime_readiness` verifier turns the spoken-conversation posture into a local checklist. It can pass while the receipt says `blocked_realtime_prerequisites`, because the pass only means the blocker list is complete, redacted, and not overclaiming. The `manfred_spoken_conversation` posture still summarizes the existing memorial operator status so the active bundle can say, for example, "STT provider benchmark passes, but real captured STT or room-audio attestation still blocks premium speech" without turning that into completion.

4. Manfred premium speech
   - voice-first route evidence;
   - STT/TTS roundtrip receipts;
   - interruption and retry evidence;
   - difficult-memory guardrail preservation.

## Completion Bar

The lane is not complete until:

- audiobook voice choice happens before long-form rendering;
- selected voice is audible, stable, and not quiet at the end;
- M4B outputs carry chapter metadata and cover art;
- rolling narration can adapt to scene signals without resetting style every scene;
- promo videos have either verified provider proof or public-safe fallback storyboard proof;
- all public claims match the receipts.
