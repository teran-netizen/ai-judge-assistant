"""add credited_at to transactions"""
from alembic import op
import sqlalchemy as sa

revision = '025'
down_revision = '024'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('transactions', sa.Column('credited_at', sa.DateTime(), nullable=True))

def downgrade():
    op.drop_column('transactions', 'credited_at')
