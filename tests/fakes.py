from spotify_dj.models import Playback, Track
from spotify_dj.spotify import SEARCH_PAGE_SIZE, NoActiveDeviceError


def make_tracks(artist: str, count: int, prefix: str = "") -> list[Track]:
    return [
        Track(f"spotify:track:{prefix or artist}-{i}", f"{prefix or artist} song {i}", (artist,))
        for i in range(count)
    ]


class FakeGateway:
    """In-memory Spotify. Search results are keyed by the exact query string."""

    def __init__(self) -> None:
        self.search_results: dict[str, list[Track]] = {}
        self.top: dict[str, list[Track]] = {}
        self.artists: dict[str, list[str]] = {}
        self.current: Track | None = None
        self.queue: list[Track] = []
        self.no_device = False
        self.queue_visible = True  # False simulates Spotify's queue read lagging behind writes
        self.search_calls: list[tuple[str, int]] = []

    def search_tracks(self, query: str, offset: int = 0) -> list[Track]:
        self.search_calls.append((query, offset))
        return self.search_results.get(query, [])[offset : offset + SEARCH_PAGE_SIZE]

    def top_tracks(self, time_range: str) -> list[Track]:
        return self.top.get(time_range, [])

    def top_artists(self, time_range: str) -> list[str]:
        return self.artists.get(time_range, [])

    def playback(self) -> Playback:
        upcoming = tuple(t.uri for t in self.queue) if self.queue_visible else ()
        return Playback(self.current, upcoming)

    def add_to_queue(self, uri: str) -> None:
        if self.no_device:
            raise NoActiveDeviceError
        self.queue.append(Track(uri, uri, ()))

    # --- helpers that simulate what the Spotify player does ---
    def advance(self) -> None:
        """The current song ends and the next queued one starts."""
        self.current = self.queue.pop(0) if self.queue else None

    def skip_queue(self) -> None:
        """The user clears or skips past everything we queued."""
        self.queue.clear()


class Clock:
    """A manually advanced clock, so tests control the DJ's queue-lag grace period."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
