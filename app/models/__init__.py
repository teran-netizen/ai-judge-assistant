import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, SmallInteger, BigInteger, Boolean, Text, DateTime, Numeric, text,
    ForeignKey, Enum as SAEnum, Index, CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, TSVECTOR
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    display_id = Column(Integer, unique=True, server_default=text("nextval('users_display_id_seq'::regclass)"))  # numeric user ID for display
    yandex_id = Column(String(64), unique=True, nullable=True, index=True)
    vk_id = Column(String(64), unique=True, nullable=True, index=True)
    email = Column(String(255), nullable=True)
    name = Column(String(255), nullable=True)
    nickname = Column(String(30), unique=True, nullable=True)
    token_balance = Column(BigInteger, nullable=False, default=0, server_default="0")
    balance_kopecks = Column(BigInteger, nullable=False, default=0, server_default="0")
    withdrawable_balance_kopecks = Column(BigInteger, nullable=False, default=0, server_default="0")
    free_cases_left = Column(Integer, nullable=False, default=0, server_default="0")
    style_profile = Column(JSONB, nullable=True)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    is_vip = Column(Boolean, default=False)          # бесплатный доступ без лимитов
    invite_code_used = Column(String(20), nullable=True)  # каким инвайтом зашёл
    referred_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    utm_source = Column(String(500), nullable=True)       # UTM-метка при регистрации (полная строка)
    billing_model = Column(String(20), nullable=False, default="cases", server_default="cases")
    paid_cases_left = Column(Integer, nullable=False, default=0, server_default="0")
    subscription_until = Column(DateTime(timezone=True), nullable=True)
    last_activity = Column(DateTime, nullable=True)
    ab_group = Column(String(30), nullable=True)  # AB test group: paywall_early, paywall_preview
    promo_price = Column(Boolean, nullable=False, default=True, server_default="true")  # True = акционные цены 99/690/1990
    city = Column(String(100), nullable=True)
    timezone = Column(String(50), nullable=True)
    phone = Column(String(20), nullable=True)
    sex = Column(String(10), nullable=True)
    real_name = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.utcnow())
    updated_at = Column(DateTime, default=lambda: datetime.utcnow(), onupdate=lambda: datetime.utcnow())

    cases = relationship("Case", back_populates="user", foreign_keys="Case.user_id")
    transactions = relationship("Transaction", back_populates="user")
    feedbacks = relationship("Feedback", back_populates="user")

    __table_args__ = (
        CheckConstraint('token_balance >= 0', name='ck_users_token_balance_non_negative'),
    )


class Case(Base):
    __tablename__ = "cases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(500), nullable=True)
    user_instructions = Column(Text, nullable=True)  # Указания судьи для ИИ
    status = Column(SAEnum("draft", "processing", "completed", "error", "deleted", name="case_status"), default="draft")
    fact_pack = Column(JSONB, nullable=True)
    matched_norms = Column(JSONB, nullable=True)
    generated_text = Column(Text, nullable=True)
    final_text = Column(Text, nullable=True)
    validation_result = Column(JSONB, nullable=True)
    tokens_used = Column(JSONB, nullable=True)
    cost_kopecks = Column(Integer, nullable=True)
    ocr_pages = Column(Integer, nullable=True)      # кол-во распознанных OCR-страниц
    ocr_chars = Column(Integer, nullable=True)       # кол-во распознанных символов всего
    case_context = Column(JSONB, default=dict)  # Аккумулированный контекст дела
    billing_method = Column(String(30), nullable=True)
    files_count = Column(Integer, nullable=True)
    files_recognized = Column(Integer, nullable=True)
    files_failed = Column(Integer, nullable=True)
    generation_seconds = Column(Numeric, nullable=True)
    rating = Column(SmallInteger, nullable=True)  # 1-5 stars
    review_text = Column(Text, nullable=True)  # user review
    chat_history = Column(JSONB, default=list)  # История доработок (user + assistant сообщения)
    created_at = Column(DateTime, default=lambda: datetime.utcnow())
    stage = Column(String(30), nullable=True)  # processing stage: context_ready, generating, ready
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # assistant who created this case
    active_run_id = Column(UUID(as_uuid=True), nullable=True)  # Currently active CaseRun
    last_successful_run_id = Column(UUID(as_uuid=True), nullable=True)  # Last completed CaseRun
    last_progress_at = Column(DateTime, nullable=True)  # Last progress update timestamp
    updated_at = Column(DateTime, default=lambda: datetime.utcnow(), onupdate=lambda: datetime.utcnow())

    user = relationship("User", back_populates="cases", foreign_keys=[user_id])
    files = relationship("CaseFile", back_populates="case", lazy="selectin", cascade="all, delete-orphan")


