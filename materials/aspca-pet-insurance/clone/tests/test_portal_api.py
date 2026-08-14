"""Portal validation, enumeration resistance, and registration boundaries."""


def test_login_empty_fields_are_validation_errors(client) -> None:
    response = client.post("/portal/api/login", json={"email": "", "password": ""})
    assert response.status_code == 422
    errors = response.json()["errors"]
    assert "email" in errors
    assert "password" in errors


def test_login_with_unknown_credentials_is_generic(client) -> None:
    response = client.post(
        "/portal/api/login",
        json={"email": "member@example.com", "password": "hunter2-not-real"},
    )
    assert response.status_code == 403
    body = response.json()
    assert body["authenticated"] is False
    assert body["message"] == "The email or password is incorrect."


def test_forgot_password_requires_email(client) -> None:
    response = client.post("/portal/api/forgot-password", json={"email": ""})
    assert response.status_code == 422
    assert "email" in response.json()["errors"]


def test_forgot_password_does_not_disclose_unknown_account(client) -> None:
    response = client.post(
        "/portal/api/forgot-password", json={"email": "member@example.com"}
    )
    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] is True
    assert body["mail_status"] is None
    assert "If that email belongs" in body["message"]


def test_register_requires_profile_terms_and_verification(client) -> None:
    empty = client.post("/portal/api/register", json={})
    assert empty.status_code == 422

    response = client.post(
        "/portal/api/register",
        json={"email": "member@example.com", "password": "hunter2-not-real"},
    )
    assert response.status_code == 422
    assert set(response.json()["errors"]) == {"display_name", "accept_terms"}


def test_portal_api_unknown_path_is_json_404(client) -> None:
    response = client.post("/portal/api/does-not-exist", json={})
    assert response.status_code == 404
    assert response.json() == {"error": "not-found"}
