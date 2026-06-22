# Memorial VoiceWave Workspace Runbook

Use this lane to inspect the real `VoiceWave.ai` workspace before treating it as a serious memorial voice-generation candidate.

What this lane does:
- signs into `VoiceWave.ai`
- captures the visible workspace surface
- scores the workspace for memorial voice fit
- looks for signals such as voice cloning, timeline editing, WAV/MP3 export, and commercial-use phrasing

Command:

```bash
cd "$EA_REPO_ROOT"
python3 scripts/analyze_voicewave_workspace.py \
  --project-name "Manfred Memorial Voice" \
  --fit-keyword memorial \
  --fit-keyword voice \
  --fit-keyword export \
  --fit-keyword timeline
```

Optional:

```bash
python3 scripts/analyze_voicewave_workspace.py \
  --page-url "https://www.voicewave.ai/app" \
  --project-name "Manfred Memorial Voice"
```

Credential slots:
- `VOICEWAVE_LOGIN_EMAIL`
- `VOICEWAVE_LOGIN_PASSWORD`

Output:

```text
.codex-studio/published/voicewave_provider/voicewave_workspace_analysis.generated.json
```

Interpretation:
- `strong_fit`
  Authenticated workspace plus clear evidence of the voice editor/export surface and matching memorial voice keywords.
- `possible_fit`
  Authenticated workspace with some useful markers, but not yet enough proof for a production lane.
- `weak_fit`
  Login worked but the visible page did not clearly expose the needed voice-generation/export surface.
- `blocked`
  Login failed or the BrowserAct worker never reached a usable authenticated workspace.

Important:
- This is a workspace-inspection lane, not automatic provider approval.
- It does not prove legal, privacy, or memorial-source-data readiness by itself.
- Treat any positive result as evidence gathering for a later provider-proof step, not as production truth.
