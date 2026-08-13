from __future__ import annotations

from typing import Any


def runtime_config(
    site_id: str = "alpha",
    label: str = "Alpha Clone",
    *,
    stripe: bool = False,
    legacy_unbound_migration: bool = False,
) -> dict[str, Any]:
    stripe_test = (
        {
            "public_origin": f"https://{site_id}.example.test",
            "return_path": "/checkout/stripe-return",
            "webhook_path": "/api/stripe/webhook",
            "max_line_items": 20,
            "secret_key_env": "STRIPE_SECRET_KEY",
            "webhook_secret_env": "STRIPE_WEBHOOK_SECRET",
        }
        if stripe
        else None
    )
    payment_adapter = "stripe-test" if stripe else "local-sandbox"
    return {
        "schema_version": "websitebench.site-backend-runtime.v1",
        "site": {
            "id": site_id,
            "label": label,
            "public_origin": f"https://{site_id}.example.test",
        },
        "database": {
            "engine": "sqlite",
            "data_dir": "data",
            "filename": f"{site_id}.sqlite3",
            "migration_hook": None,
            "seed_hook": None,
            "legacy_unbound_migration": legacy_unbound_migration,
        },
        "session": {
            "host_only": True,
            "secure": True,
            "http_only": True,
            "same_site": "Lax",
        },
        "mail": {
            "sender": {
                "display_name": label,
                "address_env": "RESEND_FROM_EMAIL",
            },
            "purposes": {
                "registration": {
                    "template_id": f"{site_id}.registration.v1",
                    "subject": f"Verify your {label} account",
                    "lead": f"Finish creating your {label} account.",
                    "body": "Your verification code is ${code}.",
                    "expiry": "This code expires in ${minutes} minutes.",
                    "footer": f"This message only applies to {label}.",
                    "required_variables": ["code", "minutes"],
                    "secret_variables": ["code"],
                },
                "order-receipt": {
                    "template_id": f"{site_id}.order-receipt.v1",
                    "subject": f"Your {label} order ${{order_id}}",
                    "lead": "Your simulated order is recorded.",
                    "body": "Order ${order_id} totals ${total}.",
                    "expiry": "No real funds moved.",
                    "footer": f"Thank you for using {label}.",
                    "required_variables": ["order_id", "total"],
                    "secret_variables": [],
                },
            },
        },
        "payments": {
            "default_adapter": "local-sandbox",
            "currency": "USD",
            "local_sandbox": {
                "scenarios": [
                    {
                        "id": "sandbox-approved",
                        "outcome": "approved",
                        "display_label": "Approve",
                    },
                    {
                        "id": "sandbox-declined",
                        "outcome": "declined",
                        "display_label": "Decline",
                    },
                    {
                        "id": "sandbox-retry",
                        "outcome": "retryable",
                        "display_label": "Retry",
                    },
                ]
            },
            "stripe_test": stripe_test,
        },
        "deployment": {
            "profiles": {
                "offline-harbor": {
                    "persistence": "persistent",
                    "mail_adapter": "local-outbox",
                    "payment_adapter": "local-sandbox",
                },
                "cloudflare-review": {
                    "persistence": "ephemeral-reset",
                    "mail_adapter": "redis-resend",
                    "payment_adapter": payment_adapter,
                },
                "docker-volume": {
                    "persistence": "persistent-volume",
                    "mail_adapter": "effects-gateway",
                    "payment_adapter": payment_adapter,
                },
            }
        },
    }
