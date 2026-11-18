"""Start the app on the e2e seed data (for looking at the UI by hand): fresh users, port 8766.

    python scripts/e2e_serve.py      # sign in as admin@example.com / e2e-password-123
"""
import os
import subprocess
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env = dict(os.environ, FIDELITY_DB_URL="sqlite+aiosqlite:///./.e2e/e2e.db",
           FIDELITY_SECRET="e2e-secret-e2e-secret-e2e-secret-1234", QA_SERVER_PORT="8766", PYTHONUTF8="1")
subprocess.run([sys.executable, "scripts/e2e_seed.py"], cwd=BACKEND, env=env, check=True)
sys.exit(subprocess.call([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8766"], cwd=BACKEND, env=env))
