"""Find receivers with the eISCP discovery message (``!xECNQSTN`` over UDP 60128).

A receiver answers ``!1ECN<model>/<port>/<area>/<12 hex MAC>`` ending ``0x19 CR LF`` and padded
with NUL bytes. Broadcast reaches only the local network; Hattan's VLANs pass unicast only, so
``discover(host)`` asks one address.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .exceptions import EiscpError
from .frame import HEADER_SIZE, encode, parse_data

if TYPE_CHECKING:
    from asyncio import BaseTransport

DEFAULT_PORT = 60128
BROADCAST = "255.255.255.255"
_FIELDS = 4


@dataclass(frozen=True, slots=True)
class Discovered:
    """One receiver that answered."""

    host: str
    port: int
    model: str
    mac: str
    """12 upper case hex digits."""


def parse_answer(datagram: bytes, host: str) -> Discovered | None:
    """Read one UDP answer; ``None`` when it is not a discovery answer."""
    text = datagram[HEADER_SIZE:].decode("latin-1").rstrip("\x00\x19\x1a\r\n")
    try:
        message = parse_data(text)
    except EiscpError:
        return None
    if message.code != "ECN":
        return None
    fields = message.param.rsplit("/", _FIELDS - 1)
    if len(fields) != _FIELDS or not fields[1].isdigit():
        return None
    model, port, _area, mac = fields
    return Discovered(host=host, port=int(port), model=model, mac=mac.replace(":", "").upper())


class _Collector(asyncio.DatagramProtocol):
    def __init__(self, found: dict[str, Discovered], first: asyncio.Event) -> None:
        self.found = found
        self.first = first

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if (item := parse_answer(data, addr[0])) is not None:
            self.found[item.mac or item.host] = item
            self.first.set()

    def connection_made(self, transport: BaseTransport) -> None:
        pass


async def discover(
    host: str | None = None,
    timeout: float = 2.0,  # noqa: ASYNC109
    *,
    port: int = DEFAULT_PORT,
) -> list[Discovered]:
    """Ask ``host`` (unicast) or the local network (broadcast) and collect the answers.

    A unicast ask returns as soon as the receiver answers; a broadcast waits ``timeout`` s.
    """
    loop = asyncio.get_running_loop()
    found: dict[str, Discovered] = {}
    first = asyncio.Event()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, int(True))
    sock.settimeout(0)
    transport, _ = await loop.create_datagram_endpoint(lambda: _Collector(found, first), sock=sock)
    try:
        transport.sendto(encode("ECNQSTN", unit="x"), (host or BROADCAST, port))
        if host is not None:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(first.wait(), timeout)
        else:
            await asyncio.sleep(timeout)
    finally:
        transport.close()
    return list(found.values())
