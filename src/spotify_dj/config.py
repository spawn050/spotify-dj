"""Settings, loaded from the project's .env (never from the working directory)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Claude Code starts the server from whatever folder the user is in,
# so every file we touch is anchored to the project root instead.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOKEN_PATH = PROJECT_ROOT / ".spotify_token.json"
LOG_DIR = PROJECT_ROOT / "logs"

DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"


class ConfigError(Exception):
    """The environment is missing or has invalid settings."""


@dataclass(frozen=True)
class Settings:
    client_id: str
    redirect_uri: str = DEFAULT_REDIRECT_URI
    queue_depth: int = 3
    poll_seconds: float = 5.0

    @classmethod
    def load(cls, env: Mapping[str, str] | None = None) -> "Settings":
        if env is None:
            load_dotenv(PROJECT_ROOT / ".env")
            env = os.environ

        client_id = env.get("SPOTIFY_CLIENT_ID", "").strip()
        if not client_id:
            raise ConfigError(f"SPOTIFY_CLIENT_ID is not set. Add it to {PROJECT_ROOT / '.env'}.")

        try:
            queue_depth = int(env.get("DJ_QUEUE_DEPTH", cls.queue_depth))
            poll_seconds = float(env.get("DJ_POLL_SECONDS", cls.poll_seconds))
        except ValueError as error:
            raise ConfigError(f"Invalid number in settings: {error}") from error
        if queue_depth < 1:
            raise ConfigError("DJ_QUEUE_DEPTH must be at least 1.")
        if poll_seconds <= 0:
            raise ConfigError("DJ_POLL_SECONDS must be greater than 0.")

        return cls(
            client_id=client_id,
            redirect_uri=env.get("SPOTIFY_REDIRECT_URI", DEFAULT_REDIRECT_URI),
            queue_depth=queue_depth,
            poll_seconds=poll_seconds,
        )
