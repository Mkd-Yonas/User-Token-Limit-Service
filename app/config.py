from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TQS_", env_file=".env.local", extra="ignore")

    # MongoDB
    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "tqs"

    # API keys
    api_key: str = "sk-tqs-changeme"
    admin_api_key: str = "sk-tqs-admin-changeme"

    # Token limit policy
    token_limit: int = 50000       # tokens per window
    reset_hours: int = 5           # hours until auto-reset after limit is hit


settings = Settings()
