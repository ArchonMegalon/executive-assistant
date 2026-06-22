# Telegram EPUB to Audiobookshelf Skill

## Purpose

EA can accept an EPUB sent through Telegram and turn it into an audiobook job that ends in Audiobookshelf import storage.

The governed workflow is:

```text
Telegram EPUB
  -> durable audiobook job storage
  -> EPUB spine/chapter extraction
  -> language and topic profiling
  -> voice audition with the best three configured Unmixr voices
  -> user choice through Telegram inline `Use this` / `Dismiss` controls
  -> Unmixr chapter narration, only after the external TTS gate is enabled
  -> durable throttle state when the provider asks EA to wait
  -> scheduler-backed resume from the last rendered segment
  -> m4b-tool chaptered M4B merge, or ffmpeg chaptered fallback when m4b-tool is absent
  -> Audiobookshelf import folder
  -> EA-issued player/runner-scoped audiobook reference for Chummer6 desktop
  -> Telegram status with ETA or blocker
  -> sanitized job receipt
```

## Boundaries

This lane is for books the operator owns, has licensed, or can legally transform for private listening. It must not process unlicensed book text, raw Gmail, raw Calendar content, people memory, workspace secrets, customer drafts, or any file whose rights basis is unclear.

Large artifacts must stay on durable audiobook storage. The portable default job root is:

```text
data/audiobooks/jobs
```

The portable default Audiobookshelf import root is:

```text
data/audiobooks/audiobookshelf
```

Production hosts may point these roots at a mounted pCloud library or another durable volume through `EA_AUDIOBOOK_DURABLE_STORAGE_ROOT`, `EA_AUDIOBOOK_JOBS_ROOT`, and `EA_AUDIOBOOKSHELF_IMPORT_ROOT`. Raw host paths are runtime configuration, not repo truth.

Raw book text leaves EA only when:

```text
EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED=1
EA_AUDIOBOOK_UNMIXR_AUTO_RENDER=1
```

Without those flags, EA still creates the job, extracts chapters, stores the manifest, and replies with the exact blocker and ETA after approval.

If Unmixr throttles a long render, EA must persist:

```text
status = waiting_provider_throttle
next_action = resume_after_unmixr_throttle
render_result.provider_retry_after = <UTC timestamp>
```

For long EPUBs, EA should also pace itself before the provider has to do it. The default short-TTS lane renders at most 20 fresh Unmixr segments in one run, then persists:

```text
status = waiting_provider_throttle
next_action = resume_after_unmixr_pacing
render_result.status = provider_pacing_wait
render_result.provider_retry_after = <UTC timestamp>
```

This wait is an intentional bulk-job pause, not a provider failure. It protects the single Unmixr lane so short, player-facing jobs such as Origin Dossier narration can still run promptly unless Unmixr has already applied a real account-wide throttle.

The scheduler may resume the job only when the retry timestamp has passed and the stored job manifest already records that raw book text was allowed to leave EA for Unmixr narration.

Before long-form rendering, the EPUB lane should audition voices instead of silently accepting a weak default. EA profiles the book language and topic, ranks configured and generically discovered voices, sends three short samples from the first few sentences, and waits for the user to choose. If the user dismisses the whole batch, EA sends the next three available samples. Alice is deprioritized by default through `EA_AUDIOBOOK_VOICE_BLOCKLIST=alice` because the current operator feedback says Alice is not good enough.

The chosen voice is stored as a public label/tags/score packet plus a private job-local voice ID. Public receipts must never expose raw provider voice IDs.

When several jobs are due at the same time, the scheduler must prefer priority small narration work before bulk EPUB resumes. The default priority source kinds are:

```text
origin_dossier_story
origin_dossier
```

Within the same priority class, older retry timestamps run first.

Every completed job-state update writes a sanitized receipt beside the job manifest:

```text
<job-dir>/job_receipt.json
```

The operator can also materialize a published receipt with:

