# ADR-0107: Adopting React Router v8 and Retiring `react-router-dom`

**Status:** Proposed
**Date:** 2026-07-26
**Author:** Leonardo Merza

## Context

### Background

[ADR-0106](./0106-remaining-dependency-upgrade-sequencing.md) sequenced seven held-back
frontend upgrades and shipped them as PRs #93–#98. It deliberately placed React Router v8
**out of scope**, and recorded its two HIGH advisories as an accepted risk on the grounds
that the vulnerability looked RSC-specific and this application has no React Server
Components.

With ADR-0106's tracks merged, `react-router` is **the only package in the frontend
lockfile still carrying an advisory**. `npm audit` on `main` reports exactly two HIGH
findings, both of it:

```
{"info":0,"low":0,"moderate":0,"high":2,"critical":0,"total":2}
  HIGH  react-router      7.12.0 - 8.2.0
  HIGH  react-router-dom  >=7.12.0-pre.0
```

This ADR decides what to do about that, and about the fact that `react-router-dom` is a
package with no future — v8 deletes it.

### Three corrections to ADR-0106

ADR-0106's react-router paragraph was written from release notes rather than measurement.
Three of its claims do not survive checking:

1. **React is not a blocker.** ADR-0106 says v8 "wants … React 19.2.7+ (above the repo's
   `^19.2.0`)". The repo declares `^19.2.8` and installs **19.2.8**, so
   `react-router@8`'s `peerDependencies` (`react >=19.2.7`, `react-dom >=19.2.7`) are
   already satisfied.
2. **`react-router-dom` is not a pure re-export shim.** ADR-0106 describes it as
   `export * from 'react-router'`. Its actual entry point (`dist/index.mjs`, 384 bytes) is:

   ```js
   export * from "react-router";
   export { HydratedRouter, RouterProvider };   // these come from react-router/dom
   ```

   Two symbols come from a *different* entry point. The import swap is still safe for this
   repo — it uses neither — but the reason is narrower than "it's a pure shim," and the
   distinction matters for anyone applying the same reasoning to another codebase.
3. **The advisory's scope is now a documented fact, not an assessment.** ADR-0106 recorded
   RSC-only applicability as a judgment call needing a second opinion. GHSA-qwww-vcr4-c8h2
   states it outright: *"This only affects your application if you are using the unstable
   RSC APIs."* Affected `>=7.12.0, <8.3.0`; **patched in 8.3.0**. CVSS 7.1, high integrity
   impact, no confidentiality or availability impact.

Correction 3 is the significant one: it converts the accepted risk from *probably fine* to
*documented as not applicable*. It also means the advisory is **not** a reason to rush —
but v8 remains worth adopting on its own merits.

### Current State

