# ADR 0039: Unified Error Handling

## Status
Implemented

## Context

Error handling across the application is inconsistent, making it difficult to debug issues, provide clear error messages to users, and maintain the codebase. This ADR addresses the **exception hierarchy and handling patterns**.

### Relationship to ADR 0025 (Standardized API Response Format)

**This ADR should be implemented BEFORE ADR 0025.**

| ADR | Focus | Priority |
|-----|-------|----------|
| **0039 (this)** | Exception hierarchy, error handling, HTTP status mapping | **First** |
| 0025 | Response envelope structure for all API responses | Second |

**Rationale:**
1. **Safety first** - Ensure all app logic is safely wrapped with proper exception handling before standardizing response formats
2. **Debugging** - Consistent errors with `error_code` and `detail` fields make frontend debugging straightforward
3. **Foundation** - The error response structure defined here (`{"detail": "...", "error_code": "..."}`) becomes the foundation that ADR 0025 builds upon
4. **Incremental value** - Error handling improvements provide immediate value; response envelope standardization can follow later

### Current State Analysis

#### 1. Multiple Exception Hierarchies

**Domain Exceptions** (`config/domain_exceptions.py`) - Well-designed:
```python
DomainError (base)
├── ValidationError
├── UnauthorizedError
├── ForbiddenError
├── NotFoundError
├── ConflictError
└── ServiceUnavailableError
```

**Gateway Exceptions** - Inconsistent, use `RuntimeError` as base:
- `gateways/home_assistant.py`: `HomeAssistantGatewayError`, `HomeAssistantNotConfigured`, `HomeAssistantNotReachable`
- `integrations_zwavejs/manager.py`: `ZwavejsGatewayError`, `ZwavejsNotConfigured`, `ZwavejsNotReachable`, `ZwavejsClientUnavailable`, `ZwavejsNotConnected`, `ZwavejsCommandError`
- `transports_mqtt/manager.py`: `MqttGatewayError`, `MqttNotConfigured`, `MqttNotReachable`, `MqttClientUnavailable`, `MqttPublishError`, `MqttSubscribeError`

**State Machine Exceptions** (`state_machine/errors.py`) - Uses `RuntimeError`:
- `TransitionError`, `CodeRequiredError`, `InvalidCodeError`

**Use Case Exceptions** - Mixed inheritance:
- `accounts/use_cases/auth.py`: `InvalidCredentials(UnauthorizedError)`, `InvalidRefreshToken(UnauthorizedError)` - Correct
- `accounts/use_cases/code_validation.py`: `CodeValidationError(RuntimeError)` - Inconsistent
- `locks/use_cases/code_validation.py`: `CodeValidationError(RuntimeError)` - Inconsistent
- `accounts/use_cases/onboarding.py`: `OnboardingError(RuntimeError)` - Inconsistent
- `alarm/use_cases/alarm_actions.py`: `AlarmActionError(RuntimeError)` - Inconsistent

**Other RuntimeError-based Exceptions:**
- `alarm/rules_engine.py`: `RuleEngineError(RuntimeError)` - Should be `DomainError`
- `integrations_home_assistant/impl.py`: `HomeAssistantAvailabilityError(RuntimeError)` - Should be `GatewayError`

#### 2. Exception Handler Coverage Gaps

**File:** `config/exception_handler.py`

Currently handles:
- All `DomainError` subclasses
- `HomeAssistantNotConfigured`, `HomeAssistantNotReachable`
- `TransitionError`

**Not registered (require manual handling in views):**
- `ZwavejsNotConfigured`, `ZwavejsNotReachable`, `ZwavejsClientUnavailable`
- `MqttNotConfigured`, `MqttNotReachable`, `MqttClientUnavailable`
- `CodeValidationError` variants

#### 3. Broad Exception Catching

The codebase has **170+ occurrences** of `except Exception` across **40+ files**. These need to be categorized by cleanup priority:

**Priority 1: Views (Must Fix)** - User-facing, need proper error responses:

