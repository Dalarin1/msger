import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # chat/
sys.path.insert(0, BASE_DIR)

from config import DB_PATH  # тот же путь, что видит приложение
from models import Base

target_metadata = Base.metadata
config = context.config

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
config.set_main_option("sqlalchemy.url", f"sqlite:///{DB_PATH}")


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()