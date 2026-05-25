"""Add case content version and one-judge-per-assistant constraint.

Revision ID: 030
Revises: 029
"""

from alembic import op
import sqlalchemy as sa

revision = "030"
down_revision = "029"


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Idempotent add for fresh / partially migrated DBs.
    case_columns = {c["name"] for c in inspector.get_columns("cases")}
    if "content_version" not in case_columns:
        op.add_column(
            "cases",
            sa.Column("content_version", sa.Integer(), nullable=False, server_default="0"),
        )

    table_names = set(inspector.get_table_names())
    if "judge_assistants" not in table_names:
        op.create_table(
            "judge_assistants",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("judge_id", sa.UUID(), nullable=False),
            sa.Column("assistant_id", sa.UUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["assistant_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["judge_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_judge_assistants_judge_id", "judge_assistants", ["judge_id"], unique=False)
        op.create_index("ix_judge_assistants_assistant_id", "judge_assistants", ["assistant_id"], unique=False)
        op.create_index("uq_judge_assistant", "judge_assistants", ["judge_id", "assistant_id"], unique=True)

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("judge_assistants")}
    if "uq_judge_assistant_one_judge_per_assistant" not in existing_indexes:
        op.create_index(
            "uq_judge_assistant_one_judge_per_assistant",
            "judge_assistants",
            ["assistant_id"],
            unique=True,
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "judge_assistants" in table_names:
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("judge_assistants")}
        if "uq_judge_assistant_one_judge_per_assistant" in existing_indexes:
            op.drop_index("uq_judge_assistant_one_judge_per_assistant", table_name="judge_assistants")
    case_columns = {c["name"] for c in inspector.get_columns("cases")}
    if "content_version" in case_columns:
        op.drop_column("cases", "content_version")
