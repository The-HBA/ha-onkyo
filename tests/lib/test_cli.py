"""The command line, run against the simulator (it only reads)."""

import asyncio
import functools
import runpy
import sys
from typing import TYPE_CHECKING, Any

import pytest
from lib_helpers import FAST, make_sim

from custom_components.onkyo_eiscp.lib import Receiver, cli
from custom_components.onkyo_eiscp.lib.frame import encode

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from tools.eiscp_sim import SimServer


@pytest.fixture(autouse=True)
def fast_receiver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "Receiver", functools.partial(Receiver, timing=FAST))


async def run(*argv: str) -> int:
    return await asyncio.to_thread(cli.main, list(argv))


async def test_read_prints_decoded_values(
    sim: SimServer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await run("read", "--host", "127.0.0.1", "--port", str(sim.port)) == 0
    out = capsys.readouterr().out
    assert "PWR 01  ->  on" in out
    assert "MVL 4C  ->  76" in out
    assert "DSS 112" in out
    assert "IFA HDMI 1,PCM" in out


async def test_read_named_codes_shows_na_silence_and_refusals(
    sim: SimServer, capsys: pytest.CaptureFixture[str]
) -> None:
    code = await run("read", "--host", "127.0.0.1", "--port", str(sim.port), "mvl", "SW2", "TCT")
    assert code == 0
    out = capsys.readouterr().out
    assert "MVL 4C" in out
    assert "SW2 N/A" in out
    assert "TCT no reply to TCTQSTN" in out


async def test_read_never_queries_the_popup_codes(
    sim: SimServer, capsys: pytest.CaptureFixture[str]
) -> None:
    await run("read", "--host", "127.0.0.1", "--port", str(sim.port), "NLT", "XYZ", "FWV")
    out = capsys.readouterr().out
    assert "NLT NLT must not be queried" in out
    assert "FWV R145111912840034" in out


async def test_info_lists_the_capabilities(
    sim: SimServer, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await run("info", "--host", "127.0.0.1", "--port", str(sim.port)) == 0
    out = capsys.readouterr().out
    assert "ONKYO TX-RZ50  firmware R145-1119-1284-0034-0000" in out
    assert "main (Main), zone2 (Zone2), zone3 (Zone3)" in out
    assert "10  Movie" in out
    assert "supported codes" in out
    assert "unavailable now: SW2" in out


async def test_listen_prints_changes(sim: SimServer, capsys: pytest.CaptureFixture[str]) -> None:
    listening = asyncio.create_task(
        run("listen", "--host", "127.0.0.1", "--port", str(sim.port), "--seconds", "1.2")
    )
    await asyncio.sleep(0.7)  # the command line is connected by now
    _, writer = await asyncio.open_connection("127.0.0.1", sim.port, local_addr=("127.0.0.2", 0))
    writer.write(encode("TFRBUP"))
    await writer.drain()
    assert await listening == 0
    writer.close()
    assert "TFR B+1T00  ->  Tone(bass=1, treble=0)" in capsys.readouterr().out


async def test_discover_prints_and_returns_one_when_nobody_answers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sim = make_sim(udp=True)
    await sim.start()
    try:
        args = ("discover", "--host", "127.0.0.1", "--port", str(sim.port), "--timeout", "1")
        assert await run(*args) == 0
        assert f"127.0.0.1:{sim.port}  TX-RZ50  0009B0000001" in capsys.readouterr().out
    finally:
        await sim.stop()
    args = ("discover", "--host", "127.0.0.1", "--port", "9", "--timeout", "0.1")
    assert await run(*args) == 1
    assert "no receiver answered" in capsys.readouterr().err


async def test_an_unreachable_receiver_is_an_error_not_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sim = make_sim()
    await sim.start()
    port = sim.port
    await sim.stop()
    assert await run("info", "--host", "127.0.0.1", "--port", str(port)) == 2
    assert "error: cannot reach" in capsys.readouterr().err


async def test_module_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    sim = make_sim(udp=True)
    await sim.start()
    argv = ["x", "discover", "--host", "127.0.0.1", "--port", str(sim.port), "--timeout", "1"]
    monkeypatch.setattr(sys, "argv", argv)

    def call() -> None:
        runpy.run_module("custom_components.onkyo_eiscp.lib", run_name="__main__")

    with pytest.raises(SystemExit) as stop:
        await asyncio.to_thread(call)
    assert stop.value.code == 0
    await sim.stop()


def test_a_keyboard_interrupt_exits_quietly(monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupted(coroutine: Coroutine[Any, Any, int]) -> None:
        coroutine.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.asyncio, "run", interrupted)
    assert cli.main(["info", "--host", "127.0.0.1"]) == 130


def test_the_command_line_has_no_way_to_write() -> None:
    commands = {"discover", "info", "read", "listen"}
    parser_source = cli.__doc__ or ""
    assert "never sets anything" in parser_source
    with pytest.raises(SystemExit):
        cli.main(["set", "--host", "127.0.0.1"])
    assert commands  # the four read-only commands are all there is


def test_a_value_that_cannot_be_decoded_is_shown_as_it_came() -> None:
    assert cli._show("MVL", "ZZ") == "MVL ZZ"
    assert cli._show("QQQ", "01") == "QQQ 01"


async def test_the_command_line_never_puts_the_volume_back(
    sim: SimServer, capsys: pytest.CaptureFixture[str]
) -> None:
    sim.receiver.handle("PWR", "00")
    listening = asyncio.create_task(
        run("listen", "--host", "127.0.0.1", "--port", str(sim.port), "--seconds", "1.6")
    )
    await asyncio.sleep(0.6)
    await other_host_sends(sim, "PWR01")  # the receiver comes up at 7C
    assert await listening == 0
    assert sim.receiver.values["MVL"] == "7C"  # a library set would have put 4C back
    assert "MVL 7C" in capsys.readouterr().out


async def other_host_sends(sim: SimServer, message: str) -> None:
    _, writer = await asyncio.open_connection("127.0.0.1", sim.port, local_addr=("127.0.0.2", 0))
    writer.write(encode(message))
    await writer.drain()
    await asyncio.sleep(0.05)
    writer.close()
