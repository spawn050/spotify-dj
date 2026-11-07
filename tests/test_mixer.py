import pytest

from spotify_dj.mixer import Mixer, UnknownSourceError
from spotify_dj.sources import PinnedSource
from tests.fakes import make_tracks


def mixer_with(**sources: tuple[int, int]) -> Mixer:
    """mixer_with(taylor=(weight, song_count), ...)"""
    mixer = Mixer()
    for artist, (weight, count) in sources.items():
        mixer.add(artist, PinnedSource(make_tracks(artist, count)), weight)
    return mixer


def artists_of(mixer: Mixer, count: int) -> list[str]:
    return [mixer.next_track().artists[0] for _ in range(count)]


def test_empty_mix_has_nothing_to_play():
    assert Mixer().next_track() is None


def test_equal_weights_take_turns():
    mixer = mixer_with(a=(1, 5), b=(1, 5))

    assert artists_of(mixer, 4) == ["a", "b", "a", "b"]


def test_weights_set_the_share_and_spread_it_evenly():
    mixer = mixer_with(a=(3, 10), b=(1, 10))

    assert artists_of(mixer, 8) == ["a", "a", "b", "a", "a", "a", "b", "a"]


def test_exhausted_source_is_skipped_while_others_have_songs():
    mixer = mixer_with(a=(1, 1), b=(1, 4))

    assert artists_of(mixer, 4) == ["a", "b", "b", "b"]


def test_same_song_from_two_sources_plays_once_per_pass():
    shared = make_tracks("x", 1)
    mixer = Mixer()
    mixer.add("first", PinnedSource(shared))
    mixer.add("second", PinnedSource(shared + make_tracks("y", 1)))

    assert [t.uri for t in (mixer.next_track(), mixer.next_track())] == [
        shared[0].uri,
        make_tracks("y", 1)[0].uri,
    ]


def test_repeats_begin_only_after_everything_has_played():
    mixer = mixer_with(a=(1, 2), b=(1, 1))
    first_pass = [mixer.next_track().uri for _ in range(3)]

    second_pass = [mixer.next_track().uri for _ in range(3)]

    assert len(set(first_pass)) == 3
    assert sorted(second_pass) == sorted(first_pass)


def test_set_weight_changes_share():
    mixer = mixer_with(a=(1, 20), b=(1, 20))

    mixer.set_weight("a", 3)

    assert artists_of(mixer, 4).count("a") == 3


def test_zero_weight_removes_the_source():
    mixer = mixer_with(a=(1, 5), b=(1, 5))

    mixer.set_weight("a", 0)

    assert set(artists_of(mixer, 4)) == {"b"}
    assert mixer.weights() == {"b": 1}


def test_unknown_source_is_reported_with_what_is_in_the_mix():
    mixer = mixer_with(a=(1, 1))

    with pytest.raises(UnknownSourceError, match="'a': 1"):
        mixer.set_weight("nope", 2)


def test_adding_an_existing_name_replaces_it():
    mixer = mixer_with(a=(1, 5))

    mixer.add("a", PinnedSource(make_tracks("a2", 1)), 2)

    assert mixer.weights() == {"a": 2}
    assert mixer.next_track().artists == ("a2",)


def test_clear_forgets_sources_and_history():
    mixer = mixer_with(a=(1, 1))
    mixer.next_track()

    mixer.clear()
    mixer.add("a", PinnedSource(make_tracks("a", 1)))

    assert mixer.next_track() is not None


def test_invalid_weights_are_rejected():
    mixer = mixer_with(a=(1, 1))

    with pytest.raises(ValueError):
        mixer.add("b", PinnedSource([]), 0)
    with pytest.raises(ValueError):
        mixer.set_weight("a", -1)
