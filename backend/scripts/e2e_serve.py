"""Start the app on the e2e seed data (for looking at the UI by hand): fresh users, port 8766.

    python scripts/e2e_serve.py      # sign in as admin@example.com with the password printed at the start
"""
import os
import secrets
import subprocess
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PW = os.environ.get("E2E_PASSWORD") or secrets.token_urlsafe(12)       # a new one each start unless given
env = dict(os.environ, FIDELITY_DB_URL="sqlite+aiosqlite:///./.e2e/e2e.db", E2E_PASSWORD=PW,
           FIDELITY_SECRET=os.environ.get("E2E_SECRET") or secrets.token_hex(32), QA_SERVER_PORT="8766", PYTHONUTF8="1")
print(f"test users: admin@example.com, reviewer@example.com, viewer@example.com; password for this start: {PW}", flush=True)
subprocess.run([sys.executable, "scripts/e2e_seed.py"], cwd=BACKEND, env=env, check=True)
sys.exit(subprocess.call([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8766"], cwd=BACKEND, env=env))