| File | Occurrences | Issue |
|------|-------------|-------|
| `notifications/views.py` | 3 | Catches all exceptions during save |
| `control_panels/views.py` | 2 | Generic exception handlers |
| `integrations_zigbee2mqtt/views.py` | 2 | Generic error handlers |
| `integrations_frigate/views.py` | 1 | Int conversion errors |
| `integrations_zwavejs/views.py` | 7 | Generic handlers for Z-Wave operations |
| `integrations_home_assistant/views.py` | 3 | Generic handlers |
| `transports_mqtt/views.py` | 1 | Generic handler |
| `locks/views/sync.py` | 1 | Generic handler |
| `alarm/views/entities.py` | 1 | Generic handler |

**Priority 2: Managers/Gateways (Should Fix)** - Core integration logic:

| File | Occurrences | Issue |
|------|-------------|-------|
| `integrations_zwavejs/manager.py` | 15+ | Many broad catches in connection/command handling |
| `transports_mqtt/manager.py` | 12+ | Broad catches in MQTT operations |
| `alarm/gateways/home_assistant.py` | 1 | Connection handling |
| `integrations_home_assistant/impl.py` | 8+ | State sync and entity operations |

**Priority 3: Runtime/Background (Review Case-by-Case)** - Many are intentional for resilience:

| File | Occurrences | Likely Intentional? |
|------|-------------|---------------------|
| `integrations_zigbee2mqtt/runtime.py` | 20+ | Mostly yes - event loop resilience |
| `integrations_frigate/runtime.py` | 12+ | Mostly yes - event loop resilience |
| `control_panels/zwave_ring_keypad_v2.py` | 12+ | Mostly yes - hardware resilience |
| `scheduler/runner.py` | 1 | Yes - task isolation |
| `notifications/dispatcher.py` | 2 | Yes - notification isolation |

**Priority 4: Startup/Config (Keep As-Is)** - Fail gracefully on startup:

| File | Occurrences | Reason to Keep |
|------|-------------|----------------|
| `*/apps.py` | 15+ | AppConfig.ready() should not crash server |
| `*/config.py` | 5+ | Config loading should fail gracefully |
| `alarm/crypto.py` | 2 | Encryption fallback handling |

#### 4. Inconsistent Response Fields

| Pattern | Files | Issue |
|---------|-------|-------|
| `{"detail": "..."}` | Most views | Preferred |
| `{"error": "..."}` | `notifications/views.py` | Legacy |
| `{"detail": "...", "error": "..."}` | Integration views | Mixed |

#### 5. Missing Logging

Some exception handlers log nothing:
- `control_panels/views.py` lines 46-49: No logging for Z-Wave JS validation failures
- `integrations_frigate/views.py` lines 179-180: No logging for conversion errors

---

## Decision

### 1. Unified Exception Hierarchy

Create a consistent exception hierarchy for all external integrations:

```python
# config/domain_exceptions.py (updated)

class DomainError(Exception):
    """Base exception for all domain/business logic errors."""
    pass

class ValidationError(DomainError):
    """Invalid input or state."""
    pass

class UnauthorizedError(DomainError):
    """Authentication required or failed."""
    pass

class ForbiddenError(DomainError):
    """Authenticated but not permitted."""
    pass

class NotFoundError(DomainError):
    """Resource does not exist."""
    pass

class ConflictError(DomainError):
    """State conflict (duplicate, concurrent modification)."""
    pass

class ServiceUnavailableError(DomainError):
    """External service not available."""
    pass

class ConfigurationError(DomainError):
    """Required configuration is missing or invalid."""
    pass

class OperationTimeoutError(DomainError):
    """Operation timed out waiting for response."""
    pass


# NEW: Gateway base exception
# Note: Using SINGLE inheritance to avoid diamond pattern MRO issues.
# The exception handler uses duck-typing (checking attributes) instead of isinstance checks
# for specific error types.

class GatewayError(DomainError):
    """Base exception for all external gateway/integration errors.

    Subclasses should set `gateway_name` as a class attribute or instance attribute.
    """
    gateway_name: str | None = None
```

### 2. Migrate Gateway Exceptions

Each gateway module defines exceptions that inherit from the gateway-specific base class.
Single inheritance is used to avoid diamond pattern MRO issues:

