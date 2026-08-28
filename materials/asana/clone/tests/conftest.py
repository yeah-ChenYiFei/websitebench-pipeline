import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Isolate the test database before the app (and its service singleton) loads.
_TMP = tempfile.mkdtemp(prefix="asana-test-db-")
os.environ["WEBSITEBENCH_SITE_BACKEND_DATABASE"] = str(Path(_TMP) / "asana.sqlite3")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402  (env isolation must precede this import)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


_COUNTER = {"n": 0}


@pytest.fixture()
def auth_client() -> TestClient:
    """A client signed up and verified as a fresh account."""

    _COUNTER["n"] += 1
    email = f"user{_COUNTER['n']}@example.com"
    c = TestClient(app)
    r = c.post("/api/auth/signup", json={
        "name": f"Test User{_COUNTER['n']}", "email": email,
        "password": "password123"})
    assert r.status_code == 200, r.text
    mail = c.get("/api/auth/mail", params={"purpose": "registration"}).json()
    r = c.post("/api/auth/verify", json={"code": mail["verification_code"]})
    assert r.status_code == 200, r.text
    c.email = email
    return c
