"""The receiver simulator (tools/eiscp_sim) against the sanitized TX-RZ50 fixture."""

import asyncio
import json
import re
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest

from custom_components.onkyo_eiscp.lib import EiscpClient, FrameParser, Message, encode
from tools import sanitize_capture
from tools.eiscp_sim import Fixture, Receiver, SimServer

FIXTURE = Path(__file__).parents[1] / "fixtures" / "tx-rz50"
FIXTURE_DATA = Fixture.load(FIXTURE)
PLACEHOLDER_MAC = "0009B0000001"


class Clock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def receiver(clock: Clock) -> Receiver:
    return Receiver(Fixture.load(FIXTURE), clock)


def ask(receiver: Receiver, code: str) -> list[str]:
    return receiver.handle(code, "QSTN").replies


def value(receiver: Receiver, code: str) -> str:
    (reply,) = ask(receiver, code)
    return reply[3:]


# ----- queries as captured -------------------------------------------------------------------


@pytest.mark.parametrize("code", sorted(FIXTURE_DATA.on))
def test_every_captured_query_answers_as_captured(receiver: Receiver, code: str) -> None:
    assert ask(receiver, code) == [code + FIXTURE_DATA.on[code]]


def test_nri_file_equals_the_nri_answer(receiver: Receiver) -> None:
    assert ask(receiver, "NRI") == ["NRI" + FIXTURE_DATA.nri]


@pytest.mark.parametrize("code", ["TCT", "TSW", "RES", "ECN", "ZZZ", "ADY", "MT4"])
def test_unknown_and_unsupported_codes_stay_silent(receiver: Receiver, code: str) -> None:
    assert ask(receiver, code) == []
    result = receiver.handle(code, "01")
    assert result.replies == []
    assert result.broadcast == []


@pytest.mark.parametrize("code", ["SW2", "NLS", "DSN"])
def test_codes_that_answer_na_keep_answering_na(receiver: Receiver, code: str) -> None:
    assert ask(receiver, code) == [code + "N/A"]


# ----- standby and power ----------------------------------------------------------------------


def test_standby_answers_as_captured(receiver: Receiver) -> None:
    result = receiver.handle("PWR", "00")
    assert result.broadcast[0] == "PWR00"
    assert "TGA00" in result.broadcast
    for code, standby in FIXTURE_DATA.standby.items():
        assert ask(receiver, code) == ([] if standby is None else [code + standby])
    assert value(receiver, "PWR") == "00"
    assert value(receiver, "MVL") == FIXTURE_DATA.on["MVL"]  # standby keeps the stored level


def test_sets_in_standby_are_refused_except_power(receiver: Receiver) -> None:
    receiver.handle("PWR", "00")
    assert receiver.handle("TFR", "BUP").replies == ["TFRN/A"]
    assert receiver.handle("DBC", "01").replies == []  # silent codes stay silent


def test_power_on_pushes_the_burst_and_resets_the_volume(receiver: Receiver) -> None:
    receiver.handle("PWR", "00")
    messages = receiver.handle("PWR", "01").broadcast
    assert messages[0] == "PWR01"
    for code in ("SLI", "DIM", "TGA", "LMD", "TFR", "PCT", "DGF", "STW", "FLD", "MVL"):
        assert any(m.startswith(code) for m in messages), code
    assert "MVL7C" in messages  # power-on level, although it was 4C before
    assert value(receiver, "MVL") == "7C"
    assert value(receiver, "TGA") == "01"
    assert value(receiver, "FLD") == "4D6F766965202020202D32302E30"  # "Movie    -20.0"


def test_power_set_to_the_same_value_echoes(receiver: Receiver) -> None:
    assert receiver.handle("PWR", "01").broadcast == ["PWR01"]


# ----- writes: accepted, refused, silent -----------------------------------------------------


def records(*kinds: str) -> list[tuple[str, str]]:
    found = [
        (code, write.param)
        for (code, _), items in FIXTURE_DATA.writes.items()
        for write in items
        if write.kind in kinds and write.before == FIXTURE_DATA.on.get(code)
    ]
    return sorted(set(found))