```bash
python3 scripts/materialize_audiobook_job_receipt.py --job-dir <job-dir>
```

The runtime lane should also have a current preflight receipt:

```bash
python3 scripts/materialize_audiobook_runtime_preflight.py
```

That receipt proves durable audiobook storage, Telegram EPUB intake, governed external TTS, the Unmixr voice catalog, ffmpeg/m4b assembly, Audiobookshelf import, player-scoped signing, and scheduler resume without exposing secrets or raw paths.

The user-facing audio quality contract should also stay green:

```bash
python3 scripts/materialize_audiobook_epub_quality_contract.py --pretty
python3 scripts/verify_audiobook_epub_quality_contract.py --pretty
```

That receipt binds the Alice blocklist, language/topic/author-gender voice ranking, short three-sample audition, inline `Use this` / `Dismiss` controls, immediate dismiss-to-replacement behavior, Audiobookshelf public-share playback acceptance buttons, provider-audio normalization, quiet-tail/trailing-silence quality reports, M4B chapter/cover embedding hooks, and an artifact-level M4B structure probe.

For live Telegram delivery setup, the operator should first materialize the stricter readiness checklist:

```bash
make verify-telegram-audiobook-live-readiness
```

That checklist turns the runtime preflight into concrete setup actions for the live goal: external TTS approval, Unmixr auto-render, at least three voices, at least one owned Unmixr API-key slot, durable job/import storage, M4B assembly, Audiobookshelf public-share API configuration, player-scoped signing, and scheduler resume. It may pass verification while its status is still blocked; that means the blockers are accurately recorded, not that live delivery has happened.

The M4B probe materializes a tiny covered, chaptered M4B through the same ffmpeg fallback merge path as real jobs, then verifies it with `ffprobe` for title/artist metadata, chapter titles, audio stream presence, and attached poster art. This proves the final file structure, not just the command shape.

After a real Telegram EPUB job has rendered, imported into Audiobookshelf, been scanned, had a public share created, and had that public share sent back to Telegram, the operator can materialize live delivery proof:

```bash
make materialize-telegram-audiobook-live-delivery-receipt
make verify-telegram-audiobook-live-delivery-receipt
```

That receipt proves live delivery only when a sanitized real job receipt shows `status=audiobookshelf_imported`, a ready M4B, a ready Audiobookshelf public share, and `public_share_telegram_delivery_status=sent`. It hashes the public share URL and Telegram message ID instead of publishing them. It does not prove that a human listened to the audiobook or accepted playback quality unless the separate Telegram playback acceptance callback has been recorded as accepted.

Telegram status replies may name the book, blocker, ETA, selected voice label, and scoped playback URL. They must not include the raw job path, raw Audiobookshelf import path, provider voice ID, provider URL, Telegram file URL, or any global library/admin token.

The same pipeline can accept approved text chapters instead of an EPUB. Origin Dossier uses that entrypoint when a player asks for an audiobook of the approved origin story:

```text
Origin Dossier approved story
  -> EA text-chapter audiobook job
  -> automatic voice selection
  -> governed Unmixr narration
  -> M4B import
  -> player/runner-scoped Chummer6 audiobook reference
```

Chummer6 desktop must receive only the scoped EA reference. It must not receive an Audiobookshelf admin token, provider token, global library token, raw storage path, or access to other players' audiobook libraries.

## Runtime flags

