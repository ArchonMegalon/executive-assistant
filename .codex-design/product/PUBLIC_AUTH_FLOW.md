# Public auth flow

## Purpose

This file defines the first-wave guest-to-registered entry flow for `chummer.run`.

It exists so the landing, Hub account shell, and participation entry do not invent contradictory auth posture.

## Canonical route split

Public auth routes:

* `/login`
* `/signup`
* `/logout`
* `/auth/email/start`
* `/auth/email/callback`
* `/auth/google/start`
* `/auth/google/callback`

Registered routes:

* `/home`
* `/account`
* `/participate/codex`

## Download and install linking rule

Public stable/open downloads remain guest-readable.

Signed-in users may receive a better handoff, not a different artifact:

* Hub may mint a `DownloadReceipt`
* Hub may mint a short-lived `InstallClaimTicket`
* first launch may offer `Use as guest` or `Link this copy to my account`

That flow must not require a personalized installer binary.

## Install claim posture

Install claim linking belongs to Hub-owned account flow, not to installer mutation.

Allowed public wording:

* download now
* link this copy to your account
* keep me updated about issues I report

Forbidden public wording:

* this installer is custom-built for your account
* sign in to download a public stable build

## Guest fallback rules

* guest access to `/home` must redirect or fall back to `/login?next=/home`
* guest access to `/account` must redirect or fall back to `/login?next=/account`
* guest access to `/participate/codex` must redirect or fall back to `/login?next=/participate/codex`
* `/participate` remains the public explainer and must not require sign-in
* guest-visible participation CTAs should prefer `/participate` first; the deep `/participate/codex` lane is a later step, not the first public landing target

## Discoverability rule

* guest-visible chrome must expose both `Sign in` and `Create account`
* `/login` must link to `/signup`
* `/signup` must link back to `/login`
* guest waitlist or follow CTAs must prefer first-party guest targets such as `/signup?next=/home` over generic redirects to `/home`

## First-wave implemented posture

Enabled now:

* email or magic-link style entry
* basic browser session for the hosted shell

Allowed next when real provider credentials exist:

* Google sign-in

Deferred from first wave:

* Facebook as a visible signup default
* arbitrary user-provided Telegram bots
* per-user desktop installers

## Provider language rule

Provider names do not belong on the landing hero, proof shelf, horizon cards, or generic product pitch.

Provider names may appear on:

* `/login`
* `/signup`
* `/account`
* dedicated account-security or linked-identity surfaces

## Preview honesty rule

If a provider route exists before the full adapter is configured, the route must still explain:

* what the route is for
* whether it is enabled in the current build
* what the current fallback is

The route must not pretend the provider is already live.