@pytest.mark.parametrize(("code", "param"), records("changed"))
def test_recorded_accepted_write_gives_the_recorded_reply(
    receiver: Receiver, code: str, param: str
) -> None:
    (write,) = [w for w in FIXTURE_DATA.writes[code, param] if w.before == FIXTURE_DATA.on[code]][
        :1
    ]
    result = receiver.handle(code, param)
    if write.reply is None:  # KYL, IRL answer on the display only
        assert not [m for m in result.broadcast if m.startswith(code)]
    else:
        assert result.broadcast[0] == code + write.reply
    assert value(receiver, code) == write.readback


@pytest.mark.parametrize(("code", "param"), records("refused"))
def test_recorded_refused_write_answers_na_to_the_asker_only(
    receiver: Receiver, code: str, param: str
) -> None:
    result = receiver.handle(code, param)
    assert result.replies == [code + "N/A"]
    assert result.broadcast == []
    assert value(receiver, code) == FIXTURE_DATA.on[code]


@pytest.mark.parametrize(("code", "param"), records("silent", "same_silent"))
def test_recorded_silent_write_gets_no_reply_and_no_change(
    receiver: Receiver, code: str, param: str
) -> None:
    result = receiver.handle(code, param)
    assert result.replies == []
    assert not [m for m in result.broadcast if m.startswith(code)]
    assert value(receiver, code) == FIXTURE_DATA.on[code]


def test_ignored_write_echoes_the_old_value(receiver: Receiver) -> None:
    assert receiver.handle("DGF", "02").broadcast == ["DGF03"]
    assert value(receiver, "DGF") == "03"


def test_values_never_seen_are_refused(receiver: Receiver) -> None:
    assert receiver.handle("DIM", "03").replies == ["DIMN/A"]
    assert receiver.handle("DSS", "211").replies == ["DSSN/A"]  # the survey saw this refused
    assert receiver.handle("TFR", "BUP").broadcast == ["TFRB+1T00"]


def test_tone_steps_and_range(receiver: Receiver) -> None:
    for _ in range(10):
        receiver.handle("TFR", "BUP")
    assert value(receiver, "TFR") == "B+AT00"
    assert receiver.handle("TFR", "BUP").replies == ["TFRN/A"]
    assert receiver.handle("TFR", "T-2").broadcast == ["TFRB+AT-2"]


def test_volume_steps_in_half_decibels(receiver: Receiver) -> None:
    assert receiver.handle("MVL", "DOWN").broadcast[0] == "MVL4B"
    assert receiver.handle("MVL", "4C").broadcast[0] == "MVL4C"
    assert receiver.handle("MVL", "UP").broadcast[0] == "MVL4D"
    assert receiver.handle("MVL", "ZZ").replies == ["MVLN/A"]


def test_sub_level_sync_and_sleep(receiver: Receiver) -> None:
    assert receiver.handle("SWL", "-09").broadcast == ["SWL-09"]
    assert receiver.handle("SWL", "UP").broadcast == ["SWL-08"]
    assert receiver.handle("AVS", "UP").broadcast == ["AVS+005"]
    assert receiver.handle("AVS", "DOWN").broadcast == ["AVS0000"]
    assert receiver.handle("SLP", "UP").broadcast == ["SLP1E"]
    assert receiver.handle("SLP", "OFF").broadcast == ["SLPOFF"]
    assert receiver.handle("SLP", "0A").broadcast == ["SLP0A"]


def test_dirac_slots_write_with_dsscxx(receiver: Receiver) -> None:
    assert value(receiver, "DSS") == "112"
    assert receiver.handle("DSS", "C01").broadcast[:2] == ["DSS211", "DBC00"]
    assert value(receiver, "DSS") == "211"
    assert receiver.handle("DSS", "C03").broadcast[0] == "DSS112"  # back, from another slot
    assert receiver.handle("DSS", "C03").broadcast == ["DSS112"]  # same slot: echo only
    off = receiver.handle("DSS", "C00").broadcast
    assert off[0] == "DSS111"
    assert {"AEQ00", "MOT00", "STW00"} <= set(off)
    assert value(receiver, "DSS") == "111"


