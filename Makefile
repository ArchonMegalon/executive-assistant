.PHONY: deploy deploy-ea-prod deploy-ea-memorial deploy-property deploy-legacy-ea-stack deploy-memory deploy-bootstrap bootstrap db-status db-size db-retention smoke-api smoke-api-principal smoke-postgres smoke-postgres-legacy smoke-help release-smoke release-preflight release-docs test-api test-all test-postgres-contracts test-telegram-bot openapi-export openapi-diff openapi-prune documentation-ai-public-openapi verify-documentation-ai-public-docs materialize-documentation-ai-deployment-readiness verify-documentation-ai-deployment-readiness endpoints version-info release-authority-probe materialize-deploy-context refresh-deploy-context materialize-release-manifest refresh-release-manifest materialize-release-authority-status refresh-release-authority-status verify-release-authority-runtime verify-release-authority-runtime-authoritative proactive-ooda verify-proactive-ooda verify-proactive-ooda-live-receipt materialize-proactive-ooda-operator-status verify-proactive-ooda-operator-status materialize-proactive-ooda-gold-acceptance verify-proactive-ooda-gold-acceptance operator-summary operator-help provider-readiness overlay-vision-check overlay-vision-pull support-bundle tasks-archive tasks-archive-prune tasks-archive-dry-run materialize-release-assets materialize-continuous-improvement-goal-posture verify-continuous-improvement-goal-posture materialize-teable-env-recovery-readiness verify-teable-env-recovery-readiness send-audiobook-public-share-followups materialize-office-loop-goal-receipt verify-office-loop-goal-receipt materialize-executive-assistant-acceptance-evidence verify-executive-assistant-acceptance-evidence materialize-executive-assistant-quality-readiness verify-executive-assistant-quality-readiness materialize-whole-project-signal-to-decision-receipt verify-whole-project-signal-to-decision-receipt materialize-whole-project-scope-gap-audit verify-whole-project-scope-gap-audit materialize-active-media-ltd-goal-bundle verify-active-media-ltd-goal-bundle materialize-memorial-chatlab-external-evidence materialize-manfred-realtime-conversation-readiness verify-manfred-realtime-conversation-readiness materialize-telegram-audiobook-live-readiness verify-telegram-audiobook-live-readiness verify-telegram-audiobook-deployed-runtime materialize-telegram-audiobook-live-delivery-receipt verify-telegram-audiobook-live-delivery-receipt materialize-whatsapp-audiobook-local-intake-proof verify-whatsapp-audiobook-local-intake-proof materialize-whatsapp-audiobook-operator-proof-bundle verify-whatsapp-audiobook-operator-proof-bundle materialize-whatsapp-audiobook-live-delivery-receipt verify-whatsapp-audiobook-live-delivery-receipt verify-whatsapp-audiobook-public-share-playback materialize-whatsapp-audiobook-live-voice-selection-shadow verify-whatsapp-audiobook-live-voice-selection-shadow materialize-telegram-video-delivery-operator-receipt materialize-telegram-video-delivery-live-receipt materialize-telegram-video-delivery-receipts verify-telegram-video-delivery-live-receipt materialize-memorial-public-voice-gold materialize-memorial-public-browser-gold materialize-memorial-public-browser-meaningful-gold materialize-memorial-public-auto-receipts-clean materialize-memorial-room-audio-attestation-packet materialize-memorial-room-audio-gold materialize-memorial-room-audio-gold-clean materialize-memorial-public-gold materialize-memorial-phrase-bank materialize-memorial-operator-status inspect-source-dirty-groups materialize-memorial-stt-provider-benchmark verify-memorial-stt-provider-benchmark verify-memorial-runtime-overlay verify-memorial-deploy-readiness sync-memorial-public-sources-teable env-backup-teable env-bootstrap-teable env-check-teable env-disable-extra-teable env-drill-teable env-ensure-local-teable env-fresh-host-teable env-local-status-teable env-probe-teable probe-teable-recovery env-recover-teable env-restore-teable env-restore-teable-local env-restore-teable-service verify-env-teable-recovery verify-generated-release-artifacts-clean verify-runtime-supply-chain materialize-runtime-dependency-evidence verify-runtime-dependency-evidence verify-local-quality-gates verify-release-authority verify-codexea-e2e-exit-gate verify-codexea-fleet-shim-parity ci-local ci-gates ci-gates-postgres ci-gates-postgres-legacy property-release-gates hard-exit-gates runtime-hard-exit-gates ltd-release-gates memorial-gold-gates verify-release-assets verify-flagship-release-readiness verify-project-mode-runtime verify-whole-project-gold-map verify-memorial-voice-stability verify-memorial-gold-readiness verify-pocket-audio-archive verify-ltd-critical-entries verify-ltd-flagship-subset verify-ltd-provider-lanes verify-poppy-draft-workflow verify-design-mirror-bundle verify-design-full-mirror-parity repair-design-mirror-bundle repair-design_mirror-bundle docs-verify all-local

