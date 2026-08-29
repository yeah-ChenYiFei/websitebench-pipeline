import sys
from pathlib import Path

CLONE_ROOT = Path(__file__).resolve().parents[1]
if str(CLONE_ROOT) not in sys.path:
    sys.path.insert(0, str(CLONE_ROOT))
