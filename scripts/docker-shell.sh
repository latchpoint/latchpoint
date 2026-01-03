#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT_DIR/scripts/docker-env.sh"

cd "$ROOT_DIR"
SERVICE="${1:-backend}"
shift || true
if [ "$#" -gt 0 ]; then
  docker compose run --rm "$SERVICE" "$@"
else
  docker compose run --rm "$SERVICE" sh
fi
