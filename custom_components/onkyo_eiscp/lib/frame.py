"""Build and parse eISCP packets (no Home Assistant, no network).

A packet is a 16 byte header followed by the data part:

    "ISCP" | header size (4 bytes, 16) | data size (4 bytes) | version (1 byte, 1) | 3 reserved
    data: "!" + unit type + 3 letter code + parameter + end bytes

CI (custom install, config) messages carry a lower-case ``s`` in front of the code, for example
``!1sLCCMMMM1FL+07``. The parser then returns a four character code (``sLCC``).

We send CR as the end byte. Receivers end replies with EOF, CR, LF (hex 1A 0D 0A), and some
replies carry only CR LF, so the parser accepts any run of CR, LF and EOF at the end.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .exceptions import FrameError

MAGIC = b"ISCP"
HEADER_SIZE = 16
VERSION = 1
UNIT_TYPE = "1"
END_BYTES = "\x1a\r\n"
MAX_DATA_SIZE = 1 << 20
CODE_LENGTH = 3
CI_PREFIX = "s"
_HEADER = struct.Struct(">4sIIB3x")


@dataclass(frozen=True, slots=True)
class Message:
    """One message from the receiver."""

    raw: str
    """The data part exactly as received (end bytes included)."""
    unit: str
    code: str
    param: str


def encode(message: str, unit: str = UNIT_TYPE) -> bytes:
    """Wrap ``message`` (code plus parameter, for example ``MVLQSTN``) in an eISCP packet."""
    data = f"!{unit}{message}\r".encode("latin-1")
    return _HEADER.pack(MAGIC, HEADER_SIZE, len(data), VERSION) + data


def parse_data(raw: str) -> Message:
    """Split the data part of a packet into unit, code and parameter."""
    body = raw.rstrip(END_BYTES)
    if not body.startswith("!") or len(body) < 2 + CODE_LENGTH:
        msg = f"not an eISCP message: {raw!r}"
        raise FrameError(msg)
    length = CODE_LENGTH + 1 if body[2] == CI_PREFIX else CODE_LENGTH
    if len(body) < 2 + length:
        msg = f"not an eISCP message: {raw!r}"
        raise FrameError(msg)
    return Message(raw=raw, unit=body[1], code=body[2 : 2 + length], param=body[2 + length :])


class FrameParser:
    """Turn a stream of bytes into messages; a packet may arrive in pieces or several at once."""

    def __init__(self) -> None:
        """Start with an empty buffer."""
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[Message]:
        """Add received bytes and return every message that is now complete."""
        self._buffer += data
        messages: list[Message] = []
        while len(self._buffer) >= HEADER_SIZE:
            magic, header_size, data_size, _version = _HEADER.unpack_from(self._buffer)
            if magic != MAGIC:
                msg = f"bad header {bytes(self._buffer[:HEADER_SIZE])!r}"
                raise FrameError(msg)
            if header_size < HEADER_SIZE or data_size > MAX_DATA_SIZE:
                msg = f"bad sizes: header {header_size}, data {data_size}"
                raise FrameError(msg)
            end = header_size + data_size
            if len(self._buffer) < end:
                break
            raw = bytes(self._buffer[header_size:end]).decode("latin-1")
            del self._buffer[:end]
            messages.append(parse_data(raw))
        return messages
