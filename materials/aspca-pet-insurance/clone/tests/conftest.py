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
_DB_DIR = Path(tempfile.mkdtemp(prefix="aspca-clone-tests-"))
os.environ["WEBSITEBENCH_SITE_BACKEND_DATABASE"] = str(
    _DB_DIR / "aspca-pet-insurance.sqlite3"
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
from backend import quotes_db  # noqa: E402


@pytest.fixture()
def client():
    quotes_db.reset()
    with TestClient(app_module.app, base_url="http://testserver") as test_client:
        yield test_client
    quotes_db.reset()
