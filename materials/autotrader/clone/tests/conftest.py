import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault(
    "WEBSITEBENCH_SITE_BACKEND_DATABASE",
    str(Path(tempfile.mkdtemp(prefix="autotrader-tests-")) / "autotrader.sqlite3"),
)
