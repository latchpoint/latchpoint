#!/usr/bin/env node
/**
 * Latchpoint screenshot tour driver.
 *
 * Default target: the frontend-only demo bundle (ADR-0089). The demo's MSW
 * handlers return a logged-in admin user from /api/users/me/ regardless of
 * session state, so no real login is required — the harness just navigates
 * and shoots. Set DEMO=false to fall back to the legacy backend-driven flow
 * (POST /api/auth/login/ then route mocks for integration health endpoints).
 *
 * - Reads manifest.json (declarative shot list with global mocks).
 * - For each shot: optionally logs in, applies route mocks, sets theme via
 *   localStorage, navigates, waits for network-idle, screenshots full page.
 * - Writes PNGs to docs/screenshots/<name>-<theme>-<viewport>.png.
 *
 * Usage (demo target — default):
 *   # In another shell: cd frontend && npm run dev:demo  (serves on :5427)
 *   cd scripts/screenshots
 *   npm install
 *   npx playwright install chromium     # one-time browser download
 *   node take-shots.mjs                 # capture every shot in the manifest
 *   node take-shots.mjs dashboard rules-list   # only named shots
 *
 * Usage (legacy backend target):
 *   DEMO=false FRONTEND=http://localhost:5427 BACKEND=http://localhost:8000 \
 *   EMAIL=admin@testhome.local PASSWORD=adminpass node take-shots.mjs
 */

import { chromium } from 'playwright'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const REPO_ROOT = path.resolve(__dirname, '..', '..')
const OUT_DIR = path.join(REPO_ROOT, 'docs', 'screenshots')

// DEMO=true (default) targets the in-browser MSW demo — no backend, no real
// auth, no broker mocks needed (the demo's MSW handlers already serve a
// "connected" state). DEMO=false falls back to the legacy flow that logs in
// against a real Django backend and overlays integration-health mocks.
const DEMO = process.env.DEMO !== 'false'
const FRONTEND = process.env.FRONTEND ?? 'http://localhost:5427'
const BACKEND = process.env.BACKEND ?? FRONTEND
const EMAIL = process.env.EMAIL ?? 'admin@testhome.local'
const PASSWORD = process.env.PASSWORD ?? 'adminpass'
const ONLY = process.argv.slice(2)

function log(...args) {
  console.log('[shots]', ...args)
}

async function loadManifest() {
  const raw = await fs.readFile(path.join(__dirname, 'manifest.json'), 'utf8')
  return JSON.parse(raw)
}

async function ensureOutDir() {
  await fs.mkdir(OUT_DIR, { recursive: true })
}

/**
 * Login by hitting the API directly and forwarding cookies + CSRF to the browser context.
 *
 * The frontend reads sessionid via cookie and CSRF via a separate header on writes;
 * for read-mostly screenshots we only need the session cookie.
 */
async function loginContext(context) {
  const res = await context.request.post(`${BACKEND}/api/auth/login/`, {
    data: { email: EMAIL, password: PASSWORD },
    headers: { 'Content-Type': 'application/json' },
  })
  if (!res.ok()) {
    throw new Error(`Login failed: ${res.status()} ${await res.text()}`)
  }
  log(`logged in as ${EMAIL}`)
}

/**
 * Apply manifest globalMocks to the page via route().
 *
 * Each mock fulfills the matching request with a JSON body; non-matching requests
 * pass through to the real backend.
 */
async function applyMocks(page, mocks) {
  for (const mock of mocks) {
    await page.route(mock.url, async (route) => {
      log(`mock hit: ${route.request().url()}`)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mock.body),
      })
    })
  }
}

/**
 * Set the theme by writing to localStorage before any app code runs.
 *
 * The Zustand persist key is `alarm-theme` and the value is a stringified JSON
 * envelope: `{ "state": { "theme": "dark" }, "version": 0 }`.
 * We initialize via addInitScript so the value is present on first paint.
 */
async function primeTheme(context, theme) {
  await context.addInitScript((selectedTheme) => {
    try {
      window.localStorage.setItem(
        'alarm-theme',
        JSON.stringify({ state: { theme: selectedTheme }, version: 0 }),
      )
    } catch (err) {
      // localStorage may be unavailable on first navigation; the app fallback handles it.
      console.warn('failed to prime theme', err)
    }
  }, theme)
}

async function captureShot({ browser, manifest, shot, theme, viewportName }) {
  const viewport = manifest.viewports[viewportName]
  if (!viewport) throw new Error(`unknown viewport: ${viewportName}`)

  const context = await browser.newContext({ viewport, deviceScaleFactor: 2 })
  await primeTheme(context, theme)
  // Demo mode pre-authenticates via MSW, so skip the API-level login step.
  // Route mocks are also unnecessary in demo mode (MSW already returns the
  // connected state for every integration), but applying them is harmless —
  // Playwright route handlers take precedence over MSW for the same URL.
  if (!DEMO && !shot.skipLogin) {
    await loginContext(context)
  }
  const page = await context.newPage()
  if (!DEMO) {
    await applyMocks(page, manifest.globalMocks)
  }

  const url = new URL(shot.route, FRONTEND).toString()
  await page.goto(url, { waitUntil: 'networkidle', timeout: 30_000 }).catch((err) => {
    log(`networkidle timeout for ${url}: ${err.message}`)
  })

  // Auth-gated TanStack Query reads can prime with undefined or stale values
  // when the status query fires before the auth-session query resolves on
  // first page mount. Clicking Refresh forces a fresh refetch through the
  // mocks so integration cards show the connected state.
  const refreshButtons = page.locator('button:has-text("Refresh")')
  const refreshCount = await refreshButtons.count().catch(() => 0)
  for (let i = 0; i < refreshCount; i += 1) {
    await refreshButtons.nth(i).click({ trial: false }).catch(() => {})
  }
  // Wait long enough for the success toast triggered by Refresh to fade.
  if (refreshCount > 0) {
    await page.waitForTimeout(3500)
  } else {
    await page.waitForTimeout(1200)
  }

  const outPath = path.join(OUT_DIR, `${shot.name}-${theme}-${viewportName}.png`)
  await page.screenshot({ path: outPath, fullPage: true })
  log(`wrote ${path.relative(REPO_ROOT, outPath)} (${viewport.width}x${viewport.height})`)

  await context.close()
}

async function main() {
  await ensureOutDir()
  const manifest = await loadManifest()
  const browser = await chromium.launch({ headless: true })

  try {
    const filteredShots = ONLY.length
      ? manifest.shots.filter((s) => ONLY.includes(s.name))
      : manifest.shots

    if (ONLY.length && filteredShots.length === 0) {
      log(`no shots matched filter: ${ONLY.join(', ')}`)
      return
    }

    for (const shot of filteredShots) {
      const themes = shot.themes ?? ['dark']
      const viewports = shot.viewports ?? ['desktop']
      for (const theme of themes) {
        for (const viewportName of viewports) {
          try {
            await captureShot({ browser, manifest, shot, theme, viewportName })
          } catch (err) {
            log(`FAILED ${shot.name} (${theme}/${viewportName}): ${err.message}`)
          }
        }
      }
    }
  } finally {
    await browser.close()
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
