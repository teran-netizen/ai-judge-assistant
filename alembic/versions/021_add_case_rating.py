"""add rating and review_text to cases

Revision ID: 021
Revises: 020
Create Date: 2026-03-22
"""
from alembic import op
import sqlalchemy as sa

revision = '021'
down_revision = '020'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('cases', sa.Column('rating', sa.SmallInteger(), nullable=True))
    op.add_column('cases', sa.Column('review_text', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('cases', 'review_text')
    op.drop_column('cases', 'rating')
