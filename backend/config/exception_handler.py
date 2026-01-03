from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


def _error_response(
    *,
    error_status: str,
    message: str,
    http_status: int,
    details: dict[str, list[str]] | None = None,
    gateway: str | None = None,
    operation: str | None = None,
    error: str | None = None,
) -> Response:
    body: dict[str, object] = {
        "error": {
            "status": error_status,
            "message": message,
        }
    }
    if details:
        body["error"]["details"] = details  # type: ignore[index]
    if gateway:
        body["error"]["gateway"] = gateway  # type: ignore[index]
    if operation:
        body["error"]["operation"] = operation  # type: ignore[index]
    if error:
        body["error"]["error"] = error  # type: ignore[index]
    return Response(body, status=http_status)


def _extract_first_message(data: Any) -> str | None:
    if isinstance(data, str):
        return data or None
    if isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray)):
        for item in data:
            if isinstance(item, str) and item:
                return item
        return None
    if not isinstance(data, Mapping):
        return None

    detail = data.get("detail")
    if isinstance(detail, str) and detail:
        return detail
    message = data.get("message")
    if isinstance(message, str) and message:
        return message

    non_field = data.get("non_field_errors")
    if isinstance(non_field, Sequence) and non_field and isinstance(non_field[0], str):
        return non_field[0]

    for key, value in data.items():
        if key in {"detail", "message", "non_field_errors"}:
            continue
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            if value and isinstance(value[0], str):
                return f"{key}: {value[0]}"
        if isinstance(value, str) and value:
            return f"{key}: {value}"
    return None


def _flatten_error_details(details: Any) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}

    def add(path: str, value: Any) -> None:
        key = path or "non_field_errors"
        out.setdefault(key, []).append(str(value))

    def walk(path: str, value: Any) -> None:
        if isinstance(value, Mapping):
            for k, v in value.items():
                next_path = f"{path}.{k}" if path else str(k)
                walk(next_path, v)
            return

        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            # Treat a list of scalar messages as a leaf list.
            if all(not isinstance(item, (Mapping, Sequence)) or isinstance(item, (str, bytes, bytearray)) for item in value):
                for item in value:
                    add(path, item)
                return

            for idx, item in enumerate(value):
                next_path = f"{path}.{idx}" if path else str(idx)
                walk(next_path, item)
            return

        add(path, value)

    walk("", details)
    return out


def _drf_error_status(exc: Exception, response: Response) -> str:
    if isinstance(exc, drf_exceptions.ValidationError):
        return "validation_error"
    if isinstance(exc, (drf_exceptions.ParseError, drf_exceptions.UnsupportedMediaType)):
        return "bad_request"
    if isinstance(exc, (drf_exceptions.NotAuthenticated, drf_exceptions.AuthenticationFailed)):
        return "unauthorized"
    if isinstance(exc, drf_exceptions.PermissionDenied):
        return "forbidden"
    if isinstance(exc, drf_exceptions.NotFound):
        return "not_found"
    if isinstance(exc, drf_exceptions.MethodNotAllowed):
        return "method_not_allowed"
    if isinstance(exc, drf_exceptions.Throttled):
        return "rate_limited"
    if response.status_code == 400:
        return "bad_request"
    if response.status_code >= 500:
        return "server_error"
    return "bad_request"


def _wrap_drf_error(exc: Exception, response: Response) -> Response:
    error_status = _drf_error_status(exc, response)
    data = response.data

    details: dict[str, list[str]] | None = None
    message = _extract_first_message(data) or "Request failed."

    if isinstance(exc, drf_exceptions.ValidationError):
        details = _flatten_error_details(data)
        if len(details) == 1:
            (only_key, messages), = details.items()
            if messages:
                message = messages[0]
            else:
                message = "One or more fields failed validation."
        else:
            message = "One or more fields failed validation."

    return _error_response(
        error_status=error_status,
        message=message,
        http_status=response.status_code,
        details=details,
    )


def _get_gateway_name(exc: Exception) -> str | None:
    return getattr(exc, "gateway_name", None)


def _is_not_configured(exc: Exception) -> bool:
    if getattr(exc, "not_configured", False):
        return True
    name = exc.__class__.__name__
    if name.endswith("NotConfigured"):
        return True
    return "not configured" in str(exc).lower()


