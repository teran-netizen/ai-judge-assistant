"""Remove referral system

Drops referral_payouts table and referral-related columns from users.

Revision ID: 006
Revises: 005
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Drop referral_payouts table
    op.drop_table("referral_payouts")

    # 2. Drop referral columns from users
    # Drop FK constraint first
    op.drop_constraint("users_referred_by_fkey", "users", type_="foreignkey")
    op.drop_column("users", "referred_by")
    op.drop_column("users", "referral_active_until")

    # Drop unique index on referral_code before dropping column
    op.drop_index("ix_users_referral_code", table_name="users")
    op.drop_column("users", "referral_code")

    # 3. Add CHECK constraint for token_balance (H17)
    op.create_check_constraint(
        "ck_users_token_balance_non_negative",
        "users",
        "token_balance >= 0",
    )


def downgrade():
    op.drop_constraint("ck_users_token_balance_non_negative", "users", type_="check")

    op.add_column("users", sa.Column("referral_code", sa.String(16), nullable=True))
    op.create_index("ix_users_referral_code", "users", ["referral_code"], unique=True)
    op.add_column("users", sa.Column("referral_active_until", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("referred_by", sa.dialects.postgresql.UUID(), nullable=True))
    op.create_foreign_key("users_referred_by_fkey", "users", "users", ["referred_by"], ["id"])

    op.create_table(
        "referral_payouts",
        sa.Column("id", sa.dialects.postgresql.UUID(), primary_key=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.Enum("balance_bonus", "withdrawal", name="payout_type"), nullable=False),
        sa.Column("status", sa.Enum("pending", "processing", "completed", "failed", name="payout_status"), server_default="pending"),
        sa.Column("phone_number", sa.String(20)),
        sa.Column("admin_note", sa.String(500)),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()),
    )
