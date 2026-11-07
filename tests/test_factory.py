import pytest

from spotify_dj.factory import SourceFactory, SourceSpec, TrackRef
from spotify_dj.sources import InvalidRuleError, take
from tests.fakes import FakeGateway, make_tracks

TAYLOR_2015 = 'artist:"Taylor Swift" year:2015'


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def factory(gateway) -> SourceFactory:
    return SourceFactory(gateway)


def test_search_spec_builds_a_named_search_source(gateway, factory):
    gateway.search_results[TAYLOR_2015] = make_tracks("Taylor Swift", 3)

    built = factory.build(SourceSpec(type="search", artist="Taylor Swift", year="2015", weight=2))

    assert built.name == "Taylor Swift 2015"
    assert built.weight == 2
    assert len(take(built.source, 10)) == 3


def test_search_with_no_results_is_rejected(factory):
    with pytest.raises(InvalidRuleError, match="found nothing"):
        factory.build(SourceSpec(type="search", artist="Nobody Real"))


def test_search_with_unanswerable_filters_is_rejected(factory):
    with pytest.raises(InvalidRuleError):
        factory.build(SourceSpec(type="search"))


def test_pinned_resolves_songs_and_notes_the_missing_ones(gateway, factory):
    song = make_tracks("One Direction", 1)[0]
    gateway.search_results['track:"Drag Me Down" artist:"One Direction"'] = [song]

    built = factory.build(
        SourceSpec(
            type="pinned",
            tracks=[
                TrackRef(title="Drag Me Down", artist="One Direction"),
                TrackRef(title="Made Up Song", artist="One Direction"),
            ],
        )
    )

    assert take(built.source, 10) == [song]
    assert built.notes == ["Not found on Spotify: Made Up Song - One Direction"]


def test_pinned_with_nothing_found_is_rejected(factory):
    with pytest.raises(InvalidRuleError):
        factory.build(SourceSpec(type="pinned", tracks=[TrackRef(title="x", artist="y")]))


def test_top_tracks_for_an_artist_play_favourites_then_search_fallback(gateway, factory):
    favourite = make_tracks("Taylor Swift", 1, "fav")[0]
    other = make_tracks("Coldplay", 1)[0]
    gateway.top = {"medium_term": [other, favourite]}
    catalog = make_tracks("Taylor Swift", 2, "cat")
    gateway.search_results['artist:"Taylor Swift"'] = catalog

    built = factory.build(SourceSpec(type="top_tracks", artists=["Taylor Swift"]))

    assert take(built.source, 10) == [favourite, *catalog]
    assert built.name == "My top tracks by Taylor Swift"


def test_top_tracks_without_artists_fall_back_to_taking_turns_between_top_artists(gateway, factory):
    gateway.top = {"medium_term": make_tracks("fan", 1)}
    gateway.artists = {"medium_term": ["A", "B"], "long_term": ["B", "C"]}
    for artist in "ABC":
        gateway.search_results[f'artist:"{artist}"'] = make_tracks(artist, 2)

    built = factory.build(SourceSpec(type="top_tracks"))

    played = take(built.source, 10)
    assert played[0].artists == ("fan",)
    assert [t.artists[0] for t in played[1:4]] == ["A", "B", "C"]


def test_top_tracks_with_no_listening_history_is_rejected(factory):
    with pytest.raises(InvalidRuleError):
        factory.build(SourceSpec(type="top_tracks"))


def test_pinned_skips_karaoke_and_unrelated_matches_for_the_real_recording(gateway, factory):
    karaoke = make_tracks("Taylor Swift", 1, "karaoke")[0]
    karaoke = type(karaoke)(karaoke.uri, "Blank Space - Karaoke Version", karaoke.artists)
    stranger = make_tracks("Spanish Swift", 1)[0]
    real = make_tracks("Taylor Swift", 1, "real")[0]
    gateway.search_results['track:"Blank Space" artist:"Taylor Swift"'] = [karaoke, stranger, real]

    built = factory.build(
        SourceSpec(type="pinned", tracks=[TrackRef(title="Blank Space", artist="Taylor Swift")])
    )

    assert take(built.source, 10) == [real]