PYTHON_BIN ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
TEST_API_PYTEST_IGNORE ?= --ignore-glob=tests/test_chummer*.py --ignore-glob=tests/test_next90*.py --ignore=tests/test_design_mirror_bundle_contracts.py
TEST_API_PYTEST_DESELECT ?= \
	--deselect=tests/test_responses_api_contracts.py::test_tool_shim_direct_operator_unblock_hotspot_does_not_restart_from_new_shard_after_repo_diff \
	--deselect=tests/test_responses_api_contracts.py::test_tool_shim_decision_prefers_operator_repo_diff_followup_over_prompt_hotspot_after_shard_telemetry \
	--deselect=tests/test_responses_api_contracts.py::test_tool_shim_decision_prefers_operator_repo_hunks_after_repo_diff_followup \
	--deselect=tests/test_responses_api_contracts.py::test_tool_shim_decision_prefers_operator_verify_after_repo_hunks \
	--deselect=tests/test_responses_api_contracts.py::test_tool_shim_decision_prefers_operator_provider_health_after_verify \
	--deselect=tests/test_responses_api_contracts.py::test_tool_shim_decision_prefers_operator_live_routing_hotspots_after_provider_health \
	--deselect=tests/test_responses_api_contracts.py::test_tool_shim_direct_nested_post_staged_command_builds_repo_diff_after_allowed_worker_reads \
	--deselect=tests/test_responses_api_contracts.py::test_tool_shim_direct_nested_telemetry_first_command_uses_allowed_fleet_source_paths_from_runtime_json \
	--deselect=tests/test_responses_api_contracts.py::test_tool_shim_direct_nested_telemetry_first_command_survives_prompt_truncation_when_history_marks_operator_unblock \
	--deselect=tests/test_responses_api_contracts.py::test_tool_shim_direct_nested_telemetry_first_command_skips_equivalent_var_lib_telemetry_after_prompt_read \
	--deselect=tests/test_responses_api_contracts.py::test_tool_shim_direct_nested_telemetry_first_command_ignores_non_fleet_task_logs_and_repo_worklists \
	--deselect=tests/test_responses_api_contracts.py::test_tool_shim_build_staged_repo_diff_command_groups_existing_paths \
	--deselect=tests/test_responses_api_contracts.py::test_local_fleet_runtime_helpers_cover_output_token_and_command_selection

deploy:
	@echo "Refusing ambiguous deploy. Use 'make deploy-ea-prod' or 'make deploy-property' explicitly." >&2
	@exit 2

deploy-ea-prod:
	@set -eu; \
		if [ -n "$${TEABLE_API_KEY:-}" ]; then \
			echo "Ensuring EA env/config recovery artifacts from Teable before deploy."; \
			scripts/bootstrap_from_teable.sh --ensure-local >/dev/null; \
		fi; \
		if [ ! -f .env ]; then \
			cp .env.example .env; \
			chmod 600 .env; \
			echo "Created .env from .env.example. Fill values and rerun." >&2; \
			exit 1; \
		fi; \
		primary_path="$${EA_ONEDRIVE_ATTACHMENTS_HOST_PATH:-./data/onedrive_attachments}"; \
		fallback_path="$${EA_ONEDRIVE_ATTACHMENTS_FALLBACK_HOST_PATH:-.runtime/onedrive_attachments_fallback}"; \
		selected_path="$$primary_path"; \
		if ! ls "$$primary_path" >/dev/null 2>&1; then \
			mkdir -p "$$fallback_path"; \
			selected_path="$$fallback_path"; \
			echo "OneDrive attachment mount unavailable; deploying with fallback path $$selected_path" >&2; \
		fi; \
		COMPOSE_PROJECT_NAME=ea \
		PROPERTYQUARRY_USE_LEGACY_STACK=1 \
		EA_DEPLOY_PRIMARY_MODE=EA_CORE \
		EA_ONEDRIVE_ATTACHMENTS_HOST_PATH="$$selected_path" \
		bash scripts/deploy.sh --compose-override docker-compose.whatsapp-web-session.yml

deploy-ea-memorial:
	@set -eu; \
		if [ -n "$${TEABLE_API_KEY:-}" ]; then \
			echo "Ensuring EA env/config recovery artifacts from Teable before deploy."; \
			scripts/bootstrap_from_teable.sh --ensure-local >/dev/null; \
		fi; \
		if [ ! -f .env ]; then \
			cp .env.example .env; \
			chmod 600 .env; \
			echo "Created .env from .env.example. Fill values and rerun." >&2; \
			exit 1; \
		fi; \
		$(MAKE) verify-memorial-deploy-readiness; \
		COMPOSE_PROJECT_NAME=ea \
		PROPERTYQUARRY_USE_LEGACY_STACK=1 \
		EA_DEPLOY_PRIMARY_MODE=MEMORIAL \
		bash scripts/deploy.sh --compose-override docker-compose.memorial.yml

deploy-property:
	docker compose -f docker-compose.property.yml up -d --build --remove-orphans

deploy-legacy-ea-stack:
	COMPOSE_PROJECT_NAME=ea PROPERTYQUARRY_USE_LEGACY_STACK=1 bash scripts/deploy.sh

deploy-memory:
	COMPOSE_PROJECT_NAME=ea PROPERTYQUARRY_USE_LEGACY_STACK=1 EA_MEMORY_ONLY=1 bash scripts/deploy.sh

deploy-bootstrap:
	COMPOSE_PROJECT_NAME=ea PROPERTYQUARRY_USE_LEGACY_STACK=1 EA_BOOTSTRAP_DB=1 bash scripts/deploy.sh

bootstrap:
	bash scripts/db_bootstrap.sh

db-status:
	bash scripts/db_status.sh

db-size:
	bash scripts/db_size.sh

db-retention:
	bash scripts/db_retention.sh

smoke-api:
	bash scripts/smoke_api.sh

smoke-api-principal:
	bash scripts/smoke_api_principal.sh

smoke-postgres:
	bash scripts/smoke_postgres.sh

smoke-postgres-legacy:
	bash scripts/smoke_postgres.sh --legacy-fixture

smoke-help:
	bash scripts/smoke_help.sh

release-smoke: smoke-help smoke-api

release-preflight:
	$(MAKE) verify-release-assets
	$(MAKE) verify-runtime-supply-chain
	$(MAKE) verify-release-authority
	$(MAKE) verify-release-authority-runtime-authoritative
	$(MAKE) verify-flagship-release-readiness
	$(MAKE) verify-proactive-ooda-operator-status
	$(MAKE) verify-proactive-ooda-gold-acceptance
	$(MAKE) verify-telegram-audiobook-deployed-runtime
	$(MAKE) verify-project-mode-runtime
	$(MAKE) verify-whole-project-gold-map
	$(MAKE) verify-office-loop-goal-receipt
	$(MAKE) verify-executive-assistant-quality-readiness
	$(MAKE) verify-active-media-ltd-goal-bundle
	$(MAKE) verify-whole-project-signal-to-decision-receipt
	$(MAKE) verify-whole-project-scope-gap-audit
	$(MAKE) verify-generated-release-artifacts-clean
	$(MAKE) operator-help
	$(MAKE) release-smoke

