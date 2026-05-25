from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://judge:dev_password_change_me@db:5432/ai_judge"
    redis_url: str = "redis://:dev_redis_password_change_me@redis:6379/0"
    secret_key: str = "change-me"
    domain: str = "https://your-domain.ru"
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://192.168.0.101:3000"  # Comma-separated CORS allowed origins
    debug: bool = False
    dev_access_enabled: bool = False
    dev_access_user_email: str = "dev@localhost"
    dev_access_user_name: str = "Dev User"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    yandex_client_id: str = ""
    yandex_client_secret: str = ""
    yandex_ocr_api_key: str = ""  # Yandex Vision OCR API (https://ocr.api.cloud.yandex.net)
    vk_client_id: str = ""
    vk_client_secret: str = ""

    # Tochka acquiring
    tochka_client_id: str = ""
    tochka_client_secret: str = ""
    tochka_access_token: str = ""
    tochka_refresh_token: str = ""
    tochka_customer_code: str = ""
    tochka_merchant_id: str = ""
    tochka_webhook_secret: str = ""                # HMAC-SHA256 секрет от Точки
    tochka_webhook_allowed_ips: str = ""           # IP allowlist (comma-separated, поддерживает CIDR)
    tochka_webhook_enforced: bool = True           # True = отклонять callback'и без secret/IP (fail-closed)

    telegram_bot_token: str = ""
    telegram_admin_chat_id: str = ""

    # Unisender / SMTP
    unisender_api_key: str = ""
    unisender_list_id: int = 2
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    resend_api_key: str = ""

    upload_dir: str = "/app/uploads"
    max_file_size_mb: int = 20

    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 43200  # 30 дней
    internal_api_secret: str = ""  # separate secret for internal service-to-service JWT (falls back to secret_key)

    # Registration / billing base values
    registration_free_cases: int = 0

    # Limits
    cases_max_per_user: int = 500

    # File/storage limits
    max_files_per_case: int = 500                   # max файлов на одно дело
    max_storage_per_case_gb: float = 2.0            # max объём файлов на дело (ГБ)
    est_pages_per_pdf: int = 15                     # средняя оценка страниц в PDF для расчёта стоимости

    # DeepSeek cost model (RUB per token)
    ds_cost_per_input_token: float = 0.000014       # ₽
    ds_cost_per_output_token: float = 0.000028      # ₽
    ocr_cost_per_page_rub: float = 1.3              # ₽ per OCR page (Yandex Vision)

    @property
    def case_packages(self) -> dict:
        # Non-promo (B group in current AB split)
        return {
            "single_case": {
                "cases": 1,
                "price_kopecks": 14900,
                "label": "Разовое дело",
            },
            "subscription_monthly": {
                "cases": None,
                "price_kopecks": 500000,
                "label": "Подписка на месяц",
                "duration_days": 30,
            },
        }

    @property
    def promo_packages(self) -> dict:
        return self.case_packages

    @property
    def gift_presets(self) -> dict:
        return {
            "trial": {
                "label": "\u041f\u0440\u043e\u0431\u043d\u044b\u0439 (\u224810 \u0434\u0435\u043b)",
                "bonus_tokens": 3_000,
                "bonus_free_cases": 0,
            },
            "starter": {
                "label": "\u0421\u0442\u0430\u0440\u0442\u043e\u0432\u044b\u0439 (\u224830 \u0434\u0435\u043b)",
                "bonus_tokens": 9_000,
                "bonus_free_cases": 0,
            },
            "standard": {
                "label": "\u0421\u0442\u0430\u043d\u0434\u0430\u0440\u0442\u043d\u044b\u0439 (\u224865 \u0434\u0435\u043b)",
                "bonus_tokens": 20_000,
                "bonus_free_cases": 0,
            },
            "premium": {
                "label": "\u041f\u0440\u0435\u043c\u0438\u0443\u043c (\u2248200 \u0434\u0435\u043b)",
                "bonus_tokens": 60_000,
                "bonus_free_cases": 0,
            },
            "vip": {
                "label": "VIP (\u2248500 \u0434\u0435\u043b)",
                "bonus_tokens": 150_000,
                "bonus_free_cases": 0,
            },
            "max": {
                "label": "\u041c\u0430\u043a\u0441\u0438\u043c\u0430\u043b\u044c\u043d\u044b\u0439 (\u22481000 \u0434\u0435\u043b)",
                "bonus_tokens": 300_000,
                "bonus_free_cases": 0,
            },
        }

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.secret_key == "change-me":
        import logging

        logging.getLogger("app.config").critical(
            "SECRET_KEY not set. Default value is insecure for production."
        )
        if not s.debug:
            raise RuntimeError("SECRET_KEY must be set in production (debug=False)")

    if not s.debug:
        if "legacy_default_db_password" in s.database_url or "dev_password_change_me" in s.database_url:
            import logging

            logging.getLogger("app.config").critical(
                "Default DB password detected in production."
            )
            raise RuntimeError("Default DB password in production (debug=False)")
        if "legacy_default_redis_password" in s.redis_url or "dev_redis_password_change_me" in s.redis_url:
            import logging

            logging.getLogger("app.config").critical(
                "Default Redis password detected in production."
            )
            raise RuntimeError("Default Redis password in production (debug=False)")
    return s
