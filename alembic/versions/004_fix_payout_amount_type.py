"""fix referral_payouts.amount_kopecks: Integer → BigInteger

Consistency with users.balance_kopecks and transactions.amount_kopecks
(both fixed in migration 003).

Revision ID: 004
Revises: 003
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"


def upgrade() -> None:
    op.alter_column(
        "referral_payouts", "amount_kopecks",
        type_=sa.BigInteger, existing_type=sa.Integer,
    )


def downgrade() -> None:
    op.alter_column(
        "referral_payouts", "amount_kopecks",
        type_=sa.Integer, existing_type=sa.BigInteger,
    )