send-audiobook-public-share-followups:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/send_audiobook_public_share_followups.py --force --pretty

release-docs:
	$(MAKE) docs-verify
	$(MAKE) operator-help

test-api:
	$(MAKE) materialize-release-assets
	CI=$${CI:-1} PYTHONPATH=ea EA_STORAGE_BACKEND=memory $(PYTHON_BIN) -m pytest -q tests $(TEST_API_PYTEST_IGNORE) $(TEST_API_PYTEST_DESELECT)

test-all:
	PYTHONPATH=ea $(PYTHON_BIN) -m pytest -q

test-postgres-contracts:
	bash scripts/test_postgres_contracts.sh

test-telegram-bot:
	PYTHONPATH=ea EA_STORAGE_BACKEND=memory $(PYTHON_BIN) -m pytest -q tests/e2e/test_telegram_bot_workflows.py tests/e2e/test_telegram_bot_outbound_workflows.py

openapi-export:
	bash scripts/export_openapi.sh

openapi-diff:
	bash scripts/diff_openapi.sh

openapi-prune:
	bash scripts/prune_openapi.sh

documentation-ai-public-openapi:
	$(PYTHON_BIN) scripts/materialize_documentation_ai_public_docs.py --require-source

verify-documentation-ai-public-docs:
	$(PYTHON_BIN) scripts/verify_documentation_ai_public_docs.py

materialize-documentation-ai-deployment-readiness: verify-documentation-ai-public-docs
	$(PYTHON_BIN) scripts/verify_documentation_ai_deployment_readiness.py --write .codex-studio/published/documentation_ai_deployment_readiness.generated.json

verify-documentation-ai-deployment-readiness: verify-documentation-ai-public-docs
	$(PYTHON_BIN) scripts/verify_documentation_ai_deployment_readiness.py --require-deployed

endpoints:
	bash scripts/list_endpoints.sh

version-info:
	bash scripts/version_info.sh

release-authority-probe: refresh-release-authority-status
	bash scripts/release_authority_probe.sh

materialize-deploy-context:
	$(PYTHON_BIN) scripts/materialize_deploy_context.py --pretty

refresh-deploy-context:
	$(PYTHON_BIN) scripts/materialize_deploy_context.py >/dev/null

verify-deploy-context: refresh-deploy-context
	$(PYTHON_BIN) scripts/verify_deploy_context.py --pretty

verify-release-authority-runtime: refresh-release-authority-status
	$(PYTHON_BIN) scripts/verify_release_authority_runtime.py --pretty

verify-release-authority-runtime-authoritative: refresh-release-authority-status
	$(PYTHON_BIN) scripts/verify_release_authority_runtime.py --pretty --require-authoritative

verify-memorial-deploy-readiness: materialize-memorial-operator-status refresh-release-authority-status
	$(PYTHON_BIN) scripts/verify_memorial_deploy_readiness.py --pretty

proactive-ooda:
	PYTHONPATH=ea $(PYTHON_BIN) scripts/run_proactive_ooda.py --pretty

.PHONY: bootstrap-proactive-ooda-teable
bootstrap-proactive-ooda-teable:
	$(PYTHON_BIN) scripts/bootstrap_proactive_ooda_teable_tables.py --create-missing --write-config

.PHONY: proactive-ooda-safe-work
proactive-ooda-safe-work:
	PYTHONPATH=ea $(PYTHON_BIN) scripts/materialize_proactive_ooda_safe_work.py --pretty

verify-proactive-ooda:
	PYTHONPATH=ea $(PYTHON_BIN) scripts/verify_proactive_ooda.py

verify-proactive-ooda-live-receipt:
	docker compose -f docker-compose.yml exec -T ea-proactive-ooda python /app/scripts/verify_proactive_ooda_live_receipt.py --pretty

materialize-proactive-ooda-operator-status:
	$(PYTHON_BIN) scripts/materialize_proactive_ooda_operator_status.py --pretty

verify-proactive-ooda-operator-status:
	$(PYTHON_BIN) scripts/materialize_proactive_ooda_operator_status.py
	$(PYTHON_BIN) scripts/verify_proactive_ooda_operator_status.py --pretty

materialize-proactive-ooda-gold-acceptance:
	$(PYTHON_BIN) scripts/materialize_proactive_ooda_operator_status.py
	$(PYTHON_BIN) scripts/materialize_proactive_ooda_gold_acceptance.py --pretty

verify-proactive-ooda-gold-acceptance:
	$(PYTHON_BIN) scripts/materialize_proactive_ooda_operator_status.py
	$(PYTHON_BIN) scripts/materialize_proactive_ooda_gold_acceptance.py
	$(PYTHON_BIN) scripts/verify_proactive_ooda_gold_acceptance.py --pretty

operator-summary:
	bash scripts/operator_summary.sh

provider-readiness:
	$(PYTHON_BIN) scripts/chummer6_provider_readiness.py

