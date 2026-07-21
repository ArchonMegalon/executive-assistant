# Next Session Handoff: Flagship Memorial Talk-Only Release

Date: 2026-07-21
Goal status: source implementation complete; public deployment blocked

## Goal

Publish the Manfred flagship memorial as a minimal, conversation-only public
experience. Visitors should arrive directly at the talk interface. Retain only
essential identity, AI and synthetic-voice disclosure, privacy, accessibility,
source-provenance, and safety controls. Hide galleries, story surfaces,
promotional content, dashboards, secondary navigation, contribution surfaces,
installation prompts, and other non-conversational routes.

Preserve source-grounded memorial behavior and fail-closed voice/provider
boundaries.

## Release worktree

- Worktree: `/home/tibor/.local/share/ea-releases/memorial-talk-only-20260721`
- Branch: `codex/memorial-talk-only-20260721`
- HEAD: `477add7f2998b61e601f8eaceb93d622e2fdcbc0`
- Parent implementation commit:
  `db1f548b Make the flagship memorial privacy-safe and talk-only`
- HEAD commit:
  `477add7f Harden talk-only memorial release verification`
- Base parent:
  `f3afffa7 Block Memorial release pending credential remediation`
- The release worktree was clean when last checked.

Do not use `/docker/EA` for release edits. It is a separate dirty main worktree
whose unrelated user changes must be preserved.

Before any release action, read and obey:

- `/home/tibor/.local/share/ea-releases/memorial-talk-only-20260721/AGENTS.md`
- `.codex-design/product/README.md`
- `.codex-design/repo/IMPLEMENTATION_SCOPE.md`
- `.codex-design/review/REVIEW_CONTEXT.md`

Use the `ea-live-ops` skill and read its complete `SKILL.md` before performing
fresh runtime or authority checks.

## Completed implementation

- The primary Manfred route explicitly uses `conversation_only=True`.
- The page contains one identity header and one conversation `<main>`.
- Navigation, story, gallery, contribution, installation, dashboard, and
  promotional surfaces are absent from the public experience.
- The visible disclosure states that the AI is not Manfred and does not speak
  for him; synthetic voice is disclosed where applicable.
- Text fallback, transcript, sources, privacy details, accessibility, and safety
  controls remain available.
- Personal-memory opt-in defaults off.
- Settings status is loaded only when settings are opened.
- Delete clears server-side state and the local opt-in.
- Written HTTP turns use the central completed-turn renderer, so provenance is
  exposed through the sources control.
- The source panel resets and collapses for each answer to prevent stale
  provenance.
- WebSocket voice turns render both the visitor and assistant in the transcript.
- No-JavaScript output uses `lang="de-AT"`, hides the speech-ready status, and
  keeps personal-memory controls disabled until JavaScript boots.
- Privacy opt-in and delete controls meet the 44-pixel target size.
- The production memorial-only surface boundary returns generic `not_found`
  responses for hidden legacy routes.
- Provider and voice boundaries remain fail-closed.

Compatibility note: the rendered HTML still carries legacy dead JavaScript and
CSS because of the marker-based stripping mechanism. Those assets do not expose
the removed public experience and are not a completion blocker.

## Verification completed

842 relevant checks passed:

- 151 deployment-contract checks
- 142 candidate-isolation checks
- 45 runtime checks
- 157 security and voice-preview checks
- 324 conversation, release-policy, copy, and archive-security checks
- 23 browser end-to-end checks

Also passed:

- Ruff across changed files, ignoring only pre-existing `F401` and `F841`
- `py_compile`
- `git diff --check`
- Final read-only P0/P1 review
- Manual exact memorial-only browser audit: zero provider requests, zero
  WebSockets, zero external requests, zero failed requests, and no page errors

## Public status

The source is ready, but it has not been deployed.

- URL: `https://myexternalbrain.com/memorials/manfred`
- Live source revision last observed:
  `2e5b40f9fe2ef4acb7946eb7e80537fcd01ab047`
- The live page still contained `id="memorial-story"`, proving that it remained
  on the legacy surface.
- No live or Docker mutation was performed.

## Hard release blockers

### 1. VEXP enforced soak

Last observed state in
`/home/tibor/.local/state/vexp-sentinel/state.json`:

- schema version: 6
- `qualification_phase`: `enforced_soak`
- `qualified_at`: `null`
- epoch start: `2026-07-21T07:43:20.579Z`
- earliest completion: `2026-07-28T07:43:20.579Z`
- certification blocker: `license:fresh_token_not_renewed`
- `fresh_token_renewed_in_epoch`: `false`
- current resources healthy: `true`
- AppArmor qualification ready and enforced: `true`

### 2. Required root-owned authority absent

The following were absent when last checked:

- `/var/lib/vexp-qualification-certificate`
- `/run/ea/memorial-vexp-mutation-permit.json`
- `/run/ea/memorial-vexp-mutation-permit.commit.json`
- `/run/ea/memorial-vexp-mutation-permit.lock`

Missing state, certificate, permit, commit, or lock means deny.

### 3. Credential-exposure remediation unverified

The build, candidate, and deployment lanes intentionally fail with
`credential_exposure_remediation_unverified`. In particular:

- `scripts/build_manfred_memorial_image.py`
- `scripts/deploy_ea_memorial.py`

Their remediation guards are unconditional, and tests prove that environment
flags cannot bypass them. A canonical external closure verifier or approved
artifact has not been found.

Do not patch around, disable, or otherwise bypass these guards. Closure requires
authorized external credential incident remediation/rotation plus canonical
code or evidence recognized by the release lane.

## Governance boundaries

- `qualification_phase=enforced_soak` is a hard candidate, merge, promotion,
  and live-release hold.
- Do not edit, stop, backdate, fabricate, or weaken VEXP state, certificates,
  permits, or locks.
- A user saying `go`, `deploy`, or `unblock` is not schema-v6 recovery or
  deployment authority.
- Qualification-plumbing recovery requires an explicit operator instruction
  naming schema-v6 recovery and a reviewed commit/SHA-bound maintenance
  manifest. Even that does not authorize deployment and requires a new seven-day
  epoch.
- Do not run candidate preparation, build, or deployment until a root-owned
  positive permit proves the exact terminal epoch and release revision.
- EA is governance-adjacent; it is not itself release authority.

## Next session

1. Work from the clean release worktree and preserve `/docker/EA` changes.
2. Read the governing instructions and invoke the `ea-live-ops` skill.
3. Perform read-only checks for current VEXP state, qualification certificate,
   permit, permit commit, permit lock, and canonical credential-remediation
   closure.
4. If any authority remains absent or invalid, do not run build, candidate, or
   deployment commands. Report the exact blockers.
5. If every authority is present and valid for the exact HEAD, use the governed
   memorial deployment lane.
6. Verify the public origin serves the expected revision and the exact
   conversation-only topology, including hidden legacy routes and fail-closed
   provider behavior.
7. Do not mark the goal complete until the public origin is verified on the new
   revision.

Goal-lifecycle note: the user's most recent `go` resumed a previously blocked
goal and produced the first repeated-authority-block audit in the new resumed
run. Do not mark the resumed goal blocked again unless the same condition recurs
for three consecutive resumed goal turns.
