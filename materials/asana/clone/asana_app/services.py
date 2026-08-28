"""Process-wide backend/auth services opened through the generated seam."""

from __future__ import annotations

import sys
from pathlib import Path

_CLONE_ROOT = Path(__file__).resolve().parents[1]
if str(_CLONE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CLONE_ROOT))

import os  # noqa: E402

# Under the isolated diagnostic runner the candidate root is read-only and a
# private writable directory is provided; place the site database there.
if not os.environ.get("WEBSITEBENCH_SITE_BACKEND_DATABASE"):
    _data_dir = os.environ.get("WEBSITEBENCH_DATA_DIR")
    if _data_dir:
        os.environ["WEBSITEBENCH_SITE_BACKEND_DATABASE"] = str(
            Path(_data_dir) / "asana.sqlite3"
        )

from backend.site_backend_integration import open_site_services  # noqa: E402

from . import db as _db  # noqa: E402


class _Services:
    def __init__(self) -> None:
        self.backend, self.auth = open_site_services()
        self.cookie_name = self.backend.session_cookie["name"]
        with self.auth.connect() as connection:
            _db.ensure_schema(connection)
            connection.commit()


SERVICES = _Services()
