"""add case_runs table and stage field

Revision ID: 020
Revises: 019
Create Date: 2026-03-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '022'
down_revision = '021'
branch_labels = None
depends_on = None


def upgrade():
    # Add stage to cases
    op.add_column('cases', sa.Column('stage', sa.String(30), nullable=True))
    op.add_column('cases', sa.Column('last_progress_at', sa.DateTime(), nullable=True))

    # Create case_runs table
    op.create_table(
        'case_runs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('case_id', UUID(as_uuid=True), sa.ForeignKey('cases.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('pipeline_type', sa.String(30), nullable=False),  # full, generate_only, revalidate, rescue
        sa.Column('status', sa.String(20), nullable=False, server_default='queued'),  # queued, running, completed, failed, stale
        sa.Column('stage', sa.String(30), nullable=True),  # queued, ocr_running, context_building, context_ready, generating, validating, ready
        sa.Column('progress_pct', sa.Integer(), nullable=True),
        sa.Column('worker_id', sa.String(50), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('heartbeat_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('retry_count', sa.Integer(), server_default='0'),
        sa.Column('error_code', sa.String(50), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_case_runs_status', 'case_runs', ['status'])
    op.create_index('ix_case_runs_heartbeat', 'case_runs', ['heartbeat_at'])


def downgrade():
    op.drop_table('case_runs')
    op.drop_column('cases', 'stage')
    op.drop_column('cases', 'last_progress_at')
