from __future__ import annotations


class DomainError(Exception):
    """
    Base class for predictable, user-facing domain/use-case errors.
    """


class ValidationError(DomainError):
    pass


class UnauthorizedError(DomainError):
    pass


class ForbiddenError(DomainError):
    pass


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class ServiceUnavailableError(DomainError):
    pass


class ConfigurationError(DomainError):
    """
    Missing/invalid server-side configuration required to perform an operation.
    """


class OperationTimeoutError(DomainError):
    """
    Operation timed out waiting for an external response.
    """


class GatewayError(DomainError):
    """
    Base exception for external gateway/integration failures.

    Subclasses should set `gateway_name` as a class attribute or instance attribute.
    """

    gateway_name: str | None = None


class GatewayValidationError(ValidationError):
    """
    Validation error related to a specific external gateway/integration.
    """

    gateway_name: str | None = None
