"""The simulated receiver on a TCP port: framing, connections, pushes.

Like the TX-RZ50 it keeps one connection per client host (a new one closes the older one from
the same address), answers each message from the fixture state, and pushes every change to
every open connection.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import struct
from pathlib import Path

from custom_components.onkyo_eiscp.lib.exceptions import EiscpError
from custom_components.onkyo_eiscp.lib.frame import (
    END_BYTES,
    HEADER_SIZE,
    MAGIC,
    VERSION,
    FrameParser,
)

from .receiver import Receiver, Result

_LOGGER = logging.getLogger(__name__)
_HEADER = struct.Struct(">4sIIB3x")


def reply_packet(message: str) -> bytes:
    """Build the packet the receiver sends for ``message`` (code plus parameter)."""
    data = f"!1{message}{END_BYTES}".encode("latin-1")
    return _HEADER.pack(MAGIC, HEADER_SIZE, len(data), VERSION) + data


class SimServer:
    """Serve a ``Receiver`` over eISCP."""

    def __init__(
        self,
        receiver: Receiver,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        one_per_host: bool = True,
    ) -> None:
        """Remember the address; call ``start`` to listen (port 0 picks a free port)."""
        self.receiver = receiver
        self.host = host
        self.port = port
        self.one_per_host = one_per_host
        self._server: asyncio.Server | None = None
        self._connections: dict[asyncio.StreamWriter, str] = {}

    async def start(self) -> None:
        """Start listening."""
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        """Close every connection and stop listening."""
        for writer in list(self._connections):
            self._drop(writer)
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    @property
    def connection_count(self) -> int:
        """Number of open client connections."""
        return len(self._connections)

    def set_signal(self, name: str) -> None:
        """Change the incoming signal and push the result to every connection."""
        self._send(self.receiver.set_signal(name))

    def _drop(self, writer: asyncio.StreamWriter) -> None:
        self._connections.pop(writer, None)
        with contextlib.suppress(OSError, RuntimeError):
            writer.close()

    def _send(self, result: Result, to: asyncio.StreamWriter | None = None) -> None:
        """Replies go to the asker only, broadcast messages to every connection."""
        for writer in list(self._connections):
            if writer is to:
                for message in result.replies:
                    self._write(writer, message)
            for message in result.broadcast:
                self._write(writer, message)

    def _write(self, writer: asyncio.StreamWriter, message: str) -> None:
        try:
            writer.write(reply_packet(message))
        except OSError, RuntimeError:
            self._drop(writer)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = str(writer.get_extra_info("peername")[0])
        if self.one_per_host:
            for old, old_peer in list(self._connections.items()):
                if old_peer == peer:
                    self._drop(old)
        self._connections[writer] = peer
        for message in self.receiver.connect_messages():
            self._write(writer, message)
        parser = FrameParser()
        try:
            while data := await reader.read(4096):
                for incoming in parser.feed(data):
                    result = self.receiver.handle(incoming.code, incoming.param)
                    self._send(result, to=writer)
                await writer.drain()
        except OSError, EiscpError:
            _LOGGER.debug("connection from %s ended", peer)
        finally:
            self._drop(writer)


async def serve(fixture: Path, host: str, port: int, *, one_per_host: bool) -> None:
    """Run until interrupted."""
    server = SimServer(Receiver.from_folder(fixture), host, port, one_per_host=one_per_host)
    await server.start()
    print(f"simulated receiver on {host}:{server.port} ({fixture.name})")
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.Event().wait()


def main(argv: list[str] | None = None) -> None:
    """Command line entry: ``python -m tools.eiscp_sim --fixture tests/fixtures/tx-rz50``."""
    parser = argparse.ArgumentParser(description="Simulated Onkyo receiver (eISCP over TCP).")
    parser.add_argument("--fixture", type=Path, default=Path("tests/fixtures/tx-rz50"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=60128)
    parser.add_argument("--many", action="store_true", help="allow several connections per host")
    args = parser.parse_args(argv)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve(args.fixture, args.host, args.port, one_per_host=not args.many))
