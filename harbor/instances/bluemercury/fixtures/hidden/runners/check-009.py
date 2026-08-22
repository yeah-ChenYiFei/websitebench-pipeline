#!/usr/bin/python3
import json
import os
from pathlib import Path
root = Path(os.environ['WEBSITEBENCH_CANDIDATE_ROOT']).resolve()
assert len(json.loads((root / 'clone' / 'static' / 'catalog-image-map.json').read_text())) == 249
