# ADR-0087: Banner Feedback for Integration Settings Save and Refresh

**Status:** Implemented
**Date:** 2026-04-23
**Author:** Leonardo Merza

## Context

### Background

Every integration settings tab (Home Assistant, MQTT, Z-Wave JS, Zigbee2MQTT,
Frigate) renders a shared `IntegrationOverviewCard` with a **Save** button
and a **Refresh** button. When a user clicks either, they currently get
inconsistent and occasionally silent feedback:

- **Save success** shows a generic info-coloured banner (e.g. `"Saved MQTT
  settings."`). Visually identical to a non-actionable hint.
- **Save failure** shows a red banner whose message is whatever
  `getErrorMessage(err)` returns — raw server text, sometimes a stack-trace
  excerpt, with no indication of *why* the save failed (bad credentials?
  backend down? validation?).
- **Refresh** refetches quietly in almost every integration. If the refetch
  fails, the user sees a stale card with no explanation. If it succeeds,
  there is no confirmation at all.

The ask from the user: every Save and Refresh should produce a clear banner
that tells them whether it worked and, if not, *why*.

### Current State

**Settings model hook pattern** — each integration has a hook that owns
`error` / `notice` strings and exposes `save()` / `refresh()`:

`frontend/src/features/mqtt/hooks/useMqttSettingsModel.ts`, lines 44–59:
```ts
const refresh = () => {
  void statusQuery.refetch()
  void settingsQuery.refetch()
}

const save = async () => {
  if (!draft) return
  setError(null)
  setNotice(null)
  try {
    await updateSettings.mutateAsync(draft)
    setNotice('Saved MQTT settings.')
  } catch (err) {
    setError(getErrorMessage(err) || 'Failed to save MQTT settings.')
  }
}
```

`useZwavejsSettingsModel.ts` follows the same shape;
`useZigbee2mqttSettingsModel.ts`, `useFrigateSettingsModel.ts`, and
`useHomeAssistantSettingsModel.ts` are minor variants. None of them set any
feedback on refresh — `refetch()` is fire-and-forget.

**Banner renderer** — `frontend/src/features/settings/components/SettingsTabShell.tsx`,
lines 38–46:
```tsx
{error ? (
  <Alert variant="error">
    <AlertDescription>{error}</AlertDescription>
  </Alert>
) : notice ? (
  <Alert>
    <AlertDescription>{notice}</AlertDescription>
  </Alert>
) : null}
```

The `notice` branch uses the default `<Alert>` variant, which resolves to
`variant: 'info'` in `frontend/src/components/ui/alert.tsx` (line 22). There
is no visual distinction between "settings saved" and a general info hint.

**Alert primitive** — `frontend/src/components/ui/alert.tsx`:
```ts
variant: {
  info:    '…muted/30…',
  success: '…success/10 text-success…',
  warning: '…warning/10 text-warning…',
  error:   '…destructive/10 text-destructive…',
},
```
The `success` variant exists and is already used elsewhere
(`frontend/src/pages/ImportSensorsPage.tsx:55`,
`frontend/src/features/setupMqtt/components/SetupMqttCard.tsx:89`), but no
settings *tab* uses it.

**Error shape** — `frontend/src/types/errors.ts` exposes `getErrorMessage()`,
which handles the ADR-0025 envelope (`{error: {message}}`), Django field
errors, and the `detail` / `non_field_errors` shapes. It returns a single
string; it does not classify by cause.

### Requirements

- Every Save emits a banner on both success and failure.
- Every Refresh emits a banner on both success and failure.
- Failure banners state *why* in plain English (network vs. auth vs.
  validation vs. server error), not raw server text.
- Success banners auto-dismiss after a few seconds. Failure banners stay
  sticky until the next action.
- Contract is shared across all five integrations so new integrations inherit
  it for free.

### Constraints

