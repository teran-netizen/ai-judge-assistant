"""Create case_upload_sessions table

Revision ID: 026
Revises: 66821ad98869
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '026'
down_revision = '66821ad98869'


def upgrade():
    op.create_table(
        'case_upload_sessions',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('case_id', UUID(as_uuid=True), sa.ForeignKey('cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='pending'),
        sa.Column('expected_files_count', sa.Integer(), nullable=True),
        sa.Column('uploaded_files_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_bytes', sa.BigInteger(), nullable=True),
        sa.Column('uploaded_bytes', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('failed_files_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_activity_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('finalized_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('client_upload_token', sa.String(128), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_case_upload_sessions_case_id', 'case_upload_sessions', ['case_id'])
    op.create_index('ix_case_upload_sessions_user_id', 'case_upload_sessions', ['user_id'])
    op.create_index('ix_case_upload_sessions_status', 'case_upload_sessions', ['status'])
    op.create_index('ix_case_upload_sessions_last_activity_at', 'case_upload_sessions', ['last_activity_at'])
    op.create_index('ix_case_upload_sessions_case_status', 'case_upload_sessions', ['case_id', 'status'])


def downgrade():
    op.drop_index('ix_case_upload_sessions_case_status')
    op.drop_index('ix_case_upload_sessions_last_activity_at')
    op.drop_index('ix_case_upload_sessions_status')
    op.drop_index('ix_case_upload_sessions_user_id')
    op.drop_index('ix_case_upload_sessions_case_id')
    op.drop_table('case_upload_sessions')
