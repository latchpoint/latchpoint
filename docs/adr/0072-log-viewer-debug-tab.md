# ADR 0072: Log Viewer Debug Tab

## Status
Proposed

## Context
LatchPoint logs go to stdout and are captured by Docker's json-file driver, but there is no way to view logs from within the UI. When debugging issues, users must SSH into the server and run `docker logs`. ADR 0070 established the Debug page as an extensible container for diagnostic tools — a log viewer is the natural next tab.

This ADR documents the architecture for an in-browser log viewer that captures Python logs into an in-memory ring buffer (inspired by Home Assistant's `system_log` component) and streams them to a new "Logs" tab on the Debug page via the existing WebSocket infrastructure. Docker logs remain untouched — the new handler is purely additive.

## Decision

### Backend: Custom Log Handler with Ring Buffer

**Approach:** Custom `logging.Handler` subclass backed by a thread-safe `collections.deque` ring buffer.

Home Assistant uses `LogErrorHandler` → `DedupStore` (OrderedDict, 50 entries, deduplication, rate limiting). We adapt this for Django with simplifications:
- **Skip deduplication** — every entry is visible for full trace-ability
- **Skip rate limiting** — bounded buffer (default 500) is self-limiting
- **Skip QueueHandler pipeline** — `deque` with `threading.Lock` is sufficient since Django log emission happens in thread pool workers, not the async event loop
- **Keep dual-output model** — existing `StreamHandler` → stdout → Docker is untouched; new handler is additive

**Module: `alarm/log_handler.py`**
- `BufferedWebSocketHandler(logging.Handler)` — appends structured entries to `deque(maxlen=500)`, broadcasts WARNING+ over existing Channels `alarm` group
- Each entry stores both structured fields (level, logger, message, exc_text) AND a pre-formatted ANSI string for direct xterm.js rendering
- `get_buffered_entries(level?, logger_name?, limit?)` — read from buffer with optional filtering
- `clear_buffer()` — clear the ring buffer

**Logging config:** Add `"buffered_ws"` handler alongside existing `"console"` handler in both the root logger and each explicit per-module logger (since they have `propagate: False`).

**REST endpoint:** `GET /api/alarm/debug/logs/` — returns buffered entries for initial page load; `DELETE` clears buffer. Admin-only.

**WebSocket message type:** `log_entry` — follows existing envelope pattern `{ type, timestamp, sequence, payload }`. Broadcasts through existing `AlarmConsumer.broadcast()` — no consumer changes needed.

**Environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_VIEWER_CAPTURE_LEVEL` | `DEBUG` | Min level stored in buffer |
| `LOG_VIEWER_BROADCAST_LEVEL` | `WARNING` | Min level pushed over WebSocket |
| `LOG_VIEWER_BUFFER_SIZE` | `500` | Max entries in ring buffer |

**Log level ANSI color coding (backend-side formatting):**

| Level | ANSI Code | Color |
|-------|-----------|-------|
| DEBUG | `\033[90m` | Gray (bright black) |
| INFO | `\033[36m` | Cyan |
| WARNING | `\033[33m` | Yellow |
| ERROR | `\033[31m` | Red |
| CRITICAL | `\033[1;31m` | Bold Red |

### Frontend: Debug Page Tab Conversion

Convert the flat `DebugPage.tsx` into `DebugLayout.tsx` following the `SettingsLayout.tsx` pattern:
- NavLink tabs + Outlet
- Nested routes: `/debug/entities` (existing inspector), `/debug/logs` (new)
- Index redirect: `/debug` → `/debug/entities`

### Frontend: Log Viewer with xterm.js

**UI library: `@xterm/xterm`** wrapped in a custom React component.

Libraries evaluated and rejected:
- **@patternfly/react-log-viewer** — requires entire PatternFly design system, heavy CSS conflicts with Tailwind
- **@melloware/react-logviewer** — URL-centric API doesn't match our REST buffer + multiplexed WS data flow

Why xterm.js fits:
1. Programmatic `write()`/`writeln()` API matches our REST + WS data flow
2. Native ANSI color rendering — backend emits colored lines, terminal displays them directly
3. GPU-accelerated renderer with virtual scrolling handles any buffer size
4. `disableStdin: true` makes it a clean read-only viewer
5. Zero CSS conflicts — theming is JS-only, wraps in a Tailwind-styled container
6. Addon ecosystem — `@xterm/addon-search` for search, `@xterm/addon-fit` for responsive sizing

**Component structure:**
- `LogViewer.tsx` — xterm.js wrapper (Terminal + FitAddon + SearchAddon), toolbar, status bar
- `LogToolbar.tsx` — level filter, search, auto-scroll toggle, pause/resume, clear
- `useLogStream.ts` — WS subscription, writes to xterm
- `useLogBufferInit.ts` — initial buffer fetch, writes to xterm

**Data flow:**
1. On mount: `GET /api/alarm/debug/logs/` → write buffered entries to terminal via `terminal.writeln(entry.formatted)`
2. Real-time: `wsManager.onMessage` filters for `type === 'log_entry'` → `terminal.writeln(entry.formatted)`
3. Level filtering: Client-side check before writing (compare entry level against filter threshold)
4. Search: `@xterm/addon-search` provides `findNext()`/`findPrevious()` over the terminal buffer

**State management:** Minimal — xterm.js manages its own scrollback buffer. React wrapper manages `paused`, `autoScroll`, `levelFilter` state, and a queue for entries accumulated while paused.

## Alternatives Considered

- **Custom React log component with virtual scrolling** — would require Zustand store for entries, per-line React components, custom ANSI parsing, and a virtual scrolling library. xterm.js provides all of this out of the box with better performance.
- **Direct Docker log streaming** — would require Docker socket access and a separate backend service. The in-process ring buffer approach is simpler and sufficient for debugging.
- **File-based log storage** — adds complexity (rotation, disk management) with no benefit for a debug tool. Docker logs are the durable store; the ring buffer is ephemeral by design.

## Consequences

- Users can view recent logs directly in the browser without SSH access
- WARNING+ logs stream in real-time via existing WebSocket infrastructure
- Zero impact on existing logging — the new handler sits alongside `StreamHandler`
- Buffer is in-memory only — lost on restart (Docker logs remain the durable store)
- Admin-only access — log content contains internal paths, logger names, and stack traces
- The Debug page becomes a tabbed layout, establishing the pattern anticipated in ADR 0070

## Todos
- [ ] Create `alarm/log_handler.py` with `BufferedWebSocketHandler` and ring buffer
- [ ] Add `buffered_ws` handler to LOGGING config in settings.py
- [ ] Create `GET /api/alarm/debug/logs/` and `DELETE` REST endpoint (admin-only)
- [ ] Add `log_entry` WebSocket message type to broadcast pipeline
- [ ] Convert `DebugPage.tsx` to tabbed `DebugLayout.tsx` with nested routes
- [ ] Create `DebugEntitiesTab.tsx` wrapping existing `EntityStateInspector`
- [ ] Install `@xterm/xterm`, `@xterm/addon-fit`, `@xterm/addon-search`
- [ ] Build `LogViewer` component with xterm.js terminal wrapper
- [ ] Build `LogToolbar` with level filter, search, auto-scroll, pause, clear controls
- [ ] Create `useLogStream` hook for WS subscription
- [ ] Create `useLogBufferInit` hook for initial buffer fetch
- [ ] Add `log_entry` to frontend WebSocket message type union
- [ ] Add debug logs endpoint and query key to frontend services
