from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TLS_", env_file=".env", extra="ignore")

    # Core
    database_url: str = "postgresql+asyncpg://tls:secret@localhost:5432/tls"
    redis_url: str = "redis://localhost:6379/0"

    # API
    api_key: str = "sk-tls-changeme"
    admin_api_key: str = "sk-tls-admin-changeme"
    request_timeout_ms: int = 5000

    # Business defaults
    default_tier: str = "free"
    grace_percentage: float = 5.0
    refund_overestimation: bool = True
    strict_mode: bool = False

    # Feature flags
    enable_org_limits: bool = True
    enable_concurrent_limits: bool = True
    enable_model_multipliers: bool = True

    # Reaper
    reaper_interval_minutes: int = 1
    reaper_stale_threshold_minutes: int = 5


settings = Settings()
