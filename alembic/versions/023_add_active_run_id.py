"""add active_run_id and last_successful_run_id to cases + unique constraint on case_runs

Revision ID: 023
Revises: 022
Create Date: 2026-03-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '023'
down_revision = '022'
branch_labels = None
depends_on = None


def upgrade():
    # Add run tracking to cases
    op.add_column('cases', sa.Column('active_run_id', UUID(as_uuid=True), nullable=True))
    op.add_column('cases', sa.Column('last_successful_run_id', UUID(as_uuid=True), nullable=True))

    # Add attempt field to case_runs
    op.add_column('case_runs', sa.Column('attempt', sa.Integer(), server_default='1'))
    op.add_column('case_runs', sa.Column('job_id', sa.String(100), nullable=True))

    # Unique partial index: one active run per case+pipeline_type
    op.execute("""
        CREATE UNIQUE INDEX ix_case_runs_one_active
        ON case_runs (case_id, pipeline_type)
        WHERE status IN ('queued', 'running')
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_case_runs_one_active")
    op.drop_column('case_runs', 'job_id')
    op.drop_column('case_runs', 'attempt')
    op.drop_column('cases', 'last_successful_run_id')
    op.drop_column('cases', 'active_run_id')