def test_zone_3_refuses_power_on_and_pushes_the_status_code(receiver: Receiver) -> None:
    assert value(receiver, "MRM") == "00"
    assert receiver.handle("PW3", "01").broadcast[:2] == ["PW300", "MRM44"]
    assert value(receiver, "PW3") == "00"
    assert value(receiver, "MRM") == "44"  # stays, as on the real receiver


def test_same_value_sam_switches_the_listening_mode_to_stereo(receiver: Receiver) -> None:
    assert value(receiver, "LMD") == "82"
    messages = receiver.handle("SAM", "FR").broadcast
    assert "LMD00" in messages
    assert value(receiver, "LMD") == "00"
    assert "Stereo" in value_ifa(receiver)


def value_ifa(receiver: Receiver) -> str:
    return value(receiver, "IFA")


def test_osd_keys_get_no_reply(receiver: Receiver) -> None:
    assert receiver.handle("OSD", "MENU").replies == []


# ----- inputs ---------------------------------------------------------------------------------


def test_every_nri_input_is_accepted_except_the_zone_only_source(receiver: Receiver) -> None:
    assert receiver.handle("SLI", "80").replies == ["SLIN/A"]
    for sid in FIXTURE_DATA.inputs:
        if sid in {"80", "10"}:
            continue
        reply = receiver.handle("SLI", sid).broadcast
        assert reply[0] == f"SLI{sid}", sid
        assert value(receiver, "SLI") == sid
    assert receiver.handle("SLI", "FF").replies == ["SLIN/A"]


def test_input_without_signal_uses_mode_0c_and_movie_gets_its_own_back(receiver: Receiver) -> None:
    messages = receiver.handle("SLI", "01").broadcast
    assert "LMD0C" in messages
    assert value(receiver, "LMD") == "0C"
    assert value(receiver, "IFA").startswith("ANALOG,")
    back = receiver.handle("SLI", "10").broadcast
    assert "LMD82" in back
    assert value(receiver, "LMD") == "82"
    assert value(receiver, "IFA") == FIXTURE_DATA.on["IFA"]


def test_passing_fm_moves_the_tuner_to_fm(receiver: Receiver) -> None:
    assert value(receiver, "TUN") == "00522"
    receiver.handle("SLI", "24")
    assert value(receiver, "TUN") == "08750"


def test_display_shows_the_input_and_the_volume(receiver: Receiver) -> None:
    receiver.handle("SLI", "02")
    receiver.handle("MVL", "50")
    text = bytes.fromhex(value(receiver, "FLD")).decode("latin-1")
    assert text == "PS5      -42.0"


# ----- listening modes -------------------------------------------------------------------------

STEREO_PCM = [
    "82", "84", "85", "8B", "8C", "89", "8A", "08", "09", "0A", "0B", "03", "05", "06", "0E",
    "0C", "13", "0D", "11", "01", "00", "0F", "80",
]  # fmt: skip


def test_mode_set_within_three_seconds_of_a_mode_change_is_ignored(
    receiver: Receiver, clock: Clock
) -> None:
    clock.now += 60
    first = receiver.handle("LMD", "84")
    assert first.broadcast[0] == "LMD84"
    clock.now += 2.9
    ignored = receiver.handle("LMD", "85")
    assert ignored.replies == []
    assert ignored.broadcast == []
    assert value(receiver, "LMD") == "84"
    clock.now += 0.2
    assert receiver.handle("LMD", "85").broadcast[0] == "LMD85"
    assert "THX Cinema" in value_ifa(receiver)


def test_mode_set_alone_is_accepted_and_names_follow_the_ifa_field(
    receiver: Receiver, clock: Clock
) -> None:
    clock.now += 60
    receiver.handle("LMD", "0A")
    assert value(receiver, "IFA") == "HDMI 1,PCM,44.1 kHz,2.0 ch,Studio-Mix,6.1 ch,"
    clock.now += 4
    receiver.handle("LMD", "11")
    assert value(receiver, "IFA") == "HDMI 1,PCM,44.1 kHz,2.0 ch,Pure Audio,2.0 ch,"


