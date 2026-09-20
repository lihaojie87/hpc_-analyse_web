from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config,pool
from app.db.base import Base
from app.db.models import *
config=context.config
if config.config_file_name:
    try:
        fileConfig(config.config_file_name)
    except (KeyError, ValueError):
        # Continue with Alembic's minimal configuration when no formatter exists.
        config.attributes["logging_config_missing"] = True
# Alembic uses a synchronous URL while the application uses async drivers.
import os
async_url = os.getenv("HPC_DATABASE_URL", config.get_main_option("sqlalchemy.url"))
sync_url = async_url.replace("+aiosqlite", "").replace("+asyncpg", "+psycopg")
config.set_main_option("sqlalchemy.url", sync_url)
target_metadata=Base.metadata
def run_migrations_offline():
 context.configure(url=config.get_main_option("sqlalchemy.url"),target_metadata=target_metadata,literal_binds=True,compare_type=True)
 with context.begin_transaction(): context.run_migrations()
def run_migrations_online():
 connectable=engine_from_config(config.get_section(config.config_ini_section,{}),prefix="sqlalchemy.",poolclass=pool.NullPool)
 with connectable.connect() as connection:
  context.configure(connection=connection,target_metadata=target_metadata,compare_type=True)
  with context.begin_transaction(): context.run_migrations()
if context.is_offline_mode(): run_migrations_offline()
else: run_migrations_online()
