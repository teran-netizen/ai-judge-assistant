"""Add missing users/cases columns required by current models.

Revision ID: 031
Revises: 030
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def _get_columns(inspector, table_name: str) -> set[str]:
    return {c["name"] for c in inspector.get_columns(table_name)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    user_cols = _get_columns(inspector, "users")
    if "phone" not in user_cols:
        op.add_column("users", sa.Column("phone", sa.String(length=20), nullable=True))
    if "sex" not in user_cols:
        op.add_column("users", sa.Column("sex", sa.String(length=10), nullable=True))
    if "real_name" not in user_cols:
        op.add_column("users", sa.Column("real_name", sa.String(length=200), nullable=True))

    inspector = sa.inspect(bind)
    case_cols = _get_columns(inspector, "cases")
    if "created_by" not in case_cols:
        op.add_column("cases", sa.Column("created_by", UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(
            "fk_cases_created_by_users",
            "cases",
            "users",
            ["created_by"],
            ["id"],
            ondelete="SET NULL",
        )
    if "files_count" not in case_cols:
        op.add_column("cases", sa.Column("files_count", sa.Integer(), nullable=True))
    if "files_recognized" not in case_cols:
        op.add_column("cases", sa.Column("files_recognized", sa.Integer(), nullable=True))
    if "files_failed" not in case_cols:
        op.add_column("cases", sa.Column("files_failed", sa.Integer(), nullable=True))
    if "generation_seconds" not in case_cols:
        op.add_column("cases", sa.Column("generation_seconds", sa.Numeric(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    case_cols = _get_columns(inspector, "cases")
    if "generation_seconds" in case_cols:
        op.drop_column("cases", "generation_seconds")
    if "files_failed" in case_cols:
        op.drop_column("cases", "files_failed")
    if "files_recognized" in case_cols:
        op.drop_column("cases", "files_recognized")
    if "files_count" in case_cols:
        op.drop_column("cases", "files_count")
    if "created_by" in case_cols:
        fk_names = {fk["name"] for fk in inspector.get_foreign_keys("cases") if fk.get("name")}
        if "fk_cases_created_by_users" in fk_names:
            op.drop_constraint("fk_cases_created_by_users", "cases", type_="foreignkey")
        op.drop_column("cases", "created_by")

    inspector = sa.inspect(bind)
    user_cols = _get_columns(inspector, "users")
    if "real_name" in user_cols:
        op.drop_column("users", "real_name")
    if "sex" in user_cols:
        op.drop_column("users", "sex")
    if "phone" in user_cols:
        op.drop_column("users", "phone")

