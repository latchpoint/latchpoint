# ADR 0025: Standardized API Response Format

## Status
Implemented

## Context
The current API responses are inconsistent:
- Some endpoints return raw data, others wrap in `{ data: ... }`
- Error responses vary: `{ detail: ... }`, `{ message: ... }`, DRF field errors, etc.
- The frontend has multiple layers of error parsing (`lib/errors.ts`, `types/errors.ts`, `api.ts`)
- Form validation errors require special handling to extract field-level messages

We need a consistent envelope for all API responses so the frontend can:
1. Always know where to find the payload
2. Always know where to find errors (including field-level validation)
3. Display errors uniformly in toasts, forms, and error boundaries

## Decision
All API endpoints will return responses in this envelope format:

### Compatibility / Rollout
This is a breaking change for any client that expects “raw” payloads or legacy error shapes.

To support incremental rollout:
- Enable the backend envelope renderer behind a settings flag (`API_RESPONSE_ENVELOPE_ENABLED`) for safe rollback.
- Update the frontend API client to support both legacy and enveloped formats during the migration window (now implemented).
- Audit views that manually construct error `Response(..., status>=400)` objects (the exception handler can’t wrap errors that never become exceptions).

### Success Response
```json
{
  "data": <payload>,
  "meta": {
    "page": 1,
    "page_size": 20,
    "total": 100,
    "has_next": true,
    "has_previous": false
  }
}
```
- `data`: Required. The response payload (object, array, or null for 204-like success).
- `meta`: Optional. Pagination or other metadata when applicable.

### Error Response
```json
{
  "error": {
    "status": "validation_error",
    "message": "One or more fields failed validation.",
    "details": {
      "code": ["This field is required."],
      "email": ["Enter a valid email address."]
    }
  }
}
```
- `error.status`: Required. A machine-readable error code (e.g., `validation_error`, `not_found`, `unauthorized`, `forbidden`, `conflict`, `server_error`).
- `error.message`: Required. A human-readable summary.
- `error.details`: Optional. Field-level errors as `{ field: string[] }` for forms.

### Status Codes
| HTTP Status | `error.status` value | When to use |
|-------------|---------------------|-------------|
| 400 | `validation_error` | Field-level validation failures (serializer errors) |
| 400 | `bad_request` | Non-field validation (malformed request, missing config) |
| 401 | `unauthorized` | Missing or invalid authentication |
| 403 | `forbidden` | Authenticated but lacks permission |
| 404 | `not_found` | Resource does not exist |
| 405 | `method_not_allowed` | HTTP method not supported for endpoint |
| 409 | `conflict` | State conflict (duplicate, concurrent modification) |
| 422 | `validation_error` | Semantic validation failure (valid syntax, invalid meaning) |
| 429 | `rate_limited` | Too many requests |
| 500 | `server_error` | Unexpected server error |
| 503 | `service_unavailable` | Dependency unavailable (Home Assistant, external API) |

### TypeScript Types (Frontend)
```typescript
// frontend/src/types/apiEnvelope.ts

// Pagination metadata (camelCase - transformed by API client from snake_case)
interface ApiMeta {
  page?: number
  pageSize?: number
  total?: number
  totalPages?: number
  hasNext?: boolean
  hasPrevious?: boolean
  timestamp?: string  // ISO 8601 format when included
}

interface ApiSuccessResponse<T> {
  data: T
  meta?: ApiMeta
}

type ApiErrorStatus =
  | 'validation_error'
  | 'bad_request'
  | 'unauthorized'
  | 'forbidden'
  | 'not_found'
  | 'method_not_allowed'
  | 'conflict'
  | 'rate_limited'
  | 'server_error'
  | 'service_unavailable'

interface ApiErrorBody {
  status: ApiErrorStatus
  message: string
  // Field errors use dot notation for nested fields: "address.city", "items.0.name"
  details?: Record<string, string[]>
}

interface ApiErrorResponse {
  error: ApiErrorBody
}

type ApiResponse<T> = ApiSuccessResponse<T> | ApiErrorResponse

// Type guard
function isApiError<T>(response: ApiResponse<T>): response is ApiErrorResponse {
  return 'error' in response
}
```

### Edge Cases

#### Empty Results
- Empty collections return `{ "data": [] }`, never `{ "data": null }`
- Single missing resources return HTTP 404, not `{ "data": null }`
- Successful deletions return HTTP 204 with no body

