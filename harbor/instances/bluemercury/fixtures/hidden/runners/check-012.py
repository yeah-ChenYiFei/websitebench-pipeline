#!/usr/bin/python3
import json
import os
from pathlib import Path
root = Path(os.environ['WEBSITEBENCH_CANDIDATE_ROOT']).resolve()
assert (root / 'clone' / 'backend' / 'site_backend_integration.py').is_file()