- No new UI dependency. Only `@radix-ui/react-slot` is installed; no toast
  library is mounted. `useNotificationStore` (Zustand) exists but has no
  visible container — introducing one is a separate design decision and out
  of scope.
- No change to the backend error envelope (ADR-0025 stays as-is).
- Existing `notice` consumers outside the integration tabs must continue to
  behave identically — no back-compat regression in `SettingsTabShell`.
- Follows the import boundary (`alarm/rules/`, `alarm/use_cases/`) but this
  ADR is frontend-only.

## Options Considered

### Option 1: Shared `useSettingsActionFeedback` hook + `noticeVariant` prop (chosen)

**Description:** Introduce a small hook
`frontend/src/features/integrations/lib/settingsFeedback.ts` that wraps the
save/refresh flow, sets `error` / `notice` / `noticeVariant` state, owns the
auto-dismiss timer, and categorizes errors via a companion
`categorizeSettingsError(err)` utility. Every integration settings model
hook adopts it. `SettingsTabShell` grows one additive prop,
`noticeVariant: 'info' | 'success'` (default `'info'`), so the `notice`
branch can render the green success Alert.

**Pros:**
- Reuses the existing `<Alert variant="success" | "error">` primitive.
- Reuses the existing `SettingsTabShell` banner slots.
- One implementation of auto-dismiss, one of error categorization — five
  integrations stay in lockstep.
- No new dependency.
- Backwards compatible: any caller of `SettingsTabShell` that doesn't pass
  `noticeVariant` keeps today's info-coloured behavior.

**Cons:**
- Adds one new helper module and one new prop.
- Category labels (`'validation' | 'auth' | 'network' | 'server' | 'unknown'`)
  are a client-side heuristic, not a server-declared contract. A backend
  error that doesn't fit the heuristic falls into `unknown` and shows raw
  server text — acceptable fallback.

### Option 2: Toast notifications via `useNotificationStore`

**Description:** Mount a `ToastContainer` that subscribes to the existing
`useNotificationStore` (Zustand). Each mutation calls `toast.success(…)` or
`toast.error(…)`; banners go away entirely.

**Pros:**
- Global: feedback is visible even if the user has scrolled.
- Store already exists — deduplication and auto-dismiss already
  implemented.

**Cons:**
- Requires mounting a brand-new visual container that affects every page,
  not just settings. That's a separate design call with its own accessibility
  and positioning questions.
- The user's ask explicitly says "banner feedback" — this substitutes a
  different UI primitive.
- Doesn't solve the "why did it fail" categorization problem; just moves
  it.
- The existing `ConnectionStatusBanner` already occupies fixed positioning
  at the bottom — introducing a toast stack raises layering questions.

### Option 3: Inline per-field validation only

**Description:** Leave Save/Refresh silent at the card level; attach
field-level error markers to each input on validation errors.

**Pros:**
- Most precise for validation errors.

**Cons:**
- Tells the user *which field* is wrong but not whether the *overall*
  Save succeeded.
- Doesn't help Refresh at all (no fields involved).
- Doesn't help network / auth / server errors at all.
- A regression from current behavior, which at least surfaces a top-level
  message.

### Option 4: Do nothing, document current behavior

**Description:** Accept that feedback is inconsistent; document it in
`IntegrationOverviewCard` so future developers know not to rely on it.

**Pros:** Zero change.

**Cons:** Defeats the user's explicit ask. Leaves silent-refresh and
untyped-error as known bad UX.

## Decision

**Chosen Option:** Option 1 — shared `useSettingsActionFeedback` hook, a new
`categorizeSettingsError` utility, and an additive `noticeVariant` prop on
`SettingsTabShell`. Banners stay; toasts do not enter the equation.

**Rationale:**
- The infrastructure is 90% there: `SettingsTabShell` renders banners,
  `<Alert>` has a `success` variant, five hooks already manage `error` /
  `notice` state. The gap is a shared *contract*, not a new UI primitive.
