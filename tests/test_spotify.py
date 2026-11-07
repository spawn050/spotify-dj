import pytest
import spotipy

from spotify_dj.config import Settings
from spotify_dj.models import Track
from spotify_dj.spotify import (
    NoActiveDeviceError,
    NotLoggedInError,
    SpotifyError,
    SpotipyGateway,
    connect,
)


def _item(uri: str, name: str, *artists: str) -> dict:
    return {"uri": uri, "name": name, "artists": [{"name": a} for a in artists]}


class FakeSpotipy:
    def __init__(self) -> None:
        self.search_args: dict = {}
        self.queue_error: Exception | None = None
        self.queued: list[str] = []

    def search(self, **kwargs):
        self.search_args = kwargs
        return {"tracks": {"items": [_item("spotify:track:1", "Style", "Taylor Swift"), None]}}

    def current_user_top_tracks(self, **kwargs):
        return {"items": [_item("spotify:track:2", "Story of My Life", "One Direction")]}

    def current_user_top_artists(self, **kwargs):
        return {"items": [{"name": "The Script"}]}

    def queue(self):
        return {
            "currently_playing": _item("spotify:track:1", "Style", "Taylor Swift"),
            "queue": [_item("spotify:track:2", "Story of My Life", "One Direction")],
        }

    def add_to_queue(self, uri):
        if self.queue_error:
            raise self.queue_error
        self.queued.append(uri)


@pytest.fixture
def client() -> FakeSpotipy:
    return FakeSpotipy()


def test_search_requests_ten_results_and_skips_null_items(client):
    tracks = SpotipyGateway(client).search_tracks("artist:Taylor", offset=20)

    assert tracks == [Track("spotify:track:1", "Style", ("Taylor Swift",))]
    assert client.search_args["limit"] == 10
    assert client.search_args["offset"] == 20


def test_top_tracks_and_artists_are_mapped(client):
    gateway = SpotipyGateway(client)

    assert gateway.top_tracks("short_term")[0].name == "Story of My Life"
    assert gateway.top_artists("long_term") == ["The Script"]


def test_playback_maps_current_and_upcoming(client):
    playback = SpotipyGateway(client).playback()

    assert playback.current.name == "Style"
    assert playback.upcoming_uris == ("spotify:track:2",)


def test_playback_with_nothing_playing(client):
    client.queue = lambda: {}

    playback = SpotipyGateway(client).playback()

    assert playback.current is None
    assert playback.upcoming_uris == ()


def test_queueing_without_a_device_raises_domain_error(client):
    client.queue_error = spotipy.SpotifyException(404, -1, "NO_ACTIVE_DEVICE")

    with pytest.raises(NoActiveDeviceError):
        SpotipyGateway(client).add_to_queue("spotify:track:1")


def test_other_spotify_errors_become_readable_domain_errors(client):
    client.queue_error = spotipy.SpotifyException(403, -1, "Premium required")

    with pytest.raises(SpotifyError, match="403.*Premium required"):
        SpotipyGateway(client).add_to_queue("spotify:track:1")


def test_connect_without_saved_login_refuses_to_start_interactive_auth(tmp_path, monkeypatch):
    monkeypatch.setattr("spotify_dj.spotify.TOKEN_PATH", tmp_path / "missing.json")

    with pytest.raises(NotLoggedInError):
        connect(Settings(client_id="abc"))
