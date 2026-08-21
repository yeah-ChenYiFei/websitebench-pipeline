#!/usr/bin/python3
import json
import os
from pathlib import Path
root = Path(os.environ['WEBSITEBENCH_CANDIDATE_ROOT']).resolve()
assert '@media' in (root / 'clone' / 'static' / 'site.css').read_text()
