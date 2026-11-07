"""Entry points: `spotify-dj login` (once) and `spotify-dj` (run by Claude Code)."""

import logging
import sys

from spotify_dj.config import LOG_DIR, ConfigError, Settings
from spotify_dj.dj import DJ
from spotify_dj.factory import SourceFactory
from spotify_dj.mixer import Mixer
from spotify_dj.server import build_server
from spotify_dj.session import DJSession
from spotify_dj.spotify import connect, make_auth_manager


def login() -> None:
    """One-time browser login; saves the token so the server can run unattended."""
    make_auth_manager(Settings.load()).get_access_token()
    print("Logged in to Spotify. You can now start the DJ from Claude Code.")


def serve() -> None:
    settings = Settings.load()
    _log_to_file_and_stderr()
    session = DJSession(lambda: _make_dj(settings), settings.poll_seconds)
    build_server(session).run()  # stdio: stdout belongs to the MCP protocol


def _make_dj(settings: Settings) -> DJ:
    gateway = connect(settings)
    return DJ(gateway, SourceFactory(gateway), Mixer(), settings.queue_depth)


def _log_to_file_and_stderr() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_DIR / "spotify-dj.log"), logging.StreamHandler(sys.stderr)],
        force=True,
    )


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "serve"
    commands = {"login": login, "serve": serve}
    if command not in commands:
        sys.exit(f"Unknown command: {command}. Use `login` or `serve` (the default).")
    try:
        commands[command]()
    except ConfigError as error:
        sys.exit(str(error))