#### Nested Validation Errors
Field errors for nested objects use dot notation:
```json
{
  "error": {
    "status": "validation_error",
    "message": "One or more fields failed validation.",
    "details": {
      "address.city": ["This field is required."],
      "items.0.quantity": ["Ensure this value is greater than 0."]
    }
  }
}
```

#### Non-JSON Responses
File downloads and streaming responses bypass the envelope format (they should not be returned through the JSON renderer path).

---

## Detailed Implementation Plan

### Phase 1: Backend Infrastructure

#### 1.0 Add an “enable envelope” feature flag
**Goal:** Allow safe deployment and rollback without code churn.

**Proposed setting:** `API_RESPONSE_ENVELOPE_ENABLED` (env-backed, defaults to `False` until the migration is complete).

**Behavior:**
- When disabled: current behavior (raw success payloads, current error handling).
- When enabled: JSON responses use `EnvelopeJSONRenderer` and the exception handler returns the standardized error envelope.

#### 1.1 Create Envelope Renderer
**File:** `backend/config/renderers.py`

```python
from rest_framework.renderers import JSONRenderer

# Keys that indicate an already-enveloped *success* response
ENVELOPE_KEYS = frozenset({"data", "meta"})


class EnvelopeJSONRenderer(JSONRenderer):
    """
    Wraps all successful responses in { "data": ... } envelope.
    Error responses are handled by the exception handler.
    """

    def render(self, data, accepted_media_type=None, renderer_context=None):
        response = renderer_context.get("response") if renderer_context else None

        # Don't wrap error responses (handled by exception_handler)
        if response and response.status_code >= 400:
            return super().render(data, accepted_media_type, renderer_context)

        # Don't double-wrap if already enveloped
        if self._is_already_enveloped(data):
            return super().render(data, accepted_media_type, renderer_context)

        # Wrap in envelope
        enveloped = {"data": data}
        return super().render(enveloped, accepted_media_type, renderer_context)

    def _is_already_enveloped(self, data) -> bool:
        """Check if data is already in envelope format."""
        if not isinstance(data, dict):
            return False
        if "data" not in data:
            return False
        # Consider it enveloped if it only contains envelope keys
        return set(data.keys()).issubset(ENVELOPE_KEYS)
```

**Notes / gotchas to account for in implementation:**
- DRF will still call the renderer for manually-constructed error `Response({...}, status=400)`; the renderer skips wrapping `>= 400`, but the response body still needs to already match the standardized error envelope (or be converted into an exception upstream).
- If we want “extra fields” in successful responses, they should go under `meta` (otherwise they’ll be double-wrapped).

#### 1.2 Update Exception Handler
**File:** `backend/config/exception_handler.py`

