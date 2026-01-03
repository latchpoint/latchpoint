# ADR 0054: Frontend Testing Strategy

## Status
Implemented

## Context

The frontend is a React + TypeScript SPA (Vite) with non-trivial client behavior:
- Auth flows (session cookies + CSRF priming)
- Data fetching/caching (React Query)
- Client state (Zustand)
- Forms + validation (react-hook-form + zod)
- Feature-level error boundaries and standardized API error shapes

Today, the frontend has no automated test harness. This makes it easy to regress:
- Routing and setup wizard flows
- Error handling and messaging consistency
- API client behavior (CSRF, credentials, envelopes)
- Store/query interactions (cache invalidation, refetch triggers)

We need a standard testing approach that:
- Is fast for local iteration
- Aligns with Vite and modern React tooling
- Encourages “test behavior, not implementation” for UI
- Provides a place for a small set of end-to-end smoke tests

## Decision

Adopt a 3-tier frontend testing strategy:

1) **Unit tests** (pure logic)
   - Target: `frontend/src/lib/*`, small helpers, and deterministic transformations.
   - Tooling: `vitest` (test runner; node environment).

2) **Component + integration tests** (UI behavior)
   - Target: pages/components with user-visible behavior, including query + store interactions.
   - Tooling: **React Testing Library** (`@testing-library/react` + `@testing-library/user-event`) running on `vitest` in `jsdom`.
   - Network: mock HTTP with `msw` (Mock Service Worker) and test-only handlers.
   - Avoid snapshot-heavy tests; prefer assertions on accessible roles/text and state changes.

3) **End-to-end smoke tests** (critical flows)
   - Target: a small number of high-value flows (login, onboarding/setup gating, dashboard load).
   - Tooling: `playwright` in CI (and runnable locally).
   - Scope: smoke coverage only; do not attempt to fully replicate backend test coverage in E2E.

### Conventions

- Test file naming:
  - Unit: `*.test.ts`
  - UI: `*.test.tsx`
- Folder layout:
  - Shared test helpers: `frontend/src/test/` (render helpers, MSW server/handlers, fixtures)
- What to mock:
  - Prefer MSW for HTTP; avoid mocking `fetch` directly.
  - Prefer real React Query + real Zustand stores with test helpers for setup/reset.
- Determinism:
  - Use fake timers only where necessary (timers/countdowns); restore after each test.
  - Avoid brittle timing assertions; prefer `findBy*` / `waitFor`.

## Alternatives Considered

- **Jest**: mature ecosystem, but slower iteration and less aligned with Vite tooling.
- **Cypress** for E2E: good UI runner, but Playwright is preferred for modern cross-browser + parallelism and works well headless in CI.
- **Only E2E tests**: too slow and too brittle for day-to-day development; unit/integration tests catch regressions earlier.
- **No frontend tests**: continues current risk profile and slows refactors.

## Consequences

- Adds dependencies and configuration for `vitest`, Testing Library, MSW, and Playwright.
- Requires small test utilities to keep tests readable and consistent (render wrappers, query client factory, MSW handlers).
- Increases confidence for UI refactors and error-handling changes; reduces regression risk in setup/auth flows.

## Implementation Plan

### Phase 0: Agree on scope (one-time)
- Confirm the initial target is **unit + component/integration** coverage, with **minimal E2E smoke** (not full E2E coverage).
- Define “critical flows” for the first E2E pass (recommended: login → dashboard load, onboarding/setup wizard gating).

### Phase 1: Add test tooling (frontend)
- Add dev deps:
  - `vitest` (runner), `jsdom`
  - React Testing Library: `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`
  - `msw` for HTTP mocking
- Add scripts in `frontend/package.json`:
  - `test`: run once in CI mode
  - `test:watch`: dev loop
  - `test:e2e`: Playwright (Phase 5)

### Phase 2: Configure Vitest + setup file
- Configure `vite.config.ts` with `test` settings:
  - `environment: 'jsdom'`
  - `setupFiles: ['src/test/setup.ts']`
  - sane defaults for `include` patterns and coverage (coverage optional initially)
- Add `frontend/src/test/setup.ts`:
  - `@testing-library/jest-dom` matchers
  - MSW server lifecycle (`beforeAll/afterEach/afterAll`)
  - global test hygiene (reset mocks between tests)

### Phase 3: Add shared test utilities (keep tests readable)
- Create `frontend/src/test/render.tsx`:
  - `renderWithProviders()` wrapper for Router + React Query provider (and any global providers used by pages)
  - ability to start at a route (for page tests)
- Create `frontend/src/test/msw/handlers.ts`:
  - request handlers for common endpoints used by many pages (auth csrf, me, setup-status, etc.)
- Create `frontend/src/test/msw/server.ts`:
  - `setupServer(...handlers)` export used by `setup.ts`
- Add conventions:
  - Prefer MSW handlers over stubbing `fetch`
  - Prefer route-level tests that drive UI via user-event

### Phase 4: Establish baseline tests (first value)
- Add a small set of tests that validate “platform guarantees”:
  - API client behavior (credentials + CSRF priming behavior for unsafe requests)
  - Error handling: standardized envelope error shape → user-visible message mapping
- Add one page-level integration test:
  - Example: `LoginPage` submits, handles error, success navigates/redirects as expected (using MSW)
  - Or: setup wizard gating logic routes correctly based on `/api/onboarding/setup-status/`

### Phase 5: Add Playwright smoke tests (optional but recommended)
- Add Playwright config under `frontend/` and a minimal smoke suite:
  - Login flow (happy path)
  - App loads dashboard and renders core UI shell
- Decide how E2E will run locally/CI:
  - Preferred: use the unified `app` service (one port) and treat backend as black box
  - Keep E2E test data/setup minimal and explicit (seed script or dedicated test user)

### Phase 6: CI integration + guardrails
- Add CI steps (or document local equivalents if CI isn’t set up yet):
  - `frontend` install + `npm run test`
  - optionally `npm run test:e2e` behind a separate job
- Add a lightweight standard for new frontend changes:
  - new non-trivial UI behavior comes with at least one RTL test
  - new API client behavior comes with a unit/integration test

### Definition of Done (for “testing is set up”)
- `npm run test` passes locally and in CI.
- A failing test blocks the pipeline (no “allowed failures” for the main test job).
- At least:
  - 2–5 unit tests for pure logic helpers
  - 1–3 component/integration tests for a page flow
  - (optional) 1–2 Playwright smoke tests

## Todos

- Add `vitest` (runner) + React Testing Library (`@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event`) + `jsdom` + `msw` to `frontend/package.json`.
- Add `frontend/vite.config.ts` test config and a `frontend/src/test/setup.ts` (jest-dom, MSW lifecycle).
- Add `npm` scripts: `test`, `test:watch`, `test:ui` (optional), `test:e2e` (Playwright).
- Add baseline tests:
  - API client CSRF priming + error envelope parsing
  - One page-level flow test (e.g., login redirect/setup gating)
- Add Playwright smoke test skeleton and document local run prerequisites.
