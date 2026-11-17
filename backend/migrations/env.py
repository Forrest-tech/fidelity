from alembic import context
from sqlalchemy import create_engine

from app import orm
from app.auth import models  # noqa: F401  (register tables)

config = context.config
# Alembic runs synchronously; strip the async driver from the URL.
URL = orm.DB_URL.replace("+aiosqlite", "").replace("+asyncpg", "")
target_metadata = orm.Base.metadata


def run_migrations_online():
    engine = create_engine(URL)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
