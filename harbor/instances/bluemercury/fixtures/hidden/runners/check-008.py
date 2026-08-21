#!/usr/bin/python3
import json
import os
from pathlib import Path
root = Path(os.environ['WEBSITEBENCH_CANDIDATE_ROOT']).resolve()
products=json.loads((root / 'clone' / 'static' / 'products.json').read_text())['products']; assert len({x['handle'] for x in products}) == 250