```env
EA_TELEGRAM_AUDIOBOOK_EPUB_ENABLED=1
EA_AUDIOBOOK_DURABLE_STORAGE_ROOT=data/audiobooks
EA_AUDIOBOOK_JOBS_ROOT=data/audiobooks/jobs
EA_AUDIOBOOK_TELEGRAM_MAX_BYTES=209715200
EA_AUDIOBOOK_EPUB_MAX_UNCOMPRESSED_BYTES=629145600
EA_AUDIOBOOK_EPUB_MAX_ARCHIVE_ENTRIES=2500
EA_AUDIOBOOK_EXTERNAL_TTS_ENABLED=0
EA_AUDIOBOOK_UNMIXR_AUTO_RENDER=0
EA_AUDIOBOOK_UNMIXR_MAX_CHARS_PER_REQUEST=1800
EA_AUDIOBOOK_UNMIXR_MAX_SEGMENTS_PER_RUN=20
EA_AUDIOBOOK_UNMIXR_PACING_WAIT_SECONDS=1800
EA_AUDIOBOOK_UNMIXR_BULK_PACING_CHAR_THRESHOLD=60000
EA_AUDIOBOOK_PRIORITY_SOURCE_KINDS=origin_dossier_story,origin_dossier
EA_AUDIOBOOK_UNMIXR_RETRY_COUNT=3
EA_AUDIOBOOK_UNMIXR_RETRY_BACKOFF_SECONDS=4
EA_AUDIOBOOK_VOICE_DISCOVERY_ENABLED=1
EA_AUDIOBOOK_VOICE_DISCOVERY_TARGET_COUNT=30
EA_AUDIOBOOK_VOICE_DISCOVERY_PROVIDERS=unmixr
EA_AUDIOBOOK_UNMIXR_VOICE_DISCOVERY_USE_CASES=audiobook-voices,narration-voices,documentary-voices,podcast-voices
EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_JSON=
EA_AUDIOBOOK_UNMIXR_VOICE_PRESETS_PATH=
EA_AUDIOBOOK_DEFAULT_VOICE_LABEL=
EA_AUDIOBOOK_DEFAULT_VOICE_LANGUAGE=
EA_AUDIOBOOK_DEFAULT_VOICE_TAGS=narration,neutral,general
EA_AUDIOBOOK_VOICE_AUDITION_ENABLED=1
EA_AUDIOBOOK_VOICE_BLOCKLIST=alice
EA_AUDIOBOOK_VOICE_SAMPLE_SOURCE_CHARS=1800
EA_AUDIOBOOK_VOICE_SAMPLE_MAX_CHARS=420
EA_AUDIOBOOK_AUDIO_NORMALIZATION_ENABLED=1
EA_AUDIOBOOK_AUDIO_NORMALIZATION_FILTER=dynaudnorm=f=150:g=15,loudnorm=I=-16:TP=-1.5:LRA=11
EA_AUDIOBOOK_AUDIO_QUALITY_REPORT_ENABLED=1
EA_AUDIOBOOK_AUDIO_TAIL_WINDOW_SECONDS=1.5
EA_AUDIOBOOK_AUDIO_MAX_TRAILING_SILENCE_SECONDS=1.2
EA_AUDIOBOOK_AUDIO_QUIET_TAIL_RMS_THRESHOLD=0.006
EA_AUDIOBOOK_AUDIO_AUDIBLE_RMS_THRESHOLD=0.004
EA_SCHEDULER_AUDIOBOOK_RESUME_ENABLED=1
EA_SCHEDULER_AUDIOBOOK_RESUME_INTERVAL_SECONDS=300
EA_AUDIOBOOK_RESUME_DUE_LIMIT=2
EA_AUDIOBOOK_RESUME_ATTEMPT_COOLDOWN_SECONDS=900
EA_AUDIOBOOK_M4B_AUTO_MERGE=1
EA_M4B_TOOL_BIN=m4b-tool
EA_AUDIOBOOK_FFMPEG_M4B_FALLBACK=1
EA_AUDIOBOOKSHELF_AUTO_IMPORT=1
EA_AUDIOBOOKSHELF_IMPORT_ROOT=data/audiobooks/audiobookshelf
EA_AUDIOBOOK_ACCESS_SIGNING_SECRET=
EA_AUDIOBOOK_ACCESS_EXPIRES_DAYS=30
EA_AUDIOBOOK_PLAYER_ACCESS_BASE_URL=
EA_AUDIOBOOKSHELF_PUBLIC_SHARE_ENABLED=0
EA_AUDIOBOOKSHELF_API_BASE_URL=
EA_AUDIOBOOKSHELF_PUBLIC_BASE_URL=
EA_AUDIOBOOKSHELF_API_TOKEN=
EA_AUDIOBOOKSHELF_LIBRARY_ID=
EA_AUDIOBOOKSHELF_SCAN_POLL_SECONDS=90
EA_AUDIOBOOK_PUBLIC_SHARE_ATTEMPT_COOLDOWN_SECONDS=300
```

