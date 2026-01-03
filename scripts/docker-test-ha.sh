#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT_DIR/scripts/docker-env.sh"

cd "$ROOT_DIR"
docker compose run --rm -e ALLOW_HOME_ASSISTANT_IN_TESTS=true backend sh -c "cd backend && python manage.py test"