```python
import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework import exceptions as drf_exceptions

# Import domain exceptions at module level for reliability
from alarm.state_machine.errors import TransitionError
from alarm.gateways.home_assistant import HomeAssistantNotConfigured, HomeAssistantNotReachable
from config import domain_exceptions as domain

logger = logging.getLogger(__name__)

# Map HTTP status codes to error.status values
STATUS_MAP = {
    # NOTE: 400 is ambiguous in DRF; prefer mapping by exception class where possible.
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    503: "service_unavailable",
}


def custom_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)

    if response is not None:
        return _wrap_drf_error(exc, response)

    # Handle domain exceptions
    if isinstance(exc, domain.ValidationError):
        return _error_response("validation_error", str(exc), status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, domain.UnauthorizedError):
        return _error_response("unauthorized", str(exc), status.HTTP_401_UNAUTHORIZED)
    if isinstance(exc, domain.ForbiddenError):
        return _error_response("forbidden", str(exc), status.HTTP_403_FORBIDDEN)
    if isinstance(exc, domain.NotFoundError):
        return _error_response("not_found", str(exc), status.HTTP_404_NOT_FOUND)
    if isinstance(exc, domain.ConflictError):
        return _error_response("conflict", str(exc), status.HTTP_409_CONFLICT)
    if isinstance(exc, HomeAssistantNotConfigured):
        return _error_response("bad_request", str(exc) or "Home Assistant is not configured.", status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, HomeAssistantNotReachable):
        return _error_response("service_unavailable", "Home Assistant is not reachable.", status.HTTP_503_SERVICE_UNAVAILABLE)
    if isinstance(exc, TransitionError):
        return _error_response("validation_error", str(exc), status.HTTP_400_BAD_REQUEST)

    # Log unhandled exceptions for debugging
    logger.exception("Unhandled exception in API view", exc_info=exc)
    return None


def _wrap_drf_error(exc: Exception, response: Response) -> Response:
    """Convert DRF error response to envelope format."""
    data = response.data
    status_code = response.status_code

    # Prefer exception-type mapping for common DRF failures.
    if isinstance(exc, drf_exceptions.ValidationError):
        error_status = "validation_error"
    elif isinstance(exc, (drf_exceptions.ParseError, drf_exceptions.UnsupportedMediaType)):
        error_status = "bad_request"
    elif isinstance(exc, (drf_exceptions.NotAuthenticated, drf_exceptions.AuthenticationFailed)):
        error_status = "unauthorized"
    elif isinstance(exc, drf_exceptions.PermissionDenied):
        error_status = "forbidden"
    elif isinstance(exc, drf_exceptions.NotFound):
        error_status = "not_found"
    elif isinstance(exc, drf_exceptions.MethodNotAllowed):
        error_status = "method_not_allowed"
    elif isinstance(exc, drf_exceptions.Throttled):
        error_status = "rate_limited"
    elif status_code == 400:
        error_status = "bad_request"
    else:
        error_status = STATUS_MAP.get(status_code, "server_error")

    # Extract message and details from DRF response
    if isinstance(data, dict):
        if "detail" in data:
            message = str(data["detail"])
            details = None
        elif "non_field_errors" in data:
            message = data["non_field_errors"][0] if data["non_field_errors"] else "Validation error"
            details = {k: v for k, v in data.items() if k != "non_field_errors"}
        else:
            # Field-level validation errors
            message = "One or more fields failed validation."
            details = data
    elif isinstance(data, list):
        message = data[0] if data else "An error occurred"
        details = None
    else:
        message = str(data) if data else "An error occurred"
        details = None

    # Contract: `error.details` is `Record<string, string[]>` using dot notation for nested fields.
    # Implementation should:
    # - normalize DRF ErrorDetail / lazy strings to `str`
    # - flatten nested serializer errors into dot paths (e.g. items.0.name)
    if details is not None:
        details = flatten_error_details(details)  # -> dict[str, list[str]]

    error_body = {
        "error": {
            "status": error_status,
            "message": message,
        }
    }
    if details:
        error_body["error"]["details"] = details

    response.data = error_body
    return response


def flatten_error_details(details) -> dict[str, list[str]]:
    """
    Convert DRF serializer error shapes into the contract format:
      - values are always list[str]
      - nested dicts/lists are flattened into dot paths (e.g. items.0.name)
    """
    # Pseudocode (implementation can live in a helper module):
    # - recursively walk dict/list
    # - accumulate a dot-path prefix
    # - coerce DRF ErrorDetail / lazy strings to str
    # - if leaf is a string/ErrorDetail: wrap in [str(...)]
    # - if leaf is list: map str(...) over entries
    ...


def _error_response(error_status: str, message: str, http_status: int) -> Response:
    """Create a new error response in envelope format."""
    return Response(
        {
            "error": {
                "status": error_status,
                "message": message,
            }
        },
        status=http_status,
    )
```

#### 1.3 Create Envelope Pagination Class
**File:** `backend/config/pagination.py`

```python
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class EnvelopePagination(PageNumberPagination):
    """
    Pagination that returns { data: [...], meta: { page, page_size, total, ... } }

    Meta fields use snake_case (Python convention). The frontend API client
    transforms these to camelCase automatically.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 200

    def get_paginated_response(self, data):
        page_size = self.get_page_size(self.request)
        if page_size is None:
            page_size = self.page_size

        return Response({
            "data": data,
            "meta": {
                "page": self.page.number,
                "page_size": page_size,
                "total": self.page.paginator.count,
                "total_pages": self.page.paginator.num_pages,
                "has_next": self.page.has_next(),
                "has_previous": self.page.has_previous(),
            }
        })
```

#### 1.4 Update DRF Settings
**File:** `backend/config/settings.py`

```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounts.authentication.BearerTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "config.renderers.EnvelopeJSONRenderer",  # <-- Enable only when feature flag is on
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PAGINATION_CLASS": "config.pagination.EnvelopePagination",  # <-- Added
    "PAGE_SIZE": 20,  # <-- Added
    "EXCEPTION_HANDLER": "config.exception_handler.custom_exception_handler",
}
```