operator-help:
	@for s in scripts/deploy.sh scripts/db_bootstrap.sh scripts/db_status.sh scripts/db_size.sh scripts/db_retention.sh scripts/smoke_api.sh scripts/smoke_api_runtime.sh scripts/smoke_help.sh scripts/smoke_postgres.sh scripts/test_postgres_contracts.sh scripts/hard_exit_gates.sh scripts/runtime_hard_exit_gates.sh scripts/verify_codexea_e2e_exit_gate.sh scripts/verify_codexea_fleet_shim_parity.py scripts/verify_local_quality_gates.py scripts/verify_ltd_critical_entries.py scripts/verify_ltd_flagship_subset.py scripts/verify_ltd_provider_lanes.py scripts/bootstrap_from_teable.sh scripts/sync_env_to_teable.py scripts/ea_live_ops.py scripts/verify_proactive_ooda.py scripts/verify_proactive_ooda_live_receipt.py scripts/materialize_proactive_ooda_operator_status.py scripts/verify_proactive_ooda_operator_status.py scripts/materialize_proactive_ooda_gold_acceptance.py scripts/verify_proactive_ooda_gold_acceptance.py scripts/materialize_continuous_improvement_goal_posture.py scripts/verify_continuous_improvement_goal_posture.py scripts/materialize_poppy_draft_packet.py scripts/materialize_memorial_voice_roundtrip_exit_gate.py scripts/materialize_memorial_room_audio_receipt.py scripts/materialize_deploy_context.py scripts/verify_memorial_voice_stability_gate.py scripts/verify_memorial_gold_readiness.py scripts/materialize_project_mode_manifests.py scripts/verify_project_mode_manifests.py scripts/verify_project_mode_runtime.py scripts/materialize_whole_project_gold_map.py scripts/verify_whole_project_gold_map.py scripts/materialize_whatsapp_web_action_processor_readiness.py scripts/verify_whatsapp_web_action_processor_readiness.py ea/scripts/materialize_office_loop_goal_receipt.py ea/scripts/verify_office_loop_goal_receipt.py ea/scripts/materialize_executive_assistant_acceptance_evidence.py ea/scripts/verify_executive_assistant_acceptance_evidence.py ea/scripts/materialize_executive_assistant_quality_readiness.py ea/scripts/verify_executive_assistant_quality_readiness.py ea/scripts/materialize_whole_project_signal_to_decision_receipt.py ea/scripts/verify_whole_project_signal_to_decision_receipt.py ea/scripts/materialize_whole_project_scope_gap_audit.py ea/scripts/verify_whole_project_scope_gap_audit.py ea/scripts/materialize_active_media_ltd_goal_bundle.py ea/scripts/verify_active_media_ltd_goal_bundle.py ea/scripts/materialize_telegram_audiobook_live_readiness.py ea/scripts/verify_telegram_audiobook_live_readiness.py ea/scripts/verify_whatsapp_audiobook_live_delivery_receipt.py ea/scripts/verify_whatsapp_audiobook_operator_proof_bundle.py ea/scripts/verify_whatsapp_audiobook_public_share_playback.py scripts/list_endpoints.sh scripts/version_info.sh scripts/release_authority_probe.sh scripts/export_openapi.sh scripts/diff_openapi.sh scripts/prune_openapi.sh scripts/operator_summary.sh scripts/support_bundle.sh scripts/archive_tasks.sh scripts/bootstrap_payfunnels_propertyquarry.py scripts/bootstrap_emailit_propertyquarry.py scripts/verify_release_assets.sh scripts/chummer6_overlay_vision_readiness.py; do \
	  echo "===== $$s --help ====="; \
	  case "$$s" in \
	    *.py) $(PYTHON_BIN) $$s --help ;; \
	    *) bash $$s --help ;; \
	  esac; \
	  echo; \
	done

overlay-vision-check:
	$(PYTHON_BIN) scripts/chummer6_overlay_vision_readiness.py

overlay-vision-pull:
	$(PYTHON_BIN) scripts/chummer6_overlay_vision_readiness.py --pull

support-bundle:
	bash scripts/support_bundle.sh

tasks-archive:
	bash scripts/archive_tasks.sh

tasks-archive-prune:
	bash scripts/archive_tasks.sh --prune-done

tasks-archive-dry-run:
	bash scripts/archive_tasks.sh --dry-run

materialize-release-assets:
	PYTHONPATH=ea $(PYTHON_BIN) scripts/materialize_release_bundle.py --python-bin $(PYTHON_BIN)

materialize-release-manifest: materialize-deploy-context
	$(PYTHON_BIN) scripts/materialize_release_manifest.py

refresh-release-manifest: refresh-deploy-context
	$(PYTHON_BIN) scripts/materialize_release_manifest.py >/dev/null

materialize-release-authority-status: materialize-release-manifest
	$(PYTHON_BIN) scripts/materialize_release_authority_status.py

refresh-release-authority-status: refresh-release-manifest
	$(PYTHON_BIN) scripts/materialize_release_authority_status.py >/dev/null

materialize-continuous-improvement-goal-posture:
	$(PYTHON_BIN) scripts/materialize_continuous_improvement_goal_posture.py

verify-continuous-improvement-goal-posture:
	$(PYTHON_BIN) scripts/materialize_continuous_improvement_goal_posture.py
	$(PYTHON_BIN) scripts/verify_continuous_improvement_goal_posture.py --pretty

materialize-teable-env-recovery-readiness:
	$(PYTHON_BIN) scripts/materialize_teable_env_recovery_readiness.py

verify-teable-env-recovery-readiness:
	$(PYTHON_BIN) scripts/materialize_teable_env_recovery_readiness.py
	$(PYTHON_BIN) scripts/verify_teable_env_recovery_readiness.py

materialize-office-loop-goal-receipt:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_office_loop_goal_receipt.py

verify-office-loop-goal-receipt:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_office_loop_goal_receipt.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/verify_office_loop_goal_receipt.py

materialize-executive-assistant-acceptance-evidence:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_executive_assistant_acceptance_evidence.py

verify-executive-assistant-acceptance-evidence:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_executive_assistant_acceptance_evidence.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/verify_executive_assistant_acceptance_evidence.py

materialize-executive-assistant-quality-readiness:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_executive_assistant_acceptance_evidence.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_executive_assistant_quality_readiness.py

verify-executive-assistant-quality-readiness:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_executive_assistant_acceptance_evidence.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/verify_executive_assistant_acceptance_evidence.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_executive_assistant_quality_readiness.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/verify_executive_assistant_quality_readiness.py

materialize-whole-project-signal-to-decision-receipt:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_whole_project_signal_to_decision_receipt.py

verify-whole-project-signal-to-decision-receipt:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_whole_project_signal_to_decision_receipt.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/verify_whole_project_signal_to_decision_receipt.py

materialize-whole-project-scope-gap-audit:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_executive_assistant_acceptance_evidence.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_executive_assistant_quality_readiness.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_whole_project_signal_to_decision_receipt.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_whole_project_scope_gap_audit.py

