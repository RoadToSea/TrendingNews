"""Application settings loaded from environment variables."""

from pathlib import Path
from typing import Optional

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
    agy_bin: str = "agy"
    agy_proxy: str = ""
    agy_workspace: Path = Path("data/agy-sandbox")
    agy_max_concurrency: int = 2
    agy_timeout_sec: int = 180
    cors_origins: str = ""
    legacy_repo_root: Optional[Path] = None
    enable_scheduler: bool = True
    session_max_age_sec: int = 604800

    def resolved_legacy_root(self) -> Path:
        """Resolve the repository root directory containing the legacy `trendradar` package.

        Returns:
            Path: Explicit `legacy_repo_root` when set, otherwise two levels above `backend/app`.
        """
        if self.legacy_repo_root is not None:
            return self.legacy_repo_root
        return Path(__file__).resolve().parents[2]

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
