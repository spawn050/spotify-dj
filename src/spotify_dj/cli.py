import sys

from spotify_dj.config import ConfigError, Settings
from spotify_dj.spotify import make_auth_manager


def login() -> None:
    """One-time browser login; saves the token so the server can run unattended."""
    auth = make_auth_manager(Settings.load())
    auth.get_access_token()
    print("Logged in to Spotify. You can now start the DJ from Claude Code.")


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "serve"
    try:
        if command == "login":
            login()
        else:
            sys.exit(f"Unknown command: {command}. Use `login` or no argument to serve.")
    except ConfigError as error:
        sys.exit(str(error))