- Placing auto-dismiss and categorization in the helper (not in the shell)
  keeps the shell a dumb renderer and avoids a behavior ripple for any
  other consumer that passes a `notice` string.
- Categorizing errors into five plain-English buckets addresses the user's
  "why didn't it" ask without requiring backend changes.

### Sub-decisions

**Helper module** — `frontend/src/features/integrations/lib/settingsFeedback.ts`:

```ts
export type SettingsErrorCategory =
  | 'validation'
  | 'auth'
  | 'network'
  | 'server'
  | 'unknown'

export interface CategorizedError {
  category: SettingsErrorCategory
  message: string
}

export function categorizeSettingsError(
  err: unknown,
  verbPrefix: 'Save' | 'Refresh'
): CategorizedError

export function useSettingsActionFeedback(options?: {
  saveDismissMs?: number      // default 5000
  refreshDismissMs?: number   // default 3000
}): {
  error: string | null
  notice: string | null
  noticeVariant: 'info' | 'success'
  clear: () => void
  runSave: <T>(fn: () => Promise<T>, successMessage: string) => Promise<T | undefined>
  runRefresh: <T>(fn: () => Promise<T>, successMessage: string) => Promise<T | undefined>
}
```

Error categorization heuristic (client-side, keyed on the `ApiError` shape
thrown by `services/api.ts` and the `TypeError` that `fetch` throws on
network failure):

| Condition | Category | Message template |
|---|---|---|
| `err.code === '400'` and `err.details` is a record of field errors | `validation` | `"<Verb> failed: <field> — <detail>"` (first offending field) |
| `err.code === '401' \|\| '403'` | `auth` | `"<Verb> failed: you don't have permission to change these settings."` |
| `err instanceof TypeError` (fetch failed: DNS, offline, CORS, abort) | `network` | `"<Verb> failed: could not reach the server. Check your connection and try again."` |
| `Number.parseInt(err.code) >= 500` | `server` | `"<Verb> failed: the server returned an error. Check logs."` (+ appended server `detail` if present) |
| Anything else | `unknown` | `getErrorMessage(err)` fallback, prefixed with `"<Verb> failed: "` |

Note: `services/api.ts` always sets `code` to `response.status.toString()`,
so the validation/auth/server rows compare strings, not numbers. There is
no Axios in this codebase — `ECONNABORTED` / `ERR_NETWORK` do not appear.

`<Verb>` is `"Save"` or `"Refresh"`. The template picker is an internal
switch; integrations never see the category label in the UI — only the
rendered message.

**Auto-dismiss ownership.** The timer lives in
`useSettingsActionFeedback`, not in `SettingsTabShell`. A `useEffect` keyed
on `notice` sets a `setTimeout` that clears the notice after
`saveDismissMs` / `refreshDismissMs` depending on which verb was last run.
Errors do not auto-clear. This keeps the shell a pure renderer — any caller
not using the helper keeps today's indefinite-display behavior.

**Shell change.** `SettingsTabShell` accepts a new optional prop:

```ts
noticeVariant?: 'info' | 'success'  // default: 'info'
```

The `notice` branch becomes:

```tsx
<Alert variant={noticeVariant === 'success' ? 'success' : 'info'}>
  <AlertDescription>{notice}</AlertDescription>
</Alert>
```

Callers that don't pass the prop keep the info-coloured banner they have
today. The five integration tabs pass `noticeVariant={model.noticeVariant}`.

**Integration adoption.** All five integration settings model hooks
(`useMqttSettingsModel`, `useZwavejsSettingsModel`,
`useZigbee2mqttSettingsModel`, `useFrigateSettingsModel`,
`useHomeAssistantSettingsModel`) replace their local
`[error, setError] + [notice, setNotice]` pair with the helper's return
values. `refresh()` wraps the refetches in `runRefresh`; `save()` wraps the
mutation in `runSave`. This is a prescribed change, not optional — the
point of the ADR is consistency across the five.

