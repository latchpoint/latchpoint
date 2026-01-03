# ADR 0055: GitHub Actions CI + GHCR Image Publishing

## Status
Implemented

## Context

We need repeatable automation for:
- Running backend tests on every branch commit, pull request, and tag.
- Building and publishing a single “full stack” production image (Nginx serving the built frontend + Daphne backend) to GitHub Container Registry (GHCR) when changes land on `main` and when a release tag is pushed.

Today, tests and image builds are developer-driven and can drift across environments.

## Decision

1) Add a **CI workflow** that runs Django tests in Docker on:
   - `push` to any branch
   - `pull_request`
   - `push` of any tag

   The workflow runs tests via the existing `backend` container image target and uses SQLite fallback to avoid requiring Postgres in CI.

2) Add a **build/publish workflow** that builds the Docker `production` target and pushes to GHCR on:
   - `push` to `main`
   - `push` of any tag

   Image naming and tags:
   - Image: `ghcr.io/<owner>/latchpoint`
   - Tags:
     - `latest` (default branch only)
     - `sha-<short>` (commit builds)
     - `<tag>` (tag builds)

## Alternatives Considered

- Run tests outside Docker (pure Python + services): faster, but risks diverging from the containerized runtime and requires more host setup (Postgres, system deps).
- Publish images only on tags: simpler, but no “latest main” artifact for easy deployments and testing.
- Publish separate backend/frontend images: more flexible, but increases deployment complexity; this project already has a unified production service (ADR 0031).

## Consequences

- CI becomes slower than pure host Python tests (container build), but is closer to production behavior.
- SQLite in CI may miss Postgres-specific issues; we can add an opt-in Postgres test job later if needed.
- Publishing on `main` makes rollbacks easier (pin to `sha-*`), but requires GHCR package permissions to be enabled.

## Todos

- [x] Add CI workflow to run backend + frontend tests (branches, PRs, tags).
- [x] Add build/publish workflow to push `production` image to GHCR (default branch and tags).
- [x] Update docs/compose to reference the published image.
- [ ] Optionally add a CI job variant that runs tests against Postgres (nightly or on demand).
- [ ] Add a lightweight “smoke” job that boots the `production` image and validates the health endpoint (if/when one exists).
