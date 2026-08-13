"""The Home City place picker's server contract.

The create form's Home City field is driven by the vendored
``components/placepicker.js``, which is mirrored source code and must not be
edited. It asks ``GET /complete/place`` with ``query``/``limit`` (and ``near``
on the focus pass) and expects a JSON array of ``{value,label}`` — or
``{"near": [...]}`` for the nearby pass. Before this endpoint existed the field
looked like an autocomplete and answered nothing.

These tests read the contract off the vendored script itself, so the day the
mirror is refreshed with a different contract they fail rather than drift.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SITE_DIR = Path(__file__).resolve().parents[2]
CLONE_DIR = SITE_DIR / "clone"
APP_FILE = CLONE_DIR / "app.py"

DATA_DIR = Path(tempfile.mkdtemp(prefix="tripit-place-tests-"))
os.environ["WEBSITEBENCH_TRIPIT_DATA_DIR"] = str(DATA_DIR)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


app_module = load_module(APP_FILE, "tripit_clone_app_place_tests")
app = app_module.app


def picker_source() -> str:
    matches = sorted(
        (CLONE_DIR / "static" / "assets").rglob("placepicker.*.js")
    )
    assert matches, "the vendored place picker is missing from the asset closure"
    return matches[0].read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def pinned_data_dir(monkeypatch):
    monkeypatch.setenv("WEBSITEBENCH_TRIPIT_DATA_DIR", str(DATA_DIR))
    yield


@pytest.fixture()
def client():
    app_module.reset_fixture_state()
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# the contract, read off the vendored script
# ---------------------------------------------------------------------------


def test_the_vendored_picker_still_asks_for_the_endpoint_we_serve():
    source = picker_source()
    assert 'complete/place' in source
    assert "global_baseURL" in source


def test_the_vendored_pickers_minimum_length_is_the_one_we_honour():
    assert "minLength:3" in picker_source().replace(" ", "")


def test_the_create_page_still_mounts_the_picker(client):
    body = client.get("/account/create").text
    assert 'class="itUI-placepicker' in body
    assert "components/placepicker" in body


# ---------------------------------------------------------------------------
# the endpoint
# ---------------------------------------------------------------------------


def test_a_query_returns_value_label_pairs(client):
    payload = client.get("/complete/place?query=lond&limit=15").json()
    assert isinstance(payload, list)
    assert {"value": "London, United Kingdom", "label": "London, United Kingdom"} in payload
    assert all(set(row) == {"value", "label"} for row in payload)


def test_prefix_matches_are_offered_before_substring_matches(client):
    payload = client.get("/complete/place?query=york").json()
    assert payload, "expected New York to match on a substring"
    assert all("york" in row["value"].casefold() for row in payload)


def test_nothing_is_returned_below_the_pickers_minimum_length(client):
    assert client.get("/complete/place?query=lo").json() == []
    assert client.get("/complete/place?query=").json() == []


def test_the_near_pass_gets_its_own_envelope(client):
    payload = client.get("/complete/place?query=lond&near=true").json()
    assert isinstance(payload, dict)
    assert isinstance(payload["near"], list)


def test_the_limit_is_honoured_and_bounded(client):
    assert len(client.get("/complete/place?query=a&limit=3").json()) <= 3
    # an absurd limit does not turn into an unbounded response
    assert len(client.get("/complete/place?query=a&limit=100000").json()) <= 25


def test_a_nonsense_limit_falls_back_instead_of_failing(client):
    response = client.get("/complete/place?query=lond&limit=not-a-number")
    assert response.status_code in (200, 422)


def test_matching_is_case_insensitive(client):
    lower = client.get("/complete/place?query=paris").json()
    upper = client.get("/complete/place?query=PARIS").json()
    assert lower == upper and lower


def test_an_unknown_place_returns_an_empty_list_not_an_error(client):
    response = client.get("/complete/place?query=zzzzzznowhere")
    assert response.status_code == 200
    assert response.json() == []


def test_the_endpoint_is_open_to_anonymous_visitors(client):
    # The create form is reached signed out, so the picker behind it must answer
    # signed out too.
    assert client.get("/complete/place?query=lond").status_code == 200
