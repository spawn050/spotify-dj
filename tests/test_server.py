import asyncio

import pytest
from mcp.client import Client

from spotify_dj.dj import DJ
from spotify_dj.factory import SourceFactory
from spotify_dj.mixer import Mixer
from spotify_dj.server import build_server
from spotify_dj.session import DJSession
from spotify_dj.spotify import NotLoggedInError
from tests.fakes import Clock, FakeGateway, make_tracks


def make_session(gateway: FakeGateway, clock: Clock | None = None, poll_seconds: float = 0.01) -> DJSession:
    gateway.search_results['artist:"Taylor Swift"'] = make_tracks("Taylor Swift", 10)
    gateway.current = make_tracks("Someone", 1)[0]
    dj_clock = clock or Clock()
    return DJSession(lambda: DJ(gateway, SourceFactory(gateway), Mixer(), 3, clock=dj_clock), poll_seconds)


async def call(server, tool: str, arguments: dict | None = None) -> str:
    async with Client(server) as client:
        result = await client.call_tool(tool, arguments or {})
    return result.content[0].text


async def test_set_mix_returns_a_message_and_flags(tmp_path):
    session = make_session(FakeGateway())
    server = build_server(session)

    text = await call(
        server,
        "set_mix",
        {"sources": [{"type": "search", "artist": "Taylor Swift"}, {"type": "search", "artist": "Nobody"}]},
    )

    assert "Mix started: Taylor Swift." in text
    assert "⚠️ Spotify found nothing for 'Nobody'" in text


async def test_unknown_source_is_reported_not_raised():
    server = build_server(make_session(FakeGateway()))

    text = await call(server, "set_weight", {"name": "Adele", "weight": 2})

    assert text.startswith("⚠️")


async def test_not_logged_in_is_reported_as_a_message():
    def not_logged_in():
        raise NotLoggedInError("Run `spotify-dj login` first.")

    server = build_server(DJSession(not_logged_in, 0.01))

    assert await call(server, "get_status") == "⚠️ Run `spotify-dj login` first."


async def test_background_loop_stocks_the_queue():
    gateway = FakeGateway()
    server = build_server(make_session(gateway))

    async with Client(server) as client:
        await client.call_tool("set_mix", {"sources": [{"type": "search", "artist": "Taylor Swift"}]})
        await asyncio.sleep(0.2)  # let the background loop tick

    assert len(gateway.queue) == 2


async def test_background_loop_survives_a_failing_tick_and_recovers():
    gateway, clock = FakeGateway(), Clock()
    server = build_server(make_session(gateway, clock))

    async with Client(server) as client:
        await client.call_tool("set_mix", {"sources": [{"type": "search", "artist": "Taylor Swift"}]})
        await asyncio.sleep(0.1)

        working = gateway.playback
        gateway.playback = lambda: (_ for _ in ()).throw(RuntimeError("Spotify is down"))
        await asyncio.sleep(0.1)  # several failing ticks

        gateway.playback = working
        gateway.skip_queue()
        clock.advance(10)
        await asyncio.sleep(0.2)

    assert len(gateway.queue) == 2


async def test_unsupported_fields_such_as_mood_are_rejected_not_ignored():
    gateway = FakeGateway()
    server = build_server(make_session(gateway))

    async with Client(server) as client:
        result = await client.call_tool(
            "set_mix", {"sources": [{"type": "search", "artist": "Taylor Swift", "mood": "upbeat"}]}
        )

    assert result.is_error
    assert "mood" in result.content[0].text
    assert gateway.queue == []
