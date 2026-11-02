"""Secure Telegram deep-link token generation and validation."""

from __future__ import annotations

import re
import secrets

TOKEN_PATTERN = re.compile(r"^f_[A-Za-z0-9_-]{20,50}$")
WEBSITE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def generate_token() -> str:
    token = f"f_{secrets.token_urlsafe(18)}"
    if len(token) > 64:  # Defensive guard against future changes.
        raise RuntimeError("Generated Telegram payload is too long")
    return token


def is_valid_token(token: str) -> bool:
    return len(token) <= 64 and TOKEN_PATTERN.fullmatch(token) is not None


def validate_website_id(website_id: str) -> str:
    if WEBSITE_ID_PATTERN.fullmatch(website_id) is None:
        raise ValueError(
            "Website ID must be 1-100 ASCII letters, numbers, dots, "
            "underscores, or hyphens"
        )
    return website_id


def build_deep_link(bot_username: str, token: str) -> str:
    if not is_valid_token(token):
        raise ValueError("Invalid public token")
    username = bot_username.lstrip("@")
    if not username:
        raise ValueError("Bot username is required")
    return f"https://t.me/{username}?start={token}"
