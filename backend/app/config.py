"""Application settings loaded from environment variables."""

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the TrendRadar web backend.

    Args:
        All fields map to environment variables (`APP_BASE_PATH` or `TRENDRADAR_*`).
    """

    model_config = SettingsConfigDict(
        env_prefix="TRENDRADAR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_base_path: str = Field(
        default="/radar",
        validation_alias=AliasChoices("APP_BASE_PATH", "app_base_path"),
    )
    host: str = "127.0.0.1"
    port: int = 8000
    db_path: Path = Path("data/trendradar.db")
    secret_key: str = "dev-insecure-change-me"
    admin_user: str = "admin"
    admin_pass: str = ""
    timezone: str = "Asia/Shanghai"
    cors_origins: str = ""
    enable_scheduler: bool = True
    session_max_age_sec: int = 604800

    def normalized_base_path(self) -> str:
        """Return the base path normalized with a leading slash and no trailing slash.

        Returns:
            str: Normalized base path (for example `/radar` or empty string for root).
        """
        cleaned = self.app_base_path.strip().rstrip("/")
        if not cleaned or cleaned == "/":
            return ""
        return cleaned if cleaned.startswith("/") else f"/{cleaned}"

    def cookie_path(self) -> str:
        """Return the HTTP cookie path scoped to the configured subpath.

        Returns:
            str: Cookie path ending with a trailing slash.
        """
        base = self.normalized_base_path()
        return f"{base}/" if base else "/"