**Recommendation:** avoid globally enabling pagination until we’ve audited all list endpoints. Many endpoints are hand-rolled `APIView`s that return full lists (and the frontend may rely on that). Consider:
- Keep `DEFAULT_PAGINATION_CLASS` unset initially.
- Apply `EnvelopePagination` only to endpoints that are explicitly paginated today (like events), then expand.

---

### Phase 2: Migrate Existing Views

#### 2.1 Views Returning Raw Data (No Changes Needed)
These views return serializer data directly. The `EnvelopeJSONRenderer` will automatically wrap them.

| View File | Endpoints |
|-----------|-----------|
| `alarm/views/sensors.py` | `GET /api/alarm/sensors/`, `GET/PATCH /api/alarm/sensors/:id/` |
| `alarm/views/alarm_state.py` | `GET /api/alarm/state/` |
| `alarm/views/rules.py` | `GET/POST /api/alarm/rules/` |
| `accounts/views/codes.py` | `GET/POST /api/codes/`, `GET/PATCH /api/codes/:id/` |
| `accounts/views/users.py` | `GET /api/users/`, `GET /api/users/me/` |
| (and others) | ... |

**No code changes required** - renderer handles wrapping.

#### 2.2 Views Already Returning Envelope (Update to Match Schema)
These views already return `{ data: [...], ... }`. Update to use `meta` for pagination fields.

**File:** `backend/alarm/views/events.py`

```python
# BEFORE:
return Response({
    "data": AlarmEventSerializer(page_obj.object_list, many=True).data,
    "total": paginator.count,
    "page": page_obj.number,
    "page_size": page_size,
    "total_pages": paginator.num_pages,
    "has_next": page_obj.has_next(),
    "has_previous": page_obj.has_previous(),
    "timestamp": timezone.now(),
})

# AFTER:
return Response({
    "data": AlarmEventSerializer(page_obj.object_list, many=True).data,
    "meta": {
        "page": page_obj.number,
        "page_size": page_size,
        "total": paginator.count,
        "total_pages": paginator.num_pages,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
        "timestamp": timezone.now().isoformat(),
    }
})
```

#### 2.3 Audit manual error responses
Some views may return an error `Response` directly (without raising an exception). Those bypass the exception handler and must be updated to:
- raise a domain/use-case exception (preferred), or
- return the standardized `{ "error": ... }` envelope directly (via a helper), or
- temporarily opt out of enveloping (only as a short-lived migration escape hatch).

#### 2.4 Views Returning 204 No Content
Views that return `Response(status=status.HTTP_204_NO_CONTENT)` are fine - no body means no envelope needed.

---

### Phase 3: Frontend Infrastructure

#### 3.1 Create New Types
**File:** `frontend/src/types/apiEnvelope.ts`

```typescript
// Pagination metadata (camelCase - transformed by API client from snake_case)
export interface ApiMeta {
  page?: number
  pageSize?: number
  total?: number
  totalPages?: number
  hasNext?: boolean
  hasPrevious?: boolean
  timestamp?: string  // ISO 8601 format when included
}

// Success response envelope
export interface ApiSuccessResponse<T> {
  data: T
  meta?: ApiMeta
}

// Error status codes (machine-readable)
export type ApiErrorStatus =
  | 'validation_error'
  | 'bad_request'
  | 'unauthorized'
  | 'forbidden'
  | 'not_found'
  | 'method_not_allowed'
  | 'conflict'
  | 'rate_limited'
  | 'server_error'
  | 'service_unavailable'

// Error body structure
export interface ApiErrorBody {
  status: ApiErrorStatus
  message: string
  // Field errors use dot notation for nested fields: "address.city", "items.0.name"
  details?: Record<string, string[]>
}

// Error response envelope
export interface ApiErrorResponse {
  error: ApiErrorBody
}

// Union type for all responses
export type ApiResponse<T> = ApiSuccessResponse<T> | ApiErrorResponse

// Type guards
export function isApiErrorResponse(response: unknown): response is ApiErrorResponse {
  return (
    typeof response === 'object' &&
    response !== null &&
    'error' in response &&
    typeof (response as ApiErrorResponse).error === 'object'
  )
}

export function isApiSuccessResponse<T>(response: unknown): response is ApiSuccessResponse<T> {
  return (
    typeof response === 'object' &&
    response !== null &&
    'data' in response &&
    !('error' in response)
  )
}

// Helper to extract field errors for forms (handles dot notation for nested fields)
export function getFieldErrors(error: ApiErrorBody): Record<string, string> {
  if (!error.details) return {}
  const result: Record<string, string> = {}
  for (const [field, messages] of Object.entries(error.details)) {
    result[field] = messages[0] || 'Invalid value'
  }
  return result
}
```

