#!/usr/bin/python3
import json
import os
from pathlib import Path
root = Path(os.environ['WEBSITEBENCH_CANDIDATE_ROOT']).resolve()
assert json.loads((root / 'backend' / 'runtime.json').read_text())['payments']['stripe_test'] is None
