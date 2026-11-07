"""Tests against the real Spotify API. Skipped by default; run with:

    uv run pytest -m live

Needs `spotify-dj login` done and a Premium account. The last test queues
real songs, so Spotify must be playing on a device (Spotify cannot remove
queued songs afterwards).
"""

import pytest

from spotify_dj.config import ConfigError, Settings
from spotify_dj.dj import DJ
from spotify_dj.factory import SourceFactory, SourceSpec
from spotify_dj.mixer import Mixer
from spotify_dj.spotify import NotLoggedInError, SpotipyGateway, connect

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.load()
    except ConfigError as error:
        pytest.skip(str(error))


@pytest.fixture(scope="module")
def gateway(settings) -> SpotipyGateway:
    try:
        return connect(settings)
    except NotLoggedInError as error:
        pytest.skip(str(error))


def test_search_honours_filters_and_the_ten_result_cap(gateway):
    tracks = gateway.search_tracks('artist:"Taylor Swift" year:2015')

    assert 0 < len(tracks) <= 10
    assert all(track.uri.startswith("spotify:track:") for track in tracks)


def test_search_pages_with_offset(gateway):
    first = gateway.search_tracks('artist:"Taylor Swift"', offset=0)
    second = gateway.search_tracks('artist:"Taylor Swift"', offset=10)

    assert {t.uri for t in first}.isdisjoint({t.uri for t in second})


def test_top_tracks_and_artists_are_readable(gateway):
    assert isinstance(gateway.top_tracks("medium_term"), list)
    assert isinstance(gateway.top_artists("medium_term"), list)


def test_dj_queues_songs_from_a_search_mix(gateway, settings):
    if gateway.playback().current is None:
        pytest.skip("Start playing something in Spotify on any device first.")
    dj = DJ(gateway, SourceFactory(gateway), Mixer(), settings.queue_depth)

    report = dj.set_mix([SourceSpec(type="search", artist="Taylor Swift", year="2015")])
    dj.tick()

    assert report.added and not report.flags
    assert dj.problem is None
    assert len(dj.status().up_next) == settings.queue_depth - 1
