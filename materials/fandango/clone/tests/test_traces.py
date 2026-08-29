from fastapi.testclient import TestClient

from app import app
from backend.store import (
    SEATS_PER_ROW,
    SHOWTIMES,
    THEATER_BY_ID,
    featured_thriller,
    reset,
    sold_seats,
    upcoming_friday,
)

# The ClawBench trace targets whichever thriller the captured catalog is showing
# at Regal Union Square, so these tests derive it instead of pinning a title.
THRILLER = featured_thriller()
UNION_SQUARE = THEATER_BY_ID["regal-union-square"]["name"]
_SLOT, _FORMAT, _ = SHOWTIMES[THRILLER["id"]]["regal-union-square"][2]
PRIME_SHOWTIME = f"{_SLOT}-{_FORMAT.lower().replace(' ', '-')}"


def client():
    reset()
    return TestClient(app)


def free_block(theater_id: str, showtime_id: str, count: int, rows=("D", "E", "F")) -> list[str]:
    """Adjacent unsold seats for a showtime; sold seats are seeded per showtime."""
    taken = set(sold_seats(theater_id, showtime_id))
    for row in rows:
        for start in range(1, SEATS_PER_ROW - count + 2):
            block = [f"{row}{start + offset}" for offset in range(count)]
            if not taken.intersection(block):
                return block
    raise AssertionError("no adjacent free block")


def test_routes_search_filters_and_404():
    c = client()
    assert c.get("/").status_code == 200
    assert c.get("/movies").status_code == 200
    results = c.get("/api/movies", params={"q": THRILLER["title"], "sort": "rating"}).json()
    assert THRILLER["title"] in [movie["title"] for movie in results["movies"]]
    thrillers = c.get("/api/movies", params={"genre": "Suspense/Thriller"}).json()["movies"]
    assert thrillers and all("Suspense/Thriller" in m["genres"] for m in thrillers)
    assert c.get("/api/movies", params={"q": "definitely absent"}).json()["movies"] == []
    missing = c.get("/this-route-does-not-exist")
    assert missing.status_code == 404
    assert "default-src 'self'" in missing.headers["content-security-policy"]


def test_typical_task_three_adjacent_center_seats_and_confirmation():
    c = client()
    payload = c.get(f"/api/movies/{THRILLER['id']}").json()
    movie = payload["movie"]
    theater = next(t for t in movie["theaters"] if t["id"] == "regal-union-square")
    showing = next(s for s in theater["showtimes"] if s["time"] == "7:30 PM")
    assert "Suspense/Thriller" in movie["genres"]
    assert showing["minutes"] > 18 * 60
    chosen_date = payload["date"]
    assert chosen_date == upcoming_friday()
    assert c.post("/api/selection/showtime", json={"movie_id": THRILLER["id"], "theater_id": theater["id"], "showtime_id": showing["id"], "date": chosen_date}).status_code == 201
    assert c.post("/api/selection/tickets", json={"adults": 3, "children": 0, "seniors": 0}).status_code == 200
    block = free_block(theater["id"], showing["id"], 3)
    seats = c.post("/api/selection/seats", json={"seats": block})
    assert seats.status_code == 200
    review = c.post("/api/checkout/review", json={"email": "trace@example.test", "postal_code": "10003"}).json()
    assert review["movie"] == THRILLER["title"]
    assert review["theater"] == UNION_SQUARE
    assert review["ticket_count"] == 3
    assert review["seats"] == block
    assert review["payment_adapter"] == "local-sandbox"
    confirmed = c.post("/api/checkout/confirm", json={}).json()
    assert "Local Simulation" in confirmed["status"]
    assert confirmed["seats"] == block


