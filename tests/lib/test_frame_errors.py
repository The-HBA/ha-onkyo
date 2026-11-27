"""Frame parser: bad sizes, plus small gaps of the library not reached elsewhere."""

import asyncio
from typing import TYPE_CHECKING

import pytest
from lib_helpers import FAST, poll

from custom_components.onkyo_eiscp.lib import EiscpClient, FrameError, FrameParser, Receiver
from custom_components.onkyo_eiscp.lib.codecs import encode
from custom_components.onkyo_eiscp.lib.commands import COMMANDS
from custom_components.onkyo_eiscp.lib.exceptions import CodecError

if TYPE_CHECKING:
    from tools.eiscp_sim import SimServer


def header(header_size: int, data_size: int) -> bytes:
    return b"ISCP" + header_size.to_bytes(4, "big") + data_size.to_bytes(4, "big") + b"\x01\0\0\0"


@pytest.mark.parametrize("sizes", [(8, 4), (16, (1 << 20) + 1)])
def test_impossible_sizes_are_a_frame_error(sizes: tuple[int, int]) -> None:
    with pytest.raises(FrameError, match="bad sizes"):
        FrameParser().feed(header(*sizes))


def test_a_value_that_cannot_be_rounded_is_a_codec_error() -> None:
    with pytest.raises(CodecError):
        encode(COMMANDS["SLP"], float("nan"))


async def test_a_read_that_loses_the_connection_ends_quietly(
    sim: SimServer, receiver: Receiver
) -> None:
    reading = asyncio.create_task(receiver._read(["TCT"]))  # silent code: waits for an answer
    await asyncio.sleep(0.05)
    for writer in list(sim._connections):
        sim._drop(writer)
    assert await reading == []
    await poll(lambda: receiver.connected)


async def test_the_keepalive_ends_when_the_connection_closes(sim: SimServer) -> None:
    library = Receiver("127.0.0.1", sim.port, timing=FAST)
    client = EiscpClient("127.0.0.1", sim.port)
    await client.connect()
    task = asyncio.create_task(library._keep_alive(client))
    await asyncio.sleep(0.1)
    await sim.stop()
    await asyncio.wait_for(task, 2)
    await client.close()
