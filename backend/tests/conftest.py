import os
import sys

# make `app` and legacy `scripts` importable
BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (BACKEND, os.path.join(BACKEND, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

# Isolated database for tests, set before any `app` import.
import tempfile
_TMP = tempfile.mkdtemp(prefix="fidelity-test-")
os.environ.setdefault("FIDELITY_DB_URL", "sqlite+aiosqlite:///" + os.path.join(_TMP, "t.db").replace("\\", "/"))
os.environ.setdefault("FIDELITY_SECRET", "test-secret-test-secret-test-secret-123")
os.environ.setdefault("FIDELITY_VISUAL_SAMPLES", "0")  # the visual check has its own tests
os.environ.setdefault("FIDELITY_GLOSSARY", os.path.join(_TMP, "no-glossary.json"))  # tests pass their own
