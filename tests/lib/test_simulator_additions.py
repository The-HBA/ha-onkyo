"""Simulator gaps closed for the library (C2): SWL per input, mute, UDP, slow power-on."""

import asyncio
import time

import pytest
from lib_helpers import FIXTURE, SPEED, fast_clock, make_sim

from custom_components.onkyo_eiscp.lib import Discovered, EiscpClient, discover
from tools.eiscp_sim import Fixture, Receiver, SimServer
from tools.eiscp_sim.server import UDP_SIZE, discovery_packet


@pytest.fixture
def sim_receiver() -> Receiver:
    return Receiver(Fixture.load(FIXTURE), fast_clock)


def value(receiver: Receiver, code: str) -> str:
    (reply,) = receiver.handle(code, "QSTN").replies
    return reply[3:]


# ----- SWL is stored per input -----------------------------------------------------------------


def test_the_subwoofer_level_is_remembered_per_input(sim_receiver: Receiver) -> None:
    assert value(sim_receiver, "SWL") == "-0A"
    sim_receiver.handle("SWL", "-05")  # on Movie
    messages = sim_receiver.handle("SLI", "11").broadcast
    assert not [m for m in messages if m.startswith("SWL")]  # not pushed: the client must read it
    assert value(sim_receiver, "SWL") == "-05"  # an input nobody set keeps the level it had
    sim_receiver.handle("SWL", "-0C")  # on Streaming
    sim_receiver.handle("SLI", "10")
    assert value(sim_receiver, "SWL") == "-05"
    sim_receiver.handle("SLI", "11")
    assert value(sim_receiver, "SWL") == "-0C"


def test_a_seeded_input_level_is_used_and_the_same_input_is_a_no_op(sim_receiver: Receiver) -> None:
    sim_receiver.input_swl["22"] = "-1E"
    sim_receiver.handle("SLI", "22")
    assert value(sim_receiver, "SWL") == "-1E"
    assert sim_receiver.handle("SLI", "22").broadcast == ["SLI22"]
    assert value(sim_receiver, "SWL") == "-1E"


# ----- power-off clears mute -------------------------------------------------------------------


def test_power_off_clears_mute(sim_receiver: Receiver) -> None:
    sim_receiver.handle("AMT", "01")
    assert value(sim_receiver, "AMT") == "01"
    pushed = sim_receiver.handle("PWR", "00").broadcast
    assert "AMT00" in pushed
    assert value(sim_receiver, "AMT") == "00"
    sim_receiver.handle("PWR", "01")
    assert value(sim_receiver, "AMT") == "00"


def test_power_off_pushes_amt_once_when_the_profile_already_lists_it(
    sim_receiver: Receiver,
) -> None:
    sim_receiver.handle("AMT", "01")
    pushed = sim_receiver.handle("PWR", "00").broadcast
    assert pushed.count("AMT00") == 1


def test_power_off_adds_the_mute_push_when_the_profile_has_none(sim_receiver: Receiver) -> None:
    sim_receiver.fixture.profile["power_off_pushes"] = ["TGA00"]
    sim_receiver.handle("AMT", "01")
    assert sim_receiver.handle("PWR", "00").broadcast == ["PWR00", "TGA00", "AMT00"]


# ----- UDP discovery ---------------------------------------------------------------------------


def test_the_discovery_answer_names_model_port_and_mac(sim_receiver: Receiver) -> None:
    assert sim_receiver.discovery_answer(60128) == "ECNTX-RZ50/60128/XX/0009B0000001"


def test_the_discovery_packet_is_padded_with_nul_bytes() -> None:
    packet = discovery_packet("ECNTX-RZ50/60128/XX/0009B0000001")
    assert len(packet) == UDP_SIZE
    assert packet[16:].rstrip(b"\x00").endswith(b"\x19\r\n")
    assert packet.endswith(b"\x00")


async def test_udp_discovery_is_answered_and_other_datagrams_are_not() -> None:
    sim = make_sim(udp=True)
    await sim.start()
    try:
        found = await discover("127.0.0.1", timeout=1.0, port=sim.port)
        assert found == [Discovered("127.0.0.1", sim.port, "TX-RZ50", "0009B0000001")]

        loop = asyncio.get_running_loop()
        got: list[bytes] = []

        class Listen(asyncio.DatagramProtocol):
            def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:  # noqa: ARG002
                got.append(data)

        transport, _ = await loop.create_datagram_endpoint(Listen, local_addr=("127.0.0.1", 0))
        for junk in (b"short", b"ISCP" + bytes(12) + b"!1PWRQSTN\r", bytes(16) + b"!pECNQSTN\r"):
            transport.sendto(junk, ("127.0.0.1", sim.port))
        await asyncio.sleep(0.2)
        transport.close()
        assert got == []  # as on the real receiver, only !xECNQSTN is answered
    finally:
        await sim.stop()


async def test_without_udp_nothing_listens_on_the_udp_port() -> None:
    sim = make_sim()
    await sim.start()
    try:
        assert await discover("127.0.0.1", timeout=0.2, port=sim.port) == []
    finally:
        await sim.stop()


# ----- slow power-on ---------------------------------------------------------------------------


async def test_a_slow_power_on_holds_the_pushes_back_and_leaves_queries_unanswered() -> None:
    sim = make_sim(power_on_delay=0.3, power_on_quiet=0.5)
    await sim.start()
    client = EiscpClient("127.0.0.1", sim.port)
    seen: list[str] = []
    client.add_listener(lambda m: seen.append(m.code + m.param))
    await client.connect()
    try:
        await client.command("PWR", "00")
        await asyncio.sleep(0.1)
        started = time.monotonic()
        await client.command("PWR", "01")
        await asyncio.sleep(0.15)
        assert "PWR01" not in seen  # held back
        await client.command("MVL", "QSTN")
        await asyncio.sleep(0.1)
        assert not [m for m in seen if m.startswith("MVL")]  # quiet: queries unanswered
        async with asyncio.timeout(2):
            while "PWR01" not in seen:  # noqa: ASYNC110
                await asyncio.sleep(0.01)
        assert time.monotonic() - started >= 0.28
        assert "MVL7C" in seen  # the burst arrives together
        await asyncio.sleep(0.4)
        assert await client.query("MVL") == "7C"  # quiet is over
    finally:
        await client.close()
        await sim.stop()


async def test_power_on_without_a_delay_answers_at_once() -> None:
    sim = make_sim()
    await sim.start()
    client = EiscpClient("127.0.0.1", sim.port)
    await client.connect()
    try:
        await client.command("PWR", "00")
        await asyncio.sleep(0.05)
        assert await client.set("PWR", "01") == "01"
        assert await client.query("MVL") == "7C"
    finally:
        await client.close()
        await sim.stop()


def test_the_simulator_clock_runs_faster_than_real_time() -> None:
    first = fast_clock()
    time.sleep(0.05)
    assert fast_clock() - first >= 0.05 * SPEED * 0.8
    assert isinstance(SimServer, type)
