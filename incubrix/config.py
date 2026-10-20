"""Configuration settings for IncuBrix Script-to-B-Roll Video Engine."""

from pathlib import Path
import shutil
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    JOBS_DIR: Path = Field(default=Path("./data/jobs"))
    DB_PATH: Path = Field(default=Path("./data/incubrix.db"))
    STORAGE_DIR: Path = Field(default=Path("./data/storage"))
    CACHE_DIR: Path = Field(default=Path("./data/cache"))
    RENDERS_DIR: Path = Field(default=Path("./renders"))
    AGY_BIN_PATH: str = Field(
        default_factory=lambda: shutil.which("agy") or "/home/sooriya/.local/bin/agy"
    )
    AGY_MOCK: bool = Field(default=False)
    JOB_TIMEOUT_SECONDS: int = Field(default=900)
    WEBHOOK_SECRET: str = Field(default="secret")
    REQUIRE_IDEMPOTENCY_KEY: bool = Field(default=False)

    PIXABAY_API_KEY: Optional[str] = Field(default=None)
    PEXELS_API_KEY: Optional[str] = Field(default=None)

    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8000)

    def ensure_directories(self) -> None:
        """Ensure all required runtime directories exist."""
        self.JOBS_DIR.mkdir(parents=True, exist_ok=True)
        self.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.RENDERS_DIR.mkdir(parents=True, exist_ok=True)
        self.JOBS_DIR.parent.mkdir(parents=True, exist_ok=True)
        (self.STORAGE_DIR / "uploads").mkdir(parents=True, exist_ok=True)

    def model_post_init(self, __context) -> None:
        self.ensure_directories()


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


settings = get_settings()