```python
# gateways/home_assistant.py (updated)
from config.domain_exceptions import GatewayError

GATEWAY_NAME = "Home Assistant"

class HomeAssistantError(GatewayError):
    """Base exception for Home Assistant gateway errors."""
    gateway_name = GATEWAY_NAME

class HomeAssistantNotConfigured(HomeAssistantError):
    """Home Assistant is not configured."""
    def __init__(self, message: str | None = None):
        super().__init__(message or f"{GATEWAY_NAME} is not configured.")

class HomeAssistantNotReachable(HomeAssistantError):
    """Home Assistant service is not reachable."""
    def __init__(self, error: str | None = None):
        self.error = error
        message = f"{GATEWAY_NAME} is not reachable."
        if error:
            message = f"{message} Error: {error}"
        super().__init__(message)
```

```python
# integrations_zwavejs/manager.py (updated)
from config.domain_exceptions import GatewayError

GATEWAY_NAME = "Z-Wave JS"

class ZwavejsError(GatewayError):
    """Base exception for Z-Wave JS gateway errors."""
    gateway_name = GATEWAY_NAME

class ZwavejsNotConfigured(ZwavejsError):
    """Z-Wave JS is not configured."""
    def __init__(self, message: str | None = None):
        super().__init__(message or f"{GATEWAY_NAME} is not configured.")

class ZwavejsNotReachable(ZwavejsError):
    """Z-Wave JS service is not reachable."""
    def __init__(self, error: str | None = None):
        self.error = error
        message = f"{GATEWAY_NAME} is not reachable."
        if error:
            message = f"{message} Error: {error}"
        super().__init__(message)

class ZwavejsClientUnavailable(ZwavejsError):
    """Z-Wave JS client is not connected."""
    def __init__(self, message: str | None = None):
        super().__init__(message or f"{GATEWAY_NAME} client is not connected.")

class ZwavejsCommandError(ZwavejsError):
    """A Z-Wave JS command failed."""
    def __init__(self, operation: str, error: str | None = None):
        self.operation = operation
        self.error = error
        message = f"{GATEWAY_NAME} {operation} failed."
        if error:
            message = f"{message} Error: {error}"
        super().__init__(message)
```

```python
# transports_mqtt/manager.py (updated)
from config.domain_exceptions import GatewayError

GATEWAY_NAME = "MQTT"

class MqttError(GatewayError):
    """Base exception for MQTT gateway errors."""
    gateway_name = GATEWAY_NAME

class MqttNotConfigured(MqttError):
    """MQTT is not configured."""
    def __init__(self, message: str | None = None):
        super().__init__(message or f"{GATEWAY_NAME} is not configured.")

class MqttNotReachable(MqttError):
    """MQTT broker is not reachable."""
    def __init__(self, error: str | None = None):
        self.error = error
        message = f"{GATEWAY_NAME} is not reachable."
        if error:
            message = f"{message} Error: {error}"
        super().__init__(message)

class MqttClientUnavailable(MqttError):
    """MQTT client is not connected."""
    def __init__(self, message: str | None = None):
        super().__init__(message or f"{GATEWAY_NAME} client is not connected.")

class MqttPublishError(MqttError):
    """MQTT publish operation failed."""
    def __init__(self, topic: str, error: str | None = None):
        self.operation = f"publish to {topic}"
        self.error = error
        message = f"{GATEWAY_NAME} publish to {topic} failed."
        if error:
            message = f"{message} Error: {error}"
        super().__init__(message)

class MqttSubscribeError(MqttError):
    """MQTT subscribe operation failed."""
    def __init__(self, topic: str, error: str | None = None):
        self.operation = f"subscribe to {topic}"
        self.error = error
        message = f"{GATEWAY_NAME} subscribe to {topic} failed."
        if error:
            message = f"{message} Error: {error}"
        super().__init__(message)
```

### 3. Centralized Exception Handler

Update `config/exception_handler.py` to handle all gateway exceptions using duck-typing
(check for attributes like `gateway_name`, `error`, `operation`) rather than multiple inheritance:

