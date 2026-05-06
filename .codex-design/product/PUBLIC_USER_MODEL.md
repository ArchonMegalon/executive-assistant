# Public user model

## Purpose

This file defines the user-facing model for `chummer.run` and adjacent public surfaces.
It is intentionally smaller than the internal identity, role, or moderation model.

## Current user classes

### Guest

A guest may:

* browse the landing page
* read the product story
* inspect what is real today
* inspect horizons
* open downloads
* view public status
* inspect featured artifacts and teasers
* open the participate entry page

### Registered user

A registered user may, in addition to guest behavior:

* access `/home`
* manage a lightweight account/profile
* follow or watch future horizons when that overlay is enabled
* raise beta-interest or waitlist intent
* enter the guided participation flow
* unlock future advisory-vote placeholders when enabled

## Install relationship states

Downloads and installs are related to user classes, but they are not the same thing.

### Guest install

A guest install may:

* download public stable/open builds
* run the app without a Hub account
* send pseudonymous crash, bug, or feedback intake tied to an installation id
* later be linked to an account

### Claimed install

A claimed install is a desktop installation linked to a registered user.

It may additionally:

* receive account-aware channel guidance
* receive case-status and fix-available notices
* keep support history attached to the account

The install relationship may be personalized without making the binary itself user-specific.

## Community-ledger relationship states

The signed-in front door may surface:

* claim state for this install
* group and community membership
* participation and sponsor-session posture
* reward journal and entitlement journal state
* linked channel and recovery posture

These are Hub community-ledger facts, not provider-auth side effects or local-cache guesses.

A guest may inspect the public explainer and later claim an install, but a guest does not receive implied ledger membership merely by opening `/participate`, `/downloads`, or `/home` redirects.

Linked channels stay separate from rewards and entitlements even when the same signed-in surface can explain all of them together.

## Profile flags

The first public profile pass should prefer flags over hard roles:

* `interested_in_play`
* `interested_in_gm_tools`
* `interested_in_creator_tools`
* `wants_horizon_updates`
* `wants_beta_invites`
* `guided_participation_opt_in`

These flags may later inform richer roles or product lanes, but they are not a license to hardcode complex role UX into the early-access surface.

## Linked identities

Registered users may later link:

* email or magic link
* Google
* Telegram identity
* optional Facebook if that provider is enabled

Email verification is account hygiene.
Google is the preferred mainstream social bootstrap.
Telegram is a useful linked identity or channel, but not the account core.

## Linked channels

Linked channels are distinct from linked identities.

First-wave channel posture:

* official Telegram companion bot is allowed
* user-provided Telegram bots are future capability only

EA remains the orchestrator brain behind companion channels.
Hub owns identity, linking, permissions, and entitlement checks around those channels.

## Future expansion

Future role expansion may introduce:

* GM
* Creator
* Moderator

That expansion must grow from the Hub account/community plane rather than from landing-page-only logic.

## Privacy rule

Public recognition remains opt-in.
Group-public and user-private combinations are allowed.
Landing and home surfaces must not force public identity merely to show interest, status, or future follow behavior.

## Early-access rule

The early-access surface needs only:

* sign in
* basic profile
* follow/watchlist placeholders
* guided participation entry
* future vote placeholder

Do not force a giant onboarding wizard or hard role selection up front.

## First-wave auth posture

First-wave entry should be boring:

* `/login`
* `/signup`
* browser session cookies for the hosted shell
* email-first entry before a larger provider set appears

Google is the next allowed mainstream adapter when provider credentials exist.
Facebook and user-provided Telegram bots must stay out of the default first-wave UI until canon changes and the adapters are actually live.