verify-whole-project-scope-gap-audit:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_executive_assistant_acceptance_evidence.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/verify_executive_assistant_acceptance_evidence.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_executive_assistant_quality_readiness.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_whole_project_signal_to_decision_receipt.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/verify_whole_project_signal_to_decision_receipt.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_whole_project_scope_gap_audit.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/verify_whole_project_scope_gap_audit.py

materialize-active-media-ltd-goal-bundle:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_active_media_ltd_goal_bundle.py

verify-active-media-ltd-goal-bundle:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_active_media_ltd_goal_bundle.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/verify_active_media_ltd_goal_bundle.py

materialize-memorial-chatlab-external-evidence:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_memorial_chatlab_external_evidence.py \
		--provider "$${EA_MEMORIAL_CHATLAB_PROVIDER:-}" \
		--account-capability-evidence "$${CHATLAB_ACCOUNT_CAPABILITY_EVIDENCE:-}" \
		--runtime-probe-evidence "$${CHATLAB_RUNTIME_PROBE_EVIDENCE:-}" \
		--no-private-context-evidence "$${CHATLAB_NO_PRIVATE_CONTEXT_EVIDENCE:-}" \
		--guardrail-preservation-evidence "$${CHATLAB_GUARDRAIL_PRESERVATION_EVIDENCE:-}" \
		--pretty

materialize-manfred-realtime-conversation-readiness:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_manfred_realtime_conversation_readiness.py

verify-manfred-realtime-conversation-readiness:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_manfred_realtime_conversation_readiness.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/verify_manfred_realtime_conversation_readiness.py

materialize-telegram-audiobook-live-readiness:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_telegram_audiobook_live_readiness.py --runtime-container "$${EA_TELEGRAM_AUDIOBOOK_RUNTIME_CONTAINER:-ea-api}"

verify-telegram-audiobook-live-readiness:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_telegram_audiobook_live_readiness.py --runtime-container "$${EA_TELEGRAM_AUDIOBOOK_RUNTIME_CONTAINER:-ea-api}"
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/verify_telegram_audiobook_live_readiness.py --runtime-container "$${EA_TELEGRAM_AUDIOBOOK_RUNTIME_CONTAINER:-ea-api}" --require-deployed-runtime

verify-telegram-audiobook-deployed-runtime:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/verify_telegram_audiobook_live_readiness.py --runtime-container "$${EA_TELEGRAM_AUDIOBOOK_RUNTIME_CONTAINER:-ea-api}" --require-deployed-runtime --pretty

materialize-telegram-audiobook-live-delivery-receipt:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_telegram_audiobook_live_delivery_receipt.py

verify-telegram-audiobook-live-delivery-receipt:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_telegram_audiobook_live_delivery_receipt.py --require-pass

materialize-whatsapp-audiobook-local-intake-proof:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_whatsapp_audiobook_local_intake_proof.py

verify-whatsapp-audiobook-local-intake-proof:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_whatsapp_audiobook_local_intake_proof.py --require-pass
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/verify_whatsapp_audiobook_local_intake_proof.py

materialize-whatsapp-web-action-processor-readiness:
	$(PYTHON_BIN) scripts/materialize_whatsapp_web_action_processor_readiness.py

verify-whatsapp-web-action-processor-readiness:
	$(PYTHON_BIN) scripts/materialize_whatsapp_web_action_processor_readiness.py
	$(PYTHON_BIN) scripts/verify_whatsapp_web_action_processor_readiness.py

probe-whatsapp-pairing:
	$(PYTHON_BIN) scripts/ea_live_ops.py probe-whatsapp-pairing --format operator

send-whatsapp-pairing-telegram:
	$(PYTHON_BIN) scripts/ea_live_ops.py probe-whatsapp-pairing --send-telegram --format operator

materialize-whatsapp-audiobook-operator-proof-bundle:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_whatsapp_audiobook_operator_proof_bundle.py

verify-whatsapp-audiobook-operator-proof-bundle:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_whatsapp_audiobook_operator_proof_bundle.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/verify_whatsapp_audiobook_operator_proof_bundle.py

materialize-whatsapp-audiobook-live-delivery-receipt:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_whatsapp_audiobook_live_delivery_receipt.py

verify-whatsapp-audiobook-live-delivery-receipt:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_whatsapp_audiobook_live_delivery_receipt.py
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/verify_whatsapp_audiobook_live_delivery_receipt.py

verify-whatsapp-audiobook-public-share-playback:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/verify_whatsapp_audiobook_public_share_playback.py --require-pass

materialize-whatsapp-audiobook-live-voice-selection-shadow:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_whatsapp_audiobook_live_voice_selection_shadow.py

verify-whatsapp-audiobook-live-voice-selection-shadow:
	PYTHONPATH=ea $(PYTHON_BIN) ea/scripts/materialize_whatsapp_audiobook_live_voice_selection_shadow.py --require-pass

materialize-telegram-video-delivery-operator-receipt:
	PYTHONPATH=ea $(PYTHON_BIN) scripts/materialize_telegram_video_delivery_receipt.py

materialize-telegram-video-delivery-live-receipt:
	PYTHONPATH=ea $(PYTHON_BIN) scripts/materialize_telegram_video_delivery_live_receipt.py

materialize-telegram-video-delivery-receipts:
	$(MAKE) materialize-telegram-video-delivery-operator-receipt
	$(MAKE) materialize-telegram-video-delivery-live-receipt
	PYTHONPATH=ea $(PYTHON_BIN) scripts/materialize_whole_project_gold_map.py

verify-telegram-video-delivery-live-receipt:
	PYTHONPATH=ea $(PYTHON_BIN) scripts/materialize_telegram_video_delivery_live_receipt.py --require-pass

verify-generated-release-artifacts-clean:
	$(MAKE) materialize-release-assets
	$(PYTHON_BIN) scripts/verify_generated_release_artifacts_clean.py

