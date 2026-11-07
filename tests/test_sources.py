import pytest

from spotify_dj.sources import (
    ChainedSource,
    InterleavedSource,
    InvalidRuleError,
    PinnedSource,
    SearchSource,
    TopTracksSource,
    build_search_query,
    is_wanted,
    take,
)
from spotify_dj.models import Track
from tests.fakes import FakeGateway, make_tracks


# --- query building ---------------------------------------------------------
def test_query_combines_filters():
    query = build_search_query(artist="Taylor Swift", year="2015", genre="pop")

    assert query == 'artist:"Taylor Swift" genre:"pop" year:2015'


def test_query_accepts_year_ranges_and_strips_quotes():
    assert build_search_query(artist='Say "Hi"', year="2010-2015") == 'artist:"Say Hi" year:2010-2015'


@pytest.mark.parametrize("kwargs", [{}, {"artist": "  "}, {"year": "last year"}, {"year": "15"}])
def test_query_rejects_unanswerable_rules(kwargs):
    with pytest.raises(InvalidRuleError):
        build_search_query(**kwargs)


# --- search -----------------------------------------------------------------
def test_search_source_pages_through_results_lazily():
    gateway = FakeGateway()
    gateway.search_results["q"] = make_tracks("a", 25)
    source = SearchSource(gateway, "q")

    assert len(take(source, 3)) == 3
    assert gateway.search_calls == [("q", 0)]  # only the first page was fetched

    assert len(take(source, 100)) == 22
    assert [offset for _, offset in gateway.search_calls] == [0, 10, 20, 30]  # 30 = empty page


def test_search_source_with_no_results_is_exhausted():
    assert SearchSource(FakeGateway(), "nothing").next_track() is None


def test_reset_restarts_the_stream():
    gateway = FakeGateway()
    gateway.search_results["q"] = make_tracks("a", 2)
    source = SearchSource(gateway, "q")
    first_pass = take(source, 10)

    source.reset()

    assert take(source, 10) == first_pass


def test_peek_does_not_consume():
    gateway = FakeGateway()
    gateway.search_results["q"] = make_tracks("a", 2)
    source = SearchSource(gateway, "q")

    assert source.peek() == source.next_track()
    assert source.next_track() == make_tracks("a", 2)[1]


# --- top tracks -------------------------------------------------------------
def test_top_tracks_merge_time_ranges_without_duplicates():
    gateway = FakeGateway()
    shared, only_long = make_tracks("x", 1, "shared")[0], make_tracks("x", 1, "long")[0]
    gateway.top = {"short_term": [shared], "medium_term": [shared], "long_term": [only_long]}

    assert take(TopTracksSource(gateway), 10) == [shared, only_long]


def test_top_tracks_can_be_limited_to_artists_case_insensitively():
    gateway = FakeGateway()
    taylor, other = make_tracks("Taylor Swift", 1)[0], make_tracks("Coldplay", 1)[0]
    gateway.top = {"medium_term": [other, taylor]}

    assert take(TopTracksSource(gateway, ["taylor swift"]), 10) == [taylor]


def test_top_tracks_are_fetched_once_across_resets():
    gateway = FakeGateway()
    gateway.top = {"medium_term": make_tracks("x", 2)}
    calls = []
    original = gateway.top_tracks
    gateway.top_tracks = lambda r: calls.append(r) or original(r)
    source = TopTracksSource(gateway)

    take(source, 10)
    source.reset()
    take(source, 10)

    assert len(calls) == 3  # one per time range, not per pass


# --- pinned, chained, interleaved -------------------------------------------
def test_pinned_source_plays_in_order_then_ends():
    tracks = make_tracks("a", 2)
    source = PinnedSource(tracks)

    assert take(source, 5) == tracks
    assert source.next_track() is None


def test_chained_source_drains_in_order():
    first, second = make_tracks("a", 2), make_tracks("b", 2)

    chained = ChainedSource(PinnedSource(first), PinnedSource(second))

    assert take(chained, 10) == first + second


def test_chained_reset_resets_children():
    tracks = make_tracks("a", 2)
    chained = ChainedSource(PinnedSource(tracks))
    take(chained, 10)

    chained.reset()

    assert take(chained, 10) == tracks


def test_interleaved_source_takes_turns_and_drops_exhausted_sources():
    a, b = make_tracks("a", 3), make_tracks("b", 1)

    mixed = InterleavedSource(PinnedSource(a), PinnedSource(b))

    assert take(mixed, 10) == [a[0], b[0], a[1], a[2]]


# --- filtering junk ---------------------------------------------------------
def test_karaoke_and_tribute_versions_are_not_wanted():
    taylor = ("Taylor Swift",)

    assert is_wanted(Track("u1", "Style", taylor, "1989"))
    assert not is_wanted(Track("u2", "Style - Karaoke Version", taylor, "1989"))
    assert not is_wanted(Track("u3", "Style", taylor, "Taylor Swift Karaoke: 1989 (Deluxe)"))
    assert not is_wanted(Track("u4", "Style (Instrumental)", taylor, "1989"))
    assert not is_wanted(Track("u5", "Style", taylor, "A Tribute to Taylor Swift"))


def test_remixes_and_live_versions_are_kept():
    taylor = ("Taylor Swift",)

    assert is_wanted(Track("u1", "Wildest Dreams - R3hab Remix", taylor, "Wildest Dreams"))
    assert is_wanted(Track("u2", "Live While We're Young", ("One Direction",), "Take Me Home"))


def test_artist_must_be_credited_and_accents_and_case_are_ignored():
    song = Track("u1", "Halo", ("Beyoncé", "Someone"))

    assert is_wanted(song, "beyonce")
    assert is_wanted(song, "Someone")
    assert not is_wanted(Track("u2", "Friday", ("Spanish Swift", "Luicia Taylor")), "Taylor Swift")


def test_search_source_skips_unwanted_tracks_but_keeps_paging():
    gateway = FakeGateway()
    junk = [Track(f"junk{i}", f"Song {i} - Karaoke Version", ("Taylor Swift",)) for i in range(10)]
    real = Track("real", "Style", ("Taylor Swift",))
    stranger = Track("stranger", "Style", ("Spanish Swift",))
    gateway.search_results["q"] = junk + [real, stranger]  # first page is 100% junk

    source = SearchSource(gateway, "q", artist="Taylor Swift")

    assert take(source, 10) == [real]


def test_search_without_an_artist_still_filters_junk_but_not_by_credit():
    gateway = FakeGateway()
    gateway.search_results["q"] = [
        Track("a", "Hit", ("Anyone",)),
        Track("b", "Hit - Karaoke Version", ("Anyone",)),
    ]

    assert [t.uri for t in take(SearchSource(gateway, "q"), 10)] == ["a"]
