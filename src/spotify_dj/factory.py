"""Turns a request from Claude (a SourceSpec) into a playable Source."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from spotify_dj.models import Track
from spotify_dj.sources import (
    ChainedSource,
    InterleavedSource,
    InvalidRuleError,
    PinnedSource,
    SearchSource,
    Source,
    TopTracksSource,
    build_search_query,
    is_wanted,
)
from spotify_dj.spotify import TIME_RANGES, SpotifyGateway

TOP_ARTIST_LIMIT = 10


class TrackRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    artist: str


class SourceSpec(BaseModel):
    # Reject unknown fields (e.g. a made-up `mood`) instead of silently ignoring them,
    # so an impossible request fails loudly and Claude can tell the user.
    model_config = ConfigDict(extra="forbid")

    type: Literal["search", "top_tracks", "pinned"]
    name: str | None = Field(None, description="Unique label for this source; used to change its weight later.")
    weight: int = Field(1, ge=1, description="Share of the mix relative to other sources.")
    artist: str | None = Field(None, description="search: artist name.")
    year: str | None = Field(None, description="search: '2015' or a range like '2010-2015'.")
    genre: str | None = Field(None, description="search: Spotify genre, e.g. 'k-pop'.")
    album: str | None = Field(None, description="search: album name.")
    artists: list[str] | None = Field(
        None, description="top_tracks: only the user's favourites by these artists (omit for all)."
    )
    tracks: list[TrackRef] | None = Field(None, description="pinned: songs you chose, by title and artist.")


@dataclass
class BuiltSource:
    name: str
    source: Source
    weight: int
    notes: list[str] = field(default_factory=list)  # things the user should be told


class SourceFactory:
    def __init__(self, gateway: SpotifyGateway) -> None:
        self._gateway = gateway

    def build(self, spec: SourceSpec) -> BuiltSource:
        """Raises InvalidRuleError when Spotify cannot supply anything for the spec."""
        match spec.type:
            case "search":
                built = self._search(spec)
            case "top_tracks":
                built = self._top_tracks(spec)
            case "pinned":
                built = self._pinned(spec)
        if built.source.peek() is None:
            raise InvalidRuleError(f"Spotify found nothing for '{built.name}'")
        return built

    def _search(self, spec: SourceSpec) -> BuiltSource:
        query = build_search_query(
            artist=spec.artist, year=spec.year, genre=spec.genre, album=spec.album
        )
        default = " ".join(filter(None, [spec.artist, spec.album, spec.genre, spec.year]))
        return BuiltSource(
            spec.name or default, SearchSource(self._gateway, query, spec.artist), spec.weight
        )

    def _top_tracks(self, spec: SourceSpec) -> BuiltSource:
        """The user's favourites first, then more songs by those same artists."""
        artists = spec.artists or self._top_artists()
        fallback = InterleavedSource(
            *(SearchSource(self._gateway, build_search_query(artist=a), a) for a in artists)
        )
        source = ChainedSource(TopTracksSource(self._gateway, spec.artists), fallback)
        default = "My top tracks" + (f" by {', '.join(spec.artists)}" if spec.artists else "")
        return BuiltSource(spec.name or default, source, spec.weight)

    def _pinned(self, spec: SourceSpec) -> BuiltSource:
        found: list[Track] = []
        missing: list[str] = []
        for ref in spec.tracks or []:
            query = f'track:"{_clean(ref.title)}" artist:"{_clean(ref.artist)}"'
            results = self._gateway.search_tracks(query)
            match = next((t for t in results if is_wanted(t, ref.artist)), None)
            if match:
                found.append(match)
            else:
                missing.append(f"{ref.title} - {ref.artist}")
        notes = [f"Not found on Spotify: {', '.join(missing)}"] if missing else []
        name = spec.name or f"Picked songs ({len(found)})"
        return BuiltSource(name, PinnedSource(found), spec.weight, notes)

    def _top_artists(self) -> list[str]:
        names: dict[str, None] = {}
        for time_range in TIME_RANGES:
            names.update(dict.fromkeys(self._gateway.top_artists(time_range)))
        return list(names)[:TOP_ARTIST_LIMIT]


def _clean(text: str) -> str:
    return text.replace('"', "").strip()
