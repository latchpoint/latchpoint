# ADR 0011: Session Cookie Authentication for SPA

## Status
**Implemented**

## Context
The frontend previously stored API tokens in `localStorage` and authenticated WebSocket connections via `?token=...`.
This increases XSS blast radius (token exfiltration) and leaks credentials in URLs (logs, browser history, proxies).

The backend already supports Django sessions and CSRF middleware, but the login endpoint did not create a session.

## Decision
- Use Django session cookies (`sessionid`) as the primary authentication mechanism for the SPA.
- Use CSRF protection for unsafe methods (`POST`, `PUT`, `PATCH`, `DELETE`) via the `csrftoken` cookie and the
  `X-CSRFToken` header.
- Provide a lightweight `/api/auth/csrf/` endpoint to prime the `csrftoken` cookie for SPA clients.
- Keep token-based endpoints and WebSocket `?token=` support temporarily for backwards compatibility and tests.

## Alternatives Considered
- Keep `localStorage` bearer tokens and harden with CSP: still vulnerable to XSS token theft.
- Store tokens in memory only: improves exfiltration risk, but complicates refresh/rehydration and multi-tab behavior.
- Issue JWTs in httpOnly cookies: workable, but adds JWT lifecycle complexity vs. Django sessions already in place.

## Consequences
- Frontend API calls must use `credentials: 'include'`.
- Unsafe requests require CSRF header plumbing.
- WebSocket authentication can rely on session cookies (no credentials in URL).
- Existing token flows remain available but are not used by the SPA.

## Todos
- Make cookie security settings env-driven for production (`CSRF_COOKIE_SECURE`, `SESSION_COOKIE_SECURE`,
  `CSRF_COOKIE_SAMESITE`, `SESSION_COOKIE_SAMESITE`).
- Deprecate and remove token response fields and `/api/auth/token/refresh/` once no longer needed.
- Remove `?token=` WebSocket auth and related middleware when migration is complete.
