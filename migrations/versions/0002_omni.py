"""Manual Omni positions and explicit event provenance; existing ledgers stay intact."""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('legs', sa.Column('source', sa.String(), nullable=False, server_default='exchange'))
    op.add_column('legs', sa.Column('quote_asset', sa.String(), nullable=False, server_default='USDT'))
    op.add_column('legs', sa.Column('manual_revision', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('events', sa.Column('source', sa.String(), nullable=False, server_default='exchange'))


def downgrade():
    raise RuntimeError('Ledger downgrade is disabled; restore a verified backup instead.')
