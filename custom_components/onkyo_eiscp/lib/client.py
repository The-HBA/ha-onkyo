"""One eISCP connection: connect, send, request and reply, push dispatch.

The receiver closes an older connection when the same host opens a second one, so everything a
program does must go over one ``EiscpClient``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from .exceptions import ConnectionClosedError, EiscpError, NoReplyError, NotAvailableError
from .frame import FrameParser, encode

if TYPE_CHECKING:
    from collections.abc import Callable

    from .frame import Message

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 60128
READ_SIZE = 4096
NOT_AVAILABLE = "N/A"
QUERY = "QSTN"


class EiscpClient:
    """One TCP connection to a receiver."""

    def __init__(self, host: str, port: int = DEFAULT_PORT) -> None:
        """Remember the address; call ``connect`` to open the connection."""
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task[None] | None = None
        self._listeners: list[Callable[[Message], None]] = []
        self._locks: dict[str, asyncio.Lock] = {}
        self._waiters: dict[str, asyncio.Future[str]] = {}
        self._closed = asyncio.Event()
        self._closed.set()
        self.close_reason = ""

    @property
    def connected(self) -> bool:
        """True while the connection is open."""
        return self._writer is not None and not self._closed.is_set()

    def add_listener(self, callback: Callable[[Message], None]) -> Callable[[], None]:
        """Call ``callback`` for every message received (replies and pushes alike).

        Returns a function that removes the listener again.
        """
        self._listeners.append(callback)

        def remove() -> None:
            with contextlib.suppress(ValueError):
                self._listeners.remove(callback)

        return remove

    async def connect(self, timeout: float = 5.0) -> None:  # noqa: ASYNC109
        """Open the connection and start reading."""
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), timeout
        )
        self._closed.clear()
        self.close_reason = ""
        self._task = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        """Close the connection."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(OSError):
                await self._writer.wait_closed()
            self._writer = None
        self._closed.set()
        self._fail_waiters()

    async def send(self, message: str) -> None:
        """Send one message (code plus parameter, for example ``PWRQSTN``)."""
        if self._writer is None or self._closed.is_set():
            msg = self.close_reason or "not connected"
            raise ConnectionClosedError(msg)
        try:
            self._writer.write(encode(message))
            await self._writer.drain()
        except OSError as err:
            msg = f"connection lost: {err}"
            raise ConnectionClosedError(msg) from err

    async def query(self, code: str, timeout: float = 2.0) -> str:  # noqa: ASYNC109
        """Ask for ``code`` and return its parameter (``N/A`` included).

        Raises ``NoReplyError`` when the receiver stays silent (some codes do, on purpose).
        """
        return await self._request(code, QUERY, timeout)

    async def set(self, code: str, param: str, timeout: float = 2.0) -> str:  # noqa: ASYNC109
        """Set ``code`` and return the reply parameter.

        Raises ``NotAvailableError`` when refused (``N/A``) and ``NoReplyError`` when ignored.
        """
        reply = await self._request(code, param, timeout)
        if reply == NOT_AVAILABLE:
            raise NotAvailableError(code, param)
        return reply

    async def command(self, code: str, param: str) -> None:
        """Send ``code`` and ``param`` without waiting for an answer."""
        await self.send(code + param)

    async def wait_closed(self) -> None:
        """Return when the connection has closed."""
        await self._closed.wait()

    async def _request(self, code: str, param: str, timeout: float) -> str:  # noqa: ASYNC109
        """One request in flight per code; return the parameter of the next message with it."""
        lock = self._locks.setdefault(code, asyncio.Lock())
        async with lock:
            future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            self._waiters[code] = future
            try:
                await self.send(code + param)
                async with asyncio.timeout(timeout):
                    return await future
            except TimeoutError:
                raise NoReplyError(code, param) from None
            finally:
                self._waiters.pop(code, None)

    def _fail_waiters(self) -> None:
        for future in list(self._waiters.values()):
            if not future.done():
                future.set_exception(ConnectionClosedError(self.close_reason or "closed"))

    def _dispatch(self, message: Message) -> None:
        waiter = self._waiters.get(message.code)
        if waiter is not None and not waiter.done():
            waiter.set_result(message.param)
        for listener in list(self._listeners):
            try:
                listener(message)
            except Exception:
                _LOGGER.exception("listener failed for %s", message.code)

    async def _read_loop(self) -> None:
        assert self._reader is not None  # noqa: S101
        parser = FrameParser()
        try:
            while data := await self._reader.read(READ_SIZE):
                for message in parser.feed(data):
                    self._dispatch(message)
            self.close_reason = "closed by the receiver"
        except (OSError, EiscpError) as err:
            self.close_reason = f"connection lost: {err}"
        finally:
            self._closed.set()
            self._fail_waiters()
