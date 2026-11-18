from alembic import context
from backend.config import Settings
from backend.db import database
from backend.models import Base

engine, _ = database(Settings().database_url)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
