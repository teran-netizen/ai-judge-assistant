"""Add ocr_status to case_files

Tracks per-file OCR result: pending/ok/error for instant feedback.

Revision ID: 014
Revises: 013
"""

from alembic import op
import sqlalchemy as sa

revision = '015'
down_revision = '014'


def upgrade():
    op.add_column('case_files', sa.Column('ocr_status', sa.String(10), nullable=True))
    op.add_column('case_files', sa.Column('ocr_chars', sa.Integer, nullable=True))


def downgrade():
    op.drop_column('case_files', 'ocr_chars')
    op.drop_column('case_files', 'ocr_status')