def _is_not_reachable(exc: Exception) -> bool:
    if getattr(exc, "not_reachable", False):
        return True
    name = exc.__class__.__name__
    if name.endswith("NotReachable"):
        return True
    return "not reachable" in str(exc).lower()


def _is_client_unavailable(exc: Exception) -> bool:
    if getattr(exc, "client_unavailable", False):
        return True
    name = exc.__class__.__name__
    if name.endswith("ClientUnavailable") or name.endswith("NotConnected"):
        return True
    text = str(exc).lower()
    if "not connected" in text:
        return True
    return "client" in text and ("not connected" in text or "unavailable" in text)


def custom_exception_handler(exc: Exception, context):
    """
    Central exception->HTTP mapping for domain/use-case exceptions.

    Keep views/controllers thin: raise meaningful exceptions and let this layer
    translate them into consistent API responses.
    """

    response = drf_exception_handler(exc, context)
    if response is not None:
        return _wrap_drf_error(exc, response)

    # Local imports to avoid import-time side effects.
    from alarm.state_machine.errors import CodeRequiredError, InvalidCodeError, TransitionError
    from config import domain_exceptions as domain

    if isinstance(exc, InvalidCodeError):
        return _error_response(
            error_status="unauthorized",
            message=str(exc),
            http_status=status.HTTP_401_UNAUTHORIZED,
        )

    if isinstance(exc, CodeRequiredError):
        return _error_response(
            error_status="validation_error",
            message=str(exc),
            http_status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, TransitionError):
        return _error_response(
            error_status="conflict",
            message=str(exc),
            http_status=status.HTTP_409_CONFLICT,
        )

    if isinstance(exc, domain.GatewayError):
        gateway = _get_gateway_name(exc)
        operation = getattr(exc, "operation", None)
        raw_error = getattr(exc, "error", None)

        if _is_not_configured(exc) or _is_not_reachable(exc) or _is_client_unavailable(exc):
            logger.warning("Gateway unavailable: %s - %s", gateway or "unknown", str(exc))
            return _error_response(
                error_status="service_unavailable",
                message=str(exc),
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                gateway=gateway,
                operation=operation,
                error=raw_error,
            )

        logger.warning("Gateway error: %s - %s", gateway or "unknown", str(exc))
        return _error_response(
            error_status="gateway_error",
            message=str(exc),
            http_status=status.HTTP_502_BAD_GATEWAY,
            gateway=gateway,
            operation=operation,
            error=raw_error,
        )

    if isinstance(exc, domain.ValidationError):
        return _error_response(
            error_status="validation_error",
            message=str(exc),
            http_status=status.HTTP_400_BAD_REQUEST,
            gateway=_get_gateway_name(exc),
        )
    if isinstance(exc, domain.ConfigurationError):
        return _error_response(
            error_status="configuration_error",
            message=str(exc),
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if isinstance(exc, domain.UnauthorizedError):
        return _error_response(
            error_status="unauthorized",
            message=str(exc),
            http_status=status.HTTP_401_UNAUTHORIZED,
        )
    if isinstance(exc, domain.ForbiddenError):
        return _error_response(
            error_status="forbidden",
            message=str(exc),
            http_status=status.HTTP_403_FORBIDDEN,
        )
    if isinstance(exc, domain.NotFoundError):
        return _error_response(
            error_status="not_found",
            message=str(exc),
            http_status=status.HTTP_404_NOT_FOUND,
        )
    if isinstance(exc, domain.ConflictError):
        return _error_response(
            error_status="conflict",
            message=str(exc),
            http_status=status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, domain.OperationTimeoutError):
        return _error_response(
            error_status="timeout",
            message=str(exc),
            http_status=status.HTTP_504_GATEWAY_TIMEOUT,
        )
    if isinstance(exc, domain.ServiceUnavailableError):
        return _error_response(
            error_status="service_unavailable",
            message=str(exc),
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if isinstance(exc, domain.DomainError):
        return _error_response(
            error_status="bad_request",
            message=str(exc),
            http_status=status.HTTP_400_BAD_REQUEST,
        )

    logger.exception(
        "Unhandled exception in API view: %s",
        context.get("view").__class__.__name__ if context.get("view") else "unknown",
        exc_info=exc,
    )
    return None
