"""Make financial columns NOT NULL with server_default

Fixes: AJ-301, AJ-302 — nullable financial columns cause TypeError when None += X

Revision ID: 005
Revises: 004
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    # Сначала заполняем NULL значения дефолтами (иначе ALTER COLUMN NOT NULL упадёт)
    op.execute("UPDATE users SET token_balance = 0 WHERE token_balance IS NULL")
    op.execute("UPDATE users SET balance_kopecks = 0 WHERE balance_kopecks IS NULL")
    op.execute("UPDATE users SET withdrawable_balance_kopecks = 0 WHERE withdrawable_balance_kopecks IS NULL")
    op.execute("UPDATE users SET free_cases_left = 5 WHERE free_cases_left IS NULL")

    op.execute("UPDATE norm_associations SET frequency = 1 WHERE frequency IS NULL")
    op.execute("UPDATE invite_codes SET activated_count = 0 WHERE activated_count IS NULL")

    # Теперь ставим NOT NULL + server_default
    op.alter_column("users", "token_balance",
                    existing_type=sa.BigInteger(),
                    nullable=False,
                    server_default=sa.text("0"))
    op.alter_column("users", "balance_kopecks",
                    existing_type=sa.BigInteger(),
                    nullable=False,
                    server_default=sa.text("0"))
    op.alter_column("users", "withdrawable_balance_kopecks",
                    existing_type=sa.BigInteger(),
                    nullable=False,
                    server_default=sa.text("0"))
    op.alter_column("users", "free_cases_left",
                    existing_type=sa.Integer(),
                    nullable=False,
                    server_default=sa.text("5"))

    op.alter_column("norm_associations", "frequency",
                    existing_type=sa.Integer(),
                    nullable=False,
                    server_default=sa.text("1"))
    op.alter_column("invite_codes", "activated_count",
                    existing_type=sa.Integer(),
                    nullable=False,
                    server_default=sa.text("0"))


def downgrade():
    for col in ["token_balance", "balance_kopecks", "withdrawable_balance_kopecks", "free_cases_left"]:
        op.alter_column("users", col, nullable=True, server_default=None)
    op.alter_column("norm_associations", "frequency", nullable=True, server_default=None)
    op.alter_column("invite_codes", "activated_count", nullable=True, server_default=None)
