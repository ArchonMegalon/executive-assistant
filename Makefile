.PHONY: deploy deploy-memory deploy-bootstrap bootstrap db-status db-size db-retention smoke-api smoke-postgres smoke-postgres-legacy smoke-help release-smoke release-preflight release-docs test-api openapi-export openapi-diff openapi-prune endpoints version-info operator-summary operator-help support-bundle tasks-archive tasks-archive-prune tasks-archive-dry-run ci-local ci-gates ci-gates-postgres ci-gates-postgres-legacy verify-release-assets docs-verify all-local

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
	$(MAKE) operator-help
	$(MAKE) release-smoke

release-docs:
	$(MAKE) docs-verify
	$(MAKE) operator-help

test-api:
	PYTHONPATH=ea EA_STORAGE_BACKEND=memory pytest -q tests

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

operator-help:
	@for s in scripts/deploy.sh scripts/db_bootstrap.sh scripts/db_status.sh scripts/db_size.sh scripts/db_retention.sh scripts/smoke_api.sh scripts/smoke_help.sh scripts/smoke_postgres.sh scripts/list_endpoints.sh scripts/version_info.sh scripts/export_openapi.sh scripts/diff_openapi.sh scripts/prune_openapi.sh scripts/operator_summary.sh scripts/support_bundle.sh scripts/archive_tasks.sh scripts/verify_release_assets.sh; do \
	  echo "===== $$s --help ====="; \
	  bash $$s --help; \
	  echo; \
	done

support-bundle:
	bash scripts/support_bundle.sh

tasks-archive:
	bash scripts/archive_tasks.sh

tasks-archive-prune:
	bash scripts/archive_tasks.sh --prune-done

tasks-archive-dry-run:
	bash scripts/archive_tasks.sh --dry-run

ci-local:
	python3 -m compileall -q ea/app
	python3 -m compileall -q tests
	bash scripts/smoke_help.sh

# Mirror the smoke-runtime CI gate order locally from one entrypoint.
ci-gates:
	$(MAKE) smoke-help
	$(MAKE) ci-local
	$(MAKE) test-api
	$(MAKE) verify-release-assets

ci-gates-postgres:
	$(MAKE) ci-gates
	$(MAKE) smoke-postgres

ci-gates-postgres-legacy:
	$(MAKE) ci-gates
	$(MAKE) smoke-postgres-legacy

verify-release-assets:
	bash scripts/verify_release_assets.sh

docs-verify: verify-release-assets

all-local: ci-local verify-release-assets
