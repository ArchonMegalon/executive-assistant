.PHONY: deploy deploy-memory deploy-bootstrap bootstrap db-status smoke-api test-api openapi-export openapi-diff openapi-prune

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
