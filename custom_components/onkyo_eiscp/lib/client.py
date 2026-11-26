"""Minimal eISCP connection: connect, send, receive, push dispatch.

The receiver closes an older connection when the same host opens a second one, so everything a
program does must go over one ``EiscpClient``.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from .exceptions import ConnectionClosedError, EiscpError
from .frame import FrameParser, encode

if TYPE_CHECKING:
    from collections.abc import Callable

    from .frame import Message

DEFAULT_PORT = 60128
READ_SIZE = 4096


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
        self._closed = asyncio.Event()
        self.close_reason = ""

    @property
    def connected(self) -> bool:
        """True while the connection is open."""
        return self._writer is not None and not self._closed.is_set()

    def add_listener(self, callback: Callable[[Message], None]) -> None:
        """Call ``callback`` for every message received (replies and pushes alike)."""
        self._listeners.append(callback)

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

    async def send(self, message: str) -> None:
        """Send one message (code plus parameter, for example ``PWRQSTN``)."""
        if self._writer is None or self._closed.is_set():
            msg = self.close_reason or "not connected"
            raise ConnectionClosedError(msg)
        self._writer.write(encode(message))
        await self._writer.drain()

    async def wait_closed(self) -> None:
        """Return when the connection has closed."""
        await self._closed.wait()

    async def _read_loop(self) -> None:
        assert self._reader is not None  # noqa: S101
        parser = FrameParser()
        try:
            while data := await self._reader.read(READ_SIZE):
                for message in parser.feed(data):
                    for listener in list(self._listeners):
                        listener(message)
            self.close_reason = "closed by the receiver"
        except (OSError, EiscpError) as err:
            self.close_reason = f"connection lost: {err}"
        finally:
            self._closed.set()
