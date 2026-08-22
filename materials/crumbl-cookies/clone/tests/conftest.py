import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Every test run gets its own bound database so order/payment state never
# leaks between runs; the filename must match the runtime contract
# (crumbl-cookies.sqlite3).
_TEST_DATA_ROOT = Path(__file__).resolve().parents[1] / ".test-data"
_TEST_DATA_ROOT.mkdir(exist_ok=True)
os.environ.setdefault(
    "WEBSITEBENCH_SITE_BACKEND_DATABASE",
    str(_TEST_DATA_ROOT / "crumbl-cookies.sqlite3"),
)


@pytest.fixture(autouse=True)
def _reset_database():
    """Reset site + payment + mail state before every test.

    Payment flows are terminal after one attempt, so each test needs a
    clean database to remain independent and deterministic.
    """

    from backend import orders

    orders.reset()
    yield
