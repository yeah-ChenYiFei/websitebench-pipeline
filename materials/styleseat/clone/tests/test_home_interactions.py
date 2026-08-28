"""Home marketing controls are wired through clone-owned browser code."""

from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def test_home_loads_local_marketing_controller():
    response = client.get("/m/")
    assert response.status_code == 200
    assert '<script src="/static/home-actions.js" defer></script>' in response.text


def test_every_home_marketing_destination_is_local_and_reachable():
    for path in (
        "/m/pro-signup",
        "/join/run-your-business",
        "/join/grow-your-business",
        "/join/manage-your-business",
        "/join/elevate-your-client-experience",
        "/m/search/new-york-city-ny/professionals",
    ):
        response = client.get(path, follow_redirects=True)
        assert response.status_code == 200, path


def test_every_home_city_service_link_is_a_real_search_page():
    cities = (
        "dallas-tx", "chicago-il", "atlanta-ga", "washington-dc",
        "los-angeles-ca", "houston-tx", "detroit-mi", "charlotte-nc",
        "columbus-oh", "newport-news-va",
    )
    services = ("braids", "natural-hair", "haircut", "weaves", "barber")
    for city in cities:
        for service in services:
            path = f"/m/search/{city}/{service}"
            response = client.get(path)
            assert response.status_code == 200, path
            assert "Beyond captured scope" not in response.text, path
            assert 'data-testid="searchResultsList"' in response.text, path
            assert f'data-clone-city="{city}"' in response.text, path
            assert f'data-clone-service="{service}"' in response.text, path


def test_home_find_professionals_entry_opens_search_results():
    response = client.get("/search", follow_redirects=True)
    assert response.status_code == 200
    assert "Beyond captured scope" not in response.text
    assert 'data-testid="searchResultsList"' in response.text

