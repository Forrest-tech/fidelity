"""Create (or reset) a user:  python scripts/create_admin.py EMAIL [--role admin|reviewer|viewer]
The password is read from the FIDELITY_NEW_PASSWORD env var or prompted; it is never a CLI argument."""
import asyncio
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main(email, role):
    from app.migrate import upgrade
    upgrade()
    from app.auth.models import Role
    from app.auth.schemas import UserCreate
    from app.auth.users import UserManager
    from app.orm import SessionLocal
    from app.auth.models import User
    from fastapi_users.db import SQLAlchemyUserDatabase
    pw = os.environ.get("FIDELITY_NEW_PASSWORD") or getpass.getpass("Password: ")
    async with SessionLocal() as s:
        mgr = UserManager(SQLAlchemyUserDatabase(s, User))
        await mgr.create(UserCreate(email=email, password=pw, role=Role(role), is_verified=True))
    print("created", email, role)


if __name__ == "__main__":
    role = sys.argv[sys.argv.index("--role") + 1] if "--role" in sys.argv else "admin"
    asyncio.run(main(sys.argv[1], role))
