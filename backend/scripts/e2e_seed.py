"""Create the three test users for the browser end-to-end tests (fresh database each run).

Run from backend/ with FIDELITY_DB_URL pointing at a throw-away database file.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The password comes from the run (playwright.config.ts or e2e_serve.py make a random one): none is kept in the code.
PW = os.environ.get("E2E_PASSWORD") or sys.exit("E2E_PASSWORD is not set (playwright.config.ts or scripts/e2e_serve.py set it)")

# fresh throw-away database every run
os.makedirs(".e2e", exist_ok=True)
for _f in (".e2e/e2e.db", ".e2e/e2e.db-wal", ".e2e/e2e.db-shm"):
    if os.path.exists(_f):
        os.remove(_f)


async def main():
    from app.migrate import upgrade
    upgrade()
    from fastapi_users.db import SQLAlchemyUserDatabase

    from app.auth.models import Role, User
    from app.auth.schemas import UserCreate
    from app.auth.users import UserManager
    from app.orm import SessionLocal

    async with SessionLocal() as s:
        mgr = UserManager(SQLAlchemyUserDatabase(s, User))
        for role in Role:
            try:
                await mgr.create(UserCreate(email=f"{role.value}@example.com", password=PW, role=role, is_verified=True))
            except Exception:
                pass  # already exists
    # a local source folder that exists on this machine (the shipped default points at another computer)
    from app import config
    lib = os.path.abspath(os.path.join(".e2e", "library"))
    os.makedirs(lib, exist_ok=True)
    config.upsert_source({"id": "e2e", "name": "E2E library", "src_root": lib,
                          "md_root": os.path.abspath(os.path.join(".e2e", "md"))})
    print("e2e users and source ready")


if __name__ == "__main__":
    asyncio.run(main())
