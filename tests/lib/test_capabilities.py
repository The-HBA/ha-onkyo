"""Capabilities: NRI plus the probe, against the simulated TX-RZ50, and the TX-RZ50 profile."""

import json
from typing import TYPE_CHECKING

import pytest
from lib_helpers import FIXTURE, make_sim

from custom_components.onkyo_eiscp.lib import (
    COMMANDS,
    LISTENING_MODES,
    PROFILES,
    EiscpClient,
    NoReplyError,
    capabilities,
    probe,
)
from custom_components.onkyo_eiscp.lib.codecs import parse_device_info
from custom_components.onkyo_eiscp.lib.profiles import find_profile

if TYPE_CHECKING:
    from tools.eiscp_sim import SimServer

BEHAVIOR = json.loads((FIXTURE / "behavior.json").read_text(encoding="utf-8"))
NRI = (FIXTURE / "nri.xml").read_text(encoding="utf-8")


async def probe_sim(sim: SimServer) -> capabilities.Capabilities:
    client = EiscpClient("127.0.0.1", sim.port)
    await client.connect()
    try:
        return await probe(client, spacing=0.001, settle=0.1)
    finally:
        await client.close()


async def test_probe_reads_identity_zones_and_inputs(sim: SimServer) -> None:
    caps = await probe_sim(sim)
    assert (caps.brand, caps.model, caps.mac) == ("ONKYO", "TX-RZ50", "0009B0000001")
    assert caps.firmware == "R145-1119-1284-0034-0000"
    assert [(z.id, z.name, z.volume_max, z.half_db) for z in caps.zones] == [
        ("main", "Main", 200, True),
        ("zone2", "Zone2", 200, True),
        ("zone3", "Zone3", 200, True),
    ]
    assert caps.zone("zone2") is not None
    assert caps.zone("zone4") is None
    names = {item.code: item.name for item in caps.inputs}
    assert names["10"] == "Movie"
    assert names["11"] == "Streaming"
    assert list(names)[:4] == ["10", "02", "01", "11"]  # NRI order is kept
    by_code = {item.code: item for item in caps.inputs}
    assert by_code["80"].zones == {"zone2", "zone3"}


async def test_probe_finds_what_answers(sim: SimServer) -> None:
    caps = await probe_sim(sim)
    assert {"PWR", "MVL", "SLI", "LMD", "DSS", "TFR", "SWL", "VOC", "IFA", "IFV"} <= caps.supported
    assert "SW2" in caps.supported  # N/A counts as supported (unavailable, not unknown)
    assert caps.values["SW2"] == "N/A"
    assert caps.values["DSS"] == "112"
    assert not {"NLT", "NCP", "NRI", "OSD"} & set(caps.values)  # never queried, command only
    silent = {code for code in COMMANDS if code not in caps.values and code != "NRI"}
    assert not silent & caps.supported


async def test_probe_in_standby_counts_the_standby_silent_codes(sim: SimServer) -> None:
    sim.receiver.handle("PWR", "00")
    caps = await probe_sim(sim)
    assert caps.values["PWR"] == "00"
    assert "DLC" not in caps.values  # silent in standby
    assert {"DLC", "EQS"} <= caps.supported


async def test_probe_uses_the_tx_rz50_profile(sim: SimServer) -> None:
    caps = await probe_sim(sim)
    assert len(caps.listening_modes) == 24
    assert len(caps.signal_modes["pcm"]) == 23
    assert len(caps.signal_modes["atmos"]) == 15
    assert "1F" not in caps.listening_modes
    assert caps.options["DIM"] == ("00", "01", "02")
    assert caps.options["DGF"] == ("00", "01", "03")
    assert "DSS" not in caps.options
    assert caps.options["AMT"] == ("00", "01")