Unmixr account slots:

```env
UNMIXR_API_KEY=
UNMIXR_API_KEY_FALLBACK_1=
UNMIXR_API_KEY_FALLBACK_2=
```

The fallback slots are for additional owned Unmixr accounts. They are active only when their API keys are present in runtime config; account login/password/license-code facts stay outside git.

## Exit Criteria

- Telegram EPUB documents are detected before the generic document reply.
- The source EPUB, chapter text, audio files, M4B, and job manifest are stored under the configured durable job root.
- The job manifest never stores the Telegram file URL or provider secrets.
- EA replies with a concrete current status and ETA after blockers clear.
- Completion replies expose only the scoped playback URL, never the raw job or Audiobookshelf path.
- Provider throttles become a resumable wait state, not a failed job, and the scheduler resumes only after the recorded provider retry timestamp.
- Long EPUB renders use resumable batch pacing before provider throttling, while Origin Dossier story jobs are treated as priority small narration work.
- A sanitized receipt can be materialized for every job; it must not contain raw chapter text, Telegram chat IDs, Telegram message IDs, Telegram file URLs, bot tokens, provider voice IDs, Audiobookshelf tokens, raw Audiobookshelf paths, or private job paths.
- The durable job folder contains a current `job_receipt.json` after every `continue_job` update.
- The published runtime preflight receipt passes before promising automatic EPUB-to-Audiobookshelf completion.
- EA records the selected voice by label, tags, score, and hashed voice ID, never by raw voice ID in public receipts.
- EA sends three voice samples with inline `Use this` and `Dismiss` controls before long-form render when at least three configured or discovered voices are available.
- If a sample is dismissed, EA immediately replaces that one voice with the next available candidate without requiring the EPUB to be re-uploaded.
- Alice is deprioritized by default unless the operator changes `EA_AUDIOBOOK_VOICE_BLOCKLIST`.
- Rendered provider audio is normalized so the end of the sample or chapter is not too quiet.
- Rendered WAV samples and chapters write a bounded quality report that flags missing speech energy, quiet tails, and excessive trailing silence.
- M4B output embeds chapter metadata and the EPUB cover/poster when the EPUB contains one.
- Runtime receipts expose only the count of configured Unmixr API-key slots, not the keys or account passwords.
- `m4b-tool` is installed, or the ffmpeg chaptered-M4B fallback is available, before claiming automatic M4B completion.
- Telegram EPUB URLs are restricted to `api.telegram.org` and rejected at ingest before download.
- EPUB downloads are validated as real EPUB archives before chapter extraction: `mimetype`, `META-INF/container.xml`, a safe OPF rootfile path, safe ZIP member paths, entry-count limits, and uncompressed-size limits must pass.
- Audiobookshelf import writes to durable library/import storage, normally a mounted production library volume.
- If Audiobookshelf scan is not ready immediately, the scheduler keeps polling for the imported item and sends the public share link to Telegram after the scan catches up.
- A live delivery receipt can prove a real Telegram public-share send without exposing the raw public share URL, Telegram message ID, Audiobookshelf token, or raw import path.
- Public share messages include `Playback works` and `Problem` buttons. Pressing either button records only hashed callback evidence in the job receipt.
- A live delivery receipt must keep human playback acceptance separate; delivery proof is not a quality-listening claim unless the accepted playback callback is present.
- Chummer6 receives a player/runner-scoped EA reference or download route, not a global Audiobookshelf credential.
