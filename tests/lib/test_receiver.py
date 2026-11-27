"""Receiver: the timing and availability rules of contract C3, against the simulated TX-RZ50."""

import asyncio
import logging
import time
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from lib_helpers import FAST, fast_clock, make_sim, poll

from custom_components.onkyo_eiscp.lib import (
    COMMANDS,
    ConnectionClosedError,
    EiscpError,
    NoReplyError,
    NotAvailableError,
    Receiver,
    Timing,
    receiver,
)
from custom_components.onkyo_eiscp.lib.commands import Command, Kind, Reply, Value, Zone
from custom_components.onkyo_eiscp.lib.frame import Message, encode, parse_data

if TYPE_CHECKING:
    from types import ModuleType

    from tools.eiscp_sim import SimServer


class Changes:
    """Collects the ``changed`` sets a receiver reports."""

    def __init__(self, library: Receiver) -> None:
        self.sets: list[frozenset[str]] = []
        library.add_listener(self.sets.append)

    def codes(self) -> set[str]:
        return set().union(*self.sets) if self.sets else set()

    def clear(self) -> None:
        self.sets.clear()


async def other_host_sends(sim: SimServer, message: str) -> None:
    """A phone app (another host) sends a message; the receiver pushes the result to everyone."""
    _, writer = await asyncio.open_connection("127.0.0.1", sim.port, local_addr=("127.0.0.2", 0))
    writer.write(encode(message))
    await writer.drain()
    await asyncio.sleep(0.05)
    writer.close()


# ----- start, state, listeners ----------------------------------------------------------------


async def test_start_probes_and_holds_the_values(receiver: Receiver) -> None:
    caps = receiver.capabilities
    assert caps.model == "TX-RZ50"
    assert receiver.connected
    values = receiver.values
    assert values["PWR"] == "01"
    assert values["MVL"] == "4C"
    assert values["DSS"] == "112"
    assert "NRI" not in values
    assert "SW2" not in values
    assert receiver.unavailable == {"SW2"}
    assert isinstance(values, type(receiver.values))
    assert values is not receiver.values  # a copy each time


async def test_start_twice_and_capabilities_before_start(sim: SimServer) -> None:
    library = Receiver("127.0.0.1", sim.port, timing=FAST)
    with pytest.raises(EiscpError):
        _ = library.capabilities
    await library.start()
    with pytest.raises(EiscpError, match="already started"):
        await library.start()
    await library.stop()
    await library.stop()  # stopping twice is harmless
    assert not library.connected


async def test_start_fails_with_a_library_error_when_nothing_listens() -> None:
    sim = make_sim()
    await sim.start()
    port = sim.port
    await sim.stop()
    library = Receiver("127.0.0.1", port, timing=FAST)
    with pytest.raises(ConnectionClosedError, match="cannot reach"):
        await library.start()
    assert not library.connected
    with pytest.raises(ConnectionClosedError):
        await library.query("PWR")


