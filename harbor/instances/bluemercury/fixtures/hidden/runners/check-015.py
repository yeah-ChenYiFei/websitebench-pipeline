#!/usr/bin/python3
import json
import os
from pathlib import Path
root = Path(os.environ['WEBSITEBENCH_CANDIDATE_ROOT']).resolve()
assert (root / 'compile.sh').is_file() and os.access(root / 'compile.sh', os.X_OK)
