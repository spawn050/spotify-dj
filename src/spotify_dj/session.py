import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress

from spotify_dj.dj import DJ
from spotify_dj.spotify import NotLoggedInError

log = logging.getLogger(__name__)


class DJSession:
    """Shares one DJ between MCP tool calls and the background top-up loop.

    Spotify calls are blocking, so they run in a worker thread; the lock makes
    sure the tools and the loop never use the DJ at the same moment.
    """

    def __init__(self, make_dj: Callable[[], DJ], poll_seconds: float) -> None:
        self._make_dj = make_dj  # called on first use, so a missing login surfaces as a tool message
        self._poll_seconds = poll_seconds
        self._dj: DJ | None = None
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()

    async def run[T](self, action: Callable[[DJ], T]) -> T:
        """Run a DJ action for a tool call, then top the queue up straight away."""
        async with self._lock:
            result = await asyncio.to_thread(lambda: action(self._get_dj()))
        self._wake.set()
        return result

    async def keep_queue_stocked(self) -> None:
        """Top the queue up every poll interval, or sooner when a tool changes the mix."""
        while True:
            self._wake.clear()
            try:
                async with self._lock:
                    await asyncio.to_thread(lambda: self._get_dj().tick())
            except NotLoggedInError:
                pass  # tools tell the user; nothing to top up yet
            except Exception as error:  # the loop must outlive any single failure
                log.exception("Queue top-up failed")
                if self._dj is not None:
                    self._dj.problem = f"Background error: {error}"
            with suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self._poll_seconds)

    def _get_dj(self) -> DJ:
        if self._dj is None:
            self._dj = self._make_dj()
        return self._dj
