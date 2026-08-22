"""Shared semantics for site-isolated clone databases, mail, and payments."""

from .backend import SiteBackend
from .auth_mail import AuthMailDelivery, AuthMailDeliveryError
from .effects_mail import EffectsMailDelivery, EffectsMailDeliveryError
from .errors import (
    LifecycleError,
    MailError,
    PaymentConflict,
    PaymentError,
    PaymentRejected,
    RuntimeContractError,
    SiteBackendError,
    SiteBindingError,
)
from .runtime import RUNTIME_SCHEMA_VERSION, RuntimeConfig, load_runtime
from .stdio_bridge import (
    BRIDGE_SCHEMA_VERSION,
    BridgeProtocolError,
    BridgeService,
    serve_jsonl,
    validate_allowlist,
)

__all__ = [
    "RUNTIME_SCHEMA_VERSION",
    "BRIDGE_SCHEMA_VERSION",
    "BridgeProtocolError",
    "BridgeService",
    "LifecycleError",
    "AuthMailDelivery",
    "AuthMailDeliveryError",
    "EffectsMailDelivery",
    "EffectsMailDeliveryError",
    "MailError",
    "PaymentConflict",
    "PaymentError",
    "PaymentRejected",
    "RuntimeConfig",
    "RuntimeContractError",
    "SiteBackend",
    "SiteBackendError",
    "SiteBindingError",
    "load_runtime",
    "serve_jsonl",
    "validate_allowlist",
]
