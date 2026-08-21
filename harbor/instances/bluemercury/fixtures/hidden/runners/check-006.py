#!/usr/bin/python3
import json
import os
from pathlib import Path
root = Path(os.environ['WEBSITEBENCH_CANDIDATE_ROOT']).resolve()
assert [x['id'] for x in json.loads((root / 'backend' / 'runtime.json').read_text())['payments']['local_sandbox']['scenarios']] == ['sandbox-approved', 'sandbox-declined', 'sandbox-retry']
