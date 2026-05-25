"""add last_activity to users

Revision ID: 017
Revises: 016
"""
from alembic import op
import sqlalchemy as sa

revision = '017'
down_revision = '016'

def upgrade():
    op.add_column('users', sa.Column('last_activity', sa.DateTime(), nullable=True))

def downgrade():
    op.drop_column('users', 'last_activity')
