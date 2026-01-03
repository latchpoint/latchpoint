# ADR 0050: Paginate Recent Frigate Detections UI (Page Size 5)

## Status
Implemented

## Context
The Settings → Frigate "Recent detections" card is an admin-only debug view that currently renders the full list of fetched detections in one long stack. This gets noisy quickly and makes it harder to scan recent events or jump between a few items when debugging.

We want a compact, predictable UI that shows a small page of detections at a time.

## Decision
Paginate the "Recent detections" UI with a page size of **5**.

- The card shows 5 detections per page with simple Prev/Next controls.
- The existing detections API remains unchanged initially (it already supports a `?limit=` cap, but has no server-side paging/offset).
- The first implementation paginates client-side over the fetched list (currently fetched with `limit=25`), so the user can page through up to 5 pages without additional backend work.

## Alternatives Considered
- **Show only the most recent 5** (no pagination): simplest, but makes it harder to inspect a little history without repeated refreshes.
- **Server-side pagination** (cursor/offset): more scalable, but requires API contract changes (including `meta.next`/cursor) and more tests.
- **Infinite scroll**: more UI complexity than needed for an admin debug card.

## Consequences
- Improves readability and reduces scrolling in the Frigate settings UI.
- Client-side paging means we still fetch more than 5 rows initially, but the payload is small and admin-only.
- If we later change the query to fetch additional pages on demand, the detections query key should include the effective `limit`/paging params to avoid React Query cache collisions.

## Todos
- Add paging controls to `FrigateRecentDetectionsCard`.
- Default to page 1 (most recent) and reset to page 1 on refresh.
- (Optional follow-up) If detections volume grows, add cursor-based paging to `GET /api/alarm/integrations/frigate/detections/` with `{ data, meta }`.