verify-runtime-supply-chain:
	$(PYTHON_BIN) scripts/verify_runtime_supply_chain.py

materialize-runtime-dependency-evidence:
	$(PYTHON_BIN) scripts/materialize_runtime_dependency_evidence.py

verify-runtime-dependency-evidence:
	$(MAKE) materialize-runtime-dependency-evidence
	$(PYTHON_BIN) scripts/verify_runtime_dependency_evidence.py

verify-local-quality-gates:
	$(PYTHON_BIN) scripts/verify_local_quality_gates.py

verify-codexea-fleet-shim-parity:
	$(PYTHON_BIN) scripts/verify_codexea_fleet_shim_parity.py

verify-release-authority: refresh-release-manifest
	$(PYTHON_BIN) scripts/verify_release_authority.py --pretty

verify-codexea-e2e-exit-gate:
	bash scripts/verify_codexea_e2e_exit_gate.sh

ci-local:
	$(PYTHON_BIN) -m compileall -q ea/app
	$(PYTHON_BIN) -m compileall -q tests
	bash scripts/smoke_help.sh

# Run the local release gate order from one entrypoint.
ci-gates:
	$(MAKE) smoke-help
	$(MAKE) ci-local
	$(MAKE) verify-codexea-e2e-exit-gate
	$(MAKE) verify-codexea-fleet-shim-parity
	$(MAKE) verify-local-quality-gates
	$(MAKE) verify-runtime-dependency-evidence
	$(MAKE) test-api
	$(MAKE) ltd-release-gates
	$(MAKE) verify-release-assets
	$(MAKE) verify-flagship-release-readiness
	$(PYTHON_BIN) scripts/verify_project_mode_manifests.py
	$(MAKE) verify-project-mode-runtime
	$(MAKE) verify-whole-project-gold-map
	$(MAKE) verify-generated-release-artifacts-clean

ci-gates-postgres:
	$(MAKE) ci-gates
	$(MAKE) smoke-postgres

ci-gates-postgres-legacy:
	$(MAKE) ci-gates
	$(MAKE) smoke-postgres-legacy

property-release-gates:
	bash scripts/property_release_gates.sh

hard-exit-gates:
	bash scripts/hard_exit_gates.sh

runtime-hard-exit-gates:
	bash scripts/runtime_hard_exit_gates.sh

memorial-gold-gates:
	$(MAKE) verify-memorial-runtime-overlay
	$(MAKE) verify-memorial-voice-stability
	$(MAKE) verify-memorial-gold-readiness

materialize-memorial-public-voice-gold:
	$(PYTHON_BIN) scripts/materialize_memorial_voice_roundtrip_exit_gate.py \
		--base-url "$${MEMORIAL_PUBLIC_ORIGIN:?Set MEMORIAL_PUBLIC_ORIGIN to the deployed memorial origin}" \
		--slug "$${MEMORIAL_PUBLIC_SLUG:-manfred}" \
		--gold-mode \
		--require-public-origin \
		--direct-min-f1 "$${MEMORIAL_GOLD_DIRECT_TTS_F1_MIN:-0.92}" \
		--conversation-min-f1 "$${MEMORIAL_GOLD_CONVERSATION_AUDIO_F1_MIN:-0.90}" \
		--critical-token worum \
		--critical-token geht \
		--critical-token es \
		--output .codex-studio/published/memorial_voice_roundtrip_public_origin.generated.json

materialize-memorial-public-browser-gold:
	$(PYTHON_BIN) scripts/measure_memorial_live_browser.py \
		--base-url "$${MEMORIAL_PUBLIC_ORIGIN:?Set MEMORIAL_PUBLIC_ORIGIN to the deployed memorial origin}" \
		--slug "$${MEMORIAL_PUBLIC_SLUG:-manfred}" \
		--real-stt \
		--exit-gate \
		--gold-mode \
		--require-public-origin \
		--max-first-answer-ms "$${MEMORIAL_GOLD_MAX_BROWSER_FIRST_ANSWER_MS:-4500}" \
		--output .codex-studio/published/memorial_realtime_browser_public_origin.generated.json

materialize-memorial-public-browser-meaningful-gold:
	$(PYTHON_BIN) scripts/measure_memorial_live_browser.py \
		--base-url "$${MEMORIAL_PUBLIC_ORIGIN:?Set MEMORIAL_PUBLIC_ORIGIN to the deployed memorial origin}" \
		--slug "$${MEMORIAL_PUBLIC_SLUG:-manfred}" \
		--prompt-text "$${MEMORIAL_MEANINGFUL_BROWSER_PROMPT:-Was war dir bei Gerechtigkeit wichtig?}" \
		--text-prompt \
		--exit-gate \
		--gold-mode \
		--require-public-origin \
		--max-first-answer-ms "$${MEMORIAL_GOLD_MAX_MEANINGFUL_BROWSER_FIRST_ANSWER_MS:-8000}" \
		--output .codex-studio/published/memorial_realtime_browser_meaningful_public_origin.generated.json

materialize-memorial-public-auto-receipts-clean:
	$(PYTHON_BIN) scripts/materialize_memorial_public_auto_receipts_clean.py \
		--python-bin "$(PYTHON_BIN)" \
		--base-url "$${MEMORIAL_PUBLIC_ORIGIN:?Set MEMORIAL_PUBLIC_ORIGIN to the deployed memorial origin}" \
		--slug "$${MEMORIAL_PUBLIC_SLUG:-manfred}" \
		--direct-min-f1 "$${MEMORIAL_GOLD_DIRECT_TTS_F1_MIN:-0.92}" \
		--conversation-min-f1 "$${MEMORIAL_GOLD_CONVERSATION_AUDIO_F1_MIN:-0.90}" \
		--browser-first-answer-ms "$${MEMORIAL_GOLD_MAX_BROWSER_FIRST_ANSWER_MS:-4500}" \
		--meaningful-browser-first-answer-ms "$${MEMORIAL_GOLD_MAX_MEANINGFUL_BROWSER_FIRST_ANSWER_MS:-8000}" \
		--meaningful-prompt "$${MEMORIAL_MEANINGFUL_BROWSER_PROMPT:-Was war dir bei Gerechtigkeit wichtig?}"

