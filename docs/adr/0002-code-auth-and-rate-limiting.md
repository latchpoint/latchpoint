# ADR 0002: Code Auth and Rate Limiting (MVP)

## Status
**Implemented**

## Context
The MVP needs clear code permissions and protection against brute-force attempts.

## Decision
- Define code_type permissions:
  - master: always allowed to disarm/override; can arm/disarm in any state.
  - admin: can arm/disarm; can manage codes.
  - user: can arm/disarm with own code only.
- Enforce per-code lockout using failed_attempts + lockout_until.
- Add a global rate limit at the API/auth layer (per user, per device, and per IP).

## Alternatives Considered
- No explicit permissions; treat all codes equally.
- Per-code lockout only, no global rate limiting.
- Per-user lockout only, no per-code tracking.

## Consequences
- Permission checks must be enforced in service/command handlers.
- API layer needs rate limiting with per-user/device/IP context.
- Operational configuration for rate limits should be exposed in settings.

## Todos
- Decide how device identity is tracked (e.g., session id, device token).
- Define default rate limits and lockout thresholds.
- Update API docs to document lockout/rate limit responses.
