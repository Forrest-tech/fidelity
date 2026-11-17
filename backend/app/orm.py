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


# NullPool for SQLite: one short-lived connection per request, safe across event loops.
engine = create_async_engine(DB_URL, **({"poolclass": NullPool} if DB_URL.startswith("sqlite") else {}))
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session():
    async with SessionLocal() as session:
        yield session


async def create_all():
    """Used by tests and first-run; production schema is managed by Alembic."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
