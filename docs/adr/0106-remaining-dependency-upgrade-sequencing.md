# ADR-0106: Sequencing the Remaining Held-Back Dependency Upgrades

**Status:** Proposed
**Date:** 2026-07-25
**Author:** Leonardo Merza

## Context

### Background

A `/dep-upgrade` audit on 2026-07-25 enumerated 33 outdated npm packages and 39
lockfile changes on the Python side. Each candidate was investigated by a dedicated
agent, and — critically — the agents that queried the npm/PyPI registry or unpacked
published tarballs produced findings that **contradicted and corrected** agents
working from release-note prose. Three corrections were material:

1. `vitest` 4 does **not** require Vite 8 (it declares `vite: "^6.0.0 || ^7.0.0 || ^8.0.0"`),
   which decouples two majors that looked inseparable.
2. `typescript-eslint` 8.50.0 peers TypeScript `<6.0.0`, not `<6.1.0` — the widening
   to `<6.1.0` is a *gain* of the 8.65.0 bump, not pre-existing.
3. `eslint-plugin-react-refresh` 0.5.3's **default** export still exposes `configs` as
   plain objects, so the `configs.vite()` call-form change does not apply to this repo.

Three PRs shipped from that audit (#88 uv-only deps, #89 24 frontend bumps,
#90 Node 20 → 24), plus #91 correcting a lockfile-staleness regression #88 introduced.
Seven upgrades were deliberately held back. This ADR records why, and the order in
which they should land.

The held-back set is not a backlog of routine bumps. Its members are bound by a
**peer-dependency graph** in which several cannot move alone, and one — `typescript` 7 —
cannot move at all. Landing them in arbitrary order produces unresolvable installs;
landing them together produces an unbisectable failure surface across 281 test files.

### The measurement pass

The first draft of this ADR sized each upgrade from release notes and static repo
inspection. Every candidate was subsequently **installed and run** — `npm i --no-save
--no-package-lock <pkg>@<ver>`, execute, restore via `npm ci` — the same technique that
produced the audit's three corrections. That pass changed five of the seven per-phase
findings and surfaced two blockers the paper analysis had no way to see.

Every number in this ADR is now a measurement, not an estimate. Measurements were taken
on **Node 22.19.0** (local); CI and the Dockerfile run **Node 24** since #90. Node 22.19
clears every version floor in play, but the runs are not byte-identical to CI.

### Current State

Shipped as of this ADR (post #88–#91):

| Change | PR |
|---|---|
| Docker installs from `uv.lock` (hash-pinned) instead of floating `requirements.txt` | #88 |
| `uv.lock` refreshed — 36 updates, 3 removals, 19 CVEs closed | #91 |
| 24 frontend packages bumped; 3 `setState`-in-effect violations fixed | #89 |
| Node 20 → 24 across all four pins (`ci.yml`, `deploy-demo.yml`, `Dockerfile` ×2) | #90 |

Relevant current versions:

| Package | Version | Note |
|---|---|---|
| `vite` | 7.3.0 | Vite 8 available; **7.3.0 is within a HIGH advisory range** |
| `vitest` | 3.2.4 | carries `vite` as a **direct** dependency; **CRITICAL advisory below 3.2.6** |
| `jsdom` | 26.1.0 | |
| `@testing-library/jest-dom` | 6.9.1 | |
| `eslint` | 9.39.2 | |
| `typescript-eslint` | 8.65.0 | shipped in #89 — **already unlocks ESLint 10**; peers `typescript >=4.8.4 <6.1.0` |
| `eslint-plugin-react-hooks` | 7.1.1 | shipped in #89 — **already unlocks ESLint 10** |
| `@tailwindcss/vite` | 4.3.3 | shipped in #89 — **already accepts Vite 8** (verified) |
| `@vitejs/plugin-react` | 5.1.2 | peer excludes Vite 8 |
| `typescript` | 5.9.3 | |
| `@hookform/resolvers` | 5.4.0 (lock) / `^5.4.0` (declared) | **the declared range breaks `npm install` — see Phase 0** |
| `react-router-dom` | 7.18.1 | terminal v7; v8 removes this package entirely; **within a HIGH advisory range** |
| Node | 24.18.0 (CI/Docker) | clears the floor for jsdom 29, jest-dom 7, eslint 10, react-router v8 |

Three prerequisites are therefore **already satisfied** by #89 and #90.

Two conditions the first draft did not record:

- **`npm install` fails on this repo today.** A bare `npm install`, with no package named,
  exits `ERESOLVE`. `npm ci` is unaffected.
- **The lockfile carries 14 advisories** — 1 critical, 11 high, 1 moderate, 1 low. Four
  are in packages this ADR already sequences.

### Requirements

- **R1** — Every upgrade lands with CI green on the commit it was verified against.
- **R2** — A failure introduced by any single upgrade must be attributable to that
  upgrade without bisecting across unrelated majors.
- **R3** — No upgrade may be applied that produces an unresolvable peer graph or
  silently duplicates a package in the tree.
- **R4** — `typescript` must not move to 7.x while `typescript-eslint` caps it, because
  that breaks the lint step outright.
- **R5** — Behavioral risk that CI cannot cover (live TLS, live Z-Wave schema) must be
  named as a deployment-time check rather than assumed covered.
- **R6** — The pre-existing `await import()` test flake must not be conflated with
  upgrade regressions.
- **R7** — `npm install` must succeed before any phase begins. Every phase adds a
  package; none can be performed while the command that adds packages is broken.

### Constraints

- **C1** — CI requires **0 eslint errors** (warnings tolerated).
- **C2** — The frontend suite is 281 files / 579 tests. 56 files use `vi.mock()` and
  there are 17 `vi.spyOn()` sites. `vite.config.ts:59-60` sets `clearMocks: true` **and**
  `restoreMocks: true` globally, so mock-lifecycle semantics apply suite-wide rather than
  per-file.
- **C3** — CI runs `pytest` via `ljmerza/misc-actions@v2`, not `manage.py test`; the
  local `./scripts/docker-test.sh` runs the latter. Both must stay green.
- **C4** — A pre-existing load-dependent flake times out `await import(X)` smoke tests at
  the 5000 ms default. **Baseline rate is 7 failures in a single full run** (higher than
  the 1–6 first recorded). It is not uniformly random: 6 of 7 baseline failures fell in
  `features/codes` and `features/doorCodes`, the heaviest import graphs. It has never
  fired in CI.
- **C5** — `npm ci` installs the lockfile verbatim and never re-resolves peer ranges;
  `npm install` re-resolves. A conflict can therefore be invisible in CI and fatal
  locally. This is not hypothetical — it is the Phase 0 blocker.
- **C6** — `tsconfig.app.json` **excludes** `src/**/*.test.ts(x)` and `src/test/**`.
  `tsc -b` never typechecks the 281 test files, so a green `tsc -b` says nothing about
  test-file type health under any upgrade.

## Options Considered

### Option 1: Graph-ordered, one PR per unblocking step (chosen)

**Description:** One PR per upgrade, in dependency order, each verified and merged before
anything that depends on it.

**Pros:**
- Every step is independently revertable.
- A red suite localizes to exactly one major.
- `vitest` 4's 56 `vi.mock` files are verified on their own, not tangled with a bundler swap.
- Mirrors the pattern that shipped #88–#91 successfully.

**Cons:**
- Multiple review cycles; slowest wall-clock.
- Requires discipline to not batch "just these two."

### Option 2: Two batches — test stack, then build stack

**Description:** Group by what each upgrade touches: `vitest` 4 + `jsdom` 29 +
`jest-dom` 7 in one PR, `vite` 8 + `plugin-react` 6 in another.

**Pros:**
- Natural conceptual grouping; fewer cycles.
- The test-stack members share a Node floor, already satisfied.

**Cons:**
- Stacks three majors over 281 test files. A failure could be `vitest`'s spy rewrite,
  `jsdom`'s CSSOM reimplementation, or `jest-dom`'s new peer — all plausible, all
  distinguishable only by bisecting.
- `jsdom` 29 adds ~29% wall clock, which interacts directly with the C4 flake. Bundled,
  a new timeout is ambiguous between "jsdom is slower" and "vitest 4 broke a mock."

### Option 3: Single PR for everything except TypeScript

**Description:** One PR carrying six majors; TypeScript 6.0.3 follows separately.

**Pros:**
- One review, one CI cycle; the peer graph resolves in a single pass.

**Cons:**
- Unbisectable. A red suite could be the spy rewrite, the Rolldown swap, the CSSOM
  reimplementation, or three newly-error-level eslint rules.
- All-or-nothing revert.
- Directly contradicts the incremental method that caught three wrong findings in the
  audit that produced this ADR — and five more in the measurement pass.

### Option 4: Defer the majors; automate freshness only

**Description:** Skip manual sequencing; configure Renovate/Dependabot and let tooling
propose upgrades.

**Pros:**
- Addresses the root cause of the #91 regression — nothing enforced lock freshness.
- Catches future CVEs without human scheduling.

**Cons:**
- Bot PRs **cannot** resolve the coupled majors. `plugin-react` 6 requires Vite 8;
  `vitest` 3 pins `vite` as a direct dependency; `typescript-eslint` caps TypeScript.
  Each would open as a failing PR needing the same human sequencing this ADR describes.
- A bot cannot even open a PR here until Phase 0 lands — its first `npm install` fails.
- Defers rather than solves.

## Decision

**Chosen Option:** Option 1 — graph-ordered, one PR per unblocking step, preceded by a
Phase 0 that unblocks installation, and reorganized into four independent tracks.

**Rationale:**

- **R2 is the binding requirement.** With 281 test files and a known load-dependent
  flake (C4), the ability to attribute a failure to one upgrade is worth more than
  saved review cycles. Options 2 and 3 both trade that away.
- **The graph makes the order nearly forced — and this is now measured, not inferred.**
  Installing `vite@8` while `vitest@3` is present produces **no error** and silently
  nests a second Vite (see Track A). `vitest` 4 must precede Vite 8.
- **The audit's own method argues for it.** Three findings in the original audit were
  wrong and were corrected by narrower, empirical follow-ups. The measurement pass then
  corrected five more findings in the first draft of *this* ADR. Batching six majors
  optimizes for the case where nothing goes wrong; there is now direct, repeated
  evidence that things go wrong in ways release notes do not predict.
- **Only one dependency edge is real.** Measurement showed Tracks B, C and D have no
  unmet prerequisite and no dependency on each other or on Track A. Serializing them
  buys nothing that R2 requires.
- **Option 4 is necessary but not sufficient.** Freshness automation genuinely addresses
  the #91 root cause and should happen — but as its own decision, because it governs
  cadence and review ownership rather than sequencing. Deferred to a separate ADR.

### Phase 0 — unblock `npm install` and close the reachable CVEs (prerequisite for everything)

**This must land first. It is not a track; every other track depends on it (R7).**

**Part 1 — restore `npm install`.**

A bare `npm install` on this repo exits `ERESOLVE`:

```
Found: valibot@0.39.0
  peerOptional valibot@"^0.39.0" from @typeschema/valibot@0.14.0
    peerOptional @typeschema/valibot@"0.14.0" from @typeschema/main@0.14.1
      peerOptional @typeschema/main@">=0.13.7" from @hookform/resolvers@5.5.3
Could not resolve dependency:
  peerOptional valibot@"^1.0.0 || ^1.0.0-beta.4 || ^1.0.0-rc" from @hookform/resolvers@5.5.3
```

`@hookform/resolvers` reaches `valibot` by two paths that demand incompatible majors.
Measured version boundary:

| Version | `valibot` peer | `@typeschema/main` peer |
|---|---|---|
| **5.4.0** | *(none declared)* | *(none declared)* |
| 5.4.1 – 5.5.3 | `^1.0.0 \|\| ^1.0.0-beta.4 \|\| ^1.0.0-rc` | `>=0.13.7` |

The lockfile pins 5.4.0, so `npm ci` succeeds (C5) and CI never sees this. The declared
range `^5.4.0` floats to 5.5.3 the moment anything re-resolves.

**Fix: pin `"@hookform/resolvers": "5.4.0"` exactly** — drop the caret. Verified: with
that pin, `npm install <pkg>` resolves cleanly. Every measurement in this ADR was taken
under it. Do **not** use `--legacy-peer-deps` as the workaround: it skips auto-installed
peers and prunes `@testing-library/dom` (a peer of `@testing-library/react` 16, present
in the lockfile but not a direct dependency), which fails all 281 test files with
`Cannot find module '@testing-library/dom'`. That failure mode was observed and is an
artifact of the flag, not of any upgrade.

**Part 2 — close the CVEs that need no major.** `npm audit` reports 14 advisories
(1 critical, 11 high, 1 moderate, 1 low). Two direct hits are fixable **inside the
existing caret ranges** — `npm update`, no `package.json` change, no major:

| Package | Current | Wanted | Vulnerable range | Advisories closed |
|---|---|---|---|---|
| `vitest` | 3.2.4 | **3.2.7** | `<3.2.6` | 1 CRITICAL (GHSA-5xrq-8626-4rwp) |
| `vite` | 7.3.0 | **7.3.6** | `7.0.0 – 7.3.3` | 3 HIGH + 2 moderate |

Reachability assessment: the Vitest critical requires the **Vitest UI server** to be
listening, and the Vite highs are all **dev-server** paths (`server.fs.deny` bypass,
dev-server WebSocket arbitrary file read, optimized-deps `.map` traversal). Neither runs
in the production image, which is nginx serving static `dist/`. The dev stack in
`docker-compose.yml` does run the Vite dev server on 5427. This is an assessment from
advisory text, not a verified non-exploitability finding — and since the fix costs one
`npm update`, the question does not need settling.

`rollup` (HIGH, `4.0.0 – 4.58.0`) is transitive via Vite and disappears entirely at
Track A step 2, when Rolldown replaces it.

**Deliverable:** one PR — exact-pin `@hookform/resolvers`, `npm update`, refreshed
lockfile. No source changes.

### Upgrade order and per-step evidence

Only one dependency edge in the held-back set is real. The rest are independent:

```
Phase 0  ──▶  Track A:  vitest 4  ──▶  vite 8 + plugin-react 6 (atomic)   [serial edge]
         ──▶  Track B:  jsdom 29 + jest-dom 7                             [independent]
         ──▶  Track C:  eslint 10 + @eslint/js 10                         [independent]
         ──▶  Track D:  typescript 6.0.3                                  [independent]
```

Tracks B, C and D may proceed in any order or concurrently. They remain **one major per
PR**, so R2 holds. The only real cost of concurrency is `frontend/package-lock.json`
conflicts on rebase, which regenerate rather than requiring manual merge.

---

**Track A, step 1 — `vitest` 3.2.4 → 4.1.10 (on Vite 7)**

- **Measured: 5 failed / 574 passed, 100.28s** — against a baseline of **7 failed / 572
  passed, 103.67s**. All 5 failures are 5000 ms `await import()` timeouts (C4). **Zero
  assertion errors, zero type errors, zero test-file edits, zero config edits.**
- The predicted risk did not materialize. The first draft flagged
  `AlarmPanelContainer.test.tsx:45-49` as "the only `mockReset()` on a `vi.fn(impl)`";
  that file declares `const arm = vi.fn()` with **no implementation**, so the changed
  semantics cannot reach it. Repo-wide there are **6** `vi.fn(impl)` sites and **89**
  `mockReset()` sites, and the intersection is **empty**. The global
  `clearMocks`/`restoreMocks` pair (C2) was the larger unknown and is empirically inert.
- `vitest` 4 declares `vite: "^6.0.0 || ^7.0.0 || ^8.0.0"` — **Vite 7 satisfies it**, so
  this lands on the current bundler.
- Zero `toMatchSnapshot` and no `__snapshots__` directories, so the snapshot-format and
  obsolete-snapshots-fail-CI changes are inert.
- **The `basic` reporter is removed in Vitest 4.** `--reporter=basic` is now a startup
  error. No `package.json` script or CI config uses it; check any local scripts.

**Track A, step 2 — `vite` 7 → 8.1.5 with `@vitejs/plugin-react` 5.1.2 → 6.0.4 (atomic)**

- **This is why step 1 comes first, and it is measured.** Installing `vite@8` +
  `plugin-react@6` while `vitest@3` is present produces **no ERESOLVE** and silently
  nests a duplicate:

  ```
  ├── vite@8.1.5                    ← root
  └─┬ vitest@3.2.7
    ├─┬ @vitest/mocker@3.2.7 → vite@7.3.6 deduped
    ├─┬ vite-node@3.2.4      → vite@7.3.6
    └── vite@7.3.6                  ← duplicate, no warning
  ```

  Two Vite copies means two module graphs: the dev server transforms with 8 while Vitest
  resolves with 7. npm reports success. This is exactly what R3 forbids and AC-4 checks.
- With `vitest` 4 installed, the same install yields **a single `vite@8.1.5`, fully
  deduped** across `@tailwindcss/vite`, `@vitejs/plugin-react` and `vitest`.
- **Measured build: `vite build` exits 0 in 765 ms / 84 chunks**, against a Vite 7
  baseline of **7.50 s / 76 chunks** — roughly 10× faster from the Rolldown + Oxc swap.
  The chunk-count delta is a code-splitting difference and should get a glance in review.
- **Measured suite on the end state: 3 failed / 576 passed, 94.35s** — the lowest flake
  count and fastest wall clock of any configuration tested. All 3 are C4 timeouts.
- `plugin-react` 6 declares `peerDependencies.vite = "^8.0.0"` — a hard requirement. No
  version spans both, so it ships **inside** this PR, never before it.
- Rolldown + Oxc replace Rollup + esbuild: `build.rollupOptions` → `build.rolldownOptions`,
  `optimizeDeps.esbuildOptions` → `optimizeDeps.rolldownOptions`, top-level `esbuild` → `oxc`.
  **`vite.config.ts` uses none of these**, so config impact is nil — confirmed by the
  clean build above.
- Default browser target rises to Chrome 111 / Firefox 114 / Safari 16.4 (from
  107 / 104 / 16.0); output moves ES2020 → ES2022. This is a **product decision**, not
  just a build one — confirm it against the browsers the alarm UI must support (AC-8).
- `plugin-react` 6 drops Babel entirely (React Refresh moves to Oxc) and no longer
  auto-adds `react`/`react-dom` to `resolve.dedupe`. Add that manually if duplicate React
  copies appear.
- Node is **not** a blocker: Vite 8 wants `^20.19.0 || >=22.12.0`; #90 put CI on 24.

---

**Track B — `jsdom` 26.1.0 → 29.1.1 and `@testing-library/jest-dom` 6.9.1 → 7.0.0**

- Both were gated on Node ≥ 22; #90 satisfied that.
- **Measured together: 4 failed / 575 passed. Zero assertion errors, zero test-file
  edits, zero config edits.** All 4 failures are C4 timeouts.
- **Measured cost: 133.90 s wall vs 103.67 s baseline (+29%);** aggregate environment
  time 364.03 s → 684.89 s (**+88%**). This is the slowest configuration tested — notably
  slower than the Vite 8 end state at 94.35 s.
- **Raise `testTimeout` above the 5000 ms default in this PR.** At +29% wall clock on a
  suite whose baseline already flakes 7 times per run, leaving the default makes C4
  ambiguous with a real regression.
- `jest-dom` 7 peers `@testing-library/dom: ">=10 <11"`. The lockfile already carries
  10.4.1 transitively, so the peer **is** satisfied — adding it as an explicit
  devDependency is hygiene, not a requirement.
- `vite.config.ts` sets no `test.environmentOptions.jsdom`, so jsdom 29's removed
  `ResourceLoader` / `VirtualConsole.sendTo` call sites are never reached.

**Track C — ESLint 10 bundle**

- `eslint` 9.39.2 → 10.8.0 and `@eslint/js` → 10.0.1. The version-line skew is expected;
  10.0.1 peers `eslint ^10.0.0`.
- **Both blocking peers are already satisfied by #89** — `typescript-eslint` 8.65.0
  (peers `eslint: "^8.57.0 || ^9.0.0 || ^10.0.0"`) and `eslint-plugin-react-hooks` 7.1.1.
- **Measured: exactly 2 errors, 63 warnings** — against a baseline of 0 errors,
  63 warnings. The warning count is unchanged; the entire delta is two errors:

  | File | Rule |
  |---|---|
  | `src/features/rules/queryBuilder/ActionsEditor.tsx:859:9` | `no-useless-assignment` — value assigned to `parsedValue` unused downstream |
  | `src/lib/validation.ts:86:7` | `preserve-caught-error` — no `cause` attached to the rethrown error |

  The third new error-level rule, `no-unassigned-vars`, produces **zero** hits.
- Both fixes are local and belong in this PR (C1).
- `eslint-plugin-react-refresh` 0.4.26 → 0.5.3 is optional here and requires **no config
  edit** — 0.5.3's default export still exposes `configs.recommended|vite|next` as plain
  objects.
- Everything else (`.eslintrc` removal, config-lookup change, removed `FlatESLint` /
  `context.getCwd` APIs) is inert — flat config only, no custom rules.

**Track D — `typescript` 5.9.3 → 6.0.3 (explicitly *not* 7.x)**

- **TypeScript 7 is blocked and stays blocked.** `typescript-eslint` peers
  `typescript: ">=4.8.4 <6.1.0"` even at 8.65.0, which excludes 7.x — verified against the
  published package. TypeScript's `latest` dist-tag is now **7.0.2**, so this is a live
  temptation, not a theoretical one. Upstream closed the TS 7 support issue
  ([typescript-eslint#12518](https://github.com/typescript-eslint/typescript-eslint/issues/12518))
  as **not-planned**, pending the TS 7.1 API. Moving to 7 breaks the lint step outright (R4).
- 6.0.3 is reachable *because* #89 shipped `typescript-eslint` 8.65.0, which widened the
  cap from `<6.0.0` to `<6.1.0`.
- **Measured: `tsc -b` produces exactly one error**, and it is not the predicted one:

  ```
  tsconfig.app.json:28:5 - error TS5101: Option 'baseUrl' is deprecated and will stop
  functioning in TypeScript 7.0.
  ```

- **The first draft's prescribed edit is a no-op.** TS 6.0 drops auto-`@types`
  discovery, but this repo never relied on it: `tsconfig.app.json` already sets
  `"types": ["vite/client"]` and `tsconfig.node.json` already sets `"types": ["node"]`.
  Of the six TS 6.0 default flips, **five are already explicitly pinned** in both project
  files (`strict`, `module`, `target`/`lib`, `types`, `noUncheckedSideEffectImports`).
  The sixth, `libReplacement: false`, is inert — no lib-replacement packages are used.
- **The real diff is one deleted line.** `paths` already uses tsconfig-relative
  `"@/*": ["./src/*"]` and no longer needs `baseUrl`. Verified: with `"baseUrl": "."`
  removed from `tsconfig.app.json`, `tsc -b` on 6.0.3 **exits 0**.
- `tsc -b` build mode and project references **are** supported, so the solution-style
  `tsconfig.json` layout survives.
- Note C6: `tsc -b` excludes the test files, so this green result covers `src/` only.
- Revisit 7.x only after `typescript-eslint` ships TS 7.1 compatibility. That will warrant
  its own ADR — TS 7 is the Go-native rewrite with no stable programmatic API.

### Not sequenced here

**`react-router-dom` → `react-router` import prep.** Switch the 29 import sites from
`react-router-dom` to `react-router`. This works **today** on 7.18.1 (the package is a pure
re-export shim, `export * from 'react-router'`) and constitutes the bulk of the eventual
v8 diff. Zero risk, fully decoupled from every track above, land whenever convenient.

**`react-router-dom` carries an unfixable-in-v7 HIGH advisory.** GHSA-qwww-vcr4-c8h2
("RSC Mode CSRF Bypass Allows Action Execution Before 400 Response") covers
`react-router` `7.12.0 – 8.2.0`; the repo is on 7.18.1. npm's only proposed remediation is
a **downgrade to 7.11.0**, flagged `isSemVerMajor`. The genuine fix is react-router
**> 8.2.0**, which means the v8 migration — and v8 removes `react-router-dom` entirely,
wants Node 22.22+, and wants React 19.2.7+ (above the repo's declared `^19.2.0`).

The advisory is specific to **RSC mode**. This repo is a Vite SPA with no React Server
Components, so the vulnerable path is assessed as unreachable. **That is an assessment,
not a verified finding**, and it is recorded here as an accepted risk rather than a
scoping note. v8 adoption remains out of scope for this ADR and should get its own.

## Acceptance Criteria

- [ ] **AC-0**: Given `@hookform/resolvers` pinned to exact `5.4.0` and `npm update` run,
      when a bare `npm install` executes on a clean checkout, then it exits 0 with no
      `ERESOLVE`; and `npm audit` reports **0 critical** with `vitest ≥ 3.2.7` and
      `vite ≥ 7.3.6` in the lockfile (R7).
- [ ] **AC-1**: Given `vitest` 4.1.10 installed on Vite 7, when `npx vitest run` executes,
      then failures number **≤ 7** (the C4 baseline) and **all** are 5000 ms `await
      import()` timeouts — zero assertion or type errors — with no edits to
      `vite.config.ts` and no edits to any test file.
- [ ] **AC-2**: Given `jsdom` 29.1.1 and `@testing-library/jest-dom` 7.0.0 installed, when
      the full suite runs, then no test file requires editing, all failures are C4
      timeouts, and `testTimeout` has been raised above 5000 ms **in the same PR** to
      absorb the measured +29% wall clock.
- [ ] **AC-3**: Given ESLint 10.8.0 with `@eslint/js` 10.0.1, when `npx eslint .` runs,
      then it exits 0 with **0 errors** (C1) — specifically, `ActionsEditor.tsx:859`
      (`no-useless-assignment`) and `validation.ts:86` (`preserve-caught-error`) are fixed
      in that PR — and the warning count remains **63**.
- [ ] **AC-4**: Given Vite 8.1.5 and `@vitejs/plugin-react` 6.0.4 in the **same** commit,
      when `npm run build` runs, then it succeeds and `npm ls vite` reports **exactly one**
      Vite version with every consumer `deduped` (R3). A nested `vite@7.x` under `vitest`
      means Track A step 1 did not land first.
- [ ] **AC-5**: Given TypeScript 6.0.3 and `"baseUrl"` removed from `tsconfig.app.json`,
      when `tsc -b` runs, then it exits 0; and `npm ls typescript` confirms no version
      ≥ 6.1.0 is installed (R4). No `types` array needs adding — both already exist.
- [ ] **AC-6**: For Phase 0 and each track PR, the merged commit SHA appears in a
      **completed, successful** CI run — verified via `gh run list --json headSha`, not
      `gh pr checks` alone (R1).
- [ ] **AC-7**: Given any PR in this sequence reports test failures, when those failures
      are triaged, then each is classified as either a genuine regression or a C4 flake by
      re-running the failing file in isolation, and the classification is recorded in the
      PR (R6).
- [ ] **AC-8**: After the Vite 8 PR, the browser-target change (Chrome 111 / Firefox 114 /
      Safari 16.4) has been explicitly confirmed as acceptable for the alarm UI's supported
      browsers, and that confirmation is recorded in the PR description.

## Consequences

### Positive

- Each upgrade is independently revertable; a regression never requires unwinding six majors.
- Every track now has a measured expected result, so "is this a regression?" is answerable
  by comparing to a number rather than by judgment.
- Four prerequisites (`typescript-eslint` 8.65, `react-hooks` 7.1.1, `@tailwindcss/vite`
  4.3.3, Node 24) are already shipped, so Tracks C and D are smaller than they appear —
  Track D is a one-line diff.
- Phase 0 restores `npm install`, which unblocks not just these tracks but any future
  dependency work at all, including the freshness automation of Option 4.
- The reachable CVEs close in Phase 0 without waiting on any major upgrade.
- Recognizing B, C and D as independent removes most of the serialization the first draft
  booked as a cost, without weakening R2.
- Vite 8 measurably improves the build (7.50 s → 765 ms) and slightly *reduces* the C4
  flake rate (7 → 3), so Track A carries its own justification beyond currency.
- TypeScript 7's blockage is documented with a concrete unblock condition rather than
  rediscovered each quarter — now more urgent to record, since TS 7 holds the `latest` tag.

### Negative

- Still multiple review cycles, though fewer serialized than the first draft assumed.
- Concurrent tracks will conflict in `frontend/package-lock.json` and need rebasing.
- The repo sits on mixed-age tooling in the interim (Vite 7 with vitest 4, for example) —
  a supported combination, but not one upstream tests as heavily as the matched pair.
- **Track B makes the suite meaningfully slower** (+29% wall, +88% environment) in
  exchange for no measured behavioral benefit. It is currency work, and it is the one
  track with a negative measured outcome.
- **`react-router-dom` retains a HIGH advisory with no v7 remedy.** Accepted on a
  reachability assessment (no RSC), not on a fix.
- **Lock staleness remains unmanaged, knowingly.** Automated freshness (Dependabot,
  Renovate, or a scheduled refresh job) was considered and not adopted. This is a real
  accepted risk, not an oversight: `uv.lock` went **110 days** without a full refresh
  (last full generation `868c5cc` 2026-04-06; `520e56c` touched only 6 packages), and
  during that window Django shipped 6.0.4 → 6.0.7 — four consecutive security releases,
  16 CVEs. Those reached the image only because `requirements.txt` still used floating
  `>=` ranges. #88 removed that accidental safety net and #91 was needed to repair the
  resulting gap. The npm side has now demonstrated the same failure independently: 14
  advisories accumulated, one critical, with the two direct hits fixable by a plain
  `npm update` nobody was running. Until someone revisits this, **keeping both lockfiles
  current is a manual responsibility**, and the failure mode is silent: a stale lock
  produces green CI and a reproducibly-vulnerable image.

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| A track is attempted before Phase 0 and `npm install` fails | High | Low | AC-0 gates the sequence; the failure is loud and immediate. |
| Someone works around the ERESOLVE with `--legacy-peer-deps` | Medium | High | Documented in Phase 0: it prunes `@testing-library/dom` and fails all 281 files with a misleading error. Use the exact pin. |
| Vite 8 lands before vitest 4, silently duplicating Vite | Medium | High | Reproduced and documented above. AC-4 requires every `npm ls vite` consumer to read `deduped`. |
| `vitest` 4 spy rewrite breaks some of the 56 `vi.mock` files | **Low** (measured: 0) | Medium | Measured at 5 failures vs 7 baseline, all C4. AC-1 pins the expected number. |
| ESLint 10's new error rules exceed the 0-error gate | **Low** (measured: 2) | Low | Both sites named in AC-3; fix in the same PR. |
| Vite 8 browser-target rise drops a browser the alarm UI must support | Low | High | AC-8 forces explicit confirmation before merge. |
| `jsdom` 29's +29% wall clock pushes C4 flakes into CI | Medium | Medium | Raise `testTimeout` in the same PR (AC-2). |
| Vite 8 leaves duplicate React copies (auto-dedupe removed) | Low | Medium | AC-4 checks `npm ls`; add `resolve.dedupe: ['react','react-dom']` if needed. |
| `react-router` RSC advisory turns out to be reachable | Low | High | Reassess if the app ever adopts RSC or a framework mode; the fix is v8 and needs its own ADR. |
| A stale CI result is mistaken for verification of a new commit | Medium | High | AC-6 requires SHA-level verification. This occurred during the #88 work: `gh pr checks` reported green from a prior commit. |
| Someone batches two tracks "since they're both small" | Medium | Medium | This ADR is the record; PR descriptions should reference the AC they satisfy. |

## Implementation Plan

- [ ] **Phase 0** *(blocks everything)*: pin `@hookform/resolvers` to exact `5.4.0`,
      `npm update` (vitest → 3.2.7, vite → 7.3.6), refresh lockfile (AC-0)
- [ ] **Track A.1**: `vitest` 3 → 4.1.10 on Vite 7 (AC-1)
- [ ] **Track A.2** *(after A.1)*: `vite` 8.1.5 + `@vitejs/plugin-react` 6.0.4, atomically
      (AC-4, AC-8)
- [ ] **Track B** *(independent)*: `jsdom` 29.1.1 + `@testing-library/jest-dom` 7.0.0 +
      raise `testTimeout` (AC-2)
- [ ] **Track C** *(independent)*: `eslint` 10.8.0 + `@eslint/js` 10.0.1, fix the 2 named
      errors; optionally `eslint-plugin-react-refresh` 0.5.3 (AC-3)
- [ ] **Track D** *(independent)*: `typescript` 6.0.3, delete `baseUrl` from
      `tsconfig.app.json` (AC-5)
- [ ] **Anytime, decoupled**: `react-router-dom` → `react-router` import prep, 29 sites
- [ ] **Separate ADR**: react-router v8 adoption (closes GHSA-qwww-vcr4-c8h2)
- [ ] **Separate ADR**: dependency freshness/governance policy (see Related ADRs)

## Related ADRs

- [ADR-0105](./0105-adopt-homeassistant-api-as-ha-transport.md) — established that
  `uv.lock`, `pyproject.toml` and the Docker install path must agree; the lesson that
  motivated the #88/#91 consolidation. Its `homeassistant-api==6.0.1` pin is excluded
  from all automated upgrades until its phases 2–5 complete.

Two follow-on ADRs are now anticipated: react-router v8 adoption, and a dependency
freshness/governance policy. The latter was considered here and **deliberately not
adopted** — see Consequences → Negative.

## References

- [Vitest 4 migration guide](https://vitest.dev/guide/migration.html)
- [Vite 8 migration guide](https://vite.dev/guide/migration)
- [ESLint 10 migration guide](https://eslint.org/docs/latest/use/migrate-to-10.0.0)
- [jsdom releases](https://github.com/jsdom/jsdom/releases)
- [@testing-library/jest-dom v7.0.0](https://github.com/testing-library/jest-dom/releases/tag/v7.0.0)
- [typescript-eslint dependency versions](https://typescript-eslint.io/users/dependency-versions/)
- [typescript-eslint#12518 — TypeScript 7 support, closed not-planned](https://github.com/typescript-eslint/typescript-eslint/issues/12518)
- [Announcing TypeScript 7.0](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/)
- [react-router CHANGELOG (v7 branch)](https://raw.githubusercontent.com/remix-run/react-router/v7/packages/react-router/CHANGELOG.md)
- Advisories referenced: [GHSA-5xrq-8626-4rwp](https://github.com/advisories/GHSA-5xrq-8626-4rwp) (vitest, critical),
  [GHSA-v2wj-q39q-566r](https://github.com/advisories/GHSA-v2wj-q39q-566r) /
  [GHSA-p9ff-h696-f583](https://github.com/advisories/GHSA-p9ff-h696-f583) /
  [GHSA-fx2h-pf6j-xcff](https://github.com/advisories/GHSA-fx2h-pf6j-xcff) (vite, high),
  [GHSA-qwww-vcr4-c8h2](https://github.com/advisories/GHSA-qwww-vcr4-c8h2) (react-router, high)
- Full audit with per-package evidence: `.claude/dep-upgrade-report.md` (gitignored, local)
- Shipped from the same audit: #88, #89, #90, #91