class CaseFile(Base):
    __tablename__ = "case_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_type = Column(String(10), default="image")
    file_size = Column(Integer, nullable=True)  # может быть NULL для старых записей
    ocr_status = Column(String(10), nullable=True)  # null/pending/ok/error
    ocr_chars = Column(Integer, nullable=True)       # кол-во распознанных символов
    sort_order = Column(Integer, default=0)
    uploaded_at = Column(DateTime, default=lambda: datetime.utcnow())

    # Resumable upload columns (migration 027)
    upload_session_id = Column(UUID(as_uuid=True), ForeignKey("case_upload_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    client_file_id = Column(String(128), nullable=True, index=True)
    original_filename = Column(Text, nullable=True)
    size_bytes = Column(BigInteger, nullable=True)
    client_last_modified = Column(BigInteger, nullable=True)
    mime_type = Column(String(255), nullable=True)
    upload_order = Column(Integer, nullable=True)
    upload_batch_id = Column(String(128), nullable=True)
    ocr_text = Column(Text, nullable=True)

    case = relationship("Case", back_populates="files")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)  # nullable for widget flow
    type = Column(SAEnum("purchase", "spend", "refund", "referral_bonus", "rating_bonus", "gift", "widget_payment", name="tx_type"), nullable=False)
    amount_tokens = Column(BigInteger, nullable=True)
    amount_kopecks = Column(BigInteger, nullable=True)
    description = Column(String(500), nullable=True)
    purchase_type = Column(String(50), nullable=True)
    external_payment_id = Column(String(100), nullable=True, unique=True)  # ID заказа в платёжном шлюзе
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="SET NULL"), nullable=True)
    tx_metadata = Column("metadata", JSONB, nullable=True)  # Widget metadata: email, session_id, etc. ('metadata' is reserved in SQLAlchemy declarative)
    source_partner_id = Column(UUID(as_uuid=True), nullable=True)  # Partner who initiated the payment
    created_at = Column(DateTime, default=lambda: datetime.utcnow())
    credited_at = Column(DateTime, nullable=True)  # When cases/subscription were actually credited

    user = relationship("User", back_populates="transactions")

    __table_args__ = (
        Index("ix_transactions_user_type_date", "user_id", "type", "created_at"),
        Index("ix_transactions_source_partner", "source_partner_id"),
    )


class Feedback(Base):
    __tablename__ = "feedbacks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    category = Column(String(50), nullable=False)
    text = Column(Text, nullable=False)
    screenshot_path = Column(String(500), nullable=True)
    status = Column(String(20), default="new")
    reward_kopecks = Column(Integer, nullable=True)
    admin_response = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.utcnow())

    user = relationship("User", back_populates="feedbacks")


class LegalDocument(Base):
    __tablename__ = "legal_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_type = Column(String(50), nullable=False)
    title = Column(Text, nullable=False)
    source_url = Column(String(1000), nullable=True)
    date_published = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)

    norms = relationship("LegalNorm", back_populates="document")


