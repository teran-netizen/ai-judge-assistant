from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID
from typing import Optional


# Auth
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str

class UserProfile(BaseModel):
    id: UUID; display_id: int | None = None; name: str | None; email: str | None; nickname: str | None
    balance_kopecks: int; withdrawable_balance_kopecks: int
    free_cases_left: int; is_admin: bool; created_at: datetime
    billing_model: str = "cases"
    paid_cases_left: int = 0
    subscription_until: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    ab_group: Optional[str] = None
    promo_price: bool = True
    phone: str | None = None
    sex: str | None = None
    real_name: str | None = None
    class Config:
        from_attributes = True

class OAuthCallback(BaseModel):
    code: str
    state: str | None = None
    redirect_uri: str | None = None
    code_verifier: str | None = None  # PKCE для VK ID
    device_id: str | None = None      # VK ID device_id

class SetNickname(BaseModel):
    nickname: str = Field(min_length=2, max_length=30, pattern=r"^[a-zA-Zа-яА-ЯёЁ0-9_\-]+$")

# Cases
class CaseCreate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    user_instructions: str | None = Field(default=None, max_length=500_000)
    judge_id: str | None = Field(default=None, max_length=36)  # Create case on behalf of judge

class CaseFileResponse(BaseModel):
    id: UUID
    filename: str
    file_type: str | None = None
    file_size: int | None = None
    ocr_status: str | None = None
    ocr_chars: int | None = None
    class Config:
        from_attributes = True

class CaseListItem(BaseModel):
    id: UUID; title: str | None; status: str; created_at: datetime
    user_instructions: str | None = None
    rating: int | None = None
    files_count: int = 0
    class Config:
        from_attributes = True

class CaseResponse(BaseModel):
    id: UUID; title: str | None; user_instructions: str | None; status: str; generated_text: str | None
    final_text: str | None; validation_result: dict | None; tokens_used: dict | None; created_at: datetime
    billing_method: str | None = None
    rating: int | None = None; review_text: str | None = None
    files: list[CaseFileResponse] = []
    chat_history: list[dict] = []
    class Config:
        from_attributes = True

class CaseUpdate(BaseModel):
    final_text: str = Field(max_length=2_000_000)  # защита от OOM, не от юзера

class RefineRequest(BaseModel):
    full_text: str = Field(max_length=2_000_000)    # ~500K слов — любое реальное решение пройдёт
    selected_text: str = Field(max_length=500_000)   # фрагмент для доработки
    user_request: str = Field(min_length=1, max_length=5000)
    selection_offset: int | None = Field(default=None, ge=0)  # позиция selected_text в full_text (для точной замены)
    new_file_ids: list[str] | None = None  # IDs of newly uploaded files to include in refinement context

# Billing
class PurchaseRequest(BaseModel):
    tokens: int = Field(gt=0)  # только положительные значения

class SbpPaymentResponse(BaseModel):
    order_id: str
    payment_type: str  # "sbp_qr" или "redirect"
    payment_url: str  # fallback URL для оплаты картой
    qr_payload: str | None = None  # строка для QR-кода СБП
    qr_image: str | None = None  # base64 картинка QR

# Feedback
class FeedbackCreate(BaseModel):
    category: str = Field(pattern="^(bug|suggestion|prompt|new_category|other)$")
    text: str = Field(min_length=10, max_length=5000)

class FeedbackResponse(BaseModel):
    id: UUID; category: str; text: str; status: str; reward_kopecks: int | None
    admin_response: str | None; created_at: datetime
    class Config:
        from_attributes = True


# Internal widget API
class WidgetPaymentRequest(BaseModel):
    partner_id: UUID
    session_id: UUID
    email: str | None = None
    amount_kopecks: int = 9900
    origin_url: str | None = None
    utm: str | None = None


class WidgetPaymentResponse(BaseModel):
    status: str = "ok"
    payment_url: str
    transaction_id: UUID
    operation_id: str
