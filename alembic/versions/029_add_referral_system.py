"""Add referral system: referred_by, referral_events, referral_link_clicks

Revision ID: 029
Revises: 66821ad98869
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add referred_by to users
    op.add_column("users", sa.Column("referred_by", UUID(as_uuid=True), nullable=True))
    op.create_index("ix_users_referred_by", "users", ["referred_by"])
    op.create_foreign_key("fk_users_referred_by", "users", "users", ["referred_by"], ["id"], ondelete="SET NULL")

    # 2. Create referral_events table
    op.create_table(
        "referral_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("referrer_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("referred_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="registered"),
        sa.Column("registered_at", sa.DateTime, server_default=sa.text("now()")),
        sa.Column("converted_at", sa.DateTime, nullable=True),
        sa.Column("bonus_paid_at", sa.DateTime, nullable=True),
        sa.Column("referrer_bonus_cases", sa.Integer, nullable=False, server_default="0"),
        sa.Column("referred_bonus_cases", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_referral_events_referrer_id", "referral_events", ["referrer_id"])
    op.create_index("ix_referral_events_referred_id", "referral_events", ["referred_id"], unique=True)
    op.create_index("ix_referral_events_referrer_status", "referral_events", ["referrer_id", "status"])

    # 3. Create referral_link_clicks table
    op.create_table(
        "referral_link_clicks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("clicked_at", sa.DateTime, server_default=sa.text("now()")),
    )
    op.create_index("ix_referral_link_clicks_user_id", "referral_link_clicks", ["user_id"])


def downgrade():
    op.drop_table("referral_link_clicks")
    op.drop_table("referral_events")
    op.drop_constraint("fk_users_referred_by", "users", type_="foreignkey")
    op.drop_index("ix_users_referred_by", "users")
    op.drop_column("users", "referred_by")
