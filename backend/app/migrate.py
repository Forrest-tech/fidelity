import os

from alembic import command
from alembic.config import Config

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def upgrade():
    cfg = Config(os.path.join(BACKEND, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND, "migrations"))
    command.upgrade(cfg, "head")
