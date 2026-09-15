"""Runtime configuration, intentionally kept dependency-free."""

from dataclasses import dataclass
from os import getenv
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "Cascading Failure API"
    version: str = "0.5.0"
    environment: str = "development"
    allowed_origins: tuple[str, ...] = ("http://localhost:5173", "http://localhost:3000")
    database_path: Path = Path("data/cascading_failure.db")
    api_key: str | None = None


def get_settings() -> Settings:
    origins = tuple(
        origin.strip()
        for origin in getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
        if origin.strip()
    )
    return Settings(
        environment=getenv("APP_ENV", "development"),
        allowed_origins=origins,
        database_path=Path(getenv("DATABASE_PATH", "data/cascading_failure.db")),
        api_key=getenv("API_KEY") or None,
    )
