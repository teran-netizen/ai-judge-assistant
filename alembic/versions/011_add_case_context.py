"""Add case_context JSONB column to cases table

Stores accumulated document context for the Accumulator pipeline:
- documents: list of extracted document data
- summary: running summary of the case
- doc_count: number of processed documents

Revision ID: 010
Revises: 009
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '011'
down_revision = '010'


def upgrade():
    op.add_column('cases', sa.Column('case_context', JSONB, server_default='{}', nullable=True))


def downgrade():
    op.drop_column('cases', 'case_context')
