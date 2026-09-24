"""Runtime settings, read from environment variables (or a .env file)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Core ---
    environment: str = Field(default="development", description="development | production | test")
    database_url: str = "postgresql+asyncpg://wam:wam@localhost:5432/wam"
    redis_url: str = "redis://localhost:6379/0"
    log_level: str = "INFO"

    # Secret used to sign admin JWTs. MUST be changed in production.
    secret_key: str = "change-me-in-production"
    admin_token_hours: int = 12

    # The Chatwoot agent-bot webhook must hit /webhooks/chatwoot/<webhook_secret>.
    webhook_secret: str = "change-me-webhook-secret"

    # --- Chatwoot ---
    chatwoot_base_url: str = ""  # e.g. https://inbox.example.com ; empty => dry-run (messages only logged)
    chatwoot_api_token: str = ""  # default admin/agent access token (per-business token overrides)
    chatwoot_bot_token: str = ""  # default agent-bot token used for replies (optional)
    chatwoot_timeout_seconds: float = 15.0
    # Chatwoot WhatsApp template parameter format: "enhanced" ({"body": {"1": "x"}}, Chatwoot 4.x) or
    # "legacy" ({"1": "x"}, older Chatwoot; deprecated upstream)
    chatwoot_template_format: str = "enhanced"

    # --- AI ---
    anthropic_api_key: str = ""
    ai_model: str = "claude-haiku-4-5"
    ai_max_tokens: int = 1024
    ai_max_tool_rounds: int = 6
    ai_timeout_seconds: float = 30.0

    # --- Features ---
    enable_simulator: bool = True  # /api/simulator endpoints for testing without WhatsApp
    process_inline: bool = False  # process webhooks in-process instead of via the arq queue
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""

    # CORS origins for the admin (only needed if the browser calls core directly)
    cors_origins: list[str] = Field(default_factory=list)

    # Alerts (monitoring): optional webhook URL that receives JSON {"text": "..."} on failures
    alert_webhook_url: str = ""

    @property
    def chatwoot_enabled(self) -> bool:
        return bool(self.chatwoot_base_url)

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
