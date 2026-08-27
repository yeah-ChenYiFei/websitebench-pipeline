import os
import sys
import tempfile
from pathlib import Path

CLONE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLONE))
_TEST_DATA = Path(tempfile.mkdtemp(prefix="websitebench-crunchyroll-tests-"))
os.environ["WEBSITEBENCH_SITE_BACKEND_RUNTIME"] = str(
    CLONE.parent / "backend" / "runtime.json"
)
os.environ["WEBSITEBENCH_SITE_BACKEND_DATABASE"] = str(
    _TEST_DATA / "crunchyroll.sqlite3"
)
os.environ["WEBSITEBENCH_LOCAL_HTTP_COOKIE"] = "1"
