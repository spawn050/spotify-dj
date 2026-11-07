"""The only module that talks to Spotify. The rest of the app depends on SpotifyGateway."""

from collections.abc import Callable
from functools import wraps
from typing import Literal, Protocol

import spotipy
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyPKCE

from spotify_dj.config import TOKEN_PATH, Settings
from spotify_dj.models import Playback, Track

SCOPES = (
    "user-top-read user-read-playback-state "
    "user-modify-playback-state user-read-currently-playing"
)
TIME_RANGES = ("short_term", "medium_term", "long_term")
TimeRange = Literal["short_term", "medium_term", "long_term"]

# Development Mode apps may request at most 10 search results per call (Feb 2026).
SEARCH_PAGE_SIZE = 10


class NoActiveDeviceError(Exception):
    """Spotify has no device to play on, so nothing can be queued."""


class SpotifyError(Exception):
    """Spotify rejected a request (e.g. the account is not Premium)."""


class NotLoggedInError(Exception):
    """No saved Spotify login; the user must run `spotify-dj login`."""


class SpotifyGateway(Protocol):
    def search_tracks(self, query: str, offset: int = 0) -> list[Track]: ...

    def top_tracks(self, time_range: TimeRange) -> list[Track]: ...

    def top_artists(self, time_range: TimeRange) -> list[str]: ...

    def playback(self) -> Playback: ...

    def add_to_queue(self, uri: str) -> None: ...


def _to_track(item: dict) -> Track:
    return Track(
        uri=item["uri"],
        name=item["name"],
        artists=tuple(artist["name"] for artist in item["artists"]),
        album=item.get("album", {}).get("name", ""),
    )


def _readable_errors[**P, R](method: Callable[P, R]) -> Callable[P, R]:
    """Show callers a SpotifyError instead of spotipy's raw exception."""

    @wraps(method)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return method(*args, **kwargs)
        except spotipy.SpotifyException as error:
            raise SpotifyError(f"Spotify returned {error.http_status}: {error.msg}") from error

    return wrapper


class SpotipyGateway:
    def __init__(self, client: spotipy.Spotify) -> None:
        self._client = client

    @_readable_errors
    def search_tracks(self, query: str, offset: int = 0) -> list[Track]:
        result = self._client.search(q=query, type="track", limit=SEARCH_PAGE_SIZE, offset=offset)
        return [_to_track(item) for item in result["tracks"]["items"] if item]

    @_readable_errors
    def top_tracks(self, time_range: TimeRange) -> list[Track]:
        result = self._client.current_user_top_tracks(limit=50, time_range=time_range)
        return [_to_track(item) for item in result["items"]]

    @_readable_errors
    def top_artists(self, time_range: TimeRange) -> list[str]:
        result = self._client.current_user_top_artists(limit=50, time_range=time_range)
        return [item["name"] for item in result["items"]]

    @_readable_errors
    def playback(self) -> Playback:
        queue = self._client.queue() or {}
        current = queue.get("currently_playing")
        return Playback(
            current=_to_track(current) if current else None,
            upcoming_uris=tuple(item["uri"] for item in queue.get("queue", [])),
        )

    @_readable_errors
    def add_to_queue(self, uri: str) -> None:
        try:
            self._client.add_to_queue(uri)
        except spotipy.SpotifyException as error:
            if error.http_status == 404:
                raise NoActiveDeviceError from error
            raise


def make_auth_manager(settings: Settings) -> SpotifyPKCE:
    """PKCE needs only the client id, so there is no secret to store or leak."""
    return SpotifyPKCE(
        client_id=settings.client_id,
        redirect_uri=settings.redirect_uri,
        scope=SCOPES,
        cache_handler=CacheFileHandler(cache_path=str(TOKEN_PATH)),
        open_browser=True,
    )


def connect(settings: Settings) -> SpotipyGateway:
    """Build a gateway from the saved login. Never starts an interactive login:
    the MCP server's stdin/stdout belong to the protocol."""
    auth = make_auth_manager(settings)
    if auth.cache_handler.get_cached_token() is None:
        raise NotLoggedInError("Not logged in to Spotify. Run `uv run spotify-dj login` first.")
    return SpotipyGateway(spotipy.Spotify(auth_manager=auth))
