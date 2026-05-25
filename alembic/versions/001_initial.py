"""initial schema

Revision ID: 001_initial
Revises:
Create Date: 2026-02-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, TSVECTOR


revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Users ──
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("yandex_id", sa.String(64), unique=True, nullable=True, index=True),
        sa.Column("vk_id", sa.String(64), unique=True, nullable=True, index=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("role", sa.Enum("judge", "assistant", "lawyer", "other", name="user_role"), server_default="judge"),
        sa.Column("nickname", sa.String(30), unique=True, nullable=True, index=True),
        sa.Column("is_admin", sa.Boolean, server_default="false"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("is_vip", sa.Boolean, server_default="false"),
        sa.Column("token_balance", sa.BigInteger, server_default="0"),
        sa.Column("balance_kopecks", sa.BigInteger, server_default="0"),
        sa.Column("withdrawable_balance_kopecks", sa.BigInteger, server_default="0"),
        sa.Column("free_cases_left", sa.Integer, server_default="5"),
        sa.Column("referral_code", sa.String(16), unique=True, nullable=False, index=True),
        sa.Column("referred_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("referral_active_until", sa.DateTime, nullable=True),
        sa.Column("invite_code_used", sa.String(20), nullable=True),
        sa.Column("style_profile", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ── Cases ──
    op.create_table(
        "cases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("status", sa.Enum("draft", "processing", "completed", "error", name="case_status"), server_default="draft"),
        sa.Column("fact_pack", JSONB, nullable=True),
        sa.Column("matched_norms", JSONB, nullable=True),
        sa.Column("generated_text", sa.Text, nullable=True),
        sa.Column("final_text", sa.Text, nullable=True),
        sa.Column("validation_result", JSONB, nullable=True),
        sa.Column("tokens_used", JSONB, nullable=True),
        sa.Column("cost_kopecks", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # ── Case Files ──
    op.create_table(
        "case_files",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", UUID(as_uuid=True), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("file_type", sa.String(10), server_default="image"),
        sa.Column("file_size", sa.Integer, nullable=True),
        sa.Column("sort_order", sa.Integer, server_default="0"),
        sa.Column("uploaded_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ── Transactions ──
    op.create_table(
        "transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("type", sa.Enum("purchase", "spend", "gift", "refund", "referral_bonus", "rating_bonus", name="tx_type"), nullable=False),
        sa.Column("amount_tokens", sa.BigInteger, server_default="0"),
        sa.Column("amount_kopecks", sa.BigInteger, server_default="0"),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("external_payment_id", sa.String(100), unique=True, nullable=True),
        sa.Column("case_id", UUID(as_uuid=True), sa.ForeignKey("cases.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_transactions_user_type_date", "transactions", ["user_id", "type", "created_at"])

    # ── Referral Payouts ──
    op.create_table(
        "referral_payouts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("amount_kopecks", sa.Integer, nullable=False),
        sa.Column("type", sa.String(20), server_default="withdrawal"),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("phone_number", sa.String(20), nullable=True),
        sa.Column("admin_note", sa.String(500), nullable=True),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ── Feedback ──
    op.create_table(
        "feedback",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), server_default="new"),
        sa.Column("admin_response", sa.Text, nullable=True),
        sa.Column("reward_kopecks", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ── Legal Documents ──
    op.create_table(
        "legal_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("doc_type", sa.String(50), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=True),
        sa.Column("date_published", sa.DateTime, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ── Legal Norms ──
    op.create_table(
        "legal_norms",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("legal_documents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("article", sa.String(100), nullable=True, index=True),
        sa.Column("paragraph", sa.String(100), nullable=True),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("text_tsvector", TSVECTOR, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    # GIN index для FTS
    op.create_index("ix_legal_norms_text_tsvector", "legal_norms", ["text_tsvector"], postgresql_using="gin")

    # ── Exemplars (learning) ──
    op.create_table(
        "exemplars",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", UUID(as_uuid=True), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("generated_text", sa.Text, nullable=False),
        sa.Column("final_text", sa.Text, nullable=False),
        sa.Column("edit_distance", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ── Norm Associations (learning) ──
    op.create_table(
        "norm_associations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("fact_keywords", JSONB, nullable=False),
        sa.Column("norm_id", UUID(as_uuid=True), sa.ForeignKey("legal_norms.id"), nullable=False),
        sa.Column("frequency", sa.Integer, server_default="1"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ── Hallucination Log (learning) ──
    op.create_table(
        "hallucination_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", UUID(as_uuid=True), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reference_text", sa.String(500), nullable=False),
        sa.Column("was_in_base", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ── Chat Messages ──
    op.create_table(
        "chat_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("tokens_used", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_chat_messages_user_date", "chat_messages", ["user_id", "created_at"])

    # ── Invite Codes ──
    op.create_table(
        "invite_codes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(20), unique=True, nullable=False, index=True),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("bonus_tokens", sa.BigInteger, server_default="0"),
        sa.Column("bonus_free_cases", sa.Integer, server_default="0"),
        sa.Column("max_activations", sa.Integer, server_default="1"),
        sa.Column("activated_count", sa.Integer, server_default="0"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("expires_at", sa.DateTime, nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ── Invite Activations ──
    op.create_table(
        "invite_activations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("invite_id", UUID(as_uuid=True), sa.ForeignKey("invite_codes.id"), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("bonus_tokens", sa.BigInteger, server_default="0"),
        sa.Column("bonus_free_cases", sa.Integer, server_default="0"),
        sa.Column("activated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("uq_invite_user", "invite_activations", ["invite_id", "user_id"], unique=True)

    # ── Trigger: автообновление text_tsvector при INSERT/UPDATE на legal_norms ──
    op.execute("""
        CREATE OR REPLACE FUNCTION legal_norms_tsvector_update() RETURNS trigger AS $$
        BEGIN
            NEW.text_tsvector := to_tsvector('russian', COALESCE(NEW.text, ''));
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER tsvector_update BEFORE INSERT OR UPDATE OF text
        ON legal_norms FOR EACH ROW EXECUTE FUNCTION legal_norms_tsvector_update();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tsvector_update ON legal_norms")
    op.execute("DROP FUNCTION IF EXISTS legal_norms_tsvector_update()")
    tables = [
        "invite_activations", "invite_codes", "chat_messages",
        "hallucination_log", "norm_associations", "exemplars",
        "legal_norms", "legal_documents", "feedback",
        "referral_payouts", "transactions", "case_files", "cases", "users",
    ]
    for t in tables:
        op.drop_table(t)
    for e in ["user_role", "case_status", "tx_type"]:
        op.execute(f"DROP TYPE IF EXISTS {e}")