The Z-Wave JS `sync` action (`syncEntities`) is distinct from Save/Refresh
and stays on its own code path for now — the helper targets the two
universal verbs. A follow-up ADR can extend to secondary actions if the
feedback pattern proves out.

**Out of scope for 0087:**
- Notifications *provider* CRUD modal (separate flow; not a settings tab).
- Global toast system.
- Server-declared error category in the API envelope.

## Consequences

### Positive

- Every Save and every Refresh produces a consistent banner on both success
  and failure, across all five integrations.
- Failure banners tell the user *why*: network, auth, validation, or
  server-side.
- Success banners auto-dismiss so the card stays scannable.
- No new dependency; reuses `Alert`, `SettingsTabShell`, `getErrorMessage`,
  and the `success` Alert variant already in use elsewhere in the app.
- A sixth integration added tomorrow inherits the pattern by calling the
  helper.

### Negative

- Five integration model hooks change simultaneously in the follow-up PR.
  Tests for each will need a minor update (already covered — each
  integration has a model-hook test file).
- Client-side error categorization is a heuristic; a weird backend
  response may fall into `unknown` and show raw text. Mitigation: `unknown`
  is still a full sentence, just less specific.
- One new shell prop (`noticeVariant`) is additive but introduces a second
  way to style the notice. Documented default (`'info'`) keeps back-compat
  obvious.

### Neutral

- The helper lives under `features/integrations/lib/` because it is
  integration-settings-specific. If a non-integration settings tab later
  wants the same contract, it can import the helper directly — no need to
  promote it higher until that second use case appears.
- Auto-dismiss timers (5s / 3s) are parameterized via hook options — a
  future consumer that wants different cadences can override without a
  helper change.

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Auto-dismiss hides a success the user didn't see in time | Low | Low | Errors are sticky; only the *success* banner dismisses. 5s is longer than typical SaaS success toasts (3s). |
| Categorization misfires on an unusual backend error | Medium | Low | `unknown` fallback uses `getErrorMessage()`, preserving today's behavior for errors the heuristic can't classify. |
| A non-integration caller of `SettingsTabShell` starts rendering green by accident | Low | Low | `noticeVariant` defaults to `'info'`; omitting the prop is the back-compat path. |
| Refresh feedback annoys users because it fires on every pane load | Low | Low | Refresh is user-triggered (button click), not auto — no banner on mount. |

## Implementation Plan

- [x] **Phase 1 — Helper module**
  - Add `frontend/src/features/integrations/lib/settingsFeedback.ts` with
    `categorizeSettingsError(err, verbPrefix)` and
    `useSettingsActionFeedback(options?)`.
  - Unit tests (`settingsFeedback.test.ts`): each category produces the
    expected message; auto-dismiss timer clears success after the
    configured ms; errors are not dismissed; `runSave` / `runRefresh`
    return `undefined` on failure and the value on success; `clear()`
    resets both state slots.

- [x] **Phase 2 — Shell prop**
  - Add `noticeVariant?: 'info' | 'success'` to `SettingsTabShell` with
    default `'info'`.
  - Extend `SettingsTabShell.test.tsx` to cover both variants.

- [x] **Phase 3 — Integration adoption**
  - Migrate `useMqttSettingsModel` to use the helper. Tests in
    `useMqttSettingsModel.test.tsx` (or the tab-level test) verify that
    Save success sets a success notice, Save failure sets an error in the
    correct category, Refresh success sets a success notice, Refresh
    failure sets an error.
  - Repeat for `useZwavejsSettingsModel`, `useZigbee2mqttSettingsModel`,
    `useFrigateSettingsModel`, `useHomeAssistantSettingsModel`.
  - Pass `noticeVariant` from each model down through the respective
    settings tab page into `SettingsTabShell`.
  - Follow-up fix: TanStack Query's `query.refetch()` resolves with
    `{ isError, error }` rather than rejecting; each hook's `runRefresh`
    inspects the resolved results and rethrows the first `isError` so
    failures are categorized instead of silently turning into a green
    success notice.