def test_seats_are_normalised_and_sold_seats_are_rejected():
    c = client()
    date = upcoming_friday()
    c.post("/api/selection/showtime", json={"movie_id": THRILLER["id"], "theater_id": "regal-union-square", "showtime_id": PRIME_SHOWTIME, "date": date})
    c.post("/api/selection/tickets", json={"adults": 3})
    block = free_block("regal-union-square", PRIME_SHOWTIME, 3)
    # seats submitted out of order come back sorted, so summaries read left to right
    scrambled = [block[2], block[0], block[1]]
    assert c.post("/api/selection/seats", json={"seats": scrambled}).json()["seats"] == block
    taken = sold_seats("regal-union-square", PRIME_SHOWTIME)[0]
    row, number = taken[0], int(taken[1:])
    neighbours = [f"{row}{number + offset}" for offset in (1, 2)]
    rejected = c.post("/api/selection/seats", json={"seats": [taken, *neighbours]})
    assert rejected.status_code == 422
    assert "already sold" in rejected.json()["error"]


def test_date_window_is_enforced():
    c = client()
    stale = c.post("/api/selection/showtime", json={"movie_id": THRILLER["id"], "theater_id": "regal-union-square", "showtime_id": PRIME_SHOWTIME, "date": "2020-01-01"})
    assert stale.status_code == 422
    assert "next two weeks" in stale.json()["error"]


def test_theater_directory_lists_each_theater_lineup():
    c = client()
    directory = c.get("/api/theaters").json()
    names = {row["name"] for row in directory["theaters"]}
    assert {UNION_SQUARE, "AMC Village 7", "Regal Essex Crossing & RPX", "AMC Kips Bay 15"} <= names
    for theater in directory["theaters"]:
        assert theater["movies"], f"{theater['name']} has no lineup"
        assert all(movie["showtimes"] for movie in theater["movies"])
    lineups = {theater["id"]: {movie["id"] for movie in theater["movies"]} for theater in directory["theaters"]}
    assert lineups["regal-union-square"] != lineups["amc-kips-bay-15"]


def test_seat_and_required_field_validation():
    c = client()
    c.post("/api/selection/showtime", json={"movie_id": THRILLER["id"], "theater_id": "regal-union-square", "showtime_id": PRIME_SHOWTIME, "date": upcoming_friday()})
    c.post("/api/selection/tickets", json={"adults": 3})
    block = free_block("regal-union-square", PRIME_SHOWTIME, 3)
    row = block[0][0]
    assert c.post("/api/selection/seats", json={"seats": [f"{row}2", f"{row}4", "H12"]}).status_code == 422
    assert c.post("/api/selection/seats", json={"seats": block[:2]}).status_code == 422
    assert c.post("/api/checkout/review", json={"email": "", "postal_code": ""}).status_code == 422


def test_favorite_auth_recovery_and_booking_management():
    c = client()
    assert c.post(f"/api/favorites/{THRILLER['id']}").json()["saved"] is True
    registration = c.post("/api/auth/register", json={"display_name": "Trace User", "email": "trace@example.test", "password": "long-password"})
    assert registration.status_code == 201
    assert c.post("/api/auth/logout").status_code == 200
    assert c.post("/api/auth/login", json={"email": "trace@example.test", "password": "wrong"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": "trace@example.test", "password": "long-password"}).status_code == 200
    recovery = c.post("/api/auth/recovery-preview", json={"email": "trace@example.test"}).json()
    assert recovery["sent"] is False
    seed = c.get("/api/bootstrap").json()["bookings"][0]
    booking_id = seed["id"]
    for action in ("reschedule", "contact", "review"):
        response = c.post(f"/api/bookings/{booking_id}/{action}", json={"value": "Trace note"})
        assert response.status_code == 200
    assert c.post(f"/api/bookings/{booking_id}/book-again", json={}).status_code == 200
    assert c.post(f"/api/bookings/{booking_id}/cancel", json={}).json()["booking"]["status"] == "Cancelled"


def test_actor_state_is_isolated():
    first, second = client(), TestClient(app)
    first.post(f"/api/favorites/{THRILLER['id']}")
    assert THRILLER["id"] in first.get("/api/bootstrap").json()["favorites"]
    assert THRILLER["id"] not in second.get("/api/bootstrap").json()["favorites"]