#### 3.2 Update API Client
**File:** `frontend/src/services/api.ts`

```typescript
import { isApiErrorResponse, type ApiErrorBody, type ApiMeta } from '@/types/apiEnvelope'

// New error class that carries structured error info
export class ApiError extends Error {
  public readonly status: string
  public readonly details?: Record<string, string[]>
  public readonly httpStatus: number

  constructor(body: ApiErrorBody, httpStatus: number) {
    super(body.message)
    this.name = 'ApiError'
    this.status = body.status
    this.details = body.details
    this.httpStatus = httpStatus
  }
}

class ApiClient {
  // ... existing code ...

  private async handleResponse<T>(response: Response): Promise<T> {
    const parsed = await response.json().catch((err) => {
      // Log JSON parse failures for debugging (non-JSON responses, malformed JSON)
      console.warn(`Failed to parse JSON response from ${response.url}:`, err)
      return null
    })

    if (!response.ok) {
      // New: Check for envelope error format
      if (isApiErrorResponse(parsed)) {
        throw new ApiError(parsed.error, response.status)
      }

      // Fallback for non-envelope errors (during migration)
      const message = parsed?.detail || parsed?.message || response.statusText || 'An error occurred'
      throw new ApiError(
        { status: 'server_error', message },
        response.status
      )
    }

    if (response.status === 204) {
      return undefined as T
    }

    // Handle null parsed (empty body or parse failure)
    if (parsed === null) {
      return undefined as T
    }

    const transformed = transformKeysDeep(parsed, toCamelCaseKey)

    // New: Unwrap envelope if present
    if (
      typeof transformed === 'object' &&
      transformed !== null &&
      'data' in transformed
    ) {
      return (transformed as { data: T }).data
    }

    // Fallback for non-envelope responses (during migration)
    return transformed as T
  }

  // New: Method that returns data + meta for paginated responses
  async getWithMeta<T>(
    endpoint: string,
    params?: Record<string, string | number | boolean | undefined>
  ): Promise<{ data: T; meta?: ApiMeta }> {
    const response = await this.rawRequest('GET', endpoint, { params })
    const parsed = await response.json().catch((err) => {
      console.warn(`Failed to parse paginated JSON response from ${endpoint}:`, err)
      return { data: [] as T, meta: {} }
    })
    const transformed = transformKeysDeep(parsed, toCamelCaseKey) as { data: T; meta?: ApiMeta }
    return transformed
  }
}
```

#### 3.3 Update Error Handling
**File:** `frontend/src/lib/errors.ts`

```typescript
import { ApiError } from '@/services/api'

export function categorizeError(error: unknown): AppError {
  // New: Handle ApiError class
  if (error instanceof ApiError) {
    const categoryMap: Record<string, ErrorCategory> = {
      validation_error: 'validation',
      bad_request: 'validation',
      unauthorized: 'auth',
      forbidden: 'auth',
      not_found: 'not_found',
      method_not_allowed: 'validation',
      conflict: 'validation',
      rate_limited: 'server',
      server_error: 'server',
      service_unavailable: 'server',
    }

    return {
      category: categoryMap[error.status] || 'unknown',
      message: error.message,
      code: error.httpStatus.toString(),
      details: error.details,
      recoverable: error.status !== 'unauthorized' && error.status !== 'forbidden',
      timestamp: Date.now(),
      originalError: error,
    }
  }

  // ... existing categorization logic for legacy errors ...
}
```

#### 3.4 Create Form Error Hook
**File:** `frontend/src/hooks/useFormErrors.ts`

