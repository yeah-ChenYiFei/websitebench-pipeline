"""Rating engine vs the directly-observed source price walk.

The observed anchors are read from the capture evidence
(``source-current/<capture-id>/rating-claims.json``) rather than re-typed here,
so a drift between the model and the evidence fails loudly.
"""

import json
import re
from pathlib import Path

import pytest

from backend import rating
from backend.rating import RatingError

SITE_DIR = Path(__file__).resolve().parents[2]
CLAIMS_PATH = (
    SITE_DIR
    / "source-current"
    / "2026-08-13.aspca-pet-insurance-r1"
    / "rating-claims.json"
)

_PRICE_RE = re.compile(r"\$([0-9,]+\.[0-9]{2})/mo")


def _observation_prices(observation: dict) -> list[str]:
    return [
        match.group(1).replace(",", "")
        for entry in observation["observed_prices"]
        for match in [_PRICE_RE.match(entry["text"])]
        if match
    ]


def _claims() -> dict:
    return json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))


def test_tier_ladder_matches_observed_capture() -> None:
    claims = _claims()
    initial = next(
        o for o in claims["observations"] if o["state"] == "quote-rates-initial"
    )
    observed = _observation_prices(initial)
    tier_prices = [t["monthly"] for t in rating.tiers()]
    # The first three /mo prices on the rates view are the tier cards.
    assert observed[:3] == tier_prices == ["8.48", "16.74", "23.19"]


def test_observed_customization_walk_reproduced_exactly() -> None:
    claims = _claims()
    by_state = {o["state"]: o for o in claims["observations"]}

    # base custom plan 5000/500/80
    assert rating.rate(5000, 500, 80)["monthly"] == "16.74"

    # deductible -> $250 (observed after-state carries 23.65)
    ded = by_state["customize-deductible"]
    assert ded["control"]["name"] == "annualDeductiblel2"
    assert ded["control"]["value"] == "Deductible250"
    assert "23.65" in _observation_prices(ded)
    assert rating.rate(5000, 250, 80)["monthly"] == "23.65"

    # then reimbursement -> 90% (observed after-state carries 30.83)
    reimb = by_state["customize-reimbursement"]
    assert reimb["control"]["name"] == "reimbursementPercentl2"
    assert reimb["control"]["value"] == "Copay10"
    assert "30.83" in _observation_prices(reimb)
    assert rating.rate(5000, 250, 90)["monthly"] == "30.83"

    # annual-limit re-select $5,000: no delta
    limit = by_state["customize-annual-limit"]
    assert limit["control"]["name"] == "annualLimitl2"
    assert _observation_prices(limit) == _observation_prices(reimb)


def test_model_observed_checks_all_pass() -> None:
    model = rating.load_model()
    for check in model["observed_checks"]:
        priced = rating.rate(
            check["annual_limit"], check["deductible"], check["reimbursement"]
        )
        assert priced["monthly"] == check["expected_monthly"], check


def test_observed_cells_report_observed_provenance() -> None:
    assert rating.rate(5000, 250, 90)["provenance"] == "directly-observed"
    assert rating.rate(2500, 500, 80)["provenance"] == "directly-observed"


def test_derived_cells_report_derived_provenance() -> None:
    # $7,000 limit, $100/$750 deductibles and 70% reimbursement were visible
    # UI options but never priced by the walk — they must say so.
    assert rating.rate(7000, 500, 80)["provenance"] == "derived"
    assert rating.rate(5000, 100, 80)["provenance"] == "derived"
    assert rating.rate(5000, 750, 80)["provenance"] == "derived"
    assert rating.rate(5000, 500, 70)["provenance"] == "derived"


def test_preventive_prices_are_separate_line_items() -> None:
    claims = _claims()
    initial = next(
        o for o in claims["observations"] if o["state"] == "quote-rates-initial"
    )
    observed = _observation_prices(initial)
    assert "9.95" in observed and "24.95" in observed

    priced = rating.rate(5000, 500, 80, "basic")
    assert priced["monthly"] == "16.74"  # plan price unchanged
    assert priced["preventive_monthly"] == "9.95"
    assert priced["total_monthly"] == "26.69"

    prime = rating.rate(5000, 500, 80, "prime")
    assert prime["preventive_monthly"] == "24.95"
    assert prime["total_monthly"] == "41.69"


def test_off_table_options_are_rejected() -> None:
    with pytest.raises(RatingError):
        rating.rate(12345, 500, 80)
    with pytest.raises(RatingError):
        rating.rate(5000, 123, 80)
    with pytest.raises(RatingError):
        rating.rate(5000, 500, 55)
    with pytest.raises(RatingError):
        rating.rate(5000, 500, 80, "deluxe")


def test_zip_rule_matches_observed_probe() -> None:
    assert rating.valid_zip("44301")
    assert not rating.valid_zip("00000")
    assert not rating.valid_zip("1234")
    assert not rating.valid_zip("abcde")
    assert rating.zip_error_message("00000") == "00000 is not a valid zip code."
