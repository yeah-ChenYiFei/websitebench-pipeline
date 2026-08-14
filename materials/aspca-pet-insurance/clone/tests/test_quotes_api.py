"""Quote-funnel JSON API: create -> rate -> add pet -> resume -> enroll."""


PET = {
    "species": "Cat",
    "name": "Willow",
    "age": "2 Years",
    "gender": "Female",
    "breed": "Domestic Shorthair",
}
EMAIL = "willow-capture-2026-08-13@example.com"
ZIP = "44301"


def _create(client, **overrides):
    payload = {**PET, "email": EMAIL, "zip": ZIP, **overrides}
    return client.post("/api/quotes", json=payload)


def test_create_quote_success(client) -> None:
    response = _create(client)
    assert response.status_code == 201
    body = response.json()
    assert body["eligible"] is True
    assert body["quote_id"].startswith("WB")
    assert body["pet"]["name"] == "Willow"
    assert body["pet"]["selection"]["monthly"] == "16.74"
    tier_prices = [t["monthly"] for t in body["rates"]["tiers"]]
    assert tier_prices == ["8.48", "16.74", "23.19"]


def test_create_quote_missing_fields(client) -> None:
    response = client.post("/api/quotes", json={"species": "Dog"})
    assert response.status_code == 422
    errors = response.json()["errors"]
    for field in ("name", "age_label", "gender", "breed", "email", "zip"):
        assert field in errors


def test_create_quote_email_tld_rule(client) -> None:
    # ng-pattern on the source form caps the TLD at 4 characters.
    ok = _create(client, email="pet@example.info")
    assert ok.status_code == 201
    bad = _create(client, email="pet@example.museum")
    assert bad.status_code == 422
    assert "email" in bad.json()["errors"]


def test_create_quote_invalid_zip_is_ineligible(client) -> None:
    response = _create(client, zip="00000")
    assert response.status_code == 422
    body = response.json()
    assert body["eligible"] is False
    assert body["errors"]["zip"] == "00000 is not a valid zip code."


def test_rate_walk_matches_observed_prices(client) -> None:
    quote_id = _create(client).json()["quote_id"]

    def rate(**kw):
        payload = {"limit": 5000, "deductible": 500, "reimbursement": 80, **kw}
        response = client.post(f"/api/quotes/{quote_id}/rate", json=payload)
        assert response.status_code == 200, response.text
        return response.json()

    assert rate()["monthly"] == "16.74"
    assert rate(deductible=250)["monthly"] == "23.65"
    step = rate(deductible=250, reimbursement=90)
    assert step["monthly"] == "30.83"
    assert step["provenance"] == "directly-observed"
    # annual-limit re-select: same limit, no delta
    assert rate(limit=5000, deductible=250, reimbursement=90)["monthly"] == "30.83"
    # preventive is a separate line item
    basic = rate(preventive="basic")
    assert basic["monthly"] == "16.74"
    assert basic["preventive_monthly"] == "9.95"
    assert basic["total_monthly"] == "26.69"


def test_rate_rejects_off_table_values(client) -> None:
    quote_id = _create(client).json()["quote_id"]
    response = client.post(
        f"/api/quotes/{quote_id}/rate",
        json={"limit": 5000, "deductible": 123, "reimbursement": 80},
    )
    assert response.status_code == 422


def test_rate_persists_selection(client) -> None:
    quote_id = _create(client).json()["quote_id"]
    client.post(
        f"/api/quotes/{quote_id}/rate",
        json={"limit": 5000, "deductible": 250, "reimbursement": 90},
    )
    quote = client.get(f"/api/quotes/{quote_id}").json()
    selection = quote["pets"][0]["selection"]
    assert selection["deductible"] == 250
    assert selection["monthly"] == "30.83"


def test_add_pet(client) -> None:
    quote_id = _create(client).json()["quote_id"]
    response = client.post(
        f"/api/quotes/{quote_id}/pets",
        json={
            "species": "Dog",
            "name": "Biscuit",
            "age": "4 Years",
            "gender": "Male",
            "breed": "Beagle",
        },
    )
    assert response.status_code == 201
    pets = response.json()["pets"]
    assert [p["name"] for p in pets] == ["Willow", "Biscuit"]
    assert pets[1]["selection"]["monthly"] == "16.74"


