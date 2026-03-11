# EA provider registry and Unmixr feedback

Date: 2026-03-11
Audience: `executive-assistant` and `solo-ea`
Status: injected fleet feedback

The runtime kernel is still the strongest part of EA. The missing bounded context is now a typed provider registry.

## Main findings

* LTD truth still lives in multiple places at once: `LTDs.md`, `SKILLS.md`, env scaffolding, and JSON policy bags.
* the existing plan/skill/tool runtime is already strong enough; a second integration framework is not needed.
* provider lifecycle and capability verification should be modeled explicitly instead of buried in free-form metadata.
* auth still fails open too easily in dev-like configurations.
* bootstrap/runtime profile can still drift into mixed modes.

## Recommended bounded context

Add typed provider models:

* `ProviderProfile`
* `ProviderBinding`
* `ProviderCapabilityProbe`
* `SkillProviderBinding`

Then move providers through:

* `tracked`
* `auth_configured`
* `discovered`
* `capability_verified`
* `skill_bound`
* `operational`

`LTDs.md` should become a rendered report, not the source of truth.

## Runtime direction

Keep the existing execution path:

* `skill_key -> task_key -> planner -> tools -> artifact -> dispatch/memory`

Route by capability, not vendor name.

## First operational providers

* BrowserAct
* 1min.AI
* Unmixr
* ApiX-Drive
* ApproveThis

Evidence/content providers:

* Paperguide
* Documentation.AI

Projection/storage surfaces:

* Teable
* Internxt

## Unmixr-first guidance

Unmixr is the cleanest next provider because its API is concrete today.

First provider tools:

* `unmixr.voice_list`
* `unmixr.voice_detail`
* `unmixr.tts_generate`
* `unmixr.clone_voice`
* `unmixr.cloned_voice_list`
* `unmixr.credit_balance`

`unmixr.tts_generate` should:

* chunk below the documented request limits
* persist audio into the existing artifact repository
* emit receipts with voice, locale, usage, and request metadata
* support optional secondary secret refs when an extra upstream key is required

## Small cleanup

* add Unmixr env placeholders to local env examples
* replace stale `EA_LEDGER_BACKEND=memory` overlays with `EA_STORAGE_BACKEND=memory`
* keep Teable out of the hot-path runtime DB role