```python
# config/exception_handler.py (updated)
import logging
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from alarm.state_machine.errors import (
    TransitionError,
    CodeRequiredError,
    InvalidCodeError,
)
from config import domain_exceptions as domain

logger = logging.getLogger(__name__)

# Standard error codes for frontend
ERROR_CODES = {
    "VALIDATION_ERROR": "validation_error",
    "BAD_REQUEST": "bad_request",
    "UNAUTHORIZED": "unauthorized",
    "FORBIDDEN": "forbidden",
    "NOT_FOUND": "not_found",
    "CONFLICT": "conflict",
    "TIMEOUT": "timeout",
    "SERVICE_UNAVAILABLE": "service_unavailable",
    "CONFIGURATION_ERROR": "configuration_error",
    "GATEWAY_ERROR": "gateway_error",
    "SERVER_ERROR": "server_error",
}


def _get_gateway_name(exc: Exception) -> str | None:
    """Extract gateway name from exception using duck-typing."""
    return getattr(exc, "gateway_name", None)


def _is_not_configured(exc: Exception) -> bool:
    """Check if exception indicates 'not configured' state."""
    return "not configured" in str(exc).lower()


def _is_not_reachable(exc: Exception) -> bool:
    """Check if exception indicates 'not reachable' state."""
    return "not reachable" in str(exc).lower() or hasattr(exc, "error")


def _is_client_unavailable(exc: Exception) -> bool:
    """Check if exception indicates 'client unavailable' state."""
    return "client" in str(exc).lower() and "not connected" in str(exc).lower()


def custom_exception_handler(exc, context):
    """
    Centralized exception handler for all API views.

    Handles:
    - DRF built-in exceptions
    - State machine exceptions (TransitionError hierarchy)
    - Domain exceptions (DomainError hierarchy)
    - Gateway exceptions (GatewayError hierarchy)
    - Unexpected exceptions (logged and returned as 500)
    """
    # Let DRF handle its own exceptions first
    response = drf_exception_handler(exc, context)
    if response is not None:
        return _format_drf_error(response)

    # --- State Machine Exceptions ---
    if isinstance(exc, InvalidCodeError):
        return _error_response(
            ERROR_CODES["UNAUTHORIZED"],
            str(exc),
            status.HTTP_401_UNAUTHORIZED,
        )

    if isinstance(exc, CodeRequiredError):
        return _error_response(
            ERROR_CODES["VALIDATION_ERROR"],
            str(exc),
            status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, TransitionError):
        return _error_response(
            ERROR_CODES["CONFLICT"],
            str(exc),
            status.HTTP_409_CONFLICT,
        )

    # --- Gateway Exceptions (duck-typed) ---
    if isinstance(exc, domain.GatewayError):
        gateway = _get_gateway_name(exc)

        # Not configured → 503 (server-side config issue)
        if _is_not_configured(exc):
            logger.warning("Gateway not configured: %s", gateway or "unknown")
            return _error_response(
                ERROR_CODES["SERVICE_UNAVAILABLE"],
                str(exc),
                status.HTTP_503_SERVICE_UNAVAILABLE,
                gateway=gateway,
            )

        # Not reachable → 503
        if _is_not_reachable(exc):
            logger.warning(
                "Gateway unreachable: %s - %s",
                gateway or "unknown",
                getattr(exc, "error", None) or "no details",
            )
            return _error_response(
                ERROR_CODES["SERVICE_UNAVAILABLE"],
                str(exc),
                status.HTTP_503_SERVICE_UNAVAILABLE,
                gateway=gateway,
                error=getattr(exc, "error", None),
            )

        # Client unavailable → 503
        if _is_client_unavailable(exc):
            logger.warning("Gateway client unavailable: %s", gateway or "unknown")
            return _error_response(
                ERROR_CODES["SERVICE_UNAVAILABLE"],
                str(exc),
                status.HTTP_503_SERVICE_UNAVAILABLE,
                gateway=gateway,
            )

        # Operation error (has operation attribute) → 502
        if hasattr(exc, "operation"):
            logger.warning(
                "Gateway operation failed: %s %s - %s",
                gateway or "unknown",
                exc.operation,
                getattr(exc, "error", None) or "no details",
            )
            return _error_response(
                ERROR_CODES["GATEWAY_ERROR"],
                str(exc),
                status.HTTP_502_BAD_GATEWAY,
                gateway=gateway,
                operation=exc.operation,
                error=getattr(exc, "error", None),
            )

        # Generic gateway error → 502
        logger.warning("Gateway error: %s - %s", gateway or "unknown", str(exc))
        return _error_response(
            ERROR_CODES["GATEWAY_ERROR"],
            str(exc),
            status.HTTP_502_BAD_GATEWAY,
            gateway=gateway,
        )

    # --- Domain Exceptions ---
    if isinstance(exc, domain.ValidationError):
        return _error_response(
            ERROR_CODES["VALIDATION_ERROR"],
            str(exc),
            status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, domain.ConfigurationError):
        return _error_response(
            ERROR_CODES["CONFIGURATION_ERROR"],
            str(exc),
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if isinstance(exc, domain.UnauthorizedError):
        return _error_response(
            ERROR_CODES["UNAUTHORIZED"],
            str(exc),
            status.HTTP_401_UNAUTHORIZED,
        )

    if isinstance(exc, domain.ForbiddenError):
        return _error_response(
            ERROR_CODES["FORBIDDEN"],
            str(exc),
            status.HTTP_403_FORBIDDEN,
        )

    if isinstance(exc, domain.NotFoundError):
        return _error_response(
            ERROR_CODES["NOT_FOUND"],
            str(exc),
            status.HTTP_404_NOT_FOUND,
        )

    if isinstance(exc, domain.ConflictError):
        return _error_response(
            ERROR_CODES["CONFLICT"],
            str(exc),
            status.HTTP_409_CONFLICT,
        )

    if isinstance(exc, domain.OperationTimeoutError):
        return _error_response(
            ERROR_CODES["TIMEOUT"],
            str(exc),
            status.HTTP_504_GATEWAY_TIMEOUT,
        )

    if isinstance(exc, domain.ServiceUnavailableError):
        return _error_response(
            ERROR_CODES["SERVICE_UNAVAILABLE"],
            str(exc),
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if isinstance(exc, domain.DomainError):
        return _error_response(
            ERROR_CODES["BAD_REQUEST"],
            str(exc),
            status.HTTP_400_BAD_REQUEST,
        )

    # Log unexpected exceptions
    logger.exception(
        "Unhandled exception in API view: %s",
        context.get("view").__class__.__name__ if context.get("view") else "unknown",
        exc_info=exc,
    )
    return None  # Let DRF return 500


def _error_response(
    error_code: str,
    message: str,
    http_status: int,
    **extra
) -> Response:
    """Create a standardized error response."""
    body = {
        "detail": message,
        "error_code": error_code,
    }
    # Add extra context (gateway, operation, etc.)
    for key, value in extra.items():
        if value is not None:
            body[key] = value
    return Response(body, status=http_status)


def _format_drf_error(response: Response) -> Response:
    """Format DRF error response to match our standard."""
    data = response.data
    status_code = response.status_code

    # Map status codes to error codes
    error_code_map = {
        400: ERROR_CODES["VALIDATION_ERROR"],
        401: ERROR_CODES["UNAUTHORIZED"],
        403: ERROR_CODES["FORBIDDEN"],
        404: ERROR_CODES["NOT_FOUND"],
        405: ERROR_CODES["BAD_REQUEST"],
        409: ERROR_CODES["CONFLICT"],
        429: ERROR_CODES["BAD_REQUEST"],
        500: ERROR_CODES["SERVER_ERROR"],
        503: ERROR_CODES["SERVICE_UNAVAILABLE"],
    }
    error_code = error_code_map.get(status_code, ERROR_CODES["SERVER_ERROR"])

    # Extract message
    if isinstance(data, dict):
        if "detail" in data:
            message = str(data["detail"])
            # Keep existing structure for DRF errors
            response.data["error_code"] = error_code
            return response
        elif "non_field_errors" in data:
            message = data["non_field_errors"][0] if data["non_field_errors"] else "Validation error"
        else:
            # Field-level validation errors - keep as-is for form binding
            message = "One or more fields failed validation."
            response.data = {
                "detail": message,
                "error_code": error_code,
                "field_errors": data,
            }
            return response
    else:
        message = str(data) if data else "An error occurred"

    response.data = {
        "detail": message,
        "error_code": error_code,
    }
    return response
```

