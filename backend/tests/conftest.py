import os
import sys

# make `app` and legacy `scripts` importable
BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (BACKEND, os.path.join(BACKEND, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)
