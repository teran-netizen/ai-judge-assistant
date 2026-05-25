"""Add chat_history JSONB column to cases table.

Revision ID: 010
Revises: 009
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '010'
down_revision = '009'


def upgrade():
    op.add_column('cases', sa.Column('chat_history', JSONB, server_default='[]', nullable=True))


def downgrade():
    op.drop_column('cases', 'chat_history')