materialize-memorial-room-audio-attestation-packet:
	$(PYTHON_BIN) scripts/materialize_memorial_room_audio_attestation_packet.py \
		--base-url "$${MEMORIAL_PUBLIC_ORIGIN:-https://example.test}" \
		--slug "$${MEMORIAL_PUBLIC_SLUG:-manfred}"

materialize-memorial-room-audio-gold:
	$(PYTHON_BIN) scripts/materialize_memorial_room_audio_receipt.py \
		--base-url "$${MEMORIAL_PUBLIC_ORIGIN:?Set MEMORIAL_PUBLIC_ORIGIN to the deployed memorial origin}" \
		--slug "$${MEMORIAL_PUBLIC_SLUG:-manfred}" \
		--reviewer "$${MEMORIAL_ROOM_REVIEWER:?Set MEMORIAL_ROOM_REVIEWER to the listener/operator name}" \
		--device-label "$${MEMORIAL_ROOM_DEVICE_LABEL:-}" \
		--speaker-label "$${MEMORIAL_ROOM_SPEAKER_LABEL:-}" \
		--room-label "$${MEMORIAL_ROOM_LABEL:-}" \
		--notes "$${MEMORIAL_ROOM_NOTES:-}" \
		--manual-attestation-id "$${MEMORIAL_ROOM_ATTESTATION_ID:?Set MEMORIAL_ROOM_ATTESTATION_ID from the signed/manual room review}" \
		--manual-attestation-signed-at "$${MEMORIAL_ROOM_ATTESTATION_SIGNED_AT:?Set MEMORIAL_ROOM_ATTESTATION_SIGNED_AT from the signed/manual room review}" \
		--manual-attestation-source "$${MEMORIAL_ROOM_ATTESTATION_SOURCE:-operator_room_review}" \
		--require-public-origin \
		--actual-device-checked \
		--actual-speaker-checked \
		--first-syllable-not-clipped \
		--intelligibility-confirmed \
		--answer-text-fallback-visible \
		--no-internet-search-confirmed \
		--normal-spoken-turn-confirmed \
		--interruption-behavior-confirmed \
		--retry-path-confirmed

materialize-memorial-room-audio-gold-clean:
	$(PYTHON_BIN) scripts/materialize_memorial_room_audio_receipt_clean.py \
		--base-url "$${MEMORIAL_PUBLIC_ORIGIN:?Set MEMORIAL_PUBLIC_ORIGIN to the deployed memorial origin}" \
		--slug "$${MEMORIAL_PUBLIC_SLUG:-manfred}" \
		--reviewer "$${MEMORIAL_ROOM_REVIEWER:?Set MEMORIAL_ROOM_REVIEWER to the listener/operator name}" \
		--device-label "$${MEMORIAL_ROOM_DEVICE_LABEL:-}" \
		--speaker-label "$${MEMORIAL_ROOM_SPEAKER_LABEL:-}" \
		--room-label "$${MEMORIAL_ROOM_LABEL:-}" \
		--notes "$${MEMORIAL_ROOM_NOTES:-}" \
		--manual-attestation-id "$${MEMORIAL_ROOM_ATTESTATION_ID:?Set MEMORIAL_ROOM_ATTESTATION_ID from the signed/manual room review}" \
		--manual-attestation-signed-at "$${MEMORIAL_ROOM_ATTESTATION_SIGNED_AT:?Set MEMORIAL_ROOM_ATTESTATION_SIGNED_AT from the signed/manual room review}" \
		--manual-attestation-source "$${MEMORIAL_ROOM_ATTESTATION_SOURCE:-operator_room_review}"

materialize-memorial-public-gold:
	$(PYTHON_BIN) scripts/materialize_memorial_public_gold_clean.py \
		--python-bin "$(PYTHON_BIN)" \
		--base-url "$${MEMORIAL_PUBLIC_ORIGIN:?Set MEMORIAL_PUBLIC_ORIGIN to the deployed memorial origin}" \
		--slug "$${MEMORIAL_PUBLIC_SLUG:-manfred}" \
		--reviewer "$${MEMORIAL_ROOM_REVIEWER:?Set MEMORIAL_ROOM_REVIEWER to the listener/operator name}" \
		--device-label "$${MEMORIAL_ROOM_DEVICE_LABEL:-}" \
		--speaker-label "$${MEMORIAL_ROOM_SPEAKER_LABEL:-}" \
		--room-label "$${MEMORIAL_ROOM_LABEL:-}" \
		--notes "$${MEMORIAL_ROOM_NOTES:-}" \
		--manual-attestation-id "$${MEMORIAL_ROOM_ATTESTATION_ID:?Set MEMORIAL_ROOM_ATTESTATION_ID from the signed/manual room review}" \
		--manual-attestation-signed-at "$${MEMORIAL_ROOM_ATTESTATION_SIGNED_AT:?Set MEMORIAL_ROOM_ATTESTATION_SIGNED_AT from the signed/manual room review}" \
		--manual-attestation-source "$${MEMORIAL_ROOM_ATTESTATION_SOURCE:-operator_room_review}" \
		--direct-min-f1 "$${MEMORIAL_GOLD_DIRECT_TTS_F1_MIN:-0.92}" \
		--conversation-min-f1 "$${MEMORIAL_GOLD_CONVERSATION_AUDIO_F1_MIN:-0.90}" \
		--browser-first-answer-ms "$${MEMORIAL_GOLD_MAX_BROWSER_FIRST_ANSWER_MS:-4500}" \
		--meaningful-browser-first-answer-ms "$${MEMORIAL_GOLD_MAX_MEANINGFUL_BROWSER_FIRST_ANSWER_MS:-8000}" \
		--meaningful-prompt "$${MEMORIAL_MEANINGFUL_BROWSER_PROMPT:-Was war dir bei Gerechtigkeit wichtig?}"
	MEMORIAL_REQUIRE_MEANINGFUL_BROWSER_RECEIPT=1 $(MAKE) verify-memorial-gold-readiness