```typescript
import { useCallback, useState } from 'react'
import { ApiError } from '@/services/api'
import { getFieldErrors } from '@/types/apiEnvelope'

interface UseFormErrorsResult {
  /** Field-level errors: { fieldName: "error message" } */
  fieldErrors: Record<string, string>
  /** General error message (non-field errors) */
  generalError: string | null
  /** Set errors from an API error */
  setFromError: (error: unknown) => void
  /** Clear all errors */
  clearErrors: () => void
  /** Clear a specific field error */
  clearFieldError: (field: string) => void
}

export function useFormErrors(): UseFormErrorsResult {
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [generalError, setGeneralError] = useState<string | null>(null)

  const setFromError = useCallback((error: unknown) => {
    if (error instanceof ApiError) {
      if (error.details && Object.keys(error.details).length > 0) {
        setFieldErrors(getFieldErrors(error))
        setGeneralError(null)
      } else {
        setFieldErrors({})
        setGeneralError(error.message)
      }
    } else if (error instanceof Error) {
      setFieldErrors({})
      setGeneralError(error.message)
    } else {
      setFieldErrors({})
      setGeneralError('An unexpected error occurred')
    }
  }, [])

  const clearErrors = useCallback(() => {
    setFieldErrors({})
    setGeneralError(null)
  }, [])

  const clearFieldError = useCallback((field: string) => {
    setFieldErrors((prev) => {
      const next = { ...prev }
      delete next[field]
      return next
    })
  }, [])

  return { fieldErrors, generalError, setFromError, clearErrors, clearFieldError }
}
```

#### 3.5 Example Form Usage

```tsx
function CreateCodeForm() {
  const { fieldErrors, generalError, setFromError, clearFieldError } = useFormErrors()
  const createMutation = useCreateCodeMutation(userId)

  const handleSubmit = async (formData: CreateCodeRequest) => {
    try {
      await createMutation.mutateAsync(formData)
      // Success handling
    } catch (error) {
      setFromError(error)
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      {generalError && <Alert variant="error">{generalError}</Alert>}

      <Input
        name="code"
        error={fieldErrors.code}
        onChange={() => clearFieldError('code')}
      />

      <Input
        name="label"
        error={fieldErrors.label}
        onChange={() => clearFieldError('label')}
      />

      <Button type="submit">Create</Button>
    </form>
  )
}
```

---

### Phase 4: Migration Strategy

#### 4.1 Migration Order
Migrate in this order to minimize disruption:

1. **Infrastructure first** (can be deployed without breaking existing code):
   - Add feature flag in settings (default off)
   - Create `config/renderers.py`
   - Update `config/exception_handler.py` (distinguish 400 validation vs bad request; flatten `details`)
   - Create `config/pagination.py` (optional at first; see pagination note)
   - Update `config/settings.py` to enable renderer only when flag is on

2. **Frontend compatibility layer**:
   - Update `api.ts` to handle both old and new formats
   - Add new types alongside existing types

3. **Migrate views incrementally** (by Django app):
   - `alarm/` views
   - `accounts/` views
   - `locks/` views
   - Integration views (`integrations_*/views.py`, `transports_mqtt/views.py`)

4. **Update frontend hooks** (as views are migrated):
   - Update query hooks to use new types
   - Update mutation error handling

5. **Cleanup**:
   - Remove legacy error handling code
   - Remove compatibility shims

#### 4.2 Testing Strategy

**Backend Tests:**
- Add tests for `EnvelopeJSONRenderer` wrapping behavior
- Add tests for exception handler envelope format
- Update existing API tests to expect envelope format

**Frontend Tests:**
- Add tests for `ApiError` class
- Add tests for `useFormErrors` hook
- Add tests for type guards

#### 4.3 Rollback Strategy

The migration is designed for safe, incremental rollout:

1. **Backend rollback is simple**: Toggle `API_RESPONSE_ENVELOPE_ENABLED` off (or revert `DEFAULT_RENDERER_CLASSES` to `JSONRenderer`) to restore legacy success payloads while keeping existing error handling.

2. **Frontend handles both formats**: The API client detects envelope format and falls back gracefully. No frontend changes needed for rollback.

3. **Per-view override**: Individual views can opt out by setting `renderer_classes`:
   ```python
   class LegacyView(APIView):
       renderer_classes = [JSONRenderer]  # Skip envelope
   ```

4. **Monitoring**: Add lightweight logging/metrics for envelope adoption and legacy fallbacks in the frontend API client.

#### 4.4 Example Tests

