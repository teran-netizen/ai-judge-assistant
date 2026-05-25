"""Add resumable upload columns to case_files + ocr_text

Revision ID: 027
Revises: 026
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '027'
down_revision = '026'


def upgrade():
    # Upload session link
    op.add_column('case_files', sa.Column('upload_session_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_case_files_upload_session', 'case_files', 'case_upload_sessions', ['upload_session_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_case_files_upload_session_id', 'case_files', ['upload_session_id'])

    # Client file identity (for resume/dedup)
    op.add_column('case_files', sa.Column('client_file_id', sa.String(128), nullable=True))
    op.create_index('ix_case_files_client_file_id', 'case_files', ['client_file_id'])

    # Original filename (may differ from stored filename)
    op.add_column('case_files', sa.Column('original_filename', sa.Text(), nullable=True))

    # Exact file size from client
    op.add_column('case_files', sa.Column('size_bytes', sa.BigInteger(), nullable=True))

    # Browser File.lastModified
    op.add_column('case_files', sa.Column('client_last_modified', sa.BigInteger(), nullable=True))

    # MIME type from browser
    op.add_column('case_files', sa.Column('mime_type', sa.String(255), nullable=True))

    # Selection order in upload
    op.add_column('case_files', sa.Column('upload_order', sa.Integer(), nullable=True))

    # Batch ID for chunk tracking
    op.add_column('case_files', sa.Column('upload_batch_id', sa.String(128), nullable=True))

    # OCR result text — critical for checkpoint
    op.add_column('case_files', sa.Column('ocr_text', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('case_files', 'ocr_text')
    op.drop_column('case_files', 'upload_batch_id')
    op.drop_column('case_files', 'upload_order')
    op.drop_column('case_files', 'mime_type')
    op.drop_column('case_files', 'client_last_modified')
    op.drop_column('case_files', 'size_bytes')
    op.drop_column('case_files', 'original_filename')
    op.drop_index('ix_case_files_client_file_id')
    op.drop_column('case_files', 'client_file_id')
    op.drop_index('ix_case_files_upload_session_id')
    op.drop_constraint('fk_case_files_upload_session', 'case_files', type_='foreignkey')
    op.drop_column('case_files', 'upload_session_id')
