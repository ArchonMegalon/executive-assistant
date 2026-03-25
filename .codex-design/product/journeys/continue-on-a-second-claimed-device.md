# Continue on a second claimed device

Status: additive_middle_wave

## User goal

Claim a second device and continue the same runners, campaigns, rule environment, artifacts, and eligible features without mystery sync.

## Entry surfaces

* Hub claimed-install restore surfaces
* desktop or mobile signed-in home
* registry-backed compatibility and artifact refs

## Happy path

1. The user claims a second install without reinstalling or downloading a personalized binary.
2. Hub resolves person, campaign, and group-scoped roaming workspace truth for that install.
3. Registry provides immutable install compatibility, channel posture, and artifact references.
4. The client restores recent runners, campaigns, rule-environment refs, and artifact-shelf pointers instead of mirroring raw files.
5. Eligible features appear through Hub capability grants, and any device-local channel differences stay visible.
6. If the user chooses a runner or campaign with a newer remote draft, the client offers latest, compare, branch, or stay-local rather than silently replacing work.

## Failure modes

* No logs, crash dumps, secrets, or local key material may roam.
* No premium or preview access may come from synced install-local booleans.
* If the install lacks the required rule environment or compatibility posture, the product must show a concrete repair path before compute or play continues.
* If person, campaign, and install scopes disagree, the conflict must be visible instead of collapsing into a hidden last-write-wins state.

## Success evidence

* Cross-device continuity feels like one workspace, not one opaque blob.
* Install-local safety boundaries remain visible.
* Rule-environment and entitlement posture stay trustworthy.

## Owning repos

* `chummer6-hub`
* `chummer6-hub-registry`
* `chummer6-ui`
* `chummer6-mobile`
* `chummer6-core`
