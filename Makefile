.PHONY: deploy deploy-memory deploy-bootstrap bootstrap db-status smoke-api test-api openapi-export openapi-diff openapi-prune endpoints version-info operator-summary support-bundle tasks-archive tasks-archive-prune tasks-archive-dry-run ci-local verify-release-assets

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

smoke-api:
	bash scripts/smoke_api.sh

test-api:
	PYTHONPATH=ea EA_LEDGER_BACKEND=memory pytest -q tests/smoke_runtime_api.py

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
	python3 -m py_compile tests/smoke_runtime_api.py

verify-release-assets:
	bash scripts/verify_release_assets.sh
