# Identity and channel linking model

## Purpose

This file defines the canonical public-account posture for:

* email verification
* social onboarding
* linked identities
* linked channels
* official companion bots
* future user-provided bot links

It exists so Hub, `chummer.run`, and later channel adapters do not invent contradictory account behavior.

## Person, install, and channel are distinct

Chummer keeps three related but separate identities:

* the Hub account person
* the claimed or guest desktop installation
* the linked notification or companion channel

Do not collapse these into one giant auth object.

## Canonical split

* `chummer6-hub` owns identity linking, account hygiene, permissions, groups, sponsorship sessions, rewards, and entitlements.
* EA remains the orchestrator brain behind assistant and GM-companion behavior.
* Google, Facebook, Telegram, and transactional email are adapters around that Hub-owned account model.
* Email verification is identity hygiene, not a separate product pillar.

Do not add a second "brain" or a separate channel-specific identity stack for this.

## Account creation posture

Recommended order:

1. email or magic link
2. Google
3. Telegram identity link
4. Facebook only if demand justifies it

Current principle:

* a user should not be forced through an oversized auth zoo up front
* recovery should stay boring
* onboarding friction should stay lower than the value of the surface being unlocked

## Verification rules

### Email

* email signup requires verification
* the default verification path is a link, not a manual code
* unverified email is not strong recovery posture

### Google

* Google-backed sign-in may be treated as provider-backed auth proof
* it is the preferred mainstream social bootstrap

### Facebook

* Facebook is allowed as an optional provider
* it is not a first-wave requirement

### Telegram identity

* Telegram may be linked as an identity
* it is not the account core
* a stronger recovery identity should still be encouraged

## Linked identities versus linked channels

Do not conflate:

* a linked identity
* a notification channel
* the official GM-companion bot
* a user-provided bot token

Canonical distinction:

* linked identities prove or recover account access
* linked channels route messages, notifications, and companion behavior
* installations authenticate desktop clients and bind support/update history to one local copy

These are separate records and separate policy decisions.

## Community-ledger rule

Linked identities and linked channels attach to the Hub community ledger; they do not replace it.

That means:

* reward journal, entitlement journal, sponsor-session status, and group membership are separate community records
* a linked channel is never proof of reward, entitlement, or sponsor-session completion
* `/home` and `/account` may explain identity, channel, participation, reward, and recovery posture together, but each fact still comes from its own Hub-owned record

## Install claim rule

Desktop installs are claimable after download.

That means:

* the downloaded installer stays canonical and signed for its release target
* Hub may mint a claim ticket when a signed-in user downloads it
* first launch may link the installed copy to the account
* the desktop client later authenticates as that claimed installation instead of pretending a browser session is its long-lived identity

## Telegram posture

### First wave

Allowed:

* Telegram as a linked identity
* one official Chummer / Hubbrain Telegram bot

Not yet first-wave:

* arbitrary user-provided Telegram bots as direct front doors into EA

### Later wave

User-provided Telegram bots may exist later, but only with:

* ownership verification
* bounded command scope
* Hub-owned entitlements and policy checks
* explicit auditability

Until then, "bring your own bot" is a future capability, not an implied promise.

## Channel brain rule

EA remains the orchestration substrate for companion behavior because it already owns:

* principal-scoped execution
* memory
* skill routing
* approvals
* delivery orchestration

Hub routes identity, account, entitlement, and channel policy into EA.
Hub does not spawn a second assistant brain for Telegram or GM companion features.

## Public-surface effect

`chummer.run` and Hub account surfaces may say:

* continue with email
* continue with Google
* link Telegram later

They must not imply:

* that Facebook is first-wave unless canon changes
* that arbitrary user-provided bots already work
* that a new AI control plane exists outside EA
