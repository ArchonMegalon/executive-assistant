# Product usage telemetry event schema

## Purpose

This file turns `PRODUCT_USAGE_TELEMETRY_MODEL.md` into a concrete contract:

* exact event names
* bounded event envelopes
* daily rollup tables
* opt-out settings for `chummer6-ui`
* install-level preference handling for `chummer6-hub`

This is the canonical implementation-facing shape for product-improvement telemetry.
If a team wants to emit a new analytics event, it should be added here first.

## Posture

The default product-improvement telemetry plane is opt-out.

That means:

* stable and preview builds may emit Tier-2 product-improvement telemetry by default
* the user must see a plain-language first-run explanation and a visible off switch
* the user must be able to turn it off later without account friction
* Tier-3 debug uplift remains explicit opt-in outside crash recovery
* after a crash, the crash handler may auto-arm a temporary crash-debug window for the next reopen
* the recovery UI must immediately offer an opt-out and remember if the user declines future crash-triggered debug uplift

## Envelope rule

Every Tier-2 hosted telemetry event must fit this bounded envelope:

* `event_id`
* `observed_at_utc`
* `installation_id`
* `telemetry_tier`
* `event_name`
* `app_head`
* `platform`
* `arch`
* `release_channel`
* `app_version`
* `ui_language`
* `content_language` when distinct
* `claimed_install` as `true` or `false`
* `payload`

Allowed optional dimensions inside the payload:

* `ruleset`
* `preset_id`
* `source_pack_hash`
* `amend_package_ids`
* `houserule_fingerprint_set`
* `custom_data_present`
* `connectivity_posture`
* `hub_topology`
* `sync_enabled`
* `saved_character_count_bucket`
* `roster_size_bucket`
* `source_pack_count_bucket`
* `workspace_scale_bucket`
* `workflow_id`
* `entry_path`
* `feature_id`
* `input_posture`
* `font_scale_bucket`
* `high_contrast_enabled`
* `reduced_motion_enabled`
* `screen_reader_enabled`
* `error_family`
* `error_class`
* bounded timing buckets

Forbidden payload content:

* character names
* campaign names
* runner names
* free text
* raw notes
* raw houserule bodies
* full custom-data payloads
* full local file paths

## Opt-out state model

The canonical install-level preference is:

* `enabled_default`
* `disabled_by_user`
* `enabled_by_user`
* `debug_uplift_enabled`
* `debug_uplift_expired`
* `crash_debug_auto_armed`
* `crash_debug_auto_declined`

### `chummer6-ui` settings

The client should expose these settings:

* `product_improvement_telemetry_enabled`
  Default: `true`
  UI label: `Help improve Chummer with product usage telemetry`
  Help text: `Shares pseudonymous usage, startup, ruleset, language, and workflow counts. No character names, notes, or raw houserule text.`
* `crash_triggered_debug_uplift_enabled`
  Default: `true`
  UI label: `After a crash, temporarily enable crash diagnostics`
  Help text: `When Chummer crashes before recovery, it may temporarily enable extra diagnostics for the next launch. You can turn this off and Chummer remembers it.`
* `share_debug_uplift_with_support`
  Default: `false`
  UI label: `Share temporary debug telemetry for support`
  Help text: `Only on when you explicitly enable a time-boxed support or beta investigation.`
* `clear_local_telemetry_history`
  Action, not a toggle
  Effect: deletes the install-local telemetry history and any unsent hosted telemetry spool

When `product_improvement_telemetry_enabled` becomes `false`, `chummer6-ui` must:

* stop emitting new Tier-2 hosted telemetry
* clear any unsent Tier-2 spool within 24 hours
* keep only the local setting needed to remember the opt-out
* keep crash/support telemetry separate from product-improvement telemetry

When a crash occurs and `crash_triggered_debug_uplift_enabled=true`, `chummer6-ui` may:

* auto-arm a temporary Tier-3 crash-debug window for the immediate reopen and next recovery flow
* mark that state as temporary and expiry-bounded
* show a recovery prompt that says the extra diagnostics were enabled because the app crashed
* offer one clear opt-out action that disables future crash-triggered debug uplift and remembers the decision on this install
* clear any unsent crash-debug spool immediately if the user opts out from that prompt

### `chummer6-hub` install settings

Hub should persist one bounded install preference record:

* `installation_id`
* `telemetry_state`
* `telemetry_state_changed_at_utc`
* `telemetry_state_source` of `default`, `user`, `crash_handler`, or `support_debug`
* `crash_triggered_debug_uplift_enabled`
* `crash_triggered_debug_uplift_changed_at_utc`
* `debug_uplift_expires_at_utc` when present

This preference record is allowed even when telemetry is turned off because it exists to honor the opt-out itself, not to continue analytics collection.

## Delivery safety rules

