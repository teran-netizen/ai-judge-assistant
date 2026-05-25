"""Devalue tokens: divide all token amounts by 100

1 internal token = 100 DeepSeek API tokens

Revision ID: 009
Revises: 008
"""
from alembic import op
import sqlalchemy as sa

revision = '009'
down_revision = '008'


def upgrade():
    # Users: token_balance / 100
    op.execute("UPDATE users SET token_balance = token_balance / 100")

    # Transactions: amount_tokens / 100
    op.execute("UPDATE transactions SET amount_tokens = amount_tokens / 100 WHERE amount_tokens IS NOT NULL AND amount_tokens > 0")

    # Invite codes: bonus_tokens / 100
    op.execute("UPDATE invite_codes SET bonus_tokens = bonus_tokens / 100 WHERE bonus_tokens IS NOT NULL AND bonus_tokens > 0")

    # Invite activations: bonus_tokens / 100 (historical record)
    op.execute("UPDATE invite_activations SET bonus_tokens = bonus_tokens / 100 WHERE bonus_tokens IS NOT NULL AND bonus_tokens > 0")


def downgrade():
    op.execute("UPDATE users SET token_balance = token_balance * 100")
    op.execute("UPDATE transactions SET amount_tokens = amount_tokens * 100 WHERE amount_tokens IS NOT NULL AND amount_tokens > 0")
    op.execute("UPDATE invite_codes SET bonus_tokens = bonus_tokens * 100 WHERE bonus_tokens IS NOT NULL AND bonus_tokens > 0")
    op.execute("UPDATE invite_activations SET bonus_tokens = bonus_tokens * 100 WHERE bonus_tokens IS NOT NULL AND bonus_tokens > 0")
