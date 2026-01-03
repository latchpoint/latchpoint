# Docker helper scripts

This repo uses a split **dev** `docker-compose.yml`:
- `backend` (Django/Daphne) on port `8000` (internal)
- `frontend` (Vite) on port `5427` (host) → proxies `/api` and `/ws` to `backend`

Production remains combined via `docker-compose.prod.yml` (`app` service).

## Common commands

- Start dev stack: `./scripts/docker-up.sh`
- Stop dev stack: `./scripts/docker-down.sh`
- Rebuild backend only: `./scripts/docker-rebuild-backend.sh`
- Shell into backend (default): `./scripts/docker-shell.sh`
- Shell into frontend: `./scripts/docker-shell.sh frontend`