**Backend: Renderer Tests**
```python
# backend/config/tests/test_renderers.py
from django.test import TestCase
from rest_framework.test import APIRequestFactory
from config.renderers import EnvelopeJSONRenderer


class EnvelopeJSONRendererTests(TestCase):
    def setUp(self):
        self.renderer = EnvelopeJSONRenderer()
        self.factory = APIRequestFactory()

    def test_wraps_dict_in_envelope(self):
        """Raw dict responses are wrapped in { data: ... }"""
        data = {"id": 1, "name": "Test"}
        result = self.renderer.render(data, renderer_context={"response": MockResponse(200)})
        parsed = json.loads(result)
        self.assertEqual(parsed, {"data": {"id": 1, "name": "Test"}})

    def test_wraps_list_in_envelope(self):
        """Raw list responses are wrapped in { data: [...] }"""
        data = [{"id": 1}, {"id": 2}]
        result = self.renderer.render(data, renderer_context={"response": MockResponse(200)})
        parsed = json.loads(result)
        self.assertEqual(parsed, {"data": [{"id": 1}, {"id": 2}]})

    def test_does_not_double_wrap(self):
        """Already-enveloped responses are not wrapped again"""
        data = {"data": [1, 2, 3], "meta": {"page": 1}}
        result = self.renderer.render(data, renderer_context={"response": MockResponse(200)})
        parsed = json.loads(result)
        self.assertEqual(parsed, {"data": [1, 2, 3], "meta": {"page": 1}})

    def test_does_not_wrap_error_responses(self):
        """Error responses (4xx/5xx) are passed through unchanged"""
        data = {"error": {"status": "not_found", "message": "Not found"}}
        result = self.renderer.render(data, renderer_context={"response": MockResponse(404)})
        parsed = json.loads(result)
        self.assertIn("error", parsed)
        self.assertNotIn("data", parsed)


class MockResponse:
    def __init__(self, status_code):
        self.status_code = status_code

    def get(self, key, default=""):
        return default
```

**Backend: Exception Handler Tests**
```python
# backend/config/tests/test_exception_handler.py
from django.test import TestCase
from rest_framework.test import APIClient


class ExceptionHandlerTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_validation_error_format(self):
        """Field validation errors return proper envelope format"""
        response = self.client.post("/api/codes/", {})  # Missing required fields
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertIn("error", body)
        self.assertEqual(body["error"]["status"], "validation_error")
        self.assertIn("details", body["error"])

    def test_not_found_format(self):
        """404 errors return proper envelope format"""
        response = self.client.get("/api/codes/99999/")
        self.assertEqual(response.status_code, 404)
        body = response.json()
        self.assertEqual(body["error"]["status"], "not_found")

    def test_unauthorized_format(self):
        """Unauthenticated requests return proper envelope format"""
        self.client.logout()
        response = self.client.get("/api/users/me/")
        self.assertEqual(response.status_code, 401)
        body = response.json()
        self.assertEqual(body["error"]["status"], "unauthorized")
```

**Frontend: ApiError Tests**
```typescript
// frontend/src/services/__tests__/api.test.ts
import { ApiError } from '../api'

describe('ApiError', () => {
  it('stores error details from API response', () => {
    const error = new ApiError(
      {
        status: 'validation_error',
        message: 'Validation failed',
        details: { email: ['Invalid email format'] },
      },
      400
    )

    expect(error.status).toBe('validation_error')
    expect(error.message).toBe('Validation failed')
    expect(error.details?.email).toEqual(['Invalid email format'])
    expect(error.httpStatus).toBe(400)
  })

  it('is an instance of Error', () => {
    const error = new ApiError({ status: 'not_found', message: 'Not found' }, 404)
    expect(error).toBeInstanceOf(Error)
  })
})
```

**Frontend: useFormErrors Tests**
```typescript
// frontend/src/hooks/__tests__/useFormErrors.test.ts
import { renderHook, act } from '@testing-library/react'
import { useFormErrors } from '../useFormErrors'
import { ApiError } from '@/services/api'

describe('useFormErrors', () => {
  it('extracts field errors from ApiError', () => {
    const { result } = renderHook(() => useFormErrors())

    act(() => {
      result.current.setFromError(
        new ApiError(
          {
            status: 'validation_error',
            message: 'Validation failed',
            details: {
              email: ['Invalid email', 'Already taken'],
              code: ['Required'],
            },
          },
          400
        )
      )
    })

    expect(result.current.fieldErrors).toEqual({
      email: 'Invalid email', // Takes first error
      code: 'Required',
    })
    expect(result.current.generalError).toBeNull()
  })

  it('sets general error when no field details', () => {
    const { result } = renderHook(() => useFormErrors())

    act(() => {
      result.current.setFromError(
        new ApiError({ status: 'server_error', message: 'Internal error' }, 500)
      )
    })

    expect(result.current.fieldErrors).toEqual({})
    expect(result.current.generalError).toBe('Internal error')
  })

  it('clears individual field errors', () => {
    const { result } = renderHook(() => useFormErrors())

    act(() => {
      result.current.setFromError(
        new ApiError(
          {
            status: 'validation_error',
            message: 'Failed',
            details: { email: ['Invalid'], code: ['Required'] },
          },
          400
        )
      )
    })

    act(() => {
      result.current.clearFieldError('email')
    })

    expect(result.current.fieldErrors).toEqual({ code: 'Required' })
  })
})
```

