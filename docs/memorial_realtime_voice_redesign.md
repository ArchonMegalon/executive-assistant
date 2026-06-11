# Memorial Realtime Voice Redesign

## Current State

The public memorial minimal client uses Gemini Live over EA's existing
`/memorials/{slug}/realtime` WebSocket.
The browser captures microphone samples through Web Audio, resamples them to
16 kHz signed PCM, and streams binary chunks immediately after
`user_audio_start`.
The backend opens a server-owned Gemini Live WebSocket with the configured
Google API key, sends the memorial system instruction and voice settings, and
forwards PCM chunks as `realtimeInput.audio`.

Gemini Live performs activity detection and emits transcript/audio responses
on the same turn. The browser plays returned `audio/pcm;rate=24000` chunks via
Web Audio as they arrive.

The old `/realtime/webrtc` SDP endpoint is intentionally closed. EA does not
depend on an OpenAI key for this path.

## Fallback State

The legacy MediaRecorder chunk path still exists for non-PCM clients and
unsupported browsers. That path buffers WebM/Opus chunks until `user_audio_end`,
then runs batch STT, answer generation, and TTS.

The ready frame exposes the active live target:

- `provider`: `gemini_live`
- `audio_transport`: `gemini_live_websocket_pcm`
- `turn_timing`: `streaming_audio_server_vad`
- `redesign_target`: `native_speech_to_speech_live_audio`

## Acceptance Bar

- Partial transcript events are visible before the complete fallback turn path.
- End-of-speech can start a Gemini answer without a separate upload step.
- Returned PCM audio is playable incrementally, not only after full TTS render.
- Barge-in/cancel closes the current Gemini turn and frees the upstream socket.
- Memorial guardrails, private context, memory policy, and source policy remain server-owned.
- Contract tests fail if OpenAI/WebRTC markers return to the public page.

## Acceptance Bar

- Partial transcript events are visible before `user_audio_end`.
- End-of-speech starts answer generation without a separate upload step.
- Barge-in cancels current assistant audio and starts a new user turn.
- The live page exposes the active mode in diagnostics: fallback or speech-to-speech live audio.
- A strict live voice loop proves STT, answer text, generated audio, and interruption behavior.
