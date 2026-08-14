"""Application review and authenticated member lifecycle contracts."""

from __future__ import annotations


PET = {
    "species": "Cat",
    "name": "Willow",
    "age_label": "2 Years",
    "gender": "Female",
    "breed": "Domestic Shorthair",
    "email": "member@example.com",
    "zip": "44301",
}


def _quote(client, email: str = "member@example.com") -> str:
    response = client.post("/api/quotes", json={**PET, "email": email})
    assert response.status_code == 201
    return response.json()["quote_id"]


def _register(client, email: str = "member@example.com") -> dict:
    session = client.get("/portal/api/session")
    assert session.status_code == 200
    assert session.json()["authenticated"] is False

    started = client.post(
        "/portal/api/register",
        json={
            "email": email,
            "display_name": "Taylor Morgan",
            "password": "correct-horse-battery-staple",
            "accept_terms": True,
        },
    )
    assert started.status_code == 202
    assert started.json()["mail_status"] == "LOCAL_ONLY"

    inbox = client.get("/portal/api/local-inbox/registration")
    assert inbox.status_code == 200
    code = inbox.json()["verification_code"]
    assert len(code) == 6

    completed = client.post(
        "/portal/api/register/verify",
        json={"code": code},
    )
    assert completed.status_code == 201
    assert completed.json()["authenticated"] is True
    return completed.json()["account"]


def _enroll(client, quote_id: str) -> str:
    response = client.post(
        f"/api/quotes/{quote_id}/enroll",
        json={
            "contact": {
                "firstName": "Taylor",
                "lastName": "Morgan",
                "address1": "1 Main St",
                "city": "Akron",
                "state": "OH",
                "zip": "44301",
                "phone": "555-555-5555",
                "email": "member@example.com",
            },
            "frequency": "Monthly",
            "paperless": True,
            "agree_terms": True,
            "scenario_id": "sandbox-approved",
        },
    )
    assert response.status_code == 201
    return response.json()["policy_number"]


def test_application_review_questions_consent_and_location_persist(client) -> None:
    quote_id = _quote(client)

    eligibility = client.get(f"/api/quotes/{quote_id}/eligibility")
    assert eligibility.status_code == 200
    assert eligibility.json() == {
        "eligible": True,
        "zip": "44301",
        "state": "OH",
        "enrollment_fee": "0.00",
        "currency": "USD",
    }

    missing_conditional = client.put(
        f"/api/quotes/{quote_id}/application",
        json={
            "contact": {"first_name": "Taylor", "last_name": "Morgan"},
            "questions": {
                "currently_ill": True,
                "condition_details": "",
                "seen_vet_last_12_months": False,
            },
            "consent": {"privacy": True, "electronic_signature": True},
        },
    )
    assert missing_conditional.status_code == 422
    assert "condition_details" in missing_conditional.json()["errors"]

    saved = client.put(
        f"/api/quotes/{quote_id}/application",
        json={
            "contact": {
                "first_name": "Taylor",
                "last_name": "Morgan",
                "address": "1 Main St",
                "city": "Akron",
                "state": "OH",
                "zip": "44301",
                "phone": "555-555-5555",
            },
            "questions": {
                "currently_ill": True,
                "condition_details": "Seasonal allergies",
                "seen_vet_last_12_months": True,
                "vet_name": "Main Street Veterinary Clinic",
            },
            "consent": {"privacy": True, "electronic_signature": True},
        },
    )
    assert saved.status_code == 200
    assert saved.json()["review_ready"] is True

    reviewed = client.get(f"/api/quotes/{quote_id}/application")
    assert reviewed.status_code == 200
    assert reviewed.json()["contact"]["city"] == "Akron"
    assert reviewed.json()["questions"]["condition_details"] == "Seasonal allergies"
    assert reviewed.json()["consent"]["electronic_signature"] is True

    edited = client.put(
        f"/api/quotes/{quote_id}/application",
        json={**saved.json(), "contact": {**saved.json()["contact"], "city": "Cuyahoga Falls"}},
    )
    assert edited.status_code == 200
    assert client.get(f"/api/quotes/{quote_id}/application").json()["contact"]["city"] == "Cuyahoga Falls"