def test_stereo_pcm_offers_23_modes_and_lmdup_cycles_them(receiver: Receiver, clock: Clock) -> None:
    seen = []
    for _ in range(len(STEREO_PCM)):
        clock.now += 4
        seen.append(receiver.handle("LMD", "UP").broadcast[0][3:])
    assert seen == [*STEREO_PCM[1:], "82"]  # starts at 82, wraps after 23 steps


def test_mode_lists_depend_on_the_signal(receiver: Receiver, clock: Clock) -> None:
    clock.now += 60
    assert receiver.handle("LMD", "0F").broadcast[0] == "LMD0F"  # allowed for PCM
    clock.now += 4
    pushed = receiver.set_signal("truehd_atmos").broadcast
    assert pushed[0] == "LMD80"  # 0F does not exist for Atmos, the receiver falls back
    assert value(receiver, "IFA") == "HDMI 1,Dolby Atmos/TrueHD,48 kHz,,Dolby Atmos,6.1 ch,"
    clock.now += 4
    assert receiver.handle("LMD", "82").replies == ["LMDN/A"]  # no Neural:X for Atmos
    assert receiver.handle("LMD", "0F").replies == ["LMDN/A"]
    assert receiver.handle("LMD", "84").replies == ["LMDN/A"]  # no THX
    assert receiver.handle("LMD", "08").broadcast[0] == "LMD08"
    clock.now += 4
    modes = []
    for _ in range(15):
        modes.append(receiver.handle("LMD", "UP").broadcast[0][3:])
        clock.now += 4
    assert len(set(modes)) == 15


def test_lmdmusic_jumps_to_the_music_group(receiver: Receiver, clock: Clock) -> None:
    clock.now += 60
    assert receiver.handle("LMD", "MUSIC").broadcast[0] == "LMD0C"


def test_set_signal_rejects_a_name_it_does_not_have(receiver: Receiver) -> None:
    with pytest.raises(ValueError, match="unknown signal"):
        receiver.set_signal("nope")


# ----- over the network ------------------------------------------------------------------------


async def poll(done: Callable[[], bool], seconds: float = 2.0) -> None:
    """Wait until ``done()`` is true (the simulator answers within milliseconds)."""
    async with asyncio.timeout(seconds):
        while not done():  # noqa: ASYNC110
            await asyncio.sleep(0.01)


class RawClient:
    """A bare TCP client that logs every message it receives."""

    def __init__(self, local: str | None = None) -> None:
        self.local = local
        self.messages: list[Message] = []
        self.parser = FrameParser()
        self.reader: asyncio.StreamReader
        self.writer: asyncio.StreamWriter
        self.task: asyncio.Task[None]

    async def connect(self, port: int) -> None:
        local = (self.local, 0) if self.local else None
        self.reader, self.writer = await asyncio.open_connection(
            "127.0.0.1", port, local_addr=local
        )
        self.task = asyncio.create_task(self._read())

    async def _read(self) -> None:
        while data := await self.reader.read(4096):
            self.messages += self.parser.feed(data)

    async def send(self, text: str) -> None:
        self.writer.write(encode(text))
        await self.writer.drain()

    def texts(self) -> list[str]:
        return [m.code + m.param for m in self.messages]

    async def wait_for(self, predicate: Callable[[list[str]], bool], seconds: float = 2.0) -> None:
        await poll(lambda: predicate(self.texts()), seconds)

    async def close(self) -> None:
        self.writer.close()
        self.task.cancel()


@pytest.fixture
async def server() -> AsyncIterator[SimServer]:
    sim = SimServer(Receiver.from_folder(FIXTURE))
    await sim.start()
    yield sim
    await sim.stop()


