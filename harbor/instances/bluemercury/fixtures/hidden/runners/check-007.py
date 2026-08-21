#!/usr/bin/python3
import json
import os
from pathlib import Path
root = Path(os.environ['WEBSITEBENCH_CANDIDATE_ROOT']).resolve()
assert len(json.loads((root / 'clone' / 'static' / 'products.json').read_text())['products']) == 250