### 4. View-Level Exception Handling Guidelines

#### Replace Broad Catches with Specific Exceptions

**Before:**
```python
except Exception as e:
    logger.exception("Unexpected error creating provider")
    return Response({"error": f"Failed: {e}"}, status=500)
```

**After:**
```python
from django.db import IntegrityError
from config.domain_exceptions import GatewayNotReachableError, ConfigurationError

try:
    provider = serializer.save()
except IntegrityError:
    raise ConflictError("A provider with this name already exists.")
except GatewayNotReachableError:
    raise  # Let exception handler format response
except ConfigurationError:
    raise  # Let exception handler format response
# Remove generic Exception catch - let unexpected errors bubble up
```

#### When to Use Try/Except in Views

1. **Database operations** - Catch `IntegrityError` and convert to `ConflictError`
2. **External calls** - Let gateway exceptions bubble up to handler
3. **Type conversions** - Catch specific errors (e.g., `ValueError` for int parsing)

#### When NOT to Use Try/Except

1. Don't catch `Exception` unless logging and re-raising
2. Don't catch exceptions you can't handle meaningfully
3. Don't suppress errors - either handle or let bubble up

### 5. Logging Standards

```python
import logging

logger = logging.getLogger(__name__)

# Log levels by scenario:
# - DEBUG: Expected failures (e.g., validation errors, user mistakes)
# - INFO: Significant events (e.g., provider created, connection established)
# - WARNING: Degraded service (e.g., gateway unreachable, retry needed)
# - ERROR: Unexpected failures that should be investigated
# - EXCEPTION: Error with full stack trace for debugging

# Examples:
logger.debug("Validation failed for provider config: %s", errors)
logger.info("Created notification provider: %s", provider.name)
logger.warning("Z-Wave JS not reachable, will retry: %s", error)
logger.exception("Unexpected error in notification dispatch")
```

