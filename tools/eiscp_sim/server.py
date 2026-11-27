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
from typing import Any

from custom_components.onkyo_eiscp.lib.exceptions import EiscpError
from custom_components.onkyo_eiscp.lib.frame import (
    END_BYTES,
    HEADER_SIZE,
    MAGIC,
    VERSION,
    FrameParser,
    parse_data,
)

from .receiver import Receiver, Result

_LOGGER = logging.getLogger(__name__)
_HEADER = struct.Struct(">4sIIB3x")
UDP_END = "\x19\r\n"
UDP_SIZE = 64  # the real receiver pads the discovery answer with NUL bytes to a fixed size


def discovery_packet(message: str) -> bytes:
    """The UDP answer to ``!xECNQSTN``: ends ``0x19 CR LF`` and is padded with NUL bytes."""
    data = f"!1{message}{UDP_END}".encode("latin-1")
    packet = _HEADER.pack(MAGIC, HEADER_SIZE, len(data), VERSION) + data
    return packet.ljust(UDP_SIZE, b"\x00")


class _Discovery(asyncio.DatagramProtocol):
    """Answers ``!xECNQSTN`` over UDP like the receiver does; anything else gets no answer."""

    def __init__(self, receiver: Receiver, port: int) -> None:
        self.receiver = receiver
        self.port = port
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        try:
            message = parse_data(data[HEADER_SIZE:].decode("latin-1").rstrip("\x00"))
        except EiscpError:
            return
        if (
            message.unit == "x"
            and message.code == "ECN"
            and message.param == "QSTN"
            and self.transport is not None
        ):
            self.transport.sendto(discovery_packet(self.receiver.discovery_answer(self.port)), addr)


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
        udp: bool = False,
        power_on_delay: float = 0.0,
        power_on_quiet: float = 0.0,
    ) -> None:
        """Remember the address; call ``start`` to listen (port 0 picks a free port).

        ``udp`` also answers discovery (``!xECNQSTN``) on the same port number. The real
        TX-RZ50 pushes ``PWR01`` about 7.6 s after a power-on set and answers no query for about
        20 s: ``power_on_delay`` holds the power-on pushes back that many seconds and
        ``power_on_quiet`` leaves queries unanswered that many seconds after the set.
        """
        self.receiver = receiver
        self.host = host
        self.port = port
        self.one_per_host = one_per_host
        self.udp = udp
        self.power_on_delay = power_on_delay
        self.power_on_quiet = power_on_quiet
        self._server: asyncio.Server | None = None
        self._transport: asyncio.DatagramTransport | None = None
        self._connections: dict[asyncio.StreamWriter, str] = {}
        self._quiet_until = 0.0
        self._tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        """Start listening."""
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]
        if self.udp:
            loop = asyncio.get_running_loop()
            transport, _ = await loop.create_datagram_endpoint(
                lambda: _Discovery(self.receiver, self.port), local_addr=(self.host, self.port)
            )
            self._transport = transport

    async def stop(self) -> None:
        """Close every connection and stop listening."""
        for writer in list(self._connections):
            self._drop(writer)
        for task in list(self._tasks):
            task.cancel()
        if self._transport is not None:
            self._transport.close()
            self._transport = None
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

    def _answer(self, code: str, param: str, writer: asyncio.StreamWriter) -> None:
        loop = asyncio.get_running_loop()
        if param == "QSTN" and loop.time() < self._quiet_until:
            return  # right after a power-on the receiver answers no query (pushes still come)
        was_on = self.receiver.powered
        result = self.receiver.handle(code, param)
        if code == "PWR" and not was_on and self.receiver.powered:
            self._quiet_until = loop.time() + self.power_on_quiet
            if self.power_on_delay > 0:
                task = loop.create_task(self._later(result, self.power_on_delay))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
                return
        self._send(result, to=writer)

    async def _later(self, result: Result, delay: float) -> None:
        await asyncio.sleep(delay)
        self._send(result)

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
                    self._answer(incoming.code, incoming.param, writer)
                await writer.drain()
        except OSError, EiscpError:
            _LOGGER.debug("connection from %s ended", peer)
        finally:
            self._drop(writer)


async def serve(
    fixture: Path, host: str, port: int, *, one_per_host: bool, udp: bool = False
) -> None:
    """Run until interrupted."""
    server = SimServer(
        Receiver.from_folder(fixture), host, port, one_per_host=one_per_host, udp=udp
    )
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
    parser.add_argument("--udp", action="store_true", help="answer UDP discovery (!xECNQSTN)")
    args = parser.parse_args(argv)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(
            serve(args.fixture, args.host, args.port, one_per_host=not args.many, udp=args.udp)
        )
