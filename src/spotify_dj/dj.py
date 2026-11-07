from collections import Counter
from dataclasses import dataclass

from spotify_dj.factory import SourceFactory, SourceSpec
from spotify_dj.mixer import Mixer
from spotify_dj.models import Track
from spotify_dj.sources import InvalidRuleError
from spotify_dj.spotify import NoActiveDeviceError, SpotifyGateway


@dataclass(frozen=True)
class MixReport:
    added: list[str]  # names of sources that joined the mix
    flags: list[str]  # things Spotify could not do, to relay to the user


@dataclass(frozen=True)
class Status:
    now_playing: Track | None
    up_next: tuple[Track, ...]
    mix: dict[str, int]
    problem: str | None


class DJ:
    """Keeps Spotify's queue stocked from the mix.

    Not thread-safe: callers must not run its methods concurrently.
    """

    def __init__(
        self, gateway: SpotifyGateway, factory: SourceFactory, mixer: Mixer, queue_depth: int
    ) -> None:
        self._gateway = gateway
        self._factory = factory
        self._mixer = mixer
        self._depth = queue_depth
        self._pending: list[Track] = []  # songs we queued that have not started yet
        self.problem: str | None = None  # latest reason the queue could not be filled

    # --- changing the mix -------------------------------------------------
    def set_mix(self, specs: list[SourceSpec]) -> MixReport:
        """Replace the mix. If nothing usable was requested, the old mix is kept."""
        return self._apply(specs, replace=True)

    def add_to_mix(self, specs: list[SourceSpec]) -> MixReport:
        return self._apply(specs, replace=False)

    def set_weight(self, name: str, weight: int) -> None:
        self._mixer.set_weight(name, weight)

    def stop(self) -> None:
        """Stop adding songs. Songs already in Spotify's queue will still play."""
        self._mixer.clear()

    def _apply(self, specs: list[SourceSpec], *, replace: bool) -> MixReport:
        built, flags = [], []
        for spec in specs:
            try:
                item = self._factory.build(spec)
            except InvalidRuleError as error:
                flags.append(str(error))
            else:
                built.append(item)
                flags.extend(item.notes)
        if built and replace:
            self._mixer.clear()
        for item in built:
            self._mixer.add(item.name, item.source, item.weight)
        return MixReport([item.name for item in built], flags)

    # --- keeping the queue stocked ------------------------------------------
    def tick(self) -> None:
        """Top the queue up to the configured depth (the playing song counts)."""
        self.problem = None
        playback = self._gateway.playback()
        self._forget_started(playback.upcoming_uris)
        if playback.current is None:
            self.problem = "Nothing is playing. Start playback in Spotify on any device."
            return
        while 1 + len(self._pending) < self._depth:
            track = self._mixer.next_track()
            if track is None:
                return
            try:
                self._gateway.add_to_queue(track.uri)
            except NoActiveDeviceError:
                self.problem = "No active Spotify device. Start playback on any device."
                return
            self._pending.append(track)

    def _forget_started(self, upcoming_uris: tuple[str, ...]) -> None:
        """Keep only our songs still waiting in Spotify's queue (others played or were skipped)."""
        waiting = Counter(upcoming_uris)
        still_pending = []
        for track in self._pending:
            if waiting[track.uri] > 0:
                waiting[track.uri] -= 1
                still_pending.append(track)
        self._pending = still_pending

    def status(self) -> Status:
        playback = self._gateway.playback()
        self._forget_started(playback.upcoming_uris)
        return Status(playback.current, tuple(self._pending), self._mixer.weights(), self.problem)
