"""Replace ix_case_runs_one_active: unique on case_id instead of (case_id, pipeline_type)

Revision ID: 033
Revises: 032
Create Date: 2026-05-25

The old index ix_case_runs_one_active was on (case_id, pipeline_type), which
allowed multiple active runs on the same case with different pipeline_types
(e.g. full + rescue both running). This is a data-integrity risk if the Redis
job_lock fails or expires.

New index: unique on case_id alone — at most one queued/running CaseRun per case,
regardless of pipeline_type.
"""
from alembic import op
import sqlalchemy as sa


revision = '033'
down_revision = '032'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Clean up: mark older duplicate active runs as stale so the new unique
    #    index can be created without conflicts.
    op.execute("""
        UPDATE case_runs
        SET status = 'stale',
            error_code = 'index_cleanup',
            error_message = 'Marked stale during index migration — another active run exists for this case',
            finished_at = COALESCE(finished_at, NOW())
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY case_id
                           ORDER BY created_at DESC
                       ) AS rn
                FROM case_runs
                WHERE status IN ('queued', 'running')
            ) sub
            WHERE rn > 1
        )
    """)

    # 2. Drop old index
    op.execute("DROP INDEX IF EXISTS ix_case_runs_one_active")

    # 3. Create new index: one active run per case (not per case+pipeline_type)
    op.execute("""
        CREATE UNIQUE INDEX ix_case_runs_one_active
        ON case_runs (case_id)
        WHERE status IN ('queued', 'running')
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_case_runs_one_active")
    op.execute("""
        CREATE UNIQUE INDEX ix_case_runs_one_active
        ON case_runs (case_id, pipeline_type)
        WHERE status IN ('queued', 'running')
    """)
