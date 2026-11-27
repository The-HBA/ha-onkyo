"""Discovery over UDP against the simulator, and the answer parser."""

from typing import TYPE_CHECKING

import pytest
from lib_helpers import make_sim

from custom_components.onkyo_eiscp.lib import Discovered, discover, discovery
from custom_components.onkyo_eiscp.lib.discovery import parse_answer

if TYPE_CHECKING:
    from tools.eiscp_sim import SimServer


@pytest.fixture
async def udp_sim() -> SimServer:  # type: ignore[misc]
    server = make_sim(udp=True)
    await server.start()
    yield server  # type: ignore[misc]
    await server.stop()


async def test_unicast_discovery_finds_the_receiver(udp_sim: SimServer) -> None:
    found = await discover("127.0.0.1", timeout=1.0, port=udp_sim.port)
    assert found == [Discovered("127.0.0.1", udp_sim.port, "TX-RZ50", "0009B0000001")]


async def test_unicast_discovery_without_an_answer_returns_empty() -> None:
    sim = make_sim()  # no UDP answer
    await sim.start()
    try:
        assert await discover("127.0.0.1", timeout=0.2, port=sim.port) == []
    finally:
        await sim.stop()


async def test_broadcast_discovery_waits_and_collects(
    udp_sim: SimServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(discovery, "BROADCAST", "127.0.0.1")  # stand in for the local network
    found = await discover(None, timeout=0.3, port=udp_sim.port)
    assert [item.model for item in found] == ["TX-RZ50"]


def test_answer_is_parsed_with_either_padding() -> None:
    body = b"!1ECNTX-RZ50/60128/XX/0009B0000001\x19\r\n"
    header = b"ISCP\x00\x00\x00\x10" + len(body).to_bytes(4, "big") + b"\x01\x00\x00\x00"
    expected = Discovered("10.0.0.5", 60128, "TX-RZ50", "0009B0000001")
    assert parse_answer(header + body + b"\x00" * 20, "10.0.0.5") == expected
    assert parse_answer(header + body, "10.0.0.5") == expected


def test_answer_with_a_colon_mac_and_a_slash_in_the_model() -> None:
    body = b"!1ECNTX/NR609/60128/DX/00:09:b0:00:00:01\x19\r\n"
    header = b"ISCP\x00\x00\x00\x10" + len(body).to_bytes(4, "big") + b"\x01\x00\x00\x00"
    found = parse_answer(header + body, "h")
    assert found is not None
    assert found.model == "TX/NR609"
    assert found.mac == "0009B0000001"


@pytest.mark.parametrize(
    "body",
    [b"!1PWR01\r\n", b"garbage", b"!1ECNonly/two\r\n", b"!1ECNm/notaport/XX/0009B0000001\r\n"],
)
def test_other_datagrams_are_not_answers(body: bytes) -> None:
    header = b"ISCP\x00\x00\x00\x10" + len(body).to_bytes(4, "big") + b"\x01\x00\x00\x00"
    assert parse_answer(header + body, "h") is None
