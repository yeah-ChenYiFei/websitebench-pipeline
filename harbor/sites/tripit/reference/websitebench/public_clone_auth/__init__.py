"""Reusable email verification boundary for public website clones."""

from .frontend import registration_frontend_script
from .sqlite import ensure_sqlite_email_verified
from .verification import (
    ExternalRegistrationVerification,
    PublicCloneIdentity,
    RegistrationMailTemplate,
    RedisRestClient,
    ResendEmailClient,
    VerificationConfigurationError,
    VerificationIssue,
    VerificationLocked,
    VerificationRateLimited,
    VerificationUnavailable,
    load_public_clone_registration_verification,
    normalize_registration_email,
)

__all__ = [
    "ExternalRegistrationVerification",
    "PublicCloneIdentity",
    "RegistrationMailTemplate",
    "RedisRestClient",
    "ResendEmailClient",
    "VerificationConfigurationError",
    "VerificationIssue",
    "VerificationLocked",
    "VerificationRateLimited",
    "VerificationUnavailable",
    "ensure_sqlite_email_verified",
    "load_public_clone_registration_verification",
    "normalize_registration_email",
    "registration_frontend_script",
]
