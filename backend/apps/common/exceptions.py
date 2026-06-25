from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


class DomainError(Exception):
    """Base for all application-level domain errors. Mapped to HTTP 409."""


class OtpExpiredError(DomainError):
    """OTP token is past its expires_at, or has already been consumed."""


class OtpAttemptsExceededError(DomainError):
    """OTP attempt cap has been reached."""


class AadhaarAlreadyRegisteredError(DomainError):
    """The supplied Aadhaar hash matches an existing account."""


def domain_exception_handler(exc, context):
    """DRF exception handler: converts any DomainError subclass to HTTP 409."""
    if isinstance(exc, DomainError):
        return Response(
            {"detail": str(exc), "code": type(exc).__name__},
            status=status.HTTP_409_CONFLICT,
        )
    return exception_handler(exc, context)
