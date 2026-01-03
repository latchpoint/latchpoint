from __future__ import annotations

from config.domain_exceptions import DomainError

class TransitionError(DomainError):
    pass


class CodeRequiredError(TransitionError):
    pass


class InvalidCodeError(TransitionError):
    pass
