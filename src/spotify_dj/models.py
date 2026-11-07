from dataclasses import dataclass


@dataclass(frozen=True)
class Track:
    uri: str
    name: str
    artists: tuple[str, ...]

    def __str__(self) -> str:
        return f"{self.name} - {', '.join(self.artists)}"


@dataclass(frozen=True)
class Playback:
    """What Spotify is playing now and which tracks are lined up next."""

    current: Track | None
    upcoming_uris: tuple[str, ...]
