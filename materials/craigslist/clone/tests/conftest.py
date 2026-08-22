"""Test bootstrap: isolated database + clone dir on sys.path before app import."""

import os
import sys
import tempfile
from pathlib import Path

CLONE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLONE_DIR))

# Pin the whole test session into a throwaway sqlite file, set before the app
# module (and thus the backend seam) is imported. The filename must match the
# runtime contract's database filename.
_DB_DIR = Path(tempfile.mkdtemp(prefix="craigslist-clone-tests-"))
os.environ["WEBSITEBENCH_SITE_BACKEND_DATABASE"] = str(
    _DB_DIR / "craigslist.sqlite3"
)
os.environ["WEBSITEBENCH_SITE_BACKEND_RUNTIME"] = str(
    CLONE_DIR.parent / "backend" / "runtime.json"
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
from backend import craigslist_db  # noqa: E402

COOKIE_NAME = app_module._backend().session_cookie["name"]


def _login_into_jar(client: TestClient, email: str, password: str) -> str:
    """Log in and leave exactly one session cookie in the client jar."""
    client.cookies.clear()
    response = client.post(
        "/account/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303
    token = response.cookies.get(COOKIE_NAME)
    assert token
    client.cookies.clear()  # drop the auto-stored entry, keep one canonical
    client.cookies.set(COOKIE_NAME, token)
    return token


def _cookie_header(token: str) -> dict[str, str]:
    return {"Cookie": f"{COOKIE_NAME}={token}"}


@pytest.fixture()
def client():
    craigslist_db.reset()
    # HTTPS base so the __Host- Secure session cookie is transmitted.
    with TestClient(app_module.app, base_url="https://testserver") as test_client:
        yield test_client
    craigslist_db.reset()


@pytest.fixture()
def poster_session(client):
    """Log in as the seeded poster; the session lives in the client jar."""
    _login_into_jar(client, "poster@example.com", "Websitebench1!")
    return client


@pytest.fixture()
def seeker_session(client):
    _login_into_jar(client, "seeker@example.com", "Websitebench1!")
    return client


@pytest.fixture()
def login(client):
    """Factory: log in any account into the jar; returns the session token."""

    def _login(email: str, password: str) -> str:
        return _login_into_jar(client, email, password)

    return _login
