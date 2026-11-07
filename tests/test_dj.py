import pytest

from spotify_dj.dj import DJ
from spotify_dj.factory import SourceFactory, SourceSpec
from spotify_dj.mixer import Mixer, UnknownSourceError
from tests.fakes import Clock, FakeGateway, make_tracks

TAYLOR = 'artist:"Taylor Swift"'
ONE_D = 'artist:"One Direction"'


def search(artist: str, **kwargs) -> SourceSpec:
    return SourceSpec(type="search", artist=artist, **kwargs)


@pytest.fixture
def gateway() -> FakeGateway:
    fake = FakeGateway()
    fake.search_results[TAYLOR] = make_tracks("Taylor Swift", 10)
    fake.search_results[ONE_D] = make_tracks("One Direction", 10)
    fake.current = make_tracks("Someone", 1, "now")[0]
    return fake


def make_dj(gateway: FakeGateway, depth: int = 3, clock: Clock | None = None) -> DJ:
    return DJ(gateway, SourceFactory(gateway), Mixer(), depth, clock=clock or Clock())


def test_tick_fills_the_queue_so_the_playing_song_plus_queued_equals_depth(gateway):
    dj = make_dj(gateway)
    dj.set_mix([search("Taylor Swift")])

    dj.tick()

    assert len(gateway.queue) == 2


def test_tick_adds_one_song_each_time_a_song_starts(gateway):
    clock = Clock()
    dj = make_dj(gateway, clock=clock)
    dj.set_mix([search("Taylor Swift")])
    dj.tick()

    gateway.advance()
    clock.advance(10)  # a song takes far longer than Spotify's queue lag
    dj.tick()

    assert len(gateway.queue) == 2
    assert [t.uri for t in gateway.queue][-1] == make_tracks("Taylor Swift", 10)[2].uri


def test_tick_is_idempotent_when_the_queue_is_full(gateway):
    dj = make_dj(gateway)
    dj.set_mix([search("Taylor Swift")])

    dj.tick()
    dj.tick()

    assert len(gateway.queue) == 2


def test_queue_depth_is_configurable(gateway):
    dj = make_dj(gateway, depth=5)
    dj.set_mix([search("Taylor Swift")])

    dj.tick()

    assert len(gateway.queue) == 4


def test_a_skipped_queue_is_refilled(gateway):
    clock = Clock()
    dj = make_dj(gateway, clock=clock)
    dj.set_mix([search("Taylor Swift")])
    dj.tick()

    gateway.skip_queue()
    clock.advance(10)
    dj.tick()

    assert len(gateway.queue) == 2


def test_empty_mix_queues_nothing(gateway):
    dj = make_dj(gateway)

    dj.tick()

    assert gateway.queue == []
    assert dj.problem is None


def test_nothing_playing_is_reported_and_resolves_once_playback_starts(gateway):
    dj = make_dj(gateway)
    dj.set_mix([search("Taylor Swift")])
    gateway.current = None

    dj.tick()
    assert "Nothing is playing" in dj.problem
    assert gateway.queue == []

    gateway.current = make_tracks("Someone", 1)[0]
    dj.tick()
    assert dj.problem is None
    assert len(gateway.queue) == 2


def test_losing_the_device_is_reported_not_raised(gateway):
    dj = make_dj(gateway)
    dj.set_mix([search("Taylor Swift")])
    gateway.no_device = True

    dj.tick()

    assert "No active Spotify device" in dj.problem


def test_set_mix_replaces_and_add_blends(gateway):
    dj = make_dj(gateway)
    dj.set_mix([search("Taylor Swift")])

    dj.add_to_mix([search("One Direction")])
    assert dj.status().mix == {"Taylor Swift": 1, "One Direction": 1}

    dj.set_mix([search("One Direction")])
    assert dj.status().mix == {"One Direction": 1}


def test_a_failed_request_is_flagged_and_keeps_the_old_mix(gateway):
    dj = make_dj(gateway)
    dj.set_mix([search("Taylor Swift")])

    report = dj.set_mix([search("Nobody Real")])

    assert report.added == []
    assert "Nobody Real" in report.flags[0]
    assert dj.status().mix == {"Taylor Swift": 1}


def test_a_partly_successful_request_applies_what_it_can(gateway):
    dj = make_dj(gateway)

    report = dj.add_to_mix([search("Taylor Swift"), search("Nobody Real")])

    assert report.added == ["Taylor Swift"]
    assert len(report.flags) == 1


def test_weights_and_stop(gateway):
    dj = make_dj(gateway)
    dj.set_mix([search("Taylor Swift"), search("One Direction")])

    dj.set_weight("Taylor Swift", 3)
    assert dj.status().mix["Taylor Swift"] == 3
    with pytest.raises(UnknownSourceError):
        dj.set_weight("Adele", 2)

    dj.stop()
    assert dj.status().mix == {}


def test_status_shows_now_playing_and_our_upcoming_songs(gateway):
    dj = make_dj(gateway)
    dj.set_mix([search("Taylor Swift")])
    dj.tick()

    status = dj.status()

    assert status.now_playing == gateway.current
    assert [t.uri for t in status.up_next] == [t.uri for t in gateway.queue]


def test_songs_not_yet_visible_in_spotifys_queue_are_not_queued_twice(gateway):
    clock = Clock()
    dj = make_dj(gateway, clock=clock)
    dj.set_mix([search("Taylor Swift")])
    dj.tick()

    gateway.queue_visible = False  # Spotify's queue read lags behind the write
    clock.advance(1)
    dj.tick()

    assert len(gateway.queue) == 2  # no duplicates added
    assert len(dj.status().up_next) == 2


def test_songs_that_never_show_up_are_forgotten_after_the_grace_period(gateway):
    clock = Clock()
    dj = make_dj(gateway, clock=clock)
    dj.set_mix([search("Taylor Swift")])
    dj.tick()

    gateway.queue_visible = False
    clock.advance(10)  # long past the lag window: they really are gone
    dj.tick()

    assert len(gateway.queue) == 4