async def test_server_pushes_on_connect_and_answers_a_query(server: SimServer) -> None:
    client = EiscpClient("127.0.0.1", server.port)
    got: list[str] = []
    client.add_listener(lambda m: got.append(m.code + m.param))
    await client.connect()
    await client.send("PWRQSTN")
    await client.send("DSSQSTN")
    await poll(lambda: "DSS112" in got)
    assert got[0].startswith("NJA")  # the TX-RZ50 pushes NJA before any reply
    assert "PWR01" in got
    await client.close()


async def test_a_second_connection_from_the_same_host_closes_the_first(
    server: SimServer,
) -> None:
    first = EiscpClient("127.0.0.1", server.port)
    await first.connect()
    second = EiscpClient("127.0.0.1", server.port)
    await second.connect()
    async with asyncio.timeout(2):
        await first.wait_closed()
    assert second.connected
    assert server.connection_count == 1
    await second.close()


async def test_another_host_keeps_its_connection_and_gets_every_push(server: SimServer) -> None:
    here = RawClient()
    other = RawClient("127.0.0.2")
    await here.connect(server.port)
    await other.connect(server.port)
    await poll(lambda: server.connection_count == 2)
    await here.send("TFRBUP")
    await here.wait_for(lambda t: "TFRB+1T00" in t)
    await other.wait_for(lambda t: "TFRB+1T00" in t)
    assert server.connection_count == 2
    # a query answers only the asker
    await other.send("MVLQSTN")
    await other.wait_for(lambda t: "MVL4C" in t)
    await asyncio.sleep(0.1)
    assert "MVL4C" not in here.texts()
    # a signal change reaches both
    server.set_signal("truehd_atmos")
    for client in (here, other):
        await client.wait_for(lambda t: any(m.startswith("IFAHDMI 1,Dolby Atmos") for m in t))
    await here.close()
    await other.close()


async def test_many_flag_allows_several_connections_from_one_host() -> None:
    sim = SimServer(Receiver.from_folder(FIXTURE), one_per_host=False)
    await sim.start()
    a, b = RawClient(), RawClient()
    await a.connect(sim.port)
    await b.connect(sim.port)
    await a.send("PWRQSTN")
    await a.wait_for(lambda t: "PWR01" in t)
    assert sim.connection_count == 2
    await a.close()
    await b.close()
    await sim.stop()


# ----- the fixture and the sanitizer -----------------------------------------------------------

DOTTED_QUAD = re.compile(r"\d{1,3}(?:\. ?\d{1,3}){3}")
COLON_MAC = re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")
MAC_TAGS = re.compile(r"<(?:macaddress|deviceserial|deviceid)>([^<]*)<")


def fixture_texts() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in FIXTURE.iterdir() if p.is_file()}


@pytest.mark.parametrize("name", sorted(fixture_texts()))
def test_fixture_holds_no_ip_address_and_no_foreign_mac(name: str) -> None:
    text = fixture_texts()[name]
    assert not DOTTED_QUAD.findall(text)
    assert {m.replace(":", "").upper() for m in COLON_MAC.findall(text)} <= {PLACEHOLDER_MAC}
    assert set(MAC_TAGS.findall(text)) <= {PLACEHOLDER_MAC}


def test_fixture_identity_is_placeholder_only() -> None:
    nri = FIXTURE_DATA.nri
    assert "<friendlyname></friendlyname>" in nri
    assert f"<macaddress>{PLACEHOLDER_MAC}</macaddress>" in nri
    assert f"<deviceserial>{PLACEHOLDER_MAC}</deviceserial>" in nri
    assert FIXTURE_DATA.on["IFN"] == "00:09:B0:00:00:01, receiver.invalid,Onkyo Test"
    assert FIXTURE_DATA.on["NFN"] == ".Onkyo Test"
    assert FIXTURE_DATA.profile["mac"] == PLACEHOLDER_MAC
    assert FIXTURE_DATA.profile["friendly_name"] == "Onkyo Test"
    assert FIXTURE_DATA.on["NGT"] == "Etc/UTC"
    assert PLACEHOLDER_MAC in FIXTURE_DATA.on["MDI"]


