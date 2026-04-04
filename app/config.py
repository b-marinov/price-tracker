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


def get_settings() -> Settings:
    """Return a cached Settings instance.

    Returns:
        Settings: The application settings singleton.
    """
    return Settings()  # type: ignore[call-arg]
