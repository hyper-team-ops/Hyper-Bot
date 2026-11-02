"""Environment-backed application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(RuntimeError):
    """Raised when required configuration is invalid or missing."""


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Load a simple .env file without overriding real environment variables."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"Missing required environment variable: {name}")
    return value


def _integer(name: str) -> int:
    value = _required(name)
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc


def _integer_set(name: str, *, required: bool = True) -> frozenset[int]:
    raw = _required(name) if required else os.getenv(name, "")
    try:
        values = frozenset(int(item.strip()) for item in raw.split(",") if item.strip())
    except ValueError as exc:
        raise ConfigurationError(f"{name} must contain comma-separated integers") from exc
    if required and not values:
        raise ConfigurationError(f"{name} must contain at least one user ID")
    return values


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    bot_username: str
    source_channel_id: int
    download_request_chat_id: int
    complaint_recipient_chat_id: int
    admin_user_ids: frozenset[int]
    admin_chat_ids: frozenset[int]
    database_url: str
    log_level: str
    rate_limit_requests: int
    rate_limit_window_seconds: int

    @classmethod
    def from_env(cls, *, dotenv_path: Path = Path(".env")) -> "Settings":
        _load_dotenv(dotenv_path)
        username = _required("BOT_USERNAME").lstrip("@")
        database_url = os.getenv("DATABASE_URL", "sqlite:///data/hyperbot.db").strip()
        if not database_url.startswith("sqlite:///"):
            raise ConfigurationError("Only sqlite:/// DATABASE_URL values are currently supported")
        try:
            requests = int(os.getenv("RATE_LIMIT_REQUESTS", "5"))
            window = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
        except ValueError as exc:
            raise ConfigurationError("Rate-limit settings must be integers") from exc
        if requests < 1 or window < 1:
            raise ConfigurationError("Rate-limit settings must be positive")
        return cls(
            bot_token=_required("BOT_TOKEN"),
            bot_username=username,
            source_channel_id=_integer("SOURCE_CHANNEL_ID"),
            download_request_chat_id=_integer("DOWNLOAD_REQUEST_CHAT_ID"),
            complaint_recipient_chat_id=_integer("COMPLAINT_RECIPIENT_CHAT_ID"),
            admin_user_ids=_integer_set("ADMIN_USER_IDS"),
            admin_chat_ids=_integer_set("ADMIN_CHAT_IDS", required=False),
            database_url=database_url,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            rate_limit_requests=requests,
            rate_limit_window_seconds=window,
        )

    @property
    def database_path(self) -> Path:
        return Path(self.database_url.removeprefix("sqlite:///"))