| Item | Value |
|---|---|
| `react-router-dom` | 7.18.1 — **terminal**; no 8.x has been or will be published |
| `react-router` (transitive) | 7.18.1 |
| `react-router@latest` | **8.3.0** |
| `react` / `react-dom` | 19.2.8 / 19.2.8 |
| Node — CI (`ci.yml`), demo deploy, Dockerfile | **24** (ADR-0106 / PR #90) |
| Node — local dev machine observed during this work | **22.19.0** |
| `frontend/package.json` `engines` | **not declared** |
| Import sites | **29 files**, **11 unique symbols**, all named imports |
| Routing style | declarative only — `BrowserRouter` + `Routes` + `Route` |

The 11 symbols in use: `BrowserRouter`, `Link`, `MemoryRouter`, `Navigate`, `NavLink`,
`Outlet`, `Route`, `Routes` (once aliased `RouterRoutes`), `useLocation`, `useNavigate`,
`useSearchParams`.

### What v8 actually breaks

From the react-router CHANGELOG, mapped against this repo:

| v8.0.0 breaking change | Applies here? |
|---|---|
| `react-router-dom` package removed; import from `react-router` (and `react-router/dom` for `RouterProvider`/`HydratedRouter`) | **Yes** — the entire migration |
| Minimum Node 22.22.0 | **Partly** — CI/Docker on 24; local dev may be below |
| Minimum React 19.2.7 | No — already on 19.2.8 |
| Packages are now **ESM-only** | No — Vite 8 / Vitest 4 are ESM-native |
| TS target/lib ES2020 → ES2022 | No — `tsconfig.app.json` already targets ES2022 |
| `future.v8_middleware` / `v8_passThroughRequests` / `v8_trailingSlashAwareDataRequests` flags removed (behavior now default) | No — no future flags set |
| `context` to `loader`/`action`/`middleware` is always `RouterContextProvider` | No — no loaders, actions or middleware |
| `hasErrorBoundary` removed from internal `router.routes` | No — internal API, unused |
| `AppLoadContext` type export removed | No — unused |

Verified absent from `src/` (excluding tests): `createBrowserRouter`, `RouterProvider`,
`HydratedRouter`, `useLoaderData`, `useActionData`, `defer`, `createRoutesFromElements`,
`AppLoadContext`. Every v8 breaking change other than the package rename lands in
framework-mode / data-router / custom-server territory this application does not use.

**Export probe.** `react-router@8.3.0` was installed in a scratch directory and its module
namespace enumerated: **129 exports, and all 11 symbols this repo imports are present.**
This is the same measure-the-published-package technique that corrected three findings in
the audit behind ADR-0106.

### Requirements

- **R1** — The import swap must not change runtime behavior. It is a module-specifier
  change, not a refactor.
- **R2** — One change per PR, so a regression is attributable to one cause
  (inherited from ADR-0106 R2).
- **R3** — The Node floor must hold everywhere the frontend is built or tested, including
  developer machines, not just CI.
- **R4** — The advisory must either be closed or explicitly re-accepted with reasoning
  recorded here rather than rediscovered.

### Constraints

- **C1** — 29 files import from `react-router-dom`. All are named imports; there are no
  default or namespace imports, so the swap is purely mechanical.
- **C2** — v8 requires **Node ≥ 22.22.0**. CI, the demo deploy and the Dockerfile are all
  on 24, but a local machine used during this work was on **22.19.0** — below the floor.
  `frontend/package.json` declares no `engines`, so nothing warns about this today.
- **C3** — v8 packages are ESM-only.
- **C4** — CI requires 0 eslint errors (warnings tolerated).
- **C5** — The suite has a load-dependent `await import()` flake. PR #98 raised
  `testTimeout` to 15000, which suppressed it, but classify any failure by re-running the
  file in isolation before calling it a regression (ADR-0106 C4, AC-7).

## Options Considered

### Option 1: Two steps — import prep on v7, then the v8 bump (chosen)

**Description:** PR 1 rewrites the 29 import specifiers from `react-router-dom` to
`react-router`, landing on the **current** v7. PR 2 then swaps the dependency itself:
remove `react-router-dom`, add `react-router@^8.3.0`.

**Pros:**
- PR 1 is provably a no-op: on 7.18.1 `react-router-dom` re-exports `react-router`, and
  the repo imports none of the two symbols that differ. It is verifiable *before* any
  major moves.
- PR 2 becomes a two-line `package.json` change plus a lockfile — the smallest possible
  diff for a major version bump.
- A behavioral regression is unambiguously attributable: PR 1 changes specifiers only,
  PR 2 changes versions only.
- PR 1 can land immediately and is useful even if v8 is deferred indefinitely.
- Matches the method that shipped ADR-0106's six PRs without a single revert.

**Cons:**
- Two review cycles for what is conceptually one migration.

### Option 2: Single atomic PR

**Description:** Rewrite the 29 imports and bump to v8 in one commit.

**Pros:**
- One cycle. The end state is identical.
- Arguably more honest about intent — the import change exists *because of* v8.

**Cons:**
- Mixes a 29-file mechanical edit with a major version bump. If the suite goes red, the
  cause could be either, and separating them means reconstructing this split anyway.
- Forfeits the ability to verify the mechanical half against the known-good v7.
- Directly contradicts ADR-0106 R2 for no gain beyond one review cycle.

### Option 3: Import prep only; defer v8 indefinitely

**Description:** Land PR 1. Stop. Stay on `react-router` 7.18.1 (reached via the
`react-router-dom` dependency), accept the advisory permanently.

**Pros:**
- Captures the entire zero-risk portion of the work.
- The advisory is documented as not applicable, so there is no security pressure.
- No Node floor to raise.

**Cons:**
- 7.18.1 is terminal. Every month on it widens the eventual jump, and the *next* react-router
  advisory may not be RSC-scoped — at which point the migration becomes urgent instead of
  optional.
- Leaves `npm audit` reporting 2 HIGH permanently, which trains everyone to ignore its
  output. That is how the 14 advisories ADR-0106 found accumulated in the first place.

### Option 4: Do nothing

**Description:** Keep `react-router-dom` 7.18.1 and the imports as they are.

**Pros:**
- Zero work.

**Cons:**
- Strictly worse than Option 3: same deferred migration, but without the free half done.
- No argument in favour beyond inertia.

## Decision

**Chosen Option:** Option 1 — two steps, import prep first.

**Rationale:**

- **The two halves have completely different risk profiles, and splitting them is free.**
  The import swap is mechanical and verifiable on the current version; the version bump is
  a two-line dependency change. Option 2's only benefit is one fewer review cycle, paid for
  with an unbisectable failure surface across 29 files plus a major.
- **PR 1 has standalone value.** It works today, reduces the eventual v8 diff to almost
  nothing, and is worth landing even if the decision on v8 later goes the other way. That
  makes it a decision that does not need to be made now.
- **The advisory is not the reason.** GHSA-qwww-vcr4-c8h2 is documented as RSC-only, and
  this is a declarative-mode SPA. The reason to adopt v8 is that `react-router-dom` is a
  **terminal package** — it has no 8.x and never will — and that `npm audit` reporting a
  permanent 2 HIGH is corrosive to the signal. Closing it is a side benefit, not the driver.
- **Every v8 breaking change except the package rename has been checked against this repo
  and does not apply.** The migration is genuinely as small as it looks; the evidence is in
  *What v8 actually breaks* above rather than asserted.

### Not decided here

**Whether to declare `engines` in `frontend/package.json`.** C2 is real — v8 needs Node
≥ 22.22.0 and a dev machine was observed at 22.19.0 — but adding an `engines` field changes
how `npm install` behaves for every contributor and is a project-policy question broader
than this migration. Flagged in AC-3, deliberately left open.

## Acceptance Criteria

- [ ] **AC-1**: Given the import-prep PR, when the suite and `tsc -b` run on the
      **unchanged** `react-router-dom` 7.18.1 dependency, then all 281 files pass,
      `grep -rn "from 'react-router-dom'" src/` returns **zero** hits, and
      `frontend/package.json` is **unmodified** — proving the change is specifier-only (R1).
- [ ] **AC-2**: Given the v8 PR, when it merges, then `frontend/package.json` lists
      `react-router` at `^8.3.0` and **no** `react-router-dom` entry, and `npm ls
      react-router-dom` reports the package absent from the tree.
- [ ] **AC-3**: Before the v8 PR merges, the Node ≥ 22.22.0 floor (C2) has been confirmed
      against every environment that builds or tests the frontend — CI, the demo deploy,
      the Dockerfile, and developer machines — and a decision recorded on whether to
      declare `engines` in `frontend/package.json` (R3).
- [ ] **AC-4**: After the v8 PR, `npm audit` reports **0 high and 0 critical** for the
      frontend (R4). If any react-router advisory remains, it is re-accepted in writing
      with its scope quoted, not silently tolerated.
- [ ] **AC-5**: For both PRs, the merged commit SHA appears in a completed, successful CI
      run — verified via `gh run list --json headSha`, not `gh pr checks` alone
      (ADR-0106 AC-6).
- [ ] **AC-6**: Any suite failure in either PR is classified as a genuine regression or a
      C5 flake by re-running the failing file in isolation, and the classification recorded
      in the PR (ADR-0106 AC-7).

## Consequences

### Positive

- Removes the last advisory from the frontend lockfile, so `npm audit` returning clean
  becomes a meaningful signal again rather than a permanent 2-HIGH baseline.
- Retires a terminal dependency. `react-router-dom` has no 8.x; every release that passes
  widens the gap.
- The eventual v8 diff shrinks to two lines of `package.json` plus a lockfile, because
  PR 1 absorbs the 29-file change while it is still risk-free.
- Aligns the repo with react-router's actual package layout, so future upgrades read the
  same as upstream documentation.
- v8's ESM-only packaging and ES2022 target match what the repo already runs after
  ADR-0106 (Vite 8, Vitest 4, TypeScript 6 targeting ES2022).

### Negative

- Two review cycles for one conceptual migration.
- **Raises the effective Node floor for local development** from whatever developers happen
  to run to 22.22.0. CI and Docker are unaffected (both on 24), but a machine on 22.19 will
  need upgrading — and with no `engines` field, the failure mode is confusing rather than
  explicit.
- v8 is a young major. Its `latest` is 8.3.0 and the repo would be an early adopter
  relative to its own historical upgrade cadence.
- The 29-file diff is mechanical but wide, and will show up in `git blame` on files that
  are otherwise untouched.

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| A v8 behavioral change affects one of the 11 symbols in a way the export probe cannot detect | Low | Medium | Probe confirms presence, not behavior. The CHANGELOG lists no changes to declarative-mode components. Split PRs mean a regression localizes to PR 2. |
| A developer on Node < 22.22.0 hits a confusing failure after PR 2 | **Medium** | Low | AC-3 forces the floor to be confirmed and an `engines` decision recorded before merge. |
| The 29-file import swap silently misses a site | Low | Medium | AC-1 requires `grep -rn "from 'react-router-dom'" src/` to return zero, and `package.json` to be unchanged. |
| v8 is deferred after PR 1 lands, leaving the repo importing `react-router` while depending on `react-router-dom` | Medium | **None** | This is a supported, working configuration on 7.18.1 — that is precisely why PR 1 is safe alone. |
| A future react-router advisory is *not* RSC-scoped while the repo is still on 7.x | Low | High | This ADR is the standing decision to move; Option 3 explicitly names this as its main cost. |
| The C5 import flake is mistaken for a migration regression | Medium | Medium | AC-6 requires isolation re-runs. PR #98's `testTimeout: 15000` already suppressed it. |

## Implementation Plan

- [ ] **PR 1 — import prep (zero risk, land anytime).** Rewrite 29 files from
      `react-router-dom` to `react-router`. No `package.json` change. Verify with AC-1.
- [ ] **PR 2 — v8 bump.** Remove `react-router-dom`, add `react-router@^8.3.0`, refresh the
      lockfile. Verify with AC-2, AC-3, AC-4.
- [ ] **Open question for PR 2:** declare `engines: { node: ">=22.22.0" }` in
      `frontend/package.json`, or leave the floor implicit? (AC-3)

## Related ADRs

- [ADR-0106](./0106-remaining-dependency-upgrade-sequencing.md) — sequenced the upgrades
  that made this one reachable, and deferred react-router v8 to this ADR. Its R2
  (one change per PR) and C4 (the import flake) are inherited here as R2 and C5. Three of
  its react-router claims are corrected above.
- [ADR-0105](./0105-adopt-homeassistant-api-as-ha-transport.md) — established that
  `uv.lock`, `pyproject.toml` and the Docker install path must agree. Backend-side, but the
  same lesson: the lockfile and the declared dependency must not drift.

## References

- [react-router CHANGELOG (v8 breaking changes)](https://raw.githubusercontent.com/remix-run/react-router/main/packages/react-router/CHANGELOG.md)
- [GHSA-qwww-vcr4-c8h2 — RSC Mode CSRF Bypass Allows Action Execution Before 400 Response](https://github.com/advisories/GHSA-qwww-vcr4-c8h2)
  — affected `>=7.12.0, <8.3.0`, patched 8.3.0, *"only affects your application if you are
  using the unstable RSC APIs"*
- [CVE-2026-22030](https://github.com/advisories/GHSA-qwww-vcr4-c8h2) — the earlier CSRF
  issue this advisory follows up on
- Shipped from ADR-0106: #92, #93, #94, #95, #96, #97, #98
