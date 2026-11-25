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
# Bot protection is switched on by the tests that check it (test_login_security.py); the rest sign in directly.
os.environ.setdefault("FIDELITY_CAPTCHA", "off")
os.environ.setdefault("FIDELITY_VISUAL_SAMPLES", "0")  # the visual check has its own tests
os.environ.setdefault("FIDELITY_GLOSSARY", os.path.join(_TMP, "no-glossary.json"))  # tests pass their own
os.environ.setdefault("FIDELITY_OCR_SELECTION", os.path.join(_TMP, "no-ocr-selection.json"))
os.environ.setdefault("FIDELITY_FORMULA_APPROVALS", os.path.join(_TMP, "no-formula-approvals.json"))
os.environ.setdefault("FIDELITY_GOOGLE_AUTH", os.path.join(_TMP, "google_auth.json"))
os.environ.setdefault("FIDELITY_OCR_PROTECTED", "0")   # never the owner's live switch in data/app_settings.json

# The job/review database and the cache are module paths, not environment settings: point them at the
# test folder too, so a test can never touch the real data/trust.db of the machine running the suite
# (found in testing: job-table tests had cleaned up real Dropbox-sync history rows).
from app import config as _config  # noqa: E402
_config.TRUST_DB = os.path.join(_TMP, "trust.db")
_config.CACHE_DIR = os.path.join(_TMP, "cache")
os.makedirs(_config.CACHE_DIR, exist_ok=True)
# defaults for new rooms live in the data folder: keep the tests' own copy
from app.api import appsettings as _appsettings  # noqa: E402
_appsettings.PATH = os.path.join(_TMP, "app_settings.json")
# the mail server and the human-check provider are the owner's live settings too (found 2026-11-23: once SMTP was
# set up on the server, sign-up tests on that machine switched to "confirm your e-mail first")
from app.ops import mail as _mail  # noqa: E402
_mail.PATH = os.path.join(_TMP, "email_settings.json")
from app.auth import captcha as _captcha  # noqa: E402
_captcha._settings_path = lambda: os.path.join(_TMP, "captcha_settings.json")
# and the Dropbox authorisation: a test must never reach the owner's Dropbox (rooms resolve shared links, S-4)
from app.distill import dropbox_io as _dropbox_io  # noqa: E402
_dropbox_io.AUTH_PATH = os.path.join(_TMP, "dropbox_auth.json")


def _reset_postgres():
    """Running the suite on PostgreSQL (Phase 8): start from an empty schema. Refuses any database
    whose name does not end in _test, so a real database can never be wiped by the tests."""
    urls = {u for u in (os.environ.get("FIDELITY_DB_URL", ""), os.environ.get("FIDELITY_TRUST_URL", ""))
            if u.startswith("postgres")}
    for url in urls:
        plain = url.replace("+asyncpg", "").replace("+psycopg", "")
        if not plain.rsplit("/", 1)[-1].split("?")[0].endswith("_test"):
            raise RuntimeError("refusing to run tests on a PostgreSQL database not named *_test: " + plain.rsplit("@", 1)[-1])
        import psycopg
        with psycopg.connect(plain, autocommit=True) as con:
            con.execute("DROP SCHEMA public CASCADE")
            con.execute("CREATE SCHEMA public")


_reset_postgres()
