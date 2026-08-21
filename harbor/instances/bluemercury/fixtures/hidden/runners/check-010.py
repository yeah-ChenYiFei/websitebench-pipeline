#!/usr/bin/python3
import json
import os
from pathlib import Path
root = Path(os.environ['WEBSITEBENCH_CANDIDATE_ROOT']).resolve()
text='\n'.join((root / 'clone' / p).read_text(errors='ignore') for p in ['app.py','static/site.css']); assert 'https://' not in text and 'http://' not in text
