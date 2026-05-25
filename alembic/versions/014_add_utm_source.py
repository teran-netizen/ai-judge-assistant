"""Add utm_source to users table

Revision ID: 014
Revises: 013
"""

from alembic import op
import sqlalchemy as sa

revision = '014'
down_revision = '013'


def upgrade():
    op.add_column('users', sa.Column('utm_source', sa.String(100), nullable=True))


def downgrade():
    op.drop_column('users', 'utm_source')
