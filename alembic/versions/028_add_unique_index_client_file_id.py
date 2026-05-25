"""Add unique partial index on case_files(case_id, client_file_id)

Revision ID: 028
Revises: 027
"""

from alembic import op

revision = '028'
down_revision = '027'


def upgrade():
    # Partial unique index — only for files that have client_file_id
    op.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS uix_case_files_case_client_file
        ON case_files (case_id, client_file_id)
        WHERE client_file_id IS NOT NULL
    ''')


def downgrade():
    op.execute('DROP INDEX IF EXISTS uix_case_files_case_client_file')