The telemetry transport layer must obey these rules:

* a network failure must never block launch, save, recovery, or close
* the local hosted-telemetry spool must stay bounded by age and size
* clearing telemetry history must also clear any unsent Tier-2 or crash-debug spool
* Hub may publish a global telemetry kill switch for a broken or unsafe rollout
* a global kill switch may disable new emission, but it must never silently override a user opt-out back to enabled

## Exact event names

### App lifecycle

* `app.lifecycle.session_started`
  Use when the product begins a user-visible launch session.
  Payload:
  * `launch_kind`: `cold_start`, `warm_resume`, `post_update_relaunch`, `recovery_reopen`
* `app.lifecycle.ready_reached`
  Use when the product reaches a usable ready state.
  Payload:
  * `time_to_ready_bucket_ms`
* `app.lifecycle.session_ended`
  Use when the session closes normally.
  Payload:
  * `session_length_bucket_minutes`
* `app.lifecycle.crash_before_ready`
  Use when the app fails before the ready state.
  Payload:
  * `startup_phase`
  * `failure_bucket`
* `app.lifecycle.recovery_prompt_shown`
  Use when the user is shown a crash or recovery prompt.
  Payload:
  * `recovery_kind`: `crash_reopen`, `workspace_restore`, `sync_conflict_reopen`

### Rule environment

* `rule_env.activated`
  Use when a session selects or restores a rule environment.
  Payload:
  * `ruleset`
  * `preset_id`
  * `source_pack_hash`
  * `amend_package_ids`
  * `houserule_fingerprint_set`
  * `custom_data_present`
* `rule_env.changed`
  Use when the active rule environment changes inside a session.
  Payload:
  * same fields as `rule_env.activated`

### Install topology and scale

* `install.context_observed`
  Use when the app observes durable install context at session start or when that context materially changes.
  Payload:
  * `connectivity_posture`: `standalone_guest`, `standalone_claimed`, `hub_connected`, `hub_self_hosted`
  * `hub_topology`: `none`, `managed_hub`, `self_hosted_hub`
  * `sync_enabled`
  * `saved_character_count_bucket`
  * `roster_size_bucket`
  * `source_pack_count_bucket`
  * `workspace_scale_bucket`

### Workflow

* `workflow.started`
  Payload:
  * `workflow_id`
  * `entry_path`
  * `ruleset`
* `workflow.completed`
  Payload:
  * `workflow_id`
  * `duration_bucket_ms`
* `workflow.abandoned`
  Payload:
  * `workflow_id`
  * `abandon_stage`
* `workflow.failed`
  Payload:
  * `workflow_id`
  * `error_family`
  * `error_class`

Canonical `workflow_id` values:

* `first_launch_open_or_build`
* `open_existing_character`
* `create_new_character`
* `import_legacy_character`
* `save_character`
* `update_and_relaunch`
* `recover_after_crash`
* `open_campaign_workspace`
* `launch_play_shell`

### Feature adoption

* `feature.surface_opened`
  Payload:
  * `feature_id`

Canonical `feature_id` values:

* `master_index`
* `character_roster`
* `build_lab`
* `campaign_workspace`
* `play_shell`
* `explain_breakdown`
* `compare_diff`
* `print_export`

### Accessibility and input

* `accessibility.posture_observed`
  Use when a session starts with or changes into a materially different accessibility posture.
  Payload:
  * `input_posture`: `keyboard_primary`, `pointer_primary`, `touch_primary`, `mixed`
  * `font_scale_bucket`
  * `high_contrast_enabled`
  * `reduced_motion_enabled`
  * `screen_reader_enabled`

### Search and findability

* `search.query_observed`
  Payload:
  * `surface_id`
  * `query_length_bucket`
  * `result_count_bucket`
  * `zero_result`
* `search.result_opened`
  Payload:
  * `surface_id`
  * `result_kind`
* `surface.empty_state_shown`
  Payload:
  * `surface_id`
  * `empty_state_kind`

### Release and migration

* `release.update_offered`
  Payload:
  * `from_version`
  * `to_version`
* `release.update_started`
  Payload:
  * `from_version`
  * `to_version`
* `release.update_succeeded`
  Payload:
  * `from_version`
  * `to_version`
  * `time_to_relaunch_bucket_ms`
* `release.update_failed`
  Payload:
  * `from_version`
  * `to_version`
  * `error_family`
  * `error_class`
* `migration.import_started`
  Payload:
  * `source_family`
* `migration.import_completed`
  Payload:
  * `source_family`
* `migration.import_failed`
  Payload:
  * `source_family`
  * `error_family`
  * `error_class`

Canonical `source_family` values:

* `chummer4`
* `chummer5a`
* `hero_lab`
* `genesis`
* `other`

### Friction

* `friction.error_classified`
  Payload:
  * `affected_workflow`
  * `error_family`
  * `error_class`
