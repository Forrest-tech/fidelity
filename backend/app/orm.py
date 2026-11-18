"""SQLAlchemy data layer (SQLite now, PostgreSQL later via FIDELITY_DB_URL).

Separate from the legacy `trust.db` (app/db.py), which is migrated in Phase 2.
"""
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase

from . import config

DB_URL = os.environ.get(
    "FIDELITY_DB_URL",
    "sqlite+aiosqlite:///" + os.path.join(config.DATA_DIR, "fidelity.db").replace("\\", "/"),
)


class Base(DeclarativeBase):
    pass


# NullPool: one short-lived connection per request. Safe across event loops (asyncpg connections are
# bound to the loop that opened them) and ample for an office-sized user base. Set FIDELITY_DB_POOL=1
# on a busy server to use SQLAlchemy's default pool instead.
_pool = {} if os.environ.get("FIDELITY_DB_POOL") == "1" else {"poolclass": NullPool}
engine = create_async_engine(DB_URL, **_pool)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session():
    async with SessionLocal() as session:
        yield session


async def create_all():
    """Used by tests and first-run; production schema is managed by Alembic."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