def test_registration_signin_dashboard_policy_claims_documents_and_billing(client) -> None:
    account = _register(client)
    assert account["email_normalized"] == "member@example.com"

    quote_id = _quote(client)
    policy_number = _enroll(client, quote_id)

    dashboard = client.get("/portal/api/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["metrics"]["active_policies"] == 1
    assert dashboard.json()["policies"][0]["policy_number"] == policy_number
    assert dashboard.json()["policies"][0]["pet"]["name"] == "Willow"

    policy = client.get(f"/portal/api/policies/{policy_number}")
    assert policy.status_code == 200
    assert policy.json()["status"] == "active"
    assert policy.json()["insured"]["breed"] == "Domestic Shorthair"
    assert policy.json()["holder"]["firstName"] == "Taylor"

    updated = client.patch(
        f"/portal/api/policies/{policy_number}/coverage",
        json={"annual_limit": 7000, "deductible": 250, "reimbursement": 90, "preventive": "basic"},
    )
    assert updated.status_code == 200
    assert updated.json()["coverage"]["annual_limit"] == 7000
    assert updated.json()["coverage"]["monthly"] == "35.58"
    assert client.get(f"/portal/api/policies/{policy_number}").json()["coverage"]["annual_limit"] == 7000

    billing = client.patch(
        f"/portal/api/policies/{policy_number}/billing",
        json={"autopay": True, "frequency": "Annually"},
    )
    assert billing.status_code == 200
    assert billing.json()["autopay"] is True
    assert billing.json()["frequency"] == "Annually"
    assert billing.json()["total"] == "546.36"

    documents = client.get(f"/portal/api/policies/{policy_number}/documents")
    assert documents.status_code == 200
    assert {item["kind"] for item in documents.json()["documents"]} >= {"policy", "coverage-summary"}
    download_url = documents.json()["documents"][0]["download_url"]
    assert client.get(download_url).headers["content-type"] == "application/pdf"

    invalid_upload = client.post(
        "/portal/api/uploads",
        json={"filename": "malware.exe", "content_type": "application/octet-stream", "size": 100},
    )
    assert invalid_upload.status_code == 422
    valid_upload = client.post(
        "/portal/api/uploads",
        json={"filename": "invoice.pdf", "content_type": "application/pdf", "size": 2048},
    )
    assert valid_upload.status_code == 201
    assert valid_upload.json()["parse_status"] == "parsed"

    missing_claim_condition = client.post(
        "/portal/api/claims",
        json={"policy_number": policy_number, "incident_date": "2026-07-20", "reason": "Illness", "provider": "Main Street Veterinary Clinic", "amount": "125.00", "has_invoice": True},
    )
    assert missing_claim_condition.status_code == 422
    assert "upload_id" in missing_claim_condition.json()["errors"]

    claim = client.post(
        "/portal/api/claims",
        json={"policy_number": policy_number, "incident_date": "2026-07-20", "reason": "Illness", "provider": "Main Street Veterinary Clinic", "amount": "125.00", "has_invoice": True, "upload_id": valid_upload.json()["upload_id"]},
    )
    assert claim.status_code == 201
    claim_number = claim.json()["claim_number"]
    assert claim.json()["status"] == "submitted"
    assert client.get(f"/portal/api/claims/{claim_number}").json()["evidence"][0]["filename"] == "invoice.pdf"
    assert client.get("/portal/api/claims").json()["metrics"]["submitted"] == 1

    renewed = client.post(f"/portal/api/policies/{policy_number}/renew", json={})
    assert renewed.status_code == 200
    assert renewed.json()["status"] == "active"
    assert renewed.json()["renewed"] is True

    canceled = client.post(
        f"/portal/api/policies/{policy_number}/cancel",
        json={"reason": "No longer needed", "confirm": True},
    )
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"
    assert canceled.json()["renewal_eligible"] is False
    assert client.get(f"/portal/api/policies/{policy_number}").json()["status"] == "canceled"

    signed_out = client.post("/portal/api/logout", json={})
    assert signed_out.status_code == 200
    assert client.get("/portal/api/dashboard").status_code == 401

    signed_in = client.post(
        "/portal/api/login",
        json={"email": "member@example.com", "password": "correct-horse-battery-staple"},
    )
    assert signed_in.status_code == 200
    assert signed_in.json()["authenticated"] is True
    assert client.get("/portal/api/dashboard").json()["policies"][0]["status"] == "canceled"
