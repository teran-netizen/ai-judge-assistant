"""add city and timezone to users

Revision ID: 020
Revises: 019
Create Date: 2026-03-22
"""
from alembic import op
import sqlalchemy as sa

revision = '020'
down_revision = '019'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('city', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('timezone', sa.String(50), nullable=True))


def downgrade():
    op.drop_column('users', 'timezone')
    op.drop_column('users', 'city')