* `friction.slow_operation_observed`
  Payload:
  * `affected_workflow`
  * `operation_kind`
  * `duration_bucket_ms`

### Preference

* `telemetry.preference_changed`
  This is an install-control receipt, not a general product-improvement event.
  Payload:
  * `telemetry_state`
  * `changed_from`
  * `changed_to`
  * `change_source`
  * `reason_code`
* `telemetry.preference_prompt_seen`
  Use when the user sees the first-run or settings telemetry prompt.
  Payload:
  * `prompt_kind`: `first_run`, `settings`, `crash_recovery`
* `telemetry.debug_uplift_auto_armed`
  Use when crash recovery temporarily enables crash-focused debug uplift.
  Payload:
  * `arm_reason`: `crash_recovery`
  * `failure_bucket`
  * `expires_at_utc`
* `telemetry.debug_uplift_auto_declined`
  Use when the user opts out from crash-triggered debug uplift and asks Chummer to remember that choice.
  Payload:
  * `decline_reason`: `remember_opt_out`
  * `failure_bucket`

When a user disables telemetry before any other hosted telemetry is emitted, this may be the only hosted receipt.

## Daily rollup tables

### `install_activity_daily`

One row per install per UTC day.

Columns:

* `usage_day`
* `installation_id`
* `app_head`
* `platform`
* `arch`
* `release_channel`
* `app_version`
* `ui_language`
* `claimed_install`
* `session_start_count`
* `ready_count`
* `crash_before_ready_count`
* `recovery_prompt_count`
* `cold_start_count`
* `warm_resume_count`
* `median_time_to_ready_bucket_ms`

### `rule_environment_daily`

One row per install, ruleset, and day.

Columns:

* `usage_day`
* `installation_id`
* `ruleset`
* `preset_id`
* `source_pack_hash`
* `amend_package_ids`
* `houserule_fingerprint_set`
* `custom_data_present`
* `activation_count`
* `save_count`
* `import_count`
* `export_count`

### `install_context_daily`

One row per install and day.

Columns:

* `usage_day`
* `installation_id`
* `connectivity_posture`
* `hub_topology`
* `sync_enabled`
* `saved_character_count_bucket`
* `roster_size_bucket`
* `source_pack_count_bucket`
* `workspace_scale_bucket`

### `workflow_funnel_daily`

One row per workflow, install, and day.

Columns:

* `usage_day`
* `installation_id`
* `workflow_id`
* `entry_path`
* `ruleset`
* `started_count`
* `completed_count`
* `abandoned_count`
* `failed_count`
* `median_duration_bucket_ms`

### `feature_adoption_daily`

One row per feature, install, and day.

Columns:

* `usage_day`
* `installation_id`
* `feature_id`
* `open_count`

### `search_usage_daily`

One row per install, surface, and day.

Columns:

* `usage_day`
* `installation_id`
* `surface_id`
* `query_count`
* `zero_result_count`
* `result_open_count`
* `empty_state_count`

### `friction_rollup_daily`

One row per install, workflow, error family, and day.

Columns:

* `usage_day`
* `installation_id`
* `affected_workflow`
* `error_family`
* `error_class`
* `count`

### `telemetry_preference_daily`

One row per install and day whenever preference state changes.

Columns:

* `usage_day`
* `installation_id`
* `telemetry_state`
* `telemetry_state_source`
* `last_change_reason_code`
* `crash_triggered_debug_uplift_enabled`
* `debug_uplift_expires_at_utc`

### `accessibility_posture_daily`

One row per install and day.

Columns:

* `usage_day`
* `installation_id`
* `input_posture`
* `font_scale_bucket`
* `high_contrast_enabled_any`
* `reduced_motion_enabled_any`
* `screen_reader_enabled_any`
* `observed_session_count`

## Aggregates the product governor should read

Derived dashboards should answer:

* starts per day by platform, head, channel, and version
* active installs by UI language
* active installs by ruleset
* active installs by connectivity posture and Hub topology
* percent of active installs using custom data
* top amend-package IDs
* top houserule fingerprints
* search zero-result rate by surface
* first-launch completion rate
* import completion rate by source family
* update-to-relaunch success rate
* startup reliability by platform and head
* startup and save reliability by install complexity bucket
* active installs using high-contrast, screen-reader, or large-font posture
* friction classes with the highest repeated user pain

## Sampling and retention rule

Core lifecycle, workflow, and failure events should not be sampled away.
If a lower-value event family is sampled later, the sampling policy must be named here first.

Raw hosted Tier-2 events should age out quickly into daily rollups, per `PRIVACY_AND_RETENTION_BOUNDARIES.md`.

## Rule

If an implementation needs a new event name that is not listed here, it should not silently invent one in code.
It should petition this file first.