- [x] **Phase 4 — Verification**
  - `npx eslint src/` — no new errors.
  - `npx tsc --noEmit` — types clean.
  - `npx vitest run` — all existing suites pass; new helper + shell tests
    pass; each integration model's tests pass.
  - Manual: open each of the five settings tabs, click Save with valid
    data, click Save with the backend stopped, click Refresh with the
    backend stopped. Confirm banners match the table in the Decision
    section.

- [x] **Phase 5 — Docs**
  - Flip this ADR to **Implemented**.
  - Entry in `docs/adr/0000-adr-index.md` moves from Proposed to
    Implemented.
  - No CLAUDE.md change — the contract lives in the helper's JSDoc and is
    discoverable from any integration settings model.

## Acceptance Criteria

- [x] **AC-1:** `categorizeSettingsError(err, 'Save')` returns `{category: 'validation', message}` when the error has HTTP status 400 with field errors; the message names the first offending field.
- [x] **AC-2:** `categorizeSettingsError(err, verb)` returns `{category: 'auth', message}` for HTTP 401 and 403; message reads "<Verb> failed: you don't have permission to change these settings."
- [x] **AC-3:** `categorizeSettingsError(err, verb)` returns `{category: 'network', message}` when the error is a `TypeError` (the shape `fetch()` throws on network failure: offline, DNS, CORS, abort); message tells the user to check their connection.
- [x] **AC-4:** `categorizeSettingsError(err, verb)` returns `{category: 'server', message}` for HTTP status >= 500; appends the server `detail` field if present.
- [x] **AC-5:** `categorizeSettingsError(err, verb)` returns `{category: 'unknown', message}` for anything else — message prefixed with `<Verb> failed: ` and body from `getErrorMessage(err)`.
- [x] **AC-6:** `useSettingsActionFeedback().runSave(fn, msg)` on success sets `notice === msg`, `noticeVariant === 'success'`, `error === null`, and returns the resolved value.
- [x] **AC-7:** `useSettingsActionFeedback().runSave(fn, msg)` on failure sets `error` to the categorized message, leaves `notice === null`, and returns `undefined`.
- [x] **AC-8:** `useSettingsActionFeedback().runRefresh(fn, msg)` mirrors AC-6/AC-7 with `'Refresh'` as the verb prefix in error messages.
- [x] **AC-9:** Success notices auto-clear after `saveDismissMs` (default 5000) for Save and `refreshDismissMs` (default 3000) for Refresh; errors do NOT auto-clear.
- [x] **AC-10:** `useSettingsActionFeedback().clear()` resets both `error` and `notice` to `null`, resets `noticeVariant` to `'info'`, and cancels any pending dismiss timer.
- [x] **AC-11:** `useSettingsActionFeedback().setNotice(msg)` writes `notice = msg`, forces `noticeVariant = 'info'`, does NOT start the dismiss timer, and clears any prior `error`. `setError(msg)` mirrors it for `error` (and clears `notice`). These are the entry points for non-Save/Refresh actions (`sync`, `reset`, `publishDiscovery`) so they keep today's UX byte-for-byte.
- [x] **AC-12:** `<SettingsTabShell noticeVariant="success" notice="x">` renders the notice in the success Alert variant; omitting the prop preserves the existing `info` default (back-compat for non-integration callers).
- [x] **AC-13:** `useMqttSettingsModel`'s `save()` routes through `runSave` (success → green notice; failure → categorized red error). Its `refresh()` routes through `runRefresh` (success → green notice; failure → categorized red error).
- [x] **AC-14:** Same as AC-13 for `useZwavejsSettingsModel`. The `sync()` action calls `helper.setError` / `helper.setNotice` (info variant, no auto-dismiss) — regression test asserts `sync()` notices stay info-colored and do not auto-clear.
- [x] **AC-15:** Same as AC-13 for `useZigbee2mqttSettingsModel`.
- [x] **AC-16:** Same as AC-13 for `useFrigateSettingsModel`. The `reset()` action calls `helper.setError` / `helper.setNotice` (info variant, no auto-dismiss) — regression test asserts `reset()` notices stay info-colored and do not auto-clear.
- [x] **AC-17:** Same as AC-13 for `useHomeAssistantSettingsModel`, applied to both pairs (`saveConnection`/`refreshConnection` and `saveMqttEntity`/`refreshMqttEntity`) sharing one helper instance. The `publishDiscovery()` action calls `helper.setError` / `helper.setNotice` (info variant, no auto-dismiss) — regression test asserts `publishDiscovery()` notices stay info-colored and do not auto-clear.
- [x] **AC-18:** Each of the five integration settings tab pages (`SettingsMqttTab`, `SettingsZwavejsTab`, `SettingsZigbee2mqttTab`, `SettingsFrigateTab`, `SettingsHomeAssistantTab`) passes `noticeVariant={model.noticeVariant}` to `SettingsTabShell`.

