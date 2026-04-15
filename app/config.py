"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings populated from environment variables.

    All values are read from a `.env` file or the process environment.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379/0"
    APP_ENV: str = "development"
    SECRET_KEY: str
    ADMIN_KEY: str = "change-me-admin-key"
    CORS_ORIGINS: str = "http://localhost:3000"

    # LLM-based scraper (Gemma 4 via Ollama)
    LLM_PARSER_ENABLED: bool = False
    LLM_OLLAMA_HOST: str = "http://localhost:11434"
    LLM_MODEL: str = "qwen3.5:9b-q8_0"
    LLM_PAGE_DPI: int = 200
    LLM_TEMPERATURE: float = 0.1
    LLM_TIMEOUT_SECONDS: float = 120.0


def get_settings() -> Settings:
    """Return a cached Settings instance.

    Returns:
        Settings: The application settings singleton.
    """
    return Settings()
