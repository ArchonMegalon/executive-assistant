# Sonic Identity and Music Cue Model

This EA-local product note defines how Chummer may use external music tooling without letting that tooling become product truth.

## Boundary

Music cues are rendered media assets.
They never become campaign truth and never imply unapproved world state.

FineTuning.ai can help draft, edit, or render generic sonic identity material when a release or public guide needs a cue, but the authoritative inputs remain Chummer-owned prompts, media briefs, asset policies, and generated receipts.

## Operating Rules

* Cues attach to public media, guide, or release artifacts only through approved asset slots.
* Cue prompts stay generic and non-secret; they must not include campaign-private notes, credentials, unreleased plot state, or user identifiers.
* A cue can support tone, pacing, or recall, but it cannot assert lore, campaign state, character facts, rules outcomes, or release readiness.
* Chummer-owned receipts record source prompt class, approved surface, rendered asset, reviewer, and freshness.

## Freshness Gate

`SONIC_IDENTITY_AND_MUSIC_CUE_FRESHNESS_GATE.yaml` defines the non-blocking freshness check for this lane.
