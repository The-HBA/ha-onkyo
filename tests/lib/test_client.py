"""EiscpClient against the simulator: queries, sets, pushes, silence and closing."""

import asyncio
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest
from lib_helpers import poll

from custom_components.onkyo_eiscp.lib import (
    ConnectionClosedError,
    EiscpClient,
    Message,
    NoReplyError,
    NotAvailableError,
)

if TYPE_CHECKING:
    from tools.eiscp_sim import SimServer


@pytest.fixture
async def client(sim: SimServer) -> AsyncIterator[EiscpClient]:
    connection = EiscpClient("127.0.0.1", sim.port)
    await connection.connect()
    yield connection
    await connection.close()


async def test_query_returns_the_parameter(client: EiscpClient) -> None:
    assert await client.query("PWR") == "01"
    assert await client.query("DSS") == "112"
    assert client.connected


async def test_query_returns_na_as_text(client: EiscpClient) -> None:
    assert await client.query("SW2") == "N/A"


async def test_silent_code_raises_no_reply(client: EiscpClient) -> None:
    with pytest.raises(NoReplyError) as caught:
        await client.query("TCT", timeout=0.1)
    assert (caught.value.code, caught.value.param) == ("TCT", "QSTN")


async def test_set_returns_the_reply(client: EiscpClient) -> None:
    assert await client.set("TFR", "BUP") == "B+1T00"
    assert await client.set("DSS", "C01") == "211"


async def test_refused_set_raises_not_available(client: EiscpClient) -> None:
    with pytest.raises(NotAvailableError) as caught:
        await client.set("DIM", "03")
    assert (caught.value.code, caught.value.param) == ("DIM", "03")


async def test_ignored_set_raises_no_reply(client: EiscpClient) -> None:
    with pytest.raises(NoReplyError):
        await client.set("DCE", "01", timeout=0.1)  # a recorded silent write


async def test_command_sends_without_waiting(client: EiscpClient) -> None:
    seen: list[str] = []
    client.add_listener(lambda m: seen.append(m.code + m.param))
    await client.command("TFR", "BUP")
    await poll(lambda: "TFRB+1T00" in seen)


async def test_listener_sees_replies_and_pushes_and_can_be_removed(client: EiscpClient) -> None:
    seen: list[Message] = []
    remove = client.add_listener(seen.append)
    await client.query("MVL")
    await poll(lambda: any(m.code == "MVL" for m in seen))
    remove()
    remove()  # removing twice is harmless
    count = len(seen)
    await client.query("PWR")
    assert len(seen) == count


async def test_a_failing_listener_does_not_stop_the_connection(
    client: EiscpClient, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(_: Message) -> None:
        msg = "boom"
        raise RuntimeError(msg)

    client.add_listener(broken)
    assert await client.query("PWR") == "01"
    assert "listener failed" in caplog.text


async def test_one_request_per_code_in_flight_but_codes_overlap(client: EiscpClient) -> None:
    results = await asyncio.gather(
        client.query("MVL"), client.query("MVL"), client.query("PWR"), client.query("SLI")
    )
    assert results == ["4C", "4C", "01", "10"]


async def test_send_before_connect_raises() -> None:
    idle = EiscpClient("127.0.0.1", 1)
    assert not idle.connected
    with pytest.raises(ConnectionClosedError):
        await idle.send("PWRQSTN")


async def test_closing_the_server_side_fails_a_waiting_request(sim: SimServer) -> None:
    client = EiscpClient("127.0.0.1", sim.port)
    await client.connect()
    waiting = asyncio.create_task(client.query("TCT", timeout=5))
    await asyncio.sleep(0.05)
    await sim.stop()
    with pytest.raises(ConnectionClosedError):
        await waiting
    assert not client.connected
    assert client.close_reason == "closed by the receiver"
    with pytest.raises(ConnectionClosedError, match="closed by the receiver"):
        await client.send("PWRQSTN")
    await client.close()


async def test_close_is_repeatable_and_wait_closed_returns(sim: SimServer) -> None:
    client = EiscpClient("127.0.0.1", sim.port)
    await client.connect()
    await client.close()
    await client.close()
    await asyncio.wait_for(client.wait_closed(), 1)


async def test_garbage_from_the_receiver_closes_the_connection() -> None:
    async def talk(_: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b"HTTP/1.1 200 OK\r\n\r\nxxxxxxxxxxxxxxxxxxxxxxxx")
        await writer.drain()

    server = await asyncio.start_server(talk, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = EiscpClient("127.0.0.1", port)
    await client.connect()
    await asyncio.wait_for(client.wait_closed(), 2)
    assert client.close_reason.startswith("connection lost")
    await client.close()
    server.close()
    await server.wait_closed()
