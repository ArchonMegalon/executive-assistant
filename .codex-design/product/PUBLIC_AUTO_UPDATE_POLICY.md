# Public auto-update policy

## Purpose

This file defines the public-facing update promises for Chummer desktop heads.

Public update language must stay honest about three separate things:

* install media
* machine update payloads
* rollout and revoke truth

## Public promises

Public copy may promise:

* the desktop app can check for updates in-app
* update availability follows promoted channel truth
* Windows and Linux follow installer-first release posture
* bad heads may be paused or revoked

Public copy must not promise:

* silent repair of every issue
* instant availability on every channel
* Hub or Fleet as the runtime source of update truth
* downgrade or rollback behavior that the registry and client do not actually support

## Language rules

Use:

* `check for updates`
* `update available`
* `paused rollout`
* `revoked release`
* `install the newer build`

Avoid:

* `self-healing`
* `always auto-updates`
* `fixed everywhere now`
* helper-script or operator jargon

## Public split

The public story is:

* Registry owns promoted desktop head and update-feed truth.
* UI owns local check, stage, apply, relaunch, and recovery behavior.
* Hub explains the current posture and may guide signed-in installs.
* Fleet orchestrates release evidence and promotion, but clients do not ask Fleet whether an update is real.

## Channel honesty

Public copy must say when a fix is:

* available on the current channel
* still waiting for promotion
* paused
* revoked

The phrase `fixed` is user-safe only when the fix is actually available on that user's channel according to registry truth.
