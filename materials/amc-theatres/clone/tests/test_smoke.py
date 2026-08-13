from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_home() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "See movies" in response.text
    assert "Now Playing" in response.text


def test_core_routes_render() -> None:
    for route, expected in [
        ("/movies", "Movies at AMC"),
        ("/movies/superman", "Choose a showtime"),
        ("/movie-theatres", "Movie Theatres Near You"),
        ("/movie-theatres/ny/amc-empire-25", "234 West 42nd Street"),
        ("/showtimes", "Reserve your seats"),
        ("/checkout/superman", "Choose your seats"),
        ("/login", "Sign in to My AMC"),
        ("/sign-up", "Join for free"),
    ]:
        response = client.get(route)
        assert response.status_code == 200
        assert expected in response.text


def test_filter_search_and_not_found_states() -> None:
    assert "Superman" in client.get("/movies?q=superman").text
    assert "No movies found" in client.get("/movies?q=definitely-missing").text
    assert "AMC Empire 25" in client.get("/movie-theatres?q=empire").text
    assert client.get("/movies/definitely-missing").status_code == 404


def test_favorite_persists_in_session() -> None:
    browser = TestClient(app)
    browser.get("/")
    result = browser.post("/api/favorites", json={"movie_slug": "superman"})
    assert result.status_code == 200
    assert result.json()["saved"] is True
    assert "saved" in browser.get("/movies/superman").text
    result = browser.post("/api/favorites", json={"movie_slug": "superman"})
    assert result.json()["saved"] is False


def test_login_and_account() -> None:
    browser = TestClient(app)
    browser.get("/login")
    result = browser.post(
        "/api/login",
        json={"email": "guest@example.com", "password": "demo12345"},
    )
    assert result.status_code == 200
    assert result.json()["ok"] is True
    account = browser.get("/account")
    assert account.status_code == 200
    assert "Hello, AMC Guest" in account.text


def test_local_sandbox_order_outcomes() -> None:
    browser = TestClient(app)
    browser.get("/checkout/superman")
    payload = {
        "movie_slug": "superman",
        "theatre_slug": "amc-empire-25",
        "showtime": "7:00 PM",
        "seats": ["A1", "A2"],
    }
    declined = browser.post(
        "/api/orders", json={**payload, "scenario": "sandbox-declined"}
    )
    assert declined.status_code == 402
    approved = browser.post(
        "/api/orders", json={**payload, "scenario": "sandbox-approved"}
    )
    assert approved.status_code == 200
    assert approved.json()["order_id"].startswith("AMC-")
    assert approved.json()["total"] == "$33.97"
    signed_in = browser.post(
        "/api/login",
        json={"email": "guest@example.com", "password": "demo12345"},
    )
    assert signed_in.status_code == 200
    account = browser.get("/account")
    assert approved.json()["order_id"][-8:] in account.text
    assert "Seats A1, A2" in account.text


def test_unknown_route() -> None:
    response = client.get("/not-in-scope")
    assert response.status_code == 404
    assert "We could not find that page" in response.text
    assert client.get("/favicon.ico").status_code == 200
