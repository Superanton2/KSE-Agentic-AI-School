"""Telethon client factory. The collector is strictly read-only: it only resolves public channels and
reads their history/updates; it never sends, joins or modifies anything."""

import os
from pathlib import Path

from telethon import TelegramClient

from airalert.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
# Telethon sleeps by itself on FloodWait shorter than this; longer waits raise and are handled by callers.
FLOOD_SLEEP_THRESHOLD = 24 * 3600


def session_file(path: Path) -> Path:
    """Telethon appends '.session' when the name lacks it."""
    return path if path.suffix == ".session" else path.with_name(path.name + ".session")


def check_session_location(path: Path) -> None:
    if (REPO_ROOT / ".git").exists() and path.is_relative_to(REPO_ROOT):
        raise RuntimeError(
            f"TG_SESSION_PATH must be outside the repository ({REPO_ROOT}); the session grants full access "
            "to the Telegram account."
        )


def secure_session(path: Path) -> None:
    f = session_file(path)
    if f.exists():
        os.chmod(f, 0o600)


def make_client(s: Settings) -> TelegramClient:
    if s.tg_api_id is None or s.tg_api_hash is None:
        raise RuntimeError("TG_API_ID / TG_API_HASH are not set (see .env.example)")
    path = s.session_path
    check_session_location(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    return TelegramClient(
        str(path),
        s.tg_api_id,
        s.tg_api_hash.get_secret_value(),
        flood_sleep_threshold=FLOOD_SLEEP_THRESHOLD,
        receive_updates=True,
    )
