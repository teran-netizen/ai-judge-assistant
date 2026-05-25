"""Remove role column from users

Role field was unused — did not affect any logic, prompts, or access control.

Revision ID: 007
Revises: 006
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("users", "role")
    # Drop the enum type after column is gone
    op.execute("DROP TYPE IF EXISTS user_role")


def downgrade() -> None:
    # Recreate enum and column
    user_role = sa.Enum("judge", "assistant", "lawyer", "other", name="user_role")
    user_role.create(op.get_bind(), checkfirst=True)
    op.add_column("users", sa.Column("role", user_role, server_default="judge"))