class LegalNorm(Base):
    __tablename__ = "legal_norms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("legal_documents.id"), nullable=False, index=True)
    article = Column(String(50), nullable=True)
    paragraph = Column(String(50), nullable=True)
    text = Column(Text, nullable=False)
    text_tsvector = Column(TSVECTOR, nullable=True)

    # Actuality tracking
    content_hash = Column(String(32), nullable=True)
    edition_date = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    inactive_reason = Column(Text, nullable=True)
    replaced_by_id = Column(UUID(as_uuid=True), ForeignKey("legal_norms.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.utcnow())

    document = relationship("LegalDocument", back_populates="norms")
    replaced_by = relationship("LegalNorm", remote_side="LegalNorm.id", foreign_keys=[replaced_by_id])

    __table_args__ = (
        Index("ix_legal_norms_fts", "text_tsvector", postgresql_using="gin"),
        Index("ix_legal_norms_is_active", "is_active"),
        Index("ix_legal_norms_content_hash", "content_hash"),
    )


class NormHistory(Base):
    __tablename__ = "norm_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    norm_id = Column(UUID(as_uuid=True), ForeignKey("legal_norms.id", ondelete="CASCADE"), nullable=False, index=True)
    old_text = Column(Text, nullable=True)
    new_text = Column(Text, nullable=True)
    old_hash = Column(String(32), nullable=True)
    new_hash = Column(String(32), nullable=True)
    change_type = Column(String(30), nullable=False)  # updated | deactivated | reactivated | created
    reason = Column(Text, nullable=True)
    changed_at = Column(DateTime, default=lambda: datetime.utcnow())


class Exemplar(Base):
    __tablename__ = "exemplars"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    generated_text = Column(Text, nullable=False)
    final_text = Column(Text, nullable=False)
    edit_distance = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.utcnow())


class NormAssociation(Base):
    __tablename__ = "norm_associations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fact_keywords = Column(JSONB, nullable=False)
    norm_id = Column(UUID(as_uuid=True), ForeignKey("legal_norms.id"), nullable=False)
    frequency = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(DateTime, default=lambda: datetime.utcnow())


class HallucinationLog(Base):
    __tablename__ = "hallucination_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    reference_text = Column(String(500), nullable=False)
    was_in_base = Column(Boolean, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.utcnow())




class CaseRun(Base):
    __tablename__ = "case_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    pipeline_type = Column(String(30), nullable=False)  # full, generate_only, rescue
    status = Column(String(20), nullable=False, default="queued")  # queued, running, completed, failed, stale
    stage = Column(String(30), nullable=True)  # ocr_running, context_building, generating, validating, ready
    progress_pct = Column(Integer, nullable=True)
    worker_id = Column(String(50), nullable=True)
    job_id = Column(String(100), nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    retry_count = Column(Integer, default=0)
    error_code = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    recovery_of_run_id = Column(UUID(as_uuid=True), nullable=True)
    usage_json = Column(JSONB, nullable=True)  # {ocr_pages, ocr_chars, prompt_tokens, completion_tokens, total_tokens}
    attempt = Column(Integer, default=1, server_default="1")  # Attempt number
    created_at = Column(DateTime, default=lambda: datetime.utcnow())

    __table_args__ = (
        Index("ix_case_runs_status", "status"),
        Index("ix_case_runs_heartbeat", "heartbeat_at"),
        Index("ix_case_runs_one_active", "case_id", unique=True,
              postgresql_where="status IN ('queued', 'running')"),
    )


class CaseRating(Base):
    """Оценка качества генерации — 👍/👎 прямо на странице дела."""
    __tablename__ = "case_ratings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    is_positive = Column(Boolean, nullable=False)          # True = 👍, False = 👎
    tags = Column(JSONB, nullable=True)                     # ["wrong_norms", "bad_style", ...]
    comment = Column(Text, nullable=True)                   # необязательный комментарий
    created_at = Column(DateTime, default=lambda: datetime.utcnow())

    __table_args__ = (
        Index("uq_case_rating_user", "case_id", "user_id", unique=True),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(10), nullable=False)
    content = Column(Text, nullable=False)
    tokens_used = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.utcnow())

    __table_args__ = (
        Index("ix_chat_messages_user_date", "user_id", "created_at"),
    )


class InviteCode(Base):
    __tablename__ = "invite_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(32), unique=True, nullable=False, index=True)
    label = Column(String(200), nullable=True)          # "Для Иванова И.И., Мосгорсуд"
    bonus_tokens = Column(BigInteger, default=0)         # подарочные токены
    bonus_free_cases = Column(Integer, default=0)        # доп. бесплатные дела
    max_activations = Column(Integer, default=1)         # сколько раз можно активировать
    activated_count = Column(Integer, nullable=False, default=0, server_default="0")         # сколько раз уже активирован
    expires_at = Column(DateTime, nullable=True)         # срок годности (null = бессрочный)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.utcnow())

    activations = relationship("InviteActivation", back_populates="invite")


class InviteActivation(Base):
    __tablename__ = "invite_activations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invite_id = Column(UUID(as_uuid=True), ForeignKey("invite_codes.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    bonus_tokens = Column(BigInteger, default=0)
    bonus_free_cases = Column(Integer, default=0)
    activated_at = Column(DateTime, default=lambda: datetime.utcnow())

    invite = relationship("InviteCode", back_populates="activations")

    __table_args__ = (
        Index("uq_invite_user", "invite_id", "user_id", unique=True),
    )


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(50), nullable=False)  # login, upload, generate, purchase_attempt, payment_success, error
    details = Column(Text, nullable=True)
    utm_source = Column(String(500), nullable=True)
    ip_address = Column(String(45), nullable=True)
    case_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.utcnow(), index=True)


