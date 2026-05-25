"""fix column type mismatches between model and DB

- users.balance_kopecks: Integer → BigInteger
- users.withdrawable_balance_kopecks: Integer → BigInteger
- users.referral_code: nullable → NOT NULL
- transactions.amount_kopecks: Integer → BigInteger
- case_files: rename created_at → uploaded_at (match ORM model)

Revision ID: 003
Revises: 002
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"


def upgrade() -> None:
    # Integer → BigInteger (safe: BigInteger ⊃ Integer, no data loss)
    op.alter_column("users", "balance_kopecks", type_=sa.BigInteger, existing_type=sa.Integer)
    op.alter_column("users", "withdrawable_balance_kopecks", type_=sa.BigInteger, existing_type=sa.Integer)
    op.alter_column("transactions", "amount_kopecks", type_=sa.BigInteger, existing_type=sa.Integer)

    # referral_code: nullable → NOT NULL
    # Сначала заполняем NULL-записи (если есть) случайными кодами
    op.execute("""
        UPDATE users
        SET referral_code = substr(md5(random()::text), 1, 8)
        WHERE referral_code IS NULL
    """)
    op.alter_column("users", "referral_code", nullable=False)

    # case_files: 001 уже создаёт uploaded_at (rename не нужен)


def downgrade() -> None:
    op.alter_column("users", "referral_code", nullable=True)
    op.alter_column("transactions", "amount_kopecks", type_=sa.Integer, existing_type=sa.BigInteger)
    op.alter_column("users", "withdrawable_balance_kopecks", type_=sa.Integer, existing_type=sa.BigInteger)
    op.alter_column("users", "balance_kopecks", type_=sa.Integer, existing_type=sa.BigInteger)