### 6. State Machine Exceptions

Update `state_machine/errors.py` to inherit from `DomainError`:

```python
# alarm/state_machine/errors.py (updated)
from config.domain_exceptions import DomainError


class StateMachineError(DomainError):
    """Base exception for alarm state machine errors."""
    pass


class TransitionError(StateMachineError):
    """Invalid state transition attempted."""
    pass


class CodeRequiredError(TransitionError):
    """Transition requires a code but none was provided."""
    pass


class InvalidCodeError(TransitionError):
    """Provided code is invalid."""
    pass
```

**HTTP Status Mappings:**
- `InvalidCodeError` → 401 (like wrong password)
- `CodeRequiredError` → 400 (validation - missing required input)
- `TransitionError` → 409 (conflict - current state doesn't allow this action)

### 7. HTTP Status Code Standards

| Status | Error Code | When to Use |
|--------|------------|-------------|
| 400 | `validation_error`, `bad_request` | Invalid input, missing required fields, `CodeRequiredError` |
| 401 | `unauthorized` | Authentication required/failed, `InvalidCodeError` |
| 403 | `forbidden` | Authenticated but not permitted |
| 404 | `not_found` | Resource doesn't exist |
| 409 | `conflict` | Duplicate, concurrent modification, `TransitionError` |
| 502 | `gateway_error` | External service returned error (operation failed) |
| 503 | `service_unavailable` | Gateway not configured, not reachable, client unavailable |
| 504 | `timeout` | External service timed out |
| 500 | `server_error` | Unexpected internal error |

---

## Implementation Plan

### Current Implementation Status (as of 2026-01-02)

This ADR is **implemented**.

### Phase 1: Exception Hierarchy (High Priority)

**Domain Exceptions:**
- [x] Add `GatewayError` base class to `config/domain_exceptions.py`
- [x] Add `ConfigurationError` and `OperationTimeoutError` to domain exceptions

**Gateway Exceptions (single inheritance):**
- [x] Update `alarm/gateways/home_assistant.py` to inherit from `GatewayError`
- [x] Update `integrations_zwavejs/manager.py` to inherit from `GatewayError`
- [x] Update `transports_mqtt/manager.py` to inherit from `GatewayError`
- [x] Update `integrations_home_assistant/impl.py`: `HomeAssistantAvailabilityError` → `GatewayError`
- [x] Add `operation`/`error` metadata where applicable (MQTT publish/subscribe)

**State Machine & Use Case Exceptions:**
- [x] Update `alarm/state_machine/errors.py` to inherit from `DomainError`
- [x] Update `alarm/rules_engine.py`: `RuleEngineError` → `DomainError`

**Exception Handler:**
- [x] Update `config/exception_handler.py` with duck-typed gateway handling and WARNING logging
- [x] Normalize DRF errors to include `error_code` and a stable `detail`
- [x] Map state-machine code/transition errors to stable HTTP codes (`401`/`400`/`409`)

### Phase 2: View Cleanup (High Priority) - 21 occurrences across 9 files

- [x] `notifications/views.py` (3): Replace broad catches and normalize errors
- [x] `integrations_zwavejs/views.py` (7): Remove redundant exception handling (delegate to global handler)
- [x] `integrations_home_assistant/views.py` (3): Remove generic handlers (wrap unexpected exceptions into domain errors)
- [x] `control_panels/views.py` (2): Replace generic handlers, add logging, and raise domain errors
- [x] `integrations_zigbee2mqtt/views.py` (2): Replace generic handlers with domain errors
- [x] `integrations_frigate/views.py` (1): Add logging for conversion errors
- [x] `transports_mqtt/views.py` (1): Remove redundant exception handling
- [x] `locks/views/sync.py` (1): Delegate gateway exceptions to global handler
- [x] `alarm/views/entities.py` (1): Delegate gateway exceptions to global handler

**Phase 2 acceptance criteria:**
- Views do not catch-and-reformat gateway/domain errors that the global handler already covers.
- Any remaining catches are narrow and add meaningful context (logging, alternate flow), not just response formatting.
- No API view returns `{"error": ...}`.

### Phase 3: Use Case Exceptions (Medium Priority)

- [x] Update `accounts/use_cases/code_validation.py`: `CodeValidationError` → `ValidationError`
- [x] Update `locks/use_cases/code_validation.py`: `CodeValidationError` → `ValidationError`
- [x] Update `accounts/use_cases/onboarding.py`: `OnboardingError` → `DomainError`
- [x] Update `alarm/use_cases/alarm_actions.py`: `AlarmActionError` → `DomainError`
- [x] Update views that catch these exceptions (now handled by global handler)

### Phase 4: Error Response Cleanup (Prepares for ADR 0025)

- [x] Update all views using `{"error": "..."}` to use `{"detail": "..."}`
- [x] Ensure all error responses include `error_code`
- [x] Add `gateway` field to gateway error responses (via global handler)
- [x] Document error response structure for frontend team
- [x] Ensure frontend error utilities surface `error_code` (and optional `gateway`/`operation`) when present

> **Note:** This phase establishes the error response structure. ADR 0025 will later wrap ALL responses (success and error) in a consistent envelope.

### Phase 5: Testing

- [x] Add unit tests for exception handler mappings
- [x] Add integration tests for gateway exception scenarios
- [x] Test frontend error display with new error codes
- [x] Update any existing tests expecting the old `TransitionError` mapping (`400` → `409`)

---

## Migration Guide

### For New Code

1. Raise domain exceptions from use cases and services
2. Let views delegate exception handling to the global handler
3. Only catch exceptions you can meaningfully handle

### For Existing Code

1. Replace `RuntimeError` base classes with `DomainError`
2. Replace `except Exception` with specific exception types
3. Remove redundant try/except that duplicate handler logic
4. Add logging where currently missing

### Backwards Compatibility

- Existing exception classes remain (with updated inheritance)
- Views continue to work during incremental migration
- Frontend should handle both old and new response formats during transition

---

## Consequences

### Positive

- Consistent exception handling across all Django apps
- Gateway exceptions automatically handled - less boilerplate
- Clear mapping from exception type to HTTP status
- Better debugging with structured error responses
- Reduced code duplication in views

### Negative

- Migration effort for existing code
- Need to update tests that expect old exception types
- Duck-typing in exception handler requires consistent exception message patterns

### Neutral

- Exception handler becomes more complex (but views become simpler)
- Need to maintain exception hierarchy documentation

---

## Related ADRs

- [ADR 0025: Standardized API Response Format](0025-standardized-api-response-format.md) - **Implement AFTER this ADR**; builds on error response structure
- [ADR 0005: Thin Views and Use-Case Layer](0005-thin-views-and-use-cases.md) - Where to raise exceptions
- [ADR 0007: Home Assistant Gateway Abstraction](0007-home-assistant-gateway-and-allowlist.md) - Gateway pattern
- [ADR 0012: Z-Wave JS Gateway + Connection Manager](0012-zwave-js-gateway-and-connection-manager.md) - Z-Wave gateway
- [ADR 0014: Alarm Core + Integrations Decomposition](0014-alarm-core-and-integrations-decomposition.md) - App structure

---

## Appendix: Files Requiring Updates

### Phase 1: Exception Hierarchy

| File | Changes Needed |
|------|----------------|
| `config/domain_exceptions.py` | Add `GatewayError`, `ConfigurationError`, `OperationTimeoutError` |
| `config/exception_handler.py` | Duck-typed gateway handling, state machine exceptions, WARNING logs |
| `alarm/state_machine/errors.py` | Inherit from `DomainError` via `StateMachineError` |
| `alarm/rules_engine.py` | `RuleEngineError` → inherit from `DomainError` |
| `alarm/gateways/home_assistant.py` | Single inheritance from `GatewayError` |
| `integrations_zwavejs/manager.py` | Single inheritance, add `gateway_name` class attribute |
| `transports_mqtt/manager.py` | Single inheritance, add `gateway_name` class attribute |
| `integrations_home_assistant/impl.py` | `HomeAssistantAvailabilityError` → `GatewayError` |

### Phase 2: View Cleanup (21 occurrences)

| File | Occurrences | Changes Needed |
|------|-------------|----------------|
| `notifications/views.py` | 3 | Replace broad catches, fix response format |
| `integrations_zwavejs/views.py` | 7 | Remove redundant exception handling |
| `integrations_home_assistant/views.py` | 3 | Replace generic handlers |
| `control_panels/views.py` | 2 | Replace broad catches, add logging |
| `integrations_zigbee2mqtt/views.py` | 2 | Replace generic handlers |
| `integrations_frigate/views.py` | 1 | Add logging for conversion errors |
| `transports_mqtt/views.py` | 1 | Remove redundant handling |
| `locks/views/sync.py` | 1 | Replace generic handler |
| `alarm/views/entities.py` | 1 | Replace generic handler |

### Phase 3: Use Case Exceptions

| File | Changes Needed |
|------|----------------|
| `accounts/use_cases/code_validation.py` | `CodeValidationError` → `DomainError` |
| `locks/use_cases/code_validation.py` | `CodeValidationError` → `DomainError` |
| `accounts/use_cases/onboarding.py` | `OnboardingError` → `DomainError` |
| `alarm/use_cases/alarm_actions.py` | `AlarmActionError` → `DomainError` |

### Lower Priority (Review Case-by-Case)

These files have broad exception catches that may be intentional for resilience:

| File | Occurrences | Notes |
|------|-------------|-------|
| `integrations_zigbee2mqtt/runtime.py` | 20+ | Event loop resilience - review individually |
| `integrations_frigate/runtime.py` | 12+ | Event loop resilience - review individually |
| `control_panels/zwave_ring_keypad_v2.py` | 12+ | Hardware resilience - likely keep most |
| `integrations_zwavejs/manager.py` | 15+ | Connection handling - review individually |
| `transports_mqtt/manager.py` | 12+ | MQTT operations - review individually |

### Files with Correct Patterns (Reference)

| File | Good Pattern |
|------|--------------|
| `accounts/use_cases/auth.py` | Uses `UnauthorizedError` properly |
| `notifications/handlers/pushbullet.py` | Specific exception catches with error codes |
| `notifications/handlers/webhook.py` | Specific exception catches with error codes |
