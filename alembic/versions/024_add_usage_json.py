"""add usage_json to case_runs

Revision ID: 024
Revises: 023
Create Date: 2026-03-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '024'
down_revision = '023'

def upgrade():
    op.add_column('case_runs', sa.Column('usage_json', JSONB, nullable=True))

def downgrade():
    op.drop_column('case_runs', 'usage_json')
