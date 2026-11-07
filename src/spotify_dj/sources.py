"""Where the DJ's next song can come from.

Every source is a lazy stream of tracks. A subclass only says how to produce
them (`_generate`); the base class provides peeking, exhaustion and reset, so
the Mixer can treat all sources the same.
"""

import re
import unicodedata
from abc import ABC, abstractmethod
from collections.abc import Collection, Iterator
from itertools import islice

from spotify_dj.models import Track
from spotify_dj.spotify import SEARCH_PAGE_SIZE, TIME_RANGES, SpotifyGateway

# Spotify search cannot page past offset 1000.
MAX_SEARCH_OFFSET = 1000
_YEAR = re.compile(r"^\d{4}(-\d{4})?$")
# Spotify search is full of karaoke / tribute / instrumental re-recordings of real hits.
_JUNK = re.compile(
    r"\b(karaoke|instrumental|tribute|made famous|originally performed|backing track)\b", re.IGNORECASE
)


class InvalidRuleError(ValueError):
    """A search rule Spotify cannot answer."""


def build_search_query(
    *,
    artist: str | None = None,
    year: str | None = None,
    genre: str | None = None,
    album: str | None = None,
) -> str:
    """Turn structured filters into Spotify's query syntax. There is deliberately
    no mood/energy filter: Spotify cannot answer those."""
    if year is not None and not _YEAR.match(year):
        raise InvalidRuleError(f"year must look like 2015 or 2010-2015, got {year!r}")

    parts = []
    for field, value in (("artist", artist), ("album", album), ("genre", genre)):
        if value and value.strip():
            parts.append(f'{field}:"{value.strip().replace(chr(34), "")}"')
    if year:
        parts.append(f"year:{year}")
    if not parts:
        raise InvalidRuleError("a search needs at least one of artist, album, genre or year")
    return " ".join(parts)


def _fold(text: str) -> str:
    """Case- and accent-insensitive form, so "Beyonce" matches "Beyoncé"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def is_wanted(track: Track, artist: str | None = None) -> bool:
    """False for karaoke-style junk and, when `artist` is given, for tracks not credited to
    them (Spotify's artist match is fuzzy: "Taylor Swift" also finds "Spanish Swift")."""
    if _JUNK.search(f"{track.name} {track.album}"):
        return False
    return artist is None or any(_fold(a) == _fold(artist) for a in track.artists)


class Source(ABC):
    def __init__(self) -> None:
        self._stream: Iterator[Track] | None = None
        self._lookahead: Track | None = None

    @abstractmethod
    def _generate(self) -> Iterator[Track]:
        """Produce this source's tracks, lazily and in order."""

    def next_track(self) -> Track | None:
        """The next track, or None once the source is used up."""
        track = self.peek()
        self._lookahead = None
        return track

    def peek(self) -> Track | None:
        if self._lookahead is None:
            if self._stream is None:
                self._stream = self._generate()
            self._lookahead = next(self._stream, None)
        return self._lookahead

    def reset(self) -> None:
        self._stream = None
        self._lookahead = None


class SearchSource(Source):
    """Pages through Spotify search results, 10 at a time, skipping unwanted tracks."""

    def __init__(self, gateway: SpotifyGateway, query: str, artist: str | None = None) -> None:
        super().__init__()
        self._gateway = gateway
        self._query = query
        self._artist = artist  # when set, only tracks credited to this artist

    def _generate(self) -> Iterator[Track]:
        # Offsets count result slots, and Spotify may return fewer than 10 per page,
        # so step by the page size rather than by how many tracks came back.
        for offset in range(0, MAX_SEARCH_OFFSET, SEARCH_PAGE_SIZE):
            page = self._gateway.search_tracks(self._query, offset)
            if not page:
                return
            yield from (track for track in page if is_wanted(track, self._artist))


class TopTracksSource(Source):
    """The user's top tracks across all time ranges, optionally only some artists."""

    def __init__(self, gateway: SpotifyGateway, artists: Collection[str] | None = None) -> None:
        super().__init__()
        self._gateway = gateway
        self._artists = {_fold(name) for name in artists or ()}
        self._tracks: list[Track] | None = None  # fetched once per session

    def _generate(self) -> Iterator[Track]:
        if self._tracks is None:
            merged: dict[str, Track] = {}
            for time_range in TIME_RANGES:
                for track in self._gateway.top_tracks(time_range):
                    merged.setdefault(track.uri, track)
            self._tracks = [t for t in merged.values() if self._wanted(t)]
        yield from self._tracks

    def _wanted(self, track: Track) -> bool:
        return not self._artists or any(_fold(a) in self._artists for a in track.artists)


class PinnedSource(Source):
    """A fixed list of songs, e.g. ones Claude picked for a mood."""

    def __init__(self, tracks: Collection[Track]) -> None:
        super().__init__()
        self._tracks = list(tracks)

    def _generate(self) -> Iterator[Track]:
        yield from self._tracks


class ChainedSource(Source):
    """Drains its sources one after another (a fallback chain)."""

    def __init__(self, *sources: Source) -> None:
        super().__init__()
        self._sources = sources

    def _generate(self) -> Iterator[Track]:
        for source in self._sources:
            while (track := source.next_track()) is not None:
                yield track

    def reset(self) -> None:
        super().reset()
        for source in self._sources:
            source.reset()


class InterleavedSource(Source):
    """Takes turns between its sources, so no single one dominates."""

    def __init__(self, *sources: Source) -> None:
        super().__init__()
        self._sources = sources

    def _generate(self) -> Iterator[Track]:
        live = list(self._sources)
        while live:
            for source in list(live):
                track = source.next_track()
                if track is None:
                    live.remove(source)
                else:
                    yield track

    def reset(self) -> None:
        super().reset()
        for source in self._sources:
            source.reset()


def take(source: Source, count: int) -> list[Track]:
    """Pull up to `count` tracks (handy in tests and previews)."""
    return list(islice(iter(source.next_track, None), count))
