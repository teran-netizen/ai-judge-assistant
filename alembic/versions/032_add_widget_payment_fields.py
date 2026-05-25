"""Add widget_payment support: metadata, source_partner_id, nullable user_id, enum value

Revision ID: 032
Revises: 031
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = '032'
down_revision = '031'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Allow nullable user_id (widget payments may not have a user yet)
    op.alter_column('transactions', 'user_id', nullable=True)

    # 2. Add widget_payment to tx_type enum
    op.execute("ALTER TYPE tx_type ADD VALUE IF NOT EXISTS 'widget_payment'")

    # 3. Add metadata column for widget payment context
    op.add_column('transactions', sa.Column('metadata', JSONB, nullable=True))

    # 4. Add source_partner_id for partner attribution
    op.add_column('transactions', sa.Column('source_partner_id', UUID(as_uuid=True), nullable=True))

    # 5. Index on source_partner_id for partner analytics
    op.create_index('ix_transactions_source_partner', 'transactions', ['source_partner_id'])


def downgrade():
    op.drop_index('ix_transactions_source_partner')
    op.drop_column('transactions', 'source_partner_id')
    op.drop_column('transactions', 'metadata')
    # Cannot remove enum value from tx_type in PostgreSQL (no ALTER TYPE DROP VALUE)
    op.alter_column('transactions', 'user_id', nullable=False)
