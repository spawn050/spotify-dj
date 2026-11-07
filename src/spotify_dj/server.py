"""MCP tools. Thin adapters: parse the request, call the DJ, describe the result."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from functools import wraps

from mcp.server.mcpserver import MCPServer

from spotify_dj.dj import MixReport, Status
from spotify_dj.factory import SourceSpec
from spotify_dj.mixer import UnknownSourceError
from spotify_dj.session import DJSession
from spotify_dj.spotify import NotLoggedInError, SpotifyError

SOURCE_GUIDE = """\
Each source is one of:
- search: Spotify catalogue search by artist, album, genre and/or year ('2015' or '2010-2015'). \
These are the ONLY filters Spotify supports. It cannot filter by mood, energy, tempo, \
popularity or anything similar.
- top_tracks: the user's own favourites. Use it for 'songs I might like'. Set `artists` to \
limit it to some artists ('Taylor Swift songs I might like'); it falls back to more songs by \
those artists once the favourites are played.
- pinned: specific songs you choose from your own music knowledge. Use it for what search \
cannot express: moods ('upbeat'), 'deep cuts', 'biggest hits'.
For 'artists like X', pick about 5 similar artists from your own knowledge as separate search \
sources and include X itself with a lower weight (weights are relative whole numbers).
Give every source a unique `name`. When part of a request is impossible (e.g. a mood filter on \
search), do the possible part, then tell the user plainly what was approximated. Always relay \
any ⚠️ notes in the result to the user."""


def reported[**P](tool: Callable[P, Awaitable[str]]) -> Callable[P, Awaitable[str]]:
    """Turn expected failures into a message Claude can pass on to the user."""

    @wraps(tool)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
        try:
            return await tool(*args, **kwargs)
        except (NotLoggedInError, SpotifyError, UnknownSourceError) as error:
            return f"⚠️ {error}"

    return wrapper


def build_server(session: DJSession) -> MCPServer:
    @asynccontextmanager
    async def lifespan(_server: MCPServer):
        loop = asyncio.create_task(session.keep_queue_stocked())
        try:
            yield
        finally:
            loop.cancel()
            with suppress(asyncio.CancelledError):
                await loop

    server = MCPServer("spotify-dj", lifespan=lifespan)

    @server.tool(
        description="Start a new DJ mix, replacing the current one ('Play X'). The DJ keeps "
        "Spotify's queue stocked from it until stopped. Songs already in Spotify's queue play "
        "first.\n" + SOURCE_GUIDE
    )
    @reported
    async def set_mix(sources: list[SourceSpec]) -> str:
        return _mix_message("Mix started", await session.run(lambda dj: dj.set_mix(sources)))

    @server.tool(
        description="Blend more sources into the current mix ('Add X to the mix') without "
        "dropping what is already there. Sources work as in set_mix."
    )
    @reported
    async def add_to_mix(sources: list[SourceSpec]) -> str:
        return _mix_message("Added to the mix", await session.run(lambda dj: dj.add_to_mix(sources)))

    @server.tool(
        description="Change how often a source plays relative to the others ('more Taylor'). "
        "Weight 0 removes the source. Use the source names shown by get_status."
    )
    @reported
    async def set_weight(name: str, weight: int) -> str:
        await session.run(lambda dj: dj.set_weight(name, weight))
        return f"'{name}' now has weight {weight}."

    @server.tool(description="Show what is playing, what is queued next, the mix and any problems.")
    @reported
    async def get_status() -> str:
        return _status_message(await session.run(lambda dj: dj.status()))

    @server.tool(
        description="Stop adding songs. Songs already in Spotify's queue still play."
    )
    @reported
    async def stop() -> str:
        await session.run(lambda dj: dj.stop())
        return "Stopped. Songs already in Spotify's queue will still play."

    return server


def _mix_message(headline: str, report: MixReport) -> str:
    lines = [f"{headline}: {', '.join(report.added)}." if report.added else "Nothing changed."]
    lines += [f"⚠️ {flag}" for flag in report.flags]
    return "\n".join(lines)


def _status_message(status: Status) -> str:
    playing = f"Now playing: {status.now_playing}" if status.now_playing else "Nothing is playing."
    lines = [playing]
    if status.up_next:
        lines.append("Up next (queued by the DJ): " + "; ".join(map(str, status.up_next)))
    mix = ", ".join(f"{name} (weight {weight})" for name, weight in status.mix.items())
    lines.append(f"Mix: {mix}" if mix else "Mix: empty - the DJ is not adding songs.")
    if status.problem:
        lines.append(f"⚠️ {status.problem}")
    return "\n".join(lines)