materialize-memorial-phrase-bank:
	$(PYTHON_BIN) scripts/materialize_memorial_phrase_bank.py

materialize-memorial-operator-status:
	$(PYTHON_BIN) scripts/materialize_memorial_operator_status.py

.PHONY: inspect-source-dirty-groups verify-source-dirty-groups repair-design-mirror-bundle
inspect-source-dirty-groups:
	$(PYTHON_BIN) scripts/inspect_source_dirty_groups.py

verify-source-dirty-groups:
	$(PYTHON_BIN) scripts/verify_source_dirty_groups.py

materialize-memorial-stt-provider-benchmark:
	PYTHONPATH=ea $(PYTHON_BIN) scripts/benchmark_memorial_stt_providers.py

verify-memorial-stt-provider-benchmark:
	PYTHONPATH=ea $(PYTHON_BIN) scripts/benchmark_memorial_stt_providers.py --require-production-eligible

sync-memorial-public-sources-teable:
	PYTHONPATH=ea $(PYTHON_BIN) scripts/sync_memorial_public_sources_to_teable.py

env-backup-teable:
	$(PYTHON_BIN) scripts/sync_env_to_teable.py backup --include-values

env-history-backup-teable:
	$(PYTHON_BIN) scripts/sync_env_to_teable.py history-backup

env-bootstrap-teable:
	$(PYTHON_BIN) scripts/sync_env_to_teable.py bootstrap

env-check-teable:
	$(PYTHON_BIN) scripts/sync_env_to_teable.py check

env-disable-extra-teable:
	$(PYTHON_BIN) scripts/sync_env_to_teable.py disable-extras

env-drill-teable:
	$(PYTHON_BIN) scripts/sync_env_to_teable.py drill

env-ensure-local-teable:
	@scripts/bootstrap_from_teable.sh --ensure-local

env-fresh-host-teable:
	@scripts/bootstrap_from_teable.sh --fresh-host

env-local-status-teable:
	$(PYTHON_BIN) scripts/sync_env_to_teable.py local-status

probe-teable-recovery:
	$(PYTHON_BIN) scripts/ea_live_ops.py probe-teable-recovery --format operator

env-probe-teable:
	@scripts/bootstrap_from_teable.sh --probe

env-recover-teable:
	@scripts/bootstrap_from_teable.sh

env-restore-teable:
	$(PYTHON_BIN) scripts/sync_env_to_teable.py restore --output-path .env --source-scope ea_root

env-restore-teable-local:
	$(PYTHON_BIN) scripts/sync_env_to_teable.py restore --output-path .env.local --source-scope ea_root_local

env-restore-teable-service:
	$(PYTHON_BIN) scripts/sync_env_to_teable.py restore --output-path ea/.env --source-scope ea_service

verify-env-teable-recovery:
	$(PYTHON_BIN) scripts/sync_env_to_teable.py verify

ltd-release-gates:
	$(MAKE) verify-ltd-critical-entries
	$(MAKE) verify-ltd-flagship-subset
	$(MAKE) verify-ltd-provider-lanes

verify-release-assets:
	$(MAKE) materialize-release-assets
	$(MAKE) verify-release-authority
	$(MAKE) verify-release-authority-runtime-authoritative
	bash scripts/verify_release_assets.sh

verify-flagship-release-readiness:
	$(MAKE) materialize-release-assets
	$(PYTHON_BIN) scripts/verify_flagship_release_readiness.py

verify-project-mode-runtime:
	$(MAKE) materialize-release-assets
	PYTHONPATH=ea $(PYTHON_BIN) scripts/verify_project_mode_manifests.py
	PYTHONPATH=ea $(PYTHON_BIN) scripts/verify_project_mode_runtime.py

verify-project-mode-runtime-memorial:
	$(MAKE) materialize-release-assets
	PYTHONPATH=ea $(PYTHON_BIN) scripts/verify_project_mode_runtime.py --mode memorial

verify-whole-project-gold-map:
	$(MAKE) materialize-release-assets
	PYTHONPATH=ea $(PYTHON_BIN) scripts/verify_whole_project_gold_map.py

verify-memorial-voice-stability:
	PYTHONPATH=ea $(PYTHON_BIN) scripts/verify_memorial_voice_stability_gate.py

verify-memorial-runtime-overlay:
	$(PYTHON_BIN) scripts/verify_memorial_runtime_overlay.py --pretty

verify-memorial-gold-readiness:
	PYTHONPATH=ea $(PYTHON_BIN) scripts/verify_memorial_gold_readiness.py

verify-pocket-audio-archive:
	$(PYTHON_BIN) scripts/verify_pocket_audio_archive.py

verify-ltd-critical-entries:
	$(PYTHON_BIN) scripts/verify_ltd_critical_entries.py

verify-ltd-flagship-subset:
	$(PYTHON_BIN) scripts/verify_ltd_flagship_subset.py

verify-ltd-provider-lanes:
	$(PYTHON_BIN) scripts/verify_ltd_provider_lanes.py

verify-poppy-draft-workflow:
	PYTHONPATH=ea $(PYTHON_BIN) -m pytest -q tests/test_ltd_provider_governance.py -k poppy

verify-design-mirror-bundle:
	$(PYTHON_BIN) scripts/verify_design_mirror_bundle.py

verify-design-full-mirror-parity:
	$(PYTHON_BIN) scripts/verify_full_design_mirror_parity.py

repair-design-mirror-bundle:
	bash scripts/repair_design_mirror_bundle.sh

repair-design_mirror-bundle: repair-design-mirror-bundle

docs-verify: verify-release-assets verify-documentation-ai-public-docs

all-local: ci-local verify-codexea-e2e-exit-gate verify-codexea-fleet-shim-parity verify-local-quality-gates verify-release-assets verify-flagship-release-readiness verify-whole-project-gold-map verify-generated-release-artifacts-clean
