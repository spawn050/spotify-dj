from dataclasses import dataclass

from spotify_dj.models import Track
from spotify_dj.sources import Source


class UnknownSourceError(LookupError):
    """No source with that name is in the mix."""


@dataclass
class _Entry:
    source: Source
    weight: int
    balance: int = 0  # smooth weighted round-robin state


class Mixer:
    """Blends named sources by weight, avoiding repeats until everything is used up."""

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._played: set[str] = set()

    def clear(self) -> None:
        self._entries.clear()
        self._played.clear()

    def add(self, name: str, source: Source, weight: int = 1) -> None:
        """Blend a source in; adding an existing name replaces it."""
        if weight < 1:
            raise ValueError("weight must be at least 1")
        self._entries[name] = _Entry(source, weight)

    def set_weight(self, name: str, weight: int) -> None:
        """Change a source's share of the mix; a weight of 0 removes it."""
        if name not in self._entries:
            raise UnknownSourceError(f"{name!r} is not in the mix. In the mix: {self.weights()}")
        if weight < 0:
            raise ValueError("weight cannot be negative")
        if weight == 0:
            del self._entries[name]
        else:
            self._entries[name].weight = weight

    def weights(self) -> dict[str, int]:
        return {name: entry.weight for name, entry in self._entries.items()}

    def next_track(self) -> Track | None:
        track = self._draw()
        if track is None and self._played:
            self._start_over()
            track = self._draw()
        return track

    def _draw(self) -> Track | None:
        """Pick a source by weight; sources that have nothing new are skipped."""
        candidates = list(self._entries.values())
        while candidates:
            chosen = self._pick(candidates)
            while (track := chosen.source.next_track()) is not None:
                if track.uri not in self._played:
                    self._played.add(track.uri)
                    return track
            candidates.remove(chosen)
        return None

    @staticmethod
    def _pick(candidates: list[_Entry]) -> _Entry:
        for entry in candidates:
            entry.balance += entry.weight
        chosen = max(candidates, key=lambda entry: entry.balance)
        chosen.balance -= sum(entry.weight for entry in candidates)
        return chosen

    def _start_over(self) -> None:
        """Every source is used up: allow repeats by replaying them from the top."""
        self._played.clear()
        for entry in self._entries.values():
            entry.source.reset()
            entry.balance = 0
