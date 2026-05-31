.PHONY: deploy deploy-memory deploy-bootstrap bootstrap db-status db-size db-retention smoke-api smoke-postgres smoke-postgres-legacy smoke-help release-smoke release-preflight release-docs test-api test-postgres-contracts test-telegram-bot openapi-export openapi-diff openapi-prune endpoints version-info operator-summary operator-help provider-readiness overlay-vision-check overlay-vision-pull support-bundle tasks-archive tasks-archive-prune tasks-archive-dry-run materialize-release-assets verify-generated-release-artifacts-clean ci-local ci-gates ci-gates-postgres ci-gates-postgres-legacy verify-release-assets verify-flagship-release-readiness verify-design-mirror-bundle verify-design-full-mirror-parity repair-design-mirror-bundle docs-verify all-local

PYTHON_BIN ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
TEST_API_PYTEST_IGNORE ?= --ignore-glob=tests/test_chummer*.py --ignore-glob=tests/test_next90*.py --ignore=tests/test_design_mirror_bundle_contracts.py

deploy:
	bash scripts/deploy.sh

deploy-memory:
	EA_MEMORY_ONLY=1 bash scripts/deploy.sh

deploy-bootstrap:
	EA_BOOTSTRAP_DB=1 bash scripts/deploy.sh

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

smoke-postgres:
	bash scripts/smoke_postgres.sh

smoke-postgres-legacy:
	bash scripts/smoke_postgres.sh --legacy-fixture

smoke-help:
	bash scripts/smoke_help.sh

release-smoke: smoke-help smoke-api

release-preflight:
	$(MAKE) verify-release-assets
	$(MAKE) verify-flagship-release-readiness
	$(MAKE) verify-generated-release-artifacts-clean
	$(MAKE) operator-help
	$(MAKE) release-smoke

release-docs:
	$(MAKE) docs-verify
	$(MAKE) operator-help

test-api:
	$(MAKE) materialize-release-assets
	PYTHONPATH=ea EA_STORAGE_BACKEND=memory $(PYTHON_BIN) -m pytest -q tests $(TEST_API_PYTEST_IGNORE)

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

endpoints:
	bash scripts/list_endpoints.sh

version-info:
	bash scripts/version_info.sh

operator-summary:
	bash scripts/operator_summary.sh

provider-readiness:
	$(PYTHON_BIN) scripts/chummer6_provider_readiness.py

operator-help:
	@for s in scripts/deploy.sh scripts/db_bootstrap.sh scripts/db_status.sh scripts/db_size.sh scripts/db_retention.sh scripts/smoke_api.sh scripts/smoke_help.sh scripts/smoke_postgres.sh scripts/test_postgres_contracts.sh scripts/list_endpoints.sh scripts/version_info.sh scripts/export_openapi.sh scripts/diff_openapi.sh scripts/prune_openapi.sh scripts/operator_summary.sh scripts/support_bundle.sh scripts/archive_tasks.sh scripts/verify_release_assets.sh scripts/chummer6_overlay_vision_readiness.py; do \
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
	$(PYTHON_BIN) scripts/materialize_ea_browser_workflow_proof.py
	$(PYTHON_BIN) scripts/materialize_ea_flagship_release_gate.py
	$(PYTHON_BIN) scripts/materialize_weekly_product_pulse.py

verify-generated-release-artifacts-clean:
	$(MAKE) materialize-release-assets
	$(PYTHON_BIN) scripts/verify_generated_release_artifacts_clean.py

ci-local:
	$(PYTHON_BIN) -m compileall -q ea/app
	$(PYTHON_BIN) -m compileall -q tests
	bash scripts/smoke_help.sh

# Mirror the smoke-runtime CI gate order locally from one entrypoint.
ci-gates:
	$(MAKE) smoke-help
	$(MAKE) ci-local
	$(MAKE) test-api
	$(MAKE) verify-release-assets
	$(MAKE) verify-flagship-release-readiness
	$(MAKE) verify-generated-release-artifacts-clean

ci-gates-postgres:
	$(MAKE) ci-gates
	$(MAKE) smoke-postgres

ci-gates-postgres-legacy:
	$(MAKE) ci-gates
	$(MAKE) smoke-postgres-legacy

verify-release-assets:
	$(MAKE) materialize-release-assets
	bash scripts/verify_release_assets.sh

verify-flagship-release-readiness:
	$(MAKE) materialize-release-assets
	$(PYTHON_BIN) scripts/verify_flagship_release_readiness.py

verify-design-mirror-bundle:
	$(PYTHON_BIN) scripts/verify_design_mirror_bundle.py

verify-design-full-mirror-parity:
	$(PYTHON_BIN) scripts/verify_full_design_mirror_parity.py

repair-design-mirror-bundle:
	bash scripts/repair_design_mirror_bundle.sh

docs-verify: verify-release-assets

all-local: ci-local verify-release-assets verify-flagship-release-readiness verify-generated-release-artifacts-clean
