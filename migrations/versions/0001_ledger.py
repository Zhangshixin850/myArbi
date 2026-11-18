"""Initial SQLite ledger schema, frozen independently of future model changes."""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

STATEMENTS = [
  "\nCREATE TABLE audit (\n\tid INTEGER NOT NULL, \n\tcard_id VARCHAR NOT NULL, \n\ttime BIGINT NOT NULL, \n\tmessage VARCHAR NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
  "\nCREATE TABLE cards (\n\tid VARCHAR NOT NULL, \n\tbase VARCHAR NOT NULL, \n\tstatus VARCHAR NOT NULL, \n\tstarted_at BIGINT NOT NULL, \n\tclosed_at BIGINT, \n\tzero_since BIGINT, \n\trevised_at BIGINT NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n",
  "\nCREATE TABLE cursors (\n\t\"key\" VARCHAR NOT NULL, \n\tthrough BIGINT NOT NULL, \n\taudited_at BIGINT NOT NULL, \n\tPRIMARY KEY (\"key\")\n)\n\n",
  "\nCREATE TABLE legs (\n\tid INTEGER NOT NULL, \n\tcard_id VARCHAR NOT NULL, \n\taccount VARCHAR NOT NULL, \n\tproduct VARCHAR NOT NULL, \n\tsymbol VARCHAR NOT NULL, \n\tdirection VARCHAR NOT NULL, \n\treservation VARCHAR NOT NULL, \n\treserved BOOLEAN NOT NULL, \n\tbaseline JSON NOT NULL, \n\tsnapshot JSON NOT NULL, \n\tsynced_at BIGINT, \n\terror TEXT, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(card_id) REFERENCES cards (id)\n)\n\n",
  "\nCREATE TABLE events (\n\tid INTEGER NOT NULL, \n\tleg_id INTEGER NOT NULL, \n\taccount VARCHAR NOT NULL, \n\tproduct VARCHAR NOT NULL, \n\tsymbol VARCHAR NOT NULL, \n\tkind VARCHAR NOT NULL, \n\texternal_id VARCHAR NOT NULL, \n\ttime BIGINT NOT NULL, \n\tdata JSON NOT NULL, \n\traw JSON NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (account, product, symbol, kind, external_id), \n\tFOREIGN KEY(leg_id) REFERENCES legs (id)\n)\n\n",
  "\nCREATE TABLE snapshots (\n\tid INTEGER NOT NULL, \n\tleg_id INTEGER NOT NULL, \n\ttime BIGINT NOT NULL, \n\tdata JSON NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(leg_id) REFERENCES legs (id)\n)\n\n",
  "CREATE UNIQUE INDEX uq_active_leg ON legs (account, product, symbol, reservation) WHERE reserved = 1",
  "CREATE INDEX ix_snapshots_time ON snapshots (time)"
]


def upgrade():
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade():
    raise RuntimeError("Ledger downgrade is disabled; restore a verified backup instead.")