class CaseUploadSession(Base):
    __tablename__ = "case_upload_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="pending", server_default="pending")
    expected_files_count = Column(Integer, nullable=True)
    uploaded_files_count = Column(Integer, nullable=False, default=0, server_default="0")
    total_bytes = Column(BigInteger, nullable=True)
    uploaded_bytes = Column(BigInteger, nullable=False, default=0, server_default="0")
    failed_files_count = Column(Integer, nullable=False, default=0, server_default="0")
    started_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    last_activity_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    finalized_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    client_upload_token = Column(String(128), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    __table_args__ = (
        Index("ix_case_upload_sessions_status", "status"),
        Index("ix_case_upload_sessions_last_activity_at", "last_activity_at"),
        Index("ix_case_upload_sessions_case_status", "case_id", "status"),
    )


class ReferralEvent(Base):
    __tablename__ = "referral_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    referrer_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    referred_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="registered", server_default="registered")  # registered -> converted -> bonus_paid
    registered_at = Column(DateTime, default=lambda: datetime.utcnow())
    converted_at = Column(DateTime, nullable=True)
    bonus_paid_at = Column(DateTime, nullable=True)
    referrer_bonus_cases = Column(Integer, nullable=False, default=0, server_default="0")
    referred_bonus_cases = Column(Integer, nullable=False, default=0, server_default="0")

    referrer = relationship("User", foreign_keys=[referrer_id])
    referred = relationship("User", foreign_keys=[referred_id])

    __table_args__ = (
        Index("ix_referral_events_referrer_status", "referrer_id", "status"),
    )


class ReferralLinkClick(Base):
    __tablename__ = "referral_link_clicks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    clicked_at = Column(DateTime, default=lambda: datetime.utcnow())


class JudgeAssistant(Base):
    __tablename__ = "judge_assistants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    judge_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    assistant_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.utcnow())

    judge = relationship("User", foreign_keys=[judge_id])
    assistant = relationship("User", foreign_keys=[assistant_id])

    __table_args__ = (
        Index("uq_judge_assistant", "judge_id", "assistant_id", unique=True),
    )