## Related ADRs

- [ADR-0025](./0025-api-error-envelope.md) — API error envelope
  (`{error: {message}}`) that `getErrorMessage()` parses. This ADR consumes
  that envelope unchanged.
- [ADR-0053](./0053-ui-brand-design-system.md) — brand color tokens
  (`--color-success`, `--color-destructive`) that the `Alert` variants map
  to. No palette change here; we just start using the `success` variant in
  the settings context.
- [ADR-0079](./0079-ui-config-with-encrypted-credentials.md) — DB-backed
  integration settings and the `IntegrationSettingsForm` that every
  integration renders. This ADR adds feedback on top of the Save/Refresh
  surface that 0079 produced.
- [ADR-0086](./0086-ha-entity-equals-editable-dropdown.md) — precedent for
  frontend-only UX improvements that reuse an existing primitive rather
  than introducing a dependency.

## References

- `frontend/src/features/settings/components/SettingsTabShell.tsx`
  (lines 38–46) — the banner slot the new `noticeVariant` prop extends.
- `frontend/src/components/ui/alert.tsx` (lines 6–25) — `success` / `error`
  variants reused as-is.
- `frontend/src/features/integrations/components/IntegrationOverviewCard.tsx`
  (lines 79–103) — hosts the Save and Refresh buttons; no change.
- `frontend/src/features/mqtt/hooks/useMqttSettingsModel.ts`
  (lines 44–59) — example of the current silent-refresh + generic-save
  pattern being replaced.
- `frontend/src/features/zwavejs/hooks/useZwavejsSettingsModel.ts`
  (lines 38–70) — same pattern; note the `sync` action stays on its own
  code path.
- `frontend/src/features/zigbee2mqtt/hooks/useZigbee2mqttSettingsModel.ts`,
  `frontend/src/features/frigate/hooks/useFrigateSettingsModel.ts`,
  `frontend/src/features/homeAssistant/hooks/useHomeAssistantSettingsModel.ts`
  — the other three hooks that adopt the helper.
- `frontend/src/types/errors.ts` — `getErrorMessage()` + `ApiErrorResponse`
  reused as the `unknown`-bucket fallback.
- `frontend/src/pages/ImportSensorsPage.tsx:55`,
  `frontend/src/features/setupMqtt/components/SetupMqttCard.tsx:89` —
  existing precedent for `<Alert variant="success">` elsewhere in the app.

## Todos

- Helper module with tests.
- `noticeVariant` prop on `SettingsTabShell` with tests.
- Migrate all five integration settings model hooks.
- Smoke-test each settings tab end-to-end with the backend stopped.
- Flip status to Implemented once merged.