---

## Alternatives Considered

### Keep current DRF defaults
- Pros: No migration effort
- Cons: Inconsistent responses, complex frontend parsing, poor DX for form errors

### Use JSON:API spec
- Pros: Industry standard, rich tooling
- Cons: Overly complex for our needs, significant migration effort

### Use `{ success: boolean, data, error }` pattern
- Pros: Simple to check success
- Cons: Redundant with HTTP status codes, slightly larger payloads

## Consequences

### Positive
- Consistent API contract across all endpoints
- Simplified frontend error handling
- Field-level errors work seamlessly with form libraries
- Easier to add global error handling (toasts, logging)
- Type-safe error handling with `ApiError` class

### Negative
- Migration effort for existing endpoints
- Slight payload overhead from envelope
- Need to update all API tests
- Temporary complexity during migration (supporting both formats)

---

## Implementation Checklist

### Phase 1: Backend Infrastructure
- [ ] Add `API_RESPONSE_ENVELOPE_ENABLED` setting and gate renderer usage behind it
- [ ] Create `backend/config/renderers.py` with `EnvelopeJSONRenderer`
- [ ] Update `backend/config/exception_handler.py` for error envelope + `details` flattening
- [ ] Decide on pagination rollout (global default vs per-view), then create `backend/config/pagination.py` with `EnvelopePagination`
- [ ] Update `backend/config/settings.py` to enable the renderer only when the flag is on (and pagination if enabled)
- [ ] Add unit tests for renderer (see section 4.4)
- [ ] Add unit tests for exception handler (see section 4.4)

### Phase 2: Migrate Backend Views
- [ ] Update `backend/alarm/views/events.py` to use `meta` for pagination
- [ ] Audit all views for manual `{ data: ... }` wrapping (remove - renderer handles it)
- [ ] Audit and fix manual error `Response(..., status>=400)` returns (raise exceptions or return standardized `{ "error": ... }`)
- [ ] Update API tests to expect envelope format

### Phase 3: Frontend Infrastructure
- [ ] Create `frontend/src/types/apiEnvelope.ts` with new types
- [ ] Update `frontend/src/services/api.ts`:
  - [ ] Add `ApiError` class
  - [ ] Update `handleResponse` to unwrap envelope and log parse failures
  - [ ] Add `getWithMeta` method for paginated responses
- [ ] Update `frontend/src/lib/errors.ts` to handle `ApiError` with all status codes
- [ ] Create `frontend/src/hooks/useFormErrors.ts`
- [ ] Export new types from `frontend/src/types/index.ts`
- [ ] Add tests for `ApiError` class (see section 4.4)
- [ ] Add tests for `useFormErrors` hook (see section 4.4)

### Phase 4: Migrate Frontend Hooks
- [ ] Update `useCodesQueries.ts` to use new error handling
- [ ] Update `useDoorCodesQueries.ts` to use new error handling
- [ ] Update `useRulesQueries.ts` to use new error handling
- [ ] Update `useSettingsQueries.ts` to use new error handling
- [ ] Update form components to use `useFormErrors`

### Phase 5: Cleanup
- [ ] Remove legacy error parsing from `frontend/src/types/errors.ts`
- [ ] Remove compatibility shims from `api.ts`
- [ ] Remove `API_RESPONSE_ENVELOPE_ENABLED` and any conditional backend branching; make the envelope the default behavior
- [ ] Remove any temporary per-view opt-outs (e.g. `renderer_classes = [JSONRenderer]`) added during the migration
- [ ] Update API documentation
- [ ] Verify rollback strategy is documented (see section 4.3)
- [ ] Archive this ADR as accepted
