from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


CLONE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLONE_ROOT))

_data_root = Path(tempfile.mkdtemp(prefix="songkick-test-data-"))
os.environ["WEBSITEBENCH_SITE_BACKEND_DATABASE"] = str(
    _data_root / "songkick.sqlite3"
)