def make_capture(folder: Path, mac: str, name: str, ip: str) -> None:
    colon = ":".join(mac[i : i + 2] for i in range(0, 12, 2))
    nri = (
        f"<response><device><deviceserial>{mac}</deviceserial><macaddress>{mac}</macaddress>"
        f"<modeliconurl>http://{ip}/icon.jpg</modeliconurl>"
        f"<friendlyname>{name}</friendlyname></device></response>"
    )
    (folder / "nri.xml").write_text(nri, encoding="utf-8")
    codes = {
        "PWR": {"states": {"standby": "00", "on": "01"}, "start": "01", "writes": []},
        "MVL": {"states": {"standby": "4C", "on": "7C"}, "start": "4C", "writes": []},
        "IFN": {"states": {"on": f"{colon}, {ip.replace('.', '. ')},{name}"}},
        "NFN": {"states": {"on": f".{name}"}},
        "NJA": {"states": {"on": "LINK"}},
        "TFR": {
            "states": {"on": "B00T00", "standby": "B00T00"},
            "start": "B00T00",
            "writes": [
                {
                    "param": "BUP",
                    "reply": "B+1T00",
                    "readback": "B+1T00",
                    "before": "B00T00",
                    "outcome": "changed",
                    "also": [f"NJA2-http://{ip}/a.cgi"],
                }
            ],
        },
    }
    survey = {"model": "TX-TEST", "firmware": "1", "fwv_reply": "1", "captured": "2026-01-01",
              "codes": codes}  # fmt: skip
    (folder / "survey.json").write_text(json.dumps(survey), encoding="utf-8")
    rows = [
        {"ts": "2026-01-01T10:00:00.000+00:00", "dir": "rx", "tag": "push", "code": "NJA",
         "param": f"2-http://{ip}/a.cgi\x1a\r\n", "raw": ""},
        {"ts": "2026-01-01T10:00:01.000+00:00", "dir": "tx", "tag": "set", "code": "PWR",
         "param": "00", "raw": "!1PWR00\r"},
        {"ts": "2026-01-01T10:00:02.000+00:00", "dir": "rx", "tag": "push", "code": "TGA",
         "param": "00\x1a\r\n", "raw": ""},
        {"ts": "2026-01-01T10:01:00.000+00:00", "dir": "tx", "tag": "restore", "code": "PWR",
         "param": "01", "raw": "!1PWR01\r"},
        {"ts": "2026-01-01T10:01:01.000+00:00", "dir": "rx", "tag": "push", "code": "PWR",
         "param": "01\x1a\r\n", "raw": ""},
    ]  # fmt: skip
    (folder / "session-10-power-cycle.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
    )


def test_sanitizer_replaces_mac_name_and_ip_found_in_the_capture(tmp_path: Path) -> None:
    capture, out = tmp_path / "capture", tmp_path / "fixture"
    capture.mkdir()
    make_capture(capture, "AABBCC112233", "Living Room Receiver", "192.168.7.9")
    sanitize_capture.sanitize(capture, out)
    text = "".join(p.read_text(encoding="utf-8") for p in out.iterdir())
    for private in ("AABBCC112233", "AA:BB:CC:11:22:33", "Living Room", "192.168", "7.9"):
        assert private not in text
    assert PLACEHOLDER_MAC in text
    assert "Onkyo Test" in text
    assert "receiver.invalid" in text
    assert json.loads((out / "profile.json").read_text(encoding="utf-8"))["power_off_pushes"] == [
        "TGA00"
    ]


def test_sanitizer_stops_when_a_private_value_survives(tmp_path: Path) -> None:
    capture, out = tmp_path / "capture", tmp_path / "fixture"
    capture.mkdir()
    make_capture(capture, "AABBCC112233", "Living Room Receiver", "192.168.7.9")
    scrub = sanitize_capture.Scrubber(
        (capture / "nri.xml").read_text(encoding="utf-8"),
        json.loads((capture / "survey.json").read_text(encoding="utf-8"))["codes"],
    )
    assert scrub.leftovers("host 192.168.7.9 mac aabbcc112233")
    assert not scrub.leftovers(scrub.text("host 192.168.7.9 mac aabbcc112233"))
    assert not out.exists()