async def test_start_fails_when_the_probe_gets_no_nri(
    sim: SimServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    sim._quiet_until = 1e18
    monkeypatch.setattr("custom_components.onkyo_eiscp.lib.capabilities.NRI_TIMEOUT", 0.1)
    library = Receiver("127.0.0.1", sim.port, timing=FAST)
    with pytest.raises(NoReplyError):
        await library.start()
    assert sim.connection_count == 0 or await _closed(sim)


async def _closed(sim: SimServer) -> bool:
    await poll(lambda: sim.connection_count == 0)
    return True


async def test_one_report_per_batch_and_listeners_can_be_removed(receiver: Receiver) -> None:
    changes = Changes(receiver)
    extra: list[frozenset[str]] = []
    remove = receiver.add_listener(extra.append)
    await receiver.set("DSS", "C01")  # pushes DBC, DSS, IFAN/A, IFA, IFV together
    await poll(lambda: {"DSS", "IFA"} <= changes.codes())
    assert len(changes.sets) <= 3  # batched, not one report per message
    assert extra
    remove()
    remove()
    count = len(extra)
    await receiver.set("DSS", "C03")
    await asyncio.sleep(0.1)
    assert len(extra) == count


async def test_a_failing_listener_is_logged_and_does_not_stop_the_others(
    receiver: Receiver, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(_: frozenset[str]) -> None:
        msg = "boom"
        raise RuntimeError(msg)

    receiver.add_listener(broken)
    changes = Changes(receiver)
    await receiver.set("TFR", "BUP")
    await poll(lambda: "TFR" in changes.codes())
    assert "receiver listener failed" in caplog.text


async def test_pushes_from_another_app_update_the_values(
    sim: SimServer, receiver: Receiver
) -> None:
    changes = Changes(receiver)
    await other_host_sends(sim, "TFRBUP")
    await poll(lambda: receiver.values["TFR"] == "B+1T00")
    assert "TFR" in changes.codes()
    changes.clear()
    await other_host_sends(sim, "TFRBUP")
    await poll(lambda: receiver.values["TFR"] == "B+2T00")


async def test_the_same_value_again_reports_nothing(receiver: Receiver) -> None:
    await receiver.set("AMT", "01")
    await asyncio.sleep(0.1)
    changes = Changes(receiver)
    await receiver.set("AMT", "01")
    await asyncio.sleep(0.1)
    assert changes.sets == []


# ----- query and set --------------------------------------------------------------------------


async def test_query_and_set(receiver: Receiver) -> None:
    assert await receiver.query("MVL") == "4C"
    assert await receiver.query("SW2") == "N/A"
    assert await receiver.set("TFR", "BUP") == "B+1T00"
    assert receiver.values["TFR"] == "B+1T00"
    assert await receiver.set("DSS", "C01") == "211"


async def test_a_set_of_an_unknown_code_is_a_plain_set(receiver: Receiver) -> None:
    with pytest.raises(NoReplyError):
        await receiver.set("ZZZ", "01")


async def test_never_query_and_never_set_codes_are_refused_locally(receiver: Receiver) -> None:
    for code in ("NLT", "NCP"):
        with pytest.raises(ValueError, match="popup"):
            await receiver.query(code)
    for code in ("SAM", "NSB", "MRM", "TGA", "NLT"):
        with pytest.raises(ValueError, match="must not be set"):
            await receiver.set(code, "FR")
    assert receiver.values["LMD"] == "82"  # SAMFR would have switched it to Stereo


async def test_send_raw_collects_every_message_in_the_window(receiver: Receiver) -> None:
    seen = await receiver.send_raw("TFRBUP", wait=0.1)
    assert "TFRB+1T00" in seen
    assert await receiver.send_raw("SAMFR", wait=0.1)  # raw is exempt from the rules
    assert receiver.values["LMD"] == "00"


async def test_a_command_without_reply_returns_an_empty_string(receiver: Receiver) -> None:
    assert await receiver.set("OSD", "MENU") == ""


async def test_read_back_codes_are_queried_after_the_set(
    receiver: Receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_lock = Command(
        code="KYL", zone=Zone.SYSTEM, kind=Kind.SETTING, value=Value.ENUM, reply=Reply.READ_BACK
    )
    monkeypatch.setattr(receiver_module(), "COMMANDS", {**COMMANDS, "KYL": key_lock})
    assert await receiver.set("KYL", "01") == "01"
    assert receiver.values["KYL"] == "01"
    assert await receiver.set("KYL", "00") == "00"


async def test_a_read_back_that_says_na_is_a_refusal(
    receiver: Receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_lock = Command(
        code="DIF", zone=Zone.SYSTEM, kind=Kind.SETTING, value=Value.ENUM, reply=Reply.READ_BACK
    )
    monkeypatch.setattr(receiver_module(), "COMMANDS", {**COMMANDS, "DIF": key_lock})
    with pytest.raises(NotAvailableError):
        await receiver.set("DIF", "01")  # the simulator refuses it, so the read back is stale


def receiver_module() -> ModuleType:
    return receiver


# ----- spacing ---------------------------------------------------------------------------------


async def test_a_mode_set_waits_for_the_receiver_to_accept_it(receiver: Receiver) -> None:
    started = time.monotonic()
    assert await receiver.set("LMD", "84") == "84"
    assert await receiver.set("LMD", "85") == "85"  # the simulator ignores it inside 3 s
    assert time.monotonic() - started >= 0.3
    assert await receiver.set("LMD", "8B") == "8B"
    assert receiver.values["LMD"] == "8B"


async def test_a_mode_set_waits_after_an_audio_setting_write(sim: SimServer) -> None:
    library = Receiver("127.0.0.1", sim.port, timing=replace(FAST, audio_spacing=0.4))
    await library.start()
    try:
        await library.set("VOC", "01")
        started = time.monotonic()
        assert await library.set("LMD", "84") == "84"
        assert time.monotonic() - started >= 0.3
    finally:
        await library.stop()


async def test_a_mode_set_waits_after_a_mode_change_by_another_app(
    sim: SimServer, receiver: Receiver
) -> None:
    await other_host_sends(sim, "LMD84")
    await poll(lambda: receiver.values["LMD"] == "84")
    started = time.monotonic()
    assert await receiver.set("LMD", "85") == "85"
    assert time.monotonic() - started >= 0.2


async def test_an_ignored_mode_set_is_retried_once(sim: SimServer) -> None:
    library = Receiver("127.0.0.1", sim.port, timing=replace(FAST, mode_spacing=0.05))
    await library.start()
    try:
        await other_host_sends(sim, "LMD84")  # the receiver now ignores mode sets for 0.3 s
        await poll(lambda: library.values["LMD"] == "84")
        assert await library.set("LMD", "85") == "85"  # first try ignored, second accepted
    finally:
        await library.stop()


async def test_a_mode_set_that_is_ignored_twice_raises(sim: SimServer) -> None:
    sim.receiver.fixture.profile["mode_lock_seconds"] = 1e6
    library = Receiver("127.0.0.1", sim.port, timing=replace(FAST, mode_spacing=0.05))
    await library.start()
    try:
        await other_host_sends(sim, "LMD84")
        await poll(lambda: library.values["LMD"] == "84")
        with pytest.raises(NoReplyError):
            await library.set("LMD", "85")
    finally:
        await library.stop()


# ----- availability ----------------------------------------------------------------------------


async def test_a_refused_set_makes_the_code_unavailable_under_that_mode_only(
    receiver: Receiver,
) -> None:
    changes = Changes(receiver)
    with pytest.raises(NotAvailableError):
        await receiver.set("MOT", "01")  # Music Optimizer works only in Stereo
    assert "MOT" in receiver.unavailable
    await poll(lambda: "MOT" in changes.codes())
    changes.clear()
    await receiver.set("LMD", "00")  # Stereo
    await poll(lambda: "MOT" not in receiver.unavailable)
    await poll(lambda: "MOT" in changes.codes())  # entities hear that it came back
    assert await receiver.set("MOT", "01") == "01"
    await receiver.set("LMD", "82")
    await poll(lambda: "MOT" in receiver.unavailable)  # back in Neural:X: refused again, no retry


async def test_a_successful_set_clears_an_old_refusal(receiver: Receiver) -> None:
    receiver._refused.add(("TFR", receiver.values["LMD"]))
    assert "TFR" in receiver.unavailable
    changes = Changes(receiver)
    await receiver.set("TFR", "BUP")
    assert "TFR" not in receiver.unavailable
    await poll(lambda: "TFR" in changes.codes())


async def test_a_refused_set_does_not_mark_the_code_na_for_every_mode(receiver: Receiver) -> None:
    with pytest.raises(NotAvailableError):
        await receiver.set("DIM", "03")
    assert "DIM" in receiver.unavailable
    await receiver.set("LMD", "84")
    await poll(lambda: "DIM" not in receiver.unavailable)
    assert await receiver.query("DIM") == "00"


async def test_a_query_that_answers_na_is_unavailable_until_it_answers_a_value(
    receiver: Receiver,
) -> None:
    assert "SW2" in receiver.unavailable
    receiver._on_message(_message("SW2", "-05"))
    assert "SW2" not in receiver.unavailable
    assert receiver.values["SW2"] == "-05"
    receiver._on_message(_message("SW2", "N/A"))
    assert "SW2" in receiver.unavailable
    assert "SW2" not in receiver.values


def _message(code: str, param: str) -> Message:
    return parse_data(f"!1{code}{param}")


# ----- re-read ---------------------------------------------------------------------------------


async def test_settings_that_depend_on_the_input_are_read_again(sim: SimServer) -> None:
    sim.receiver.input_swl["22"] = "-1E"  # PHONO keeps its own subwoofer level, not pushed
    library = Receiver("127.0.0.1", sim.port, timing=FAST)
    await library.start()
    try:
        assert library.values["SWL"] == "-0A"
        changes = Changes(library)
        await library.set("SLI", "22")
        await poll(lambda: library.values.get("SWL") == "-1E")
        assert "SWL" in changes.codes()
        await library.set("SLI", "10")
        await poll(lambda: library.values.get("SWL") == "-0A")
    finally:
        await library.stop()


async def test_settings_are_read_again_after_a_mode_change(
    sim: SimServer, receiver: Receiver
) -> None:
    sim.receiver.values["LTN"] = "03"  # changed behind the client's back, no push
    assert receiver.values["LTN"] == "00"
    await receiver.set("LMD", "84")
    await poll(lambda: receiver.values["LTN"] == "03")


async def test_a_new_context_change_restarts_the_wait(receiver: Receiver) -> None:
    await receiver.set("SLI", "02")
    await receiver.set("SLI", "01")
    await receiver.set("SLI", "10")
    await asyncio.sleep(0.2)
    assert receiver.values["SLI"] == "10"


# ----- power -----------------------------------------------------------------------------------


async def test_the_volume_is_put_back_after_power_on(sim: SimServer, receiver: Receiver) -> None:
    assert receiver.values["MVL"] == "4C"
    await receiver.set("PWR", "00")
    await poll(lambda: receiver.values["PWR"] == "00")
    assert receiver.values["MVL"] == "4C"  # standby keeps the stored level
    await receiver.set("PWR", "01")
    await poll(lambda: sim.receiver.values["MVL"] == "4C", seconds=3)  # 7C, then set back
    await poll(lambda: receiver.values["MVL"] == "4C")


async def test_power_on_with_a_slow_receiver_still_ends_with_the_old_volume(sim: SimServer) -> None:
    sim.power_on_delay = 0.3  # the PWR01 push comes late
    sim.power_on_quiet = 0.5  # and queries get no answer for a while
    library = Receiver("127.0.0.1", sim.port, timing=FAST)
    await library.start()
    try:
        await library.set("PWR", "00")
        await poll(lambda: library.values["PWR"] == "00")
        changes = Changes(library)
        with pytest.raises(NoReplyError):  # the set echoes only through the delayed push
            await library.set("PWR", "01")
        await poll(lambda: library.values["PWR"] == "01", seconds=3)
        await poll(lambda: sim.receiver.values["MVL"] == "4C", seconds=3)
        await poll(lambda: library.values["MVL"] == "4C", seconds=3)
        await asyncio.sleep(1.0)  # the retries at 0.3 s and 0.6 s and the full read finish
        assert library.values["LMD"] == "82"
        assert changes.codes()
    finally:
        await library.stop()


async def test_the_volume_stays_when_restoring_is_off(sim: SimServer) -> None:
    library = Receiver("127.0.0.1", sim.port, restore_volume=False, timing=FAST)
    await library.start()
    try:
        await library.set("PWR", "00")
        await poll(lambda: library.values["PWR"] == "00")
        await library.set("PWR", "01")
        await poll(lambda: library.values["PWR"] == "01")
        await asyncio.sleep(0.5)
        assert library.values["MVL"] == "7C"
    finally:
        await library.stop()


async def test_no_restore_when_the_receiver_came_up_at_a_lower_volume(sim: SimServer) -> None:
    sim.receiver.fixture.profile["power_on_volume"] = "20"
    library = Receiver("127.0.0.1", sim.port, timing=FAST)
    await library.start()
    try:
        await library.set("PWR", "00")
        await poll(lambda: library.values["PWR"] == "00")
        await library.set("PWR", "01")
        await poll(lambda: library.values["MVL"] == "20")
        await asyncio.sleep(0.4)
        assert library.values["MVL"] == "20"
    finally:
        await library.stop()


async def test_started_in_standby_the_stored_volume_is_the_one_to_restore(sim: SimServer) -> None:
    sim.receiver.handle("PWR", "00")
    library = Receiver("127.0.0.1", sim.port, timing=FAST)
    await library.start()
    try:
        assert library.values["PWR"] == "00"
        await library.set("PWR", "01")
        await poll(lambda: sim.receiver.values["MVL"] == "4C", seconds=3)
    finally:
        await library.stop()


async def test_power_off_cancels_the_power_on_work(receiver: Receiver) -> None:
    await receiver.set("PWR", "00")
    await poll(lambda: receiver.values["PWR"] == "00")
    await receiver.set("PWR", "01")
    await receiver.set("PWR", "00")
    await asyncio.sleep(0.3)
    assert receiver.values["PWR"] == "00"
    assert not receiver._power_tasks


async def test_the_volume_put_back_gives_up_quietly(
    receiver: Receiver, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    receiver._on_message(_message("MVL", "7C"))
    calls: list[str] = []

    async def no_reply(code: str, param: str) -> str:
        calls.append(code + param)
        raise NoReplyError(code, param)

    monkeypatch.setattr(receiver, "set", no_reply)
    with caplog.at_level(logging.WARNING):
        await receiver._put_volume_back("4C")
    assert calls == ["MVL4C"] * 3
    assert "could not put the volume back" in caplog.text

    async def refused(code: str, param: str) -> str:
        raise NotAvailableError(code, param)

    monkeypatch.setattr(receiver, "set", refused)
    await receiver._put_volume_back("4C")  # any other library error ends it at once
    await receiver._put_volume_back("ZZ")  # not a hex volume
    receiver._values.pop("MVL")
    await receiver._put_volume_back("4C")  # no current volume known: assume it is fine


async def test_a_new_capability_found_after_power_on_is_reported(receiver: Receiver) -> None:
    capabilities = receiver.capabilities
    receiver._capabilities = replace(capabilities, supported=capabilities.supported - {"TPD"})
    changes = Changes(receiver)
    await receiver._read_everything()
    await poll(lambda: "*" in changes.codes())
    assert "TPD" in receiver.capabilities.supported
    changes.clear()
    await receiver._read_everything()  # nothing new, so nothing reported
    await asyncio.sleep(0.05)
    assert "*" not in changes.codes()


async def test_helpers_do_nothing_without_a_connection(receiver: Receiver) -> None:
    await receiver.stop()
    assert await receiver._read(["PWR"]) == []
    await receiver._read_everything()
    with pytest.raises(ConnectionClosedError):
        await receiver.set("TFR", "BUP")
    with pytest.raises(ConnectionClosedError):
        await receiver.send_raw("PWRQSTN")


async def test_a_failing_background_task_is_logged(
    receiver: Receiver, caplog: pytest.LogCaptureFixture
) -> None:
    async def broken() -> None:
        msg = "boom"
        raise RuntimeError(msg)

    receiver._spawn(broken())
    await asyncio.sleep(0.05)
    assert "background task failed" in caplog.text


# ----- connection supervision ------------------------------------------------------------------


async def test_the_connection_comes_back_after_the_receiver_closes_it(
    sim: SimServer, receiver: Receiver
) -> None:
    changes = Changes(receiver)
    for writer in list(sim._connections):
        sim._drop(writer)
    await poll(lambda: not receiver.connected)
    await poll(lambda: receiver.connected)
    assert "*" in changes.codes()
    assert sim.connection_count == 1  # never two connections from this host
    assert await receiver.query("PWR") == "01"


async def test_the_values_are_read_again_after_a_reconnect(
    sim: SimServer, receiver: Receiver
) -> None:
    sim.receiver.values["MVL"] = "50"
    for writer in list(sim._connections):
        sim._drop(writer)
    await poll(lambda: receiver.values["MVL"] == "50", seconds=5)


async def test_reconnect_keeps_trying_while_the_receiver_is_gone(sim: SimServer) -> None:
    library = Receiver("127.0.0.1", sim.port, timing=FAST)
    await library.start()
    port = sim.port
    try:
        await sim.stop()
        await poll(lambda: not library.connected)
        await asyncio.sleep(0.4)  # several refused attempts
        again = make_sim(port=port)
        await again.start()
        try:
            await poll(lambda: library.connected, seconds=5)
            assert again.connection_count == 1
        finally:
            await library.stop()
            await again.stop()
    finally:
        await library.stop()


async def test_a_silent_connection_is_closed_and_reopened(
    sim: SimServer, receiver: Receiver
) -> None:
    sim._quiet_until = asyncio.get_running_loop().time() + 0.5  # connected, but no query answered
    await poll(lambda: not receiver.connected, seconds=3)
    await poll(lambda: receiver.connected, seconds=5)
    assert await receiver.query("PWR") == "01"


async def test_stop_while_reconnecting_ends_cleanly(sim: SimServer) -> None:
    library = Receiver("127.0.0.1", sim.port, timing=FAST)
    await library.start()
    await sim.stop()
    await poll(lambda: not library.connected)
    await library.stop()
    assert not library.connected


def test_the_default_timing_is_the_measured_one() -> None:
    timing = Timing()
    assert (timing.keepalive_interval, timing.keepalive_timeout) == (60.0, 10.0)
    assert timing.backoff == (1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
    assert (timing.mode_spacing, timing.audio_spacing, timing.reread_delay) == (3.5, 1.0, 1.5)
    assert (timing.power_on_delay, timing.power_on_retries) == (3.0, (10.0, 20.0))
    assert timing.volume_restore_delay == 3.0
    assert fast_clock() > 0


async def test_stopping_drops_a_report_that_was_about_to_go_out(receiver: Receiver) -> None:
    changes = Changes(receiver)
    receiver._mark("PWR")
    await receiver.stop()
    await asyncio.sleep(0.05)
    assert changes.sets == []
