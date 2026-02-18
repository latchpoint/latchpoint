#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT_DIR/scripts/docker-env.sh"

cd "$ROOT_DIR"
docker compose run --rm --entrypoint sh backend -c "cd backend && python manage.py test --keepdb \
alarm.tests.test_permission_matrix_sensitive_api \
alarm.tests.test_concurrency_api \
alarm.tests.test_websocket \
notifications.tests.test_outbox \
alarm.tests.test_idempotency_api \
alarm.tests.test_integration_fault_mapping_api \
alarm.tests.test_frontend_contract_smoke_api"
