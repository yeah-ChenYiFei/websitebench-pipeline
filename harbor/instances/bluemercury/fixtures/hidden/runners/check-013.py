#!/usr/bin/python3
import json
import os
from pathlib import Path
root = Path(os.environ['WEBSITEBENCH_CANDIDATE_ROOT']).resolve()
assert '/__websitebench/health' in (root / 'clone' / 'app.py').read_text()
