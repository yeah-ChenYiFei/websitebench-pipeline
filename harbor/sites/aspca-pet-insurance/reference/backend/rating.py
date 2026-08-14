"""ASPCA Pet Health Insurance offline clone — deterministic rating engine.

Encodes the rating table frozen in ``clone/backend/model.json``, which in turn
carries the directly-observed price walk from
``source-current/2026-08-13.aspca-pet-insurance-r1/rating-claims.json``.

Model: ``monthly = round_half_up(base_monthly[annual_limit] * deductible_factor
* reimbursement_factor, 2)``. Cells the source walk did not price are marked
``derived`` in the model and surfaced through :func:`provenance` so callers can
report honestly which prices were observed on the source site and which are
mechanical extensions.

No wall clock, no randomness: identical inputs always price identically.
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

MODEL_PATH = Path(__file__).resolve().parent / "model.json"

_CENT = Decimal("0.01")


class RatingError(ValueError):
    """Raised for an option value outside the frozen rating table."""


@lru_cache(maxsize=1)
def load_model() -> dict[str, Any]:
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


def _round_half_up(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def annual_limits() -> list[int]:
    model = load_model()
    return sorted(int(k) for k in model["custom_plan"]["base_monthly_by_annual_limit"])


def deductibles() -> list[int]:
    model = load_model()
    return sorted(int(k) for k in model["custom_plan"]["deductible_factors"])


def reimbursements() -> list[int]:
    model = load_model()
    return sorted(int(k) for k in model["custom_plan"]["reimbursement_factors"])


def tiers() -> list[dict[str, Any]]:
    """The three source tier cards (limit/deductible/reimbursement/monthly)."""

    model = load_model()
    return [
        {
            "id": tier["id"],
            "annual_limit": tier["annual_limit"],
            "deductible": tier["deductible"],
            "reimbursement": tier["reimbursement"],
            "monthly": tier["monthly"],
            "provenance": tier["provenance"],
        }
        for tier in model["tiers"]
    ]


def _cell(table: dict[str, Any], key: int, label: str) -> dict[str, Any]:
    cell = table.get(str(key))
    if cell is None:
        raise RatingError(f"{label} {key} is not in the rating table")
    return cell


def preventive_monthly(option: str | None) -> tuple[Decimal, str | None]:
    """Monthly price of the separately-billed preventive add-on (0 if none)."""

    if option in (None, "", "none"):
        return Decimal("0.00"), None
    model = load_model()
    cell = model["preventive"].get(option)
    if not isinstance(cell, dict):
        raise RatingError(f"preventive option {option!r} is not in the rating table")
    return Decimal(cell["monthly"]), cell["provenance"]


def rate(
    annual_limit: int,
    deductible: int,
    reimbursement: int,
    preventive: str | None = None,
) -> dict[str, Any]:
    """Price one custom-plan selection.

    Returns monthly plan price, separately-billed preventive price, the total
    of the two, and provenance (``directly-observed`` only when every factor in
    the multiplication was observed on the source walk, else ``derived``).
    """

    model = load_model()
    custom = model["custom_plan"]
    base = _cell(custom["base_monthly_by_annual_limit"], annual_limit, "annual limit")
    ded = _cell(custom["deductible_factors"], deductible, "deductible")
    reimb = _cell(custom["reimbursement_factors"], reimbursement, "reimbursement")

    monthly = _round_half_up(
        Decimal(base["monthly"]) * Decimal(ded["factor"]) * Decimal(reimb["factor"])
    )
    parts = (base["provenance"], ded["provenance"], reimb["provenance"])
    provenance = (
        "directly-observed"
        if all(p == "directly-observed" for p in parts)
        else "derived"
    )
    preventive_price, preventive_provenance = preventive_monthly(preventive)
    return {
        "annual_limit": annual_limit,
        "deductible": deductible,
        "reimbursement": reimbursement,
        "monthly": f"{monthly:.2f}",
        "preventive": preventive if preventive not in ("", "none") else None,
        "preventive_monthly": f"{preventive_price:.2f}",
        "preventive_provenance": preventive_provenance,
        "total_monthly": f"{_round_half_up(monthly + preventive_price):.2f}",
        "provenance": provenance,
    }


def valid_zip(zip_code: str) -> bool:
    """Frozen ZIP rule: five digits, not all zeros (observed probe: 00000)."""

    return len(zip_code) == 5 and zip_code.isdigit() and zip_code != "00000"


def zip_error_message(zip_code: str) -> str:
    """Observed message format ('00000 is not a valid zip code.')."""

    return f"{zip_code} is not a valid zip code."