def test_quote_search_resume(client) -> None:
    quote_id = _create(client).json()["quote_id"]
    found = client.get("/api/quotes/search", params={"email": EMAIL, "zip": ZIP})
    assert found.status_code == 200
    assert found.json()["quote_id"] == quote_id

    missing = client.get(
        "/api/quotes/search", params={"email": "nobody@example.com", "zip": ZIP}
    )
    assert missing.status_code == 404


def test_enroll_happy_path(client) -> None:
    quote_id = _create(client).json()["quote_id"]
    response = client.post(
        f"/api/quotes/{quote_id}/enroll",
        json={
            "firstName": "Willow",
            "lastName": "Example",
            "address1": "1 Main St",
            "city": "Akron",
            "state": "OH",
            "zip": ZIP,
            "phone": "555-0100",
            "email": EMAIL,
            "frequency": "Annually",
            "agree_terms": True,
            "paperless": True,
            "scenario_id": "sandbox-approved",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["policy_number"] == "APH-000001"
    assert body["payment"]["status"] == "CONSUMED"
    assert body["payment"]["amount_minor"] == 20088
    assert body["payment"]["currency"] == "USD"
    assert body["payment"]["is_simulation"] is True
    assert body["mail"]["purpose"] == "policy-confirmation"
    assert body["mail"]["status"] == "LOCAL_SIMULATION"
    assert body["mail"]["is_simulation"] is True
    quote = client.get(f"/api/quotes/{quote_id}").json()
    assert quote["status"] == "enrolled"
    assert quote["enrollment"]["frequency"] == "Annually"
    assert quote["enrollment"]["paperless"] is True


def test_enroll_requires_agree_terms_and_frequency(client) -> None:
    quote_id = _create(client).json()["quote_id"]
    response = client.post(
        f"/api/quotes/{quote_id}/enroll",
        json={
            "frequency": "Weekly",
            "agree_terms": False,
            "scenario_id": "sandbox-approved",
        },
    )
    assert response.status_code == 422
    errors = response.json()["errors"]
    assert "agreeTerms" in errors
    assert "frequency" in errors


def test_enroll_is_idempotent(client) -> None:
    quote_id = _create(client).json()["quote_id"]
    payload = {
        "frequency": "Monthly",
        "agree_terms": True,
        "paperless": False,
        "scenario_id": "sandbox-approved",
    }
    first = client.post(f"/api/quotes/{quote_id}/enroll", json=payload)
    second = client.post(f"/api/quotes/{quote_id}/enroll", json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["policy_number"] == second.json()["policy_number"]
    assert first.json()["payment"]["flow_id"] == second.json()["payment"]["flow_id"]
    assert first.json()["mail"]["mail_id"] == second.json()["mail"]["mail_id"]


def test_payment_credentials_and_server_facts_are_rejected_everywhere(client) -> None:
    # Only an opaque local-sandbox scenario id is accepted at enrollment.
    created = _create(client, cardNumber="4111111111111111")
    assert created.status_code == 422
    assert "payment" in created.json()["errors"]

    quote_id = _create(client).json()["quote_id"]
    for payload in (
        {"agree_terms": True, "frequency": "Monthly", "scenario_id": "sandbox-approved", "cvv": "123"},
        {"agree_terms": True, "frequency": "Monthly", "scenario_id": "sandbox-approved", "cc_number": "4111"},
        {"agree_terms": True, "frequency": "Monthly", "scenario_id": "sandbox-approved", "bankAccount": "x"},
        {"agree_terms": True, "frequency": "Monthly", "scenario_id": "sandbox-approved", "amount_minor": 1},
        {"agree_terms": True, "frequency": "Monthly", "scenario_id": "sandbox-approved", "currency": "EUR"},
        {"agree_terms": True, "frequency": "Monthly", "scenario_id": "sandbox-approved", "owner": "foreign"},
        {"agree_terms": True, "frequency": "Monthly", "scenario_id": "sandbox-approved", "fingerprint": "0" * 64},
        {"agree_terms": True, "frequency": "Monthly", "scenario_id": "sandbox-approved", "flow_id": "payflow_client"},
    ):
        response = client.post(f"/api/quotes/{quote_id}/enroll", json=payload)
        assert response.status_code == 422, payload
        assert "payment" in response.json()["errors"]


def test_unknown_quote_is_json_404(client) -> None:
    response = client.get("/api/quotes/WB999999")
    assert response.status_code == 404
    assert response.json() == {"error": "not-found"}
