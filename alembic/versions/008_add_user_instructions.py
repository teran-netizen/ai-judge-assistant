"""Add user_instructions column to cases

Allows judges to provide AI instructions like
"Проанализируй 10 сторон, вынеси отказ в пользу Иванова".

Revision ID: 008
Revises: 007
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("user_instructions", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("cases", "user_instructions")
