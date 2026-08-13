"""Status and coverage reports for an offline-clone site.

These describe what a site *declares*: its identity, its scope contracts, its
asset closure and its coverage ledger. What a site *proves* comes from
``diagnostics.verify``, which runs the static and live sections and returns its
own report.
"""

from __future__ import annotations

from typing import Any

from .assets import verify_asset_closure
from .manifest import LoadedManifest, load_coverage_ledger, utc_now


def status_report(manifest: LoadedManifest) -> dict[str, Any]:
    return {
        "schema_version": "offline-clone.status.v3",
        "site_id": manifest.data["site_id"],
        "display_name": manifest.data["display_name"],
        "state_model": manifest.data["state_model"],
        "generated_at": utc_now(),
    }


def coverage_report(manifest: LoadedManifest) -> dict[str, Any]:
    """What each coverage dimension requires, dimension by dimension.

    Denominators only. A finalized ledger is required to leave `satisfied_items`
    empty because per-kind acceptance evidence owned the numerators, and that
    evidence layer is gone -- so there is no numerator to report, and inventing
    one from an always-empty field would be a metric that can never move.
    What a candidate actually does is `diagnostics.verify`.
    """

    ledger = load_coverage_ledger(manifest.coverage_path)
    dimensions = [
        {
            "id": dimension["id"],
            "unit": dimension.get("unit"),
            "required_items": list(dimension["required_items"]),
            "denominator": len(dimension["required_items"]),
        }
        for dimension in ledger["dimensions"]
    ]
    return {
        "ledger_status": ledger.get("status"),
        "dimensions": dimensions,
        "denominator_total": sum(row["denominator"] for row in dimensions),
    }


def full_report(manifest: LoadedManifest) -> dict[str, Any]:
    closure = verify_asset_closure(manifest)
    status = status_report(manifest)
    return {
        "schema_version": "offline-clone.report.v3",
        "generated_at": utc_now(),
        **{key: value for key, value in status.items() if key != "schema_version"},
        "source_baseline": manifest.data["source"]["baseline"],
        "runtime_remote_request_policy": manifest.data["source"]["capture_policy"][
            "runtime_remote_requests"
        ],
        "asset_closure": closure.as_dict(),
        "coverage": coverage_report(manifest),
    }
