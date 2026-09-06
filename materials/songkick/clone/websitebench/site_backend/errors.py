"""Errors exposed by the site backend interface."""

from __future__ import annotations


class SiteBackendError(RuntimeError):
    """Base error for the site backend deep module."""


class RuntimeContractError(SiteBackendError, ValueError):
    """The frozen backend runtime contract is invalid."""


class SiteBindingError(SiteBackendError):
    """A database or transaction belongs to another site."""


class LifecycleError(SiteBackendError):
    """Database lifecycle work could not be completed safely."""


class MailError(SiteBackendError):
    """A mail purpose, template, or queue transition is invalid."""


class PaymentError(SiteBackendError):
    """A payment transition or caller-supplied payment fact is invalid."""


class PaymentConflict(PaymentError):
    """An idempotency key or active flow conflicts with immutable facts."""


class PaymentRejected(PaymentError):
    """A payment flow is missing, foreign, stale, or not approved."""