async def test_probe_fails_when_nri_stays_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    sim = make_sim(power_on_quiet=0)
    await sim.start()
    sim._quiet_until = 1e18  # every query stays unanswered
    monkeypatch.setattr(capabilities, "NRI_TIMEOUT", 0.1)
    client = EiscpClient("127.0.0.1", sim.port)
    await client.connect()
    with pytest.raises(NoReplyError):
        await probe(client, spacing=0.001, settle=0.05)
    await client.close()
    await sim.stop()


def test_build_without_a_profile_offers_every_known_mode_but_whole_house() -> None:
    info = parse_device_info(NRI.replace("TX-RZ50", "TX-NR6100"))
    caps = capabilities.build(info, {"PWR": "01"})
    assert find_profile(info.model) is None
    assert caps.signal_modes == {}
    assert "1F" not in caps.listening_modes
    assert set(caps.listening_modes) == set(LISTENING_MODES)
    assert caps.options["DIM"] == ("00", "01", "02", "03", "08")


def test_build_skips_disabled_inputs_and_zones() -> None:
    info = parse_device_info(NRI)
    caps = capabilities.build(info, {})
    assert all(zone.id != "zone4" for zone in caps.zones)
    disabled = NRI.replace('id="11" value="1"', 'id="11" value="0"')
    assert "11" not in {i.code for i in capabilities.build(parse_device_info(disabled), {}).inputs}
    stepped = NRI.replace('volmax="100" volstep="0"', 'volmax="80" volstep="1"', 1)
    main = capabilities.build(parse_device_info(stepped), {}).zones[0]
    assert (main.volume_max, main.half_db) == (80, False)


# ----- profile ----------------------------------------------------------------------------


def test_tx_rz50_profile_matches_the_fixture() -> None:
    profile = PROFILES["TX-RZ50"]
    assert find_profile(" tx-rz50 ") is profile
    assert set(profile.signal_modes["pcm"]) == set(BEHAVIOR["signals"]["pcm_44k"]["modes"])
    assert set(profile.signal_modes["pcm"]) == set(BEHAVIOR["signals"]["pcm_48k"]["modes"])
    assert set(profile.signal_modes["atmos"]) == set(BEHAVIOR["signals"]["truehd_atmos"]["modes"])
    assert set(profile.listening_modes) == set(profile.signal_modes["pcm"]) | {"40"}
    assert all(code in LISTENING_MODES for code in profile.listening_modes)
    assert list(profile.listening_modes) == [
        c for c in LISTENING_MODES if c in profile.listening_modes
    ]


def _osd_keys(nri: str) -> tuple[str, ...]:
    return capabilities.build(parse_device_info(nri), {}).options["OSD"]


def test_remote_keys_follow_the_nri_controls() -> None:
    keys = _osd_keys(NRI)
    # The TX-RZ50 says Home is 0; Menu is 0 too, but Setup (also the MENU key) is 1.
    assert "HOME" not in keys
    assert {"UP", "ENTER", "EXIT", "MENU", "QUICK"} <= set(keys)
    # The TX-RZ50 profile drops AUDIO and VIDEO (they do nothing on that model).
    assert not {"AUDIO", "VIDEO"} & set(keys)


def test_remote_keys_keep_home_when_nri_allows_it_or_says_nothing() -> None:
    assert "HOME" in _osd_keys(NRI.replace('id="Home" value="0"', 'id="Home" value="1"'))
    assert "HOME" in _osd_keys(
        NRI.replace('<control id="Home" value="0" code="HOME" position="2" />', "")
    )


def test_remote_keys_drop_what_nri_switches_off() -> None:
    off = NRI.replace('id="Cursor" value="1"', 'id="Cursor" value="0"').replace(
        'id="Setup" value="1"', 'id="Setup" value="0"'
    )
    keys = _osd_keys(off)
    assert not {"UP", "DOWN", "LEFT", "RIGHT", "ENTER", "MENU"} & set(keys)
    assert {"EXIT", "QUICK"} <= set(keys)
